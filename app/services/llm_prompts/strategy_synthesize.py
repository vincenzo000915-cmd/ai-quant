"""Phase 14k-45 L3 + 14k-57: 动态策略合成 — AI 实时合成 buy/sell signal_fn 代码.

工作流:
  1. 输入: market_brief + balance + target_pct + days_remaining (+ 14k-57: few-shot + retry)
  2. LLM 输出 Python signal_fn 代码 + risk_params
  3. 写进 strategy_candidates (status='translated')
  4. candidate_sandbox.validate → walk-forward → 过门槛 promote
  5. AI 自己生成"为这个具体市场 + 目标 量身定制"的策略, 不是从 catalog 选

14k-57: 修 zero-shot 烂的问题
  - 加 few-shot examples (catalog 5 个 verified sharpe>2 signal_fn 作模板)
  - retry feedback: 第一次 backtest 不过 → 拿 metrics 给 LLM 重写第二版
"""
from __future__ import annotations

import hashlib
import json

from app.services.llm_provider import call_llm


def _get_few_shot_examples(target_timeframe: str | None = None, max_n: int = 3) -> list[dict]:
    """14k-57: 拉 catalog 池子 verified_oos_sharpe >= 2 的 signal_fn 代码作 few-shot.
    优先匹配 target_timeframe 的 catalog. 返回 [{candidate_type, signal_code, verified_oos_sharpe, rationale}, ...]
    """
    try:
        from app.models import StrategyCandidate
        q = StrategyCandidate.query.filter_by(source='catalog', status='qualified')
        cands = q.all()
        # Python 端按 verified_oos_sharpe 排序 (避免 JSON path SQL 兼容问题)
        scored = []
        for c in cands:
            cm = c.catalog_meta or {}
            v = cm.get('verified_oos_sharpe')
            if v is None or float(v) < 1.5:
                continue
            if not c.parsed_signal:
                continue
            tf_match = (target_timeframe and c.timeframe == target_timeframe)
            scored.append({
                'candidate_type': c.candidate_type,
                'signal_code': c.parsed_signal,
                'verified_oos_sharpe': float(v),
                'description': cm.get('description', ''),
                'timeframe': c.timeframe,
                'tf_match': tf_match,
            })
        # 优先 TF 匹配的, 然后 sharpe 高的
        scored.sort(key=lambda x: (not x['tf_match'], -x['verified_oos_sharpe']))
        return scored[:max_n]
    except Exception:
        return []

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
                        user_id: int = 1, hint: str | None = None,
                        target_timeframe: str | None = None) -> dict:
    """LLM 根据当前市场 + user 目标合成 signal_fn.

    14k-49: hint + target_timeframe 让 invent meta-trigger 给 LLM 强方向
    14k-57: few-shot examples (catalog 优秀模板) — 仍保留, 这是真改进
    14k-61: 撤回 retry loop (brief 没变 LLM 答案差不多, 浪费 token).
      失败就 4h cooldown 等下次 brief 变化重新触发, 别原地轮回.

    Returns: {'ok', 'signal_fn_name', 'signal_code', 'default_params', 'risk_params',
              'category', 'timeframe', 'rationale_zh', 'rationale_en'} or {'ok': False, 'error'}
    """
    if not market_brief:
        return {'ok': False, 'error': 'market_brief 必填'}

    # 仅在 brief 推荐有效 archetype 时合成 (wait 不合成)
    # — 但 hint='dry_spell' 时强制合成 (系统干旱期, 不管 brief 判 wait)
    archetype = market_brief.get('recommended_archetype')
    if archetype == 'wait' and hint != 'dry_spell':
        return {'ok': False, 'error': 'AI brief 判 wait, 不合成新策略'}
    # 14k-61: 删除 prev_attempt_feedback dead code 参数 (上面 signature 不再接收)

    # 14k-57: few-shot examples 让 LLM 看 catalog 优秀 signal_fn 风格
    few_shot_block = ''
    examples = _get_few_shot_examples(target_timeframe=target_timeframe, max_n=3)
    if examples:
        ex_lines = []
        for i, ex in enumerate(examples, 1):
            ex_lines.append(f"### 例 {i}: {ex['candidate_type']} ({ex['timeframe']}, "
                           f"verified OOS Sharpe {ex['verified_oos_sharpe']:.2f})")
            if ex.get('description'):
                ex_lines.append(f"思路: {ex['description'][:120]}")
            ex_lines.append('```python')
            # 截断过长 signal_code (LLM context 节省)
            code = ex['signal_code'][:1200]
            ex_lines.append(code)
            ex_lines.append('```\n')
        few_shot_block = ('\n## 优秀 signal_fn 参考 (catalog 验证 sharpe ≥ 1.5 的)\n'
                          '**学这些风格的简洁度 + 信号严谨度, 不要发散瞎写**\n\n'
                          + '\n'.join(ex_lines))

    # 14k-61: retry_block 删了 — 同 brief 同 prompt 让 LLM 改写, 实际答案差不多, 烧 token 无意义
    hint_block = ''
    if hint:
        hint_messages = {
            'dry_spell': '⚠️ 系统连续多日 0 入场, 现有策略阈值过严. 请合成**高频**策略 (15m/30m scalp / reversion), '
                         'signal 触发率每根 K 线 ≥ 5%, 不要选 breakout (低频).',
            'tf_gap': f'⚠️ catalog 池 {target_timeframe or "15m/30m"} 候选完全空白. '
                      f'**必须** timeframe = "{target_timeframe or "15m"}", 找适合短 TF 的策略类型 '
                      f'(RSI/BB scalp, VWAP pullback, EMA crossover scalp).',
            'regime_mismatch': '⚠️ 当前 running 策略类型跟市场 regime 不匹配 (eg 横盘但全 trend). '
                               '请合成跟现有组合 **互补** archetype 的策略.',
            'lag_pool_thin': '⚠️ 账户目标进度落后 + 候选池稀薄. 高 Sharpe trend/breakout 优先, 4h 偏中长期.',
        }
        msg = hint_messages.get(hint, '')
        if msg:
            hint_block = f'\n## 触发上下文 / Context\n{msg}\n'

    tf_constraint = ''
    if target_timeframe:
        tf_constraint = f'\n**timeframe 强制要求**: "{target_timeframe}" (不能选其他 TF)\n'

    prompt = f"""## 市场 brief
{json.dumps(market_brief, ensure_ascii=False, indent=2)}

## 用户参数
- 交易对 / Symbol: {symbol}
- 余额 / Balance: ${balance:.2f}
- 目标 / Target: +{target_pct}% / {days_remaining} 天剩
- 月化等价: {((1 + target_pct/100) ** (30.0/max(1, days_remaining)) - 1) * 100:.1f}%
{hint_block}{tf_constraint}{few_shot_block}

请合成一个**针对当前市场 + 用户目标的实时 signal_fn**, 输出 JSON.
"""

    sig_key = hashlib.sha256(
        json.dumps([symbol, target_pct, days_remaining, archetype,
                    market_brief.get('regime'), hint, target_timeframe],
                   sort_keys=True).encode()
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
