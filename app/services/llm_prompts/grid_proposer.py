"""Phase 14k-30 #2: AI 提议信号 grid (LLM)

让 LLM 看策略类型 + 当前 params + 最近表现, 输出搜哪些参数 + 搜什么值的 grid.
比死字典 GRIDS 更"主动" — AI 可以根据策略和市场表现微调搜索方向.
"""
from __future__ import annotations

import hashlib
import json

from app.services.llm_provider import call_llm

SYSTEM_PROMPT = """你是量化策略调参顾问。User 给你策略类型 + 当前参数 + 最近回测 metrics, 请输出**严格 JSON** grid (不要 markdown, 不要解释).

输出 schema:
{
  "grid": {
    "param_name": [v1, v2, v3, ...],
    ...
  },
  "rationale": "一段中文 (100 字内) 说明搜索方向"
}

约束:
- grid 字段名必须是策略类型已有的 params (不能新增字段)
- 每个 param 给 3-4 个候选值, 围绕当前值 ±50% 内做探索
- 总组合数 (各 list 长度连乘) ≤ 12 (避免回测过慢)
- 数字必须是 number 不是字符串
- 围绕当前 params 探索, 不要离太远"""


def propose_signal_grid(strategy_type: str, current_params: dict,
                        recent_metrics: dict, user_id: int = 1) -> dict:
    """LLM 提议 grid.

    recent_metrics: {'oos_sharpe', 'oos_dd', 'win_rate', 'trades', ...}
    Returns: {'ok': bool, 'grid': dict, 'rationale': str} or {'ok': False, 'error': str}
    """
    # 剔除 risk_params + 内部 _xxx 字段, 只保留信号参数
    sig_params = {k: v for k, v in (current_params or {}).items()
                  if k != 'risk_params' and not k.startswith('_')}
    if not sig_params:
        return {'ok': False, 'error': '当前 params 无信号参数可调'}

    prompt = f"""## 策略类型
{strategy_type}

## 当前信号参数
{json.dumps(sig_params, ensure_ascii=False)}

## 最近回测 metrics
- OOS Sharpe: {recent_metrics.get('oos_sharpe')}
- OOS Max DD: {recent_metrics.get('oos_dd')}%
- OOS Win Rate: {recent_metrics.get('win_rate')}%
- OOS Trades: {recent_metrics.get('trades')}

请输出 grid JSON, 在当前 params 周围探索更好组合 (总组合 ≤ 12)."""

    sig_key = hashlib.sha256(json.dumps([strategy_type, sig_params, recent_metrics],
                                        sort_keys=True, default=str).encode()).hexdigest()[:20]
    r = call_llm(
        user_id=user_id,
        prompt=prompt,
        system=SYSTEM_PROMPT,
        max_tokens=600,
        cache_key=f'grid_propose:{sig_key}',
    )
    if not r.get('ok'):
        return {'ok': False, 'error': r.get('error', 'LLM 失败')}

    try:
        from app.services.llm_prompts.strategy_generate import _extract_json
        spec = _extract_json(r['text'])
        if not spec or 'grid' not in spec:
            return {'ok': False, 'error': 'LLM 输出缺 grid 字段', 'raw': r.get('text', '')[:300]}
        grid = spec['grid']
        if not isinstance(grid, dict) or not grid:
            return {'ok': False, 'error': 'grid 非 dict 或空'}
        # 守: 字段必须是 sig_params 已有的 key
        rejected = [k for k in grid if k not in sig_params]
        if rejected:
            return {'ok': False, 'error': f'grid 包含非法字段: {rejected}'}
        # 守: 组合数不能超
        combos = 1
        for vs in grid.values():
            if not isinstance(vs, list) or not vs:
                return {'ok': False, 'error': f'grid 字段值非 list: {vs}'}
            combos *= len(vs)
        if combos > 12:
            return {'ok': False, 'error': f'组合数 {combos} > 12'}
        return {
            'ok': True,
            'grid': grid,
            'rationale': spec.get('rationale', ''),
            'llm_meta': {
                'provider_used': r.get('provider_used'),
                'model_used': r.get('model_used'),
                'cached': r.get('cached'),
            },
        }
    except Exception as e:
        return {'ok': False, 'error': f'{type(e).__name__}: {e}'}
