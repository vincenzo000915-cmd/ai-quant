from flask import Blueprint, abort, jsonify, request
from app.extensions import db
from app.models import Strategy, Order, Position, Trade, Candle, BacktestResult, StrategyCandidate, ParamOptimization, AuditLog
from app.services.rate_limit import rate_limit
from app.services.cache import cached_response
from app.services.user_scope import (
    apply_user_filter, assign_user_id, current_user_id, get_owned,
    has_ai_access, is_admin_actor, require_actor, require_admin, require_pro_tier,
    require_tier, scoped_query,
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
@require_tier('basic')
def create_strategy():
    data = request.get_json()
    strategy = Strategy(
        name=data['name'],
        type=data['type'],
        category=data.get('category', 'swing'),
        params=data.get('params', {}),
        symbol=data.get('symbol', 'BTC/USDT'),
        timeframe=data.get('timeframe', '4h'),
        exchange=(data.get('exchange') or 'okx').lower(),     # Phase 14k
        max_positions=data.get('max_positions', 1),
        max_daily_loss=data.get('max_daily_loss', 10.0),
    )
    assign_user_id(strategy)
    db.session.add(strategy)
    db.session.commit()
    return jsonify(strategy.to_dict()), 201


@api_bp.route('/strategies/<int:id>', methods=['PUT'])
@require_tier('basic')
def update_strategy(id):
    strategy = _owned_strategy(id)
    data = request.get_json()
    for field in ['name', 'type', 'category', 'params', 'symbol', 'timeframe',
                  'exchange', 'max_positions', 'max_daily_loss']:
        if field in data:
            setattr(strategy, field, data[field])
    db.session.commit()
    return jsonify(strategy.to_dict())


@api_bp.route('/strategies/<int:id>', methods=['DELETE'])
@require_tier('basic')
def delete_strategy(id):
    strategy = _owned_strategy(id)
    db.session.delete(strategy)
    db.session.commit()
    return jsonify({'message': 'deleted'})


@api_bp.route('/strategies/<int:id>/start', methods=['POST'])
@require_tier('basic')
def start_strategy(id):
    strategy = _owned_strategy(id)
    strategy.status = 'running'
    db.session.commit()
    # 立即觸發一次信號計算
    run_strategy_signals.delay(strategy.id)
    return jsonify(strategy.to_dict())


@api_bp.route('/strategies/<int:id>/stop', methods=['POST'])
@require_tier('basic')
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
@require_tier('basic')
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
@require_tier('basic')
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
@require_tier('basic')
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


@api_bp.route('/strategies/<int:id>/explain', methods=['POST'])
@require_actor
@require_pro_tier
def explain_strategy_route(id):
    """Phase 11.5.3: AI 解釋策略 — Pro 層獨享。

    回 {ok, text, model_used, provider_used, cached, usage, latency_ms, strategy_id, error?}
    """
    from app.services.llm_prompts.strategy_explain import explain_strategy
    s = _owned_strategy(id)
    r = explain_strategy(current_user_id() or 1, s.to_dict())
    r['strategy_id'] = id
    if not r.get('ok'):
        # 403 / 402 path 已被 decorator 處理；這裡是 LLM 自己失敗
        return jsonify(r), 502
    return jsonify(r)


@api_bp.route('/me/weekly-review', methods=['POST'])
@require_actor
@require_pro_tier
def ai_weekly_review():
    """Phase 11.5.6: 過去 7 日復盤"""
    from app.services.llm_prompts.weekly_review import weekly_review
    r = weekly_review(current_user_id() or 1)
    if not r.get('ok'):
        return jsonify(r), 502
    return jsonify(r)


@api_bp.route('/me/personal-advice', methods=['POST'])
@require_actor
@require_pro_tier
def ai_personal_advice():
    """Phase 11.5.7: 個性化建議"""
    from app.services.llm_prompts.personal_advice import personal_advice
    from app.services.exchange_service import fetch_balance, _resolve_creds
    uid = current_user_id() or 1
    # 拉 account info
    try:
        creds = None if is_admin_actor() else _resolve_creds(uid)
        balances = fetch_balance(creds=creds) if (is_admin_actor() or creds) else {}
        usd_total = sum(v.get('total', 0) for v in balances.values())
        free_usdt = balances.get('USDT', {}).get('free', 0)
        account_info = {'balance': usd_total, 'free_margin': free_usdt, 'unrealized_pnl': 0}
    except Exception:
        account_info = {'balance': 0, 'free_margin': 0, 'unrealized_pnl': 0}
    r = personal_advice(uid, account_info)
    if not r.get('ok'):
        return jsonify(r), 502
    return jsonify(r)


@api_bp.route('/me/improve-strategies', methods=['POST'])
@require_actor
@require_pro_tier
def ai_improve_strategies():
    """Phase 14: catalog-first AI 推荐 — 从 vetted catalog 选 fit user 的策略 (取代 v8 invent)
    v8 invent 仅 full_auto 模式 + 高门槛时辅助调用 (14d 待实施)
    """
    from app.services.llm_prompts.strategy_recommend import recommend_strategies
    from app.services.audit import log as audit
    uid = current_user_id() or 1
    r = recommend_strategies(uid, max_recommend=3)
    if not r.get('ok'):
        return jsonify(r), 502
    recs = r.get('recommendations', [])
    auto_count = sum(1 for x in recs if (x.get('auto_apply') or {}).get('applied'))
    audit('strategy_ai_improve', actor='user',
          recommended=len(recs),
          auto_applied=auto_count,
          mode=r.get('mode'))
    return jsonify(r), 201


@api_bp.route('/me/recommendation-explain', methods=['POST'])
@require_actor
@require_pro_tier
def ai_recommendation_explain():
    """Phase 14h: 单条 catalog clone candidate → LLM 中文解释 + 风险提示
    Body: { "clone_id": 123 }
    返回: { ok, explanation, risk_warning, source: 'llm'|'cache'|'rule_based', cached? }
    用 cache (12h) 避免重复 LLM 调用; LLM 失败 → fallback 到 catalog_meta.description.
    """
    from app.services.llm_prompts.strategy_recommend import explain_recommendation
    uid = current_user_id() or 1
    payload = request.get_json(silent=True) or {}
    clone_id = payload.get('clone_id')
    if not clone_id:
        return jsonify({'ok': False, 'error': 'missing clone_id'}), 400
    try:
        cid = int(clone_id)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'invalid clone_id'}), 400
    r = explain_recommendation(uid, cid)
    code = 200 if r.get('ok') else 502
    return jsonify(r), code


@api_bp.route('/me/sizing-advice', methods=['POST'])
@require_actor
@require_pro_tier
def ai_sizing_advice():
    """Phase 11.5.12: AI 推荐仓位/杠杆/SL/TP 一键 apply 准备"""
    from app.services.llm_prompts.sizing_advisor import recommend_sizing
    from app.services.exchange_service import fetch_balance, _resolve_creds
    uid = current_user_id() or 1
    try:
        creds = None if is_admin_actor() else _resolve_creds(uid)
        balances = fetch_balance(creds=creds) if (is_admin_actor() or creds) else {}
        usd_total = sum(v.get('total', 0) for v in balances.values())
        free_usdt = balances.get('USDT', {}).get('free', 0)
        account_info = {'balance': usd_total, 'free_margin': free_usdt, 'unrealized_pnl': 0}
    except Exception:
        account_info = {'balance': 0, 'free_margin': 0, 'unrealized_pnl': 0}
    r = recommend_sizing(uid, account_info)
    if not r.get('ok'):
        return jsonify(r), 502
    return jsonify(r)


@api_bp.route('/me/diagnose', methods=['POST'])
@require_actor
@require_pro_tier
def ai_diagnose():
    """Phase 11.5.8: 故障診斷 agent"""
    from app.services.llm_prompts.diagnose import diagnose
    r = diagnose(current_user_id() or 1)
    if not r.get('ok'):
        return jsonify(r), 502
    return jsonify(r)


@api_bp.route('/regime/ai-explain', methods=['POST'])
@require_actor
@require_pro_tier
def ai_explain_regime():
    """Phase 11.5.5: AI 解讀當前 regime"""
    from app.services.llm_prompts.regime_explain import explain_regime
    from app.services.regime_detector import detect_regime, affinity_for, fit_label
    # 拉當前 user 的 running 策略 regime（複用 /regime/running 邏輯但 inline）
    running = scoped_query(Strategy).filter(Strategy.status == 'running').all()
    unique = sorted({(s.symbol, s.timeframe) for s in running})
    regimes = {}
    for sym, tf in unique:
        regimes[f'{sym}@{tf}'] = detect_regime(sym, tf)
    per_strategy = []
    for s in running:
        r = regimes.get(f'{s.symbol}@{s.timeframe}', {})
        per_strategy.append({
            'strategy_id': s.id, 'name': s.name, 'type': s.type,
            'symbol': s.symbol, 'timeframe': s.timeframe,
            'affinity': affinity_for(s.type),
            'regime': r.get('regime'),
            'fit': fit_label(s.type, r.get('regime', 'unknown')),
        })
    regime_data = {'regimes': regimes, 'per_strategy': per_strategy}
    r = explain_regime(current_user_id() or 1, regime_data)
    if not r.get('ok'):
        return jsonify(r), 502
    return jsonify(r)


@api_bp.route('/strategies/ai-generate', methods=['POST'])
@require_actor
@require_pro_tier
def ai_generate_strategy():
    """Phase 11.5.4: AI 生成策略 — Pro 層獨享。

    Body: {"description": "用 RSI 反向 + 布林帶擠壓的短線多策略"}
    回 {ok, candidate_id, candidate, verify, llm_meta, error?}
    """
    from app.services.llm_prompts.strategy_generate import generate_strategy
    from app.services.audit import log as audit
    data = request.get_json(silent=True) or {}
    description = (data.get('description') or '').strip()
    if not description:
        return jsonify({'ok': False, 'error': '需要 description 字段'}), 400
    r = generate_strategy(current_user_id() or 1, description)
    if not r.get('ok'):
        return jsonify(r), 502
    audit('strategy_ai_generated', actor='user',
          candidate_id=r['candidate_id'], description_len=len(description),
          provider=r.get('llm_meta', {}).get('provider_used'))
    return jsonify(r), 201


@api_bp.route('/strategies/<int:id>/retire', methods=['POST'])
@rate_limit('20/min')
@require_tier('basic')
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
@require_tier('basic')
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
    """每個策略的真實表現統計（trades 表 + positions 表 + 最新 backtest）

    Phase 14i: ?include=live_card 时额外返回 running 策略 selling-point 数据:
      equity_curve_30d (累计 pnl 序列 max 30 点),
      open_position_detail (entry/current/SL/TP/距离%/浮盈%)
    """
    from sqlalchemy import func
    include_live = (request.args.get('include') == 'live_card')

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

        row = {
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
        }

        # Phase 14i: live_card 数据 — 仅 running 策略需要
        if include_live and s.status == 'running':
            # 30 天 trades → 累计 pnl curve
            import datetime as _dt
            cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=30)
            recent_trades = db.session.query(Trade.exit_time, Trade.pnl).filter(
                Trade.strategy_id == s.id,
                Trade.exit_time != None,           # noqa: E711
                Trade.exit_time > cutoff,
            ).order_by(Trade.exit_time.asc()).all()
            cum = 0.0
            curve = []
            for et, pnl in recent_trades:
                cum += float(pnl or 0)
                curve.append({'ts': et.isoformat(), 'cum_pnl': round(cum, 4)})
            # 下采样到 max 30 点 (取等距)
            if len(curve) > 30:
                step = len(curve) // 30
                curve = curve[::max(step, 1)][-30:]
            row['equity_curve_30d'] = curve
            row['trades_30d'] = len(recent_trades)

            # 持仓详情
            if open_pos:
                entry = float(open_pos.entry_price or 0)
                cur = float(open_pos.current_price or 0)
                sl = float(open_pos.sl_price or 0)
                tp = float(open_pos.tp_price or 0)
                side = (open_pos.side or '').lower()
                size = float(open_pos.size or 0)
                # 距离 % (相对当前价)
                dist_sl_pct = None
                dist_tp_pct = None
                if cur > 0 and sl > 0:
                    dist_sl_pct = round((cur - sl) / cur * 100, 2) if side == 'long' else round((sl - cur) / cur * 100, 2)
                if cur > 0 and tp > 0:
                    dist_tp_pct = round((tp - cur) / cur * 100, 2) if side == 'long' else round((cur - tp) / cur * 100, 2)
                # 浮盈 %
                unreal_pct = None
                if entry > 0:
                    if side == 'long':
                        unreal_pct = round((cur - entry) / entry * 100, 2)
                    elif side == 'short':
                        unreal_pct = round((entry - cur) / entry * 100, 2)
                row['open_position_detail'] = {
                    'side': side,
                    'size': size,
                    'entry_price': entry,
                    'current_price': cur,
                    'sl_price': sl or None,
                    'tp_price': tp or None,
                    'dist_to_sl_pct': dist_sl_pct,
                    'dist_to_tp_pct': dist_tp_pct,
                    'unrealized_pnl_usd': round(float(open_pos.unrealized_pnl or 0), 2),
                    'unrealized_pnl_pct': unreal_pct,
                    'opened_at': open_pos.opened_at.isoformat() if open_pos.opened_at else None,
                }

        result.append(row)

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
@require_tier('basic')
def reconcile_now():
    """Phase 8.2: 立即跑一次 OKX/local 對賬"""
    from app.services.reconciliation import reconcile
    return jsonify(reconcile())


@api_bp.route('/anomaly/check', methods=['POST'])
@require_tier('basic')
def anomaly_check_now():
    """Phase 6.4: 立即跑 anomaly detector"""
    from app.services.anomaly_detector import run_all_checks
    return jsonify(run_all_checks())


@api_bp.route('/killswitch', methods=['POST'])
@rate_limit('5/min')
@require_tier('basic')
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
@require_tier('basic')
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
@require_admin
def list_audit():
    """Phase 8.4 / 12.44: 查 audit log（admin-only — 跨 user 系统数据）。?type=halt&limit=100"""
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
    # Phase 14c: ai_decision_mode tier guard
    mode_changed_to_auto = False
    if 'ai_decision_mode' in patch:
        mode = patch['ai_decision_mode']
        if mode not in ('manual', 'semi_auto', 'full_auto'):
            return jsonify({'error': f'ai_decision_mode 必须是 manual / semi_auto / full_auto'}), 400
        # Basic tier 只能 manual; Pro/admin 可以选所有
        if mode != 'manual' and not has_ai_access():
            return jsonify({
                'error': f'mode {mode} 需 Pro 订阅 (Basic 仅 manual)',
                'tier_required': 'pro',
                'upgrade_hint': '/pricing',
            }), 402
        # Phase 14c.1: 切到 semi_auto/full_auto 时立即触发 recommend (不等 cron)
        from app.services.config_service import get
        prev_mode = get('ai_decision_mode', 'manual')
        if prev_mode == 'manual' and mode in ('semi_auto', 'full_auto'):
            mode_changed_to_auto = True

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

    # Phase 14c.1: 切到 semi_auto/full_auto 时立即触发 recommend (异步)
    if mode_changed_to_auto:
        try:
            from app.tasks.strategy_tasks import auto_ai_improve_strategies
            auto_ai_improve_strategies.delay()
            new_cfg['_recommend_triggered'] = True
        except Exception:
            pass

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
@require_tier('basic')
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
@require_tier('basic')
def delete_candidate(cid):
    c = StrategyCandidate.query.get_or_404(cid)
    db.session.delete(c)
    db.session.commit()
    return jsonify({'message': 'deleted'})


@api_bp.route('/candidates/<int:cid>/reject', methods=['POST'])
@require_tier('basic')
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
@require_tier('basic')
def backtest_pending_candidates():
    """批次跑所有 status='translated' 的候選回測（同步、慢）。可選 ?max=N 限制數量。"""
    from app.services.candidate_pipeline import backtest_all_translated
    max_count = request.args.get('max', type=int)
    return jsonify(backtest_all_translated(max_count=max_count))


@api_bp.route('/candidates/<int:cid>/translate', methods=['POST'])
@require_actor
@require_tier('basic')
def translate_candidate(cid):
    """Phase 11.5.9: 跑 LLM 翻譯 + 沙箱驗證。同步，慢（~5-30s/candidate）。

    admin 走 claude_cli (訂閱免費)、user 走自己 BYO API key。
    Host cron (translate_pending_cron.sh) 仍走 env ANTHROPIC_API_KEY (legacy)。
    """
    from app.services.candidate_pipeline import translate_and_verify
    result = translate_and_verify(cid, user_id=current_user_id() or 1)
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
@require_tier('basic')
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


# ===== Phase 12.42 v8: AI Insights panel endpoints =====

@api_bp.route('/candidates/ai-picks', methods=['GET'])
@require_actor
@require_pro_tier
def candidates_ai_picks():
    """List AI-recommended qualified candidates pending user review.
    Phase 14: 排除 catalog 模板自身（source='catalog'），只显示 clone + AI improve 输出
    """
    rows = StrategyCandidate.query.filter(
        StrategyCandidate.status == 'qualified',
        StrategyCandidate.promoted_strategy_id.is_(None),
        StrategyCandidate.source != 'catalog',     # 排除 catalog 模板
    ).order_by(StrategyCandidate.created_at.desc()).limit(20).all()

    out = []
    for c in rows:
        meta = c.source_meta or {}
        cat_meta = c.catalog_meta or {}
        bt = None
        if c.backtest_result_id:
            from app.models import BacktestResult
            bt = BacktestResult.query.get(c.backtest_result_id)
        wf = (bt.walkforward_json or {}) if bt else {}
        oos = wf.get('out_sample') or {}

        # Phase 14: catalog clone 用 verified_sharpe (没 actual backtest)
        # AI improve 输出 用 actual oos
        is_catalog_clone = c.source == 'catalog_clone'
        if is_catalog_clone:
            metrics = {
                'oos_sharpe': cat_meta.get('verified_oos_sharpe'),
                'oos_profit_factor': cat_meta.get('verified_pf'),
                'oos_total_trades': None,
                'oos_win_rate': None,
                'oos_annual_return_pct': None,
                'oos_max_drawdown_pct': None,
                'decay_pct': None,
                'source_label': 'vetted catalog',
            }
            risk = cat_meta.get('recommended_risk') or meta.get('risk_params') or {}
        else:
            metrics = {
                'oos_sharpe': oos.get('sharpe_ratio'),
                'oos_profit_factor': oos.get('profit_factor'),
                'oos_total_trades': oos.get('total_trades'),
                'oos_win_rate': oos.get('win_rate'),
                'oos_annual_return_pct': oos.get('annual_return_pct'),
                'oos_max_drawdown_pct': oos.get('max_drawdown_pct'),
                'decay_pct': wf.get('decay_pct'),
                'source_label': 'AI invented',
            }
            risk = meta.get('risk_params') or {}

        out.append({
            'id': c.id,
            'candidate_type': c.candidate_type,
            'signal_fn_name': c.signal_fn_name,
            'symbol': meta.get('symbol') or (bt.symbol if bt else None),
            'timeframe': c.timeframe,
            'category': c.category,
            'source': c.source,
            'source_name': c.source_name,
            'created_at': c.created_at.isoformat() if c.created_at else None,
            'rationale': meta.get('rationale') or cat_meta.get('description'),
            'description': cat_meta.get('description'),
            'citation': cat_meta.get('citation'),
            'ideal_regimes': cat_meta.get('ideal_regimes'),
            'avoid_when': cat_meta.get('avoid_when'),
            'external_source': meta.get('external_source'),
            'internal_ref': meta.get('internal_ref'),
            'analysis': meta.get('analysis'),
            'external_research_summary': (meta.get('external_research_summary') or '')[:600],
            'risk_params': risk,
            'self_estimate': meta.get('self_estimate') or {},
            'metrics': metrics,
            'trade_patterns': meta.get('trade_patterns') or {},
        })
    return jsonify({'count': len(out), 'items': out})


@api_bp.route('/candidates/<int:cid>/promote-and-start', methods=['POST'])
@require_actor
@require_tier('basic')
def candidate_promote_and_start(cid):
    """One-click promote + start running.

    Body optional: {
      "risk_params": {"leverage": 5, "stop_loss_pct": 6, "take_profit_pct": 12, "position_size_usdt": 6},
      "name": "...", "symbol": "BTC/USDT"
    }
    若不传 risk_params，使用 candidate.source_meta.risk_params (AI 推荐)
    """
    from app.services.candidate_pipeline import promote_candidate as do_promote
    from app.services.audit import log as audit

    c = StrategyCandidate.query.get_or_404(cid)
    if c.status != 'qualified':
        return jsonify({'ok': False, 'error': f'candidate {cid} status={c.status} (need qualified)'}), 400
    if c.promoted_strategy_id:
        return jsonify({'ok': False, 'error': f'candidate {cid} already promoted to strategy {c.promoted_strategy_id}'}), 400

    data = request.get_json() or {}
    meta = c.source_meta or {}
    ai_risk = meta.get('risk_params') or {}
    user_risk = data.get('risk_params') or {}
    # final risk = user override > AI推荐 > 缺省
    final_risk = {**ai_risk, **user_risk}
    # Phase 13: order_type 透传
    if 'order_type' not in final_risk:
        final_risk['order_type'] = 'market'

    # Symbol 优先级: body > AI meta > candidate
    symbol = data.get('symbol') or meta.get('symbol') or 'BTC/USDT'
    owner = current_user_id() or 1

    # 1. Promote (create Strategy in stopped state)
    result = do_promote(cid, name=data.get('name'), symbol=symbol, owner_user_id=owner)
    if not result.get('ok'):
        err = result.get('error', '')
        code = 400 if any(kw in err for kw in ('not found', 'must be qualified', 'already exists', 'missing')) else 500
        return jsonify(result), code

    new_sid = result['strategy']['id']

    # 2. Write risk_params 进 strategy.params['risk_params']
    s = Strategy.query.get(new_sid)
    if s and final_risk:
        # 写入 params jsonb (schema-less polymorphism)
        p = dict(s.params or {})
        p['risk_params'] = {
            k: v for k, v in {
                'leverage': final_risk.get('leverage'),
                'stop_loss_pct': final_risk.get('stop_loss_pct'),
                'take_profit_pct': final_risk.get('take_profit_pct'),
                'position_size_usdt': final_risk.get('position_size_usdt'),
                'order_type': final_risk.get('order_type'),    # Phase 13
                'reasoning': final_risk.get('reasoning'),
            }.items() if v is not None
        }
        s.params = p

    # 3. Set running + trigger signal cycle
    if s:
        s.status = 'running'
        db.session.commit()
        try:
            run_strategy_signals.delay(s.id)
        except Exception:
            pass

    audit('candidate_promote_and_start', actor='user', candidate_id=cid,
          strategy_id=new_sid, risk_params=final_risk, symbol=symbol)

    try:
        from app.services.telegram_service import send as _tg
        m = result.get('strategy', {})
        _tg(
            f'🚀 <b>用户从 AI 洞察一键上架</b>\n'
            f'策略 #{new_sid} {m.get("name", "?")}\n'
            f'symbol={symbol} 杠杆={final_risk.get("leverage", "default")}x SL={final_risk.get("stop_loss_pct", "default")}% TP={final_risk.get("take_profit_pct", "default")}%\n'
            f'已 status=running，即时纳入信号循环。'
        )
    except Exception:
        pass

    return jsonify({
        'ok': True,
        'strategy': {**result['strategy'], 'risk_params': final_risk},
    }), 201


@api_bp.route('/candidates/<int:cid>/dismiss', methods=['POST'])
@require_actor
@require_tier('basic')
def candidate_dismiss(cid):
    """Reject AI pick — 不删，标 status='rejected'。同 /reject 但路径明确给 UI 用"""
    c = StrategyCandidate.query.get_or_404(cid)
    c.status = 'rejected'
    data = request.get_json() or {}
    if data.get('reason'):
        c.llm_notes = (c.llm_notes or '') + f'\n[user dismissed] {data["reason"]}'
    db.session.commit()
    return jsonify({'ok': True, 'id': cid, 'status': c.status})


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


# ===== Phase 14k: per-user Hyperliquid agent wallet =====

@api_bp.route('/me/hyperliquid', methods=['GET'])
@require_actor
def me_hl_get():
    """取当前 user 的 HL agent 绑定状态 (无私钥)"""
    from app.services.hyperliquid_creds import get_for_user
    uid = _me_user_id()
    rec = get_for_user(uid)
    if not rec:
        return jsonify({'bound': False}), 200
    return jsonify({'bound': True, **rec.to_dict()}), 200


@api_bp.route('/me/hyperliquid', methods=['POST'])
@require_actor
def me_hl_bind():
    """绑定 / 更新 HL agent. {agent_address, main_address, agent_private_key, network='mainnet'|'testnet'}"""
    from app.services.hyperliquid_creds import save_for_user
    from app.services.audit import log as audit
    uid = _me_user_id()
    data = request.get_json(silent=True) or {}
    try:
        rec = save_for_user(
            uid,
            agent_address=data.get('agent_address') or '',
            main_address=data.get('main_address') or '',
            agent_private_key=data.get('agent_private_key') or '',
            network=data.get('network') or 'mainnet',
        )
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 500
    audit('hl_creds_saved', actor='user', user_id=uid,
          agent_address=rec.agent_address, main_address=rec.main_address, network=rec.network)
    return jsonify({'bound': True, **rec.to_dict()}), 201


@api_bp.route('/me/hyperliquid/test', methods=['POST'])
@require_actor
def me_hl_test():
    """调 HL info endpoint 验证 main_address + 回 balance"""
    from app.services.hyperliquid_creds import verify_against_hl
    uid = _me_user_id()
    return jsonify(verify_against_hl(uid))


@api_bp.route('/me/hyperliquid', methods=['PATCH'])
@require_actor
def me_hl_patch():
    """启停 HL agent (is_active boolean)"""
    from app.services.hyperliquid_creds import set_active
    from app.services.audit import log as audit
    uid = _me_user_id()
    data = request.get_json(silent=True) or {}
    if 'is_active' not in data:
        return jsonify({'error': '需要 is_active boolean'}), 400
    rec = set_active(uid, bool(data['is_active']))
    if not rec:
        return jsonify({'error': '尚未绑定 HL'}), 404
    audit('hl_creds_toggled', actor='user', user_id=uid, is_active=bool(data['is_active']))
    return jsonify({'bound': True, **rec.to_dict()}), 200


@api_bp.route('/me/hyperliquid', methods=['DELETE'])
@require_actor
def me_hl_delete():
    """解绑 HL agent"""
    from app.services.hyperliquid_creds import delete_for_user
    from app.services.audit import log as audit
    uid = _me_user_id()
    ok = delete_for_user(uid)
    if not ok:
        return jsonify({'error': '尚未绑定 HL'}), 404
    audit('hl_creds_deleted', actor='user', user_id=uid)
    return jsonify({'bound': False}), 200


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




# ============================================================
# Phase 12.24: USDT 订阅 + 链上付款 endpoints
# ============================================================

@api_bp.route('/billing/chains', methods=['GET'])
def billing_chains():
    """列支持的 USDT 链（用于 Checkout 页选链）"""
    from app.services.subscription_service import get_chain_addresses, PLAN_PRICES, DISCOUNT_MAP
    return jsonify({
        'chains': get_chain_addresses(),
        'plans': {k: float(v) for k, v in PLAN_PRICES.items()},
        'discounts': DISCOUNT_MAP,
        'invoice_ttl_minutes': 30,
    })


@api_bp.route('/billing/invoice', methods=['POST'])
@require_actor
def billing_create_invoice():
    """创建 USDT 付款 invoice。POST {plan, months, chain}"""
    from app.services.subscription_service import create_invoice
    from app.services.audit import log as audit
    uid = _me_user_id()
    data = request.get_json(silent=True) or {}
    plan = data.get('plan')
    months = int(data.get('months', 1))
    chain = data.get('chain', 'trc20')
    r = create_invoice(uid, plan, months, chain)
    if not r.get('ok'):
        return jsonify({'error': r.get('error')}), 400
    audit('invoice_created', actor='user', user_id=uid,
          plan=plan, months=months, chain=chain,
          invoice_id=r['invoice']['id'], amount_due=r['invoice']['amount_due'])
    return jsonify(r['invoice'])


@api_bp.route('/billing/invoice/<int:invoice_id>', methods=['GET'])
@require_actor
def billing_get_invoice(invoice_id):
    """查询单个 invoice — 仅本人或 admin 可看"""
    from app.services.subscription_service import get_invoice
    from app.models import User
    uid = _me_user_id()
    user = User.query.get(uid)
    inv = get_invoice(invoice_id, user_id=None if user and user.role == 'admin' else uid)
    if not inv:
        return jsonify({'error': 'not found'}), 404
    return jsonify(inv)


@api_bp.route('/billing/invoice/<int:invoice_id>/submit-tx', methods=['POST'])
@require_actor
def billing_submit_tx(invoice_id):
    """Phase 12.24.4: 备用通道全自动 — 用户上传 tx hash 立即链上验证 → 自动 confirm

    流程：
    1. 验证 tx 存在 + 是 USDT transfer + to == invoice.address
    2. 比对 amount（容差 0.000002 USDT dust）
    3. 全部 ok → 自动 confirm + 开通订阅
    4. 任一不符 → reject 并返回具体原因（user 自查，不走人工审核）
    """
    import decimal
    from app.models import PaymentInvoice
    from app.services.audit import log as audit
    from app.services.onchain_monitor import verify_tx_hash
    from app.services.subscription_service import activate_subscription_from_invoice

    uid = _me_user_id()
    data = request.get_json(silent=True) or {}
    tx_hash = (data.get('tx_hash') or '').strip()
    if not tx_hash:
        return jsonify({'error': '请提供 tx_hash'}), 400

    inv = PaymentInvoice.query.filter_by(id=invoice_id, user_id=uid).first()
    if not inv:
        return jsonify({'error': 'invoice 不存在或不属于你'}), 404
    if inv.status != 'pending':
        return jsonify({'error': f'invoice 当前状态 {inv.status}，无法验证'}), 400

    # 防重：同 tx_hash 已被其他 invoice 用过 → 拒
    dup = PaymentInvoice.query.filter(
        PaymentInvoice.tx_hash == tx_hash,
        PaymentInvoice.id != invoice_id,
    ).first()
    if dup:
        return jsonify({'ok': False, 'error': '此 tx hash 已被其他订单使用'}), 400

    # 链上验证
    verify = verify_tx_hash(inv.chain, tx_hash)
    if not verify.get('ok'):
        audit('invoice_tx_verify_failed', actor='user', user_id=uid,
              invoice_id=invoice_id, tx_hash=tx_hash, error=verify.get('error'))
        return jsonify({'ok': False, 'error': verify.get('error'),
                        'hint': '请确认 tx hash 正确 + 链上已确认 + 是 USDT 转账'}), 400

    # 检查 to address (case insensitive for EVM)
    if inv.chain in ('erc20', 'bep20'):
        expected_to = (inv.address or '').lower()
        actual_to = (verify.get('to') or '').lower()
    else:
        expected_to = inv.address
        actual_to = verify.get('to')
    if actual_to != expected_to:
        audit('invoice_tx_verify_failed', actor='user', user_id=uid,
              invoice_id=invoice_id, tx_hash=tx_hash,
              error=f'to address 不匹配 actual={actual_to}')
        return jsonify({
            'ok': False,
            'error': f'tx 收款地址不匹配 — 链上收款方是 {verify.get("to")}，不是我们的 {inv.address}',
            'hint': '请确认是付给本订单显示的地址；不要复用其他订单的 tx',
        }), 400

    # 检查金额（容差 0.000002 USDT — 2 个 dust）
    expected_amount = inv.amount_due
    actual_amount = verify.get('amount') or decimal.Decimal(0)
    diff = abs(actual_amount - expected_amount)
    tolerance = decimal.Decimal('0.000002')
    if diff > tolerance:
        audit('invoice_tx_verify_failed', actor='user', user_id=uid,
              invoice_id=invoice_id, tx_hash=tx_hash,
              error=f'amount 不匹配 expected={expected_amount} actual={actual_amount}')
        return jsonify({
            'ok': False,
            'error': f'金额不匹配 — 应付 {expected_amount} USDT，链上实际 {actual_amount} USDT',
            'hint': '末尾 6 位 suffix 用于识别订单，请精确转账。如多付/少付请联系 sales@medias-ai.cloud',
            'expected_amount': float(expected_amount),
            'actual_amount': float(actual_amount),
        }), 400

    # 全部通过 → 自动 confirm
    inv.tx_hash = tx_hash
    inv.tx_from_address = verify.get('from')
    inv.tx_received_amount = actual_amount
    bn = verify.get('block_number') or verify.get('block_time')
    if bn:
        try: inv.tx_block_number = int(bn)
        except Exception: pass
    sub = activate_subscription_from_invoice(inv)
    audit('invoice_confirmed_by_tx_submit', actor='user', user_id=uid,
          invoice_id=invoice_id, tx_hash=tx_hash, plan=sub.plan,
          subscription_id=sub.id,
          expires_at=sub.expires_at.isoformat() if sub.expires_at else None)
    return jsonify({
        'ok': True,
        'invoice': inv.to_dict(),
        'subscription': sub.to_dict(),
        'message': '链上验证通过，订阅已开通',
    })


@api_bp.route('/me/subscription', methods=['GET'])
@require_actor
def me_subscription():
    """当前 user 的订阅状态"""
    from app.services.subscription_service import get_active_subscription, get_user_tier
    uid = _me_user_id()
    sub = get_active_subscription(uid)
    return jsonify({
        'tier': get_user_tier(uid),
        'subscription': sub.to_dict() if sub else None,
    })


# Admin 审核 pending_review invoices
@api_bp.route('/admin/invoices/review', methods=['GET'])
@require_actor
def admin_invoices_review_list():
    """admin: 列待人工审核的 invoices"""
    from app.models import PaymentInvoice, User
    user = User.query.get(_me_user_id())
    if not user or user.role != 'admin':
        return jsonify({'error': 'admin only'}), 403
    rows = PaymentInvoice.query.filter_by(status='pending_review').order_by(PaymentInvoice.id.desc()).all()
    return jsonify([r.to_dict() for r in rows])


@api_bp.route('/admin/invoices/<int:invoice_id>/approve', methods=['POST'])
@require_actor
def admin_invoice_approve(invoice_id):
    """admin: 手动批准 invoice → 开通订阅"""
    from app.models import PaymentInvoice, User
    from app.services.subscription_service import activate_subscription_from_invoice
    from app.services.audit import log as audit
    user = User.query.get(_me_user_id())
    if not user or user.role != 'admin':
        return jsonify({'error': 'admin only'}), 403
    inv = PaymentInvoice.query.get(invoice_id)
    if not inv:
        return jsonify({'error': 'not found'}), 404
    data = request.get_json(silent=True) or {}
    inv.review_note = data.get('note', 'manual approval by admin')
    sub = activate_subscription_from_invoice(inv)
    audit('invoice_admin_approved', actor='admin', user_id=user.id,
          invoice_id=invoice_id, target_user_id=inv.user_id,
          subscription_id=sub.id, plan=sub.plan)
    return jsonify({'ok': True, 'subscription': sub.to_dict()})


@api_bp.route('/admin/invoices/<int:invoice_id>/reject', methods=['POST'])
@require_actor
def admin_invoice_reject(invoice_id):
    """admin: 拒绝 invoice"""
    from app.models import PaymentInvoice, User
    from app.services.audit import log as audit
    user = User.query.get(_me_user_id())
    if not user or user.role != 'admin':
        return jsonify({'error': 'admin only'}), 403
    inv = PaymentInvoice.query.get(invoice_id)
    if not inv:
        return jsonify({'error': 'not found'}), 404
    data = request.get_json(silent=True) or {}
    inv.status = 'cancelled'
    inv.review_note = data.get('note', 'rejected by admin')
    db.session.commit()
    audit('invoice_admin_rejected', actor='admin', user_id=user.id,
          invoice_id=invoice_id, target_user_id=inv.user_id, note=inv.review_note)
    return jsonify({'ok': True})


@api_bp.route('/admin/billing/check-now', methods=['POST'])
@require_actor
def admin_billing_check_now():
    """admin: 手动触发一次链上 polling（不等 60s cron）"""
    from app.models import User
    from app.services.onchain_monitor import check_all_chains
    user = User.query.get(_me_user_id())
    if not user or user.role != 'admin':
        return jsonify({'error': 'admin only'}), 403
    results = check_all_chains()
    return jsonify({'ok': True, 'results': results})


@api_bp.route('/admin/indexnow/ping', methods=['POST'])
@require_actor
def admin_indexnow_ping():
    """admin: 手动通知 IndexNow Bing/Yandex 抓取所有公开页"""
    from app.models import User
    from app.services.indexnow import notify_urls
    user = User.query.get(_me_user_id())
    if not user or user.role != 'admin':
        return jsonify({'error': 'admin only'}), 403
    data = request.get_json(silent=True) or {}
    urls = data.get('urls')   # 可选：只推指定 URL；None = 推全
    r = notify_urls(urls)
    return jsonify(r)


# ============================================================
# Phase 14j: Admin 后台 API
# 仅 role='admin' 可访问 — require_admin 守
# ============================================================

from app.services.user_scope import require_admin   # noqa: E402


@api_bp.route('/admin/users', methods=['GET'])
@require_actor
@require_admin
def admin_users_list():
    """列出所有 user + 聚合 stats. Query: ?q=email_substring&limit=100"""
    from app.models import User
    from sqlalchemy import func

    q_str = (request.args.get('q') or '').strip()
    limit = int(request.args.get('limit') or 100)
    query = User.query
    if q_str:
        query = query.filter(User.email.ilike(f'%{q_str}%'))
    users = query.order_by(User.id.asc()).limit(limit).all()

    # 一次性聚合 stats (avoid N+1)
    user_ids = [u.id for u in users]
    if not user_ids:
        return jsonify({'users': [], 'total': 0})

    strat_count = dict(
        db.session.query(Strategy.user_id, func.count(Strategy.id))
        .filter(Strategy.user_id.in_(user_ids))
        .group_by(Strategy.user_id).all()
    )
    running_count = dict(
        db.session.query(Strategy.user_id, func.count(Strategy.id))
        .filter(Strategy.user_id.in_(user_ids), Strategy.status == 'running')
        .group_by(Strategy.user_id).all()
    )
    trade_stats = dict(
        ((row.user_id, (row.n, float(row.pnl or 0))) for row in
         db.session.query(
            Trade.user_id,
            func.count(Trade.id).label('n'),
            func.coalesce(func.sum(Trade.pnl), 0).label('pnl'),
         ).filter(Trade.user_id.in_(user_ids)).group_by(Trade.user_id).all())
    )

    from app.models import OkxCredentials, LlmCredentials
    okx_bound = set(
        r[0] for r in db.session.query(OkxCredentials.user_id)
        .filter(OkxCredentials.user_id.in_(user_ids)).distinct().all()
    )
    llm_bound = set(
        r[0] for r in db.session.query(LlmCredentials.user_id)
        .filter(LlmCredentials.user_id.in_(user_ids)).distinct().all()
    )

    out = []
    for u in users:
        n, pnl = trade_stats.get(u.id, (0, 0.0))
        out.append({
            'id': u.id,
            'email': u.email,
            'role': u.role or 'user',
            'subscription_tier': u.subscription_tier or 'free',
            'is_active': bool(u.is_active) if u.is_active is not None else True,
            'created_at': u.created_at.isoformat() if u.created_at else None,
            'last_login_at': u.last_login_at.isoformat() if u.last_login_at else None,
            'strategies_count': strat_count.get(u.id, 0),
            'strategies_running': running_count.get(u.id, 0),
            'trades_count': n,
            'total_pnl_usd': round(pnl, 2),
            'okx_bound': u.id in okx_bound,
            'llm_bound': u.id in llm_bound,
        })

    return jsonify({'users': out, 'total': len(out)})


@api_bp.route('/admin/users/<int:uid>', methods=['GET'])
@require_actor
@require_admin
def admin_user_detail(uid: int):
    """单 user 详情 + 关联资源"""
    from app.models import User, Subscription, OkxCredentials, LlmCredentials
    from sqlalchemy import func

    u = User.query.get(uid)
    if not u:
        return jsonify({'error': 'user not found'}), 404

    # 当前 active subscription
    sub = (Subscription.query.filter_by(user_id=uid, status='active')
           .order_by(Subscription.expires_at.desc()).first())

    # 策略 + trade 聚合
    strategies = Strategy.query.filter_by(user_id=uid).order_by(Strategy.id.desc()).limit(50).all()
    trade_agg = db.session.query(
        func.count(Trade.id).label('n'),
        func.coalesce(func.sum(Trade.pnl), 0).label('pnl'),
        func.count(Trade.id).filter(Trade.pnl > 0).label('wins'),
        func.count(Trade.id).filter(Trade.pnl < 0).label('losses'),
        func.max(Trade.exit_time).label('last_trade'),
    ).filter(Trade.user_id == uid).first()
    recent_trades = (Trade.query.filter_by(user_id=uid)
                     .order_by(Trade.id.desc()).limit(30).all())

    # AI usage (audit_log filter)
    ai_actions = (db.session.query(
        AuditLog.event_type, func.count(AuditLog.id)
    ).filter(AuditLog.user_id == uid,
             AuditLog.event_type.in_(['strategy_ai_improve', 'llm_call', 'strategy_ai_generate']))
     .group_by(AuditLog.event_type).all())

    okx = OkxCredentials.query.filter_by(user_id=uid).first()
    llm = LlmCredentials.query.filter_by(user_id=uid).all()

    return jsonify({
        'user': {
            'id': u.id,
            'email': u.email,
            'role': u.role,
            'subscription_tier': u.subscription_tier,
            'is_active': u.is_active,
            'created_at': u.created_at.isoformat() if u.created_at else None,
            'last_login_at': u.last_login_at.isoformat() if u.last_login_at else None,
        },
        'subscription': {
            'plan': sub.plan if sub else None,
            'status': sub.status if sub else None,
            'activated_at': sub.activated_at.isoformat() if sub and sub.activated_at else None,
            'expires_at': sub.expires_at.isoformat() if sub and sub.expires_at else None,
            'auto_renew': sub.auto_renew if sub else None,
        },
        'bindings': {
            'okx_bound': bool(okx),
            'llm_providers': [{'provider': l.provider, 'is_active': l.is_active} for l in llm],
        },
        'stats': {
            'strategies_total': len(strategies),
            'strategies_running': sum(1 for s in strategies if s.status == 'running'),
            'trades_count': trade_agg.n or 0,
            'trades_wins': trade_agg.wins or 0,
            'trades_losses': trade_agg.losses or 0,
            'total_pnl_usd': round(float(trade_agg.pnl or 0), 2),
            'last_trade_at': trade_agg.last_trade.isoformat() if trade_agg.last_trade else None,
            'ai_actions': dict(ai_actions),
        },
        'strategies': [{
            'id': s.id, 'name': s.name, 'type': s.type, 'symbol': s.symbol,
            'timeframe': s.timeframe, 'status': s.status, 'category': s.category,
        } for s in strategies],
        'recent_trades': [{
            'id': t.id, 'strategy_id': t.strategy_id, 'symbol': t.symbol,
            'side': t.side, 'pnl': round(float(t.pnl or 0), 2),
            'pnl_percent': round(float(t.pnl_percent or 0), 2),
            'entry_time': t.entry_time.isoformat() if t.entry_time else None,
            'exit_time': t.exit_time.isoformat() if t.exit_time else None,
            'reason': t.reason,
        } for t in recent_trades],
    })


@api_bp.route('/admin/users/<int:uid>/tier', methods=['POST'])
@require_actor
@require_admin
def admin_user_set_tier(uid: int):
    """手动改 user 的 subscription_tier (legacy 字段). Body: {"tier": "free|basic|pro|team"}"""
    from app.models import User
    from app.services.audit import log as audit
    u = User.query.get(uid)
    if not u:
        return jsonify({'error': 'user not found'}), 404
    payload = request.get_json(silent=True) or {}
    tier = (payload.get('tier') or '').lower()
    if tier not in ('free', 'basic', 'pro', 'team'):
        return jsonify({'error': 'invalid tier'}), 400
    old = u.subscription_tier
    u.subscription_tier = tier
    db.session.commit()
    audit('admin_user_tier_change', actor='admin',
          target_user_id=uid, old_tier=old, new_tier=tier,
          admin_user_id=current_user_id())
    return jsonify({'ok': True, 'user_id': uid, 'old_tier': old, 'new_tier': tier})


@api_bp.route('/admin/users/<int:uid>/toggle-active', methods=['POST'])
@require_actor
@require_admin
def admin_user_toggle_active(uid: int):
    """启停 user 账号. Body: {"is_active": bool}"""
    from app.models import User
    from app.services.audit import log as audit
    u = User.query.get(uid)
    if not u:
        return jsonify({'error': 'user not found'}), 404
    if u.role == 'admin' and uid == current_user_id():
        return jsonify({'error': '不能封自己'}), 400
    payload = request.get_json(silent=True) or {}
    new_active = bool(payload.get('is_active'))
    u.is_active = new_active
    db.session.commit()
    audit('admin_user_toggle_active', actor='admin',
          target_user_id=uid, new_active=new_active,
          admin_user_id=current_user_id())
    return jsonify({'ok': True, 'user_id': uid, 'is_active': new_active})


@api_bp.route('/admin/revenue', methods=['GET'])
@require_actor
@require_admin
def admin_revenue():
    """收入 / MRR / Pro 用户数 / 最近 invoices"""
    from app.models import PaymentInvoice, Subscription, User
    from sqlalchemy import func
    import datetime as _dt

    now = _dt.datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # 总确认收入
    total_revenue = float(db.session.query(
        func.coalesce(func.sum(PaymentInvoice.amount_due), 0)
    ).filter(PaymentInvoice.status == 'confirmed').scalar() or 0)

    # 本月新增收入
    mtd_revenue = float(db.session.query(
        func.coalesce(func.sum(PaymentInvoice.amount_due), 0)
    ).filter(PaymentInvoice.status == 'confirmed',
             PaymentInvoice.confirmed_at >= month_start).scalar() or 0)

    # 活跃订阅 by plan
    active_subs = dict(
        db.session.query(Subscription.plan, func.count(Subscription.id))
        .filter(Subscription.status == 'active',
                Subscription.expires_at > now)
        .group_by(Subscription.plan).all()
    )

    # 30 天每日收入
    days = 30
    daily = []
    for i in range(days, -1, -1):
        d_start = (now - _dt.timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        d_end = d_start + _dt.timedelta(days=1)
        amt = float(db.session.query(
            func.coalesce(func.sum(PaymentInvoice.amount_due), 0)
        ).filter(PaymentInvoice.status == 'confirmed',
                 PaymentInvoice.confirmed_at >= d_start,
                 PaymentInvoice.confirmed_at < d_end).scalar() or 0)
        daily.append({'date': d_start.strftime('%Y-%m-%d'), 'revenue_usdt': round(amt, 2)})

    # 最近 invoices
    recent = (PaymentInvoice.query.order_by(PaymentInvoice.created_at.desc()).limit(20).all())
    recent_out = []
    for inv in recent:
        usr = User.query.get(inv.user_id)
        recent_out.append({
            'id': inv.id,
            'user_id': inv.user_id,
            'user_email': usr.email if usr else None,
            'plan': inv.plan,
            'months': inv.months,
            'amount_due': float(inv.amount_due),
            'chain': inv.chain,
            'status': inv.status,
            'created_at': inv.created_at.isoformat() if inv.created_at else None,
            'confirmed_at': inv.confirmed_at.isoformat() if inv.confirmed_at else None,
        })

    # 总 user 数
    total_users = User.query.count()
    active_users_30d = User.query.filter(
        User.last_login_at > now - _dt.timedelta(days=30)
    ).count()

    return jsonify({
        'total_revenue_usdt': round(total_revenue, 2),
        'mtd_revenue_usdt': round(mtd_revenue, 2),
        'active_subscriptions_by_plan': active_subs,
        'total_users': total_users,
        'active_users_30d': active_users_30d,
        'daily_revenue_30d': daily,
        'recent_invoices': recent_out,
    })


@api_bp.route('/admin/audit-log', methods=['GET'])
@require_actor
@require_admin
def admin_audit_log():
    """跨 user audit log. Query: ?user_id=&event_type=&since=ISO&limit=200"""
    from app.models import User
    import datetime as _dt

    q = AuditLog.query
    user_id = request.args.get('user_id', type=int)
    if user_id:
        q = q.filter(AuditLog.user_id == user_id)
    event_type = request.args.get('event_type', type=str)
    if event_type:
        q = q.filter(AuditLog.event_type == event_type)
    since = request.args.get('since', type=str)
    if since:
        try:
            since_dt = _dt.datetime.fromisoformat(since.replace('Z', ''))
            q = q.filter(AuditLog.created_at >= since_dt)
        except Exception:
            pass
    limit = min(int(request.args.get('limit') or 200), 500)
    rows = q.order_by(AuditLog.created_at.desc()).limit(limit).all()

    # 拉 user email 一次
    uids = list({r.user_id for r in rows if r.user_id})
    email_map = {}
    if uids:
        for u in User.query.filter(User.id.in_(uids)).all():
            email_map[u.id] = u.email

    # event_type 全分布 (做下拉用)
    from sqlalchemy import func
    event_types = [r[0] for r in db.session.query(AuditLog.event_type, func.count(AuditLog.id))
                                  .group_by(AuditLog.event_type)
                                  .order_by(func.count(AuditLog.id).desc())
                                  .limit(50).all()]

    return jsonify({
        'rows': [{
            'id': r.id,
            'event_type': r.event_type,
            'actor': r.actor,
            'user_id': r.user_id,
            'user_email': email_map.get(r.user_id),
            'context': r.context,
            'ip': r.ip,
            'created_at': r.created_at.isoformat() if r.created_at else None,
        } for r in rows],
        'event_types': event_types,
        'total': len(rows),
    })
