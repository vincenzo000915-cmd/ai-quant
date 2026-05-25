"""Phase 14k-16: Catalog × symbol × exchange batch backtest 矩阵

设计原理:
- catalog 30 条策略 × 主流 symbol × 交易所 = 全部跑 walkforward backtest 一次
- 存到 catalog_backtest_matrix 表 (is_verified = pass 门槛 = TRUE)
- AI 推荐改读 verified 池 (瞬时, 全部已经过真实数据验证)

主要 API:
- batch_backtest_catalog(exchange, symbols=None, force=False, catalog_filter=None)
  跑全 catalog × symbols, 写矩阵
- get_verified_for_exchange(exchange) → [Matrix...] (用于 recommend)
- mark_verified(matrix_row) — 通过 IS≥1.5 OOS≥0.8 decay≤70% trades 阈值
"""
from __future__ import annotations

import datetime
import time
import logging
from typing import Iterable

from app.extensions import db
from app.models import StrategyCandidate, CatalogBacktestMatrix

log = logging.getLogger(__name__)


# HL 主流 perps (覆盖率 ~95% 交易量)
DEFAULT_HL_SYMBOLS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'AVAX/USDT',
    'ARB/USDT', 'OP/USDT', 'MATIC/USDT', 'DOGE/USDT',
    'LINK/USDT', 'APT/USDT', 'INJ/USDT', 'SUI/USDT',
    'TIA/USDT', 'BNB/USDT',
]
# OKX 验证用 (较保守)
DEFAULT_OKX_SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'AVAX/USDT']

# qualified 门槛 (Phase 14k-16 放宽 IS 1.5→1.0; OOS 仍要 0.8 严格)
# 理由: IS 是训练集, OOS 才是真金白银; OOS 比 IS 好的情形 (decay 负数) 不能因 IS 略低就拒
MIN_IS_SHARPE = 1.0
MIN_OOS_SHARPE = 0.8
MAX_DECAY_PCT = 70
MIN_TRADES_PER_SIDE = 5


def _check_verified(is_sharpe, oos_sharpe, decay_pct, is_trades, oos_trades) -> tuple[bool, str]:
    """返 (is_verified, reject_reason)"""
    reasons = []
    if is_trades is None or is_trades < MIN_TRADES_PER_SIDE:
        reasons.append(f'IS trades={is_trades} < {MIN_TRADES_PER_SIDE}')
    if oos_trades is None or oos_trades < MIN_TRADES_PER_SIDE:
        reasons.append(f'OOS trades={oos_trades} < {MIN_TRADES_PER_SIDE}')
    if is_sharpe is None or is_sharpe < MIN_IS_SHARPE:
        reasons.append(f'IS sharpe={is_sharpe} < {MIN_IS_SHARPE}')
    if oos_sharpe is None or oos_sharpe < MIN_OOS_SHARPE:
        reasons.append(f'OOS sharpe={oos_sharpe} < {MIN_OOS_SHARPE}')
    if decay_pct is not None and decay_pct > MAX_DECAY_PCT:
        reasons.append(f'decay={decay_pct:.0f}% > {MAX_DECAY_PCT}%')
    if reasons:
        return False, '; '.join(reasons)
    return True, ''


# 模块级 candle cache: 避免同 (sym, tf) 重复拉 OKX (rate limit)
_CANDLE_CACHE: dict[tuple[str, str], list] = {}


def _get_candles_cached(symbol: str, timeframe: str, limit: int = 2000) -> list:
    """缓存版 OHLCV 拉取. 同 batch 内同 (sym, tf) 只调 OKX 一次."""
    key = (symbol, timeframe)
    if key in _CANDLE_CACHE:
        return _CANDLE_CACHE[key]
    from app.services.exchange_service import fetch_ohlcv_history
    import time as _t
    # rate limit 防护: 2 秒间隔
    last_fetch = getattr(_get_candles_cached, '_last_fetch_at', 0)
    elapsed = _t.time() - last_fetch
    if elapsed < 2.0:
        _t.sleep(2.0 - elapsed)
    try:
        candles = fetch_ohlcv_history(symbol, timeframe, total_limit=limit)
    except Exception as e:
        # rate limit retry once
        if 'Too Many' in str(e) or '429' in str(e):
            _t.sleep(10)
            candles = fetch_ohlcv_history(symbol, timeframe, total_limit=limit)
        else:
            raise
    _get_candles_cached._last_fetch_at = _t.time()
    _CANDLE_CACHE[key] = candles
    return candles


def _backtest_one(catalog: StrategyCandidate, symbol: str, exchange: str,
                  candle_limit: int = 2000) -> dict:
    """跑单个 catalog × symbol backtest, 返 matrix row dict (未 commit)"""
    from app.services.backtest_engine import run_walkforward_backtest
    from app.services.candidate_sandbox import load_signal_fn

    tf = catalog.timeframe or '4h'
    try:
        candles = _get_candles_cached(symbol, tf, candle_limit)
    except Exception as e:
        return {
            'ok': False, 'error': f'candle fetch: {e}',
            'is_verified': False, 'reject_reason': f'candle fetch error: {str(e)[:100]}',
        }
    if not candles or len(candles) < 200:
        return {
            'ok': False, 'error': f'no candles for {symbol} {tf}',
            'is_verified': False, 'reject_reason': 'no historical data',
        }

    try:
        signal_fn = load_signal_fn(catalog.parsed_signal, catalog.signal_fn_name)
    except Exception as e:
        return {
            'ok': False, 'error': f'load_signal_fn: {e}',
            'is_verified': False, 'reject_reason': f'fn load error: {e}',
        }

    try:
        wf = run_walkforward_backtest(
            catalog.candidate_type, catalog.default_params or {}, candles,
            timeframe=tf, signal_fn=signal_fn,
            slippage_pct=0.05, fee_pct=0.035 if exchange == 'hyperliquid' else 0.05,
            exchange=exchange,
        )
    except Exception as e:
        return {
            'ok': False, 'error': f'walkforward: {e}',
            'is_verified': False, 'reject_reason': f'backtest error: {type(e).__name__}',
        }

    if wf.get('status') == 'error':
        return {
            'ok': False, 'error': wf.get('error_message'),
            'is_verified': False, 'reject_reason': wf.get('error_message', '')[:200],
        }

    is_res = wf.get('in_sample') or {}
    oos_res = wf.get('out_sample') or {}
    full = wf.get('full') or {}
    is_sh = is_res.get('sharpe_ratio')
    oos_sh = oos_res.get('sharpe_ratio')
    decay = wf.get('decay_pct')
    is_trades = is_res.get('total_trades') or 0
    oos_trades = oos_res.get('total_trades') or 0

    verified, reason = _check_verified(is_sh, oos_sh, decay, is_trades, oos_trades)

    return {
        'ok': True,
        'is_sharpe': is_sh, 'oos_sharpe': oos_sh,
        'decay_pct': decay,
        'is_trades': is_trades, 'oos_trades': oos_trades,
        'full_sharpe': full.get('sharpe_ratio'),
        'full_total_trades': full.get('total_trades'),
        'full_max_drawdown_pct': full.get('max_drawdown_pct'),
        'is_verified': verified,
        'reject_reason': reason if not verified else None,
    }


def batch_backtest_catalog(exchange: str = 'hyperliquid', symbols: list[str] | None = None,
                            force: bool = False, catalog_filter: list[str] | None = None,
                            progress_cb=None) -> dict:
    """全跑 catalog × symbols batch backtest, 写矩阵.

    exchange: 'hyperliquid' or 'okx'
    symbols: 默认主流 perps (HL 14, OKX 4); 显式传可缩小范围
    force: True → 已存在的 row 也重跑; False → 跳过
    catalog_filter: ['cat_donchian_turtle', ...] 限定 catalog
    progress_cb: callable(done, total, current_msg) 用于推 UI 进度

    返回 {total, ran, verified, skipped, errors}
    """
    symbols = symbols or (DEFAULT_HL_SYMBOLS if exchange == 'hyperliquid' else DEFAULT_OKX_SYMBOLS)

    # catalog 池
    q = StrategyCandidate.query.filter_by(source='catalog')
    if catalog_filter:
        q = q.filter(StrategyCandidate.candidate_type.in_(catalog_filter))
    catalogs = q.all()

    total = len(catalogs) * len(symbols)
    done = 0
    ran = 0
    verified_cnt = 0
    skipped = 0
    errors = 0

    started_at = time.time()
    for cat in catalogs:
        for sym in symbols:
            done += 1
            # 已有 row? 跳过 (除非 force)
            existing = CatalogBacktestMatrix.query.filter_by(
                catalog_id=cat.id, symbol=sym, exchange=exchange,
            ).first()
            if existing and not force:
                skipped += 1
                continue

            msg = f'[{done}/{total}] {cat.candidate_type} on {sym} {cat.timeframe} ({exchange})'
            if progress_cb:
                try: progress_cb(done, total, msg)
                except Exception: pass
            log.info(msg)
            print(msg)

            r = _backtest_one(cat, sym, exchange)
            if not r.get('ok'):
                errors += 1

            # upsert matrix row
            if existing is None:
                existing = CatalogBacktestMatrix(
                    catalog_id=cat.id, symbol=sym, exchange=exchange,
                )
                db.session.add(existing)
            existing.is_sharpe = r.get('is_sharpe')
            existing.oos_sharpe = r.get('oos_sharpe')
            existing.decay_pct = r.get('decay_pct')
            existing.is_trades = r.get('is_trades')
            existing.oos_trades = r.get('oos_trades')
            existing.full_sharpe = r.get('full_sharpe')
            existing.full_total_trades = r.get('full_total_trades')
            existing.full_max_drawdown_pct = r.get('full_max_drawdown_pct')
            existing.is_verified = bool(r.get('is_verified'))
            existing.reject_reason = r.get('reject_reason')
            existing.backtest_ran_at = datetime.datetime.utcnow()
            db.session.commit()

            if existing.is_verified:
                verified_cnt += 1
            ran += 1

    return {
        'ok': True,
        'exchange': exchange,
        'symbols': symbols,
        'catalogs_count': len(catalogs),
        'total': total, 'ran': ran, 'verified': verified_cnt,
        'skipped': skipped, 'errors': errors,
        'duration_sec': round(time.time() - started_at, 1),
    }


def get_verified_for_exchange(exchange: str, *,
                                fit_symbols: list[str] | None = None,
                                top_by_sharpe: int | None = None) -> list[CatalogBacktestMatrix]:
    """查 verified 池. fit_symbols filter optional."""
    q = CatalogBacktestMatrix.query.filter_by(exchange=exchange, is_verified=True)
    if fit_symbols:
        q = q.filter(CatalogBacktestMatrix.symbol.in_(fit_symbols))
    q = q.order_by(CatalogBacktestMatrix.oos_sharpe.desc().nullslast())
    if top_by_sharpe:
        q = q.limit(top_by_sharpe)
    return q.all()


def get_matrix_summary(exchange: str | None = None) -> dict:
    """汇总: 总条数, verified 数, 各 symbol 通过率"""
    q = CatalogBacktestMatrix.query
    if exchange:
        q = q.filter_by(exchange=exchange)
    rows = q.all()
    total = len(rows)
    verified = sum(1 for r in rows if r.is_verified)
    by_symbol = {}
    by_exchange = {}
    for r in rows:
        sym_key = (r.exchange, r.symbol)
        by_symbol.setdefault(sym_key, {'total': 0, 'verified': 0})
        by_symbol[sym_key]['total'] += 1
        if r.is_verified:
            by_symbol[sym_key]['verified'] += 1
        by_exchange.setdefault(r.exchange, {'total': 0, 'verified': 0})
        by_exchange[r.exchange]['total'] += 1
        if r.is_verified:
            by_exchange[r.exchange]['verified'] += 1

    return {
        'total': total, 'verified': verified,
        'pass_rate': round(verified / total * 100, 1) if total else 0,
        'by_exchange': by_exchange,
        'by_symbol': {f'{ex}/{sym}': v for (ex, sym), v in by_symbol.items()},
    }
