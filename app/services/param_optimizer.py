"""Phase 10.2: Walk-forward parameter grid search.

For each parameter combination we run a 70/30 walk-forward backtest and
score by OOS Sharpe (the only honest signal — IS sharpe always inflates
because the params were chosen on that data).

Candles are fetched ONCE per optimization and reused across combos, which
is the only reason this is tractable inside a single Celery task.

The grid for each strategy_type is intentionally small (2-3 params,
3-4 values each) so a full sweep stays under ~2 minutes.
"""
from __future__ import annotations

import itertools
import time
from typing import Iterator

from app.services.backtest_engine import run_backtest, run_walkforward_backtest, resolve_backtest_risk_kwargs
from app.services.exchange_service import fetch_ohlcv_history
from app.services.config_service import get_config


# ---- 每策略的搜尋網格 ----
# 鍵 = strategy_type；值 = {param_name: [values]}
# 設計原則：覆蓋常見區間，但組合 <= 24 確保 walk-forward 一次跑得完
GRIDS: dict[str, dict[str, list]] = {
    'volatility_breakout': {
        'donchian_period': [10, 15, 20, 30],
        'atr_period': [10, 14, 20],
    },
    'supertrend': {
        'period': [7, 10, 14, 20],
        'multiplier': [2.0, 2.5, 3.0, 3.5],
    },
    'vwap_reversion': {
        'period': [10, 20, 30],
        'deviation_pct': [0.5, 1.0, 1.5, 2.0],
    },
    'ichimoku': {
        'tenkan': [7, 9, 12],
        'kijun': [22, 26, 30],
        'senkou_b': [44, 52, 60],
    },
    'psar': {
        'step': [0.01, 0.02, 0.03],
        'max_step': [0.1, 0.2, 0.3],
    },
    'weekly_pivot': {
        'lookback': [28, 35, 42, 56],
    },
    # Wave-1 其他常用策略
    'rsi': {
        'period': [10, 14, 21],
        'oversold': [20, 25, 30],
        'overbought': [70, 75, 80],
    },
    'macd': {
        'fast': [8, 12, 16],
        'slow': [21, 26, 32],
        'signal': [7, 9, 11],
    },
    'bollinger': {
        'window': [15, 20, 30],
        'std': [1.8, 2.0, 2.5],
    },
    'ma_crossover': {
        'fast': [5, 7, 10, 15],
        'slow': [20, 25, 35, 50],
    },
    'trend_following': {
        'fast_ema': [7, 9, 12],
        'slow_ema': [18, 21, 28],
        'adx_threshold': [20, 25, 30],
    },
    'mean_reversion': {
        'bb_period': [15, 20, 30],
        'bb_std': [2.0, 2.5, 3.0],
    },
    'tema': {
        'fast': [7, 10, 14],
        'slow': [25, 30, 40],
    },
    'stochastic': {
        'k_period': [9, 14, 21],
        'oversold': [15, 20, 25],
        'overbought': [75, 80, 85],
    },
    'cci_reversal': {
        'period': [14, 20, 28],
        'threshold': [80, 100, 150],
    },
    # Phase 14k-39: catalog clone strategy types — 让 advisor.apply_params 能优化它们
    'cand_cat_cci_extremes': {
        'period': [14, 20, 28],
        'lower': [-150, -100, -80],
        'upper': [80, 100, 150],
    },
    'cand_cat_rsi_bb_mean_rev': {
        'rsi_period': [10, 14, 21],
        'rsi_low': [25, 30, 35],
        'rsi_high': [65, 70, 75],
    },
    'cand_cat_stoch_rsi_extremes': {
        'rsi_period': [10, 14, 21],
        'oversold': [15, 20, 25],
        'overbought': [75, 80, 85],
    },
    'cand_cat_williams_r_reversal': {
        'period': [10, 14, 21],
        'oversold': [-85, -80, -75],
        'overbought': [-25, -20, -15],
    },
    'atr_breakout': {
        'ema_period': [15, 20, 30],
        'multiplier': [1.0, 1.5, 2.0],
    },
    'keltner_channel': {
        'ema_period': [15, 20, 30],
        'multiplier': [1.5, 2.0, 2.5],
    },
    'heikin_ashi': {
        'confirm_bars': [2, 3, 4, 5],
    },
    'golden_cross': {
        'fast': [40, 50, 60],
        'slow': [180, 200, 220],
    },
    'macd_trend_filter': {
        'fast': [8, 12, 16],
        'slow': [21, 26, 32],
        'ma': [150, 200, 250],
    },
}


def get_grid(strategy_type: str) -> dict[str, list]:
    """exact match 优先, 否则剥 catalog clone 后缀 (_uX_<timestamp>) 再 match.

    Phase 14k-39: catalog clone 走 cand_cat_xxx_u1_<ts> 这种 type, 直接 lookup 永远 None.
    剥后缀: cand_cat_cci_extremes_u1_20260526095930 → cand_cat_cci_extremes
    """
    g = GRIDS.get(strategy_type, {})
    if g:
        return g
    import re
    base = re.sub(r'_u\d+_\d{12,16}$', '', strategy_type)
    if base != strategy_type:
        return GRIDS.get(base, {})
    return {}


def grid_size(grid: dict[str, list]) -> int:
    n = 1
    for vs in grid.values():
        n *= len(vs)
    return n


def iter_combos(grid: dict[str, list]) -> Iterator[dict]:
    keys = list(grid.keys())
    for combo in itertools.product(*[grid[k] for k in keys]):
        yield dict(zip(keys, combo))


# Phase 14k-147 (D2): 风险维进网格 — grid 用 _lev/_sl/_tp 前缀键携带风险参数.
# 前缀 _ 与 grid_proposer 的 `_` 排除约定、get_signal 白名单忽略额外键一致 → 信号侧零干扰.
RISK_GRID_KEYS = {'_lev': 'leverage', '_sl': 'stop_loss_pct', '_tp': 'take_profit_pct'}
MIN_TP_OVER_SL = 1.2      # R:R 守门 (同 risk_optimizer)
MIN_PRICE_SL_PCT = 0.8    # 有效价格止损下限% = sl_pct/leverage, 砍"高杠杆窄SL被噪音扫"的病态格子


def split_combo(combo: dict) -> tuple[dict, dict]:
    """把一个 combo dict 拆成 (signal_params, risk_kwargs).
    signal_params = 非 RISK_GRID_KEYS 的键 (喂 get_signal);
    risk_kwargs = {leverage/stop_loss_pct/take_profit_pct: v} (走回测 kwargs)."""
    sig, risk = {}, {}
    for k, v in (combo or {}).items():
        if k in RISK_GRID_KEYS:
            risk[RISK_GRID_KEYS[k]] = v
        else:
            sig[k] = v
    return sig, risk


def _combo_viable(combo: dict, base_risk: dict) -> bool:
    """剪枝病态风险组合: tp>=sl*1.2 (R:R) + sl/lev>=0.8% (有效价格止损下限).
    用 combo 搜索的风险维 + base_risk 兜底未搜索维."""
    _, rk = split_combo(combo)
    eff = {**(base_risk or {}), **rk}
    sl = eff.get('stop_loss_pct'); tp = eff.get('take_profit_pct'); lev = eff.get('leverage')
    if sl and tp and tp < sl * MIN_TP_OVER_SL:
        return False
    if sl and lev and (sl / lev) < MIN_PRICE_SL_PCT:
        return False
    return True


def _score_combo(strategy_type, params, candles, timeframe, slippage_pct, fee_pct, symbol=None, base_risk=None):
    """跑一次 walk-forward，回傳精簡指標。
    14k-147 (D2): params 可含 _lev/_sl/_tp 风险维 → split 后只把 signal_params 喂回测的
    params (防 candidate signal_fn 误收脏键), 风险维走 kwargs (combo 覆盖 base_risk)."""
    sig_params, risk_override = split_combo(params)
    merged_risk = {**(base_risk or {}), **risk_override}
    wf = run_walkforward_backtest(
        strategy_type, sig_params, candles,
        timeframe=timeframe,
        slippage_pct=slippage_pct,
        fee_pct=fee_pct,
        symbol=symbol,
        **merged_risk,
    )
    if wf.get('status') == 'error':
        return {'params': params, 'error': wf.get('error_message', 'unknown')}

    is_seg = wf.get('in_sample') or {}
    oos_seg = wf.get('out_sample') or {}
    full = wf.get('full') or {}

    return {
        'params': params,
        'is_sharpe': is_seg.get('sharpe_ratio'),
        'oos_sharpe': oos_seg.get('sharpe_ratio'),
        'decay_pct': wf.get('decay_pct'),
        'is_trades': is_seg.get('total_trades'),
        'oos_trades': oos_seg.get('total_trades'),
        'is_ar': is_seg.get('annual_return_pct'),
        'oos_ar': oos_seg.get('annual_return_pct'),
        'is_maxdd': is_seg.get('max_drawdown_pct'),
        'oos_maxdd': oos_seg.get('max_drawdown_pct'),
        'full_sharpe': full.get('sharpe_ratio'),
        'full_pnl': full.get('total_pnl'),
        'full_trades': full.get('total_trades'),
    }


def optimize(strategy, *, candle_limit: int = 2000, max_combos: int = 48,
             on_progress=None, grid_override: dict | None = None) -> dict:
    """執行 walk-forward 網格搜尋。

    Phase 14k-30 #2: grid_override 不空时用它 (AI 提议的 grid), 否则 fallback 死字典 GRIDS.

    回傳 dict：(同前, 加 grid_source)
    """
    if grid_override:
        grid = grid_override
        grid_source = 'ai_proposed'
    else:
        grid = get_grid(strategy.type)
        grid_source = 'static_dict'
    if not grid:
        return {
            'error': f'strategy_type={strategy.type} 沒有定義網格，無法優化',
        }

    total = grid_size(grid)
    if total > max_combos:
        # 縮減：取每個 param 的等距子集直到組合 <= max_combos
        # 簡單做法：把每個 list 砍半直到符合
        trimmed = {k: list(v) for k, v in grid.items()}
        while grid_size(trimmed) > max_combos:
            longest_k = max(trimmed, key=lambda k: len(trimmed[k]))
            if len(trimmed[longest_k]) <= 2:
                break
            trimmed[longest_k] = trimmed[longest_k][::2]
        grid = trimmed
        total = grid_size(grid)

    # 抓一次 K 線重複用
    candles = fetch_ohlcv_history(strategy.symbol, strategy.timeframe, total_limit=candle_limit)
    if not candles or len(candles) < 200:
        return {'error': f'K 線不足（{len(candles) if candles else 0}）'}

    # Phase 14k-102: 同 risk_optimizer — fetch K 线后释放 implicit tx
    # 后续 grid walk-forward CPU 重 5-30min, 不释放 connection 必被 PG idle_in_tx kill
    from app.extensions import db as _db
    try:
        _db.session.commit()
    except Exception:
        try:
            _db.session.rollback()
        except Exception:
            pass

    cfg = get_config()
    slippage = cfg.get('backtest_slippage_pct', 0.05)
    fee = cfg.get('backtest_fee_pct', 0.05)

    # 14k-147 (D2): baseline 用策略实际 lev/SL/TP (与 D1 一致, 修回测固定15假象)
    base_risk = resolve_backtest_risk_kwargs(strategy)

    # 基線：strategy.params 自身
    baseline_params = dict(strategy.params or {})
    baseline = _score_combo(strategy.type, baseline_params, candles, strategy.timeframe, slippage, fee, symbol=strategy.symbol, base_risk=base_risk)
    baseline_oos = baseline.get('oos_sharpe')

    results = [baseline]
    if on_progress:
        on_progress(1, total + 1)

    # 14k-147 (D2): 剪枝病态风险组合 (tp>=sl*1.2 + sl/lev>=0.8%), 砍"高杠杆窄SL被噪音扫"格子
    combos = [c for c in iter_combos(grid) if _combo_viable(c, base_risk)]
    for i, params in enumerate(combos, start=2):
        # 跳過跟 baseline 完全相同的組合
        if params == baseline_params:
            continue
        r = _score_combo(strategy.type, params, candles, strategy.timeframe, slippage, fee, symbol=strategy.symbol, base_risk=base_risk)
        results.append(r)
        if on_progress:
            on_progress(i, total + 1)

    # 排序：OOS Sharpe 降序，None 放最後
    def sort_key(r):
        s = r.get('oos_sharpe')
        return (s is None, -(s if s is not None else 0))
    results.sort(key=sort_key)

    best = results[0] if results and results[0].get('oos_sharpe') is not None else None

    # 14k-147 (D2): 把 best 拆成信号维 + 风险维, 供 D4 分离写回 (signal→params, risk→risk_params)
    best_signal_params, best_risk_params = (None, {})
    if best:
        _sig, _risk = split_combo(best['params'])
        best_signal_params = _sig
        # 只含本次实际搜索的风险维 (grid 无 _lev/_sl/_tp → 空 → 写回时不动 risk_params)
        best_risk_params = dict(_risk)
        if 'stop_loss_pct' in best_risk_params:
            best_risk_params['sl_pct'] = best_risk_params['stop_loss_pct']   # alias 兼容
        if 'take_profit_pct' in best_risk_params:
            best_risk_params['tp_pct'] = best_risk_params['take_profit_pct']

    return {
        'grid': grid,
        'grid_source': grid_source,
        'baseline_params': baseline_params,
        'baseline_oos_sharpe': baseline_oos,
        'candidate_results': results,
        'best_params': best['params'] if best else None,
        'best_signal_params': best_signal_params,   # 14k-147 (D2): 纯信号维
        'best_risk_params': best_risk_params,        # 14k-147 (D2): 风险维 (可能空)
        'best_oos_sharpe': best['oos_sharpe'] if best else None,
        'combos_total': total + 1,
        'combos_done': len(results),
    }
