"""Kill switch — 緊急全停 (Phase 6.3)

1. 所有 status='running' 策略 → 'stopped'（**不是** 'retired'，明顯區分人為 vs alpha decay）
2. 所有 open positions → 按當前市價強平，trade.reason='kill_switch'
3. 觸發 halt（halt_reason='kill switch'）阻止新開倉
4. Telegram 通知

可選：max_drawdown_pct 自動觸發（待 monitor_daily_loss / anomaly detect 接通）。
"""
from __future__ import annotations

import datetime
from app.extensions import db
from app.models import Strategy, Position, Trade
from app.services.exchange_service import get_ticker
from app.services.config_service import set_halted, get_config
from app.services.telegram_service import notify_kill_switch


def execute_kill_switch(reason: str = 'manual kill switch') -> dict:
    """執行 kill switch。回傳統計。"""
    cfg = get_config()
    lev = cfg.get('leverage', 15.0)

    # 1. stop all running strategies
    strategies = Strategy.query.filter_by(status='running').all()
    for s in strategies:
        s.status = 'stopped'

    # 2. force-close all open positions at market
    closed = []
    errors = []
    positions = Position.query.filter_by(status='open').all()
    for pos in positions:
        try:
            t = get_ticker(pos.symbol)
            current = float(t.get('price') or t.get('last') or 0)
            if current <= 0:
                errors.append(f'#{pos.id}: no price')
                continue

            raw_pct = (current - pos.entry_price) / pos.entry_price * 100
            pnl_pct = raw_pct * lev
            pnl = raw_pct * pos.size * pos.entry_price * lev / 100

            trade = Trade(
                position_id=pos.id, strategy_id=pos.strategy_id,
                symbol=pos.symbol, side='long',
                entry_price=pos.entry_price, exit_price=current,
                quantity=pos.size, pnl=pnl, pnl_percent=pnl_pct,
                entry_time=pos.opened_at, exit_time=datetime.datetime.utcnow(),
                reason='kill_switch',
            )
            pos.status = 'closed'
            pos.closed_at = datetime.datetime.utcnow()
            pos.current_price = current
            pos.realized_pnl = pnl
            db.session.add(trade)
            closed.append({
                'position_id': pos.id, 'strategy_id': pos.strategy_id,
                'symbol': pos.symbol, 'exit': current,
                'pnl': round(pnl, 4), 'pnl_pct': round(pnl_pct, 4),
            })
        except Exception as e:
            errors.append(f'#{pos.id}: {type(e).__name__}: {e}')

    db.session.commit()

    # 3. halt
    set_halted(f'kill switch: {reason}')

    # 4. notify
    notify_kill_switch(reason)

    return {
        'reason': reason,
        'stopped_strategies': [s.id for s in strategies],
        'closed_positions': closed,
        'errors': errors,
        'halted': True,
    }
