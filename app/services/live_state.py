"""Phase 7.2: 每策略 live state — 給 Dashboard 顯示「現在指標值 / 距離觸發還差多少」

每個 strategy_type 一個 handler。LLM 翻譯的 cand_* 策略走 generic fallback
（最後收盤價 + SMA20 距離 + 上次成交時間），不會 crash 也不會空白。

只用最近 ~200 根 K 線（足夠所有指標 warmup）。每張卡的 indicators 是 dict
of {label, value, hint}，UI 直接渲染。
"""
from __future__ import annotations

import pandas as pd
import ta
from datetime import datetime
from typing import Callable

from app.extensions import db
from app.models import Strategy, Candle, Trade


def _fetch_candles_df(symbol: str, timeframe: str, n: int = 200) -> pd.DataFrame | None:
    rows = (Candle.query.filter_by(symbol=symbol, timeframe=timeframe)
            .order_by(Candle.timestamp.desc()).limit(n).all())
    if not rows:
        return None
    df = pd.DataFrame([r.to_dict() for r in rows]).sort_values('timestamp').reset_index(drop=True)
    return df


def _last_trade_time(strategy_id: int) -> str | None:
    t = (Trade.query.filter_by(strategy_id=strategy_id)
         .order_by(Trade.exit_time.desc()).first())
    return t.exit_time.isoformat() if t and t.exit_time else None


def _state_rsi(df: pd.DataFrame, params: dict) -> dict:
    p = params or {}
    period = p.get('period', 14)
    oversold = p.get('oversold', 30)
    overbought = p.get('overbought', 70)
    rsi = ta.momentum.rsi(df['close'], window=period).iloc[-1]
    rsi = float(rsi) if pd.notna(rsi) else None
    if rsi is None:
        return {'indicators': [], 'hint': 'RSI 計算中（K 線不足）'}
    return {
        'indicators': [
            {'label': f'RSI({period})', 'value': f'{rsi:.1f}'},
            {'label': '阈值', 'value': f'{oversold}/{overbought}'},
        ],
        'hint': (
            f'觸發 buy: RSI 從超賣 {oversold} 上穿（現 {rsi:.1f}，{"待回升" if rsi < oversold else f"離 {oversold} 還 {rsi-oversold:.1f}"}）；'
            f'觸發 sell: RSI 從超買 {overbought} 下穿（離 {overbought} 還 {overbought-rsi:.1f}）'
        ),
    }


def _state_supertrend(df: pd.DataFrame, params: dict) -> dict:
    p = params or {}
    period = p.get('period', 10)
    mult = p.get('multiplier', 3)
    atr = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=period).average_true_range().iloc[-1]
    close = float(df['close'].iloc[-1])
    upper = (df['high'].iloc[-1] + df['low'].iloc[-1]) / 2 + mult * atr
    lower = (df['high'].iloc[-1] + df['low'].iloc[-1]) / 2 - mult * atr
    return {
        'indicators': [
            {'label': 'close', 'value': f'${close:.0f}'},
            {'label': 'ATR', 'value': f'{atr:.1f}'},
            {'label': 'upper', 'value': f'${upper:.0f}'},
            {'label': 'lower', 'value': f'${lower:.0f}'},
        ],
        'hint': f'close < lower band ({close - lower:+.0f}) → 翻空；close > upper band ({close - upper:+.0f}) → 翻多',
    }


def _state_volatility_breakout(df: pd.DataFrame, params: dict) -> dict:
    """Donchian"""
    p = params or {}
    period = p.get('donchian_period', 20)
    upper = float(df['high'].rolling(period).max().iloc[-2])  # 前一根的最高（lookahead-safe）
    lower = float(df['low'].rolling(period).min().iloc[-2])
    close = float(df['close'].iloc[-1])
    return {
        'indicators': [
            {'label': 'close', 'value': f'${close:.0f}'},
            {'label': f'{period}-high', 'value': f'${upper:.0f}'},
            {'label': f'{period}-low', 'value': f'${lower:.0f}'},
        ],
        'hint': f'突破 {period}-high {upper:.0f} ({close - upper:+.0f}) → buy；跌破 {period}-low {lower:.0f} ({close - lower:+.0f}) → sell',
    }


def _state_vwap_reversion(df: pd.DataFrame, params: dict) -> dict:
    p = params or {}
    period = p.get('period', 20)
    dev = p.get('deviation_pct', 1.0)
    typical = (df['high'] + df['low'] + df['close']) / 3
    cum_pv = (typical * df['volume']).rolling(period).sum()
    cum_v = df['volume'].rolling(period).sum()
    vwap = (cum_pv / cum_v).iloc[-1]
    close = float(df['close'].iloc[-1])
    diff_pct = (close - vwap) / vwap * 100
    return {
        'indicators': [
            {'label': 'close', 'value': f'${close:.0f}'},
            {'label': f'VWAP({period})', 'value': f'${vwap:.0f}'},
            {'label': '偏離', 'value': f'{diff_pct:+.2f}%'},
        ],
        'hint': f'偏離 ≤ -{dev}% → buy（現 {diff_pct:+.2f}%）；偏離 ≥ +{dev}% → sell',
    }


def _state_ichimoku(df: pd.DataFrame, params: dict) -> dict:
    p = params or {}
    tenkan = p.get('tenkan', 9)
    kijun = p.get('kijun', 26)
    sen_b = p.get('senkou_b', 52)
    high = df['high']; low = df['low']
    tenkan_v = (high.rolling(tenkan).max() + low.rolling(tenkan).min()) / 2
    kijun_v = (high.rolling(kijun).max() + low.rolling(kijun).min()) / 2
    senkou_a = (tenkan_v + kijun_v) / 2
    senkou_b = (high.rolling(sen_b).max() + low.rolling(sen_b).min()) / 2
    cloud_top = max(senkou_a.iloc[-1], senkou_b.iloc[-1])
    cloud_bot = min(senkou_a.iloc[-1], senkou_b.iloc[-1])
    close = float(df['close'].iloc[-1])
    return {
        'indicators': [
            {'label': 'close', 'value': f'${close:.0f}'},
            {'label': '雲頂', 'value': f'${cloud_top:.0f}'},
            {'label': '雲底', 'value': f'${cloud_bot:.0f}'},
            {'label': 'Tenkan', 'value': f'${float(tenkan_v.iloc[-1]):.0f}'},
            {'label': 'Kijun', 'value': f'${float(kijun_v.iloc[-1]):.0f}'},
        ],
        'hint': f'close 突破雲頂 ${cloud_top:.0f} ({close - cloud_top:+.0f}) → buy；跌破雲底 ${cloud_bot:.0f} ({close - cloud_bot:+.0f}) → sell',
    }


def _state_psar(df: pd.DataFrame, params: dict) -> dict:
    p = params or {}
    step = p.get('step', 0.02)
    mx = p.get('max_step', 0.2)
    psar = ta.trend.PSARIndicator(df['high'], df['low'], df['close'], step=step, max_step=mx).psar().iloc[-1]
    close = float(df['close'].iloc[-1])
    return {
        'indicators': [
            {'label': 'close', 'value': f'${close:.0f}'},
            {'label': 'PSAR', 'value': f'${psar:.0f}'},
        ],
        'hint': f'close > PSAR → 多頭；< PSAR → 空頭。當前差 {close - psar:+.0f}（翻向會出信號）',
    }


def _state_weekly_pivot(df: pd.DataFrame, params: dict) -> dict:
    p = params or {}
    lookback = p.get('lookback', 42)
    sub = df.tail(lookback)
    hi = float(sub['high'].max())
    lo = float(sub['low'].min())
    cl = float(sub['close'].iloc[-1])
    pivot = (hi + lo + cl) / 3
    r1 = 2 * pivot - lo
    s1 = 2 * pivot - hi
    close = float(df['close'].iloc[-1])
    return {
        'indicators': [
            {'label': 'close', 'value': f'${close:.0f}'},
            {'label': 'Pivot', 'value': f'${pivot:.0f}'},
            {'label': 'R1', 'value': f'${r1:.0f}'},
            {'label': 'S1', 'value': f'${s1:.0f}'},
        ],
        'hint': f'突破 R1 ${r1:.0f} ({close - r1:+.0f}) → buy；跌破 S1 ${s1:.0f} ({close - s1:+.0f}) → sell',
    }


def _state_generic(df: pd.DataFrame, params: dict) -> dict:
    """fallback：未知 strategy_type（含 LLM 翻譯的 cand_*）— 顯示通用指標"""
    close = float(df['close'].iloc[-1])
    sma20 = float(df['close'].rolling(20).mean().iloc[-1]) if len(df) >= 20 else None
    rsi = ta.momentum.rsi(df['close'], window=14).iloc[-1] if len(df) >= 20 else None
    return {
        'indicators': [
            {'label': 'close', 'value': f'${close:.0f}'},
            *([{'label': 'SMA(20)', 'value': f'${sma20:.0f}', 'hint': f'{(close - sma20)/sma20*100:+.2f}%'}] if sma20 else []),
            *([{'label': 'RSI(14)', 'value': f'{float(rsi):.1f}'}] if pd.notna(rsi) else []),
        ],
        'hint': '（自訂策略，看翻譯產物的 signal_fn 邏輯）',
    }


_HANDLERS: dict[str, Callable[[pd.DataFrame, dict], dict]] = {
    'rsi': _state_rsi,
    'supertrend': _state_supertrend,
    'volatility_breakout': _state_volatility_breakout,
    'vwap_reversion': _state_vwap_reversion,
    'ichimoku': _state_ichimoku,
    'psar': _state_psar,
    'weekly_pivot': _state_weekly_pivot,
    # 其餘類型走 generic
}


def compute_live_state(strategy: Strategy) -> dict:
    """單一策略的 live state。失敗時回傳 error 字段，UI 顯示出來。"""
    base = {
        'id': strategy.id,
        'name': strategy.name,
        'type': strategy.type,
        'category': strategy.category,
        'symbol': strategy.symbol,
        'timeframe': strategy.timeframe,
        'last_trade': _last_trade_time(strategy.id),
    }
    df = _fetch_candles_df(strategy.symbol, strategy.timeframe)
    if df is None or len(df) < 30:
        base.update({'error': 'K 線不足', 'indicators': [], 'hint': '等下次 fetch_market_data 跑完'})
        return base
    handler = _HANDLERS.get(strategy.type, _state_generic)
    try:
        out = handler(df, strategy.params or {})
        base.update(out)
    except Exception as e:
        base.update({'error': f'{type(e).__name__}: {e}', 'indicators': [], 'hint': ''})
    return base


def all_live_states() -> list:
    # 14k-160: 多租户隔离 — 用 scoped_query 而非裸 Strategy.query (admin/Celery 看全部, 用户只看自己,
    # 未登录看空). 修 /strategies/live-state 此前泄漏所有用户 running 策略动向的污染洞.
    from app.services.user_scope import scoped_query
    strategies = scoped_query(Strategy).filter(Strategy.status == 'running').order_by(Strategy.id).all()
    return [compute_live_state(s) for s in strategies]
