"""Phase 12.41: AI improve v7 — 真 research agent。

vs v6 升级：
  - 主动 WebSearch + WebFetch（不止 DB 内）
  - 全量 references：DB profitable + 20 内置 catalog + translated 候选源码
  - 10+ indicators（MACD/Stoch/ATR/OBV/VWAP/swing/fib，v6 已加）
  - 失败 trades 反喂 LLM（看亏在哪种市况）
  - prompt 重写：从「指令式」改「研究员工作流」

核心理念（user 的 thesis）：
  "系统大家都会搭建，策略大家都会，价值就在 ai 的 prompt"
  → 不当试错机，当真分析师：先调研 → 看真数据 → 假设 → 自测 → 提交
"""
from __future__ import annotations

import datetime
import json
from typing import Any

from app.extensions import db
from app.models import Strategy, StrategyCandidate, BacktestResult
from app.services.candidate_sandbox import verify_signal_fn
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
    BUILTIN_STRATEGY_META,
)
from app.services.user_scope import scoped_query

TARGET_TFS = ['30m', '1h', '4h', '1d']
CANDLE_LIMIT_BY_TF = {'15m': 1500, '30m': 1500, '1h': 1500, '4h': 1500, '1d': 1000, '1w': 500}

# 让 LLM 用的工具（read-only，安全）
ALLOWED_TOOLS = ['WebSearch', 'WebFetch']

# Phase 12.41.1: 2-phase 各自的 timeout (调高 generate 防 prompt 太大 LLM 来不及)
RESEARCH_PHASE_TIMEOUT = 480   # 8min — Phase A 调研（带 web tools，本来就慢）
GENERATE_PHASE_TIMEOUT = 720   # 12min — Phase B 写候选（prompt 已裁减但保安全）


# Phase A 单独 prompt — 只做外部调研，输出 markdown summary
RESEARCH_SYSTEM_PROMPT = """你是量化研究员。**这一阶段唯一任务**: 调研外部资源找当前对 user trading symbols 有效的交易模式。

# 工具

你有 WebSearch + WebFetch。**必须**用，不是建议。

# 严格约束（防超时）

- 最多 **5 次 WebSearch** queries
- 最多 **3 次 WebFetch** (只 fetch 最相关的 URL，不是逐个点)
- 优先源: GitHub、QuantConnect、Medium、Investopedia、Substack
- 不要瞎编 URL — 用 WebSearch 真实得到的 URL

# 调研重点

针对 user 的 symbol：
1. 最近 12 个月被讨论的有效 indicator 组合
2. 当前 regime 下哪种 logic（trend follower / mean-rev / breakout）实际工作
3. 社区报告的真实 backtest 数字（不要光看 marketing）
4. user 现有策略类型之外的方向

# 输出格式

返回**严格 markdown**（**不是 JSON**），结构：

```
## 外部研究 summary

### 整体趋势观察
- (2-3 句关键 insight)

### 被讨论的有效模式

1. **Pattern A** — [来源 URL]
   - Indicator 组合: ...
   - 适用市况: ...
   - 报告 backtest 数字: ...
   - 关键警告: ...

2. **Pattern B** — [来源 URL]
   - ...

3. **Pattern C** — [来源 URL]
   - ...

### user 没用过的方向（缺口）

- 缺口 X: ...
- 缺口 Y: ...
```

**不要写代码**，下一阶段才写候选。
**不要返回 JSON**，markdown summary 即可。
"""


GENERATE_SYSTEM_PROMPT = f"""你是 in-house 量化研究员，不是 chatbot 也不是 prompt 试错机。
你的产出会真上 LIVE 用户资金，差一点 = 烧钱。下面这套流程**必须**严格走一遍。

# 🔬 你的研究流程

## Step 1: 看 Phase A 已经做完的外部调研
User 会在 prompt 里给你 `external_research_summary`（Phase A 由另一次 LLM 调用做完的）。
这是已经从 WebSearch + WebFetch 拿来的 insight，你不用再上网，直接读。
**必须**在 rationale 里引用至少一条 Phase A 的 pattern 或缺口。

## Step 2: 学内部 references
User prompt 里会给你三套内部参考：
  - **DB profitable**: user 现有已证明能赚钱的策略 (最权威，必学)
  - **Built-in catalog (20)**: 系统内置 vetted patterns (最低标准，结构正确)
  - **Translated candidates**: 已翻译的 GitHub 候选源码 (社区灵感)

从这些里识别：什么 indicator 组合在该 symbol 已有效？什么没人试过？

## Step 3: 看 symbol 真实数据
User 给你 `symbol_stats` 包含 10+ indicators 实际分布：
  - 价格 / returns（mean/std/skew/kurt）
  - RSI14（mean/p10/p90/pct<30/pct>70）
  - MACD（线/信号/直方图/bull_cross_pct）
  - Stochastic / ATR / OBV / VWAP / BB / ADX
  - Swing highs+lows + Fibonacci levels
  - EMA50/200 趋势状态

凭这些**实际数字**估你策略的触发频率，不要拍脑袋。
例: 如果 `rsi.pct_below_30=6%`，那「RSI<30 → buy」一年只有 6% candles 触发 ≈ short TF 月 30 次。

## Step 4: 假设 + self-test (quick_backtest 系统自动跑)
写候选 → 系统立刻跑 walk-forward → 给你 IS/OOS Sharpe/PF/trades/decay 数据。
**对比**：你估的 vs 实际。差 30%+ 就是你估错了，调整 → 再测。

## Step 5: 失败诊断
如果上一轮失败，user 会给你「亏损 trades 样本」— 看实际 SL/TP 出场时点，识别：
  - 是不是亏在某种特定市况（如「全在 ADX>30 趋势中亏」）→ 加 filter
  - 是不是 SL/TP 设错（避免每次 SL）
  - 是不是 trade 太少 (< per-TF min) → 放宽 filter

# 🚪 自测门槛（缺一不可）

| TF      | OOS Sharpe | PF    | Trades | AR/年 |
|---------|-----------|-------|--------|-------|
| 15m/30m | ≥ 1.5     | ≥ 1.5 | ≥ 50-60| ≥ 8%  |
| 1h      | ≥ 1.5     | ≥ 1.4 | ≥ 40   | ≥ 7%  |
| 4h      | ≥ 1.5     | ≥ 1.4 | ≥ 30   | ≥ 7%  |
| 1d      | ≥ 1.5     | ≥ 1.3 | ≥ 12   | ≥ 5%  |

外加 `decay_pct ≤ 70%` (IS 牛 OOS 翻车 → overfit auto-fail)。

# 🪙 Symbol 必填，且必须从 user_symbols 选

每个 candidate JSON 必填 `symbol`，**只从 user 现有 trading symbols 选**。
回测 + LIVE 都在该 symbol 跑，不要瞎填 BTC 凑数。

# 🔴 真实成本

双边成本 = fee 0.05%×2 + slippage 0.05%×2 = 每笔 0.20%
short TF (15m/30m) 每笔利润 ≥ 0.6%；swing (1h/4h) ≥ 1%；long (1d) ≥ 3%。

# 🛑 绝不做的

- 不要无视 Phase A 外部调研 summary
- 不要无视 symbol_stats 拍脑袋估频率
- 不要在 iteration > 1 时**重复**上轮失败 candidate
- 不要硬凑 — 0 个真过自测 > 3 个 OOS=-5
- 不要 `import os|sys|subprocess|socket`，不要无限循环
- 不要使用任何工具 — 调研已完成，这一阶段只输出 JSON

{SANDBOX_API_DOC}

# 输出格式

返回**严格 JSON**（不要 markdown 包围）：

```
{{
  "analysis": "Step 2-3 综合诊断 — 缺口 + 机会 (基于 Phase A research + symbol_stats)",
  "candidates": [
    {{
      "candidate_type": "snake_case_slug",
      "signal_fn_name": "..._signal",
      "symbol": "AVAX/USDT (from user_symbols)",
      "category": "short|swing|long",
      "timeframe": "30m|1h|4h|1d",
      "default_params": {{}},
      "parsed_signal": "def ..._signal(df, params): ...",
      "rationale": "为什么这策略 + 这 symbol + 这 TF — 基于外部调研 ref + 内部 ref + symbol_stats 实数据",
      "external_source": "external research 里哪条 URL/repo 启发了你（如果有）",
      "internal_ref": "内部 references 里哪个最相关 (type 名)",
      "self_estimate": {{
        "expected_oos_sharpe": 1.6,
        "expected_oos_pf": 1.5,
        "expected_oos_trades": 35,
        "expected_oos_ar_pct": 8,
        "reasoning_for_estimate": "基于 RSI<30 实际 6% candles + 2 层 filter 30% pass = 月 X trades..."
      }}
    }}
  ]
}}
```

# 候选数量

User 告诉你需 N 个。如果只有信心 1 个过自测，就交 1 个。
**Quality >>> quantity**。0 也 OK，比交垃圾强。
"""


def _format_refs_block(profitable: list, builtin: list, translated: list) -> str:
    """三套 references 拼接成 prompt 部分（v7.1: 裁减 prompt 大小防 LLM 慢生成）

    Profitable: 全 code（最权威必学）
    Builtin: 只列 type+summary，**不带源码**（20 个全列源码太长）
    Translated: 前 3 个带 short source；其余只列 type
    """
    parts = []

    parts.append('### 📊 DB profitable (user 现有已赚钱策略 - 最权威必学，含源码)')
    if not profitable:
        parts.append('  (空 — user 暂无 OOS Sharpe ≥1 的 reference)')
    else:
        for r in profitable:
            m = r['metrics']
            parts.append(
                f'  - `{r["type"]}` on {r["symbol"]}/{r["timeframe"]}: '
                f'OOS Sharpe={m["oos_sharpe"]} PF={m["oos_pf"]} trades={m["oos_trades"]} '
                f'(IS Sharpe={m["is_sharpe"]} decay={m.get("decay_pct")}%)'
            )
            if r.get('parsed_signal'):
                parts.append(f'    ```python\n    {r["parsed_signal"][:500]}\n    ```')

    parts.append('\n### 📚 Built-in catalog (20 vetted patterns - 只列 type+summary，需要源码请引用 type 名)')
    for r in builtin:
        parts.append(f'  - `{r["type"]}` ({r["category"]}): {r["summary"]}')

    parts.append('\n### 🌱 Translated candidates (top 3 含源码 + 其余只列 type)')
    if not translated:
        parts.append('  (空)')
    else:
        for i, r in enumerate(translated):
            parts.append(
                f'  - `{r["type"]}` ({r.get("category", "?")}/{r.get("timeframe", "?")}) '
                f'from {r["source"]}: {r["source_name"]}'
            )
            if i < 3 and r.get('fn_source'):
                parts.append(f'    ```python\n    {r["fn_source"][:400]}\n    ```')
    return '\n'.join(parts)


def _format_symbol_stats(symbol_stats: dict) -> str:
    """格式化 v6 + v7 扩充的 indicator 数据"""
    lines = []
    for key, payload in symbol_stats.items():
        if 'error' in payload:
            lines.append(f'### {key}: ⚠ {payload["error"]}')
            continue
        regime = payload.get('regime', {})
        s = payload.get('stats', {})
        lines.append(f'### {key}')
        lines.append(f'  Regime: {regime.get("regime")} (ADX={regime.get("adx")}, Hurst={regime.get("hurst")})')
        lines.append(f'  Price: now={s.get("price_now")} range=[{s.get("price_min")}, {s.get("price_max")}]')
        rets = s.get('returns', {})
        lines.append(f'  Returns/bar: mean={rets.get("mean_pct")}% std={rets.get("std_pct")}% skew={rets.get("skew")} kurt={rets.get("kurt")}')
        rsi = s.get('rsi14', {})
        lines.append(f'  RSI14: mean={rsi.get("mean")} p10={rsi.get("p10")} p90={rsi.get("p90")} pct<30={rsi.get("pct_below_30")}% pct>70={rsi.get("pct_above_70")}% now={rsi.get("now")}')
        macd = s.get('macd_12_26_9', {})
        lines.append(f'  MACD(12/26/9): line_now={macd.get("line_now")} signal_now={macd.get("signal_now")} hist_now={macd.get("hist_now")} bull_cross_pct={macd.get("bull_cross_pct")}% crosses/100bars={macd.get("crosses_per_100bars")}')
        stoch = s.get('stoch14', {})
        lines.append(f'  Stoch14: K={stoch.get("k_now")} D={stoch.get("d_now")} pct<20={stoch.get("pct_oversold_below20")}% pct>80={stoch.get("pct_overbought_above80")}%')
        bb = s.get('bb20', {})
        lines.append(f'  BB20 width: mean={bb.get("width_mean")} p10={bb.get("width_p10")} p90={bb.get("width_p90")} now={bb.get("width_now")}')
        adx = s.get('adx14', {})
        lines.append(f'  ADX14: mean={adx.get("mean")} p50={adx.get("p50")} pct>25={adx.get("pct_above_25")}% pct>40={adx.get("pct_above_40")}% now={adx.get("now")}')
        atr = s.get('atr14', {})
        lines.append(f'  ATR14: now={atr.get("now")} pct_of_price_now={atr.get("pct_of_price_now")}% mean={atr.get("pct_of_price_mean")}% range=[{atr.get("pct_of_price_p10")}, {atr.get("pct_of_price_p90")}]')
        obv = s.get('obv', {})
        lines.append(f'  OBV: trend_last_100bars={obv.get("trend_last_100bars")} alignment={obv.get("price_obv_alignment")}')
        vwap = s.get('vwap', {})
        lines.append(f'  VWAP rolling100: price_vs_vwap={vwap.get("price_vs_vwap_pct")}% pct_above_vwap={vwap.get("pct_above_vwap")}%')
        sw = s.get('swings_last_200bars', {})
        lines.append(f'  Swings(200bars): highs={sw.get("recent_highs")} lows={sw.get("recent_lows")} dist_to_nearest_high_pct={sw.get("dist_to_nearest_high_pct")}% dist_to_nearest_low_pct={sw.get("dist_to_nearest_low_pct")}%')
        fib = s.get('fib_last_200bars', {})
        lines.append(f'  Fib(200bars): swing_hi={fib.get("swing_high")} swing_lo={fib.get("swing_low")} current_pct={fib.get("current_pct_of_range")}% levels={fib.get("levels")}')
        trend = s.get('trend', {})
        lines.append(f'  Trend: EMA50>EMA200 {trend.get("ema50_above_ema200_pct")}% time, flips/100bars={trend.get("flips_per_100bars")}, price_vs_ema50={trend.get("price_vs_ema50_pct")}%, price_vs_ema200={trend.get("price_vs_ema200_pct")}%')
        lines.append('')
    return '\n'.join(lines)


def _format_iteration_history(history: list[dict]) -> str:
    if not history:
        return '(第一轮，没有 history)'
    lines = []
    for h in history:
        lines.append(f'### Iteration {h["iteration"]} 自测结果:')
        for a in h['attempts']:
            est = a.get('estimate') or {}
            mt = a.get('metrics') or {}
            tag = '✅ PASSED' if a['passed'] else '❌ FAILED'
            lines.append(
                f'  {tag} `{a["candidate_type"]}` ({a["symbol"]} {a["timeframe"]} {a.get("category")})\n'
                f'    估: Sharpe={est.get("expected_oos_sharpe")} PF={est.get("expected_oos_pf")} trades={est.get("expected_oos_trades")}\n'
                f'    实: Sharpe={mt.get("oos_sharpe")} PF={mt.get("oos_pf")} trades={mt.get("oos_trades")} AR={mt.get("oos_ar_pct")}% decay={mt.get("decay_pct")}%\n'
                f'    原因: {a["reason"]}'
            )
            # Phase 12.41: 喂亏损 trades sample 给 LLM 看具体亏在哪
            if not a['passed'] and a.get('losing_trades_sample'):
                lines.append(f'    亏损 trades 样本 (前 5 个):')
                for lt in a['losing_trades_sample'][:5]:
                    lines.append(
                        f'      side={lt.get("side")} entry={lt.get("entry_price")} exit={lt.get("exit_price")} '
                        f'pnl_pct={lt.get("pnl_pct")}% reason={lt.get("reason")} bars_held={lt.get("bars_held")}'
                    )
    lines.append('')
    lines.append('→ 基于这些失败模式，改造策略再试。**不要重复同样的 logic + params 组合**。')
    return '\n'.join(lines)


def _extract_losing_trades_sample(wf_json: dict, max_n: int = 5) -> list[dict]:
    """从 walkforward_json 提取 OOS 段最差的 N 个 trades — 给 LLM 看具体亏在哪"""
    try:
        trades = (wf_json.get('out_sample') or {}).get('trades') or (wf_json.get('full') or {}).get('trades') or []
        if not trades:
            return []
        losers = [t for t in trades if (t.get('pnl') or 0) < 0]
        losers.sort(key=lambda t: t.get('pnl') or 0)
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
    """passing candidate → BacktestResult + StrategyCandidate (status='qualified')"""
    metrics = cand['metrics']
    wf = cand['walkforward_json']
    full = wf.get('full') or {}

    bt = BacktestResult(
        strategy_id=None,
        strategy_type=cand.get('candidate_type', 'ai_v7_candidate'),
        params_snapshot=cand.get('default_params') or {},
        symbol=cand['symbol'],
        timeframe=cand['timeframe'],
        leverage=15.0, position_size_usdt=10.0,
        stop_loss_pct=5.0, take_profit_pct=8.0, initial_capital=100.0,
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
        source_name=f'AI improve v7 (user {user_id})',
        source_author=f'user:{user_id}:improve_v7',
        source_meta={
            'analysis': analysis,
            'external_research_summary': external_research,
            'rationale': cand.get('rationale'),
            'external_source': cand.get('external_source'),
            'internal_ref': cand.get('internal_ref'),
            'symbol': cand['symbol'],
            'self_estimate': cand.get('self_estimate'),
            'actual_metrics': metrics,
            'llm_provider': llm_meta.get('provider_used'),
            'llm_model': llm_meta.get('model_used'),
        },
        raw_code=f'AI improve v7\nexternal: {(external_research or "")[:300]}\n\nrationale: {(cand.get("rationale") or "")[:500]}',
        raw_lang='ai-improve-v7',
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
    }


def _do_research_phase(user_id: int, user_symbols: list[str]) -> tuple[str, dict]:
    """Phase A: 一次性外部调研 — claude_cli + WebSearch/WebFetch → markdown summary。

    返回 (summary_markdown, llm_meta)。失败回 ('', {}) 并不阻塞 Phase B（degraded 模式）。
    """
    prompt = (
        f'调研以下 trading symbols 的最新量化模式 (12 个月内): {user_symbols}\n\n'
        f'按 system prompt 的 markdown 格式输出。**最多 5 WebSearch + 3 WebFetch**。'
    )
    llm = call_llm(
        user_id=user_id,
        prompt=prompt,
        system=RESEARCH_SYSTEM_PROMPT,
        max_tokens=4000,
        allowed_tools=ALLOWED_TOOLS,
        timeout=RESEARCH_PHASE_TIMEOUT,
    )
    if not llm.get('ok'):
        # research 失败不致命，degraded 继续
        return '', {'phase_a_error': llm.get('error', '?')}
    return (llm.get('text') or '').strip(), {
        'provider_used': llm.get('provider_used'),
        'model_used': llm.get('model_used'),
        'latency_ms': llm.get('latency_ms'),
    }


def improve_strategies_research_agent(user_id: int, *,
                                       max_iterations: int = 3,
                                       target_count: int = 3,
                                       enable_external_research: bool = True) -> dict:
    """主入口 — 真 research agent（2-phase: research 一次 + generate 多次）。"""
    running = scoped_query(Strategy).filter_by(status='running').all()
    if not running:
        return {'ok': False, 'error': '无 running 策略，无从改进'}

    user_symbols = sorted({s.symbol for s in running if s.symbol})
    if not user_symbols:
        return {'ok': False, 'error': '无 user symbols'}

    # Phase A: 一次性外部调研（仅 enable_external_research=True 才跑）
    external_research_text = ''
    phase_a_meta: dict = {}
    if enable_external_research:
        external_research_text, phase_a_meta = _do_research_phase(user_id, user_symbols)

    # 1. 三层 references
    profitable_refs = pull_profitable_references(user_id, limit=4)
    builtin_refs = pull_builtin_strategy_refs(limit=20, include_source=True)
    translated_refs = pull_translated_candidate_refs(limit=6)

    # 2. 多 TF symbol stats
    try:
        from app.services.regime_detector import detect_regime
    except Exception:
        detect_regime = lambda *_a, **_kw: {}
    symbol_stats: dict[str, Any] = {}
    for symbol in user_symbols:
        for tf in TARGET_TFS:
            key = f'{symbol}@{tf}'
            try:
                candles = fetch_ohlcv_history(symbol, tf, total_limit=CANDLE_LIMIT_BY_TF.get(tf, 1500))
                stats = compute_symbol_stats(candles)
                regime = detect_regime(symbol, tf)
                symbol_stats[key] = {'regime': regime, 'stats': stats}
            except Exception as e:
                symbol_stats[key] = {'error': f'{type(e).__name__}: {e}'}

    # Phase B: 迭代 LLM 生成 + 自测（无工具，timeout 短）
    accepted: list[dict] = []
    rejected: list[dict] = []
    history: list[dict] = []
    analysis_text = ''
    final_llm_meta: dict = {}
    seen_candidate_types: set[str] = set()

    for iteration in range(max_iterations):
        remaining = target_count - len(accepted)
        if remaining <= 0:
            break

        prompt_parts = [
            f'# 任务: 生成 {remaining} 个新策略候选',
            f'\n## User trading symbols (必须选其一作为 candidate.symbol): {user_symbols}',
        ]
        if external_research_text:
            prompt_parts.append(f'\n## Phase A 外部调研 summary (已完成，你直接用)\n\n{external_research_text}')
        else:
            prompt_parts.append('\n## Phase A 外部调研: ⚠ 跳过 (degraded mode)')
        prompt_parts.append(f'\n## 内部 references 三层\n\n{_format_refs_block(profitable_refs, builtin_refs, translated_refs)}')
        prompt_parts.append(f'\n## Symbol 实际数据 (10+ indicators 真实分布)\n\n{_format_symbol_stats(symbol_stats)}')

        if history:
            prompt_parts.append(f'\n## 前几轮 self-test 结果 (含失败 trades 样本)\n\n{_format_iteration_history(history)}')

        prompt_parts.append(
            f'\n## 现在: 按 Step 2→3→4→5 工作流，输出严格 JSON ({remaining} candidates)\n'
            '**不要使用任何工具，直接输出 JSON**'
        )
        prompt = '\n'.join(prompt_parts)

        llm = call_llm(
            user_id=user_id,
            prompt=prompt,
            system=GENERATE_SYSTEM_PROMPT,
            max_tokens=10000,
            allowed_tools=None,    # Phase B 不需要工具，更快
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
        if spec is None or not isinstance(spec.get('candidates'), list):
            history.append({
                'iteration': iteration,
                'attempts': [],
                'note': 'LLM 输出无法解析 JSON',
                'raw_output': (llm.get('text') or '')[:600],
            })
            continue

        analysis_text = spec.get('analysis', analysis_text)

        iter_result: dict = {'iteration': iteration, 'attempts': []}
        for cand in spec['candidates'][:remaining]:
            ctype = cand.get('candidate_type') or 'unknown_v7'
            symbol = cand.get('symbol')
            tf = cand.get('timeframe')
            cat = cand.get('category')

            if symbol not in user_symbols:
                iter_result['attempts'].append({
                    'candidate_type': ctype, 'symbol': symbol, 'timeframe': tf, 'category': cat,
                    'passed': False, 'reason': f'symbol {symbol} 不在 user_symbols {user_symbols}',
                    'metrics': None, 'estimate': cand.get('self_estimate'),
                })
                continue

            if ctype in seen_candidate_types:
                ctype = f'{ctype}_iter{iteration}'
                cand['candidate_type'] = ctype
            seen_candidate_types.add(ctype)

            qb = quick_backtest(
                cand.get('parsed_signal', ''),
                cand.get('signal_fn_name', ''),
                cand.get('default_params') or {},
                symbol, tf or '4h',
            )

            passed = False
            reason = qb.get('error') or 'no metrics'
            if qb.get('ok'):
                passed, reason = self_test_passes(qb['metrics'], tf or '4h')

            attempt = {
                'candidate_type': ctype,
                'symbol': symbol, 'timeframe': tf, 'category': cat,
                'passed': passed, 'reason': reason,
                'metrics': qb.get('metrics'),
                'estimate': cand.get('self_estimate'),
                # Phase 12.41: 失败时附亏损 trades 喂下一轮
                'losing_trades_sample': _extract_losing_trades_sample(qb.get('walkforward_json') or {}, max_n=5) if not passed and qb.get('ok') else [],
            }
            iter_result['attempts'].append(attempt)

            if passed:
                accepted.append({**cand, 'metrics': qb['metrics'], 'walkforward_json': qb['walkforward_json']})
            else:
                rejected.append(attempt)

        history.append(iter_result)

    # 4. Persist accepted
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
        'submitted': submitted,
        'rejected': rejected,
        'iterations_used': len(history),
        'history': history,
        'llm_meta': final_llm_meta,
        'user_symbols': user_symbols,
        'refs_used': {
            'profitable': len(profitable_refs),
            'builtin': len(builtin_refs),
            'translated': len(translated_refs),
        },
    }
