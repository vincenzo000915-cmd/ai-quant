"""Phase 10.8: auto-apply advisor recommendations (智能托管).

Reads the advisor's current recommendations and executes the subset
the user explicitly opted into via SystemConfig.auto_apply_actions.

Defence-in-depth safeguards (all required, none optional):
- halted=True             → 全部跳過（系統已 panic，不要再亂動）
- auto_apply_enabled=False → 全部跳過
- per-action opt-in        → action 不在白名單就跳過
- daily cap                → 超過 auto_apply_max_per_day 就停下
- audit + telegram         → 每個動作都留痕 + 推播
- never auto-retire LIVE   → 留個底線：實盤模式下不自動 retire（pause 可以）

This file is import-light so it can be called from both Flask routes
and Celery tasks without circular imports.
"""
from __future__ import annotations

import datetime
from typing import Callable

from app.extensions import db
from app.models import AuditLog, Strategy
from app.services.audit import log as audit
from app.services.config_service import get_config
from app.services.strategy_advisor import build_recommendations


FAN_OUT_DEFAULTS = ['ETH/USDT', 'SOL/USDT', 'AVAX/USDT']

# 永遠不會 auto 處理的 action（純資訊類）
INFO_ONLY = {'mtf_caution'}


def _today_count() -> int:
    """今日（UTC）已 auto-apply 過幾次。"""
    today = datetime.datetime.utcnow().date()
    return (
        AuditLog.query
        .filter(AuditLog.event_type == 'advisor_auto_apply')
        .filter(AuditLog.created_at >= datetime.datetime.combine(today, datetime.time.min))
        .count()
    )


def _telegram_safe(text: str):
    try:
        from app.services.telegram_service import send as _tg
        _tg(text)
    except Exception:
        pass


def _execute_one(item: dict) -> tuple[bool, str]:
    """執行單個建議。回傳 (ok, message)。

    這裡直接呼叫 DB / 同步 helper，避免 import routes（會循環）。
    """
    action = item['action']
    sid = item['strategy_id']
    strategy = Strategy.query.get(sid)
    if not strategy:
        return False, f'strategy {sid} 不存在'

    if action == 'apply_params':
        new_params = item.get('meta', {}).get('best_params')
        if not isinstance(new_params, dict) or not new_params:
            return False, 'meta.best_params 缺失或無效'
        strategy.params = new_params
        db.session.commit()
        return True, f'已套用 params={new_params}'

    if action == 'pause':
        if strategy.status != 'running':
            return False, f'status={strategy.status}, 無需暫停'
        strategy.status = 'stopped'
        db.session.commit()
        return True, '已暫停'

    if action == 'retire':
        # 安全網：LIVE 模式絕不自動 retire（pause 已足夠）
        cfg = get_config()
        if cfg.get('trading_mode') == 'live':
            return False, 'LIVE 模式禁止自動 retire — 請手動執行'
        if strategy.status == 'retired':
            return False, '已 retired'
        reason = f"auto: {item.get('reason', '')[:200]}"
        strategy.status = 'retired'
        strategy.retired_at = datetime.datetime.utcnow()
        strategy.retire_reason = reason
        db.session.commit()
        return True, f'已退役（{reason}）'

    if action == 'fan_out':
        # 直接複用 routes 的邏輯太重；重寫精簡版
        import re
        from app.services.symbols import SUPPORTED_SYMBOLS
        if strategy.template_group is None:
            strategy.template_group = strategy.id
        group = strategy.template_group
        existing = {s.symbol for s in Strategy.query.filter(Strategy.template_group == group).all()}
        base_name = re.sub(r'\s*\([A-Z]{2,6}\)\s*$', '', strategy.name).strip()
        created = []
        for sym in FAN_OUT_DEFAULTS:
            if sym not in SUPPORTED_SYMBOLS or sym == strategy.symbol or sym in existing:
                continue
            clone = Strategy(
                name=f'{base_name} ({sym.split("/")[0]})',
                type=strategy.type,
                category=strategy.category,
                params=dict(strategy.params or {}),
                symbol=sym,
                timeframe=strategy.timeframe,
                status='stopped',
                max_positions=strategy.max_positions,
                max_daily_loss=strategy.max_daily_loss,
                template_group=group,
            )
            db.session.add(clone)
            existing.add(sym)
            created.append(sym)
        db.session.commit()
        if not created:
            return False, '沒有可新增的兄弟（都已存在）'
        return True, f'已建立 {len(created)} 個兄弟：{", ".join(created)}'

    return False, f'未知 action: {action}'


def run_auto_apply() -> dict:
    """主入口 — Celery task 跟手動觸發都呼這個。"""
    cfg = get_config()

    if cfg.get('halted'):
        return {'skipped': True, 'reason': 'system halted'}
    if not cfg.get('auto_apply_enabled'):
        return {'skipped': True, 'reason': 'auto_apply_enabled=False'}

    allowed = set(cfg.get('auto_apply_actions') or [])
    if not allowed:
        return {'skipped': True, 'reason': 'auto_apply_actions 為空'}

    daily_cap = int(cfg.get('auto_apply_max_per_day') or 5)
    already_today = _today_count()
    remaining = max(0, daily_cap - already_today)
    if remaining == 0:
        return {'skipped': True, 'reason': f'已達每日上限 {daily_cap}', 'today_count': already_today}

    recs = build_recommendations()
    items = recs.get('items', [])

    applied: list[dict] = []
    skipped: list[dict] = []

    for item in items:
        action = item['action']
        if action in INFO_ONLY:
            continue
        if action not in allowed:
            skipped.append({'item': item, 'why': f'{action} not in allowed actions'})
            continue
        if len(applied) >= remaining:
            skipped.append({'item': item, 'why': '本輪達到剩餘日限'})
            continue

        ok, msg = _execute_one(item)
        rec = {
            'action': action,
            'strategy_id': item['strategy_id'],
            'strategy_name': item['strategy_name'],
            'reason': item['reason'],
            'ok': ok,
            'message': msg,
        }
        if ok:
            applied.append(rec)
            audit('advisor_auto_apply', actor='system',
                  action=action, strategy_id=item['strategy_id'],
                  reason=item['reason'][:300], message=msg)
        else:
            skipped.append({'item': item, 'why': msg})

    if applied:
        lines = [f'🤖 <b>智能托管自動執行</b>（{len(applied)} 項）']
        for r in applied:
            lines.append(f"• {r['action']} #{r['strategy_id']} {r['strategy_name']}: {r['message']}")
        if already_today + len(applied) >= daily_cap:
            lines.append(f'\n今日已達上限 {daily_cap}，剩下今日不會再動。')
        _telegram_safe('\n'.join(lines))

    return {
        'skipped': False,
        'applied_count': len(applied),
        'applied': applied,
        'skipped_items': skipped,
        'today_count_before': already_today,
        'today_count_after': already_today + len(applied),
        'daily_cap': daily_cap,
    }
