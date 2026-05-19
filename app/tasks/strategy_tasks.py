"""Celery 定時任務 — 模擬盤模式（不下真單）"""
import random
import time
from datetime import datetime
from app.extensions import celery_app, db
from app.models import Strategy, Position, Trade, Order, Candle
from app.services.exchange_service import get_ticker
from app.services.strategy_engine import get_signal, get_candle_df

# ===== 模擬盤設定 =====
SIMULATED_BALANCE = 100.0       # 模擬本金 $100
LEVERAGE = 15                   # 15x 槓桿
TRADE_SIZE_USDT = 10.0          # 每次下單 $10（$100 本金切 10 份，15x 槓桿 = $150 名義倉位/筆）
STOP_LOSS_PCT = 5.0             # 5% 止損
TAKE_PROFIT_PCT = 8.0           # 8% 止盈


def _simulated_order(symbol, side, amount_usdt, price):
    """模擬下單（不發送到交易所）"""
    return {
        'id': f'sim_{int(time.time()*1000)}_{random.randint(1000,9999)}',
        'symbol': symbol,
        'side': side,
        'type': 'market',
        'amount': amount_usdt / price,  # 換算為BTC數量
        'price': price,
        'cost': amount_usdt,
        'fee': {'cost': amount_usdt * 0.001, 'currency': 'USDT'},  # 0.1% 手續費
        'status': 'closed',
        'simulated': True,
    }


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

            if signal in ('buy', 'long') and position:
                results.append(f'{s.name}: 已有持倉，跳過信號')
                continue

            if signal in ('sell', 'close') and not position:
                results.append(f'{s.name}: 無持倉，跳過信號')
                continue

            # 獲取當前價格
            ticker = get_ticker(s.symbol)
            price = ticker['price']

            if signal in ('buy', 'long'):
                # 計算倉位：$50 USDT / price = BTC數量
                amount_btc = TRADE_SIZE_USDT / price
                amount_btc = round(amount_btc, 6)
                
                # 名義倉位價值
                notional = amount_btc * price * LEVERAGE

                order = _simulated_order(s.symbol, 'buy', TRADE_SIZE_USDT, price)
                
                pos = Position(
                    strategy_id=s.id,
                    symbol=s.symbol,
                    side='long',
                    size=amount_btc,
                    entry_price=price,
                    current_price=price,
                    status='open',
                )
                db.session.add(pos)
                db.session.commit()
                results.append(
                    f'✅ {s.name}: 模擬買入 {amount_btc} BTC @ ${price:.1f} '
                    f'(本金${TRADE_SIZE_USDT:.0f}, 槓桿{LEVERAGE}x, '
                    f'名義${notional:.0f})'
                )

            elif signal in ('sell', 'close') and position:
                # 計算PnL
                pnl_raw = (price - position.entry_price) * position.size
                pnl_leveraged = pnl_raw * LEVERAGE
                pnl_pct = ((price - position.entry_price) / position.entry_price) * 100 * LEVERAGE

                order = _simulated_order(s.symbol, 'sell', position.size * price, price)
                
                trade = Trade(
                    position_id=position.id,
                    strategy_id=s.id,
                    symbol=s.symbol,
                    side='long',
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

        except Exception as e:
            results.append(f'{s.name}: 錯誤 - {e}')
            db.session.rollback()

    return ' | '.join(results)


@celery_app.task
def update_positions():
    """更新持倉當前價格和浮動盈虧（含槓桿）"""
    positions = Position.query.filter_by(status='open').all()
    for pos in positions:
        try:
            ticker = get_ticker(pos.symbol)
            pos.current_price = ticker['price']
            raw_pnl = (ticker['price'] - pos.entry_price) * pos.size
            pos.unrealized_pnl = raw_pnl * LEVERAGE
        except Exception as e:
            print(f'[update] 持倉 {pos.id} 更新失敗: {e}')
    db.session.commit()
    return f'已更新 {len(positions)} 個持倉'


@celery_app.task
def check_stop_loss():
    """檢查止損止盈（含槓桿）"""
    positions = Position.query.filter_by(status='open').all()
    triggered = []
    for pos in positions:
        try:
            ticker = get_ticker(pos.symbol)
            current = ticker['price']
            raw_pnl_pct = ((current - pos.entry_price) / pos.entry_price) * 100
            pnl_pct = raw_pnl_pct * LEVERAGE

            if pnl_pct <= -STOP_LOSS_PCT:
                order = _simulated_order(pos.symbol, 'sell', pos.size * current, current)
                pnl = raw_pnl_pct * pos.size * pos.entry_price * LEVERAGE / 100
                trade = Trade(
                    position_id=pos.id,
                    strategy_id=pos.strategy_id,
                    symbol=pos.symbol,
                    side='long',
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

            elif pnl_pct >= TAKE_PROFIT_PCT:
                order = _simulated_order(pos.symbol, 'sell', pos.size * current, current)
                pnl = raw_pnl_pct * pos.size * pos.entry_price * LEVERAGE / 100
                trade = Trade(
                    position_id=pos.id,
                    strategy_id=pos.strategy_id,
                    symbol=pos.symbol,
                    side='long',
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

        except Exception as e:
            print(f'[sl] 檢查失敗: {e}')

    return f'觸發 {len(triggered)} 個' if triggered else '無觸發'
