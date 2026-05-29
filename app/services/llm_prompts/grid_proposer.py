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
    "_lev": [3, 5, 7],          // (可选) 杠杆候选
    "_sl": [4, 6, 8],           // (可选) 止损% (杠杆后 PnL%)
    "_tp": [10, 14]             // (可选) 止盈% (杠杆后 PnL%)
  },
  "rationale": "一段中文 (100 字内) 说明搜索方向"
}

约束:
- 信号 grid 字段名必须是策略类型已有的 params (不能新增字段)
- **可选搜风险参数**: 用保留键 _lev (杠杆) / _sl (止损%) / _tp (止盈%) 搜索风险组合
- **关键**: SL 是"杠杆后 PnL%", 有效价格止损距离 = _sl / _lev。务必确保 _sl/_lev >= 0.8
  (否则价格小波动就被止损扫掉)。如 _lev=10 则 _sl 至少 8; _lev=3 则 _sl 至少 2.5。
- TP 至少是 SL 的 1.2 倍 (R:R 守门)
- 每个 param 给 2-4 个候选值
- 总组合数 (所有 list 长度连乘, **含风险维**) ≤ 24
- 数字必须是 number 不是字符串
- 围绕当前值探索, 不要离太远"""


def _grid_combos(g: dict) -> int:
    n = 1
    for v in g.values():
        n *= len(v)
    return n


def _shrink_grid(grid: dict, max_combos: int = 24) -> dict:
    """14k-148 (D3): 把 LLM 提议的 grid 收敛到 ≤max_combos. 风险维(_lev/_sl/_tp)优先全留,
    信号维按值少→多贪心填充. 每维值先 trim 到 ≤3. 防 LLM 提太多维度炸组合."""
    from app.services.param_optimizer import RISK_GRID_KEYS
    risk = {k: list(v)[:3] for k, v in grid.items() if k in RISK_GRID_KEYS}
    sig = {k: list(v)[:3] for k, v in grid.items() if k not in RISK_GRID_KEYS}
    out = dict(risk)
    # 风险维本身超额 → 砍值到 2
    while _grid_combos(out) > max_combos:
        longest = max(out, key=lambda k: len(out[k]))
        if len(out[longest]) <= 2:
            break
        out[longest] = out[longest][::2]
    # 信号维按值少→多贪心加入 (组合不超 max_combos)
    for k, v in sorted(sig.items(), key=lambda x: len(x[1])):
        if _grid_combos({**out, k: v}) <= max_combos:
            out[k] = v
    return out


def propose_signal_grid(strategy_type: str, current_params: dict,
                        recent_metrics: dict, user_id: int = 1) -> dict:
    """LLM 提议 grid.

    recent_metrics: {'oos_sharpe', 'oos_dd', 'win_rate', 'trades', ...}
    Returns: {'ok': bool, 'grid': dict, 'rationale': str} or {'ok': False, 'error': str}
    """
    # 剔除 risk_params + 内部 _xxx 字段, 只保留信号参数
    sig_params = {k: v for k, v in (current_params or {}).items()
                  if k != 'risk_params' and not k.startswith('_')}
    # 14k-148 (D3): 当前风险参数喂 LLM (供风险维探索). sig_params 空也 OK —
    # 信号固定的 catalog clone (如 ttm/squeeze) 只能靠风险维优化, 不再 return error.
    rp = (current_params or {}).get('risk_params') or {}
    cur_risk = {
        '_lev': rp.get('leverage'),
        '_sl': rp.get('stop_loss_pct') or rp.get('sl_pct'),
        '_tp': rp.get('take_profit_pct') or rp.get('tp_pct'),
    }
    if not sig_params and not any(cur_risk.values()):
        return {'ok': False, 'error': '当前 params 无信号参数也无风险参数可调'}

    prompt = f"""## 策略类型
{strategy_type}

## 当前信号参数
{json.dumps(sig_params, ensure_ascii=False) if sig_params else '(此策略信号参数固定, 只能调风险参数 _lev/_sl/_tp)'}

## 当前风险参数
- 杠杆 _lev: {cur_risk['_lev']}
- 止损 _sl (杠杆后%): {cur_risk['_sl']}
- 止盈 _tp (杠杆后%): {cur_risk['_tp']}

## 最近回测 metrics
- OOS Sharpe: {recent_metrics.get('oos_sharpe')}
- OOS Max DD: {recent_metrics.get('oos_dd')}%
- OOS Win Rate: {recent_metrics.get('win_rate')}%
- OOS Trades: {recent_metrics.get('trades')}

请输出 grid JSON, 在当前 params 周围探索更好组合 (信号维+可选风险维, 总组合 ≤ 24)。
若 OOS 差且止损常被扫, 重点搜 _sl/_lev 让有效价格止损 (_sl/_lev) 更合理。"""

    sig_key = hashlib.sha256(json.dumps([strategy_type, sig_params, cur_risk, recent_metrics],
                                        sort_keys=True, default=str).encode()).hexdigest()[:20]
    r = call_llm(
        user_id=user_id,
        prompt=prompt,
        system=SYSTEM_PROMPT,
        max_tokens=600,
        cache_key=f'grid_propose:v2:{sig_key}',   # v2: 14k-148 含风险维, 避免命中旧格式缓存
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
        # 守: 信号键必须 ∈ sig_params; 风险键必须 ∈ {_lev,_sl,_tp} (14k-148 D3)
        from app.services.param_optimizer import RISK_GRID_KEYS
        rejected = [k for k in grid if k not in sig_params and k not in RISK_GRID_KEYS]
        if rejected:
            return {'ok': False, 'error': f'grid 包含非法字段: {rejected}'}
        # 守: 字段值必须 list
        for k, vs in grid.items():
            if not isinstance(vs, list) or not vs:
                return {'ok': False, 'error': f'grid 字段值非 list: {vs}'}
        # 14k-148 (D3): LLM 常不守组合数约束 (提了 6 维 64 组合). 自动收敛而非拒绝:
        # 风险维优先全留 (D 核心), 信号维贪心填充, 总组合 ≤ 24. (optimize 还会再 trim 到 48)
        grid = _shrink_grid(grid)
        if not grid:
            return {'ok': False, 'error': 'grid 收敛后为空'}
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
