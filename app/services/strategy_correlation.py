"""Phase 10.1: Strategy PnL correlation matrix.

Pairwise Pearson correlation between strategies' daily PnL series.
Primary source = trades table (LIVE closed trades). When a strategy has
< MIN_OBS days of live data, fall back to its latest BacktestResult.trades_json
so a freshly-deployed system still shows useful diversification signal.

High correlation (> THRESHOLD) flags strategies that move together and adds
no real diversification — the user wants those surfaced.
"""
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import func

from app.extensions import db
from app.models import Strategy, Trade, BacktestResult

MIN_OBS = 5            # at least this many overlapping days to compute corr
THRESHOLD = 0.7        # flag pairs above this
MAX_STRATEGIES = 50    # cap matrix size


def _series_from_live(strategy_id: int) -> dict:
    """Daily PnL sum keyed by ISO date string. Empty dict if no closed trades."""
    rows = (
        db.session.query(Trade.exit_time, Trade.pnl)
        .filter(Trade.strategy_id == strategy_id, Trade.exit_time.isnot(None), Trade.pnl.isnot(None))
        .all()
    )
    out = defaultdict(float)
    for exit_time, pnl in rows:
        day = exit_time.date().isoformat()
        out[day] += float(pnl)
    return dict(out)


def _series_from_backtest(strategy_id: int) -> dict:
    """Fallback: latest backtest's trades_json — exit_ts is unix seconds."""
    br = (
        BacktestResult.query
        .filter(BacktestResult.strategy_id == strategy_id, BacktestResult.status == 'completed')
        .order_by(BacktestResult.created_at.desc())
        .first()
    )
    if not br or not br.trades_json:
        return {}
    out = defaultdict(float)
    for t in br.trades_json:
        ts = t.get('exit_ts')
        pnl = t.get('pnl')
        if ts is None or pnl is None:
            continue
        day = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        out[day] += float(pnl)
    return dict(out)


def _pearson(a: np.ndarray, b: np.ndarray) -> float | None:
    """Pearson corr on overlapping days. Returns None if undefined (constant series)."""
    if len(a) < MIN_OBS:
        return None
    sa, sb = a.std(), b.std()
    if sa == 0 or sb == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def build_correlation_matrix(strategy_ids: list[int] | None = None) -> dict:
    """Compute correlation matrix for the given strategies (or all running).

    Returns:
        {
          'strategies': [{id, name, symbol, source, n_obs}],
          'matrix': [[float|null, ...]],  # symmetric, diag = 1.0
          'flagged': [{a_id, b_id, a_name, b_name, corr}],  # |corr| > THRESHOLD
          'threshold': 0.7,
          'min_obs': 5,
          'sources_used': {'live': N, 'backtest': N, 'none': N},
        }
    """
    q = Strategy.query.filter(Strategy.status.in_(['running', 'paused']))
    if strategy_ids:
        q = q.filter(Strategy.id.in_(strategy_ids))
    strategies = q.order_by(Strategy.id).limit(MAX_STRATEGIES).all()

    series_per_strategy = []
    meta = []
    sources_used = {'live': 0, 'backtest': 0, 'none': 0}

    for s in strategies:
        live = _series_from_live(s.id)
        if len(live) >= MIN_OBS:
            series = live
            source = 'live'
        else:
            bt = _series_from_backtest(s.id)
            if len(bt) >= MIN_OBS:
                series = bt
                source = 'backtest'
            elif live:
                series = live
                source = 'live'
            else:
                series = bt
                source = 'backtest' if bt else 'none'
        sources_used[source] += 1
        series_per_strategy.append(series)
        meta.append({
            'id': s.id,
            'name': s.name,
            'symbol': s.symbol,
            'source': source,
            'n_obs': len(series),
        })

    n = len(strategies)
    matrix = [[None] * n for _ in range(n)]
    flagged = []

    for i in range(n):
        matrix[i][i] = 1.0 if meta[i]['n_obs'] >= MIN_OBS else None
        for j in range(i + 1, n):
            a_days = set(series_per_strategy[i].keys())
            b_days = set(series_per_strategy[j].keys())
            common = sorted(a_days & b_days)
            if len(common) < MIN_OBS:
                continue
            a = np.array([series_per_strategy[i][d] for d in common], dtype=float)
            b = np.array([series_per_strategy[j][d] for d in common], dtype=float)
            corr = _pearson(a, b)
            if corr is None:
                continue
            matrix[i][j] = corr
            matrix[j][i] = corr
            if abs(corr) > THRESHOLD:
                flagged.append({
                    'a_id': meta[i]['id'],
                    'b_id': meta[j]['id'],
                    'a_name': meta[i]['name'],
                    'b_name': meta[j]['name'],
                    'corr': corr,
                    'n_obs': len(common),
                })

    flagged.sort(key=lambda f: abs(f['corr']), reverse=True)

    return {
        'strategies': meta,
        'matrix': matrix,
        'flagged': flagged,
        'threshold': THRESHOLD,
        'min_obs': MIN_OBS,
        'sources_used': sources_used,
    }
