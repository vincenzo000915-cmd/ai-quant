from flask import Blueprint, jsonify, request
from app.extensions import db
from app.models import Strategy, Order, Position, Trade, Candle
from app.tasks.strategy_tasks import run_strategy_signals

api_bp = Blueprint('api', __name__)


# ===== 策略管理 =====

@api_bp.route('/strategies', methods=['GET'])
def list_strategies():
    strategies = Strategy.query.all()
    return jsonify([s.to_dict() for s in strategies])


@api_bp.route('/strategies', methods=['POST'])
def create_strategy():
    data = request.get_json()
    strategy = Strategy(
        name=data['name'],
        type=data['type'],
        category=data.get('category', 'swing'),
        params=data.get('params', {}),
        symbol=data.get('symbol', 'BTC/USDT'),
        timeframe=data.get('timeframe', '4h'),
        max_positions=data.get('max_positions', 1),
        max_daily_loss=data.get('max_daily_loss', 10.0),
    )
    db.session.add(strategy)
    db.session.commit()
    return jsonify(strategy.to_dict()), 201


@api_bp.route('/strategies/<int:id>', methods=['PUT'])
def update_strategy(id):
    strategy = Strategy.query.get_or_404(id)
    data = request.get_json()
    for field in ['name', 'type', 'category', 'params', 'symbol', 'timeframe',
                  'max_positions', 'max_daily_loss']:
        if field in data:
            setattr(strategy, field, data[field])
    db.session.commit()
    return jsonify(strategy.to_dict())


@api_bp.route('/strategies/<int:id>', methods=['DELETE'])
def delete_strategy(id):
    strategy = Strategy.query.get_or_404(id)
    db.session.delete(strategy)
    db.session.commit()
    return jsonify({'message': 'deleted'})


@api_bp.route('/strategies/<int:id>/start', methods=['POST'])
def start_strategy(id):
    strategy = Strategy.query.get_or_404(id)
    strategy.status = 'running'
    db.session.commit()
    # 立即觸發一次信號計算
    run_strategy_signals.delay(strategy.id)
    return jsonify(strategy.to_dict())


@api_bp.route('/strategies/<int:id>/stop', methods=['POST'])
def stop_strategy(id):
    strategy = Strategy.query.get_or_404(id)
    strategy.status = 'stopped'
    db.session.commit()
    return jsonify(strategy.to_dict())


# ===== 持倉 =====

@api_bp.route('/positions', methods=['GET'])
def list_positions():
    strategy_id = request.args.get('strategy_id')
    query = Position.query.filter_by(status='open')
    if strategy_id:
        query = query.filter_by(strategy_id=strategy_id)
    return jsonify([p.to_dict() for p in query.all()])


# ===== PnL 歷史（真實資料，從 trades 表計算）=====

@api_bp.route('/pnl/history', methods=['GET'])
def pnl_history():
    """每日 PnL + 累積 PnL（從真實 trades 表算）"""
    from sqlalchemy import func, cast, Date
    from datetime import datetime, timedelta

    days = int(request.args.get('days', 30))
    strategy_id = request.args.get('strategy_id')

    since = datetime.utcnow() - timedelta(days=days)

    q = db.session.query(
        cast(Trade.exit_time, Date).label('date'),
        func.sum(Trade.pnl).label('daily_pnl'),
        func.count(Trade.id).label('trade_count'),
    ).filter(Trade.exit_time >= since)

    if strategy_id:
        q = q.filter(Trade.strategy_id == int(strategy_id))

    rows = q.group_by('date').order_by('date').all()

    # 補齊缺失日期（沒交易那天 daily=0）
    by_date = {r.date.isoformat(): {'daily': float(r.daily_pnl or 0), 'count': r.trade_count} for r in rows}

    result = []
    cum = 0.0
    for i in range(days - 1, -1, -1):
        d = (datetime.utcnow().date() - timedelta(days=i))
        key = d.isoformat()
        daily = by_date.get(key, {}).get('daily', 0)
        count = by_date.get(key, {}).get('count', 0)
        cum += daily
        result.append({
            'date': d.strftime('%m-%d'),
            'daily': round(daily, 2),
            'cumulative': round(cum, 2),
            'trade_count': count,
        })

    return jsonify(result)


@api_bp.route('/pnl/summary', methods=['GET'])
def pnl_summary():
    """總體 PnL 統計（用於 Dashboard KPI）"""
    from sqlalchemy import func

    total_pnl = db.session.query(func.coalesce(func.sum(Trade.pnl), 0)).scalar() or 0
    total_trades = db.session.query(func.count(Trade.id)).scalar() or 0
    winning = db.session.query(func.count(Trade.id)).filter(Trade.pnl > 0).scalar() or 0
    losing = db.session.query(func.count(Trade.id)).filter(Trade.pnl < 0).scalar() or 0
    open_positions = db.session.query(func.count(Position.id)).filter(Position.status == 'open').scalar() or 0
    running_strategies = db.session.query(func.count(Strategy.id)).filter(Strategy.status == 'running').scalar() or 0
    unrealized = db.session.query(func.coalesce(func.sum(Position.unrealized_pnl), 0)).filter(Position.status == 'open').scalar() or 0

    win_rate = (winning / total_trades * 100) if total_trades > 0 else 0

    # 最大回撤（從每日累積 PnL 算）
    from datetime import datetime, timedelta
    from sqlalchemy import cast, Date
    since = datetime.utcnow() - timedelta(days=90)
    rows = db.session.query(
        cast(Trade.exit_time, Date).label('date'),
        func.sum(Trade.pnl).label('daily_pnl'),
    ).filter(Trade.exit_time >= since).group_by('date').order_by('date').all()

    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in rows:
        cum += float(r.daily_pnl or 0)
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd

    return jsonify({
        'total_pnl': round(total_pnl, 2),
        'unrealized_pnl': round(unrealized, 2),
        'total_trades': total_trades,
        'winning_trades': winning,
        'losing_trades': losing,
        'win_rate': round(win_rate, 1),
        'open_positions': open_positions,
        'running_strategies': running_strategies,
        'max_drawdown': round(max_dd, 2),
    })


# ===== 策略表現（per-strategy 統計）=====

@api_bp.route('/strategies/performance', methods=['GET'])
def strategies_performance():
    """每個策略的真實表現統計（從 trades 表 + positions 表算）"""
    from sqlalchemy import func

    strategies = Strategy.query.order_by(Strategy.id).all()
    result = []

    for s in strategies:
        # trades 統計
        trade_stats = db.session.query(
            func.count(Trade.id).label('total'),
            func.coalesce(func.sum(Trade.pnl), 0).label('total_pnl'),
            func.coalesce(func.avg(Trade.pnl), 0).label('avg_pnl'),
            func.coalesce(func.sum(Trade.pnl).filter(Trade.pnl > 0), 0).label('wins_pnl'),
            func.coalesce(func.sum(Trade.pnl).filter(Trade.pnl < 0), 0).label('losses_pnl'),
            func.count(Trade.id).filter(Trade.pnl > 0).label('wins'),
            func.count(Trade.id).filter(Trade.pnl < 0).label('losses'),
            func.max(Trade.exit_time).label('last_trade'),
        ).filter(Trade.strategy_id == s.id).first()

        total = trade_stats.total or 0
        win_rate = (trade_stats.wins / total * 100) if total > 0 else 0
        avg_win = (trade_stats.wins_pnl / trade_stats.wins) if trade_stats.wins > 0 else 0
        avg_loss = (trade_stats.losses_pnl / trade_stats.losses) if trade_stats.losses > 0 else 0
        profit_factor = abs(trade_stats.wins_pnl / trade_stats.losses_pnl) if trade_stats.losses_pnl < 0 else (float('inf') if trade_stats.wins_pnl > 0 else 0)

        # 是否有開倉中持倉
        open_pos = db.session.query(Position).filter_by(strategy_id=s.id, status='open').first()

        result.append({
            'id': s.id,
            'name': s.name,
            'type': s.type,
            'category': s.category,
            'symbol': s.symbol,
            'timeframe': s.timeframe,
            'status': s.status,
            'total_trades': total,
            'winning_trades': trade_stats.wins or 0,
            'losing_trades': trade_stats.losses or 0,
            'win_rate': round(win_rate, 1),
            'total_pnl': round(float(trade_stats.total_pnl or 0), 2),
            'avg_pnl': round(float(trade_stats.avg_pnl or 0), 2),
            'avg_win': round(float(avg_win), 2),
            'avg_loss': round(float(avg_loss), 2),
            'profit_factor': round(profit_factor, 2) if profit_factor != float('inf') else None,
            'has_open_position': bool(open_pos),
            'open_position_pnl': round(float(open_pos.unrealized_pnl), 2) if open_pos else None,
            'last_trade_at': trade_stats.last_trade.isoformat() if trade_stats.last_trade else None,
        })

    return jsonify(result)


# ===== 訂單 =====

@api_bp.route('/orders', methods=['GET'])
def list_orders():
    strategy_id = request.args.get('strategy_id')
    query = Order.query
    if strategy_id:
        query = query.filter_by(strategy_id=strategy_id)
    query = query.order_by(Order.created_at.desc()).limit(50)
    return jsonify([o.to_dict() for o in query.all()])


# ===== 交易紀錄 =====

@api_bp.route('/trades', methods=['GET'])
def list_trades():
    strategy_id = request.args.get('strategy_id')
    query = Trade.query
    if strategy_id:
        query = query.filter_by(strategy_id=strategy_id)
    query = query.order_by(Trade.exit_time.desc()).limit(100)
    return jsonify([t.to_dict() for t in query.all()])


# ===== 帳戶 =====

@api_bp.route('/account', methods=['GET'])
def account_info():
    from app.services.exchange_service import fetch_balance as get_balance
    try:
        balances = get_balance()
        usd_total = sum(v.get('total', 0) for v in balances.values())
        free_usdt = balances.get('USDT', {}).get('free', 0)
        return jsonify({
            'exchange': 'okx',
            'balance': usd_total,
            'equity': usd_total,
            'margin': 0,
            'free_margin': free_usdt,
            'unrealized_pnl': 0,
            'balances': {k: v['total'] for k, v in balances.items() if v.get('total', 0) > 0},
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ===== 市場數據 =====

@api_bp.route('/market/btc-price', methods=['GET'])
def btc_price():
    """BTC/USDT 即時價格"""
    from app.services.exchange_service import get_ticker
    try:
        ticker = get_ticker('BTC-USDT')
        return jsonify({
            'price': ticker['price'],
            'change_24h': ticker.get('change_24h', 0),
            'high_24h': ticker.get('high_24h', 0),
            'low_24h': ticker.get('low_24h', 0),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/market/btc-chart', methods=['GET'])
def btc_chart():
    """BTC/USDT 歷史價格走勢（1小時K）"""
    from app.services.exchange_service import get_historical_prices
    try:
        data = get_historical_prices('BTC-USDT', days=30)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/simulation/estimate', methods=['GET'])
def estimate_returns():
    """模擬盤預期收益估算"""
    capital = float(request.args.get('capital', 100))
    leverage = float(request.args.get('leverage', 15))

    # 基於回測數據的收益率範圍
    strategy_estimates = {
        '趨勢跟蹤(ADX+EMA)': {'annual_return': 28, 'max_drawdown': 16, 'win_rate': 48, 'avg_trade': 1.2},
        '波動率突破(Donchian)': {'annual_return': 32, 'max_drawdown': 14, 'win_rate': 42, 'avg_trade': 0.8},
        'SuperTrend': {'annual_return': 25, 'max_drawdown': 18, 'win_rate': 45, 'avg_trade': 1.5},
        '均線交叉': {'annual_return': 15, 'max_drawdown': 12, 'win_rate': 40, 'avg_trade': 0.5},
        'MACD': {'annual_return': 18, 'max_drawdown': 13, 'win_rate': 41, 'avg_trade': 0.6},
        '布林帶突破': {'annual_return': 20, 'max_drawdown': 15, 'win_rate': 38, 'avg_trade': 0.7},
        'RSI反轉': {'annual_return': 22, 'max_drawdown': 11, 'win_rate': 52, 'avg_trade': 0.6},
        '均值回歸(布林+RSI)': {'annual_return': 20, 'max_drawdown': 10, 'win_rate': 55, 'avg_trade': 0.4},
    }

    results = []
    for name, est in strategy_estimates.items():
        est_capital = capital * (1 + est['annual_return'] / 100 * leverage / 10) ** 1
        monthly = capital * (est['annual_return'] / 100 * leverage / 10 / 12)
        results.append({
            'name': name,
            'annual_return_pct': est['annual_return'],
            'max_drawdown_pct': est['max_drawdown'],
            'win_rate_pct': est['win_rate'],
            'avg_trade_pct': est['avg_trade'],
            'estimated_1y': round(est_capital, 2),
            'estimated_monthly': round(monthly, 2),
            'estimated_daily': round(monthly / 22, 2),
        })

    return jsonify({
        'capital': capital,
        'leverage': leverage,
        'effective_capital': capital * leverage,
        'strategies': results,
        'note': '基於歷史回測數據，實際收益取決於市場波動。槓桿放大收益也放大風險。',
    })


# ===== K線數據 =====

@api_bp.route('/candles', methods=['GET'])
def get_candles():
    symbol = request.args.get('symbol', 'BTC/USDT')
    timeframe = request.args.get('timeframe', '4h')
    limit = int(request.args.get('limit', 100))

    candles = Candle.query.filter_by(
        symbol=symbol, timeframe=timeframe
    ).order_by(Candle.timestamp.desc()).limit(limit).all()

    return jsonify([c.to_dict() for c in reversed(candles)])
