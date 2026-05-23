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
            # Phase 10.9: 不再靜默 — 推 Telegram 告訴 user「該退役但跳過」
            _telegram_safe(
                f'⚠️ <b>智能托管建議退役但跳過（LIVE 模式安全網）</b>\n'
                f'#{sid} {strategy.name}\n原因：{item.get("reason", "")[:200]}\n'
                f'若同意，請手動到策略表 🪦 退役。'
            )
            return False, 'LIVE 模式禁止自動 retire — 已推 Telegram 提醒手動處理'
        if strategy.status == 'retired':
            return False, '已 retired'
        reason = f"auto: {item.get('reason', '')[:200]}"
        strategy.status = 'retired'
        strategy.retired_at = datetime.datetime.utcnow()
        strategy.retire_reason = reason
        db.session.commit()
        return True, f'已退役（{reason}）'

    if action == 'promote_candidate':
        # Phase 10.10: 候選池 qualified → 上線
        # Phase 12.31: per-TF 門檻 (short 高 PF / long 低 trades 容差)
        from app.services.candidate_pipeline import promote_candidate as do_promote
        cfg = get_config()
        cid = item.get('meta', {}).get('candidate_id')
        oos = item.get('meta', {}).get('oos_sharpe')
        threshold = float(cfg.get('auto_promote_min_oos_sharpe', 1.5))
        if oos is None or oos < threshold:
            return False, f'OOS Sharpe {oos} < 阈值 {threshold}，跳過'

        # 拉 candidate 細節 + 回測結果做 per-TF gate
        from app.models import StrategyCandidate, BacktestResult
        cand = StrategyCandidate.query.get(cid)
        if cand and cand.backtest_result_id:
            bt = BacktestResult.query.get(cand.backtest_result_id)
            if bt:
                tf = cand.timeframe or '4h'
                # per-TF 門檻: (min PF, min trades, min AR%)
                # Phase 12.38: 降 short PF 1.8 → 1.5 (1.8 几乎没策略能过，等真有 LIVE 数据再调严)
                tf_gates = {
                    '15m': (1.5, 60, 8),
                    '30m': (1.5, 50, 8),
                    '1h':  (1.4, 40, 7),
                    '4h':  (1.4, 30, 7),
                    '1d':  (1.3, 12, 5),
                    '1w':  (1.2, 8,  4),
                }
                min_pf, min_trades, min_ar = tf_gates.get(tf, (1.5, 30, 8))
                pf = bt.profit_factor or 0
                tr = bt.total_trades or 0
                ar = bt.annual_return_pct or 0
                if pf < min_pf:
                    return False, f'TF={tf} PF {pf:.2f} < 阈值 {min_pf}，跳過'
                if tr < min_trades:
                    return False, f'TF={tf} trades {tr} < 阈值 {min_trades}，跳過'
                if ar < min_ar:
                    return False, f'TF={tf} AR {ar:.1f}% < 阈值 {min_ar}%，跳過'
        # Phase 12.39: 不再硬編碼 BTC fallback — 優先讀 candidate.source_meta，再 config 默認
        symbol = item.get('meta', {}).get('symbol')
        if not symbol and cand:
            symbol = (cand.source_meta or {}).get('symbol')
        if not symbol:
            symbol = cfg.get('default_backtest_symbol', 'BTC/USDT')
        result = do_promote(cid, symbol=symbol)
        if not result.get('ok'):
            return False, f'promote 失败: {result.get("error")}'
        new_sid = result['strategy']['id']
        # qualified 已過 walk-forward → 直接上線（user 要的就是不手動）
        new_strat = Strategy.query.get(new_sid)
        if new_strat:
            new_strat.status = 'running'
            db.session.commit()
        _telegram_safe(
            f'🚀 <b>智能托管自動上線新策略</b>\n'
            f'#{new_sid} {new_strat.name if new_strat else "?"}（候選 #{cid}）\n'
            f'OOS Sharpe = {oos:.2f}\n'
            f'已 status=running，立刻納入信號循環。'
        )
        return True, f'已 promote 候選 #{cid} → strategy #{new_sid}（已啟動）'

    if action == 'fan_out':
        # 直接複用 routes 的邏輯太重；重寫精簡版
        import re
        from app.services.symbols import SUPPORTED_SYMBOLS
        if strategy.template_group is None:
            strategy.template_group = strategy.id
        group = strategy.template_group
        existing = {s.symbol for s in Strategy.query.filter(Strategy.template_group == group).all()}
        base_name = re.sub(r'\s*\([A-Z]{2,6}\)\s*$', '', strategy.name).strip()
        created_objs = []
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
                status='stopped',   # 永遠 stopped 等回測決定
                max_positions=strategy.max_positions,
                max_daily_loss=strategy.max_daily_loss,
                template_group=group,
            )
            db.session.add(clone)
            db.session.flush()  # 拿 id
            existing.add(sym)
            created_objs.append(clone)
        db.session.commit()
        if not created_objs:
            return False, '沒有可新增的兄弟（都已存在）'

        # Phase 10.9: 立刻排 Celery 回測 — 過門檻 + auto_start 才會啟動
        # 兄弟間 60s 錯峰，避免同時打 OKX 觸發 429
        from app.tasks.strategy_tasks import backtest_and_maybe_start
        for i, c in enumerate(created_objs):
            try:
                backtest_and_maybe_start.apply_async(args=[c.id], countdown=i * 60)
            except Exception:
                pass
        symbols_str = ', '.join(c.symbol for c in created_objs)
        return True, f'已建立 {len(created_objs)} 個兄弟（{symbols_str}），已排回測 — 過門檻才會自動啟動'

    return False, f'未知 action: {action}'


def _today_count_action(action: str) -> int:
    """今日（UTC）某特定 action 已執行幾次。"""
    today = datetime.datetime.utcnow().date()
    rows = (
        AuditLog.query
        .filter(AuditLog.event_type == 'advisor_auto_apply')
        .filter(AuditLog.created_at >= datetime.datetime.combine(today, datetime.time.min))
        .all()
    )
    return sum(1 for r in rows if (r.context or {}).get('action') == action)


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
    promote_cap = int(cfg.get('auto_promote_max_per_day') or 2)
    already_today = _today_count()
    promote_today = _today_count_action('promote_candidate')
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
        # promote_candidate 額外有自己的日限
        if action == 'promote_candidate':
            if promote_today + sum(1 for a in applied if a['action'] == 'promote_candidate') >= promote_cap:
                skipped.append({'item': item, 'why': f'promote 日限 {promote_cap} 已達'})
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
