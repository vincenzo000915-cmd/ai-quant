"""Phase 14k-29 L4: AI risk 闪测 — SL/TP 网格 walk-forward search.

只搜 SL/TP (会动 PnL, 必须回测验证才能 apply); leverage/position_size 不参与
(那两个 backtest 不覆盖, 由 L3 启发式直接调).

跑一次 walk-forward 找 OOS Sharpe + DD 最优组合, 过门槛就 apply.
评分: Sharpe - DD/20 (DD 30% → -1.5; DD 10% → -0.5; 鼓励高 Sharpe + 低 DD).

14k-47: grid 按 TF 分级 — 15m scalp grid 3-10% 太宽永远 not qualified
(scalp 该 SL 0.5-2%). 跟 backtest_engine.TF_DEFAULT_SL_TP 对齐.
"""
from __future__ import annotations

# 14k-47: TF-aware risk grid (业界标准 scalp ↔ swing ↔ position 不同范围)
TF_RISK_GRIDS = {
    '15m': {'sl_pct': [0.5, 1.0, 1.5, 2.5], 'tp_pct': [1.0, 2.0, 3.0, 5.0]},
    '30m': {'sl_pct': [0.8, 1.5, 2.5, 4.0], 'tp_pct': [1.5, 3.0, 5.0, 8.0]},
    '1h':  {'sl_pct': [1.5, 2.5, 4.0, 6.0], 'tp_pct': [3.0, 5.0, 8.0, 12.0]},
    '4h':  {'sl_pct': [3, 5, 7, 10],        'tp_pct': [6, 10, 15, 20]},   # 旧默认
    '1d':  {'sl_pct': [5, 10, 15, 20],      'tp_pct': [10, 18, 28, 40]},
}
DEFAULT_RISK_GRID = TF_RISK_GRIDS['4h']    # 向后兼容: 默认仍是 4h


def grid_for_tf(timeframe: str) -> dict:
    """按 timeframe 返回 risk grid. 未知 TF fallback 4h."""
    return TF_RISK_GRIDS.get(timeframe or '4h', TF_RISK_GRIDS['4h'])
MIN_TP_OVER_SL = 1.2     # TP 至少是 SL 的 1.2 倍 (R:R 守门)
LIFT_THRESHOLD = 0.3     # best score 比 baseline 提升 ≥ 0.3 才 apply
MIN_OOS_SHARPE = 0.5     # apply 后的 OOS Sharpe 至少要 ≥ 0.5
MIN_TRADES = 5           # 候选组合 OOS trades < 5 直接 -999 (不可信)


def optimize_risk_params(strategy, grid: dict | None = None) -> dict:
    """跑 SL/TP grid walk-forward, 返回 baseline + best 候选 + 全部 scored 候选.

    14k-47: grid 自动按 strategy.timeframe (15m 用 0.5-2.5%, 4h 用 3-10%).
    """
    from app.services.backtest_engine import run_walkforward_backtest
    from app.services.exchange_service import fetch_ohlcv_history

    grid = grid or grid_for_tf(strategy.timeframe)

    candles = fetch_ohlcv_history(strategy.symbol, strategy.timeframe, total_limit=2000)
    if not candles or len(candles) < 200:
        return {'error': f'K 线不足 ({len(candles) if candles else 0} < 200)'}

    # Phase 14k-102: walk-forward 多 combo CPU 重 (5-30min), 期间 implicit tx idle 必被 PG kill
    # 14k-92 修了 task 入口 commit, 但 fetch_ohlcv_history SELECT candles 又开 implicit tx
    # 跑多次 _run_wf (CPU only, 不动 DB) 期间 tx 一直 idle → audit 写 INSERT 必失败
    # 修: fetch K 线后立刻 commit 释放 tx, 长 CPU 期间 connection 是 idle 不是 idle-in-tx
    from app.extensions import db as _db
    try:
        _db.session.commit()
    except Exception:
        try:
            _db.session.rollback()
        except Exception:
            pass

    base_params = dict(strategy.params or {})
    base_rp = base_params.get('risk_params') or {}
    base_sl = float(base_rp.get('sl_pct') or base_rp.get('stop_loss_pct') or 5)
    base_tp = float(base_rp.get('tp_pct') or base_rp.get('take_profit_pct') or 8)

    baseline_metrics = _run_wf(strategy, base_params, candles, base_sl, base_tp)
    baseline_score = _score(baseline_metrics)

    candidates = []
    for sl in grid['sl_pct']:
        for tp in grid['tp_pct']:
            if tp < sl * MIN_TP_OVER_SL:
                continue
            if abs(sl - base_sl) < 0.01 and abs(tp - base_tp) < 0.01:
                continue
            metrics = _run_wf(strategy, base_params, candles, sl, tp)
            metrics['sl_pct'] = sl
            metrics['tp_pct'] = tp
            metrics['score'] = _score(metrics)
            candidates.append(metrics)

    candidates.sort(key=lambda x: x['score'], reverse=True)
    best = candidates[0] if candidates and candidates[0]['score'] > -900 else None

    return {
        'baseline': {
            'sl_pct': base_sl,
            'tp_pct': base_tp,
            'score': baseline_score,
            **baseline_metrics,
        },
        'best': best,
        'candidates': candidates,
        'grid': grid,
        'symbol': strategy.symbol,
        'timeframe': strategy.timeframe,
    }


def _run_wf(strategy, base_params, candles, sl, tp):
    """跑一次 walk-forward, 把 SL/TP 注入 backtest_engine kwargs."""
    from app.services.backtest_engine import run_walkforward_backtest, resolve_backtest_risk_kwargs
    try:
        # 14k-146 (D1): 用策略实际 leverage (而非默认 15) — SL 是杠杆后%, lev 必须一致,
        # 否则搜出的 SL 在实盘有效价格距离是错的. sl/tp 用本轮网格值覆盖.
        _rk = resolve_backtest_risk_kwargs(strategy)
        _rk['stop_loss_pct'] = float(sl)
        _rk['take_profit_pct'] = float(tp)
        wf = run_walkforward_backtest(
            strategy.type, base_params, candles,
            timeframe=strategy.timeframe,
            symbol=strategy.symbol,
            **_rk,
        )
    except Exception as e:
        return {'oos_sharpe': None, 'oos_dd': None, 'oos_trades': 0, 'error': f'{type(e).__name__}: {e}'}

    if wf.get('status') == 'error':
        return {'oos_sharpe': None, 'oos_dd': None, 'oos_trades': 0, 'error': wf.get('error_message')}

    oos = wf.get('out_sample') or {}
    full = wf.get('full') or {}
    # 14k-69: 加 EV 字段 — risk_optimizer score 也参考盈利率
    oos_trades = oos.get('total_trades') or 0
    oos_pnl = oos.get('total_pnl') or 0
    oos_capital = oos.get('initial_capital') or 100.0
    return {
        'oos_sharpe': oos.get('sharpe_ratio'),
        'oos_dd': oos.get('max_drawdown_pct'),
        'oos_trades': oos_trades,
        'oos_ar': oos.get('annual_return_pct'),
        'oos_ev_pct': (oos_pnl / oos_trades / oos_capital * 100) if oos_trades else 0.0,
        'full_sharpe': full.get('sharpe_ratio'),
        'full_pnl': full.get('total_pnl'),
    }


def _score(metrics: dict) -> float:
    """评分 (14k-69 升级): Sharpe + EV 综合, DD penalty. 无 trades → -999.
    user 哲学: 追盈利率, 所以 EV 加权; Sharpe 仍参考 (低 sharpe + 高 EV 可能 noise 大).
    """
    trades = metrics.get('oos_trades') or 0
    if trades < MIN_TRADES:
        return -999.0
    s = metrics.get('oos_sharpe') or 0
    dd = abs(metrics.get('oos_dd') or 50)
    ev = metrics.get('oos_ev_pct') or 0
    # Score = Sharpe + EV_score (1% EV = +2 score) - DD/20
    # 例: sharpe 1.0 + EV 0.5% + DD 10% = 1.0 + 1.0 - 0.5 = 1.5
    return s + (ev * 2.0) - (dd / 20.0)


def should_apply(opt_result: dict) -> tuple[bool, str]:
    """检查 best 是否过 apply 门槛."""
    best = opt_result.get('best')
    base = opt_result.get('baseline')
    if not best:
        return False, '无可用候选 (全部 trades 不足或回测出错)'
    lift = best['score'] - base['score']
    if lift < LIFT_THRESHOLD:
        return False, f'lift {lift:.2f} < 门槛 {LIFT_THRESHOLD}'
    if (best.get('oos_sharpe') or 0) < MIN_OOS_SHARPE:
        return False, f'best OOS Sharpe {best.get("oos_sharpe")} < {MIN_OOS_SHARPE}'
    return True, f'lift={lift:.2f}, OOS Sharpe={best.get("oos_sharpe"):.2f}'
