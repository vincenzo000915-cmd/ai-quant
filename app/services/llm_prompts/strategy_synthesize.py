"""Phase 14k-45 L3: 动态策略合成 — AI 实时合成 buy/sell signal_fn 代码.

工作流:
  1. 输入: market_brief + balance + target_pct + days_remaining
  2. LLM 输出 Python signal_fn 代码 + risk_params
  3. 写进 strategy_candidates (status='translated')
  4. candidate_sandbox.validate → walk-forward → 过门槛 promote
  5. AI 自己生成"为这个具体市场 + 目标 量身定制"的策略, 不是从 catalog 选
"""
from __future__ import annotations

import hashlib
import json

from app.services.llm_provider import call_llm

SYSTEM_PROMPT = """你是顶级量化交易员 + Python 工程师. 看市场 brief + 用户目标, 写出**实时最匹配**的 signal_fn 代码 + risk_params.

输出 **严格 JSON** (无 markdown):
{
  "signal_fn_name": "synth_<short_id>_signal",
  "signal_code": "def synth_<id>_signal(df, params):\\n    ...\\n    return 'buy'/'sell'/'hold'",
  "default_params": {<参数 dict, 必须可在 params 里覆盖>},
  "risk_params": {"leverage": 1-10, "sl_pct": 1-15, "tp_pct": 2-30, "order_type": "market"},
  "category": "long" | "short" | "swing" | "ultra",
  "timeframe": "15m" | "1h" | "4h",
  "rationale_zh": "1-2 句中文说明为什么这个 signal_fn 适合当下市场",
  "rationale_en": "1-2 sentence English rationale"
}

signal_fn 约束:
- 必须签名 (df: pd.DataFrame, params: dict) → str
- df 列: open, high, low, close, volume, timestamp (升序)
- 只能用 ta, pandas, numpy (不能 import 别的)
- 返回 'buy' / 'sell' / 'hold'
- 长度 < 50 行, 简单可读, 不要 try/except 包整段
- 用 params.get() 取阈值参数 + 默认值

risk_params 约束:
- 必须 leverage / sl_pct / tp_pct / order_type 都填
- 跟 brief.recommended_archetype 一致 (trend → 长 SL 短 TP, reversion → 短 SL 等)

category 选择:
- timeframe 1d → long, 1h → short (短线), 4h → swing, 15m → ultra
- 跟 brief.regime 配合 (range → mean_reverter 类, trending → trend_follower)
"""


def synthesize_strategy(market_brief: dict, symbol: str, balance: float,
                        target_pct: float, days_remaining: int,
                        user_id: int = 1) -> dict:
    """LLM 根据当前市场 + user 目标合成 signal_fn.

    Returns: {'ok', 'signal_fn_name', 'signal_code', 'default_params', 'risk_params',
              'category', 'timeframe', 'rationale_zh', 'rationale_en'} or {'ok': False, 'error'}
    """
    if not market_brief:
        return {'ok': False, 'error': 'market_brief 必填'}

    # 仅在 brief 推荐有效 archetype 时合成 (wait 不合成)
    archetype = market_brief.get('recommended_archetype')
    if archetype == 'wait':
        return {'ok': False, 'error': 'AI brief 判 wait, 不合成新策略'}

    prompt = f"""## 市场 brief
{json.dumps(market_brief, ensure_ascii=False, indent=2)}

## 用户参数
- 交易对 / Symbol: {symbol}
- 余额 / Balance: ${balance:.2f}
- 目标 / Target: +{target_pct}% / {days_remaining} 天剩
- 月化等价: {((1 + target_pct/100) ** (30.0/max(1, days_remaining)) - 1) * 100:.1f}%

请合成一个**针对当前市场 + 用户目标的实时 signal_fn**, 输出 JSON.
"""

    sig_key = hashlib.sha256(
        json.dumps([symbol, target_pct, days_remaining, archetype,
                    market_brief.get('regime')], sort_keys=True).encode()
    ).hexdigest()[:20]

    r = call_llm(
        user_id=user_id, prompt=prompt, system=SYSTEM_PROMPT,
        max_tokens=2500,
        cache_key=f'synth:{sig_key}',
    )
    if not r.get('ok'):
        return {'ok': False, 'error': r.get('error', 'LLM 失败')}

    try:
        from app.services.llm_prompts.strategy_generate import _extract_json
        spec = _extract_json(r['text'])
        if not spec:
            return {'ok': False, 'error': 'LLM 输出无法解析为 JSON', 'raw': r.get('text', '')[:300]}
        # 守 schema
        required = {'signal_fn_name', 'signal_code', 'default_params', 'risk_params',
                    'category', 'timeframe', 'rationale_zh', 'rationale_en'}
        missing = required - set(spec.keys())
        if missing:
            return {'ok': False, 'error': f'LLM 输出缺字段: {sorted(missing)}'}
        # 简单 sandbox 安全 (不能 import 危险模块)
        code = spec['signal_code']
        forbidden = ['os.', 'sys.', 'subprocess', '__import__', 'eval(', 'exec(', 'open(']
        if any(f in code for f in forbidden):
            return {'ok': False, 'error': '代码含禁用 import / eval'}
        return {'ok': True, **spec, 'symbol': symbol,
                'llm_meta': {
                    'provider_used': r.get('provider_used'),
                    'model_used': r.get('model_used'),
                    'cached': r.get('cached'),
                }}
    except Exception as e:
        return {'ok': False, 'error': f'{type(e).__name__}: {e}'}
