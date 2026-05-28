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
    # 14k-47 deprecated 全局 SL/TP — 实际走 backtest_engine.TF_DEFAULT_SL_TP (15m:1%, 4h:5%, ...)
    # 这俩字段保留作 paranoid fallback (TF-aware 失败时), 不应直接消费. 见 feedback_problem_triage.
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


# Phase 14k-123: 资金感知 max_running + TF-aware 沉默期 + 短 TF revive
# User 反馈: "max_running=8 写死, 资金多了应该开放; 极短 TF 信号变化快需要即时淘汰/回滚/新增"

# 资金跨档 → max_running (跟 14k-55 invent_quota 同设计哲学)
CAPITAL_TIER_MAX_RUNNING = [
    # Phase 14k-133: 放开 ladder — 安全已下沉到开仓层 (14k-131 EV 排序+资金感知预算闸).
    # max_running 不再是安全旋钮: 实际开仓数由 position-open 预算 N=min(floor(权益×80%/单仓),
    #   MAX_CONCURRENT_POSITIONS=12) 限死; 雪球由 daily_loss_halt 2% / max_dd 5% /
    #   CONSECUTIVE_LOSS_LIMIT 3 / 相关性接住. 这里只决定"几个哨兵能在岗待命".
    # 多养哨兵 = 多撒网接 regime-fit 信号, 只有 EV 最高的少数每 cycle 真开火.
    # 剩余软约束: ① 防分散过细 ② 每日 03:00 monitor_strategy_health O(n) walkforward 成本
    #   ③ ORM session — 故顶档仍留上限. (n 大到回测拖慢 → 下一步按 regime/活跃度跳过 dormant 回测)
    (100,    20),   # < $100: 8→20  (开仓预算仍只放 ~12, 余 8 哨兵给 regime 轮换)
    (500,    28),   # < $500: 10→28
    (2000,   40),   # < $2000: 12→40
    (10000,  52),   # < $10000: 16→52
    (10**9,  64),   # >= $10000: 20→64 (顶档留余地防 daily walkforward / ORM 压力)
]

# TF-aware 沉默期 (days) — 短 TF 信号密集, 几天无 trade 即可怀疑死循环; 长 TF 信号稀, 多日才合理
# 标准: 大约 = TF 跑出 ~60-90 candles 的天数 (统计显著样本)
INACTIVITY_GRACE_DAYS_BY_TF = {
    '15m': 1,   # 96 candles/day, 1 day = 96 信号机会
    '30m': 2,   # 96 candles
    '1h':  3,   # 72 candles
    '2h':  7,
    '4h':  14,  # 84 candles
    '6h':  21,
    '8h':  28,
    '12h': 42,
    '1d':  60,  # 60 candles
    '3d':  90,
    '1w':  180,
}


def get_max_running_for_user(user_id: int | None = None) -> int:
    """Phase 14k-123: 资金感知 max_running.

    资金少 → 限策略数 (避免过度分散, 单策略本金太薄即使信号触发也开仓空闲).
    资金多 → 开放策略数 (能真分散不同 symbol/TF/regime).

    Override: 用户/admin 在 SystemConfig.auto_apply_max_running 显式 set 非 default 值 → 用它.
    Default 8 → 走资金 tier 计算.
    """
    cfg = get_config(user_id)
    explicit = cfg.get('auto_apply_max_running')
    if explicit is not None and explicit != 8:   # 8 是 DEFAULTS, 非 8 视为用户显式 set
        return int(explicit)
    try:
        from app.services.exchange_service import fetch_balance, _resolve_creds
        creds = _resolve_creds(user_id) if user_id else None
        balances = fetch_balance(creds=creds) if creds else fetch_balance()
        total_usd = sum(float(v.get('total', 0) or 0) for v in (balances or {}).values())
    except Exception:
        total_usd = 0
    if total_usd <= 0:
        return 4   # 没余额 = 最低
    for threshold, max_n in CAPITAL_TIER_MAX_RUNNING:
        if total_usd < threshold:
            return max_n
    return CAPITAL_TIER_MAX_RUNNING[-1][1]   # 14k-133: 取末档值, 不再写死 (防 ladder 改后 stale)


def get_inactivity_grace_days(timeframe: str | None) -> int:
    """Phase 14k-123: TF-aware 沉默期 — 用于 weekly_review / revive 判定 "信号死循环".

    短 TF (15m/30m/1h) 1-3 天无 trade 即可怀疑死, 因为 candle 密信号机会多.
    长 TF (4h/1d) 需要 2-8 周才能下结论, 因为 candle 稀.
    """
    return INACTIVITY_GRACE_DAYS_BY_TF.get(timeframe or '4h', 14)
