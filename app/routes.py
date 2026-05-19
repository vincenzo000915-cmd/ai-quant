from flask import Blueprint, jsonify, request
from app.extensions import db
from app.models import Strategy, Order, Position, Trade, Candle, BacktestResult, StrategyCandidate
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


@api_bp.route('/strategies/health/check', methods=['POST'])
def strategies_health_check():
    """Phase 5.3: 觸發一次健康檢查（async，丟給 Celery worker）。
    完成後可在 Strategies 表看 status='retired' 的策略 + retire_reason。
    """
    from app.tasks.strategy_tasks import monitor_strategy_health
    task = monitor_strategy_health.delay()
    return jsonify({
        'task_id': task.id,
        'note': '已排入 Celery worker 跑（每策略 ~14s，9 個約 2 分鐘）。完成後重新整理頁面看結果。',
    }), 202


@api_bp.route('/strategies/<int:id>/revive', methods=['POST'])
def revive_strategy(id):
    """手動把 retired 策略救回 stopped 狀態（不直接 running，user 還要再啟）"""
    strategy = Strategy.query.get_or_404(id)
    if strategy.status != 'retired':
        return jsonify({'error': f'status={strategy.status}, not retired'}), 400
    strategy.status = 'stopped'
    strategy.retired_at = None
    strategy.retire_reason = None
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


# ===== 回測（Phase 3）=====

def _run_strategy_backtest(strategy, candle_limit=2000):
    """執行單一策略回測並寫入 DB（同步）"""
    from app.services.exchange_service import fetch_ohlcv_history
    from app.services.backtest_engine import run_backtest

    candles = fetch_ohlcv_history(strategy.symbol, strategy.timeframe, total_limit=candle_limit)
    result = run_backtest(
        strategy.type, strategy.params or {}, candles,
        timeframe=strategy.timeframe,
    )

    if result.get('status') == 'error':
        bt = BacktestResult(
            strategy_id=strategy.id,
            strategy_type=strategy.type,
            params_snapshot=strategy.params or {},
            symbol=strategy.symbol,
            timeframe=strategy.timeframe,
            status='error',
            error_message=result.get('error_message', 'unknown'),
        )
        db.session.add(bt)
        db.session.commit()
        return bt.to_dict()

    bt = BacktestResult(
        strategy_id=strategy.id,
        strategy_type=strategy.type,
        params_snapshot=strategy.params or {},
        symbol=strategy.symbol,
        timeframe=strategy.timeframe,
        leverage=15.0,
        position_size_usdt=10.0,
        stop_loss_pct=5.0,
        take_profit_pct=8.0,
        initial_capital=100.0,
        period_start=result['period_start'],
        period_end=result['period_end'],
        candle_count=result['candle_count'],
        total_trades=result['total_trades'],
        winning_trades=result['winning_trades'],
        losing_trades=result['losing_trades'],
        win_rate=result['win_rate'],
        total_pnl=result['total_pnl'],
        avg_pnl=result['avg_pnl'],
        avg_win=result['avg_win'],
        avg_loss=result['avg_loss'],
        profit_factor=result['profit_factor'],
        max_drawdown=result['max_drawdown'],
        max_drawdown_pct=result['max_drawdown_pct'],
        sharpe_ratio=result['sharpe_ratio'],
        final_equity=result['final_equity'],
        annual_return_pct=result['annual_return_pct'],
        equity_curve=result['equity_curve'],
        trades_json=result['trades'],
        duration_ms=result['duration_ms'],
        status='completed',
    )
    db.session.add(bt)
    db.session.commit()
    return bt.to_dict()


@api_bp.route('/strategies/<int:id>/backtest', methods=['POST'])
def trigger_backtest(id):
    """觸發單一策略回測（同步，目前不走 Celery）"""
    strategy = Strategy.query.get_or_404(id)
    try:
        d = _run_strategy_backtest(strategy)
        return jsonify(d), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/strategies/<int:id>/backtest', methods=['GET'])
def latest_backtest(id):
    """取得策略的最新回測結果（含 equity curve + trades）"""
    bt = BacktestResult.query.filter_by(strategy_id=id).order_by(BacktestResult.created_at.desc()).first()
    if not bt:
        return jsonify({'error': 'no backtest yet'}), 404
    include_curve = request.args.get('detailed', '0') == '1'
    return jsonify(bt.to_dict(include_curve=include_curve))


@api_bp.route('/strategies/<int:id>/backtest/all', methods=['GET'])
def all_backtests(id):
    """所有歷史回測（不含 curve）"""
    bts = BacktestResult.query.filter_by(strategy_id=id).order_by(BacktestResult.created_at.desc()).limit(20).all()
    return jsonify([bt.to_dict() for bt in bts])


@api_bp.route('/backtests/latest', methods=['GET'])
def all_latest_backtests():
    """所有策略各自最新一次回測（給 dashboard 用）"""
    from sqlalchemy import func
    sub = db.session.query(
        BacktestResult.strategy_id,
        func.max(BacktestResult.created_at).label('latest'),
    ).group_by(BacktestResult.strategy_id).subquery()
    rows = db.session.query(BacktestResult).join(
        sub,
        (BacktestResult.strategy_id == sub.c.strategy_id) &
        (BacktestResult.created_at == sub.c.latest)
    ).all()
    return jsonify([r.to_dict() for r in rows])


@api_bp.route('/backtests/run-all', methods=['POST'])
def run_all_backtests():
    """批次跑所有 strategies 的回測（一次性，慢）"""
    results = []
    strategies = Strategy.query.all()
    for s in strategies:
        try:
            r = _run_strategy_backtest(s)
            results.append({'strategy_id': s.id, 'name': s.name, 'ok': True, 'total_trades': r.get('total_trades'), 'total_pnl': r.get('total_pnl')})
        except Exception as e:
            results.append({'strategy_id': s.id, 'name': s.name, 'ok': False, 'error': str(e)})
    return jsonify({'count': len(results), 'results': results})


# ===== 策略表現（per-strategy 統計）=====

@api_bp.route('/strategies/performance', methods=['GET'])
def strategies_performance():
    """每個策略的真實表現統計（trades 表 + positions 表 + 最新 backtest）"""
    from sqlalchemy import func

    strategies = Strategy.query.order_by(Strategy.id).all()

    # 預載每個 strategy 最新 backtest
    bt_map = {}
    sub = db.session.query(
        BacktestResult.strategy_id,
        func.max(BacktestResult.created_at).label('latest'),
    ).filter(BacktestResult.status == 'completed').group_by(BacktestResult.strategy_id).subquery()
    latest_bts = db.session.query(BacktestResult).join(
        sub,
        (BacktestResult.strategy_id == sub.c.strategy_id) &
        (BacktestResult.created_at == sub.c.latest)
    ).all()
    for bt in latest_bts:
        bt_map[bt.strategy_id] = bt

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

        bt = bt_map.get(s.id)
        bt_data = None
        if bt:
            bt_data = {
                'total_trades': bt.total_trades,
                'win_rate': bt.win_rate,
                'total_pnl': bt.total_pnl,
                'avg_pnl': bt.avg_pnl,
                'max_drawdown_pct': bt.max_drawdown_pct,
                'sharpe_ratio': bt.sharpe_ratio,
                'annual_return_pct': bt.annual_return_pct,
                'profit_factor': bt.profit_factor,
                'created_at': bt.created_at.isoformat() if bt.created_at else None,
            }

        # 評級（基於 backtest sharpe + drawdown）
        rating = None
        if bt:
            if bt.sharpe_ratio is not None:
                if bt.sharpe_ratio >= 3.0:
                    rating = 'excellent'
                elif bt.sharpe_ratio >= 1.5:
                    rating = 'good'
                elif bt.sharpe_ratio >= 0:
                    rating = 'marginal'
                else:
                    rating = 'negative'
            if bt.max_drawdown_pct and bt.max_drawdown_pct >= 100:
                rating = 'liquidated'  # 模擬下早就爆倉

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
            'backtest': bt_data,
            'rating': rating,
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


@api_bp.route('/config', methods=['GET'])
def get_system_config():
    """系統設定 — capital / leverage / trade_size / SL/TP / 模式 (paper|live)"""
    from app.services.config_service import get_config
    return jsonify(get_config())


@api_bp.route('/config', methods=['PUT'])
def update_system_config():
    """部分更新 system_config。
    寫 trading_mode='live' 會被擋 — Phase 6 風控完成前不允許實盤。
    """
    from app.services.config_service import update, DEFAULTS
    data = request.get_json() or {}
    # 過濾未知 key
    patch = {k: v for k, v in data.items() if k in DEFAULTS}
    # 安全鎖：實盤模式暫不開放
    if patch.get('trading_mode') == 'live':
        return jsonify({
            'error': 'live trading is locked until Phase 6 (live-risk safeguards: daily loss cap, anomaly detect, kill-switch, Telegram alerts).',
            'hint': '改用 trading_mode=paper 繼續模擬盤',
        }), 403
    # 範圍守衛
    if 'leverage' in patch and not (1 <= patch['leverage'] <= 100):
        return jsonify({'error': 'leverage out of range [1,100]'}), 400
    if 'capital_usdt' in patch and patch['capital_usdt'] <= 0:
        return jsonify({'error': 'capital_usdt must be > 0'}), 400
    if 'trade_size_usdt' in patch and patch['trade_size_usdt'] <= 0:
        return jsonify({'error': 'trade_size_usdt must be > 0'}), 400
    if 'stop_loss_pct' in patch and not (0 < patch['stop_loss_pct'] <= 50):
        return jsonify({'error': 'stop_loss_pct out of range (0,50]'}), 400
    if 'take_profit_pct' in patch and not (0 < patch['take_profit_pct'] <= 200):
        return jsonify({'error': 'take_profit_pct out of range (0,200]'}), 400
    return jsonify(update(patch))


@api_bp.route('/simulation/estimate', methods=['GET'])
def estimate_returns():
    """模擬盤預期收益估算 — 改用真實 backtest 數據（Phase 3 後）"""
    capital = float(request.args.get('capital', 100))
    leverage = float(request.args.get('leverage', 15))

    # 從每個策略的最新 backtest 合計
    from sqlalchemy import func as _f
    sub = db.session.query(
        BacktestResult.strategy_id,
        _f.max(BacktestResult.created_at).label('latest'),
    ).group_by(BacktestResult.strategy_id).subquery()
    rows = db.session.query(BacktestResult, Strategy).join(
        sub,
        (BacktestResult.strategy_id == sub.c.strategy_id) &
        (BacktestResult.created_at == sub.c.latest)
    ).join(Strategy, Strategy.id == BacktestResult.strategy_id).all()

    results = []
    for bt, s in rows:
        if bt.status != 'completed':
            continue
        results.append({
            'strategy_id': s.id,
            'name': s.name,
            'category': s.category,
            'timeframe': s.timeframe,
            'annual_return_pct': bt.annual_return_pct,
            'max_drawdown_pct': bt.max_drawdown_pct,
            'win_rate_pct': bt.win_rate,
            'sharpe_ratio': bt.sharpe_ratio,
            'profit_factor': bt.profit_factor,
            'total_trades': bt.total_trades,
            'backtest_pnl': bt.total_pnl,
        })

    results.sort(key=lambda r: (r.get('sharpe_ratio') or -999), reverse=True)
    return jsonify({
        'capital': capital,
        'leverage': leverage,
        'strategies': results,
        'source': 'real_backtest',
        'note': '數據來自真實歷史回測，非估算',
    })


# ===== 策略候選池（Phase 4）=====

@api_bp.route('/candidates', methods=['GET'])
def list_candidates():
    """列出候選策略，可按 status / source 過濾，預設按建立時間倒序"""
    q = StrategyCandidate.query
    status = request.args.get('status')
    source = request.args.get('source')
    if status:
        q = q.filter_by(status=status)
    if source:
        q = q.filter_by(source=source)
    limit = int(request.args.get('limit', 100))
    q = q.order_by(StrategyCandidate.created_at.desc()).limit(limit)

    items = q.all()
    # 預載最新 backtest，避免 N+1
    out = []
    for c in items:
        d = c.to_dict(include_code=False)
        if c.backtest:
            bt = c.backtest
            d['backtest'] = {
                'sharpe_ratio': bt.sharpe_ratio,
                'annual_return_pct': bt.annual_return_pct,
                'max_drawdown_pct': bt.max_drawdown_pct,
                'profit_factor': bt.profit_factor,
                'total_trades': bt.total_trades,
                'win_rate': bt.win_rate,
                'final_equity': bt.final_equity,
            }
        out.append(d)
    return jsonify(out)


@api_bp.route('/candidates/stats', methods=['GET'])
def candidates_stats():
    """候選池摘要（給 dashboard 統計用）"""
    from sqlalchemy import func
    rows = db.session.query(
        StrategyCandidate.status,
        func.count(StrategyCandidate.id),
    ).group_by(StrategyCandidate.status).all()
    by_status = {s: n for s, n in rows}
    rows2 = db.session.query(
        StrategyCandidate.source,
        func.count(StrategyCandidate.id),
    ).group_by(StrategyCandidate.source).all()
    by_source = {s: n for s, n in rows2}
    return jsonify({
        'total': sum(by_status.values()),
        'by_status': by_status,
        'by_source': by_source,
    })


@api_bp.route('/candidates/<int:cid>', methods=['GET'])
def get_candidate(cid):
    """取得單一候選策略（含原始碼 + 翻譯 + 回測連結）"""
    c = StrategyCandidate.query.get_or_404(cid)
    d = c.to_dict(include_code=True)
    if c.backtest:
        d['backtest'] = c.backtest.to_dict(include_curve=False)
    return jsonify(d)


@api_bp.route('/candidates', methods=['POST'])
def create_candidate():
    """手動新增候選（爬蟲也會走這條，內部呼叫）"""
    data = request.get_json() or {}
    if not data.get('source') or not data.get('raw_code'):
        return jsonify({'error': 'source and raw_code required'}), 400
    c = StrategyCandidate(
        source=data['source'],
        source_url=data.get('source_url'),
        source_name=data.get('source_name'),
        source_author=data.get('source_author'),
        source_meta=data.get('source_meta', {}),
        raw_code=data['raw_code'],
        raw_lang=data.get('raw_lang', 'python'),
        candidate_type=data.get('candidate_type'),
        category=data.get('category', 'swing'),
        timeframe=data.get('timeframe', '4h'),
        default_params=data.get('default_params', {}),
        status=data.get('status', 'pending'),
    )
    db.session.add(c)
    db.session.commit()
    return jsonify(c.to_dict(include_code=True)), 201


@api_bp.route('/candidates/<int:cid>', methods=['DELETE'])
def delete_candidate(cid):
    c = StrategyCandidate.query.get_or_404(cid)
    db.session.delete(c)
    db.session.commit()
    return jsonify({'message': 'deleted'})


@api_bp.route('/candidates/<int:cid>/reject', methods=['POST'])
def reject_candidate(cid):
    """標記為 rejected（不刪，保留紀錄）"""
    c = StrategyCandidate.query.get_or_404(cid)
    c.status = 'rejected'
    data = request.get_json() or {}
    if data.get('note'):
        c.llm_notes = (c.llm_notes or '') + f'\n[rejected] {data["note"]}'
    db.session.commit()
    return jsonify(c.to_dict())


@api_bp.route('/candidates/crawl/github', methods=['POST'])
def crawl_github():
    """觸發 GitHub 爬蟲。POST body 可選：
    { "repos": [...自訂 repo cfg...], "max_files_per_repo": 20 }
    沒帶 body 就跑預設清單，慢（可能 1-3 分鐘）。
    """
    from app.services.crawlers.github import crawl_all
    data = request.get_json() or {}
    repos = data.get('repos')
    max_files = data.get('max_files_per_repo')
    try:
        result = crawl_all(repos=repos, max_files_per_repo=max_files)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 500


@api_bp.route('/candidates/<int:cid>/backtest', methods=['POST'])
def backtest_candidate_route(cid):
    """跑單一候選策略的回測。候選必須已 translated。"""
    from app.services.candidate_pipeline import backtest_candidate
    result = backtest_candidate(cid)
    if result['ok']:
        return jsonify(result), 200
    err = result.get('error', '')
    code = 400 if ('not found' in err or 'status must be' in err or 'no parsed_signal' in err) else 500
    return jsonify(result), code


@api_bp.route('/candidates/backtest-pending', methods=['POST'])
def backtest_pending_candidates():
    """批次跑所有 status='translated' 的候選回測（同步、慢）。可選 ?max=N 限制數量。"""
    from app.services.candidate_pipeline import backtest_all_translated
    max_count = request.args.get('max', type=int)
    return jsonify(backtest_all_translated(max_count=max_count))


@api_bp.route('/candidates/<int:cid>/translate', methods=['POST'])
def translate_candidate(cid):
    """跑 LLM 翻譯 + 沙箱驗證。同步，慢（~5-15s/candidate）。"""
    from app.services.candidate_pipeline import translate_and_verify
    result = translate_and_verify(cid)
    if result['ok']:
        return jsonify(result), 200
    # 區分缺金鑰 vs 翻譯失敗
    err = result.get('error', '')
    code = 400 if 'not found' in err.lower() else 500
    if 'ANTHROPIC_API_KEY' in err:
        code = 503
    return jsonify(result), code


@api_bp.route('/candidates/<int:cid>/promote', methods=['POST'])
def promote_candidate(cid):
    """把 qualified candidate 推上線 — 建立 strategies 條目並註冊 signal_fn。
    Body 可選：{ "name": "...", "symbol": "BTC/USDT" }
    """
    from app.services.candidate_pipeline import promote_candidate as do_promote
    data = request.get_json() or {}
    result = do_promote(cid, name=data.get('name'), symbol=data.get('symbol', 'BTC/USDT'))
    if result['ok']:
        return jsonify(result), 201
    err = result.get('error', '')
    code = 400 if ('not found' in err or 'must be qualified' in err or 'already exists' in err or 'missing' in err) else 500
    return jsonify(result), code


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
