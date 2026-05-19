"""Phase 9.4: 計算每筆開倉的絕對止損 / 止盈價

兩種模式：
- 'flat_pct'：回傳 None — 用 SystemConfig 的 stop_loss_pct / take_profit_pct 算（原本行為）
- 'atr'    ：取最近 N 根 K 線 ATR，sl = entry ± k×ATR，tp = entry ± k×ATR
            （long 是 entry - k×ATR_sl, entry + k×ATR_tp；short 反之）

ATR 用該策略自己的 timeframe 計算（最近 ~50 根）。
"""
from __future__ import annotations

import pandas as pd
import ta
from app.models import Candle


def _fetch_candle_df(symbol: str, timeframe: str, n: int = 60):
    rows = (Candle.query.filter_by(symbol=symbol, timeframe=timeframe)
            .order_by(Candle.timestamp.desc()).limit(n).all())
    if len(rows) < 20:
        return None
    df = pd.DataFrame([r.to_dict() for r in rows]).sort_values('timestamp').reset_index(drop=True)
    return df


def compute_sl_tp(*, symbol: str, timeframe: str, side: str, entry_price: float, cfg: dict) -> tuple[float | None, float | None, dict]:
    """回傳 (sl_price, tp_price, debug)。flat_pct mode 回 (None, None, …)"""
    mode = cfg.get('sl_mode', 'flat_pct')
    if mode == 'flat_pct':
        return None, None, {'mode': 'flat_pct'}

    if mode == 'atr':
        period = int(cfg.get('atr_period', 14))
        sl_mult = float(cfg.get('atr_sl_mult', 2.0))
        tp_mult = float(cfg.get('atr_tp_mult', 3.0))
        df = _fetch_candle_df(symbol, timeframe, n=max(period * 4, 60))
        if df is None or len(df) < period + 5:
            return None, None, {'mode': 'atr', 'fallback': f'candle 不足 (have {0 if df is None else len(df)}, need {period+5})'}
        atr = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=period).average_true_range().iloc[-1]
        atr = float(atr) if pd.notna(atr) else 0.0
        if atr <= 0:
            return None, None, {'mode': 'atr', 'fallback': 'ATR=0'}

        if side == 'long':
            sl = entry_price - sl_mult * atr
            tp = entry_price + tp_mult * atr
        else:  # short
            sl = entry_price + sl_mult * atr
            tp = entry_price - tp_mult * atr
        return float(sl), float(tp), {
            'mode': 'atr', 'period': period, 'atr': round(atr, 2),
            'sl_mult': sl_mult, 'tp_mult': tp_mult,
            'sl_dist_pct': round((entry_price - sl) / entry_price * 100, 3) if side == 'long' else round((sl - entry_price) / entry_price * 100, 3),
        }

    return None, None, {'mode': mode, 'fallback': 'unknown mode'}
