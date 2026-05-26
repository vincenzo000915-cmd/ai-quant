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

from app.services.backtest_engine import run_backtest, run_walkforward_backtest
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
    return GRIDS.get(strategy_type, {})


def grid_size(grid: dict[str, list]) -> int:
    n = 1
    for vs in grid.values():
        n *= len(vs)
    return n


def iter_combos(grid: dict[str, list]) -> Iterator[dict]:
    keys = list(grid.keys())
    for combo in itertools.product(*[grid[k] for k in keys]):
        yield dict(zip(keys, combo))


def _score_combo(strategy_type, params, candles, timeframe, slippage_pct, fee_pct, symbol=None):
    """跑一次 walk-forward，回傳精簡指標。"""
    wf = run_walkforward_backtest(
        strategy_type, params, candles,
        timeframe=timeframe,
        slippage_pct=slippage_pct,
        fee_pct=fee_pct,
        symbol=symbol,
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


def optimize(strategy, *, candle_limit: int = 2000, max_combos: int = 24,
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

    cfg = get_config()
    slippage = cfg.get('backtest_slippage_pct', 0.05)
    fee = cfg.get('backtest_fee_pct', 0.05)

    # 基線：strategy.params 自身
    baseline_params = dict(strategy.params or {})
    baseline = _score_combo(strategy.type, baseline_params, candles, strategy.timeframe, slippage, fee, symbol=strategy.symbol)
    baseline_oos = baseline.get('oos_sharpe')

    results = [baseline]
    if on_progress:
        on_progress(1, total + 1)

    combos = list(iter_combos(grid))
    for i, params in enumerate(combos, start=2):
        # 跳過跟 baseline 完全相同的組合
        if params == baseline_params:
            continue
        r = _score_combo(strategy.type, params, candles, strategy.timeframe, slippage, fee, symbol=strategy.symbol)
        results.append(r)
        if on_progress:
            on_progress(i, total + 1)

    # 排序：OOS Sharpe 降序，None 放最後
    def sort_key(r):
        s = r.get('oos_sharpe')
        return (s is None, -(s if s is not None else 0))
    results.sort(key=sort_key)

    best = results[0] if results and results[0].get('oos_sharpe') is not None else None

    return {
        'grid': grid,
        'grid_source': grid_source,
        'baseline_params': baseline_params,
        'baseline_oos_sharpe': baseline_oos,
        'candidate_results': results,
        'best_params': best['params'] if best else None,
        'best_oos_sharpe': best['oos_sharpe'] if best else None,
        'combos_total': total + 1,
        'combos_done': len(results),
    }
