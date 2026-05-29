"""Phase 10.3: market regime detection.

ADX measures trend strength; Hurst measures persistence.

Combined label:
- strong_trend : ADX > 25 AND Hurst > 0.55
- weak_trend   : (ADX 18-25 OR Hurst 0.5-0.55) and not range
- range        : ADX < 18 AND Hurst < 0.48
- unknown      : not enough candles

Each strategy type has a regime affinity (trend_follower / mean_reverter /
breakout). The UI can then highlight strategies whose affinity is
mismatched to the current regime (e.g. a mean-reverter running in a
strong trend = likely to bleed).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import ta

from app.services.exchange_service import fetch_ohlcv
from app.services.cache import cached


STRATEGY_AFFINITY = {
    # trend-followers
    'trend_following': 'trend_follower',
    'golden_cross': 'trend_follower',
    'supertrend': 'trend_follower',
    'ichimoku': 'trend_follower',
    'psar': 'trend_follower',
    'macd': 'trend_follower',
    'macd_trend_filter': 'trend_follower',
    'ma_crossover': 'trend_follower',
    'tema': 'trend_follower',
    'heikin_ashi': 'trend_follower',
    # mean-reverters
    'rsi': 'mean_reverter',
    'vwap_reversion': 'mean_reverter',
    'bollinger': 'mean_reverter',
    'mean_reversion': 'mean_reverter',
    'stochastic': 'mean_reverter',
    'cci_reversal': 'mean_reverter',
    # breakouts (work in either trend, bad in tight range)
    'volatility_breakout': 'breakout',
    'atr_breakout': 'breakout',
    'keltner_channel': 'breakout',
    'weekly_pivot': 'breakout',
    # Phase 14k-44: catalog clone base types (剥 _uX_<ts> 后缀后的)
    'cand_cat_adx_di_trend': 'trend_follower',
    'cand_cat_ema_ribbon_gmma': 'trend_follower',
    'cand_cat_macd_ema200': 'trend_follower',
    'cand_cat_psar_flip': 'trend_follower',
    'cand_cat_supertrend_atr': 'trend_follower',
    'cand_cat_ichimoku_cloud_break': 'trend_follower',
    'cand_cat_aroon_cross': 'trend_follower',
    'cand_cat_roc_trend': 'trend_follower',
    'cand_cat_rsi_momentum_trend': 'trend_follower',
    'cand_cat_obv_trend_confirm': 'trend_follower',
    'cand_cat_volume_spike_trend': 'trend_follower',
    'cand_cat_heikin_ashi_ema': 'trend_follower',
    'cand_cat_triple_screen_elder': 'trend_follower',
    'cand_cat_donchian_turtle': 'trend_follower',
    'cand_cat_atr_chandelier': 'trend_follower',
    'cand_cat_cci_extremes': 'mean_reverter',
    'cand_cat_rsi_bb_mean_rev': 'mean_reverter',
    'cand_cat_stoch_rsi_extremes': 'mean_reverter',
    'cand_cat_williams_r_reversal': 'mean_reverter',
    'cand_cat_zscore_returns': 'mean_reverter',
    'cand_cat_vwap_pullback': 'mean_reverter',
    'cand_cat_macd_rsi_divergence': 'mean_reverter',
    'cand_cat_pivot_classic_break': 'breakout',
    'cand_cat_orb_opening_range': 'breakout',
    'cand_cat_consolidation_vol_break': 'breakout',
    'cand_cat_bb_squeeze_breakout': 'breakout',
    'cand_cat_keltner_breakout': 'breakout',
    'cand_cat_ttm_squeeze': 'breakout',
    'cand_cat_bb_width_percentile': 'breakout',
    'cand_cat_atr_vol_expansion': 'breakout',
}

# affinity x regime -> 'good' | 'ok' | 'bad'
AFFINITY_FIT = {
    'trend_follower': {
        'strong_trend': 'good', 'weak_trend': 'ok',
        'range': 'bad', 'unknown': 'ok',
    },
    'mean_reverter': {
        'strong_trend': 'bad', 'weak_trend': 'ok',
        'range': 'good', 'unknown': 'ok',
    },
    'breakout': {
        'strong_trend': 'good', 'weak_trend': 'good',
        # 14k-151: range 'bad'→'ok'. breakout 策略 (尤其 squeeze/consolidation/pivot/bb_width)
        # 的 range 是"埋伏/setup 期"不是坏环境 — 它们专为"盘整→突破"设计, 在 range 不出信号
        # 是合理等待 (特征非缺陷). 旧 'bad' → fit_label bad → advisor 建议 pause →
        # full_auto 自动暂停 → 恰在突破前关掉策略 (逻辑自相矛盾 + 追市场屁股反面).
        # 改 'ok': 不 pause (让它埋伏等突破) 也不强推; 表现真烂的由 walkforward 双轨门退役
        # (backtest_is_truth — 看实际表现, 不靠 regime 预测性暂停).
        'range': 'ok', 'unknown': 'ok',
    },
}


def hurst_exponent(prices: np.ndarray, max_lag: int = 100) -> float | None:
    """Quick Hurst via lag-difference standard-deviation regression."""
    if prices is None or len(prices) < max_lag + 10:
        return None
    try:
        max_lag = min(max_lag, len(prices) // 2)
        lags = np.arange(2, max_lag)
        diffs = []
        for lag in lags:
            d = np.std(prices[lag:] - prices[:-lag])
            if d <= 0:
                return None
            diffs.append(d)
        slope = np.polyfit(np.log(lags), np.log(diffs), 1)[0]
        return float(slope)
    except Exception:
        return None


def _classify(adx: float | None, hurst: float | None) -> str:
    if adx is None and hurst is None:
        return 'unknown'
    a = adx if adx is not None else 0
    h = hurst if hurst is not None else 0.5
    if a >= 25 and h >= 0.55:
        return 'strong_trend'
    if a < 18 and h < 0.48:
        return 'range'
    if a >= 18 or h >= 0.5:
        return 'weak_trend'
    return 'range'


@cached('regime', ttl=120)
def detect_regime(symbol: str = 'BTC/USDT', timeframe: str = '4h', limit: int = 300) -> dict:
    """Compute regime for a single symbol+timeframe.

    Returns {symbol, timeframe, adx, hurst, regime, n, error?}.
    """
    try:
        candles = fetch_ohlcv(symbol, timeframe, limit=limit)
    except Exception as e:
        return {'symbol': symbol, 'timeframe': timeframe, 'error': f'fetch_ohlcv: {e}', 'regime': 'unknown'}

    if not candles or len(candles) < 60:
        return {
            'symbol': symbol, 'timeframe': timeframe,
            'adx': None, 'hurst': None, 'regime': 'unknown',
            'n': len(candles or []),
        }

    df = pd.DataFrame(candles)
    df = df.sort_values('timestamp').reset_index(drop=True)
    for col in ('high', 'low', 'close'):
        df[col] = pd.to_numeric(df[col], errors='coerce')

    try:
        adx_series = ta.trend.adx(df['high'], df['low'], df['close'], window=14)
        adx_val = float(adx_series.iloc[-1]) if not adx_series.dropna().empty else None
    except Exception:
        adx_val = None

    hurst_val = hurst_exponent(df['close'].values, max_lag=min(100, len(df) // 3))

    regime = _classify(adx_val, hurst_val)
    return {
        'symbol': symbol,
        'timeframe': timeframe,
        'adx': round(adx_val, 2) if adx_val is not None else None,
        'hurst': round(hurst_val, 3) if hurst_val is not None else None,
        'regime': regime,
        'n': len(df),
        'last_close': float(df['close'].iloc[-1]),
    }


def affinity_for(strategy_type: str) -> str | None:
    """exact 优先, 否则剥 catalog clone 后缀 _uX_<timestamp> 再 lookup."""
    aff = STRATEGY_AFFINITY.get(strategy_type)
    if aff:
        return aff
    # Phase 14k-44: catalog clone type 剥后缀 (cand_cat_xxx_u1_20260526xxxxxx → cand_cat_xxx)
    import re
    base = re.sub(r'_u\d+_\d{12,16}$', '', strategy_type or '')
    return STRATEGY_AFFINITY.get(base)


def fit_label(strategy_type: str, regime: str) -> str:
    """'good' / 'ok' / 'bad' / 'unknown'"""
    aff = affinity_for(strategy_type)
    if not aff:
        return 'unknown'
    return AFFINITY_FIT.get(aff, {}).get(regime, 'unknown')
