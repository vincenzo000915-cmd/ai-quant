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
                 pos_side: str | None = None):
    """Phase 6.5: 模式分派 — paper → 模擬，live → OKX swap 真實下單。
    失敗時 fallback 寫 telegram，return None。

    pos_side: 'long' | 'short' — 平倉時 caller 必須顯式傳；開倉若不傳會由 side 推。
    """
    if mode == 'live':
        try:
            from app.services.exchange_service import place_order_live
            res = place_order_live(symbol, side, amount_usdt, leverage=leverage, pos_side=pos_side)
            return {
                'id': res['okx'].get('ordId', 'live_unknown'),
                'symbol': symbol, 'side': side, 'type': 'market',
                'amount': res['contracts'] * 0.01,   # contract size
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
    trade_size = cfg['trade_size_usdt']
    lev = cfg['leverage']
    sl_pct = cfg['stop_loss_pct']
    tp_pct = cfg['take_profit_pct']
    halted = cfg.get('halted', False)
    mode = cfg.get('trading_mode', 'paper')

    results = []
    for s in strategies:
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

                # Phase 9.3: 動態倉位（依 sizing_mode）
                from app.services.position_sizing import compute_size
                effective_size, sizing_debug = compute_size(s, cfg, trade_size)
                amount_base = round(effective_size / price, 6)
                notional = amount_base * price * lev

                order = _place_order(s.symbol, okx_side, effective_size, price, mode, leverage=lev, pos_side=side)
                if order is None:
                    results.append(f'⛔ {s.name}: 下單失敗（live mode），略過')
                    continue

                # Phase 9.4: 開倉時計算絕對 SL/TP（ATR mode）
                from app.services.risk_levels import compute_sl_tp
                sl_price, tp_price, sl_dbg = compute_sl_tp(
                    symbol=s.symbol, timeframe=s.timeframe, side=side,
                    entry_price=price, cfg=cfg,
                )

                # Phase 12.7+12.8: Position.size 統一為「實際 base amount」（含槓桿）
                # 這樣 PnL = size × delta_price 直接得真實 USDT，不用再 × lev
                intended_base = (effective_size * lev) / price
                intended_notional = intended_base * price
                real_size = intended_base
                if mode == 'live':
                    from app.services.symbols import get_contract_size
                    contract_size = get_contract_size(s.symbol)
                    contracts_target = max(1, round(intended_base / contract_size))
                    real_size = contracts_target * contract_size
                    real_notional = real_size * price
                    # Phase 12.8: 合約最小張數取整可能讓實際 > 目標 N 倍。
                    # 超出 50% 就跳過（避免 ETH $120 目標變 $210 實際持倉）。
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

                pos = Position(
                    strategy_id=s.id,
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

                order = _place_order(s.symbol, okx_side, position.size * price, price, mode, leverage=lev, pos_side=position.side)

                trade = Trade(
                    position_id=position.id,
                    strategy_id=s.id,
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
    """更新持倉當前價格和浮動盈虧（含槓桿）— long/short 都正確"""
    lev = _cfg()['leverage']
    positions = Position.query.filter_by(status='open').all()
    for pos in positions:
        try:
            ticker = get_ticker(pos.symbol)
            current = ticker['price']
            pos.current_price = current
            _, raw_pct = _pnl_pct_for(pos, current, lev)
            # Phase 12.8: size 已含 lev，PnL 不再 × lev
            pos.unrealized_pnl = raw_pct * pos.size * pos.entry_price / 100
        except Exception as e:
            print(f'[update] 持倉 {pos.id} 更新失敗: {e}')
    db.session.commit()
    return f'已更新 {len(positions)} 個持倉'


@celery_app.task
def check_stop_loss():
    """檢查止損止盈（含槓桿）— long/short + flat_pct/atr 都觸發"""
    cfg = _cfg()
    lev = cfg['leverage']
    sl_pct = cfg['stop_loss_pct']
    tp_pct = cfg['take_profit_pct']
    mode = cfg.get('trading_mode', 'paper')

    positions = Position.query.filter_by(status='open').all()
    triggered = []
    for pos in positions:
        try:
            ticker = get_ticker(pos.symbol)
            current = ticker['price']
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
                order = _place_order(pos.symbol, close_side, pos.size * current, current, mode, leverage=lev, pos_side=pos.side)
                pnl = raw_pct * pos.size * pos.entry_price / 100   # Phase 12.8: size 已含 lev
                trade = Trade(
                    position_id=pos.id,
                    strategy_id=pos.strategy_id,
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
                order = _place_order(pos.symbol, close_side, pos.size * current, current, mode, leverage=lev, pos_side=pos.side)
                pnl = raw_pct * pos.size * pos.entry_price / 100   # Phase 12.8: size 已含 lev
                trade = Trade(
                    position_id=pos.id,
                    strategy_id=pos.strategy_id,
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

# 退役門檻（從 candidate_pipeline 借同一套）
RETIRE_SHARPE_FULL = 0.3       # 全段 Sharpe 跌破這個 → 退役
RETIRE_SHARPE_OOS = 0.0        # OOS Sharpe 跌破 0 → 真的不行了
RETIRE_MIN_TRADES = 8          # 樣本不足就不退役（避免短期噪音誤判）


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
    for s in running:
        try:
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

            if retire_reasons:
                s.status = 'retired'
                s.retired_at = datetime.utcnow()
                reason_txt = '; '.join(retire_reasons)
                s.retire_reason = f'auto-retire @ {datetime.utcnow().isoformat(timespec="seconds")}: ' + reason_txt
                actions.append(f'🔴 {s.name} retired: {", ".join(retire_reasons)}')
                from app.services.telegram_service import notify_retire
                from app.services.audit import log as audit
                notify_retire(s.name, reason_txt)
                audit('strategy_retire', actor='auto:health_check', strategy_id=s.id,
                      name=s.name, reasons=retire_reasons)
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
        out = optimize(strategy, max_combos=max_combos, on_progress=_progress)
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

    msg_head = f'兄弟回測 #{strategy.id} {strategy.name} ({strategy.symbol} {strategy.timeframe})'
    if oos is None:
        _tg(f'🟡 {msg_head}：OOS Sharpe 無法計算（樣本太少），保持 stopped')
        return 'oos None, kept stopped'

    if oos >= min_sharpe:
        if auto_start:
            strategy.status = 'running'
            db.session.commit()
            _tg(f'🟢 {msg_head}：OOS Sharpe={oos:.2f} (IS={is_sh}) ≥ {min_sharpe} → 已自動啟動')
            return f'started, oos={oos:.2f}'
        _tg(f'🟢 {msg_head}：OOS Sharpe={oos:.2f} 通過，但 fan_out_auto_start=off，請手動啟動')
        return f'passed but auto_start off, oos={oos:.2f}'
    _tg(f'🔴 {msg_head}：OOS Sharpe={oos:.2f} < {min_sharpe} → 未啟動（行情不適合）')
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
        f'• 運行策略: {running} 個 / 持倉: {open_pos}',
        f'• 今日 PnL: <b>{today_pnl:+.2f}</b> USDT ({today_trades} 筆)',
        f'• 未實現: {unrealized:+.2f} USDT',
        f'• 智能托管執行: {auto_count} 次',
    ]
    if halts_today:
        lines.append(f'⚠️ 今日有 {halts_today} 次 halt / kill 事件')
    if auto_rows:
        lines.append('\n<b>今日托管動作：</b>')
        for r in auto_rows:
            ctx = r.context or {}
            lines.append(f"• {ctx.get('action')} #{ctx.get('strategy_id')}: {ctx.get('message', '')[:60]}")

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
