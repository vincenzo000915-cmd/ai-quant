"""Phase 14b: Catalog-first AI 推荐 (取代 strategy_improve_v8 主路径)

不再让 LLM 凭空发明，从 vetted catalog 选最 fit user 当前情境的。
LLM 角色：score + explain，不发明（除非 mode='full_auto' 时调 v8 invent）

Flow:
  1. 拉 user portfolio + symbol regimes
  2. 拉 catalog (status='qualified', source='catalog')
  3. Rule-based score each catalog 适配度:
     - regime match (+30)
     - 当前 user 未持有该 type (+20)
     - symbol fit (+10)
     - verified_oos_sharpe 越高 +
  4. 选 top N → clone catalog 行 → 写新 candidate (status='qualified')
  5. 根据 ai_decision_mode 决定下一步:
     - manual: stop here (走 AiPickPanel 等 user)
     - semi_auto: verified_oos_sharpe ≥ 2.5 → 直接 promote+start
     - full_auto: 全部 promote+start (+ 调 v8 invent 兜底)
"""
from __future__ import annotations

import datetime
from typing import Any

from app.extensions import db
from app.models import Strategy, StrategyCandidate
from app.services.user_scope import scoped_query


def _user_running_summary(user_id: int) -> dict:
    """拉 user 现有 portfolio 摘要"""
    running = scoped_query(Strategy).filter_by(status='running').all()
    return {
        'count': len(running),
        'symbols': sorted({s.symbol for s in running if s.symbol}),
        'types': sorted({s.type for s in running}),
        'categories': sorted({s.category for s in running if s.category}),
    }


def _detect_user_regimes(user_symbols: list[str]) -> dict[str, str]:
    """每 symbol 当前 regime label"""
    try:
        from app.services.regime_detector import detect_regime
    except Exception:
        return {}
    result = {}
    for sym in user_symbols or ['AVAX/USDT', 'BTC/USDT']:
        for tf in ('4h', '1h'):
            try:
                r = detect_regime(sym, tf)
                result[f'{sym}@{tf}'] = r.get('regime', 'unknown')
            except Exception:
                pass
    return result


# Regime label → catalog ideal_regimes 模糊匹配
REGIME_FAMILY = {
    'trending': ['trending', 'expanding_vol', 'multi_week', 'late_trend'],
    'strong_trend': ['trending', 'expanding_vol', 'multi_week'],
    'weak_trend': ['trending', 'turning_point', 'late_trend'],
    'ranging': ['ranging', 'low_adx', 'mean_reverting', 'intraday', 'post_consolidation'],
    'choppy': ['ranging', 'low_adx'],
    'high_vol': ['high_vol', 'expanding_vol', 'volatility_expansion'],
    'low_vol': ['post_consolidation', 'mean_reverting'],
}


def _score_catalog_entry(entry: StrategyCandidate, user: dict, regimes: dict) -> tuple[int, list[str]]:
    """Rule-based 评分 catalog 候选适配 user。返回 (score, reasons)"""
    score = 0
    reasons = []
    cm = entry.catalog_meta or {}

    # 1. verified Sharpe baseline (0-40 points)
    sharpe = float(cm.get('verified_oos_sharpe') or 1.5)
    sharpe_pts = int(min(40, sharpe * 18))
    score += sharpe_pts
    reasons.append(f'verified Sharpe={sharpe} (+{sharpe_pts})')

    # 2. Regime 匹配 (0-30)
    ideal = set(cm.get('ideal_regimes') or [])
    if ideal and regimes:
        # 看 user symbols 当前 regime 是否在 ideal 集合内
        user_regimes_flat = set()
        for k, v in regimes.items():
            user_regimes_flat.update(REGIME_FAMILY.get(v, [v]))
        match = ideal & user_regimes_flat
        if match:
            score += 30
            reasons.append(f'regime match: {list(match)[:2]} (+30)')
        else:
            reasons.append(f'regime mismatch (ideal={list(ideal)[:2]} vs current={list(user_regimes_flat)[:2]})')

    # 3. Type 多样化 — user 已有同 type 不加分
    if entry.candidate_type.replace('cat_', '') in [t.replace('cat_', '') for t in user.get('types', [])]:
        reasons.append('type already running (-)')
    else:
        score += 15
        reasons.append('new type for portfolio (+15)')

    # 4. Symbol fit — 至少有一个 user 已 symbols 在 fit_symbols
    fit_symbols = set(cm.get('fit_symbols') or [])
    user_syms = set(user.get('symbols') or [])
    if fit_symbols and user_syms and (fit_symbols & user_syms):
        score += 10
        reasons.append('symbol fit (+10)')

    # 5. Category 平衡 — user 已有同 category 不太加分
    if entry.category not in user.get('categories', []):
        score += 5
        reasons.append(f'category {entry.category} 新颖 (+5)')

    return score, reasons


def _pick_symbol_for_recommendation(entry: StrategyCandidate, user_symbols: list[str]) -> str:
    """从 catalog 的 fit_symbols ∩ user 当前 symbols 选；都无则取 fit_symbols[0]"""
    fit = (entry.catalog_meta or {}).get('fit_symbols') or []
    if user_symbols:
        for s in user_symbols:
            if s in fit:
                return s
    if fit:
        return fit[0]
    return 'AVAX/USDT'


def _clone_catalog_to_candidate(entry: StrategyCandidate, user_id: int, symbol: str) -> StrategyCandidate:
    """克隆 catalog → 新 candidate (避免 catalog 模板被 promote 后无法复用)"""
    cm = entry.catalog_meta or {}
    rec_risk = cm.get('recommended_risk') or {}
    timestamp = datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')
    cloned_type = f'{entry.candidate_type}_u{user_id}_{timestamp}'
    clone = StrategyCandidate(
        source='catalog_clone',
        source_url=entry.source_url,
        source_name=f'AI 推荐 {entry.candidate_type} (user {user_id})',
        source_author=entry.source_author,
        source_meta={
            'symbol': symbol,
            'risk_params': rec_risk,
            'cloned_from_catalog_id': entry.id,
            'cloned_at': timestamp,
            'description': cm.get('description'),
        },
        raw_code=f'# Cloned from catalog id={entry.id}\n{entry.raw_code or ""}',
        raw_lang=entry.raw_lang,
        parsed_signal=entry.parsed_signal,
        signal_fn_name=entry.signal_fn_name,
        candidate_type=cloned_type,
        category=entry.category,
        timeframe=entry.timeframe,
        default_params=entry.default_params or {},
        llm_notes=cm.get('description'),
        llm_model='human_curated',
        status='qualified',                 # catalog 已 vetted
        catalog_meta={**cm, 'cloned_for_user': user_id, 'recommended_symbol': symbol},
        backtest_result_id=entry.backtest_result_id,
    )
    db.session.add(clone)
    db.session.flush()
    return clone


def _maybe_auto_apply(clone: StrategyCandidate, user_id: int, mode: str, cfg: dict) -> dict | None:
    """根据 mode 决定是否自动 promote+start，含 guardrails"""
    if mode == 'manual':
        return None
    cm = clone.catalog_meta or {}
    sharpe = float(cm.get('verified_oos_sharpe') or 1.5)

    # Guardrails
    n_running = scoped_query(Strategy).filter_by(status='running').count()
    max_running = int(cfg.get('auto_apply_max_running', 8))
    if n_running >= max_running:
        return {'skipped': True, 'reason': f'running {n_running} >= max {max_running}'}

    if cfg.get('halted'):
        return {'skipped': True, 'reason': 'system halted'}

    # 今日已 auto-applied 数
    today_start = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    from app.models import AuditLog
    today_auto = AuditLog.query.filter(
        AuditLog.actor == 'auto:strategy_recommend',
        AuditLog.event_type == 'candidate_promote_and_start',
        AuditLog.created_at >= today_start,
    ).count()
    max_per_day = int(cfg.get('auto_promote_max_per_day', 2))
    if today_auto >= max_per_day:
        return {'skipped': True, 'reason': f'today auto-applied {today_auto} >= max {max_per_day}'}

    # semi_auto: 仅 Sharpe ≥ 2.5 自动
    if mode == 'semi_auto' and sharpe < 2.5:
        return {'skipped': True, 'reason': f'semi_auto: Sharpe {sharpe} < 2.5 (走面板)'}

    # 通过 — 自动 promote+start
    from app.services.candidate_pipeline import promote_candidate as do_promote
    rp = (clone.source_meta or {}).get('risk_params') or {}
    sym = (clone.source_meta or {}).get('symbol') or 'AVAX/USDT'
    promote_res = do_promote(clone.id, symbol=sym, owner_user_id=user_id)
    if not promote_res.get('ok'):
        return {'skipped': True, 'reason': f'promote fail: {promote_res.get("error", "")[:100]}'}
    sid = promote_res['strategy']['id']

    # 写 risk_params + start
    s = Strategy.query.get(sid)
    if s:
        p = dict(s.params or {})
        p['risk_params'] = {k: v for k, v in rp.items() if v is not None}
        s.params = p
        s.status = 'running'
        db.session.commit()
        try:
            from app.tasks.strategy_tasks import run_strategy_signals
            run_strategy_signals.delay(sid)
        except Exception:
            pass

    # audit
    try:
        from app.services.audit import log as audit
        audit('candidate_promote_and_start',
              actor='auto:strategy_recommend',
              user_id=user_id,
              candidate_id=clone.id,
              strategy_id=sid,
              risk_params=rp,
              symbol=sym,
              mode=mode,
              sharpe=sharpe)
    except Exception:
        pass

    # Telegram (admin 用 admin chat，其他 user 暂不通知)
    try:
        from app.services.telegram_service import send as _tg
        if user_id == 1:
            _tg(
                f'🤖 <b>AI 自动上线策略</b> (mode={mode})\n'
                f'#{sid} {clone.candidate_type}\n'
                f'symbol={sym} | OOS Sharpe={sharpe} (verified catalog)\n'
                f'lev={rp.get("leverage")}x SL={rp.get("stop_loss_pct")}% TP={rp.get("take_profit_pct")}% order={rp.get("order_type", "market")}\n\n'
                f'→ 已 running。<a href="https://ai-quant.medias-ai.cloud/">面板查看</a> · 不同意可立即 stop',
                event_key='auto_apply'
            )
    except Exception:
        pass

    return {'applied': True, 'strategy_id': sid, 'sharpe': sharpe}


def recommend_strategies(user_id: int, *, max_recommend: int = 3) -> dict:
    """主入口 — 从 catalog 推荐 top N 适配 user 的策略"""
    from app.services.config_service import get_config
    cfg = get_config()
    mode = cfg.get('ai_decision_mode', 'manual')

    user = _user_running_summary(user_id)
    regimes = _detect_user_regimes(user['symbols'])

    catalog = StrategyCandidate.query.filter_by(source='catalog', status='qualified').all()
    if not catalog:
        return {'ok': False, 'error': 'catalog 为空，先跑 seed_catalog.py'}

    # Score 所有 catalog
    scored = []
    for entry in catalog:
        s, reasons = _score_catalog_entry(entry, user, regimes)
        scored.append((entry, s, reasons))
    scored.sort(key=lambda x: -x[1])
    top = scored[:max_recommend]

    # Clone top N + maybe auto-apply
    recommendations = []
    for entry, score, reasons in top:
        sym = _pick_symbol_for_recommendation(entry, user['symbols'])
        clone = _clone_catalog_to_candidate(entry, user_id, sym)
        auto = _maybe_auto_apply(clone, user_id, mode, cfg)
        recommendations.append({
            'catalog_id': entry.id,
            'catalog_type': entry.candidate_type,
            'cloned_id': clone.id,
            'cloned_type': clone.candidate_type,
            'symbol': sym,
            'category': entry.category,
            'timeframe': entry.timeframe,
            'verified_sharpe': (entry.catalog_meta or {}).get('verified_oos_sharpe'),
            'recommended_risk': (entry.catalog_meta or {}).get('recommended_risk'),
            'description': (entry.catalog_meta or {}).get('description'),
            'score': score,
            'reasons': reasons,
            'auto_apply': auto,
            'source': 'catalog',
        })

    # Phase 14d: full_auto 模式且 catalog top score < 高门槛 → 触发 v8 invent
    invent_result = None
    if mode == 'full_auto':
        catalog_max_score = top[0][1] if top else 0
        if catalog_max_score < 80:
            # catalog 没有显著好选 → 尝试 invent
            try:
                from app.services.llm_prompts.strategy_improve_v8 import improve_strategies_v8
                v8_r = improve_strategies_v8(
                    user_id=user_id, max_iterations=1, target_count=1,
                    enable_external_research=True,
                )
                invent_result = {
                    'attempted': True,
                    'submitted_count': len(v8_r.get('submitted', [])),
                    'rejected_count': len(v8_r.get('rejected', [])),
                }
                # invent 输出 — apply paper-only guard
                for sub in v8_r.get('submitted', []):
                    cid = sub.get('candidate_id')
                    if not cid:
                        continue
                    metric_sharpe = (sub.get('metrics') or {}).get('oos_sharpe', 0)
                    if metric_sharpe < 2.0:
                        invent_result.setdefault('rejected_low_sharpe', []).append(
                            {'candidate_id': cid, 'sharpe': metric_sharpe}
                        )
                        continue
                    # Mark for paper-only 7 天
                    cand = StrategyCandidate.query.get(cid)
                    if cand:
                        meta = dict(cand.source_meta or {})
                        meta['paper_only_days'] = 7
                        meta['source_label'] = 'AI invented (paper-only 7d)'
                        cand.source_meta = meta
                    # Try auto-apply (with paper-only flag)
                    auto_invent = _maybe_auto_apply_invent(cand, user_id, mode, cfg)
                    recommendations.append({
                        'cloned_id': cid,
                        'cloned_type': cand.candidate_type if cand else '?',
                        'symbol': (cand.source_meta or {}).get('symbol') if cand else None,
                        'verified_sharpe': metric_sharpe,
                        'source': 'invented',
                        'auto_apply': auto_invent,
                        'paper_only_days': 7,
                    })
            except Exception as e:
                invent_result = {'attempted': True, 'error': f'{type(e).__name__}: {e}'}

    db.session.commit()
    return {
        'ok': True,
        'mode': mode,
        'user_state': user,
        'regimes': regimes,
        'catalog_size': len(catalog),
        'recommendations': recommendations,
        'invent_result': invent_result,
    }


def _maybe_auto_apply_invent(cand, user_id: int, mode: str, cfg: dict) -> dict | None:
    """Phase 14d: invent 出的策略走 paper-only 7 天再升 LIVE"""
    if mode != 'full_auto' or not cand:
        return None
    from app.services.candidate_pipeline import promote_candidate as do_promote
    sym = (cand.source_meta or {}).get('symbol') or 'AVAX/USDT'
    rp = (cand.source_meta or {}).get('risk_params') or {}

    # Guardrail: 总 running 限制
    n_running = scoped_query(Strategy).filter_by(status='running').count()
    if n_running >= int(cfg.get('auto_apply_max_running', 8)):
        return {'skipped': True, 'reason': f'running {n_running} >= max'}

    promote_res = do_promote(cand.id, symbol=sym, owner_user_id=user_id)
    if not promote_res.get('ok'):
        return {'skipped': True, 'reason': f'promote fail: {promote_res.get("error", "")[:100]}'}
    sid = promote_res['strategy']['id']
    s = Strategy.query.get(sid)
    if s:
        p = dict(s.params or {})
        p['risk_params'] = {k: v for k, v in rp.items() if v is not None}
        # Phase 14d: paper-only 7 天
        import datetime as _dt
        p['paper_only_until'] = (_dt.datetime.utcnow() + _dt.timedelta(days=7)).isoformat()
        s.params = p
        s.status = 'running'
        db.session.commit()
        try:
            from app.tasks.strategy_tasks import run_strategy_signals
            run_strategy_signals.delay(sid)
        except Exception:
            pass

    # audit
    try:
        from app.services.audit import log as audit
        audit('candidate_promote_and_start_paper_only',
              actor='auto:strategy_recommend_invent',
              user_id=user_id, candidate_id=cand.id, strategy_id=sid,
              risk_params=rp, symbol=sym,
              paper_only_until_days=7)
    except Exception:
        pass

    return {'applied': True, 'paper_only_days': 7, 'strategy_id': sid}
