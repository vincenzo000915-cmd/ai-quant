"""Phase 10.4: multi-timeframe consensus diagnostic.

Read-only check: for a given strategy run its signal function at several
timeframes (e.g. 15m / 1h / 4h / 1d) using the same params and report
what each TF says right now plus an aggregate consensus.

Does NOT change the live signal path — it is a dashboard view that lets
you see whether your 4h trend setup is currently arguing with the 15m
flow or whether they agree.
"""
from __future__ import annotations

import pandas as pd

from app.services.exchange_service import fetch_ohlcv
from app.services.strategy_engine import get_signal, get_candle_df
from app.services.cache import cached


DEFAULT_TFS = ['15m', '1h', '4h', '1d']
MIN_CANDLES = 100


@cached('mtf_signal', ttl=120)
def signal_at_tf(strategy_type: str, params: dict, symbol: str, timeframe: str) -> dict:
    """Returns {tf, signal, n, error?}."""
    try:
        candles = fetch_ohlcv(symbol, timeframe, limit=300)
    except Exception as e:
        return {'tf': timeframe, 'signal': 'error', 'error': f'fetch: {e}', 'n': 0}

    if not candles or len(candles) < MIN_CANDLES:
        return {'tf': timeframe, 'signal': 'insufficient', 'n': len(candles or [])}

    try:
        df = get_candle_df(candles)
        sig = get_signal(strategy_type, df, params or {})
    except Exception as e:
        return {'tf': timeframe, 'signal': 'error', 'error': f'signal: {type(e).__name__}: {e}', 'n': len(candles)}

    return {
        'tf': timeframe,
        'signal': sig,                         # 'buy' / 'sell' / 'hold'
        'n': len(candles),
        'last_close': float(candles[-1]['close']),
    }


def _consensus(signals: list[dict]) -> dict:
    """Aggregate per-TF signals to a single consensus.

    consensus ∈ {strong_buy, lean_buy, mixed, hold_all, lean_sell, strong_sell, insufficient}
    """
    valid = [s for s in signals if s['signal'] in ('buy', 'sell', 'hold')]
    if not valid:
        return {'label': 'insufficient', 'buy': 0, 'sell': 0, 'hold': 0, 'total': len(signals)}

    counts = {'buy': 0, 'sell': 0, 'hold': 0}
    for s in valid:
        counts[s['signal']] += 1

    n = len(valid)
    b, se, h = counts['buy'], counts['sell'], counts['hold']

    if b == n:
        label = 'strong_buy'
    elif se == n:
        label = 'strong_sell'
    elif b > 0 and se == 0:
        label = 'lean_buy'
    elif se > 0 and b == 0:
        label = 'lean_sell'
    elif b > 0 and se > 0:
        label = 'mixed'         # 衝突 — 不同 TF 互相矛盾
    else:
        label = 'hold_all'

    return {'label': label, 'buy': b, 'sell': se, 'hold': h, 'total': n}


def mtf_check(strategy, tfs: list[str] | None = None) -> dict:
    """Run signal at each requested TF + summarize consensus."""
    tfs = tfs or DEFAULT_TFS
    results = [signal_at_tf(strategy.type, strategy.params or {}, strategy.symbol, tf) for tf in tfs]
    cons = _consensus(results)
    return {
        'strategy_id': strategy.id,
        'name': strategy.name,
        'type': strategy.type,
        'symbol': strategy.symbol,
        'base_tf': strategy.timeframe,
        'per_tf': results,
        'consensus': cons,
    }
