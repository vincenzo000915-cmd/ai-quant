from flask import Blueprint, abort, jsonify, request
from app.extensions import db
from app.models import Strategy, Order, Position, Trade, Candle, BacktestResult, StrategyCandidate, ParamOptimization, AuditLog
from app.services.rate_limit import rate_limit
from app.services.cache import cached_response
from app.services.user_scope import (
    apply_user_filter, assign_user_id, current_user_id, get_owned,
    is_admin_actor, require_actor, scoped_query,
)
from app.tasks.strategy_tasks import run_strategy_signals

api_bp = Blueprint('api', __name__)


# ===== Phase 11.1.3: User-scope internal helpers =====

def _owned_strategy(id):
    """User-scoped 取 strategy。admin 看全部；user 只能看自己。無權限 → 404"""
    s = get_owned(Strategy, id)
    if not s:
        abort(404)
    return s


def _owned_position(id):
    p = get_owned(Position, id)
    if not p:
        abort(404)
    return p


# ===== 策略管理 =====

@api_bp.route('/strategies', methods=['GET'])
@require_actor
def list_strategies():
    strategies = scoped_query(Strategy).all()
    return jsonify([s.to_dict() for s in strategies])


@api_bp.route('/strategies', methods=['POST'])
@require_actor
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
    assign_user_id(strategy)
    db.session.add(strategy)
    db.session.commit()
    return jsonify(strategy.to_dict()), 201


@api_bp.route('/strategies/<int:id>', methods=['PUT'])
def update_strategy(id):
    strategy = _owned_strategy(id)
    data = request.get_json()
    for field in ['name', 'type', 'category', 'params', 'symbol', 'timeframe',
                  'max_positions', 'max_daily_loss']:
        if field in data:
            setattr(strategy, field, data[field])
    db.session.commit()
    return jsonify(strategy.to_dict())


@api_bp.route('/strategies/<int:id>', methods=['DELETE'])
def delete_strategy(id):
    strategy = _owned_strategy(id)
    db.session.delete(strategy)
    db.session.commit()
    return jsonify({'message': 'deleted'})


@api_bp.route('/strategies/<int:id>/start', methods=['POST'])
def start_strategy(id):
    strategy = _owned_strategy(id)
    strategy.status = 'running'
    db.session.commit()
    # 立即觸發一次信號計算
    run_strategy_signals.delay(strategy.id)
    return jsonify(strategy.to_dict())


@api_bp.route('/strategies/<int:id>/stop', methods=['POST'])
def stop_strategy(id):
    strategy = _owned_strategy(id)
    strategy.status = 'stopped'
    db.session.commit()
    return jsonify(strategy.to_dict())


@api_bp.route('/strategies/live-state', methods=['GET'])
def strategies_live_state():
    """Phase 7.2: 每 running 策略的指標即時讀數 + 距觸發 hint"""
    from app.services.live_state import all_live_states
    return jsonify(all_live_states())


@api_bp.route('/strategies/<int:id>/optimize', methods=['POST'])
@rate_limit('10/min')
def trigger_optimize(id):
    """Phase 10.2: 觸發策略參數網格搜尋（非同步，丟給 Celery worker）。"""
    from app.services.audit import log as audit
    from app.services.param_optimizer import get_grid, grid_size
    from app.tasks.strategy_tasks import optimize_strategy_params

    strategy = _owned_strategy(id)
    grid = get_grid(strategy.type)
    if not grid:
        return jsonify({'error': f'strategy_type={strategy.type} 沒有定義參數網格，無法優化'}), 400

    body = request.get_json(silent=True) or {}
    max_combos = int(body.get('max_combos', 24))

    # 防止對同一策略同時跑多個優化（strategy 已 user-scope，optimization 跟著綁定）
    running = scoped_query(ParamOptimization).filter(
        ParamOptimization.strategy_id == id,
        ParamOptimization.status.in_(['pending', 'running']),
    ).first()
    if running:
        return jsonify({
            'error': '已有一個進行中的優化任務',
            'optimization_id': running.id,
            'status': running.status,
        }), 409

    opt = ParamOptimization(
        strategy_id=id,
        status='pending',
        grid=grid,
        baseline_params=dict(strategy.params or {}),
        combos_total=min(grid_size(grid) + 1, max_combos + 1),
    )
    assign_user_id(opt, prefer_user_id=strategy.user_id)
    db.session.add(opt)
    db.session.commit()

    task = optimize_strategy_params.delay(opt.id, max_combos)
    audit('param_optimize_start', actor='user',
          strategy_id=id, optimization_id=opt.id, grid=grid, max_combos=max_combos)

    return jsonify({
        'optimization_id': opt.id,
        'task_id': task.id,
        'status': opt.status,
        'combos_total': opt.combos_total,
        'message': '已排入 Celery 跑（每組 ~10-20s，多參數需數分鐘）。可輪詢 /optimize/latest 看進度。',
    }), 202


@api_bp.route('/strategies/<int:id>/optimize/latest', methods=['GET'])
@require_actor
def latest_optimize(id):
    """Phase 10.2: 取得策略最新一次優化結果（含進度）。"""
    # 先確認策略歸屬（404 若無 access）
    _owned_strategy(id)
    opt = (
        scoped_query(ParamOptimization)
        .filter_by(strategy_id=id)
        .order_by(ParamOptimization.id.desc())
        .first()
    )
    if not opt:
        return jsonify({'error': 'no optimization yet'}), 404
    return jsonify(opt.to_dict(include_results=True))


@api_bp.route('/strategies/<int:id>/apply-params', methods=['POST'])
def apply_strategy_params(id):
    """Phase 10.2: 把優化選出的最佳參數套用到 strategy.params。"""
    from app.services.audit import log as audit
    strategy = _owned_strategy(id)
    body = request.get_json(silent=True) or {}
    new_params = body.get('params')
    if not isinstance(new_params, dict):
        return jsonify({'error': '需要 params 物件'}), 400

    old_params = dict(strategy.params or {})
    strategy.params = new_params
    db.session.commit()

    audit('strategy_params_applied', actor='user',
          strategy_id=id, old=old_params, new=new_params,
          optimization_id=body.get('optimization_id'))

    return jsonify({
        'strategy_id': id,
        'old_params': old_params,
        'new_params': new_params,
        'message': '已套用。可手動重啟策略或等下次 signal 自動使用新參數。',
    })


@api_bp.route('/strategies/<int:id>/fan-out', methods=['POST'])
@rate_limit('10/min')
def fan_out_strategy(id):
    """Phase 10.6: clone a strategy across multiple symbols in one click.

    Body: {"symbols": ["ETH/USDT", "SOL/USDT", ...]}

    - 每個 symbol 建一個新的 Strategy（status='stopped'，使用者手動啟動）
    - params / timeframe / category / max_positions / max_daily_loss 全部繼承
    - 用 template_group 串起家族（source 本身也補上自己的 id 當 anchor）
    - 已存在同 group 同 symbol 的兄弟會被跳過（回傳 skipped）
    """
    from app.services.audit import log as audit
    from app.services.symbols import SUPPORTED_SYMBOLS

    source = _owned_strategy(id)
    data = request.get_json() or {}
    raw_symbols = data.get('symbols') or []
    if not isinstance(raw_symbols, list) or not raw_symbols:
        return jsonify({'error': '需要 symbols 陣列'}), 400

    # 驗證 symbol
    invalid = [s for s in raw_symbols if s not in SUPPORTED_SYMBOLS]
    if invalid:
        return jsonify({'error': f'不支援的幣種：{invalid}'}), 400

    # 確保 source 自己也在 template_group 內當 anchor
    if source.template_group is None:
        source.template_group = source.id
    group = source.template_group

    # 同 group 已存在哪些 symbol，避免重複
    existing_symbols = {
        s.symbol for s in scoped_query(Strategy)
        .filter(Strategy.template_group == group)
        .all()
    }

    created = []
    skipped = []

    # 取出 source 名字的基底（去掉舊的「(XXX)」後綴，若有）
    import re
    base_name = re.sub(r'\s*\([A-Z]{2,6}\)\s*$', '', source.name).strip()

    for sym in raw_symbols:
        if sym == source.symbol or sym in existing_symbols:
            skipped.append({'symbol': sym, 'reason': '已存在同 group 兄弟'})
            continue
        nickname = sym.split('/')[0]
        clone = Strategy(
            name=f'{base_name} ({nickname})',
            type=source.type,
            category=source.category,
            params=dict(source.params or {}),
            symbol=sym,
            timeframe=source.timeframe,
            status='stopped',
            max_positions=source.max_positions,
            max_daily_loss=source.max_daily_loss,
            template_group=group,
            user_id=source.user_id,
        )
        db.session.add(clone)
        db.session.flush()  # 拿 id
        created.append({'id': clone.id, 'symbol': sym, 'name': clone.name})
        existing_symbols.add(sym)

    db.session.commit()

    audit('strategy_fan_out',
          actor='user',
          source_id=source.id,
          source_name=source.name,
          template_group=group,
          created=created,
          skipped=skipped)

    return jsonify({
        'source_id': source.id,
        'template_group': group,
        'created': created,
        'skipped': skipped,
        'message': f'已新增 {len(created)} 個兄弟實例（status=stopped，請至策略表手動啟動）',
    }), 201


@api_bp.route('/advisor/recommendations', methods=['GET'])
@cached_response('advisor', ttl=60)
def advisor_recommendations():
    """Phase 10.7: 综合所有 phase-10 诊断（相关性 + regime + MTF + 优化）生成建议。"""
    from app.services.strategy_advisor import build_recommendations
    return jsonify(build_recommendations())


@api_bp.route('/advisor/auto-apply/run', methods=['POST'])
@rate_limit('10/min')
def trigger_auto_apply():
    """Phase 10.8: 手動觸發智能托管掃描（同步跑一次，回傳結果摘要）。"""
    from app.services.advisor_executor import run_auto_apply
    r = run_auto_apply()
    return jsonify(r)


@api_bp.route('/advisor/auto-apply/history', methods=['GET'])
@require_actor
def auto_apply_history():
    """Phase 10.8: 最近 N 條自動套用紀錄（讀 audit_log）。"""
    limit = min(int(request.args.get('limit', 50)), 200)
    rows = (
        scoped_query(AuditLog)
        .filter(AuditLog.event_type == 'advisor_auto_apply')
        .order_by(AuditLog.id.desc())
        .limit(limit)
        .all()
    )
    return jsonify([r.to_dict() for r in rows])


@api_bp.route('/strategies/<int:id>/mtf', methods=['GET'])
def strategy_mtf(id):
    """Phase 10.4: multi-timeframe consensus check for one strategy."""
    from app.services.mtf_consensus import mtf_check
    strategy = _owned_strategy(id)
    tfs_param = request.args.get('tfs')
    tfs = None
    if tfs_param:
        tfs = [t.strip() for t in tfs_param.split(',') if t.strip()]
    return jsonify(mtf_check(strategy, tfs))


@api_bp.route('/mtf/running', methods=['GET'])
@cached_response('mtf_running', ttl=120)
def mtf_for_running():
    """Phase 10.4: MTF consensus for every running strategy."""
    from app.services.mtf_consensus import mtf_check
    running = scoped_query(Strategy).filter(Strategy.status == 'running').all()
    return jsonify({
        'strategies': [mtf_check(s) for s in running],
    })


@api_bp.route('/regime', methods=['GET'])
def get_regime():
    """Phase 10.3: market regime (ADX + Hurst) for a single symbol+timeframe."""
    from app.services.regime_detector import detect_regime
    symbol = request.args.get('symbol', 'BTC/USDT')
    timeframe = request.args.get('timeframe', '4h')
    return jsonify(detect_regime(symbol, timeframe))


@api_bp.route('/regime/running', methods=['GET'])
@cached_response('regime_running', ttl=120)
def regime_for_running():
    """Phase 10.3: regime per distinct (symbol,timeframe) used by running strategies,
    plus per-strategy affinity fit."""
    from app.services.regime_detector import detect_regime, affinity_for, fit_label

    running = scoped_query(Strategy).filter(Strategy.status == 'running').all()

    # 唯一 (symbol, tf) 對 -> 只算一次
    unique = sorted({(s.symbol, s.timeframe) for s in running})
    regimes = {}
    for sym, tf in unique:
        r = detect_regime(sym, tf)
        regimes[f'{sym}@{tf}'] = r

    per_strategy = []
    for s in running:
        r = regimes.get(f'{s.symbol}@{s.timeframe}', {})
        per_strategy.append({
            'strategy_id': s.id,
            'name': s.name,
            'type': s.type,
            'symbol': s.symbol,
            'timeframe': s.timeframe,
            'affinity': affinity_for(s.type),
            'regime': r.get('regime'),
            'fit': fit_label(s.type, r.get('regime', 'unknown')),
        })

    return jsonify({
        'regimes': regimes,
        'per_strategy': per_strategy,
    })


@api_bp.route('/strategies/correlation', methods=['GET'])
@cached_response('correlation', ttl=120)
def strategies_correlation():
    """Phase 10.1: pairwise daily-PnL correlation matrix for running strategies.

    Uses live trades when available; falls back to latest backtest's trades_json
    so the matrix is useful even with no closed trades yet.
    """
    from app.services.strategy_correlation import build_correlation_matrix
    ids_param = request.args.get('ids')
    ids = None
    if ids_param:
        try:
            ids = [int(x) for x in ids_param.split(',') if x.strip()]
        except ValueError:
            return jsonify({'error': 'ids must be comma-separated integers'}), 400
    return jsonify(build_correlation_matrix(ids))


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


@api_bp.route('/strategies/<int:id>/retire', methods=['POST'])
@rate_limit('20/min')
def retire_strategy(id):
    """Phase 10.7: 手動把策略退役（給 AdvisorPanel 一鍵套用用）。"""
    from app.services.audit import log as audit
    import datetime as _dt
    strategy = _owned_strategy(id)
    if strategy.status == 'retired':
        return jsonify(strategy.to_dict())  # 已退役，幂等
    body = request.get_json(silent=True) or {}
    reason = body.get('reason') or '手動退役（advisor 建議）'
    strategy.status = 'retired'
    strategy.retired_at = _dt.datetime.utcnow()
    strategy.retire_reason = reason
    db.session.commit()
    audit('strategy_retire', actor='user', strategy_id=id, name=strategy.name, reason=reason)
    return jsonify(strategy.to_dict())


@api_bp.route('/strategies/<int:id>/revive', methods=['POST'])
def revive_strategy(id):
    """手動把 retired 策略救回 stopped 狀態（不直接 running，user 還要再啟）"""
    from app.services.audit import log as audit
    strategy = _owned_strategy(id)
    if strategy.status != 'retired':
        return jsonify({'error': f'status={strategy.status}, not retired'}), 400
    strategy.status = 'stopped'
    strategy.retired_at = None
    strategy.retire_reason = None
    db.session.commit()
    audit('strategy_revive', actor='user', strategy_id=id, name=strategy.name)
    return jsonify(strategy.to_dict())


# ===== 持倉 =====

@api_bp.route('/positions', methods=['GET'])
@require_actor
def list_positions():
    strategy_id = request.args.get('strategy_id')
    query = scoped_query(Position).filter_by(status='open')
    if strategy_id:
        query = query.filter_by(strategy_id=strategy_id)
    return jsonify([p.to_dict() for p in query.all()])


# ===== PnL 歷史（真實資料，從 trades 表計算）=====

@api_bp.route('/pnl/history', methods=['GET'])
@require_actor
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
    q = apply_user_filter(q, Trade)

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
@require_actor
def pnl_summary():
    """總體 PnL 統計（用於 Dashboard KPI）"""
    from sqlalchemy import func

    def _q(*cols, model=Trade):
        return apply_user_filter(db.session.query(*cols), model)

    total_pnl = _q(func.coalesce(func.sum(Trade.pnl), 0)).scalar() or 0
    total_trades = _q(func.count(Trade.id)).scalar() or 0
    winning = _q(func.count(Trade.id)).filter(Trade.pnl > 0).scalar() or 0
    losing = _q(func.count(Trade.id)).filter(Trade.pnl < 0).scalar() or 0
    open_positions = _q(func.count(Position.id), model=Position).filter(Position.status == 'open').scalar() or 0
    running_strategies = _q(func.count(Strategy.id), model=Strategy).filter(Strategy.status == 'running').scalar() or 0
    unrealized = _q(func.coalesce(func.sum(Position.unrealized_pnl), 0), model=Position).filter(Position.status == 'open').scalar() or 0

    win_rate = (winning / total_trades * 100) if total_trades > 0 else 0

    # 最大回撤（從每日累積 PnL 算）
    from datetime import datetime, timedelta
    from sqlalchemy import cast, Date
    since = datetime.utcnow() - timedelta(days=90)
    rows = _q(
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

    # 今日（UTC）統計
    from datetime import datetime as _dt, timezone as _tz
    today_start = _dt.now(_tz.utc).replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
    today_pnl = _q(func.coalesce(func.sum(Trade.pnl), 0)).filter(Trade.exit_time >= today_start).scalar() or 0
    today_trades = _q(func.count(Trade.id)).filter(Trade.exit_time >= today_start).scalar() or 0
    today_wins = _q(func.count(Trade.id)).filter(Trade.exit_time >= today_start, Trade.pnl > 0).scalar() or 0
    today_losses = _q(func.count(Trade.id)).filter(Trade.exit_time >= today_start, Trade.pnl < 0).scalar() or 0

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
        'today_pnl': round(float(today_pnl), 2),
        'today_trades': int(today_trades),
        'today_wins': int(today_wins),
        'today_losses': int(today_losses),
    })


# ===== 回測（Phase 3）=====

def _run_strategy_backtest(strategy, candle_limit=2000):
    """執行單一策略回測並寫入 DB（同步）"""
    from app.services.exchange_service import fetch_ohlcv_history
    from app.services.backtest_engine import run_backtest

    candles = fetch_ohlcv_history(strategy.symbol, strategy.timeframe, total_limit=candle_limit)
    from app.services.config_service import get_config as _gc
    cfg = _gc()
    result = run_backtest(
        strategy.type, strategy.params or {}, candles,
        timeframe=strategy.timeframe,
        slippage_pct=cfg.get('backtest_slippage_pct', 0.05),
        fee_pct=cfg.get('backtest_fee_pct', 0.05),
    )

    if result.get('status') == 'error':
        bt = BacktestResult(
            strategy_id=strategy.id,
            user_id=strategy.user_id,
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
        user_id=strategy.user_id,
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
    strategy = _owned_strategy(id)
    try:
        d = _run_strategy_backtest(strategy)
        return jsonify(d), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/strategies/<int:id>/backtest', methods=['GET'])
@require_actor
def latest_backtest(id):
    """取得策略的最新回測結果（含 equity curve + trades）"""
    _owned_strategy(id)
    bt = scoped_query(BacktestResult).filter_by(strategy_id=id).order_by(BacktestResult.created_at.desc()).first()
    if not bt:
        return jsonify({'error': 'no backtest yet'}), 404
    include_curve = request.args.get('detailed', '0') == '1'
    return jsonify(bt.to_dict(include_curve=include_curve))


@api_bp.route('/strategies/<int:id>/backtest/all', methods=['GET'])
@require_actor
def all_backtests(id):
    """所有歷史回測（不含 curve）"""
    _owned_strategy(id)
    bts = scoped_query(BacktestResult).filter_by(strategy_id=id).order_by(BacktestResult.created_at.desc()).limit(20).all()
    return jsonify([bt.to_dict() for bt in bts])


@api_bp.route('/backtests/latest', methods=['GET'])
@require_actor
def all_latest_backtests():
    """所有策略各自最新一次回測（給 dashboard 用）"""
    from sqlalchemy import func
    sub_q = apply_user_filter(
        db.session.query(
            BacktestResult.strategy_id,
            func.max(BacktestResult.created_at).label('latest'),
        ),
        BacktestResult,
    ).group_by(BacktestResult.strategy_id).subquery()
    main_q = apply_user_filter(db.session.query(BacktestResult), BacktestResult).join(
        sub_q,
        (BacktestResult.strategy_id == sub_q.c.strategy_id) &
        (BacktestResult.created_at == sub_q.c.latest)
    )
    rows = main_q.all()
    return jsonify([r.to_dict() for r in rows])


@api_bp.route('/backtests/run-all', methods=['POST'])
@require_actor
def run_all_backtests():
    """批次跑所有 strategies 的回測（一次性，慢）"""
    results = []
    strategies = scoped_query(Strategy).all()
    for s in strategies:
        try:
            r = _run_strategy_backtest(s)
            results.append({'strategy_id': s.id, 'name': s.name, 'ok': True, 'total_trades': r.get('total_trades'), 'total_pnl': r.get('total_pnl')})
        except Exception as e:
            results.append({'strategy_id': s.id, 'name': s.name, 'ok': False, 'error': str(e)})
    return jsonify({'count': len(results), 'results': results})


# ===== 策略表現（per-strategy 統計）=====

@api_bp.route('/strategies/performance', methods=['GET'])
@require_actor
def strategies_performance():
    """每個策略的真實表現統計（trades 表 + positions 表 + 最新 backtest）"""
    from sqlalchemy import func

    strategies = scoped_query(Strategy).order_by(Strategy.id).all()

    # 預載每個 strategy 最新 backtest
    bt_map = {}
    sub = apply_user_filter(
        db.session.query(
            BacktestResult.strategy_id,
            func.max(BacktestResult.created_at).label('latest'),
        ),
        BacktestResult,
    ).filter(BacktestResult.status == 'completed').group_by(BacktestResult.strategy_id).subquery()
    latest_bts = apply_user_filter(db.session.query(BacktestResult), BacktestResult).join(
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
@require_actor
def list_orders():
    strategy_id = request.args.get('strategy_id')
    query = scoped_query(Order)
    if strategy_id:
        query = query.filter_by(strategy_id=strategy_id)
    query = query.order_by(Order.created_at.desc()).limit(50)
    return jsonify([o.to_dict() for o in query.all()])


# ===== 交易紀錄 =====

@api_bp.route('/trades', methods=['GET'])
@require_actor
def list_trades():
    strategy_id = request.args.get('strategy_id')
    query = scoped_query(Trade)
    if strategy_id:
        query = query.filter_by(strategy_id=strategy_id)
    query = query.order_by(Trade.exit_time.desc()).limit(100)
    return jsonify([t.to_dict() for t in query.all()])


# ===== 帳戶 =====

@api_bp.route('/account', methods=['GET'])
@require_actor
def account_info():
    """Phase 11.2.2: 看 actor 的 OKX 帳號餘額 — admin 看 env (system) OKX，user 看自己綁的。"""
    from app.services.exchange_service import fetch_balance as get_balance, _resolve_creds
    uid = current_user_id()
    # is_admin (system token 或 role=admin) → 走 env
    if is_admin_actor():
        creds = None  # → fetch_balance default env
    else:
        creds = _resolve_creds(uid)
        if not creds:
            return jsonify({
                'exchange': 'okx', 'bound': False,
                'balance': 0, 'equity': 0, 'margin': 0, 'free_margin': 0, 'unrealized_pnl': 0,
                'balances': {}, 'message': '尚未綁定 OKX，请到设置页绑定',
            })
    try:
        balances = get_balance(creds=creds)
        usd_total = sum(v.get('total', 0) for v in balances.values())
        free_usdt = balances.get('USDT', {}).get('free', 0)
        return jsonify({
            'exchange': 'okx', 'bound': True,
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


@api_bp.route('/symbols', methods=['GET'])
def list_supported_symbols():
    """Phase 9.1: 系統支援的 OKX SWAP 交易對清單"""
    from app.services.symbols import supported_list
    return jsonify(supported_list())


@api_bp.route('/market/<path:symbol>/price', methods=['GET'])
def market_price(symbol):
    """通用版 ticker — symbol 可帶 / (e.g. ETH/USDT)"""
    from app.services.exchange_service import get_ticker
    try:
        t = get_ticker(symbol)
        return jsonify(t)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/market/<path:symbol>/chart', methods=['GET'])
def market_chart(symbol):
    """通用版 K 線 — symbol 可帶 / (e.g. ETH/USDT)"""
    from app.services.exchange_service import get_historical_prices
    tf = request.args.get('timeframe', '1h')
    if tf not in ('15m', '30m', '1h', '4h', '1d', '1w'):
        return jsonify({'error': f'invalid timeframe: {tf}'}), 400
    limit_arg = request.args.get('limit', type=int)
    try:
        data = get_historical_prices(symbol, timeframe=tf, limit=limit_arg)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/market/btc-chart', methods=['GET'])
def btc_chart():
    """BTC/USDT 歷史價格走勢。
    ?timeframe= 15m / 30m / 1h / 4h / 1d / 1w（預設 1h）；
    ?limit= 整數（不傳就用該 timeframe 的預設量）。
    """
    from app.services.exchange_service import get_historical_prices
    tf = request.args.get('timeframe', '1h')
    if tf not in ('15m', '30m', '1h', '4h', '1d', '1w'):
        return jsonify({'error': f'invalid timeframe: {tf}'}), 400
    limit_arg = request.args.get('limit', type=int)
    try:
        data = get_historical_prices('BTC-USDT', timeframe=tf, limit=limit_arg)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/reconcile', methods=['POST'])
def reconcile_now():
    """Phase 8.2: 立即跑一次 OKX/local 對賬"""
    from app.services.reconciliation import reconcile
    return jsonify(reconcile())


@api_bp.route('/anomaly/check', methods=['POST'])
def anomaly_check_now():
    """Phase 6.4: 立即跑 anomaly detector"""
    from app.services.anomaly_detector import run_all_checks
    return jsonify(run_all_checks())


@api_bp.route('/killswitch', methods=['POST'])
@rate_limit('5/min')
def killswitch():
    """Phase 6.3: 緊急停 — stop 所有策略 + 強平所有持倉 + halt + 通知"""
    from app.services.kill_switch import execute_kill_switch
    from app.services.audit import log as audit
    data = request.get_json() or {}
    reason = data.get('reason', 'manual')
    if data.get('confirm') != 'KILL':
        return jsonify({
            'error': 'must POST {"confirm": "KILL", "reason": "..."}',
            'note': '兩段確認防誤觸',
        }), 400
    result = execute_kill_switch(reason)
    audit('kill_switch', actor='user', reason=reason,
          stopped_strategies=result.get('stopped_strategies'),
          closed_positions=len(result.get('closed_positions', [])))
    return jsonify(result), 200


@api_bp.route('/telegram/test', methods=['POST'])
def telegram_test():
    """Phase 6.2: 試送一則 Telegram 驗證 BOT_TOKEN / CHAT_ID 設定"""
    from app.services.telegram_service import send, _enabled
    if not _enabled():
        return jsonify({
            'enabled': False,
            'error': 'TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 未設定（.env）',
        }), 503
    result = send('🧪 <b>Telegram 通道測試</b>\n收到這則表示告警通道工作正常。', force=True)
    return jsonify({'enabled': True, **result}), (200 if result.get('sent') else 502)


@api_bp.route('/halt', methods=['POST'])
@rate_limit('10/min')
def manual_halt():
    """Phase 6.1: 手動觸發 halt（全局拒新開倉）"""
    from app.services.config_service import set_halted
    from app.services.audit import log as audit
    data = request.get_json() or {}
    reason = data.get('reason', 'manual halt')
    cfg = set_halted(reason)
    audit('halt', actor='user', reason=reason)
    return jsonify(cfg), 200


@api_bp.route('/unhalt', methods=['POST'])
@rate_limit('10/min')
def manual_unhalt():
    """解除 halt"""
    from app.services.config_service import set_halted
    from app.services.audit import log as audit
    cfg = set_halted(None)
    audit('unhalt', actor='user')
    return jsonify(cfg), 200


@api_bp.route('/halt/check', methods=['POST'])
def check_daily_loss():
    """立即跑一次 monitor_daily_loss（不等 cron）"""
    from app.tasks.strategy_tasks import monitor_daily_loss
    task = monitor_daily_loss.delay()
    return jsonify({'task_id': task.id, 'note': '已派發 Celery，幾秒內生效'}), 202


@api_bp.route('/config', methods=['GET'])
def get_system_config():
    """系統設定 — capital / leverage / trade_size / SL/TP / 模式 (paper|live)"""
    from app.services.config_service import get_config
    return jsonify(get_config())


@api_bp.route('/audit', methods=['GET'])
@require_actor
def list_audit():
    """Phase 8.4: 查 audit log。?type=halt&limit=100"""
    q = scoped_query(AuditLog)
    event_type = request.args.get('type')
    actor = request.args.get('actor')
    if event_type:
        q = q.filter_by(event_type=event_type)
    if actor:
        q = q.filter(AuditLog.actor.like(f'{actor}%'))
    limit = min(int(request.args.get('limit', 100)), 500)
    rows = q.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return jsonify([r.to_dict() for r in rows])


@api_bp.route('/auth/check', methods=['GET', 'POST'])
def auth_check():
    """Phase 8.1 + 11.1: 驗鉴权狀態 — 支持 system token / user JWT 雙軌

    回傳：
    - enabled: API_AUTH_TOKEN 是否啟用
    - ok: 當前 request 是否有有效 actor (system token 或 user JWT)
    - is_system: 是否 system token 通過
    - user_id: 若 user JWT 通過則回 user.id；否則 None
    """
    from flask import g
    from app.services.auth import _expected_token
    enabled = bool(_expected_token())
    is_system = bool(getattr(g, 'is_system', False))
    user_id = getattr(g, 'current_user_id', None)
    ok = is_system or user_id is not None
    return jsonify({
        'enabled': enabled,
        'ok': ok,
        'is_system': is_system,
        'user_id': user_id,
    }), (200 if ok or not enabled else 401)


@api_bp.route('/preflight', methods=['GET'])
def preflight_check():
    """Phase 6.6: 切到 LIVE 前的檢查清單。慢（含 OKX/Telegram 實際呼叫），同步。"""
    from app.services.preflight import run_preflight
    return jsonify(run_preflight())


@api_bp.route('/config', methods=['PUT'])
@rate_limit('30/min')
def update_system_config():
    """部分更新 system_config。
    寫 trading_mode='live' 需要：
      1. Body 帶 confirm_live=True（防誤觸）
      2. Pre-flight 全過
      3. 風控任務都註冊 + 不在 halted 狀態
    """
    from app.services.config_service import update, DEFAULTS
    data = request.get_json() or {}
    # 過濾未知 key
    patch = {k: v for k, v in data.items() if k in DEFAULTS}

    # 切 LIVE 流程
    if patch.get('trading_mode') == 'live':
        if not data.get('confirm_live'):
            return jsonify({
                'error': 'must POST {"trading_mode":"live", "confirm_live": true}',
                'hint': '先打 GET /api/preflight 確認所有檢查通過，再帶 confirm_live=true',
            }), 400
        from app.services.preflight import run_preflight
        pf = run_preflight()
        if not pf['ok']:
            return jsonify({
                'error': 'pre-flight failed — 不允許切 LIVE',
                'preflight': pf,
            }), 403
        # 通過，附帶記錄上鎖時間
        from app.services.telegram_service import send as _tg
        _tg('🟢 <b>TRADING MODE → LIVE</b>\nPre-flight 全過。實盤已啟動。\n下單會直接走 OKX。', force=True)
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
    if 'sizing_mode' in patch and patch['sizing_mode'] not in ('flat', 'vol_target', 'sharpe_weighted'):
        return jsonify({'error': 'sizing_mode must be flat / vol_target / sharpe_weighted'}), 400
    if 'target_vol_pct' in patch and not (0.1 <= patch['target_vol_pct'] <= 20):
        return jsonify({'error': 'target_vol_pct out of range [0.1, 20]'}), 400
    if 'sl_mode' in patch and patch['sl_mode'] not in ('flat_pct', 'atr'):
        return jsonify({'error': 'sl_mode must be flat_pct or atr'}), 400
    if 'atr_period' in patch and not (5 <= patch['atr_period'] <= 200):
        return jsonify({'error': 'atr_period out of range [5, 200]'}), 400
    if 'atr_sl_mult' in patch and not (0.5 <= patch['atr_sl_mult'] <= 10):
        return jsonify({'error': 'atr_sl_mult out of range [0.5, 10]'}), 400
    if 'atr_tp_mult' in patch and not (0.5 <= patch['atr_tp_mult'] <= 20):
        return jsonify({'error': 'atr_tp_mult out of range [0.5, 20]'}), 400
    # Phase 10.8: 智能托管 config 守衛
    if 'auto_apply_actions' in patch:
        allowed = {'apply_params', 'pause', 'retire', 'fan_out', 'promote_candidate'}
        actions = patch['auto_apply_actions']
        if not isinstance(actions, list) or any(a not in allowed for a in actions):
            return jsonify({'error': f'auto_apply_actions 必須是 list，元素限：{sorted(allowed)}'}), 400
    if 'auto_apply_max_per_day' in patch and not (0 <= patch['auto_apply_max_per_day'] <= 100):
        return jsonify({'error': 'auto_apply_max_per_day 必須 [0, 100]'}), 400
    if 'fan_out_min_oos_sharpe' in patch and not (-5 <= patch['fan_out_min_oos_sharpe'] <= 10):
        return jsonify({'error': 'fan_out_min_oos_sharpe 必須 [-5, 10]'}), 400
    if 'auto_promote_max_per_day' in patch and not (0 <= patch['auto_promote_max_per_day'] <= 20):
        return jsonify({'error': 'auto_promote_max_per_day 必須 [0, 20]'}), 400
    if 'auto_promote_min_oos_sharpe' in patch and not (-5 <= patch['auto_promote_min_oos_sharpe'] <= 10):
        return jsonify({'error': 'auto_promote_min_oos_sharpe 必須 [-5, 10]'}), 400
    from app.services.audit import log as audit
    is_live_flip = patch.get('trading_mode') == 'live'
    new_cfg = update(patch)
    audit(
        'live_mode_flip' if is_live_flip else 'config_change',
        actor='user',
        patch=patch,
    )
    return jsonify(new_cfg)


@api_bp.route('/simulation/estimate', methods=['GET'])
@require_actor
def estimate_returns():
    """模擬盤預期收益估算 — 改用真實 backtest 數據（Phase 3 後）"""
    capital = float(request.args.get('capital', 100))
    leverage = float(request.args.get('leverage', 15))

    # 從每個策略的最新 backtest 合計
    from sqlalchemy import func as _f
    sub = apply_user_filter(
        db.session.query(
            BacktestResult.strategy_id,
            _f.max(BacktestResult.created_at).label('latest'),
        ),
        BacktestResult,
    ).group_by(BacktestResult.strategy_id).subquery()
    rows = apply_user_filter(db.session.query(BacktestResult, Strategy), BacktestResult).join(
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


@api_bp.route('/candidates/pine', methods=['POST'])
def submit_pine_candidate():
    """Phase 10.5: 提交一段 Pine Script 進候選池。

    TradingView 沒有官方公開 API 又有嚴格反爬，務實做法是讓 user 在 TV
    複製腳本貼進來，後續走既有的 LLM translator pipeline 自動翻譯。

    Body: {raw_code, source_url, source_name, source_author?, timeframe?, category?}
    """
    from app.services.audit import log as audit
    import re

    data = request.get_json() or {}
    raw = (data.get('raw_code') or '').strip()
    if not raw:
        return jsonify({'error': '需要 raw_code（Pine Script 內容）'}), 400
    if len(raw) > 50_000:
        return jsonify({'error': 'raw_code 太長（>50KB），請刪減'}), 400

    # 基本格式檢查 — Pine 一定含這些關鍵字其中之一
    pine_markers = re.compile(r'//\s*@version=|indicator\s*\(|strategy\s*\(|study\s*\(', re.IGNORECASE)
    if not pine_markers.search(raw):
        return jsonify({'error': '看起來不是 Pine Script（找不到 //@version、indicator、strategy 或 study）'}), 400

    source_url = data.get('source_url') or ''
    if source_url and not source_url.startswith(('http://', 'https://')):
        return jsonify({'error': 'source_url 必須是 http(s) 開頭'}), 400

    c = StrategyCandidate(
        source='tradingview',
        source_url=source_url or None,
        source_name=data.get('source_name') or 'Pine 手動貼入',
        source_author=data.get('source_author'),
        source_meta={'submitted_via': 'manual_paste'},
        raw_code=raw,
        raw_lang='pine',
        category=data.get('category', 'swing'),
        timeframe=data.get('timeframe', '4h'),
        status='pending',
    )
    db.session.add(c)
    db.session.commit()

    audit('candidate_pine_submitted',
          actor='user',
          candidate_id=c.id,
          source_url=source_url,
          source_name=c.source_name,
          length=len(raw))

    return jsonify({
        'id': c.id,
        'status': c.status,
        'message': '已收入候選池（status=pending）。下一輪 LLM 翻譯（host cron 02:30 或 /api/candidates/<id>/translate）會把它變成可回測的 Python signal。',
    }), 201


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
@require_actor
def promote_candidate(cid):
    """把 qualified candidate 推上線 — 建立 strategies 條目並註冊 signal_fn。
    Body 可選：{ "name": "...", "symbol": "BTC/USDT" }

    Phase 11.1.3: 新策略 owner = 當前 user (admin 預設 user_id=1)。
    """
    from app.services.candidate_pipeline import promote_candidate as do_promote
    from app.services.audit import log as audit
    data = request.get_json() or {}
    owner = current_user_id() or 1
    result = do_promote(cid, name=data.get('name'), symbol=data.get('symbol', 'BTC/USDT'),
                        owner_user_id=owner)
    if result['ok']:
        audit('candidate_promote', actor='user', candidate_id=cid,
              strategy_id=result['strategy']['id'],
              strategy_type=result['strategy']['type'])
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


# ===== Phase 11.1: User 認證 =====

@api_bp.route('/auth/register', methods=['POST'])
def auth_register():
    """註冊新 user — email + password (>=8)。回傳 user + access_token"""
    from app.services.auth_user import register_user
    data = request.get_json(silent=True) or {}
    ok, payload = register_user(data.get('email', ''), data.get('password', ''))
    if not ok:
        return jsonify({'error': payload}), 400
    return jsonify(payload), 201


@api_bp.route('/auth/login', methods=['POST'])
def auth_login():
    """登入 — 回傳 user + access_token"""
    from app.services.auth_user import login_user
    data = request.get_json(silent=True) or {}
    ok, payload = login_user(data.get('email', ''), data.get('password', ''))
    if not ok:
        return jsonify({'error': payload}), 401
    return jsonify(payload), 200


@api_bp.route('/auth/me', methods=['GET'])
def auth_me():
    """回傳當前登入 user 資訊。system token 回 {is_system: True}；無鉴权回 401。"""
    from flask import g
    if getattr(g, 'is_system', False):
        return jsonify({'is_system': True, 'user': None}), 200
    user = getattr(g, 'current_user', None)
    if not user:
        return jsonify({'error': '未登入'}), 401
    return jsonify({'is_system': False, 'user': user.to_dict()}), 200


# ===== Phase 11.2.3: per-user OKX 綁定 =====

def _me_user_id():
    """me/* endpoint 通用：admin (system token) 也允許走，預設操作 user_id=1"""
    uid = current_user_id()
    if uid is None and is_admin_actor():
        return 1
    return uid


@api_bp.route('/me/okx', methods=['GET'])
@require_actor
def me_okx_get():
    """取當前 user 的 OKX 綁定狀態（masked，永不洩明文密鑰）"""
    from app.services.okx_creds import get_for_user
    uid = _me_user_id()
    # admin 走 env，回固定狀態
    if uid == 1:
        import os
        has_env = bool(os.environ.get('EXCHANGE_API_KEY'))
        return jsonify({
            'bound': has_env,
            'source': 'env',
            'note': 'admin 使用 .env 系統 OKX key（不可在 UI 改）',
        })
    rec = get_for_user(uid)
    if not rec:
        return jsonify({'bound': False, 'source': 'user'}), 200
    return jsonify({'bound': True, 'source': 'user', **rec.to_dict()}), 200


@api_bp.route('/me/okx', methods=['POST'])
@require_actor
def me_okx_bind():
    """綁定 / 更新 user OKX key。{api_key, secret, passphrase}"""
    from app.services.okx_creds import save_for_user
    from app.services.audit import log as audit
    uid = _me_user_id()
    if uid == 1:
        return jsonify({'error': 'admin 走 .env 系統 key，不在 UI 修改'}), 400
    data = request.get_json(silent=True) or {}
    ak = (data.get('api_key') or '').strip()
    sk = (data.get('secret') or '').strip()
    pp = (data.get('passphrase') or '').strip()
    if not (ak and sk and pp):
        return jsonify({'error': 'api_key / secret / passphrase 都必填'}), 400
    try:
        rec = save_for_user(uid, ak, sk, pp)
    except Exception as e:
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 500
    audit('okx_creds_saved', actor='user', user_id=uid)
    return jsonify({'bound': True, 'source': 'user', **rec.to_dict()}), 201


@api_bp.route('/me/okx/test', methods=['POST'])
@require_actor
def me_okx_test():
    """拉 OKX /account/balance 驗證 user 綁定的 key 有效"""
    from app.services.okx_creds import verify_against_okx
    uid = _me_user_id()
    if uid == 1:
        # admin 直接拉 env 餘額作測試
        from app.services.exchange_service import fetch_balance
        try:
            bal = fetch_balance()
            total = sum(v.get('total', 0) for v in bal.values())
            return jsonify({'ok': True, 'total_equity_usd': round(total, 4), 'source': 'env'})
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)}), 500
    return jsonify(verify_against_okx(uid))


@api_bp.route('/me/okx', methods=['PATCH'])
@require_actor
def me_okx_patch():
    """啟用 / 停用 user OKX（is_active boolean）"""
    from app.services.okx_creds import set_active
    from app.services.audit import log as audit
    uid = _me_user_id()
    if uid == 1:
        return jsonify({'error': 'admin 走 .env 系統 key，無法在 UI 停用'}), 400
    data = request.get_json(silent=True) or {}
    if 'is_active' not in data:
        return jsonify({'error': '需要 is_active boolean'}), 400
    rec = set_active(uid, bool(data['is_active']))
    if not rec:
        return jsonify({'error': '尚未綁定 OKX'}), 404
    audit('okx_creds_toggled', actor='user', user_id=uid, is_active=bool(data['is_active']))
    return jsonify({'bound': True, 'source': 'user', **rec.to_dict()}), 200


@api_bp.route('/me/okx', methods=['DELETE'])
@require_actor
def me_okx_delete():
    """解綁 user OKX key"""
    from app.services.okx_creds import delete_for_user
    from app.services.audit import log as audit
    uid = _me_user_id()
    if uid == 1:
        return jsonify({'error': 'admin 不能解綁 .env 系統 key'}), 400
    ok = delete_for_user(uid)
    if not ok:
        return jsonify({'error': '尚未綁定 OKX'}), 404
    audit('okx_creds_deleted', actor='user', user_id=uid)
    return jsonify({'bound': False, 'source': 'user'}), 200


# ===== Phase 11.5.1: per-user BYO LLM key =====

@api_bp.route('/me/llm', methods=['GET'])
@require_actor
def me_llm_list():
    """列出當前 user 綁的所有 LLM provider (masked)"""
    from app.services.llm_creds import list_for_user, VALID_PROVIDERS
    uid = _me_user_id()
    items = list_for_user(uid, only_active=False)
    bound = {r.provider: r.to_dict() for r in items}
    return jsonify({
        'providers': sorted(VALID_PROVIDERS),
        'bound': bound,
    })


@api_bp.route('/me/llm/<provider>', methods=['POST'])
@require_actor
def me_llm_bind(provider):
    """綁定 / 更新 user 某 provider 的 LLM key。{api_key, default_model?, priority?}"""
    from app.services.llm_creds import save_for_user
    from app.services.audit import log as audit
    uid = _me_user_id()
    data = request.get_json(silent=True) or {}
    api_key = (data.get('api_key') or '').strip()
    if not api_key:
        return jsonify({'error': 'api_key 必填'}), 400
    try:
        rec = save_for_user(uid, provider, api_key,
                            default_model=data.get('default_model'),
                            priority=int(data.get('priority', 100)))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 500
    audit('llm_creds_saved', actor='user', user_id=uid, provider=rec.provider)
    return jsonify(rec.to_dict()), 201


@api_bp.route('/me/llm/<provider>/test', methods=['POST'])
@require_actor
def me_llm_test(provider):
    """調 provider 的 ping 端點驗證 key"""
    from app.services.llm_creds import verify
    uid = _me_user_id()
    return jsonify(verify(uid, provider))


@api_bp.route('/me/llm/<provider>', methods=['PATCH'])
@require_actor
def me_llm_patch(provider):
    """更新 is_active / priority / default_model"""
    from app.services.llm_creds import get_for_user, set_active, set_priority
    from app.services.audit import log as audit
    uid = _me_user_id()
    data = request.get_json(silent=True) or {}
    rec = get_for_user(uid, provider)
    if not rec:
        return jsonify({'error': '尚未綁定該 provider'}), 404
    if 'is_active' in data:
        set_active(uid, provider, bool(data['is_active']))
    if 'priority' in data:
        set_priority(uid, provider, int(data['priority']))
    if 'default_model' in data:
        rec = get_for_user(uid, provider)
        rec.default_model = data['default_model']
        db.session.commit()
    audit('llm_creds_patched', actor='user', user_id=uid, provider=provider, fields=list(data.keys()))
    return jsonify(get_for_user(uid, provider).to_dict())


@api_bp.route('/me/llm/<provider>', methods=['DELETE'])
@require_actor
def me_llm_delete(provider):
    """解綁某 provider"""
    from app.services.llm_creds import delete_for_user
    from app.services.audit import log as audit
    uid = _me_user_id()
    ok = delete_for_user(uid, provider)
    if not ok:
        return jsonify({'error': '尚未綁定該 provider'}), 404
    audit('llm_creds_deleted', actor='user', user_id=uid, provider=provider)
    return jsonify({'ok': True})


