"""Phase 12.40: AI improve v6 — 迭代式分析师，不当试错机。

工作流（vs v4/v5 的 fire-and-forget）：

  1. 学习阶段
     → pull_profitable_references → 拉已经证明能赚钱的策略代码喂 LLM
     → "看这些是真能跑通的 pattern"

  2. 数据阶段
     → compute_symbol_stats → 实际 RSI/BB/ADX 分布喂 LLM
     → "这是当前 symbol 的真实数字，不是 regime label"

  3. 假设 + 自测阶段（核心新增）
     → LLM 写 candidate
     → quick_backtest 内存跑 walk-forward
     → 失败就把 IS/OOS 指标反喂 LLM，让它改 → 再测
     → 最多 N 轮，过自测才提交

  4. 提交阶段
     → 只 passing 才写 strategy_candidates（status='qualified', 已有 backtest_result）
     → 0 个也是 0 个，绝不灌垃圾

老 v4/v5 (strategy_improve.py) 暂保留兼容，但 cron + 端点切到 v6。
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
    compute_symbol_stats,
    quick_backtest,
    self_test_passes,
    TF_GATES,
)
from app.services.user_scope import scoped_query

# 默认抓 4 个 TF — 覆盖 short/swing/long 各层
TARGET_TFS = ['30m', '1h', '4h', '1d']
CANDLE_LIMIT_BY_TF = {'15m': 1500, '30m': 1500, '1h': 1500, '4h': 1500, '1d': 1000, '1w': 500}


SYSTEM_PROMPT_V6 = f"""你是 in-house 量化研究员。这不是 chat — 你是带回测工具的工程师。

## 🎯 你的工作流（必须严格遵守）

1. **看「已经能赚钱」的策略代码**（user 会提供 referernce_strategies）
   → 这是过滤后的金子。学它们的结构 / filter 组合 / 频率控制方式。
   → 不要模仿失败的 pattern。

2. **看 symbol 的真实数据**（user 会提供 symbol_stats）
   → 不要凭 regime label 瞎猜。看实际 RSI 分布、BB width 分布、ADX 分布、波动率。
   → 例: "rsi14.pct_below_30=12%" 意味着该 symbol 一年中 12% 时间 RSI<30。
       这才是你估"RSI<30 → buy"频率的依据，不要拍脑袋。

3. **写候选 + 自测**
   → 每个候选会立刻跑 quick_backtest 自测。
   → 失败的话你会看到 OOS Sharpe / PF / trades / decay_pct，对比你的 self_estimate。
   → 然后你改 logic / 改阈值 / 改 TF → 再测。最多 3 轮。
   → **过自测才提交**。0 个通过就交 0 个，不要硬凑。

## 🚪 自测门槛（必须全部过，缺一不可）

| TF      | OOS Sharpe | Profit Factor | Trades | AR/年 |
|---------|-----------|---------------|--------|-------|
| 15m/30m | ≥ 1.5     | ≥ 1.5         | ≥ 50-60| ≥ 8%  |
| 1h      | ≥ 1.5     | ≥ 1.4         | ≥ 40   | ≥ 7%  |
| 4h      | ≥ 1.5     | ≥ 1.4         | ≥ 30   | ≥ 7%  |
| 1d      | ≥ 1.5     | ≥ 1.3         | ≥ 12   | ≥ 5%  |

外加 **decay_pct ≤ 70%**（IS 牛 OOS 翻车说明 overfit，自动 fail）。

## 🪙 Symbol 必填且必须从 user_symbols 列表选

User 在 prompt 里给你他的 trading symbols。每个 candidate 必填 `symbol` 字段，
**只能选 user 现有 symbols** — 因为回测就在该 symbol 跑，LIVE 也在那。
不要瞎填 BTC/USDT 凑数。

## 🔴 真实成本必须计入策略逻辑

- 双边成本 = fee 0.05%×2 + slippage 0.05%×2 = **每笔 0.20%**
- short TF（15m/30m）每笔利润必须 ≥ 0.6% → 否则 PF<1.5 必 fail
- swing（1h/4h）每笔利润 ≥ 1%
- long（1d）每笔利润 ≥ 3%

## 🛑 不要做的事

- 不要无视 reference_strategies 自己发明 — 那是 textbook copy
- 不要无视 symbol_stats 拍脑袋估频率
- 不要在 iteration > 1 时**重复**上一轮失败的 candidate（看 history 改）
- 不要硬凑 3 个 — 1 个真过自测的 >>> 3 个 OOS 都 -5
- 不要用 `while True` / 无限循环 / `import os|sys|socket|subprocess`

{SANDBOX_API_DOC}

## 输出 JSON Schema

返回 **严格 JSON**（不要 markdown 包围），结构：

{{
  "analysis": "看完 references + symbol_stats 后的整体诊断 — 2-3 句",
  "candidates": [
    {{
      "candidate_type": "snake_case_slug",
      "signal_fn_name": "..._signal",
      "symbol": "AVAX/USDT (必填，从 user_symbols 选)",
      "category": "short" | "swing" | "long",
      "timeframe": "30m | 1h | 4h | 1d",
      "default_params": {{}},
      "parsed_signal": "完整 def ..._signal(df, params): ...",
      "rationale": "为什么这个策略 + 这个 symbol + 这个 TF：基于 reference XXX 的结构，针对 symbol_stats 中的 RSI/BB/ADX 实际分布",
      "self_estimate": {{
        "expected_oos_sharpe": 1.6,
        "expected_oos_pf": 1.5,
        "expected_oos_trades": 35,
        "expected_oos_ar_pct": 8,
        "reasoning_for_estimate": "RSI<30 实际占 12% candles，2 层 filter 通过率约 30% → 月 4-5 trades..."
      }}
    }}
  ]
}}

## 候选数量

User 告诉你需要 N 个 — 如果 N=3 但你只有信心 1 个能过自测，就交 1 个。
不要硬凑。Quality >> quantity。
"""


def _format_references(refs: list[dict]) -> str:
    """格式化 profitable references — 显示代码"""
    if not refs:
        return '⚠ 目前没有 OOS Sharpe ≥1 的 reference 策略可学。请基于通用量化原理写，并特别保守估频率。'
    lines = []
    for i, r in enumerate(refs, 1):
        m = r['metrics']
        lines.append(
            f'### Ref #{i} ({r["source"]}): `{r["type"]}` on {r["symbol"]} @ {r["timeframe"]}\n'
            f'  Metrics: OOS Sharpe={m["oos_sharpe"]}, OOS PF={m["oos_pf"]}, '
            f'OOS trades={m["oos_trades"]}, IS Sharpe={m["is_sharpe"]}, decay={m.get("decay_pct")}%\n'
            f'  Params: {json.dumps(r["params"], ensure_ascii=False)}'
        )
        if r.get('parsed_signal'):
            sig = r['parsed_signal'][:800]
            lines.append(f'  ```python\n{sig}\n  ```')
        lines.append('')
    return '\n'.join(lines)


def _format_symbol_stats(symbol_stats: dict) -> str:
    """格式化 symbol stats — 实际数据 + regime"""
    lines = []
    for key, payload in symbol_stats.items():
        if 'error' in payload:
            lines.append(f'### {key}: ⚠ {payload["error"]}')
            continue
        regime = payload.get('regime', {})
        stats = payload.get('stats', {})
        rsi = stats.get('rsi14', {})
        bb = stats.get('bb20', {})
        adx = stats.get('adx14', {})
        trend = stats.get('trend', {})
        rets = stats.get('returns', {})
        lines.append(
            f'### {key}\n'
            f'  Regime: {regime.get("regime")} (ADX={regime.get("adx")}, Hurst={regime.get("hurst")})\n'
            f'  Price: now={stats.get("price_now")} range=[{stats.get("price_min")}, {stats.get("price_max")}]\n'
            f'  Returns: mean={rets.get("mean_pct")}%/bar, std={rets.get("std_pct")}%/bar, skew={rets.get("skew")}, kurt={rets.get("kurt")}\n'
            f'  RSI14: mean={rsi.get("mean")}, p10={rsi.get("p10")}, p90={rsi.get("p90")}, pct<30={rsi.get("pct_below_30")}%, pct>70={rsi.get("pct_above_70")}%, now={rsi.get("now")}\n'
            f'  BB20 width: mean={bb.get("width_mean")}, p10={bb.get("width_p10")}, p90={bb.get("width_p90")}, now={bb.get("width_now")}\n'
            f'  ADX14: mean={adx.get("mean")}, p50={adx.get("p50")}, pct>25={adx.get("pct_above_25")}%, pct>40={adx.get("pct_above_40")}%, now={adx.get("now")}\n'
            f'  Trend: EMA50>EMA200 {trend.get("ema50_above_ema200_pct")}% time, flips/100bars={trend.get("flips_per_100bars")}'
        )
        lines.append('')
    return '\n'.join(lines)


def _format_iteration_history(history: list[dict]) -> str:
    """格式化前几轮失败结果 — 告诉 LLM 改方向"""
    if not history:
        return '(第一轮，没有 history)'
    lines = []
    for h in history:
        lines.append(f'### Iteration {h["iteration"]} 自测结果:')
        for a in h['attempts']:
            est = a.get('estimate') or {}
            mt = a.get('metrics') or {}
            tag = '✅ PASSED' if a['passed'] else '❌ FAILED'
            est_pf = est.get('expected_oos_pf', '?')
            est_sharpe = est.get('expected_oos_sharpe', '?')
            est_trades = est.get('expected_oos_trades', '?')
            lines.append(
                f'  {tag} `{a["candidate_type"]}` ({a["symbol"]} {a["timeframe"]} {a["category"]})\n'
                f'    你估的: Sharpe={est_sharpe} PF={est_pf} trades={est_trades}\n'
                f'    实际:   Sharpe={mt.get("oos_sharpe")} PF={mt.get("oos_pf")} '
                f'trades={mt.get("oos_trades")} AR={mt.get("oos_ar_pct")}% decay={mt.get("decay_pct")}%\n'
                f'    原因: {a["reason"]}'
            )
    lines.append('')
    lines.append('→ 基于这些失败模式，改造策略再试。**不要重复同样的 logic + params 组合**。')
    return '\n'.join(lines)


def _persist_accepted(cand: dict, user_id: int, analysis: str, llm_meta: dict) -> dict:
    """把 self-test 通过的 candidate 写入 DB：先 BacktestResult，再 StrategyCandidate (status=qualified)"""
    metrics = cand['metrics']
    wf = cand['walkforward_json']
    full = wf.get('full') or {}

    # 1. write BacktestResult
    bt = BacktestResult(
        strategy_id=None,
        strategy_type=cand.get('candidate_type', 'ai_v6_candidate'),
        params_snapshot=cand.get('default_params') or {},
        symbol=cand['symbol'],
        timeframe=cand['timeframe'],
        leverage=15.0,
        position_size_usdt=10.0,
        stop_loss_pct=5.0,
        take_profit_pct=8.0,
        initial_capital=100.0,
        period_start=None,
        period_end=None,
        candle_count=full.get('candle_count'),
        total_trades=full.get('total_trades'),
        winning_trades=full.get('winning_trades'),
        losing_trades=full.get('losing_trades'),
        win_rate=full.get('win_rate'),
        total_pnl=full.get('total_pnl'),
        avg_pnl=full.get('avg_pnl'),
        avg_win=full.get('avg_win'),
        avg_loss=full.get('avg_loss'),
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

    # 2. write StrategyCandidate
    rec = StrategyCandidate(
        source='manual',
        source_name=f'AI improve v6 (user {user_id})',
        source_author=f'user:{user_id}:improve_v6',
        source_meta={
            'analysis': analysis,
            'rationale': cand.get('rationale'),
            'symbol': cand['symbol'],
            'self_estimate': cand.get('self_estimate'),
            'actual_metrics': metrics,
            'llm_provider': llm_meta.get('provider_used'),
            'llm_model': llm_meta.get('model_used'),
        },
        raw_code=f'AI improve v6 — {cand.get("rationale", "")[:500]}',
        raw_lang='ai-improve-v6',
        parsed_signal=cand['parsed_signal'],
        signal_fn_name=cand['signal_fn_name'],
        candidate_type=cand['candidate_type'],
        category=cand.get('category', 'swing'),
        timeframe=cand['timeframe'],
        default_params=cand.get('default_params') or {},
        llm_notes=cand.get('rationale'),
        llm_model=llm_meta.get('model_used', 'unknown'),
        status='qualified',           # 已过自测 → 直接 qualified
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


def improve_strategies_iterative(user_id: int, *, max_iterations: int = 3, target_count: int = 3) -> dict:
    """主入口。返回:
    {
      ok, submitted: [...], iterations_used, history: [...], analysis,
      llm_meta, rejected: [...]   # 自测失败的（带原因，便于 debug）
    }
    """
    running = scoped_query(Strategy).filter_by(status='running').all()
    if not running:
        return {'ok': False, 'error': '无 running 策略，无从改进'}

    user_symbols = sorted({s.symbol for s in running if s.symbol})
    if not user_symbols:
        return {'ok': False, 'error': '无 user symbols'}

    # 1. 学习阶段
    profitable_refs = pull_profitable_references(user_id, limit=5)

    # 2. 数据阶段
    try:
        from app.services.regime_detector import detect_regime
    except Exception:
        detect_regime = lambda *_args, **_kw: {}
    symbol_stats = {}
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

    # 3. 迭代 LLM + 自测循环
    accepted: list[dict] = []   # passing candidates，到末尾 persist
    rejected: list[dict] = []   # 失败的，附原因
    history: list[dict] = []
    analysis_text = ''
    final_llm_meta: dict = {}
    seen_candidate_types: set[str] = set()

    for iteration in range(max_iterations):
        remaining = target_count - len(accepted)
        if remaining <= 0:
            break

        # 构建 prompt
        user_prompt_parts = [
            f'## 你的任务：生成 {remaining} 个新策略候选',
            f'\n## User symbols (必须选其一): {user_symbols}',
            f'\n## Reference 策略（已证明能赚钱的 — 学这些）\n\n{_format_references(profitable_refs)}',
            f'\n## Symbol 实际数据 + Regime\n\n{_format_symbol_stats(symbol_stats)}',
        ]
        if history:
            user_prompt_parts.append(f'\n## 前几轮 self-test 结果\n\n{_format_iteration_history(history)}')

        user_prompt_parts.append(
            f'\n## 现在生成 {remaining} 个 JSON candidates（symbol + timeframe + category + parsed_signal + rationale + self_estimate）'
        )
        prompt = '\n'.join(user_prompt_parts)

        llm = call_llm(
            user_id=user_id,
            prompt=prompt,
            system=SYSTEM_PROMPT_V6,
            max_tokens=8000,
        )
        if not llm.get('ok'):
            return {
                'ok': False,
                'error': f'LLM iter {iteration} 失败: {llm.get("error")}',
                'submitted': [_persist_accepted(c, user_id, analysis_text, final_llm_meta) for c in accepted],
                'history': history,
            }
        final_llm_meta = {
            'provider_used': llm.get('provider_used'),
            'model_used': llm.get('model_used'),
        }

        spec = _extract_json(llm['text'])
        if spec is None or not isinstance(spec.get('candidates'), list):
            history.append({
                'iteration': iteration,
                'attempts': [],
                'note': 'LLM 输出无法解析 JSON',
                'raw_output': llm['text'][:500],
            })
            continue
        analysis_text = spec.get('analysis', analysis_text)

        iter_result: dict = {'iteration': iteration, 'attempts': []}
        for cand in spec['candidates'][:remaining]:
            ctype = cand.get('candidate_type') or 'unknown_v6'
            symbol = cand.get('symbol')
            tf = cand.get('timeframe')
            cat = cand.get('category')

            # 校验 symbol 在 user_symbols 中
            if symbol not in user_symbols:
                iter_result['attempts'].append({
                    'candidate_type': ctype, 'symbol': symbol, 'timeframe': tf,
                    'category': cat, 'passed': False,
                    'reason': f'symbol {symbol} 不在 user_symbols {user_symbols}',
                    'metrics': None, 'estimate': cand.get('self_estimate'),
                })
                continue

            # 防 LLM 重复提同名 type
            if ctype in seen_candidate_types:
                ctype = f'{ctype}_iter{iteration}'
                cand['candidate_type'] = ctype
            seen_candidate_types.add(ctype)

            # quick_backtest
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
            }
            iter_result['attempts'].append(attempt)

            if passed:
                accepted.append({
                    **cand,
                    'metrics': qb['metrics'],
                    'walkforward_json': qb['walkforward_json'],
                })
            else:
                rejected.append(attempt)

        history.append(iter_result)

    # 4. Persist accepted
    submitted: list[dict] = []
    for c in accepted:
        try:
            submitted.append(_persist_accepted(c, user_id, analysis_text, final_llm_meta))
        except Exception as e:
            rejected.append({
                'candidate_type': c.get('candidate_type'),
                'symbol': c.get('symbol'),
                'timeframe': c.get('timeframe'),
                'passed': True,        # 自测过了但 persist 失败
                'reason': f'persist failed: {type(e).__name__}: {e}',
                'metrics': c.get('metrics'),
            })
    if submitted:
        db.session.commit()

    return {
        'ok': True,
        'analysis': analysis_text,
        'submitted': submitted,
        'rejected': rejected,
        'iterations_used': len(history),
        'history': history,
        'llm_meta': final_llm_meta,
        'user_symbols': user_symbols,
        'references_used': len(profitable_refs),
    }
