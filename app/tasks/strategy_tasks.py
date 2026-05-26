"""Celery 定時任務 — 模擬盤模式（不下真單）"""
import random
import time
from datetime import datetime
from app.extensions import celery_app, db
from app.models import Strategy, Position, Trade, Order, Candle
from app.services.exchange_service import get_ticker
from app.services.strategy_engine import get_signal, get_candle_df

# ===== 模擬盤設定（fallback 值；實際從 SystemConfig 動態讀） =====
SIMULATED_BALANCE = 100.0       # 仍保留以兼容舊 import；運行時看 config
LEVERAGE = 15
TRADE_SIZE_USDT = 10.0
STOP_LOSS_PCT = 5.0
TAKE_PROFIT_PCT = 8.0


def _cfg():
    """每個 task 入口呼叫一次，30s cache 內共用同一份 config"""
    from app.services.config_service import get_config
    return get_config()


def _simulated_order(symbol, side, amount_usdt, price):
    """模擬下單（不發送到交易所）"""
    return {
        'id': f'sim_{int(time.time()*1000)}_{random.randint(1000,9999)}',
        'symbol': symbol,
        'side': side,
        'type': 'market',
        'amount': amount_usdt / price,
        'price': price,
        'cost': amount_usdt,
        'fee': {'cost': amount_usdt * 0.001, 'currency': 'USDT'},
        'status': 'closed',
        'simulated': True,
    }


def _place_order(symbol, side, amount_usdt, price, mode: str, leverage: float = 15.0,
                 pos_side: str | None = None, user_id: int | None = None,
                 order_type: str = 'market', exchange: str = 'okx'):
    """Phase 6.5 + 11.1.4 + 11.2.2 + 13 + 14k: 模式 + 交易所分派.

    mode:
      paper — 模擬 (no exchange call)
      live  — 真实下单 (走 exchange 参数指定的交易所)

    exchange (Phase 14k):
      okx          — OKX swap 永续合约 (cross margin) [默认]
      hyperliquid  — Hyperliquid DEX perp (ECDSA agent wallet)

    order_type: market / maker / maker_with_fallback (HL 暂只支持 market)
    失敗時 fallback 寫 telegram，return None。
    """
    effective_mode = mode
    user_creds = None
    exchange = (exchange or 'okx').lower()

    if mode == 'live':
        if exchange == 'hyperliquid':
            from app.services.hyperliquid_creds import get_decrypted_for_user as _hl_creds, is_expired as _hl_expired
            user_creds = _hl_creds(user_id)
            if not user_creds or not user_creds.get('agent_private_key'):
                effective_mode = 'paper'
                try:
                    from app.services.audit import log as _audit
                    _audit('live_order_blocked_no_hl_key', actor='system',
                           user_id=user_id, symbol=symbol, side=side, amount_usdt=amount_usdt,
                           reason='Phase 14k — user has no active Hyperliquid agent')
                except Exception:
                    pass
                print(f'[guard] user_id={user_id} LIVE→paper ({symbol} {side}) — 未綁 Hyperliquid agent')
            elif _hl_expired(user_id):
                # Phase 14k-6: HL agent 已过期 → 强制 paper + Telegram 告警
                effective_mode = 'paper'
                user_creds = None
                try:
                    from app.services.audit import log as _audit
                    _audit('live_order_blocked_hl_expired', actor='system',
                           user_id=user_id, symbol=symbol, side=side, amount_usdt=amount_usdt,
                           reason='Phase 14k-6 — HL agent 180 天授权已过期, 需重新签名')
                    from app.services.telegram_service import send as _tg
                    _tg(f'🔴 <b>HL agent 已过期</b>\nuser_id={user_id}: agent wallet 授权过期, 已停 LIVE. 去 Settings 重新绑定.',
                        event_key=f'hl_expired_{user_id}')
                except Exception:
                    pass
                print(f'[guard] user_id={user_id} LIVE→paper ({symbol} {side}) — HL agent 已过期')
        else:
            from app.services.exchange_service import _resolve_creds
            user_creds = _resolve_creds(user_id)
            if not user_creds or not (user_creds.get('api_key') and user_creds.get('secret') and user_creds.get('passphrase')):
                effective_mode = 'paper'
                try:
                    from app.services.audit import log as _audit
                    _audit('live_order_blocked_no_okx_key', actor='system',
                           user_id=user_id, symbol=symbol, side=side, amount_usdt=amount_usdt,
                           reason='Phase 11.2.2 — user has no active OKX credentials')
                except Exception:
                    pass
                print(f'[guard] user_id={user_id} LIVE→paper ({symbol} {side}) — 未綁 OKX key 或已停用')

    if effective_mode == 'live':
        try:
            # Phase 14k: Hyperliquid 分支 (DEX perp, ECDSA agent)
            if exchange == 'hyperliquid':
                from app.services.hyperliquid_service import place_order_live as hl_place
                # HL 不支持 maker post_only via 该接口, 全走 market IOC
                if order_type in ('maker', 'maker_with_fallback'):
                    print(f'[HL] order_type={order_type} 暂不支持, 降级 market')
                hl_res = hl_place(symbol, side, amount_usdt, leverage=leverage, creds=user_creds)
                if not hl_res.get('ok'):
                    from app.services.telegram_service import send
                    send(f'🔴 <b>HL order FAILED</b>\n{symbol} {side} ${amount_usdt}\n{hl_res.get("raw")}',
                         event_key='hl_order_error')
                    return None
                raw = hl_res.get('raw') or {}
                response_data = (raw.get('response', {}).get('data', {}).get('statuses') or [{}])[0]
                filled = response_data.get('filled') or {}
                return {
                    'id': str(filled.get('oid') or 'hl_unknown'),
                    'symbol': symbol, 'side': side, 'type': 'market',
                    'amount': hl_res.get('size_base'),
                    'price': float(filled.get('avgPx') or price),
                    'cost': amount_usdt,
                    'inst_id': f"{hl_res.get('base')}-PERP",
                    'simulated': False,
                    'hl_raw': raw,
                    'exchange': 'hyperliquid',
                }

            # ─── OKX (默认) ───
            if order_type in ('maker', 'maker_with_fallback'):
                # Phase 13: maker order
                from app.services.exchange_service import place_order_maker_live
                fallback = 'taker' if order_type == 'maker_with_fallback' else 'cancel'
                res = place_order_maker_live(
                    symbol, side, amount_usdt, leverage=leverage,
                    max_wait_sec=60, fallback=fallback,
                    pos_side=pos_side, creds=user_creds,
                )
                if not res.get('ok'):
                    err_msg = res.get('error', 'maker fail')
                    from app.services.telegram_service import send
                    send(f'🟡 <b>maker order 未成交</b>\n{symbol} {side} ${amount_usdt}\n{err_msg[:200]}',
                         event_key='maker_timeout')
                    return None
                return {
                    'id': res['okx'].get('ordId', 'maker_unknown') if isinstance(res.get('okx'), dict) else 'maker_unknown',
                    'symbol': symbol, 'side': side, 'type': res.get('ord_type', 'maker'),
                    'amount': res.get('contracts', 0) * 0.01,
                    'price': res.get('entry_price_est', price),
                    'cost': amount_usdt,
                    'inst_id': res.get('inst_id'),
                    'simulated': False,
                    'okx_raw': res.get('okx'),
                    'wait_sec': res.get('wait_sec', 0),
                }
            # default: market (taker)
            from app.services.exchange_service import place_order_live
            res = place_order_live(symbol, side, amount_usdt, leverage=leverage, pos_side=pos_side, creds=user_creds)
            return {
                'id': res['okx'].get('ordId', 'live_unknown'),
                'symbol': symbol, 'side': side, 'type': 'market',
                'amount': res['contracts'] * 0.01,
                'price': res['entry_price_est'],
                'cost': amount_usdt,
                'inst_id': res['inst_id'],
                'simulated': False,
                'okx_raw': res['okx'],
            }
        except Exception as e:
            from app.services.telegram_service import send
            send(f'🔴 <b>LIVE order FAILED</b>\n{symbol} {side} ${amount_usdt}\n{type(e).__name__}: {e}',
                 event_key='live_order_error')
            print(f'[live_order] {type(e).__name__}: {e}')
            return None
    return _simulated_order(symbol, side, amount_usdt, price)


@celery_app.task
def fetch_market_data():
    """定時獲取市場數據（每小時執行）"""
    strategies = Strategy.query.filter_by(status='running').all()
    symbols = set((s.symbol, s.timeframe) for s in strategies)

    for symbol, timeframe in symbols:
        try:
            from app.services.exchange_service import fetch_ohlcv
            fetch_ohlcv(symbol, timeframe, limit=500)
        except Exception as e:
            print(f'[fetch] {symbol} {timeframe} 失敗: {e}')
    return f'已更新 {len(symbols)} 組K線'


@celery_app.task
def run_strategy_signals(strategy_id=None):
    """執行策略信號計算 — 波段/長線（4h）"""
    return _run_signals(strategy_id, category_filter=None)


@celery_app.task
def run_strategy_signals_short():
    """短線策略（1h）"""
    return _run_signals(None, category_filter='short')


@celery_app.task
def run_strategy_signals_ultra():
    """極短策略（15m）"""
    return _run_signals(None, category_filter='ultra')


def _run_signals(strategy_id=None, category_filter=None):
    """執行策略信號計算（模擬盤模式）"""
    if strategy_id:
        strategies = Strategy.query.filter_by(id=strategy_id, status='running').all()
    elif category_filter:
        strategies = Strategy.query.filter_by(status='running', category=category_filter).all()
    else:
        strategies = Strategy.query.filter_by(status='running').filter(
            Strategy.category.in_(['swing', 'long'])
        ).all()

    if not strategies:
        return '無運行中的策略'

    # 讀一次 config，循環內共用
    cfg = _cfg()
    trade_size_default = cfg['trade_size_usdt']
    lev_default = cfg['leverage']
    sl_pct_default = cfg['stop_loss_pct']
    tp_pct_default = cfg['take_profit_pct']
    halted = cfg.get('halted', False)
    mode = cfg.get('trading_mode', 'paper')

    def _resolve_risk(s):
        """Phase 12.42 v8 + 13 + 14d + 14e: per-strategy risk_params override
        14e: 同时接受 sl_pct/tp_pct (catalog 简写) 和 stop_loss_pct/take_profit_pct (v8) — alias 修
        """
        rp = (s.params or {}).get('risk_params') or {}
        return (
            rp.get('position_size_usdt') or trade_size_default,
            rp.get('leverage') or lev_default,
            rp.get('stop_loss_pct') or rp.get('sl_pct') or sl_pct_default,
            rp.get('take_profit_pct') or rp.get('tp_pct') or tp_pct_default,
            rp.get('order_type') or 'market',
        )

    def _is_paper_only(s) -> bool:
        """Phase 14d: AI invent 策略 7 天 paper-only dry-run"""
        paper_until = (s.params or {}).get('paper_only_until')
        if not paper_until:
            return False
        try:
            import datetime as _dt
            until = _dt.datetime.fromisoformat(paper_until)
            return _dt.datetime.utcnow() < until
        except Exception:
            return False

    results = []
    for s in strategies:
        trade_size, lev, sl_pct, tp_pct, ord_type = _resolve_risk(s)
        # Phase 14d: paper-only 强制覆盖 mode
        strategy_mode = 'paper' if _is_paper_only(s) else mode
        try:
            # 取得K線
            candles = Candle.query.filter_by(
                symbol=s.symbol, timeframe=s.timeframe
            ).order_by(Candle.timestamp.asc()).all()

            if len(candles) < 30:
                results.append(f'{s.name}: K線不足({len(candles)})')
                continue

            df = get_candle_df([c.to_dict() for c in candles])
            signal = get_signal(s.type, df, s.params)

            if signal == 'hold':
                results.append(f'{s.name}: 無信號')
                continue

            # 取得持倉狀態
            position = Position.query.filter_by(
                strategy_id=s.id, status='open'
            ).first()

            # Phase 9.2: long-only → 支援 short。決策矩陣：
            #   無持倉 + buy/long  → 開多
            #   無持倉 + sell/short → 開空
            #   多倉 + sell/close  → 平多
            #   空倉 + buy/close   → 平空
            #   同向重複 → 略過
            is_buy = signal in ('buy', 'long')
            is_sell = signal in ('sell', 'short')
            is_close = signal == 'close'

            if not position and is_close:
                results.append(f'{s.name}: 無持倉，無需平倉')
                continue

            if position:
                if position.side == 'long' and is_buy:
                    results.append(f'{s.name}: 多倉中，買信號略過')
                    continue
                if position.side == 'short' and is_sell:
                    results.append(f'{s.name}: 空倉中，賣信號略過')
                    continue
                # 反向信號 → 平倉
                action = 'close'
            else:
                # 無持倉 → 開倉，方向看 signal
                action = 'open_long' if is_buy else 'open_short'

            # Phase 6.1: halted 時拒新開倉，但允許平倉
            if halted and action in ('open_long', 'open_short'):
                results.append(f'⛔ {s.name}: 系統 HALTED，拒絕開倉信號')
                continue

            # 獲取當前價格
            ticker = get_ticker(s.symbol)
            price = ticker['price']

            if action in ('open_long', 'open_short'):
                side = 'long' if action == 'open_long' else 'short'
                okx_side = 'buy' if side == 'long' else 'sell'

                # Phase 12.35.1: first-mover gate — 同 (symbol, side) 已有 open Position 则跳过
                # OKX (instId, posSide) 是唯一键，多策略同方向会被合并 → PnL 归属混乱
                existing_pos = Position.query.filter_by(
                    symbol=s.symbol, side=side, status='open'
                ).first()
                if existing_pos and existing_pos.strategy_id != s.id:
                    results.append(
                        f'⛔ {s.name}: 跳過 — {s.symbol} {side} 已被策略 #{existing_pos.strategy_id} 持倉（first-mover 獨佔）'
                    )
                    from app.services.telegram_service import send as _tg
                    _tg(
                        f'⚠️ <b>{s.name} 信号跳过</b>\n'
                        f'{s.symbol} {side} 已被策略 #{existing_pos.strategy_id} 持仓\n'
                        f'OKX 合并仓位防错，本次 {action} 信号不下单。\n'
                        f'等持仓策略平仓后才能开新仓。'
                    )
                    continue

                # Phase 9.3: 動態倉位（依 sizing_mode）
                from app.services.position_sizing import compute_size
                effective_size, sizing_debug = compute_size(s, cfg, trade_size)
                amount_base = round(effective_size / price, 6)
                notional = amount_base * price * lev

                # Phase 12.7+12.8+12.9.2: 先算出實際合約持倉，超額就跳過下單
                intended_base = (effective_size * lev) / price
                intended_notional = intended_base * price
                real_size = intended_base
                if mode == 'live':
                    from app.services.symbols import get_contract_size
                    contract_size = get_contract_size(s.symbol)
                    contracts_target = max(1, round(intended_base / contract_size))
                    real_size = contracts_target * contract_size
                    real_notional = real_size * price
                    # Phase 12.9.2: 超額檢查**必須**在 _place_order 之前 — 之前順序顛倒，
                    # OKX 真下單後才檢查，跳過的只是本地 Position 寫入 → OKX 孤兒
                    if intended_notional > 0 and real_notional / intended_notional > 1.5:
                        results.append(
                            f'⛔ {s.name}: 跳過 — 合約最小張數 ${real_notional:.0f} '
                            f'超過目標 ${intended_notional:.0f} 太多（{(real_notional/intended_notional-1)*100:.0f}%）。'
                            f'若想做 {s.symbol}，提高 trade_size 到 ${effective_size * (real_notional/intended_notional):.0f} 以上'
                        )
                        from app.services.telegram_service import send as _tg
                        _tg(
                            f'⚠️ <b>{s.name} 跳過下單</b>\n'
                            f'{s.symbol} 最小合約 ${real_notional:.0f} >> 目標 ${intended_notional:.0f}\n'
                            f'建議：提高 trade_size 或關掉此 symbol。'
                        )
                        continue

                order = _place_order(s.symbol, okx_side, effective_size, price, strategy_mode, leverage=lev, pos_side=side, user_id=s.user_id, order_type=ord_type, exchange=(s.exchange or 'okx'))
                if order is None:
                    results.append(f'⛔ {s.name}: 下單失敗（live mode），略過')
                    continue

                # Phase 9.4: 開倉時計算絕對 SL/TP（ATR mode）
                from app.services.risk_levels import compute_sl_tp
                sl_price, tp_price, sl_dbg = compute_sl_tp(
                    symbol=s.symbol, timeframe=s.timeframe, side=side,
                    entry_price=price, cfg=cfg,
                )

                pos = Position(
                    strategy_id=s.id,
                    user_id=s.user_id,
                    symbol=s.symbol,
                    side=side,
                    size=real_size,
                    entry_price=price,
                    current_price=price,
                    status='open',
                    sl_price=sl_price,
                    tp_price=tp_price,
                )
                db.session.add(pos)
                db.session.commit()
                emoji = '🟢' if side == 'long' else '🔴'
                size_note = ''
                if sizing_debug.get('mode') != 'flat':
                    size_note = f' [size×{sizing_debug.get("multiplier", 1):.2f}]'
                results.append(
                    f'{emoji} {s.name}: 開{("多" if side=="long" else "空")} {amount_base} @ ${price:.1f} '
                    f'(本金${effective_size:.1f}{size_note}, 槓桿{lev}x, 名義${notional:.0f})'
                )
                from app.services.telegram_service import notify_open
                notify_open(s.name, s.symbol, side, amount_base, price, notional)

            elif action == 'close':
                # 平倉 PnL：long 是 exit-entry，short 是 entry-exit
                if position.side == 'long':
                    pnl_raw_pct = (price - position.entry_price) / position.entry_price * 100
                    okx_side = 'sell'
                else:   # short
                    pnl_raw_pct = (position.entry_price - price) / position.entry_price * 100
                    okx_side = 'buy'
                pnl_pct = pnl_raw_pct * lev
                # Phase 12.8: size 已含 lev，PnL = size × delta_price，不再 × lev
                pnl_leveraged = pnl_raw_pct * position.size * position.entry_price / 100

                order = _place_order(s.symbol, okx_side, position.size * price, price, strategy_mode, leverage=lev, pos_side=position.side, user_id=s.user_id, order_type=ord_type, exchange=(s.exchange or 'okx'))

                # Phase 12.10 + 14k-12: live 平倉用 OKX 真實 balChg 覆寫 PnL (含手續費)
                # HL 策略 skip — HL fill 信息在 order_raw 里, PnL 系统自算
                if mode == 'live' and order and not order.get('simulated') and (s.exchange or 'okx') == 'okx':
                    try:
                        from app.services.exchange_service import fetch_okx_order_real_pnl, _okx_symbol, _resolve_creds
                        ord_id = order.get('id') if isinstance(order, dict) else None
                        real = fetch_okx_order_real_pnl(_okx_symbol(s.symbol).replace('/', '-') + '-SWAP', ord_id,
                                                          creds=_resolve_creds(s.user_id))
                        if real.get('found'):
                            pnl_leveraged = real['real_pnl']
                    except Exception:
                        pass

                trade = Trade(
                    position_id=position.id,
                    strategy_id=s.id,
                    user_id=s.user_id,
                    symbol=s.symbol,
                    side=position.side,
                    entry_price=position.entry_price,
                    exit_price=price,
                    quantity=position.size,
                    pnl=pnl_leveraged,
                    pnl_percent=pnl_pct,
                    entry_time=position.opened_at,
                    exit_time=datetime.utcnow(),
                    reason='signal',
                )
                position.status = 'closed'
                position.closed_at = datetime.utcnow()
                position.realized_pnl = pnl_leveraged
                db.session.add(trade)
                db.session.commit()
                results.append(
                    f'✅ {s.name}: 平倉 @ ${price:.1f} '
                    f'PnL=${pnl_leveraged:.2f} ({pnl_pct:+.2f}%)'
                )
                from app.services.telegram_service import notify_close
                notify_close(s.name, s.symbol, price, pnl_leveraged, pnl_pct, 'signal')

        except Exception as e:
            results.append(f'{s.name}: 錯誤 - {e}')
            db.session.rollback()

    return ' | '.join(results)


def _pnl_pct_for(pos, current_price, leverage):
    """Phase 9.2: 同時支援 long/short 的 PnL% 計算（含槓桿）"""
    if pos.side == 'short':
        raw_pct = (pos.entry_price - current_price) / pos.entry_price * 100
    else:   # long
        raw_pct = (current_price - pos.entry_price) / pos.entry_price * 100
    return raw_pct * leverage, raw_pct   # leveraged, raw


@celery_app.task
def update_positions():
    """更新持倉當前價格和浮動盈虧（含槓桿）— long/short 都正確
    Phase 12.42 v8: per-strategy leverage override 优先于 cfg
    """
    cfg_lev = _cfg()['leverage']
    positions = Position.query.filter_by(status='open').all()
    for pos in positions:
        try:
            ticker = get_ticker(pos.symbol)
            current = ticker['price']
            pos.current_price = current
            # 拉对应 strategy 的 leverage override
            lev = cfg_lev
            if pos.strategy_id:
                strat = Strategy.query.get(pos.strategy_id)
                if strat:
                    rp = (strat.params or {}).get('risk_params') or {}
                    lev = rp.get('leverage') or cfg_lev
            _, raw_pct = _pnl_pct_for(pos, current, lev)
            pos.unrealized_pnl = raw_pct * pos.size * pos.entry_price / 100
        except Exception as e:
            print(f'[update] 持倉 {pos.id} 更新失敗: {e}')
    db.session.commit()
    return f'已更新 {len(positions)} 個持倉'


@celery_app.task
def check_stop_loss():
    """檢查止損止盈（含槓桿）— long/short + flat_pct/atr 都觸發
    Phase 12.42 v8: per-strategy leverage/SL/TP override
    """
    cfg = _cfg()
    cfg_lev = cfg['leverage']
    cfg_sl_pct = cfg['stop_loss_pct']
    cfg_tp_pct = cfg['take_profit_pct']
    mode = cfg.get('trading_mode', 'paper')

    positions = Position.query.filter_by(status='open').all()
    triggered = []
    for pos in positions:
        try:
            ticker = get_ticker(pos.symbol)
            current = ticker['price']
            # 拉对应 strategy 的 leverage/SL/TP override
            lev, sl_pct, tp_pct = cfg_lev, cfg_sl_pct, cfg_tp_pct
            if pos.strategy_id:
                strat = Strategy.query.get(pos.strategy_id)
                if strat:
                    rp = (strat.params or {}).get('risk_params') or {}
                    lev = rp.get('leverage') or cfg_lev
                    sl_pct = rp.get('stop_loss_pct') or rp.get('sl_pct') or cfg_sl_pct
                    tp_pct = rp.get('take_profit_pct') or rp.get('tp_pct') or cfg_tp_pct
            pnl_pct, raw_pct = _pnl_pct_for(pos, current, lev)
            close_side = 'buy' if pos.side == 'short' else 'sell'

            # Phase 9.4: 優先用 position 自帶的絕對 SL/TP（ATR mode）
            sl_hit = False
            tp_hit = False
            if pos.sl_price and pos.tp_price:
                if pos.side == 'long':
                    sl_hit = current <= pos.sl_price
                    tp_hit = current >= pos.tp_price
                else:   # short
                    sl_hit = current >= pos.sl_price
                    tp_hit = current <= pos.tp_price
            else:
                # flat % rule（原本邏輯）
                sl_hit = pnl_pct <= -sl_pct
                tp_hit = pnl_pct >= tp_pct

            if sl_hit:
                _exch = (pos.strategy.exchange if pos.strategy else 'okx') or 'okx'
                order = _place_order(pos.symbol, close_side, pos.size * current, current, mode, leverage=lev, pos_side=pos.side, user_id=pos.user_id, exchange=_exch)
                pnl = raw_pct * pos.size * pos.entry_price / 100   # Phase 12.8: size 已含 lev
                # Phase 12.10 + 14k-12: live 用 OKX 真實 balChg 覆寫 PnL — 仅 OKX 路径
                _strat_exch = (pos.strategy.exchange if pos.strategy else 'okx') or 'okx'
                if mode == 'live' and order and not order.get('simulated') and _strat_exch == 'okx':
                    try:
                        from app.services.exchange_service import fetch_okx_order_real_pnl, _resolve_creds
                        inst = pos.symbol.replace('/', '-') + '-SWAP'
                        ord_id = order.get('id') if isinstance(order, dict) else None
                        real = fetch_okx_order_real_pnl(inst, ord_id, creds=_resolve_creds(pos.user_id))
                        if real.get('found'):
                            pnl = real['real_pnl']
                    except Exception:
                        pass
                trade = Trade(
                    position_id=pos.id,
                    strategy_id=pos.strategy_id,
                    user_id=pos.user_id,
                    symbol=pos.symbol,
                    side=pos.side,
                    entry_price=pos.entry_price,
                    exit_price=current,
                    quantity=pos.size,
                    pnl=pnl,
                    pnl_percent=pnl_pct,
                    entry_time=pos.opened_at,
                    exit_time=datetime.utcnow(),
                    reason='stop_loss',
                )
                pos.status = 'closed'
                pos.closed_at = datetime.utcnow()
                pos.realized_pnl = pnl
                db.session.add(trade)
                db.session.commit()
                triggered.append(f'{pos.symbol} 止損 @ ${current:.1f} ({pnl_pct:.1f}%)')
                from app.services.telegram_service import notify_close
                notify_close(pos.symbol, pos.symbol, current, pnl, pnl_pct, 'stop_loss')

            elif tp_hit:
                _exch = (pos.strategy.exchange if pos.strategy else 'okx') or 'okx'
                order = _place_order(pos.symbol, close_side, pos.size * current, current, mode, leverage=lev, pos_side=pos.side, user_id=pos.user_id, exchange=_exch)
                pnl = raw_pct * pos.size * pos.entry_price / 100   # Phase 12.8: size 已含 lev
                # Phase 14k-12: 仅 OKX 走 balChg 覆写
                if mode == 'live' and order and not order.get('simulated') and _exch == 'okx':
                    try:
                        from app.services.exchange_service import fetch_okx_order_real_pnl, _resolve_creds
                        inst = pos.symbol.replace('/', '-') + '-SWAP'
                        ord_id = order.get('id') if isinstance(order, dict) else None
                        real = fetch_okx_order_real_pnl(inst, ord_id, creds=_resolve_creds(pos.user_id))
                        if real.get('found'):
                            pnl = real['real_pnl']
                    except Exception:
                        pass
                trade = Trade(
                    position_id=pos.id,
                    strategy_id=pos.strategy_id,
                    user_id=pos.user_id,
                    symbol=pos.symbol,
                    side=pos.side,
                    entry_price=pos.entry_price,
                    exit_price=current,
                    quantity=pos.size,
                    pnl=pnl,
                    pnl_percent=pnl_pct,
                    entry_time=pos.opened_at,
                    exit_time=datetime.utcnow(),
                    reason='take_profit',
                )
                pos.status = 'closed'
                pos.closed_at = datetime.utcnow()
                pos.realized_pnl = pnl
                db.session.add(trade)
                db.session.commit()
                triggered.append(f'{pos.symbol} 止盈 @ ${current:.1f} ({pnl_pct:.1f}%)')
                from app.services.telegram_service import notify_close
                notify_close(pos.symbol, pos.symbol, current, pnl, pnl_pct, 'take_profit')

        except Exception as e:
            print(f'[sl] 檢查失敗: {e}')

    return f'觸發 {len(triggered)} 個' if triggered else '無觸發'


# ===== Phase 5.3: 策略健康監控 / 自動退役 =====

# 退役門檻（Phase 12.9 放寬：之前 11 個策略一次被誤殺）
RETIRE_SHARPE_FULL = -0.5      # 全段 Sharpe 跌破 -0.5（真的虧損）→ 退役
RETIRE_SHARPE_OOS = -1.0       # OOS Sharpe 跌破 -1.0 → 真的不行了
RETIRE_MIN_TRADES = 12         # 樣本不足就不退役
RETIRE_GRACE_HOURS = 168       # Phase 12.9.1: 7 天保護期（48h 太短，可能整窗口落在週末 / 行情清淡）


@celery_app.task
def monitor_strategy_health():
    """每日跑 — 對每個 running 策略做新 walkforward 回測，跌穿門檻就自動退役。

    退役 = status='retired' + retired_at + retire_reason，
    跟 user 手動 'stopped' 區分。Position 不動（讓 SL/TP 自然觸發）。
    """
    from datetime import datetime
    from app.services.exchange_service import fetch_ohlcv_history
    from app.services.backtest_engine import run_walkforward_backtest
    from app.services.strategy_engine import get_signal
    from app.services.candidate_sandbox import load_signal_fn
    from app.models import StrategyCandidate, BacktestResult

    running = Strategy.query.filter_by(status='running').all()
    if not running:
        return 'no running strategies'

    actions = []
    from datetime import datetime, timedelta
    grace_cutoff = datetime.utcnow() - timedelta(hours=RETIRE_GRACE_HOURS)
    for s in running:
        try:
            # Phase 12.9: 保護期 — 創建 < 7 天的策略不 auto-retire
            if s.created_at and s.created_at > grace_cutoff:
                days = RETIRE_GRACE_HOURS / 24
                actions.append(f'⏸ {s.name}: 保護期內（< {days:.0f} 天），跳過 auto-retire')
                continue

            candles = fetch_ohlcv_history(s.symbol, s.timeframe, total_limit=2000)
            if len(candles) < 200:
                actions.append(f'{s.name}: 跳過 (K線不足 {len(candles)})')
                continue

            # candidate-backed 策略要動態載入 signal_fn
            signal_fn = None
            if s.candidate_id:
                c = StrategyCandidate.query.get(s.candidate_id)
                if c and c.parsed_signal and c.signal_fn_name:
                    try:
                        signal_fn = load_signal_fn(c.parsed_signal, c.signal_fn_name)
                    except Exception as e:
                        actions.append(f'{s.name}: 跳過 (signal_fn 載入失敗: {e})')
                        continue

            wf = run_walkforward_backtest(
                s.type, s.params or {}, candles,
                timeframe=s.timeframe, signal_fn=signal_fn,
            )

            if wf.get('status') == 'error':
                actions.append(f'{s.name}: 回測錯誤 {wf.get("error_message")}')
                continue

            full = wf['full']
            oos = wf.get('out_sample') or {}
            full_sh = full.get('sharpe_ratio')
            oos_sh = oos.get('sharpe_ratio')
            total_trades = full.get('total_trades', 0)

            # 寫 BacktestResult 留檔（不論退不退）
            bt = BacktestResult(
                strategy_id=s.id, strategy_type=s.type,
                params_snapshot=s.params or {}, symbol=s.symbol, timeframe=s.timeframe,
                leverage=15.0, position_size_usdt=10.0,
                stop_loss_pct=5.0, take_profit_pct=8.0, initial_capital=100.0,
                period_start=full['period_start'], period_end=full['period_end'],
                candle_count=full['candle_count'],
                total_trades=full['total_trades'], winning_trades=full['winning_trades'],
                losing_trades=full['losing_trades'], win_rate=full['win_rate'],
                total_pnl=full['total_pnl'], avg_pnl=full['avg_pnl'],
                avg_win=full['avg_win'], avg_loss=full['avg_loss'],
                profit_factor=full['profit_factor'],
                max_drawdown=full['max_drawdown'], max_drawdown_pct=full['max_drawdown_pct'],
                sharpe_ratio=full_sh, final_equity=full['final_equity'],
                annual_return_pct=full['annual_return_pct'],
                equity_curve=full['equity_curve'], trades_json=full['trades'],
                walkforward_json=wf, duration_ms=full['duration_ms'],
                status='completed',
            )
            db.session.add(bt)

            # 退役判斷
            retire_reasons = []
            if total_trades < RETIRE_MIN_TRADES:
                # 樣本太少，不主動退役但記錄一下
                pass
            else:
                if full_sh is not None and full_sh < RETIRE_SHARPE_FULL:
                    retire_reasons.append(f'full Sharpe {full_sh:.2f} < {RETIRE_SHARPE_FULL}')
                if oos_sh is not None and oos_sh < RETIRE_SHARPE_OOS:
                    retire_reasons.append(f'OOS Sharpe {oos_sh:.2f} < {RETIRE_SHARPE_OOS}')

            from app.services.audit import log as audit
            if retire_reasons:
                # Phase 12.11: 2-strike — 第一次只警告，連續兩次才真退役
                s.retire_warning_count = (s.retire_warning_count or 0) + 1
                if s.retire_warning_count >= 2:
                    s.status = 'retired'
                    s.retired_at = datetime.utcnow()
                    reason_txt = '; '.join(retire_reasons) + f' (strike #{s.retire_warning_count})'
                    s.retire_reason = f'auto-retire @ {datetime.utcnow().isoformat(timespec="seconds")}: ' + reason_txt
                    actions.append(f'🔴 {s.name} retired: {", ".join(retire_reasons)} (2nd strike)')
                    from app.services.telegram_service import notify_retire
                    notify_retire(s.name, reason_txt)
                    audit('strategy_retire', actor='auto:health_check', strategy_id=s.id,
                          name=s.name, reasons=retire_reasons, strikes=s.retire_warning_count)
                else:
                    actions.append(f'⚠️ {s.name} 警告 #{s.retire_warning_count}/2: {", ".join(retire_reasons)}')
                    audit('strategy_retire_warning', actor='auto:health_check', strategy_id=s.id,
                          name=s.name, reasons=retire_reasons, strike=s.retire_warning_count)
            else:
                # 通過 health check → 重置 strike 計數
                if s.retire_warning_count and s.retire_warning_count > 0:
                    actions.append(f'✅ {s.name} 恢復健康（清零 strike，原有 {s.retire_warning_count}）')
                    s.retire_warning_count = 0
                else:
                    actions.append(f'✅ {s.name} OK (full Sharpe={full_sh}, OOS={oos_sh}, trades={total_trades})')

            db.session.commit()

        except Exception as e:
            db.session.rollback()
            actions.append(f'{s.name}: EXCEPTION {type(e).__name__}: {e}')

    return ' | '.join(actions)


# ===== Phase 5.2: 候選池自動回測 =====

@celery_app.task
def auto_backtest_translated_candidates(max_count: int = 20):
    """每小時跑 — 把 status='translated' 的候選自動拉去 walk-forward 回測。
    通過門檻變 qualified，沒通過繼續 translated 等下次（如果 user 修了 params）。
    """
    from app.services.candidate_pipeline import backtest_all_translated
    result = backtest_all_translated(max_count=max_count)
    return f'auto-backtest: {result["count"]} 個跑完，{result["qualified"]} 個合格'


# ===== Phase 5.1: 自動爬蟲 + 翻譯 =====

@celery_app.task
def reconcile_okx_positions():
    """Phase 8.2: 每 5 min 對賬本地 vs OKX SWAP 持倉"""
    from app.services.reconciliation import reconcile
    r = reconcile()
    if not r.get('ok'):
        return f'reconcile error: {r.get("error")}'
    actions = r.get('actions', [])
    if not actions:
        return f'OK: OKX={r["okx_open_count"]} local={r["local_open_count"]}'
    return f'reconcile: {len(actions)} action(s) — {[a["type"] for a in actions]}'


@celery_app.task
def monitor_anomalies():
    """Phase 6.4: flash crash + 持倉密度檢查"""
    from app.services.anomaly_detector import run_all_checks
    r = run_all_checks()
    if r.get('halted'):
        return f'🛑 anomaly halt: {r["fired"]}'
    if r.get('skipped'):
        return r['skipped']
    return f'OK: {len(r.get("fired", []))} fired'


@celery_app.task
def monitor_daily_loss():
    """Phase 6.1: 每 5 分鐘檢查當日累積虧損是否觸發 halt"""
    from datetime import datetime, timezone
    from app.services.config_service import get_config, set_halted

    cfg = get_config()
    if cfg.get('halted'):
        return f'already halted: {cfg.get("halt_reason")}'

    max_loss = cfg.get('max_daily_loss_usdt', 10.0)
    if max_loss <= 0:
        return 'max_daily_loss_usdt <= 0, skip'

    # 今日 00:00 UTC
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)

    # realized = 今日 trades 的 pnl 加總
    realized = db.session.query(db.func.coalesce(db.func.sum(Trade.pnl), 0)).filter(Trade.exit_time >= today_start).scalar() or 0.0
    # unrealized = 當前 open positions 的浮動 pnl 加總
    unrealized = db.session.query(db.func.coalesce(db.func.sum(Position.unrealized_pnl), 0)).filter(Position.status == 'open').scalar() or 0.0
    total = float(realized) + float(unrealized)

    if total <= -max_loss:
        reason = f'daily loss {total:.2f} ≤ -{max_loss:.2f} (realized {realized:.2f} + unrealized {unrealized:.2f})'
        set_halted(reason)
        from app.services.telegram_service import notify_halt
        from app.services.audit import log as audit
        notify_halt(reason)
        audit('halt', actor='auto:daily_loss', reason=reason,
              realized=float(realized), unrealized=float(unrealized), threshold=-max_loss)
        return f'🛑 HALTED: {reason}'

    return f'OK: 今日 PnL ${total:.2f} (realized {realized:.2f} + unrealized {unrealized:.2f}) > -${max_loss:.2f}'


@celery_app.task
def auto_crawl_github(max_files_per_repo: int = 10):
    """每日跑 GitHub 爬蟲，把新策略灌進候選池（status=pending，dedup by source_url）"""
    from app.services.crawlers.github import crawl_all
    try:
        result = crawl_all(max_files_per_repo=max_files_per_repo)
        t = result['totals']
        return f'crawl: 偵測 {t["detected"]} 新增 {t["inserted"]} 略過 {t["skipped"]} 錯誤 {t["errors"]}'
    except Exception as e:
        return f'crawl 失敗: {type(e).__name__}: {e}'


@celery_app.task
def auto_translate_pending(max_count: int = 5):
    """容器內走 Anthropic SDK 翻譯 pending 候選 — 需要 ANTHROPIC_API_KEY。
    沒 key 就跳過、log 一行（user 應改用 host 端 translate_cli.py 跑 host cron）。
    """
    import os
    if not os.environ.get('ANTHROPIC_API_KEY'):
        return 'auto-translate skipped: no ANTHROPIC_API_KEY in env. 改用 host 端 translate_cli.py + crontab'

    from app.models import StrategyCandidate
    from app.services.candidate_pipeline import translate_and_verify

    pending = StrategyCandidate.query.filter_by(status='pending').order_by(StrategyCandidate.id).limit(max_count).all()
    if not pending:
        return 'auto-translate: 無 pending 候選'

    ok = err = 0
    for c in pending:
        try:
            r = translate_and_verify(c.id)
            if r.get('ok'):
                ok += 1
            else:
                err += 1
        except Exception:
            err += 1
    return f'auto-translate: {ok} 成功 / {err} 失敗 (共 {len(pending)} 個)'


# ===== Phase 10.2: parameter walk-forward grid search =====

@celery_app.task(bind=True)
def optimize_strategy_params(self, optimization_id: int, max_combos: int = 24):
    """執行已建立的 ParamOptimization 記錄 — 跑完寫回結果。"""
    from app.models import ParamOptimization, Strategy
    from app.services.param_optimizer import optimize
    import datetime as _dt

    opt = ParamOptimization.query.get(optimization_id)
    if not opt:
        return f'optimization {optimization_id} 不存在'

    strategy = Strategy.query.get(opt.strategy_id)
    if not strategy:
        opt.status = 'error'
        opt.error_message = 'strategy 不存在'
        opt.completed_at = _dt.datetime.utcnow()
        db.session.commit()
        return 'strategy 不存在'

    opt.status = 'running'
    db.session.commit()

    def _progress(done, total):
        try:
            opt.combos_done = done
            opt.combos_total = total
            db.session.commit()
        except Exception:
            db.session.rollback()

    try:
        # Phase 14k-30 #2: 如 opt.grid 不空 (AI 提议) 走它, 否则 fallback 死字典
        grid_override = opt.grid if opt.grid else None
        out = optimize(strategy, max_combos=max_combos, on_progress=_progress,
                       grid_override=grid_override)
        if 'error' in out:
            opt.status = 'error'
            opt.error_message = out['error']
        else:
            opt.grid = out['grid']
            opt.baseline_params = out['baseline_params']
            opt.baseline_oos_sharpe = out['baseline_oos_sharpe']
            opt.candidate_results = out['candidate_results']
            opt.best_params = out['best_params']
            opt.best_oos_sharpe = out['best_oos_sharpe']
            opt.combos_total = out['combos_total']
            opt.combos_done = out['combos_done']
            opt.status = 'completed'
        opt.completed_at = _dt.datetime.utcnow()
        db.session.commit()
        return f'optimize strategy={strategy.id} done: {opt.combos_done}/{opt.combos_total}'
    except Exception as e:
        db.session.rollback()
        opt.status = 'error'
        opt.error_message = f'{type(e).__name__}: {e}'
        opt.completed_at = _dt.datetime.utcnow()
        db.session.commit()
        return f'optimize error: {e}'


# ===== Phase 10.8: 智能托管 — 自動套用 advisor 建議 =====

@celery_app.task
def auto_apply_advisor():
    """每 4 小時跑一次。讀 SystemConfig.auto_apply_* 守衛 + 上限後，
    把使用者授權的 advisor 建議直接執行（apply_params / pause / retire / fan_out）。
    """
    from app.services.advisor_executor import run_auto_apply
    r = run_auto_apply()
    if r.get('skipped'):
        return f'auto-apply skipped: {r.get("reason")}'
    return f'auto-apply: 套用 {r["applied_count"]} 項（今日累計 {r["today_count_after"]}/{r["daily_cap"]}）'


# ===== Phase 10.9: 補洞任務 =====

@celery_app.task
def backtest_and_maybe_start(strategy_id: int):
    """Phase 10.9: 給 fan_out 新建的兄弟跑 walk-forward，過門檻 + auto_start 開就啟動，
    否則保持 stopped 並推 Telegram。
    """
    from app.models import Strategy
    from app.services.config_service import get_config
    from app.services.exchange_service import fetch_ohlcv_history
    from app.services.backtest_engine import run_walkforward_backtest
    from app.services.telegram_service import send as _tg

    strategy = Strategy.query.get(strategy_id)
    if not strategy:
        return f'strategy {strategy_id} 不存在'

    cfg = get_config()
    auto_start = bool(cfg.get('fan_out_auto_start'))
    min_sharpe = float(cfg.get('fan_out_min_oos_sharpe', 1.0))

    try:
        candles = fetch_ohlcv_history(strategy.symbol, strategy.timeframe, total_limit=2000)
    except Exception as e:
        try:
            _tg(f'🟡 兄弟回測失敗 #{strategy.id} {strategy.name}：拉 K 線錯誤 {e}')
        except Exception:
            pass
        return f'fetch failed: {e}'

    wf = run_walkforward_backtest(
        strategy.type, strategy.params or {}, candles,
        timeframe=strategy.timeframe,
        slippage_pct=cfg.get('backtest_slippage_pct', 0.05),
        fee_pct=cfg.get('backtest_fee_pct', 0.05),
    )
    oos = (wf.get('out_sample') or {}).get('sharpe_ratio')
    is_sh = (wf.get('in_sample') or {}).get('sharpe_ratio')

    msg_head = f'<b>兄弟策略回测</b> #{strategy.id} {strategy.name}\n交易对 {strategy.symbol} · {strategy.timeframe}'
    if oos is None:
        _tg(f'🟡 {msg_head}\n样本太少, OOS Sharpe 无法计算, 保持停止状态')
        return 'oos None, kept stopped'

    if oos >= min_sharpe:
        if auto_start:
            strategy.status = 'running'
            db.session.commit()
            _tg(f'🟢 {msg_head}\nOOS Sharpe {oos:.2f} ≥ 门槛 {min_sharpe} → 已自动启动')
            return f'started, oos={oos:.2f}'
        _tg(f'🟢 {msg_head}\nOOS Sharpe {oos:.2f} 通过, 但已关闭自动启动, 请手动开启')
        return f'passed but auto_start off, oos={oos:.2f}'
    _tg(f'🔴 {msg_head}\nOOS Sharpe {oos:.2f} < 门槛 {min_sharpe}, 行情不适合, 未启动')
    return f'rejected, oos={oos:.2f}'


@celery_app.task
def auto_optimize_running_strategies(max_combos: int = 24):
    """Phase 10.9: 每週給所有 running 策略排 walk-forward 網格搜尋，
    讓 apply_params 永遠有新弹药。跳過 7 天內已優化過的。
    """
    import datetime
    from app.models import Strategy, ParamOptimization
    from app.services.param_optimizer import get_grid, grid_size

    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    running = Strategy.query.filter(Strategy.status == 'running').all()
    queued = 0
    skipped = 0

    for s in running:
        grid = get_grid(s.type)
        if not grid:
            skipped += 1
            continue
        # 只把「7 天內 completed」當作已優化 — error/pending 不算，下次會重試
        recent = (
            ParamOptimization.query
            .filter(ParamOptimization.strategy_id == s.id)
            .filter(ParamOptimization.status == 'completed')
            .filter(ParamOptimization.started_at >= cutoff)
            .first()
        )
        if recent:
            skipped += 1
            continue
        # 防止重複進行中
        in_flight = ParamOptimization.query.filter(
            ParamOptimization.strategy_id == s.id,
            ParamOptimization.status.in_(['pending', 'running']),
        ).first()
        if in_flight:
            skipped += 1
            continue

        opt = ParamOptimization(
            strategy_id=s.id,
            status='pending',
            grid=grid,
            baseline_params=dict(s.params or {}),
            combos_total=min(grid_size(grid) + 1, max_combos + 1),
        )
        db.session.add(opt)
        db.session.commit()
        # 錯峰 — 每個策略間隔 120s，避免 OKX 429
        optimize_strategy_params.apply_async(args=[opt.id, max_combos], countdown=queued * 120)
        queued += 1

    return f'auto-optimize: 排了 {queued} 個（每 120s 間隔），跳過 {skipped} 個'


@celery_app.task
def daily_advisor_summary():
    """Phase 10.9: 每天 23:00 UTC 一條 Telegram 摘要 — 今日托管動了什麼、PnL、open positions"""
    import datetime
    from sqlalchemy import func
    from app.models import AuditLog, Trade, Position, Strategy
    from app.services.telegram_service import send as _tg

    today = datetime.datetime.utcnow().date()
    start = datetime.datetime.combine(today, datetime.time.min)

    auto_count = (
        AuditLog.query
        .filter(AuditLog.event_type == 'advisor_auto_apply')
        .filter(AuditLog.created_at >= start)
        .count()
    )
    auto_rows = (
        AuditLog.query
        .filter(AuditLog.event_type == 'advisor_auto_apply')
        .filter(AuditLog.created_at >= start)
        .order_by(AuditLog.id.desc())
        .limit(5)
        .all()
    )

    today_pnl = db.session.query(func.coalesce(func.sum(Trade.pnl), 0)).filter(Trade.exit_time >= start).scalar() or 0
    today_trades = db.session.query(func.count(Trade.id)).filter(Trade.exit_time >= start).scalar() or 0
    open_pos = db.session.query(func.count(Position.id)).filter(Position.status == 'open').scalar() or 0
    unrealized = db.session.query(func.coalesce(func.sum(Position.unrealized_pnl), 0)).filter(Position.status == 'open').scalar() or 0
    running = db.session.query(func.count(Strategy.id)).filter(Strategy.status == 'running').scalar() or 0

    halts_today = (
        AuditLog.query
        .filter(AuditLog.event_type.in_(['halt', 'kill_switch']))
        .filter(AuditLog.created_at >= start)
        .count()
    )

    lines = [
        f'📊 <b>日報 {today.isoformat()}</b>',
    ]
    # Phase 14k-22: 加目标进度 (admin user_id=1)
    try:
        from app.models import ProfitTarget
        t = ProfitTarget.query.filter_by(user_id=1, status='active').first()
        if t:
            cur = t.current_equity_usdt or t.start_capital_usdt
            gain = cur - t.start_capital_usdt
            expected = t.expected_equity_now()
            lag = expected - cur
            lag_sign = '✅ 领先' if lag <= 0 else f'🟡 落后 ${lag:.2f}'
            lines.append(
                f'🎯 <b>目标 +${t.target_equity() - t.start_capital_usdt:.2f}</b> '
                f'({t.target_pct}% / {t.days_elapsed() + t.days_remaining()} 天)'
            )
            lines.append(
                f'  当前 ${cur:.2f} (起 ${t.start_capital_usdt:.2f}, '
                f'+${gain:.2f}, 完成 {t.progress_pct()}%)'
            )
            lines.append(f'  应到 ${expected:.2f} · {lag_sign} · 余 {t.days_remaining()} 天')
            if t.dd_pct() > 0:
                lines.append(f'  📉 当前回撤 {t.dd_pct()}% (上限 {t.max_dd_pct}%)')
            lines.append('')
    except Exception:
        pass

    lines.extend([
        f'• 運行策略: {running} 個 / 持倉: {open_pos}',
        f'• 今日 PnL: <b>{today_pnl:+.2f}</b> USDT ({today_trades} 筆)',
        f'• 未實現: {unrealized:+.2f} USDT',
        f'• 智能托管執行: {auto_count} 次',
    ])
    if halts_today:
        lines.append(f'⚠️ 今日有 {halts_today} 次 halt / kill 事件')
    if auto_rows:
        lines.append('\n<b>AI 托管操作：</b>')
        action_names = {
            'apply_params': '调参',
            'pause': '暂停',
            'retire': '退役',
            'fan_out': '复制到新币',
            'promote_candidate': '上线新策略',
        }
        for r in auto_rows:
            ctx = r.context or {}
            act = ctx.get('action', '?')
            act_zh = action_names.get(act, act)
            msg = ctx.get('message', '') or ''
            # 去掉 params=... 之类 raw dict
            if 'params=' in msg:
                msg = msg.split('params=')[0].rstrip() or '已优化'
            lines.append(f"• {act_zh} 策略 #{ctx.get('strategy_id')}: {msg[:60]}")

    _tg('\n'.join(lines), force=True)
    return f'daily-summary sent: pnl={today_pnl:+.2f} auto={auto_count}'


# ===== Phase 12.4: 預熱 Dashboard 緩存（避免用戶等 24s 冷啟動）=====

@celery_app.task
def prewarm_dashboard_cache():
    """每 90s 跑 — 提前算好 advisor / regime / MTF / correlation，灌進 Redis 緩存。
    用戶開 Dashboard 直接拿緩存。"""
    from app.services.strategy_advisor import build_recommendations
    from app.services.strategy_correlation import build_correlation_matrix
    # build_recommendations 內部會用到 regime + MTF + correlation，這一個調用全暖
    try:
        recs = build_recommendations()
        # correlation 額外暖一下（如果 advisor 沒走過）
        build_correlation_matrix()
        return f'prewarm ok: {recs.get("summary", {}).get("total", 0)} items'
    except Exception as e:
        return f'prewarm error: {type(e).__name__}: {e}'


# ===== Phase 12.11: auto-revive retired strategies if market changed =====

REVIVE_MIN_DAYS_RETIRED = 7    # 退役 >= 7 天才考慮復活（給策略息一段時間）
REVIVE_MIN_OOS_SHARPE = 0.5    # 復活門檻 — OOS Sharpe > 0.5 才復活


@celery_app.task
def auto_revive_retired_strategies():
    """Phase 12.11: 每週掃描 retired 策略，行情變了重新試。

    對每個 status='retired' 且 retired_at < (now - 7 days) 的策略：
      1) 用最新 K 線重跑 walk-forward
      2) OOS Sharpe > REVIVE_MIN_OOS_SHARPE → 復活成 'stopped' + Telegram
      3) 不過 → 留 retired

    退役策略池會自然不斷重評估，避免供給枯竭。
    """
    import datetime as _dt
    from app.services.exchange_service import fetch_ohlcv_history
    from app.services.backtest_engine import run_walkforward_backtest
    from app.services.candidate_sandbox import load_signal_fn
    from app.models import StrategyCandidate
    from app.services.telegram_service import send as _tg
    from app.services.audit import log as audit

    cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=REVIVE_MIN_DAYS_RETIRED)
    candidates = Strategy.query.filter(
        Strategy.status == 'retired',
        Strategy.retired_at < cutoff,
    ).all()
    if not candidates:
        return 'auto-revive: 沒有符合的 retired 策略（需 >= 7 天）'

    revived = 0
    skipped = 0
    for s in candidates:
        try:
            candles = fetch_ohlcv_history(s.symbol, s.timeframe, total_limit=2000)
            if len(candles) < 200:
                skipped += 1
                continue

            signal_fn = None
            if s.candidate_id:
                c = StrategyCandidate.query.get(s.candidate_id)
                if c and c.parsed_signal and c.signal_fn_name:
                    try:
                        signal_fn = load_signal_fn(c.parsed_signal, c.signal_fn_name)
                    except Exception:
                        skipped += 1
                        continue

            wf = run_walkforward_backtest(
                s.type, s.params or {}, candles,
                timeframe=s.timeframe, signal_fn=signal_fn,
            )
            if wf.get('status') == 'error':
                skipped += 1
                continue

            oos = wf.get('out_sample') or {}
            oos_sh = oos.get('sharpe_ratio')

            if oos_sh is not None and oos_sh > REVIVE_MIN_OOS_SHARPE:
                s.status = 'stopped'   # 復活成 stopped，user 決定要不要啟動
                s.retired_at = None
                s.retire_reason = None
                s.retire_warning_count = 0   # 清零
                s.revive_count = (s.revive_count or 0) + 1
                db.session.commit()
                revived += 1
                _tg(
                    f'🌱 <b>策略自动复活</b>\n'
                    f'#{s.id} {s.name}\n'
                    f'交易对 {s.symbol} · {s.timeframe}\n'
                    f'最新回测 OOS Sharpe {oos_sh:.2f} (门槛 {REVIVE_MIN_OOS_SHARPE})\n'
                    f'已设为已停止状态, 请去策略表审视后手动启动'
                )
                audit('strategy_revive', actor='auto:weekly_revive',
                      strategy_id=s.id, name=s.name, oos_sharpe=oos_sh,
                      revive_count=s.revive_count)
            else:
                skipped += 1
        except Exception:
            skipped += 1

    return f'auto-revive: 復活 {revived} 個，跳過 {skipped} 個（OOS 未過或樣本不足）'


@celery_app.task
def cleanup_old_rejected_candidates(retention_days: int | None = None):
    """Phase 12.14: 每週清理 candidates 表的 rejected/error 行 + candidate-stage backtest_results。

    保留 retention_days 天（預設 90）內的；之前的刪除。
    保留：pending / translated / backtesting / qualified / promoted 所有狀態 — 只清 rejected + error。
    一併清 backtest_results.strategy_id IS NULL 且超期的（candidate-stage 結果，不屬任何 user 的 system resource）。

    回 dict {candidates_deleted, backtests_deleted, kept_status}。
    """
    import datetime as _dt
    import os
    from sqlalchemy import func
    from app.models import StrategyCandidate, BacktestResult
    from app.services.audit import log as audit

    days = int(retention_days or os.environ.get('CANDIDATE_CLEANUP_DAYS', '90'))
    cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=days)

    # 候選自身 (rejected / error)
    cand_q = StrategyCandidate.query.filter(
        StrategyCandidate.status.in_(['rejected', 'error']),
        StrategyCandidate.created_at < cutoff,
    )
    cand_to_delete = cand_q.count()

    # candidate-stage backtest (strategy_id IS NULL 且超期)
    bt_q = BacktestResult.query.filter(
        BacktestResult.strategy_id.is_(None),
        BacktestResult.created_at < cutoff,
    )
    bt_to_delete = bt_q.count()

    # 留一個 status 計數快照（給 audit context）
    status_counts = dict(
        db.session.query(StrategyCandidate.status, func.count(StrategyCandidate.id))
        .group_by(StrategyCandidate.status).all()
    )

    if cand_to_delete == 0 and bt_to_delete == 0:
        return f'cleanup: nothing to delete (retention={days}d, status snapshot={status_counts})'

    # 先刪 backtest（candidates 可能 FK→backtest_result_id）
    bt_q.delete(synchronize_session=False)
    cand_q.delete(synchronize_session=False)
    db.session.commit()

    audit('cleanup_candidates', actor='auto:weekly_cleanup',
          candidates_deleted=cand_to_delete,
          backtests_deleted=bt_to_delete,
          retention_days=days,
          status_snapshot=status_counts)

    return (f'cleanup: 刪 {cand_to_delete} candidates (rejected/error, > {days}d) '
            f'+ {bt_to_delete} candidate-stage backtests')


@celery_app.task
def auto_ai_improve_strategies():
    """Phase 12.40: 每日跑 v6 迭代式 AI 改進 — admin (user_id=1) 走 claude_cli 訂閱免費。

    v6 流程（vs v4/v5 fire-and-forget）:
      1. 拉 profitable references → LLM 学已能赚钱的 pattern
      2. 拉 symbol 实际数据 (RSI/BB/ADX 分布) → LLM 不再瞎猜频率
      3. LLM 写 → quick_backtest 立即自测 → 失败反喂 LLM 改 → 最多 3 轮
      4. 只 self-test 过的写入 strategy_candidates (status='qualified')

    僅 admin 跑：普通 user BYO API key 自動跑會燒 token；他們仍在 UI 手動觸發。
    """
    # Phase 14: 改用 catalog-first 推荐 (v8 invent 仅 full_auto 模式时调，留待 14d)
    from app.services.llm_prompts.strategy_recommend import recommend_strategies
    from app.services.audit import log as audit
    try:
        r = recommend_strategies(user_id=1, max_recommend=3)
    except Exception as e:
        audit('auto_ai_improve_error', actor='auto:daily_ai_improve_v8',
              error=f'{type(e).__name__}: {e}')
        return f'auto-ai-improve-v6 error: {type(e).__name__}: {e}'
    if not r.get('ok'):
        audit('auto_ai_improve_skipped', actor='auto:daily_recommend',
              reason=r.get('error'))
        return f'auto-recommend skipped: {r.get("error")}'

    recs = r.get('recommendations', [])
    auto_applied = [x for x in recs if (x.get('auto_apply') or {}).get('applied')]
    awaiting = [x for x in recs if not (x.get('auto_apply') or {}).get('applied')]
    mode = r.get('mode', 'manual')

    audit('auto_ai_improve_done', actor='auto:daily_recommend',
          recommended_count=len(recs),
          auto_applied_count=len(auto_applied),
          mode=mode)

    # Telegram report
    try:
        from app.services.telegram_service import send as _tg
        lines = []
        for x in recs[:3]:
            mark = '🚀' if (x.get('auto_apply') or {}).get('applied') else '👀'
            rp = x.get('recommended_risk') or {}
            # Phase 14k-18: 文案美化, 不显 raw catalog_type
            ctype_raw = x.get('catalog_type', '')
            pretty = ctype_raw.replace('cat_', '').replace('_', ' ').title()
            lev = rp.get('leverage')
            sh = x.get('verified_sharpe')
            lines.append(
                f'{mark} <b>{pretty}</b> · {x["symbol"]} {x["timeframe"]}'
                + (f' · Sharpe {sh}' if sh else '')
                + (f' · 杠杆 {lev}x' if lev else '')
            )
        mode_zh = {'manual': '手动', 'semi_auto': '半自动', 'full_auto': '全自动'}.get(mode, mode)
        if auto_applied:
            _tg(
                f'🤖 <b>AI 自动上线策略</b> ({mode_zh}模式)\n'
                f'已上架 {len(auto_applied)} 个 / 推荐 {len(recs)} 个\n\n'
                + '\n'.join(lines)
                + f'\n\n<a href="https://ai-quant.medias-ai.cloud/">面板查看</a>',
                event_key='ai_improve_daily',
            )
        elif awaiting:
            _tg(
                f'🤖 <b>AI 推荐 {len(awaiting)} 个策略待审核</b> ({mode_zh}模式)\n\n'
                + '\n'.join(lines)
                + f'\n\n<a href="https://ai-quant.medias-ai.cloud/">一键应用</a>',
                event_key='ai_improve_daily',
            )
    except Exception:
        pass

    return f'recommend ({mode}): {len(recs)} 个，auto-applied {len(auto_applied)}'


# ============================================================
# Phase 12.24.2: USDT 链上付款监听 (60s interval)
# ============================================================
@celery_app.task(name='app.tasks.strategy_tasks.check_onchain_payments')
def check_onchain_payments():
    """每 60s 跑：4 条 USDT 链上 polling，匹配 pending invoices 自动 confirm"""
    from app.services.onchain_monitor import check_all_chains
    from app.services.subscription_service import expire_old_invoices
    try:
        n_expired = expire_old_invoices()
    except Exception:
        n_expired = 0
    results = check_all_chains()
    total_confirmed = sum(r.get('confirmed', 0) for r in results if r.get('ok'))
    return {
        'expired': n_expired,
        'confirmed': total_confirmed,
        'chains': results,
    }


# ============================================================
# Phase 12.34: Daily Telegram 早报 (08:00 UTC 推昨日总结)
# ============================================================
@celery_app.task(name='app.tasks.strategy_tasks.daily_morning_report')
def daily_morning_report():
    """每天 08:00 UTC 推昨日运转总结 + 异常 highlight"""
    import datetime
    from app.models import StrategyCandidate, Strategy, Trade, BacktestResult, PaymentInvoice
    from app.extensions import db
    from app.services.telegram_service import send as tg_send
    from app.services.config_service import get_config

    now = datetime.datetime.utcnow()
    h24_ago = now - datetime.timedelta(hours=24)

    # 1) 候选池
    new_candidates = StrategyCandidate.query.filter(StrategyCandidate.created_at >= h24_ago).count()
    new_translated = StrategyCandidate.query.filter(
        StrategyCandidate.status == 'translated',
        StrategyCandidate.updated_at >= h24_ago,
    ).count()
    new_promoted = StrategyCandidate.query.filter(
        StrategyCandidate.status == 'promoted',
        StrategyCandidate.updated_at >= h24_ago,
    ).count()
    pending_now = StrategyCandidate.query.filter_by(status='pending').count()
    translated_now = StrategyCandidate.query.filter_by(status='translated').count()

    # 2) 策略 / 交易
    running = Strategy.query.filter_by(status='running').count()
    new_trades = Trade.query.filter(Trade.exit_time >= h24_ago).all()
    n_trades = len(new_trades)
    pnl_24h = sum((t.pnl or 0) for t in new_trades)
    n_wins = sum(1 for t in new_trades if (t.pnl or 0) > 0)

    # 3) 回测
    new_bt = BacktestResult.query.filter(BacktestResult.created_at >= h24_ago).count()

    # 4) 订阅
    new_invoices = PaymentInvoice.query.filter(PaymentInvoice.created_at >= h24_ago).count()
    confirmed = PaymentInvoice.query.filter(
        PaymentInvoice.confirmed_at >= h24_ago,
    ).count() if hasattr(PaymentInvoice, 'confirmed_at') else 0

    # 5) 异常 highlight
    issues = []
    if new_translated == 0 and pending_now > 0:
        issues.append(f'⚠️ 24h 内 0 translated 但有 {pending_now} pending（claude CLI 失败？）')
    if pending_now > 30:
        issues.append(f'⚠️ {pending_now} pending 堆积超 30')
    if running < 3:
        issues.append(f'⚠️ 仅 {running} 策略 running')
    cfg = get_config()
    if cfg.get('halted'):
        issues.append(f'🚨 system halted: {cfg.get("halt_reason", "?")}')

    msg_lines = [
        f'☀️ <b>Quant Pro 早报 · {now.strftime("%m-%d")}</b>',
        f'',
        f'<b>候选池 (24h)</b>',
        f'  新增 {new_candidates} · 翻译 {new_translated} · 上线 {new_promoted}',
        f'  存量 pending {pending_now} / translated {translated_now}',
        f'',
        f'<b>策略 / 交易 (24h)</b>',
        f'  Running {running} · trades {n_trades} ({n_wins}赢)',
        f'  PnL ${pnl_24h:+.2f}',
        f'',
        f'<b>回测 (24h)</b>',
        f'  完成 {new_bt} 次',
        f'',
        f'<b>订阅 (24h)</b>',
        f'  invoices {new_invoices} / confirmed {confirmed}',
    ]
    if issues:
        msg_lines.append('')
        msg_lines.append('<b>⚠️ 异常</b>')
        for x in issues:
            msg_lines.append(f'  {x}')
    else:
        msg_lines.append('')
        msg_lines.append('✅ 所有 cron / 业务正常')

    tg_send('\n'.join(msg_lines), parse_mode='HTML')
    return {'sent': True, 'issues': issues, 'pending': pending_now, 'running': running}


# ============================================================
# Phase 12.35: 内部 health monitor — 自己监控不依赖第三方
# 每 5 分钟跑，发现新 issue 立即 Telegram
# Redis 去重 — 同一 issue 30 分钟内不重复推
# ============================================================
@celery_app.task(name='app.tasks.strategy_tasks.internal_health_monitor')
def internal_health_monitor():
    """每 5 min 跑内部业务健康检查 + 异常 Telegram 告警"""
    import datetime
    import json
    from app.models import StrategyCandidate, Strategy
    from app.extensions import db, redis_client
    from app.services.telegram_service import send as tg_send
    from app.services.config_service import get_config

    now = datetime.datetime.utcnow()
    h48_ago = now - datetime.timedelta(hours=48)
    issues = []

    # 1) translate 48h 内是否有成功
    latest_translate = StrategyCandidate.query.filter(
        StrategyCandidate.status == 'translated',
        StrategyCandidate.updated_at >= h48_ago,
    ).order_by(StrategyCandidate.updated_at.desc()).first()
    if not latest_translate or (now - latest_translate.updated_at).total_seconds() > 18 * 3600:
        issues.append(('translate_stale', '48h 内无成功 translate（claude CLI 可能坏）'))

    # 2) pending 堆积
    pending = StrategyCandidate.query.filter_by(status='pending').count()
    if pending > 30:
        issues.append(('pending_pileup', f'{pending} pending 候选堆积 > 30'))

    # 3) running 策略数
    running = Strategy.query.filter_by(status='running').count()
    if running < 3:
        issues.append(('low_running', f'仅 {running} 策略 running（< 3）'))

    # 4) system halted
    cfg = get_config()
    if cfg.get('halted'):
        issues.append(('halted', f'system halted: {cfg.get("halt_reason", "?")}'))

    # 5) 链上 polling 是否 4 链都未配置
    import os
    chains_configured = sum(1 for k in ['USDT_TRC20_ADDRESS', 'USDT_ERC20_ADDRESS', 'USDT_BEP20_ADDRESS', 'USDT_SOL_ADDRESS'] if os.environ.get(k))
    if chains_configured == 0:
        issues.append(('chains_unconfigured', 'USDT 4 链地址全未配置（订阅付款无法识别）'))

    # 去重: Redis 存最近 30min 推送过的 issue key
    DEDUP_TTL = 30 * 60   # 30 min
    new_alerts = []
    for key, msg in issues:
        redis_key = f'health_alert:{key}'
        if not redis_client.get(redis_key):
            new_alerts.append((key, msg))
            redis_client.setex(redis_key, DEDUP_TTL, '1')

    if new_alerts:
        msg = '🚨 <b>系统异常</b>\n\n' + '\n'.join(f'• {m}' for _, m in new_alerts)
        msg += f'\n\n<i>{now.strftime("%Y-%m-%d %H:%M")} UTC · 自动监控</i>'
        try:
            tg_send(msg, parse_mode='HTML')
        except Exception as e:
            print(f'[health monitor] tg send failed: {e}')

    # 顺手记一份「最近恢复」— 之前 unhealthy 现在 healthy → 推恢复通知
    last_status_key = 'health_last_status'
    last_status = redis_client.get(last_status_key)
    last_status = last_status.decode() if isinstance(last_status, bytes) else last_status
    current_status = 'degraded' if issues else 'healthy'
    if last_status == 'degraded' and current_status == 'healthy':
        try:
            tg_send(f'✅ <b>系统已恢复正常</b>\n\n所有 cron / 业务运转正常\n<i>{now.strftime("%Y-%m-%d %H:%M")} UTC</i>', parse_mode='HTML')
        except Exception:
            pass
    redis_client.setex(last_status_key, 3600, current_status)

    return {
        'status': current_status,
        'total_issues': len(issues),
        'new_alerts': len(new_alerts),
        'checks': {
            'translate_stale': not latest_translate,
            'pending': pending,
            'running': running,
            'halted': bool(cfg.get('halted')),
            'chains_configured': chains_configured,
        },
    }


@celery_app.task(name='app.tasks.strategy_tasks.profit_progress_monitor')
def profit_progress_monitor():
    """Phase 14k-22 (核心): 每小时跑 AI 量化经理大脑.

    跟踪 active profit_targets:
    A) 更新 current_equity / peak_equity
    B) DD 检查: 当前 DD > max_dd_pct → halt all + 紧急 Telegram
    C) 进度对比: 实际 vs 目标曲线, 落后 >5% → Telegram 警告 (24h 去重)
    D) 资金扩展 trigger: equity 跨过 $100/$500/$2000 → AI 自动加策略
    E) 目标达成 → status='achieved' + 庆祝 Telegram
    F) deadline 过 → status='expired' + 复盘 Telegram
    """
    from app.models import ProfitTarget, User
    from app.services.telegram_service import send as tg_send
    from app.services.audit import log as audit
    import datetime as _dt

    now = _dt.datetime.utcnow()
    actions = []

    targets = ProfitTarget.query.filter_by(status='active').all()
    for t in targets:
        user = User.query.get(t.user_id)
        if not user:
            continue

        # A) 拉当前 equity
        try:
            from app.services.exchange_binding import bound_exchanges
            bound = bound_exchanges(t.user_id)
            total = 0.0
            if 'hyperliquid' in bound:
                from app.services.hyperliquid_creds import get_decrypted_for_user as _hc
                from app.services.hyperliquid_service import fetch_balance as _hb
                c = _hc(t.user_id)
                if c:
                    bal = _hb(creds=c)
                    total += bal['USDT']['total']
            if 'okx' in bound:
                from app.services.exchange_service import fetch_balance as _ob, _env_creds, _resolve_creds
                _ob_creds = _env_creds() if t.user_id == 1 else _resolve_creds(t.user_id)
                bal = _ob(creds=_ob_creds) if _ob_creds else {}
                for v in bal.values():
                    total += v.get('total', 0)
        except Exception as e:
            print(f'[profit_monitor] equity fetch fail uid={t.user_id}: {e}')
            continue

        t.current_equity_usdt = round(total, 4)
        if not t.peak_equity_usdt or total > t.peak_equity_usdt:
            t.peak_equity_usdt = round(total, 4)
        t.last_progress_check_at = now

        # B) DD 检查 — 触发 halt
        dd = t.dd_pct()
        if dd >= t.max_dd_pct:
            try:
                from app.services.config_service import update_config
                update_config({'halted': True, 'halt_reason': f'profit_target DD {dd:.1f}% >= {t.max_dd_pct}%'})
            except Exception:
                pass
            tg_send(
                f'🚨 <b>紧急: 触发回撤保护</b>\n'
                f'用户 {user.email}\n'
                f'当前 ${total:.2f} / 峰值 ${t.peak_equity_usdt:.2f}\n'
                f'回撤 {dd:.1f}% ≥ 上限 {t.max_dd_pct}%\n'
                f'已 HALT 全部新开仓. 请人工 review.',
                event_key=f'dd_halt_{t.id}',
            )
            audit('profit_target_dd_halt', actor='system',
                  user_id=t.user_id, target_id=t.id, dd_pct=dd,
                  current=total, peak=t.peak_equity_usdt)
            actions.append(f'DD halt user={user.email}')
            db.session.commit()
            continue

        # E) 目标达成
        if total >= t.target_equity():
            t.status = 'achieved'
            t.achieved_at = now
            tg_send(
                f'🎉 <b>目标达成!</b>\n'
                f'用户 {user.email}\n'
                f'起始 ${t.start_capital_usdt:.2f} → 现 ${total:.2f}\n'
                f'增益 ${total - t.start_capital_usdt:.2f} (+{(total/t.start_capital_usdt-1)*100:.1f}%)\n'
                f'用时 {t.days_elapsed()} 天 / 计划 {t.days_elapsed() + t.days_remaining()} 天',
                event_key=f'target_achieved_{t.id}',
            )
            audit('profit_target_achieved', actor='system',
                  user_id=t.user_id, target_id=t.id,
                  start=t.start_capital_usdt, end=total)
            actions.append(f'achieved user={user.email}')
            db.session.commit()
            continue

        # F) deadline 过期
        if t.deadline and now >= t.deadline:
            t.status = 'expired'
            t.expired_at = now
            actual_gain = total - t.start_capital_usdt
            target_gain = t.target_equity() - t.start_capital_usdt
            achieve_pct = (actual_gain / target_gain * 100) if target_gain else 0
            tg_send(
                f'⏰ <b>目标周期结束</b>\n'
                f'用户 {user.email}\n'
                f'起始 ${t.start_capital_usdt:.2f} → 现 ${total:.2f}\n'
                f'达成 {achieve_pct:.1f}% (目标 +{t.target_pct}% / 实际 +{(total/t.start_capital_usdt-1)*100:.1f}%)\n'
                f'去 Settings 设新目标, 或让 AI 复盘改策略',
                event_key=f'target_expired_{t.id}',
            )
            audit('profit_target_expired', actor='system',
                  user_id=t.user_id, target_id=t.id, achieve_pct=achieve_pct)
            actions.append(f'expired user={user.email}')
            db.session.commit()
            continue

        # C) 进度对比 — 落后警告 (24h 去重)
        expected = t.expected_equity_now()
        lag_pct = (expected - total) / expected * 100 if expected > 0 else 0
        ai_review_cooldown_h = 6      # AI review 全局 cooldown (避免与 daily AI improve 重复)
        recently_reviewed = (
            t.last_ai_review_at
            and (now - t.last_ai_review_at).total_seconds() < ai_review_cooldown_h * 3600
        )
        if lag_pct > 5:
            recently_warned = (
                t.last_lag_warned_at
                and (now - t.last_lag_warned_at).total_seconds() < 24 * 3600
            )
            if not recently_warned:
                progress = t.progress_pct()
                tg_send(
                    f'🟡 <b>目标进度落后</b>\n'
                    f'用户 {user.email}\n'
                    f'当前 ${total:.2f} · 应到 ${expected:.2f} · 落后 {lag_pct:.1f}%\n'
                    f'已用 {t.days_elapsed()}/{t.days_elapsed() + t.days_remaining()} 天, 完成 {progress}%\n'
                    + ('AI 将于 24h 内主动 review 策略' if not recently_reviewed else 'AI 最近已 review (cooldown 中)'),
                    event_key=f'target_lag_{t.id}_{now.strftime("%Y%m%d")}',
                )
                t.last_lag_warned_at = now
                # 主动触发 AI improve, 但走 cooldown 防与 daily 重复
                if not recently_reviewed:
                    try:
                        from app.services.llm_prompts.strategy_recommend import recommend_strategies
                        recommend_strategies(t.user_id)
                        t.last_ai_review_at = now
                        actions.append(f'lag→ai_review user={user.email}')
                    except Exception:
                        pass

        # D) 资金扩展 trigger — 真 cooldown 防反复触发
        thresholds = [100, 500, 2000]
        crossed = next((th for th in thresholds
                          if t.start_capital_usdt < th <= total
                          and (t.last_tier_value or 0) < th), None)
        if crossed:
            try:
                from app.services.llm_prompts.strategy_recommend import recommend_strategies
                if not recently_reviewed:
                    recommend_strategies(t.user_id)
                    t.last_ai_review_at = now
                t.last_tier_triggered_at = now
                t.last_tier_value = crossed
                tg_send(
                    f'📈 <b>资金跨档</b> ${crossed}\n'
                    f'用户 {user.email}\n'
                    f'AI 自动扩展策略数 (现 ${total:.2f})',
                    event_key=f'capital_tier_{t.id}_{crossed}',
                )
                actions.append(f'tier {crossed} triggered user={user.email}')
            except Exception:
                pass

        db.session.commit()

    return f'profit_monitor: {len(targets)} targets, actions: {actions}'


@celery_app.task(name='app.tasks.strategy_tasks.weekly_strategy_review')
def weekly_strategy_review():
    """Phase 14k-22 (B): 每周日 23:00 UTC 跑.
    - 7 日 Sharpe<0 且亏损>$5 的 running 策略 → pause
    - 30 天无 trade 策略 → retire (信号死循环)
    - 触发 AI improve 补新策略
    """
    from app.models import Strategy, Trade
    from app.services.telegram_service import send as tg_send
    from app.services.audit import log as audit
    from sqlalchemy import func
    import datetime as _dt
    import statistics

    now = _dt.datetime.utcnow()
    week_ago = now - _dt.timedelta(days=7)
    month_ago = now - _dt.timedelta(days=30)

    running = Strategy.query.filter_by(status='running').all()
    paused = []
    retired = []
    for s in running:
        # 7 日 trades
        week_trades = (Trade.query.filter(Trade.strategy_id == s.id,
                                            Trade.exit_time > week_ago)
                       .all())
        # 30 天 trades
        month_count = (Trade.query.filter(Trade.strategy_id == s.id,
                                            Trade.exit_time > month_ago)
                       .count())

        # 死循环 — 30 天 0 trade (上线 > 30 天的策略)
        days_old = (now - s.created_at).total_seconds() / 86400 if s.created_at else 0
        if month_count == 0 and days_old > 30:
            s.status = 'retired'
            s.retired_at = now
            s.retire_reason = 'weekly_review: 30 天 0 trade (signal_dead)'
            retired.append(s)
            audit('weekly_review_retire', actor='system',
                  strategy_id=s.id, reason='signal_dead_30d')
            continue

        # 7 日 Sharpe<0 + 亏>$5
        if len(week_trades) >= 3:
            pnls = [float(t.pnl or 0) for t in week_trades]
            net = sum(pnls)
            mean = statistics.mean(pnls) if pnls else 0
            stdev = statistics.stdev(pnls) if len(pnls) > 1 else 1
            sharpe = mean / stdev if stdev > 0 else 0
            if sharpe < 0 and net < -5:
                s.status = 'stopped'
                paused.append((s, sharpe, net))
                audit('weekly_review_pause', actor='system',
                      strategy_id=s.id, sharpe_7d=round(sharpe, 2), net_pnl=round(net, 2))

    db.session.commit()

    # 触发 AI improve 补
    refilled = 0
    if paused or retired:
        try:
            from app.services.llm_prompts.strategy_recommend import recommend_strategies
            r = recommend_strategies(1)    # admin 视角
            refilled = sum(1 for x in r.get('recommendations', []) if (x.get('auto_apply') or {}).get('applied'))
        except Exception as e:
            print(f'[weekly_review] AI refill failed: {e}')

    # Telegram 周报
    msg_lines = [f'📊 <b>AI 周度策略复盘</b>', '']
    if paused:
        msg_lines.append(f'<b>暂停 {len(paused)} 个亏损策略</b>:')
        for s, sh, net in paused[:5]:
            msg_lines.append(f'  • #{s.id} {s.name[:30]} Sharpe {sh:.2f} 亏 ${net:.2f}')
    if retired:
        msg_lines.append(f'<b>退役 {len(retired)} 个信号死循环</b>:')
        for s in retired[:5]:
            msg_lines.append(f'  • #{s.id} {s.name[:30]} (30 天无交易)')
    if refilled:
        msg_lines.append(f'<b>AI 自动补充 {refilled} 个新策略</b>')
    if not paused and not retired:
        msg_lines.append('本周所有策略表现 OK, 无操作.')

    tg_send('\n'.join(msg_lines), event_key='weekly_review')
    return f'review: paused={len(paused)}, retired={len(retired)}, refilled={refilled}'


@celery_app.task(name='app.tasks.strategy_tasks.retry_stuck_ai_recommendations')
def retry_stuck_ai_recommendations():
    """Phase 14k-20/26: 重试卡在 panel 的 AI 推荐 qualified clones.

    场景: _maybe_auto_apply 推荐时被 cap/concentration 挡, 之后条件改变 (cap 提升 /
    老策略停) → clones 永远不会重新检查, 卡死在 panel.
    解决: 每 5 min iterate panel 上的 qualified clone 重跑 _maybe_auto_apply.

    14k-26: 超过 24h 还 concentration 卡住的 clone → 自动 dismiss (避免永远 panel 堆积)
    """
    from app.models import StrategyCandidate
    from app.services.config_service import get_config
    from app.services.llm_prompts.strategy_recommend import _maybe_auto_apply
    from app.extensions import db as _db
    import datetime as _dt

    cfg = get_config()
    mode = cfg.get('ai_decision_mode', 'manual')
    if mode == 'manual':
        return 'mode=manual, no retry'

    stuck = StrategyCandidate.query.filter(
        StrategyCandidate.source == 'catalog_clone',
        StrategyCandidate.status == 'qualified',
        StrategyCandidate.promoted_strategy_id.is_(None),
    ).order_by(StrategyCandidate.created_at.desc()).limit(20).all()

    if not stuck:
        return 'no stuck clones'

    now = _dt.datetime.utcnow()
    promoted = 0
    still_blocked = 0
    auto_dismissed = 0
    for c in stuck:
        # 14k-26: > 24h 仍卡 concentration 的 clone → 自动 dismiss
        age_hours = (now - c.created_at).total_seconds() / 3600 if c.created_at else 0
        sm_now = c.source_meta or {}
        old_reason = sm_now.get('auto_skip_reason', '') or ''
        if age_hours > 24 and '已 running 同' in old_reason:
            c.status = 'dismissed'
            c.error_log = f'auto-dismiss after 24h concentration: {old_reason[:100]}'
            _db.session.commit()
            auto_dismissed += 1
            continue

        # 默认 user_id=1 (admin); per-user 推荐继承 source_meta.user_id
        user_id = sm_now.get('cloned_for_user') or 1
        try:
            res = _maybe_auto_apply(c, user_id, mode, cfg)
        except Exception as e:
            print(f'[retry_stuck] clone #{c.id} 异常: {e}')
            continue
        if res and res.get('applied'):
            promoted += 1
            sm = dict(c.source_meta or {})
            sm.pop('auto_skip_reason', None)
            c.source_meta = sm
            _db.session.commit()
        elif res and res.get('skipped'):
            sm = dict(c.source_meta or {})
            sm['auto_skip_reason'] = res.get('reason', '')
            c.source_meta = sm
            _db.session.commit()
            still_blocked += 1

    return f'retry: promoted={promoted}, still_blocked={still_blocked}, auto_dismissed={auto_dismissed}, total={len(stuck)}'


@celery_app.task(name='app.tasks.strategy_tasks.check_hl_agent_expiry')
def check_hl_agent_expiry():
    """Phase 14k-6: 每天 09:00 UTC 检查所有 HL agent 过期状态.

    - <=14 天到期 + 未近期警告 → Telegram + 标记 expiry_warned_at
    - <=0 天 (已过期) → 强制 is_active=false, 永远转 paper, Telegram 通知一次
    """
    from app.models import HyperliquidCredentials, User
    from app.services.telegram_service import send as tg_send
    import datetime as _dt

    now = _dt.datetime.utcnow()
    warn_threshold_days = 14
    rewarn_after_hours = 24    # 同 user 24h 内不重复 warn

    all_creds = HyperliquidCredentials.query.filter(
        HyperliquidCredentials.agent_expires_at.isnot(None),
    ).all()

    warned = 0
    expired = 0
    for rec in all_creds:
        days = (rec.agent_expires_at - now).total_seconds() / 86400

        # 1. 已过期 → 自动 disable + Telegram (一次)
        if days <= 0 and rec.is_active:
            rec.is_active = False
            rec.last_error = f'agent 过期于 {rec.agent_expires_at.isoformat()}, 自动转 paper'
            try:
                user = User.query.get(rec.user_id)
                email = user.email if user else f'user#{rec.user_id}'
                tg_send(
                    f'🔴 <b>HL agent 已过期</b>\n'
                    f'user: {email}\n'
                    f'过期时间: {rec.agent_expires_at.strftime("%Y-%m-%d %H:%M UTC")}\n'
                    f'所有 LIVE 策略已转 paper. 去 Settings 重新绑定.',
                    event_key=f'hl_expired_{rec.user_id}',
                )
            except Exception as e:
                print(f'[hl_expiry] tg send failed for user {rec.user_id}: {e}')
            db.session.commit()
            expired += 1
            continue

        # 2. <=14 天 → warn (per-user 24h 去重)
        if 0 < days <= warn_threshold_days:
            already_warned_recently = (
                rec.expiry_warned_at
                and (now - rec.expiry_warned_at).total_seconds() < rewarn_after_hours * 3600
            )
            if already_warned_recently:
                continue
            try:
                user = User.query.get(rec.user_id)
                email = user.email if user else f'user#{rec.user_id}'
                tg_send(
                    f'🟡 <b>HL agent 即将过期</b>\n'
                    f'user: {email}\n'
                    f'剩余: {int(days)} 天\n'
                    f'过期时间: {rec.agent_expires_at.strftime("%Y-%m-%d %H:%M UTC")}\n'
                    f'到期后自动转 paper. 提前去 hyperliquid.xyz/API 重新派生 agent + Settings 更新.',
                    event_key=f'hl_expiring_{rec.user_id}_{int(days)}',
                )
            except Exception as e:
                print(f'[hl_expiry] tg warn failed for user {rec.user_id}: {e}')
            rec.expiry_warned_at = now
            db.session.commit()
            warned += 1

    return {'warned': warned, 'expired': expired, 'checked': len(all_creds)}


# ===== Phase 14k-29 L4: AI risk 闪测 (SL/TP grid walk-forward) =====

@celery_app.task(bind=True, name='app.tasks.strategy_tasks.optimize_risk_and_apply',
                 max_retries=3, default_retry_delay=300)
def optimize_risk_and_apply(self, strategy_id: int):
    """AI risk 闪测: 跑 SL/TP grid walk-forward → 过门槛自动 merge 进 strategy.params.risk_params.

    Phase 14k-31: 加 retry, OKX 429 / 网络错误 → 5min 后重试 3 次.
    """
    from app.models import Strategy
    from app.services.risk_optimizer import optimize_risk_params, should_apply
    from app.services.audit import log as audit
    from app.services.telegram_service import send as _tg
    import random

    s = Strategy.query.get(strategy_id)
    if not s:
        return f'strategy {strategy_id} 不存在'
    if s.status != 'running':
        return f'strategy {strategy_id} status={s.status}, skip'

    try:
        r = optimize_risk_params(s)
    except Exception as e:
        es = str(e)
        if 'Too Many Requests' in es or '429' in es or 'timeout' in es.lower():
            # 14k-31: API rate limit → retry 5-7min 后
            audit('risk_opt_retry', strategy_id=strategy_id, error=es[:200], attempt=self.request.retries + 1)
            try:
                raise self.retry(exc=e, countdown=300 + random.randint(0, 120))
            except self.MaxRetriesExceededError:
                audit('risk_opt_error', strategy_id=strategy_id, error=f'max retries: {es[:200]}')
                return f'max retries exceeded: {es[:100]}'
        # 其他 exception 不 retry, audit + return
        audit('risk_opt_error', strategy_id=strategy_id, error=es[:300])
        return f'risk opt exception: {es[:100]}'

    if 'error' in r:
        audit('risk_opt_error', strategy_id=strategy_id, error=r['error'])
        return f'risk opt error: {r["error"]}'

    ok, msg = should_apply(r)
    base = r['baseline']
    best = r.get('best')

    if not ok:
        audit('risk_opt_no_lift', strategy_id=strategy_id,
              baseline=base, best=best, reason=msg)
        return f'no lift: {msg}'

    # Apply: merge 进 strategy.params.risk_params
    from sqlalchemy.orm.attributes import flag_modified
    before_params = dict(s.params or {})
    params = dict(s.params or {})
    rp = dict(params.get('risk_params') or {})
    old_sl, old_tp = rp.get('sl_pct'), rp.get('tp_pct')
    rp['sl_pct'] = best['sl_pct']
    rp['tp_pct'] = best['tp_pct']
    # alias 兼容 — v8 路径用 stop_loss_pct/take_profit_pct, 同步更新
    if 'stop_loss_pct' in rp:
        rp['stop_loss_pct'] = best['sl_pct']
    if 'take_profit_pct' in rp:
        rp['take_profit_pct'] = best['tp_pct']
    params['risk_params'] = rp
    s.params = params
    flag_modified(s, 'params')
    db.session.commit()

    audit('risk_opt_applied', strategy_id=strategy_id,
          baseline=base, best=best,
          old_sl=old_sl, old_tp=old_tp,
          new_sl=best['sl_pct'], new_tp=best['tp_pct'])
    # 14k-30: 统一 ai_strategy_params_change 让 auto_revert 单一查询
    audit('ai_strategy_params_change', strategy_id=strategy_id, action='risk_opt_applied',
          before_params=before_params, after_params=params,
          changed_keys=['sl_pct', 'tp_pct'])

    try:
        _tg(
            f'🤖 <b>AI risk 闪测 apply</b>\n'
            f'#{strategy_id} {s.name}\n'
            f'SL: {old_sl} → {best["sl_pct"]}%\n'
            f'TP: {old_tp} → {best["tp_pct"]}%\n'
            f'OOS Sharpe: {base.get("oos_sharpe") or 0:.2f} → {best.get("oos_sharpe") or 0:.2f}\n'
            f'OOS DD: {base.get("oos_dd") or 0:.1f}% → {best.get("oos_dd") or 0:.1f}%'
        )
    except Exception:
        pass
    return f'applied SL={best["sl_pct"]} TP={best["tp_pct"]}, lift={best["score"]-base["score"]:.2f}'


# ===== Phase 14k-29 L6: advisor 主动 invent 新策略 =====

@celery_app.task(name='app.tasks.strategy_tasks.advisor_invent_strategy')
def advisor_invent_strategy(user_id: int = 1):
    """advisor 触发的新策略 invent — 走现有 recommend_strategies (catalog-first) 路径.
    full_auto 模式下会自动 promote + start (走现有 _maybe_auto_apply 链路).
    """
    from app.services.llm_prompts.strategy_recommend import recommend_strategies
    from app.services.audit import log as audit
    from app.services.telegram_service import send as _tg

    try:
        r = recommend_strategies(user_id, max_recommend=2)
    except Exception as e:
        audit('advisor_invent_error', user_id=user_id, error=f'{type(e).__name__}: {e}')
        return f'invent error: {e}'

    if not r.get('ok'):
        audit('advisor_invent_error', user_id=user_id, error=str(r)[:300])
        return f'invent fail: {r}'

    n = r.get('total_recommendations') or len(r.get('recommendations') or [])
    audit('advisor_invent_applied', user_id=user_id, total=n,
          mode=r.get('mode'))
    try:
        if n > 0:
            _tg(f'🤖 <b>AI 主动创新策略</b>\n'
                f'目标落后触发, 新增 {n} 个候选 (mode={r.get("mode")}).\n'
                f'回测过门槛会自动上线.')
    except Exception:
        pass
    return f'invented {n} candidates'


# ===== Phase 14k-30 #1: AI 改动 auto-revert =====

@celery_app.task(name='app.tasks.strategy_tasks.auto_revert_ai_changes')
def auto_revert_ai_changes():
    """每 6h 跑: 看最近 24-48h AI 改动的 strategy, 退化就还原 params.

    退化判定 (任一满足即视为退化):
      - 改后窗口实盘 trades = 0 (策略停止开单, lev 太大/太小)
      - 改后 PnL < 改前 PnL × 0.5 (且改前 PnL 非零正值)
      - 改后 win_rate 比改前低 ≥ 20 个百分点 (且各窗口 trades ≥ 5)
    """
    import datetime as _dt
    from app.models import AuditLog, Strategy, Trade
    from app.services.audit import log as audit
    from app.services.telegram_service import send as _tg
    from sqlalchemy.orm.attributes import flag_modified

    now = _dt.datetime.utcnow()
    cutoff_lo = now - _dt.timedelta(hours=48)
    cutoff_hi = now - _dt.timedelta(hours=24)

    # 找 24-48h 内的 AI 改动 (留 24h 给改后表现累积)
    changes = AuditLog.query.filter(
        AuditLog.event_type == 'ai_strategy_params_change',
        AuditLog.created_at >= cutoff_lo,
        AuditLog.created_at < cutoff_hi,
    ).order_by(AuditLog.created_at.asc()).all()

    if not changes:
        return 'no AI changes in 24-48h window'

    reverted = 0
    skipped = 0
    for c in changes:
        ctx = c.context or {}
        sid = ctx.get('strategy_id')
        before = ctx.get('before_params')
        if not sid or not before:
            skipped += 1
            continue
        s = Strategy.query.get(sid)
        if not s or s.status != 'running':
            skipped += 1
            continue

        # 跳过已经 revert 过的 (避免反复来回)
        already_reverted = AuditLog.query.filter(
            AuditLog.event_type == 'ai_change_reverted',
            AuditLog.created_at > c.created_at,
        ).all()
        if any((a.context or {}).get('original_audit_id') == c.id for a in already_reverted):
            continue

        # 窗口: change 时点前 24h vs change 后 24h
        before_start = c.created_at - _dt.timedelta(hours=24)
        before_end = c.created_at
        after_start = c.created_at
        after_end = c.created_at + _dt.timedelta(hours=24)

        before_trades = Trade.query.filter(
            Trade.strategy_id == sid,
            Trade.exit_time >= before_start,
            Trade.exit_time < before_end,
        ).all()
        after_trades = Trade.query.filter(
            Trade.strategy_id == sid,
            Trade.exit_time >= after_start,
            Trade.exit_time < after_end,
        ).all()

        before_pnl = sum(t.pnl or 0 for t in before_trades)
        after_pnl = sum(t.pnl or 0 for t in after_trades)
        before_wins = sum(1 for t in before_trades if (t.pnl or 0) > 0)
        after_wins = sum(1 for t in after_trades if (t.pnl or 0) > 0)
        before_wr = (before_wins / len(before_trades) * 100) if before_trades else None
        after_wr = (after_wins / len(after_trades) * 100) if after_trades else None

        degraded = False
        reason = []

        # check 1: 改后 24h 0 trades, 但改前有 trades (策略被卡住了)
        if not after_trades and before_trades:
            degraded = True
            reason.append(f'改后 24h 无开单 (改前 {len(before_trades)} 笔)')
        # check 2: PnL 显著下滑 (改前正盈利且改后亏 50%+)
        elif before_pnl > 0 and after_pnl < before_pnl * 0.5:
            degraded = True
            reason.append(f'PnL 退化 ${before_pnl:.2f} → ${after_pnl:.2f}')
        # check 3: win_rate 显著下滑
        elif (before_wr is not None and after_wr is not None
              and len(before_trades) >= 5 and len(after_trades) >= 5
              and before_wr - after_wr >= 20):
            degraded = True
            reason.append(f'胜率下滑 {before_wr:.0f}% → {after_wr:.0f}%')

        if not degraded:
            skipped += 1
            continue

        # 还原
        s.params = before
        flag_modified(s, 'params')
        db.session.commit()

        audit('ai_change_reverted', strategy_id=sid, original_audit_id=c.id,
              original_action=ctx.get('action'),
              before_pnl=before_pnl, after_pnl=after_pnl,
              before_trades=len(before_trades), after_trades=len(after_trades),
              reason='; '.join(reason),
              restored_params=before)
        try:
            _tg(f'⏪ <b>AI 改动 auto-revert</b>\n'
                f'#{sid} {s.name}\n'
                f'原动作: {ctx.get("action")}\n'
                f'退化原因: {"; ".join(reason)}\n'
                f'已还原到改前 params')
        except Exception:
            pass
        reverted += 1

    return f'reviewed {len(changes)} changes: reverted {reverted}, skipped {skipped}'
