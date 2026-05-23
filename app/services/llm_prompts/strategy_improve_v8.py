"""Phase 12.42 v8: AI improve 完整量化分析师 — 多 symbol + 多 TF + risk_params + smart feedback

vs v7 升级（保持 2-phase 结构）：
  1. **15m 加入 TARGET_TFS** — 短线层不再缺
  2. **Multi-symbol universe** — AVAX + BTC + ETH + SOL，LLM 选 where edge is
  3. **AI 推荐 risk_params** — leverage/SL/TP/position_size，跟 signal logic 一起出
  4. **Smart iteration feedback** — SL hit% / win-loss ratio / freq calibration
  5. **Graceful no-edge output** — 接受「今日无好机会」诚实失败
  6. **Compact stats grid** — 8 symbols × 5 TFs 但 one-line per (sym,tf)
"""
from __future__ import annotations

import datetime
import json
from typing import Any

from app.extensions import db
from app.models import Strategy, StrategyCandidate, BacktestResult
from app.services.exchange_service import fetch_ohlcv_history
from app.services.llm_provider import call_llm
from app.services.llm_prompts.strategy_generate import SANDBOX_API_DOC, _extract_json
from app.services.strategy_research import (
    pull_profitable_references,
    pull_builtin_strategy_refs,
    pull_translated_candidate_refs,
    compute_symbol_stats,
    quick_backtest,
    self_test_passes,
    TF_GATES,
)
from app.services.user_scope import scoped_query

# Phase 12.42 v8: 5 TFs + 4 symbol universe
TARGET_TFS = ['15m', '30m', '1h', '4h', '1d']
SYMBOL_UNIVERSE_BASE = ['AVAX/USDT', 'BTC/USDT', 'ETH/USDT', 'SOL/USDT']
CANDLE_LIMIT_BY_TF = {'15m': 1500, '30m': 1500, '1h': 1500, '4h': 1500, '1d': 1000, '1w': 500}
ALLOWED_TOOLS = ['WebSearch', 'WebFetch']
RESEARCH_PHASE_TIMEOUT = 480
GENERATE_PHASE_TIMEOUT = 720


RESEARCH_SYSTEM_PROMPT = """你是量化研究员。**任务**: 调研外部资源找当前对多个 crypto symbols 有效的交易模式。

# 工具

WebSearch + WebFetch。

# 严格约束

- 最多 6 次 WebSearch、4 次 WebFetch（防超时）
- 优先源: GitHub、QuantConnect、Medium、Investopedia、TradingView 公开 idea
- 不要瞎编 URL — 用真实搜索结果

# 调研重点

跨 4 个 symbol（AVAX / BTC / ETH / SOL），针对 5 个 TF（15m / 30m / 1h / 4h / 1d）：

1. 最近 12 月被讨论的有效 indicator 组合 + 配合的 risk params (leverage / SL / TP)
2. 当前各 symbol regime 下哪种 logic 实际工作
3. 社区报告的真实 backtest 数字（剔除明显过拟合）
4. risk params 经验：mean-rev 用低杠杆 + 宽 SL / 趋势用中等杠杆 + trailing / 突破用动态 SL
5. 不同 TF 适配方向（15m 必须 breakout；1d 适合 regime-shift；4h 多种皆可）

# 输出格式

返回**严格 markdown**（不是 JSON），结构：

## 外部研究 summary

### 整体趋势观察
- (2-3 句关键 insight，跨 symbol 对比)

### Per-symbol regime 观察
- **AVAX**: ...
- **BTC**: ...
- **ETH**: ...
- **SOL**: ...

### 被讨论的有效模式 (与 risk params)

1. **Pattern A** — [来源 URL] (适配 symbol/TF)
   - Indicator 组合: ...
   - 推荐 risk: leverage X / SL Y% / TP Z%
   - 报告 backtest 数字: ...
   - 关键警告: ...

2. **Pattern B** ...

3. **Pattern C** ...

### 跨 symbol 缺口
- 哪些 symbol × TF 组合社区研究最多 / 哪些被忽视
- 当前 user (AVAX-only) 没有覆盖的 alpha 方向

**不要写代码**，下一阶段才写候选。
**不要返回 JSON**。
"""


GENERATE_SYSTEM_PROMPT = f"""你是 in-house 量化研究员 + 风险管理者。
你写的不只是 signal 函数，还要决定**杠杆 / 止损 / 止盈 / 仓位** — 因为不同策略需要不同 risk profile。

# 🔬 工作流

## Step 1: 看 Phase A 外部调研 summary（user prompt 给）
**必须**在 rationale 里引用 Phase A 的至少一条 pattern 或观察。

## Step 2: 学三层 internal references
- DB profitable: user 现有已盈利策略（最权威，含 source）
- Built-in 20 catalog: 系统内置 vetted patterns (only type+summary, source 引用即用)
- Translated candidates: GitHub 爬取 + AI 历史候选

## Step 3: 看 symbol_stats grid (4 symbols × 5 TFs)
**选择 where edge is** — 不要执着 user 现有 symbol。看哪个 (symbol, TF) 的 regime 适合你想写的 logic：
- 高 Hurst (>0.5) → 趋势跟随好
- 低 Hurst (<0.4) → mean-rev 好
- 高 ADX 高频 → breakout 好
- BB width 极宽 → 高波动，scalping fee 吃光
- 价格离 swing high/low 远 → mean-rev 容易，离近 → breakout 容易

## Step 4: 写候选 + **AI 推荐 risk_params**

每个 candidate 必须包含 risk_params:
```
"risk_params": {{
  "leverage": 5,                // 1-15 (user max = 15)
  "position_size_usdt": 6,      // 单笔 USDT，建议 5-10 (user 当前 $73)
  "stop_loss_pct": 6,           // 2-15
  "take_profit_pct": 12,        // 3-30
  "reasoning": "mean-rev 边际利润小，5x 杠杆 + 宽 SL 6% 避免 whipsaw 一笔损 50%"
}}
```

**Risk params 推荐准则**：

| Strategy type | leverage | SL | TP | reasoning |
|---|---|---|---|---|
| Mean-rev (高频/低利) | 3-5x | 5-8% (宽) | 6-12% | 每笔利润小，被 SL 一刀就清光 → 低杠杆 + 宽 SL |
| Trend follow (中长) | 5-10x | 4-6% | 10-20% | 信号确认后大波段，杠杆放大收益 |
| Breakout (动量) | 5-8x | 3-5% (紧) | 8-15% | 假突破多 → 紧 SL 快速止损 |
| Scalping (15m) | 2-4x | 1.5-3% | 2-5% | fee 吃光，杠杆低控制单笔损益 |

## Step 5: Quick_backtest 自测 → 反馈
- 系统自动跑 walk-forward + 你的 risk_params
- 回 IS/OOS Sharpe/PF/trades/AR + **trade_patterns** (SL hit% / win_loss_ratio / avg_bars_held)
- 失败时反思**根因**：SL 太紧？trades 太少？win/loss 比错？
- 不只是改阈值 — 改 architectural choice

# 🚪 自测门槛（per TF）

| TF      | OOS Sharpe | PF    | Trades | AR/年 |
|---------|-----------|-------|--------|-------|
| 15m     | ≥ 1.5     | ≥ 1.5 | ≥ 60   | ≥ 8%  |
| 30m     | ≥ 1.5     | ≥ 1.5 | ≥ 50   | ≥ 8%  |
| 1h      | ≥ 1.5     | ≥ 1.4 | ≥ 40   | ≥ 7%  |
| 4h      | ≥ 1.5     | ≥ 1.4 | ≥ 30   | ≥ 7%  |
| 1d      | ≥ 1.5     | ≥ 1.3 | ≥ 12   | ≥ 5%  |

外加 `decay_pct ≤ 70%`，**SL hit_pct ≤ 60%**（高 SL hit 说明 SL/leverage 配比错）。

# 🪙 Symbol 必填，只从 SYMBOL_UNIVERSE 选

```
SYMBOL_UNIVERSE = ['AVAX/USDT', 'BTC/USDT', 'ETH/USDT', 'SOL/USDT']
```

不限于 user 当前 running 的 symbol — go where edge is。

# 🛑 Graceful no-edge 输出（**重要**）

如果你认为所有 (symbol, TF) 组合都没好 edge，**不要硬凑**。输出：

```json
{{
  "no_edge_today": true,
  "reason": "AVAX/BTC/ETH/SOL 全 Hurst<0.5 但 4h+ ADX<25，趋势/反转都没 alpha；当前 fee 环境下 PF<1.4 必然",
  "recommendations": [
    "等 regime 切换（再试 daily cron）",
    "降低 self-test 阈值看 OOS Sharpe 1.0-1.5 之间是否有"
  ],
  "analysis": "为什么本次跳过"
}}
```

诚实 0 输出 > 硬凑 3 个 OOS=-5 的垃圾。

# 🛑 绝不做的

- 不要无视 Phase A research / symbol_stats
- 不要在 iteration 1 时重复 iter 0 的 logic（看 trade_patterns 真正诊断根因）
- 不要忽视 risk_params — signal 写完后必填
- 不要 `import os|sys|subprocess|socket`，不要无限循环

{SANDBOX_API_DOC}

# 输出格式 (JSON)

```
{{
  "analysis": "缺口诊断 + 选 symbol/TF 理由",
  "candidates": [
    {{
      "candidate_type": "snake_case_slug",
      "signal_fn_name": "..._signal",
      "symbol": "BTC/USDT (from SYMBOL_UNIVERSE)",
      "category": "short|swing|long",
      "timeframe": "15m|30m|1h|4h|1d",
      "default_params": {{}},
      "parsed_signal": "def ..._signal(df, params): ...",
      "risk_params": {{
        "leverage": 5,
        "position_size_usdt": 6,
        "stop_loss_pct": 6,
        "take_profit_pct": 12,
        "reasoning": "..."
      }},
      "rationale": "为什么 strategy + symbol + TF + risk_params 这组合 — 引用 Phase A pattern + symbol_stats 实数据",
      "external_source": "Phase A 哪条 URL/pattern 启发了你",
      "internal_ref": "内部 ref 哪个 type 最相关",
      "self_estimate": {{
        "expected_oos_sharpe": 1.6,
        "expected_oos_pf": 1.5,
        "expected_oos_trades": 35,
        "expected_oos_ar_pct": 8,
        "reasoning_for_estimate": "..."
      }}
    }}
  ]
}}
```

或者 graceful no-edge:
```
{{ "no_edge_today": true, "reason": "...", "recommendations": [...], "analysis": "..." }}
```

# 候选数量

User 要 N 个 — 只交你有信心过自测的（0 也行）。
**Quality >>> quantity**。
"""


def _format_refs_block(profitable: list, builtin: list, translated: list) -> str:
    """三层 refs 紧凑格式"""
    parts = []
    parts.append('### 📊 DB profitable (含源码)')
    if not profitable:
        parts.append('  (空 — 还没 OOS Sharpe ≥1 的 reference)')
    else:
        for r in profitable:
            m = r['metrics']
            parts.append(
                f'  - `{r["type"]}` ({r["symbol"]}/{r["timeframe"]}): OOS Sharpe={m["oos_sharpe"]} PF={m["oos_pf"]} '
                f'trades={m["oos_trades"]} (IS Sharpe={m["is_sharpe"]} decay={m.get("decay_pct")}%)'
            )
            if r.get('parsed_signal'):
                parts.append(f'    ```python\n    {r["parsed_signal"][:500]}\n    ```')

    parts.append('\n### 📚 Built-in catalog (20 patterns - 仅 type+summary)')
    for r in builtin:
        parts.append(f'  - `{r["type"]}` ({r["category"]}): {r["summary"]}')

    parts.append('\n### 🌱 Translated candidates (top 3 含源码)')
    if not translated:
        parts.append('  (空)')
    else:
        for i, r in enumerate(translated):
            parts.append(
                f'  - `{r["type"]}` ({r.get("category", "?")}/{r.get("timeframe", "?")}) from {r["source"]}'
            )
            if i < 3 and r.get('fn_source'):
                parts.append(f'    ```python\n    {r["fn_source"][:400]}\n    ```')
    return '\n'.join(parts)


def _format_symbol_stats_compact(symbol_stats: dict) -> str:
    """v8: 紧凑 grid 格式 — 每 (sym, tf) 一行 / 多 symbol 比较友好"""
    lines = ['### Symbol × TF grid (one line each)']
    lines.append('| sym/tf | regime | RSI now | MACD hist | Stoch K | ADX | BB-w | ATR% | EMA50>200% | Fib-pos |')
    lines.append('|---|---|---|---|---|---|---|---|---|---|')
    for key, payload in symbol_stats.items():
        if 'error' in payload:
            lines.append(f'| {key} | ERROR | - | - | - | - | - | - | - | - |')
            continue
        s = payload.get('stats', {})
        regime = (payload.get('regime') or {}).get('regime', '?')
        rsi = (s.get('rsi14') or {}).get('now', '?')
        macd_hist = (s.get('macd_12_26_9') or {}).get('hist_now', '?')
        stoch_k = (s.get('stoch14') or {}).get('k_now', '?')
        adx = (s.get('adx14') or {}).get('now', '?')
        bb_w = (s.get('bb20') or {}).get('width_now', '?')
        atr_pct = (s.get('atr14') or {}).get('pct_of_price_now', '?')
        ema_align = (s.get('trend') or {}).get('ema50_above_ema200_pct', '?')
        fib_pos = (s.get('fib_last_200bars') or {}).get('current_pct_of_range', '?')
        lines.append(
            f'| {key} | {regime} | {rsi} | {macd_hist} | {stoch_k} | {adx} | {bb_w} | {atr_pct}% | {ema_align}% | {fib_pos}% |'
        )

    # 也保留 1 个详细 (per symbol 最 active TF) 给参考
    lines.append('\n### Detailed pct分布 (用来估频率)')
    seen_symbols = set()
    for key, payload in symbol_stats.items():
        if 'error' in payload:
            continue
        sym = key.split('@')[0]
        if sym in seen_symbols:
            continue
        seen_symbols.add(sym)
        s = payload.get('stats', {})
        rsi = s.get('rsi14') or {}
        macd = s.get('macd_12_26_9') or {}
        stoch = s.get('stoch14') or {}
        adx = s.get('adx14') or {}
        lines.append(
            f'- **{sym}** ({key.split("@")[1]}): '
            f'RSI<30 {rsi.get("pct_below_30")}%, RSI>70 {rsi.get("pct_above_70")}%, '
            f'MACD bull_cross {macd.get("bull_cross_pct")}%, crosses/100={macd.get("crosses_per_100bars")}, '
            f'Stoch<20 {stoch.get("pct_oversold_below20")}%, Stoch>80 {stoch.get("pct_overbought_above80")}%, '
            f'ADX>25 {adx.get("pct_above_25")}%'
        )
    return '\n'.join(lines)


def _format_iteration_history_v8(history: list[dict]) -> str:
    """v8: 更细 — 加 trade_patterns 让 LLM 看 SL hit% / win-loss 配比"""
    if not history:
        return '(第一轮)'
    lines = []
    for h in history:
        lines.append(f'### Iter {h["iteration"]}:')
        for a in h['attempts']:
            est = a.get('estimate') or {}
            mt = a.get('metrics') or {}
            tp = a.get('trade_patterns') or {}
            rp = a.get('risk_params_used') or {}
            tag = '✅ PASSED' if a['passed'] else '❌ FAILED'
            lines.append(
                f'  {tag} `{a["candidate_type"]}` ({a["symbol"]} {a["timeframe"]}/{a.get("category")})'
            )
            lines.append(
                f'    估: Sharpe={est.get("expected_oos_sharpe")} PF={est.get("expected_oos_pf")} trades={est.get("expected_oos_trades")}'
            )
            lines.append(
                f'    实: Sharpe={mt.get("oos_sharpe")} PF={mt.get("oos_pf")} trades={mt.get("oos_trades")} AR={mt.get("oos_ar_pct")}% decay={mt.get("decay_pct")}%'
            )
            if rp:
                lines.append(
                    f'    risk used: leverage={rp.get("leverage")} SL={rp.get("stop_loss_pct")}% TP={rp.get("take_profit_pct")}% pos=${rp.get("position_size_usdt")}'
                )
            if tp:
                lines.append(
                    f'    trade pattern: SL hit={tp.get("sl_hit_pct")}% TP hit={tp.get("tp_hit_pct")}% '
                    f'signal_exit={tp.get("signal_exit_pct")}% avg_bars_held={tp.get("avg_bars_held")} '
                    f'win/loss ratio={tp.get("win_loss_ratio")} (avg_win=${tp.get("avg_win_usdt")} avg_loss=${tp.get("avg_loss_usdt")})'
                )
            lines.append(f'    reason: {a["reason"]}')

            if not a['passed'] and a.get('losing_trades_sample'):
                lines.append(f'    亏损 trades 前 3 个:')
                for lt in a['losing_trades_sample'][:3]:
                    lines.append(
                        f'      side={lt.get("side")} entry={lt.get("entry_price")} exit={lt.get("exit_price")} '
                        f'pnl_pct={lt.get("pnl_pct")}% reason={lt.get("reason")} bars_held={lt.get("bars_held")}'
                    )
    lines.append('')
    lines.append('→ 分析 trade_patterns 找根因（SL 太紧？filter 太宽？win_loss 比错？），不要重复同样 logic')
    return '\n'.join(lines)


def _extract_losing_trades_sample(wf_json: dict, max_n: int = 5) -> list[dict]:
    try:
        trades = (wf_json.get('out_sample') or {}).get('trades') or (wf_json.get('full') or {}).get('trades') or []
        if not trades:
            return []
        losers = sorted([t for t in trades if (t.get('pnl') or 0) < 0], key=lambda t: t.get('pnl') or 0)
        return [{
            'side': t.get('side'),
            'entry_price': t.get('entry_price'),
            'exit_price': t.get('exit_price'),
            'pnl_pct': round(t.get('pnl_pct') or 0, 2),
            'reason': t.get('reason'),
            'bars_held': t.get('bars_held'),
        } for t in losers[:max_n]]
    except Exception:
        return []


def _persist_accepted(cand: dict, user_id: int, analysis: str,
                      external_research: str, llm_meta: dict) -> dict:
    """通过 self-test 的 candidate → BacktestResult + StrategyCandidate (status='qualified')"""
    metrics = cand['metrics']
    wf = cand['walkforward_json']
    full = wf.get('full') or {}
    rp = cand.get('risk_params') or {}

    bt = BacktestResult(
        strategy_id=None,
        strategy_type=cand.get('candidate_type', 'ai_v8_candidate'),
        params_snapshot=cand.get('default_params') or {},
        symbol=cand['symbol'],
        timeframe=cand['timeframe'],
        leverage=rp.get('leverage') or 15.0,
        position_size_usdt=rp.get('position_size_usdt') or 10.0,
        stop_loss_pct=rp.get('stop_loss_pct') or 5.0,
        take_profit_pct=rp.get('take_profit_pct') or 8.0,
        initial_capital=100.0,
        candle_count=full.get('candle_count'),
        total_trades=full.get('total_trades'),
        winning_trades=full.get('winning_trades'),
        losing_trades=full.get('losing_trades'),
        win_rate=full.get('win_rate'),
        total_pnl=full.get('total_pnl'),
        avg_pnl=full.get('avg_pnl'),
        avg_win=full.get('avg_win'), avg_loss=full.get('avg_loss'),
        profit_factor=full.get('profit_factor'),
        max_drawdown=full.get('max_drawdown'),
        max_drawdown_pct=full.get('max_drawdown_pct'),
        sharpe_ratio=full.get('sharpe_ratio'),
        final_equity=full.get('final_equity'),
        annual_return_pct=full.get('annual_return_pct'),
        equity_curve=full.get('equity_curve'),
        trades_json=full.get('trades'),
        duration_ms=full.get('duration_ms'),
        status='completed',
        walkforward_json=wf,
        user_id=user_id,
    )
    db.session.add(bt)
    db.session.flush()

    rec = StrategyCandidate(
        source='manual',
        source_name=f'AI improve v8 (user {user_id})',
        source_author=f'user:{user_id}:improve_v8',
        source_meta={
            'analysis': analysis,
            'external_research_summary': external_research,
            'rationale': cand.get('rationale'),
            'external_source': cand.get('external_source'),
            'internal_ref': cand.get('internal_ref'),
            'symbol': cand['symbol'],
            'risk_params': rp,
            'self_estimate': cand.get('self_estimate'),
            'actual_metrics': metrics,
            'trade_patterns': cand.get('trade_patterns'),
            'llm_provider': llm_meta.get('provider_used'),
            'llm_model': llm_meta.get('model_used'),
        },
        raw_code=f'AI improve v8 rationale: {(cand.get("rationale") or "")[:500]}',
        raw_lang='ai-improve-v8',
        parsed_signal=cand['parsed_signal'],
        signal_fn_name=cand['signal_fn_name'],
        candidate_type=cand['candidate_type'],
        category=cand.get('category', 'swing'),
        timeframe=cand['timeframe'],
        default_params=cand.get('default_params') or {},
        llm_notes=cand.get('rationale'),
        llm_model=llm_meta.get('model_used', 'unknown'),
        status='qualified',
        backtest_result_id=bt.id,
    )
    db.session.add(rec)
    db.session.flush()
    return {
        'candidate_id': rec.id,
        'backtest_result_id': bt.id,
        'candidate_type': rec.candidate_type,
        'symbol': cand['symbol'],
        'timeframe': cand['timeframe'],
        'category': rec.category,
        'metrics': metrics,
        'risk_params': rp,
    }


def _do_research_phase(user_id: int, user_symbols: list[str], universe: list[str]) -> tuple[str, dict]:
    """Phase A: 调研多 symbol × 多 TF"""
    prompt = (
        f'调研以下 crypto symbols 的最新量化模式 (12 月内): {universe}\n\n'
        f'User 当前 LIVE running 在: {user_symbols}\n\n'
        f'按 system prompt 的 markdown 格式输出，跨 symbol 对比 + 各 symbol regime 观察。'
    )
    llm = call_llm(
        user_id=user_id,
        prompt=prompt,
        system=RESEARCH_SYSTEM_PROMPT,
        max_tokens=5000,
        allowed_tools=ALLOWED_TOOLS,
        timeout=RESEARCH_PHASE_TIMEOUT,
    )
    if not llm.get('ok'):
        return '', {'phase_a_error': llm.get('error', '?')}
    return (llm.get('text') or '').strip(), {
        'provider_used': llm.get('provider_used'),
        'model_used': llm.get('model_used'),
        'latency_ms': llm.get('latency_ms'),
    }


def improve_strategies_v8(user_id: int, *,
                          max_iterations: int = 3,
                          target_count: int = 3,
                          enable_external_research: bool = True,
                          symbol_universe: list[str] | None = None) -> dict:
    """v8 主入口。

    返回 dict 含 submitted, rejected, no_edge_today, history, llm_meta 等。
    """
    running = scoped_query(Strategy).filter_by(status='running').all()
    if not running:
        # 没 running 也允许跑 — 用 default universe
        user_symbols = []
    else:
        user_symbols = sorted({s.symbol for s in running if s.symbol})

    # Symbol universe = user 现有 + base default
    universe = symbol_universe or SYMBOL_UNIVERSE_BASE
    universe = list({*universe, *user_symbols})    # union + dedup
    universe.sort()

    # Phase A: 外部调研
    external_research_text = ''
    phase_a_meta: dict = {}
    if enable_external_research:
        external_research_text, phase_a_meta = _do_research_phase(user_id, user_symbols, universe)

    # 三层 refs
    profitable_refs = pull_profitable_references(user_id, limit=4)
    builtin_refs = pull_builtin_strategy_refs(limit=20, include_source=False)   # v8: 仅 summary
    translated_refs = pull_translated_candidate_refs(limit=6)

    # Multi-symbol multi-TF stats
    try:
        from app.services.regime_detector import detect_regime
    except Exception:
        detect_regime = lambda *_a, **_kw: {}
    symbol_stats: dict[str, Any] = {}
    for symbol in universe:
        for tf in TARGET_TFS:
            key = f'{symbol}@{tf}'
            try:
                candles = fetch_ohlcv_history(symbol, tf, total_limit=CANDLE_LIMIT_BY_TF.get(tf, 1500))
                stats = compute_symbol_stats(candles)
                regime = detect_regime(symbol, tf)
                symbol_stats[key] = {'regime': regime, 'stats': stats}
            except Exception as e:
                symbol_stats[key] = {'error': f'{type(e).__name__}: {e}'}

    # Phase B: 迭代生成 + 自测
    accepted: list[dict] = []
    rejected: list[dict] = []
    history: list[dict] = []
    no_edge_recorded: dict | None = None
    analysis_text = ''
    final_llm_meta: dict = {}
    seen_candidate_types: set[str] = set()

    for iteration in range(max_iterations):
        remaining = target_count - len(accepted)
        if remaining <= 0:
            break

        prompt_parts = [
            f'# 任务: 生成 {remaining} 个新策略候选 (或 graceful no-edge)',
            f'\n## SYMBOL_UNIVERSE: {universe}',
            f'\n## User 当前 running: {user_symbols if user_symbols else "(空)"}',
        ]
        if external_research_text:
            prompt_parts.append(f'\n## Phase A 外部调研 summary\n\n{external_research_text}')
        else:
            prompt_parts.append('\n## Phase A 外部调研: ⚠ 跳过 (degraded)')
        prompt_parts.append(f'\n## 三层 internal references\n\n{_format_refs_block(profitable_refs, builtin_refs, translated_refs)}')
        prompt_parts.append(f'\n## Symbol × TF grid (4×5=20 blocks)\n\n{_format_symbol_stats_compact(symbol_stats)}')

        if history:
            prompt_parts.append(f'\n## 前几轮 self-test 结果\n\n{_format_iteration_history_v8(history)}')

        prompt_parts.append(
            f'\n## 现在: 输出严格 JSON ({remaining} candidates 或 no_edge_today=true)\n'
            '不要使用任何工具，直接输出 JSON'
        )
        prompt = '\n'.join(prompt_parts)

        llm = call_llm(
            user_id=user_id,
            prompt=prompt,
            system=GENERATE_SYSTEM_PROMPT,
            max_tokens=10000,
            allowed_tools=None,
            timeout=GENERATE_PHASE_TIMEOUT,
        )
        if not llm.get('ok'):
            return {
                'ok': False,
                'error': f'LLM iter {iteration} 失败: {llm.get("error")}',
                'submitted': [_persist_accepted(c, user_id, analysis_text, external_research_text, final_llm_meta) for c in accepted],
                'history': history,
                'external_research_summary': external_research_text,
                'phase_a_meta': phase_a_meta,
            }
        final_llm_meta = {'provider_used': llm.get('provider_used'), 'model_used': llm.get('model_used')}

        spec = _extract_json(llm['text'])
        if spec is None:
            history.append({
                'iteration': iteration,
                'attempts': [],
                'note': 'LLM 输出无法解析 JSON',
                'raw_output': (llm.get('text') or '')[:600],
            })
            continue

        # Graceful no-edge
        if spec.get('no_edge_today'):
            no_edge_recorded = {
                'iteration': iteration,
                'reason': spec.get('reason'),
                'recommendations': spec.get('recommendations'),
                'analysis': spec.get('analysis'),
            }
            history.append({'iteration': iteration, 'attempts': [], 'no_edge': no_edge_recorded})
            break    # LLM 明确说没 edge 就停止迭代

        if not isinstance(spec.get('candidates'), list):
            history.append({
                'iteration': iteration,
                'attempts': [],
                'note': 'spec 既无 candidates 也无 no_edge_today',
                'raw_output': (llm.get('text') or '')[:600],
            })
            continue
        analysis_text = spec.get('analysis', analysis_text)

        iter_result: dict = {'iteration': iteration, 'attempts': []}
        for cand in spec['candidates'][:remaining]:
            ctype = cand.get('candidate_type') or 'unknown_v8'
            symbol = cand.get('symbol')
            tf = cand.get('timeframe')
            cat = cand.get('category')
            rp = cand.get('risk_params') or {}

            if symbol not in universe:
                iter_result['attempts'].append({
                    'candidate_type': ctype, 'symbol': symbol, 'timeframe': tf, 'category': cat,
                    'passed': False, 'reason': f'symbol {symbol} 不在 SYMBOL_UNIVERSE {universe}',
                    'metrics': None, 'estimate': cand.get('self_estimate'),
                })
                continue

            if ctype in seen_candidate_types:
                ctype = f'{ctype}_iter{iteration}'
                cand['candidate_type'] = ctype
            seen_candidate_types.add(ctype)

            # quick_backtest with LLM 推荐的 risk_params
            qb = quick_backtest(
                cand.get('parsed_signal', ''),
                cand.get('signal_fn_name', ''),
                cand.get('default_params') or {},
                symbol, tf or '4h',
                leverage=rp.get('leverage'),
                position_size_usdt=rp.get('position_size_usdt'),
                stop_loss_pct=rp.get('stop_loss_pct'),
                take_profit_pct=rp.get('take_profit_pct'),
            )

            passed = False
            reason = qb.get('error') or 'no metrics'
            if qb.get('ok'):
                passed, reason = self_test_passes(qb['metrics'], tf or '4h')
                # 额外门槛: SL hit% > 60% 自动 fail
                if passed:
                    tp_data = qb.get('trade_patterns', {})
                    sl_hit = tp_data.get('sl_hit_pct') or 0
                    if sl_hit > 60:
                        passed = False
                        reason = f'SL hit_pct {sl_hit}% > 60% (SL/leverage 配比错)'

            attempt = {
                'candidate_type': ctype,
                'symbol': symbol, 'timeframe': tf, 'category': cat,
                'passed': passed, 'reason': reason,
                'metrics': qb.get('metrics'),
                'risk_params_used': qb.get('risk_params'),
                'trade_patterns': qb.get('trade_patterns'),
                'estimate': cand.get('self_estimate'),
                'losing_trades_sample': _extract_losing_trades_sample(qb.get('walkforward_json') or {}, max_n=5) if not passed and qb.get('ok') else [],
            }
            iter_result['attempts'].append(attempt)

            if passed:
                accepted.append({
                    **cand,
                    'metrics': qb['metrics'],
                    'trade_patterns': qb.get('trade_patterns'),
                    'walkforward_json': qb['walkforward_json'],
                })
            else:
                rejected.append(attempt)

        history.append(iter_result)

    # Persist accepted
    submitted: list[dict] = []
    for c in accepted:
        try:
            submitted.append(_persist_accepted(c, user_id, analysis_text, external_research_text, final_llm_meta))
        except Exception as e:
            rejected.append({
                'candidate_type': c.get('candidate_type'),
                'symbol': c.get('symbol'), 'timeframe': c.get('timeframe'),
                'passed': True,
                'reason': f'persist failed: {type(e).__name__}: {e}',
                'metrics': c.get('metrics'),
            })
    if submitted:
        db.session.commit()

    return {
        'ok': True,
        'analysis': analysis_text,
        'external_research_summary': external_research_text,
        'phase_a_meta': phase_a_meta,
        'no_edge_today': no_edge_recorded,
        'submitted': submitted,
        'rejected': rejected,
        'iterations_used': len(history),
        'history': history,
        'llm_meta': final_llm_meta,
        'user_symbols': user_symbols,
        'symbol_universe': universe,
        'refs_used': {
            'profitable': len(profitable_refs),
            'builtin': len(builtin_refs),
            'translated': len(translated_refs),
        },
    }
