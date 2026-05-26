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
    'default_backtest_symbol': 'AVAX/USDT',
    # Phase 10.8: 智能托管（自動套用 advisor 建議）
    'auto_apply_enabled': False,
    'auto_apply_actions': [],
    'auto_apply_max_per_day': 5,
    'fan_out_auto_start': False,
    'fan_out_min_oos_sharpe': 1.0,
    'auto_promote_max_per_day': 2,
    'auto_promote_min_oos_sharpe': 1.5,
    # Phase 14c
    'ai_decision_mode': 'manual',
    'auto_apply_max_running': 8,
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


def get_config(user_id: int | None = None) -> dict:
    """回傳完整 config dict (含 TTL cache).

    Phase 14k-30 #3: user_id 不為 None → 合并 UserConfig overrides (per-user 隔离).
    """
    now = time.time()
    cache_key = f'__user_{user_id}__' if user_id else '__all__'
    cached = _cache.get(cache_key)
    if cached and cached[1] > now:
        return cached[0]
    try:
        row = _load_row()
        d = row.to_dict()
        if user_id:
            from app.models import UserConfig
            uc = UserConfig.query.filter_by(user_id=user_id).first()
            if uc and uc.overrides:
                # 仅 DEFAULTS 内字段允许覆盖 (system-level halted / trading_mode 不能 per-user)
                for k, v in (uc.overrides or {}).items():
                    if k in DEFAULTS:
                        d[k] = v
    except Exception:
        # DB 未就緒（容器剛起時）回 defaults，不要崩
        d = dict(DEFAULTS)
    _cache[cache_key] = (d, now + _CACHE_TTL_SEC)
    return d


def get(key: str, default: Any = None) -> Any:
    """取單一欄位（走 cache）"""
    d = get_config()
    return d.get(key, default if default is not None else DEFAULTS.get(key))


# Phase 14k-30 #3: 允许 per-user 覆盖的字段白名单 (其余仍走 system row)
USER_SCOPED_KEYS = {
    'leverage', 'trade_size_usdt', 'stop_loss_pct', 'take_profit_pct',
    'max_daily_loss_usdt', 'auto_apply_enabled', 'auto_apply_actions',
    'auto_apply_max_per_day', 'ai_decision_mode', 'auto_promote_max_per_day',
    'auto_promote_min_oos_sharpe', 'fan_out_auto_start', 'fan_out_min_oos_sharpe',
    'auto_apply_max_running',
}


def update(patch: dict, user_id: int | None = None) -> dict:
    """部分更新 + 失效 cache. 回傳更新後完整 config.

    Phase 14k-30 #3:
      - user_id is None → 写 system row (向后兼容)
      - user_id 指定 → user-scoped 字段写 UserConfig.overrides; 非 user-scoped 字段 (halted, trading_mode 等) 仍写 system row
    """
    from app.extensions import db
    if user_id:
        from app.models import UserConfig
        uc = UserConfig.query.filter_by(user_id=user_id).first()
        if uc is None:
            uc = UserConfig(user_id=user_id, overrides={})
            db.session.add(uc)
        overrides = dict(uc.overrides or {})
        sys_patch = {}
        for k, v in patch.items():
            if k not in DEFAULTS:
                continue
            if k in USER_SCOPED_KEYS:
                if v is None:
                    overrides.pop(k, None)   # None = 清除 override 回退到 system row
                else:
                    overrides[k] = v
            else:
                sys_patch[k] = v
        uc.overrides = overrides
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(uc, 'overrides')
        # 非 user-scoped 字段仍写 system row
        if sys_patch:
            row = _load_row()
            for k, v in sys_patch.items():
                if k in ('halted', 'halt_reason') or v is not None:
                    setattr(row, k, v)
        db.session.commit()
    else:
        row = _load_row()
        for k, v in patch.items():
            if k in DEFAULTS:
                if k in ('halted', 'halt_reason') or v is not None:
                    setattr(row, k, v)
        db.session.commit()
    invalidate()
    return get_config(user_id)


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
