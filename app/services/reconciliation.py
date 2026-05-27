"""Phase 8.2: Position-OKX sync + Order reconciliation

每 5 分鐘對賬：
  - OKX 真實 SWAP 持倉 vs 本地 positions 表
  - 三類 mismatch:
      (a) local 有 / OKX 無  → 本地孤兒。可能 OKX 已平但本地 commit 失敗。自動本地 close + 記錄。
      (b) OKX 有 / local 無  → OKX 孤兒。最危險 — 我們不知道哪個策略開的。halt + Telegram。
      (c) 兩邊都有但 size/side 不一致 → drift。halt + Telegram，等人工。

設計取向：保守 — 任何 OKX side 多出的東西都 halt 不冒險。
"""
from __future__ import annotations

import datetime
from app.extensions import db
from app.models import Position, Trade
from app.services.exchange_service import fetch_okx_positions, get_ticker
from app.services.config_service import set_halted
from app.services.telegram_service import send as _tg


def _inst_id_to_symbol(inst_id: str) -> str:
    """'BTC-USDT-SWAP' -> 'BTC/USDT'"""
    base = inst_id.replace('-SWAP', '')
    parts = base.split('-')
    if len(parts) == 2:
        return f'{parts[0]}/{parts[1]}'
    return base


def reconcile_all() -> dict:
    """Phase 14k-81 全交易所对账入口.
    - OKX: 走 reconcile() (单 admin / 系统级 OKX creds)
    - HL: 逐个 HL bound user 走 reconcile_hl_user() (per-user creds)
    返回 merged actions + ok 标识.
    """
    from app.models import HyperliquidCredentials
    okx_r = reconcile()  # OKX 不变, 原逻辑
    merged_actions = list(okx_r.get('actions') or [])
    hl_total_open = 0
    hl_errors = []

    try:
        hl_users = HyperliquidCredentials.query.filter_by(is_active=True).all()
    except Exception as e:
        hl_users = []
        hl_errors.append(f'list HL users: {type(e).__name__}: {e}')

    for hl_rec in hl_users:
        try:
            r = reconcile_hl_user(hl_rec.user_id)
            if r.get('ok'):
                merged_actions.extend(r.get('actions') or [])
                hl_total_open += r.get('hl_open_count', 0)
            else:
                hl_errors.append(f'user_id={hl_rec.user_id}: {r.get("error")}')
        except Exception as e:
            hl_errors.append(f'user_id={hl_rec.user_id}: {type(e).__name__}: {e}')

    return {
        'ok': okx_r.get('ok') and not hl_errors,
        'okx_open_count': okx_r.get('okx_open_count', 0),
        'hl_open_count': hl_total_open,
        'local_open_count': okx_r.get('local_open_count', 0),
        'actions': merged_actions,
        'hl_users_checked': len(hl_users),
        'errors': hl_errors,
        'is_halted_now': okx_r.get('is_halted_now', False),
    }


def reconcile_hl_user(user_id: int) -> dict:
    """Phase 14k-81: 单个 HL user 对账. 跟 reconcile() (OKX) 同 3 类 mismatch 逻辑,
    但 HL 不用 contract_size — pos_contracts 直接是 base unit (eg 0.0001 BTC).
    """
    from app.models import Strategy
    from app.services.hyperliquid_creds import get_decrypted_for_user
    from app.services.hyperliquid_service import fetch_positions as hl_fetch_positions

    creds = get_decrypted_for_user(user_id)
    if not creds:
        return {'ok': False, 'error': f'no HL creds for user_id={user_id}', 'actions': []}

    actions = []
    try:
        hl_positions = hl_fetch_positions(creds)
    except Exception as e:
        return {'ok': False, 'error': f'fetch_positions: {type(e).__name__}: {e}', 'actions': []}

    # 只比对该 user 的 HL 策略
    hl_strat_ids = {s.id for s in Strategy.query.filter(
        Strategy.user_id == user_id,
        Strategy.exchange == 'hyperliquid',
    ).all()}
    local_open = Position.query.filter(
        Position.status == 'open',
        Position.strategy_id.in_(hl_strat_ids) if hl_strat_ids else False,
    ).all() if hl_strat_ids else []

    hl_by_key = {}
    for p in hl_positions:
        key = (p['symbol'], p['side'])
        hl_by_key[key] = p

    local_by_key = {}
    for p in local_open:
        key = (p.symbol, p.side or 'long')
        local_by_key[key] = p

    # === (a) local 有, HL 无 → 本地补平 ===
    for key, lp in local_by_key.items():
        if key not in hl_by_key:
            try:
                from app.services.hyperliquid_service import get_ticker as hl_get_ticker
                t = hl_get_ticker(lp.symbol, creds.get('network') or 'mainnet')
                current = float(t.get('price') or lp.entry_price)
                # HL 没合约张数概念, 直接用 base size 算 PnL
                pnl_raw_pct = (current - lp.entry_price) / lp.entry_price * 100
                if (lp.side or 'long') == 'short':
                    pnl_raw_pct = -pnl_raw_pct
                # 用本地杠杆 (Strategy.params.risk_params.leverage), 没的话 fallback 3
                strat = Strategy.query.get(lp.strategy_id)
                lev = 3.0
                try:
                    lev = float((strat.params or {}).get('risk_params', {}).get('leverage') or 3.0)
                except Exception:
                    pass
                pnl_pct = pnl_raw_pct * lev
                pnl = pnl_raw_pct * lp.size * lp.entry_price * lev / 100
                trade = Trade(
                    position_id=lp.id, strategy_id=lp.strategy_id,
                    user_id=lp.user_id,
                    symbol=lp.symbol, side=lp.side or 'long',
                    entry_price=lp.entry_price, exit_price=current,
                    quantity=lp.size, pnl=pnl, pnl_percent=pnl_pct,
                    entry_time=lp.opened_at, exit_time=datetime.datetime.utcnow(),
                    reason='reconcile_orphan_hl',
                )
                lp.status = 'closed'
                lp.closed_at = datetime.datetime.utcnow()
                lp.current_price = current
                lp.realized_pnl = pnl
                db.session.add(trade)
                actions.append({
                    'type': 'hl_local_orphan_closed',
                    'position_id': lp.id, 'strategy_id': lp.strategy_id,
                    'symbol': lp.symbol, 'pnl': round(pnl, 4),
                })
                _tg(
                    f'⚠️ <b>HL 对账 · Reconcile: 持仓已自动关闭</b>\n'
                    f'持仓 #{lp.id} ({lp.symbol} {lp.side}) 显示开仓中, 但 Hyperliquid 已平.\n'
                    f'Local position #{lp.id} was open, but already closed on Hyperliquid.\n'
                    f'已同步关闭 · 估算盈亏 ${pnl:.2f}',
                    event_key=f'hl_orphan_local_{lp.id}',
                )
            except Exception as e:
                actions.append({'type': 'hl_local_orphan_error', 'position_id': lp.id, 'error': str(e)})

    db.session.commit()

    # === (b) HL 有, local 无 — 危险, halt ===
    hl_orphans = [op for k, op in hl_by_key.items() if k not in local_by_key]
    if hl_orphans:
        details = '\n'.join(
            f'  {p["inst_id"]} {p["side"]} {p["pos_contracts"]:.6f} @ ${p["avg_px"]:.0f}'
            for p in hl_orphans
        )
        set_halted(f'reconcile: HL user {user_id} 有 {len(hl_orphans)} 個本地不存在的持倉')
        _tg(
            f'🚨 <b>HL 对账 · 发现异常持仓 (已自动停单)</b>\n'
            f'Hyperliquid 上有系统不知道的持仓:\n{details}\n\n'
            f'请到 HL 检查是手动开的还是策略误开, 平仓后到 Dashboard 解除停单.',
            event_key=f'hl_orphan_user_{user_id}', force=True,
        )
        actions.append({'type': 'hl_orphan_halted', 'user_id': user_id,
                        'count': len(hl_orphans), 'details': hl_orphans})

    # === (c) 两边都有 — drift 检查 (HL 不用 contract_size, 直接比 base) ===
    drift_alerts = []
    for key in set(hl_by_key.keys()) & set(local_by_key.keys()):
        op = hl_by_key[key]
        lp = local_by_key[key]
        hl_base_amt = abs(op['pos_contracts'])
        if abs(hl_base_amt - lp.size) / max(lp.size, 1e-9) > 0.05:
            drift_alerts.append({
                'position_id': lp.id, 'symbol': lp.symbol,
                'local_size': lp.size, 'hl_size_base': hl_base_amt,
            })
    if drift_alerts:
        details = '\n'.join(
            f'  #{d["position_id"]} {d["symbol"]} 本地 {d["local_size"]:.6f} vs HL {d["hl_size_base"]:.6f}'
            for d in drift_alerts
        )
        _tg(
            f'⚠️ <b>HL 对账 · 持仓大小不一致</b>\n{details}\n\n'
            f'不影响运行, 但建议手动检查.',
            event_key=f'hl_size_drift_user_{user_id}',
        )
        actions.append({'type': 'hl_size_drift', 'user_id': user_id, 'items': drift_alerts})

    return {
        'ok': True,
        'hl_open_count': len(hl_positions),
        'local_open_count': len(local_open),
        'actions': actions,
    }


def reconcile() -> dict:
    """跑一次對賬。回傳統計 + 觸發的動作清單.

    Phase 14k-12: 仅 OKX 策略对账 — HL 策略走 reconcile_hl_user (14k-81).
    """
    actions = []
    try:
        okx_positions = fetch_okx_positions()
    except Exception as e:
        return {'ok': False, 'error': f'fetch_okx_positions: {type(e).__name__}: {e}', 'actions': []}

    # 仅对比 OKX 策略 — HL positions 不在 OKX 上, 排除避免误判 orphan
    from app.models import Strategy
    okx_strat_ids = {s.id for s in Strategy.query.filter(
        (Strategy.exchange == 'okx') | (Strategy.exchange.is_(None))
    ).all()}
    local_open = Position.query.filter(
        Position.status == 'open',
        Position.strategy_id.in_(okx_strat_ids) if okx_strat_ids else False,
    ).all() if okx_strat_ids else []

    # 用 (symbol, side) 當 key 對齊
    okx_by_key = {}
    for p in okx_positions:
        key = (p['symbol'], p['side'])
        okx_by_key[key] = p

    local_by_key = {}
    for p in local_open:
        key = (p.symbol, p.side or 'long')
        local_by_key[key] = p

    # === (a) local 有，OKX 無 ===
    for key, lp in local_by_key.items():
        if key not in okx_by_key:
            try:
                # 拿當前價當 exit_price，標 reconcile_orphan
                t = get_ticker(lp.symbol)
                current = float(t.get('price') or t.get('last') or lp.entry_price)
                pnl_raw_pct = (current - lp.entry_price) / lp.entry_price * 100
                pnl_pct = pnl_raw_pct * 15.0   # 用 15x 假設；reconcile 場景估算夠了
                pnl = pnl_raw_pct * lp.size * lp.entry_price * 15.0 / 100
                trade = Trade(
                    position_id=lp.id, strategy_id=lp.strategy_id,
                    user_id=lp.user_id,
                    symbol=lp.symbol, side=lp.side or 'long',
                    entry_price=lp.entry_price, exit_price=current,
                    quantity=lp.size, pnl=pnl, pnl_percent=pnl_pct,
                    entry_time=lp.opened_at, exit_time=datetime.datetime.utcnow(),
                    reason='reconcile_orphan',   # OKX 沒這倉了，本地補平
                )
                lp.status = 'closed'
                lp.closed_at = datetime.datetime.utcnow()
                lp.current_price = current
                lp.realized_pnl = pnl
                db.session.add(trade)
                actions.append({
                    'type': 'local_orphan_closed',
                    'position_id': lp.id,
                    'strategy_id': lp.strategy_id,
                    'symbol': lp.symbol,
                    'pnl': round(pnl, 4),
                })
                _tg(
                    f'⚠️ <b>账户对账 · Reconcile: 持仓已自动关闭 / Position Auto-Closed</b>\n'
                    f'系统记录的持仓 #{lp.id} ({lp.symbol} {lp.side}) 显示在持仓中，但交易所已平掉。\n'
                    f'Local position #{lp.id} was still open, but already closed on exchange.\n'
                    f'已同步关闭本地记录 / Synced local close · 估算盈亏 / Est PnL: ${pnl:.2f}',
                    event_key=f'orphan_local_{lp.id}',
                )
            except Exception as e:
                actions.append({'type': 'local_orphan_error', 'position_id': lp.id, 'error': str(e)})

    db.session.commit()

    # === (b) OKX 有，local 無 — 最危險 ===
    okx_orphans = []
    for key, op in okx_by_key.items():
        if key not in local_by_key:
            okx_orphans.append(op)

    if okx_orphans:
        details = '\n'.join(
            f'  {p["inst_id"]} {p["side"]} {abs(p["pos_contracts"])} @ ${p["avg_px"]:.0f}'
            for p in okx_orphans
        )
        set_halted(f'reconcile: OKX 有 {len(okx_orphans)} 個本地不存在的持倉')
        _tg(
            f'🚨 <b>账户对账 · Reconcile: 发现异常持仓 / Unknown Position (已自动停单 / Auto-Halted)</b>\n'
            f'交易所有系统不知道的持仓 / Exchange has positions not in our DB:\n{details}\n\n'
            f'请到交易所检查是手动开的还是策略误开, 平仓后到 Dashboard 解除停单.\n'
            f'Check exchange manually, close positions, then resolve halt on Dashboard.',
            event_key='orphan_okx', force=True,
        )
        actions.append({'type': 'okx_orphan_halted', 'count': len(okx_orphans), 'details': okx_orphans})

    # === (c) 兩邊都有 — 比對 size / avg_px ===
    from app.services.symbols import get_contract_size
    drift_alerts = []
    for key in set(okx_by_key.keys()) & set(local_by_key.keys()):
        op = okx_by_key[key]
        lp = local_by_key[key]
        # OKX 的 pos 是合約張數，每幣種 ctVal 不同（BTC=0.01, ETH=0.1, SOL=1, DOGE=1000 ...）
        contract_size = get_contract_size(lp.symbol)
        okx_btc = abs(op['pos_contracts']) * contract_size
        if abs(okx_btc - lp.size) / max(lp.size, 1e-9) > 0.05:   # > 5% 偏差
            drift_alerts.append({
                'position_id': lp.id, 'symbol': lp.symbol,
                'local_size': lp.size, 'okx_size_btc': okx_btc,
            })

    if drift_alerts:
        details = '\n'.join(
            f'  #{d["position_id"]} {d["symbol"]} 本地 {d["local_size"]:.6f} vs OKX {d["okx_size_btc"]:.6f}'
            for d in drift_alerts
        )
        _tg(
            f'⚠️ <b>账户对账 · Reconcile: 持仓大小不一致 / Size Drift</b>\n{details}\n\n'
            f'不影响运行, 但建议手动检查 / Not blocking but please verify manually.',
            event_key='size_drift',
        )
        actions.append({'type': 'size_drift', 'items': drift_alerts})

    return {
        'ok': True,
        'okx_open_count': len(okx_positions),
        'local_open_count': len(local_open),
        'actions': actions,
        'is_halted_now': bool(okx_orphans),
    }
