"""SystemConfig 讀寫 + 模組級快取

策略 / 回測 / Celery 每秒可能呼叫，不能每次打 DB。用 TTL cache，預設 30 秒。
寫入時主動失效。沒有 DB row 時用 hardcoded defaults。
"""
from __future__ import annotations

import time
from typing import Any

# Cache: {key: (value, expires_at)}
_CACHE_TTL_SEC = 30
_cache: dict[str, tuple[Any, float]] = {}

DEFAULTS = {
    'trading_mode': 'paper',
    'capital_usdt': 100.0,
    'leverage': 15.0,
    'trade_size_usdt': 10.0,
    'stop_loss_pct': 5.0,
    'take_profit_pct': 8.0,
    'max_daily_loss_usdt': 10.0,
    'halted': False,
    'halt_reason': None,
    'sizing_mode': 'flat',
    'target_vol_pct': 1.5,
    'sizing_min_mult': 0.3,
    'sizing_max_mult': 3.0,
    'sl_mode': 'flat_pct',
    'atr_period': 14,
    'atr_sl_mult': 2.0,
    'atr_tp_mult': 3.0,
    'backtest_slippage_pct': 0.05,
    'backtest_fee_pct': 0.05,
    # Phase 10.8: 智能托管（自動套用 advisor 建議）
    'auto_apply_enabled': False,
    'auto_apply_actions': [],
    'auto_apply_max_per_day': 5,
    'fan_out_auto_start': False,
    'fan_out_min_oos_sharpe': 1.0,
    'auto_promote_max_per_day': 2,
    'auto_promote_min_oos_sharpe': 1.5,
}


def _load_row():
    """從 DB 拉 SystemConfig 第一行；沒就建一個 defaults"""
    from app.extensions import db
    from app.models import SystemConfig
    row = SystemConfig.query.get(1)
    if row is None:
        row = SystemConfig(id=1, **DEFAULTS)
        db.session.add(row)
        db.session.commit()
    return row


def get_config() -> dict:
    """回傳完整 config dict（含 TTL cache）"""
    now = time.time()
    cached = _cache.get('__all__')
    if cached and cached[1] > now:
        return cached[0]
    try:
        row = _load_row()
        d = row.to_dict()
    except Exception:
        # DB 未就緒（容器剛起時）回 defaults，不要崩
        d = dict(DEFAULTS)
    _cache['__all__'] = (d, now + _CACHE_TTL_SEC)
    return d


def get(key: str, default: Any = None) -> Any:
    """取單一欄位（走 cache）"""
    d = get_config()
    return d.get(key, default if default is not None else DEFAULTS.get(key))


def update(patch: dict) -> dict:
    """部分更新 + 失效 cache。回傳更新後完整 config。"""
    from app.extensions import db
    row = _load_row()
    for k, v in patch.items():
        # halted/halt_reason 允許設為 None / False；其他 None skip
        if k in DEFAULTS:
            if k in ('halted', 'halt_reason') or v is not None:
                setattr(row, k, v)
    db.session.commit()
    invalidate()
    return row.to_dict()


def set_halted(reason: str | None):
    """便利：設為 halted（若 reason None 則解除）"""
    import datetime
    from app.extensions import db
    row = _load_row()
    if reason:
        row.halted = True
        row.halt_reason = reason
        row.halted_at = datetime.datetime.utcnow()
    else:
        row.halted = False
        row.halt_reason = None
        row.halted_at = None
    db.session.commit()
    invalidate()
    return row.to_dict()


def invalidate():
    _cache.clear()
