"""Phase 10.7: strategy advisor.

Synthesises everything Phase 10 collects (correlation matrix, regime fit,
multi-TF consensus, latest backtest Sharpe, latest param optimization)
into a short list of concrete suggestions:

  - retire        : highly correlated AND lower Sharpe vs its twin
  - pause         : regime mismatch + bad fit
  - apply_params  : a recent optimization beat the baseline meaningfully
  - fan_out       : strategy looks healthy and is the only sibling on its symbol
  - mtf_caution   : multi-TF conflict, suggest watching not acting

Each item carries severity (info / warn / critical) plus a one-line reason
the dashboard can render. The user always decides; we don't auto-act.
"""
from __future__ import annotations

from app.extensions import db
from app.models import Strategy, BacktestResult, ParamOptimization, StrategyCandidate
from app.services.strategy_correlation import build_correlation_matrix
from app.services.regime_detector import detect_regime, affinity_for, fit_label
from app.services.mtf_consensus import mtf_check


HIGH_CORR = 0.7
APPLY_PARAMS_LIFT = 0.5         # OOS Sharpe must beat baseline by this much
APPLY_PARAMS_MAX_AGE_DAYS = 14  # 優化超過 14 天 → 不推（K 線早變了）
RETIRE_MIN_SHARPE_DIFF = 0.5    # 兩支 Sharpe 差距 < 0.5 不算明顯，不推 retire
RETIRE_REQUIRE_POSITIVE_KEEP = True   # 留下的那支 Sharpe 必須 > 0，否則「保留較好的」沒意義
PROMOTE_MIN_OOS_SHARPE = 1.5    # promote_candidate 至少這 Sharpe 才推（跟 executor 阈值同步）
FAN_OUT_MIN_SHARPE = 2.0
FAN_OUT_BACKTEST_MAX_AGE_DAYS = 14   # backtest 太老 → 不推 fan_out

# Phase 14k-30: grace 按 timeframe 分级 — 高频策略不该等 7 天确认烂
# 设计: 大约 = TF 跑出 ~30 根 candle 的天数 (统计显著)
GRACE_DAYS_BY_TF = {
    '15m': 1,    # 96 candles/day, 1 天 = 96 根
    '30m': 1,
    '1h':  2,    # 24/day, 2 天 = 48 根
    '2h':  2,
    '4h':  3,    # 6/day, 3 天 = 18 根
    '6h':  4,
    '8h':  4,
    '12h': 5,
    '1d':  7,    # 原 7 天阈值留给 1d 策略
    '3d':  14,
    '1w':  21,
}
DEFAULT_GRACE_DAYS = 7

def _grace_days(timeframe: str | None) -> int:
    return GRACE_DAYS_BY_TF.get(timeframe or '4h', DEFAULT_GRACE_DAYS)


# Phase 14k-45 L1: 用 AI market_brief 增强 regime 判断 (取代单 regime_detector)
def _get_market_brief(symbol: str) -> dict | None:
    """拉 brief (走 LLM cache, 15min prewarm). 失败返 None 让 caller fallback 到 regime_detector."""
    try:
        from app.services.llm_prompts.market_analyst import analyze_market
        r = analyze_market(symbol, timeframes=['15m', '1h', '4h'])
        if r.get('ok'):
            return r['brief']
    except Exception as e:
        print(f'[advisor] market_brief({symbol}) failed: {type(e).__name__}: {e}')
    return None


def _fit_with_brief(strategy_type: str, symbol: str, regime: str | None) -> tuple[str, dict | None]:
    """优先用 AI brief.recommended_archetype 判 fit, fallback regime_detector.

    返回 (fit, brief): fit 是 'good'/'ok'/'bad'/'unknown', brief 是 dict 或 None
    """
    brief = _get_market_brief(symbol)
    if brief:
        from app.services.llm_prompts.market_analyst import archetype_to_affinity
        ai_aff = archetype_to_affinity(brief.get('recommended_archetype'))
        if ai_aff:
            strat_aff = affinity_for(strategy_type)
            # brief 推荐的 archetype 跟 strategy affinity 直接对比
            if strat_aff == ai_aff:
                return ('good', brief)
            elif strat_aff is None:
                return ('unknown', brief)
            else:
                return ('bad', brief)
        # AI 说 'wait' → 所有策略都 bad (没好机会)
        if brief.get('recommended_archetype') == 'wait':
            return ('bad', brief)
    # fallback
    return (fit_label(strategy_type, regime or 'unknown'), brief)


def _latest_backtest(strategy_id: int) -> BacktestResult | None:
    return (
        BacktestResult.query
        .filter_by(strategy_id=strategy_id, status='completed')
        .order_by(BacktestResult.created_at.desc())
        .first()
    )


def _latest_backtest_sharpe(strategy_id: int) -> float | None:
    bt = _latest_backtest(strategy_id)
    return bt.sharpe_ratio if bt else None


def _has_open_position(strategy_id: int) -> bool:
    """有 open position 時退役不會平倉，只是阻新信號 — 通常沒救急效果"""
    from app.models import Position
    return Position.query.filter_by(strategy_id=strategy_id, status='open').count() > 0


def _latest_completed_optimization(strategy_id: int):
    return (
        ParamOptimization.query
        .filter_by(strategy_id=strategy_id, status='completed')
        .order_by(ParamOptimization.id.desc())
        .first()
    )


def _get_target_context(user_id: int = 1) -> dict:
    """Phase 14k-24: 拉 active profit_target 上下文, 让 advisor 调阈值.

    返回:
    {
      lag_mode: bool   — 落后 >5% (更激进)
      dd_warn: bool    — DD > max_dd_pct × 0.6 (警戒区)
      ahead_mode: bool — 领先 >5% (保守)
      progress_pct: float
      none: bool       — 没目标 (走默认)
    }
    """
    try:
        from app.models import ProfitTarget
        t = ProfitTarget.query.filter_by(user_id=user_id, status='active').first()
        if not t or not t.current_equity_usdt:
            return {'none': True}
        cur = t.current_equity_usdt
        expected = t.expected_equity_now()
        lag_pct = (expected - cur) / expected * 100 if expected > 0 else 0
        dd = t.dd_pct()
        return {
            'none': False,
            'lag_mode': lag_pct > 5,
            'ahead_mode': lag_pct < -5,    # 实际 > 应该 = lag 负 = 领先
            'dd_warn': dd > (t.max_dd_pct * 0.6) if t.max_dd_pct else False,
            'progress_pct': t.progress_pct(),
            'lag_pct': lag_pct,
            'dd_pct': dd,
        }
    except Exception:
        return {'none': True}


def build_recommendations(user_id: int = 1) -> dict:
    # Phase 14k-24: 加目标上下文, 动态调阈值
    target_ctx = _get_target_context(user_id)
    apply_lift = APPLY_PARAMS_LIFT
    fan_out_min = FAN_OUT_MIN_SHARPE
    fan_out_locked = False
    if not target_ctx.get('none'):
        if target_ctx.get('lag_mode'):
            # 落后 → 降低 apply 阈值, 更激进调参
            apply_lift = max(0.2, APPLY_PARAMS_LIFT - 0.2)
            # 不动 fan_out (allow expansion)
        if target_ctx.get('dd_warn'):
            # DD 警戒 → 锁 fan_out (别扩张, 先稳)
            fan_out_locked = True
        if target_ctx.get('ahead_mode'):
            # 领先 → 保守, 提高 apply 阈值 (不轻易改赢家)
            apply_lift = APPLY_PARAMS_LIFT + 0.3

    running = Strategy.query.filter(Strategy.status == 'running').all()
    if not running:
        return {'items': [], 'note': '目前沒有運行中的策略，無建議可生成。'}

    items: list[dict] = []
    sharpe_by_id = {s.id: _latest_backtest_sharpe(s.id) for s in running}

    # 1) 相關性 → retire 較弱的那一支（Phase 12.12: 5 個 sanity check）
    import datetime as _dt
    corr = build_correlation_matrix([s.id for s in running])
    strat_map = {s.id: s for s in running}
    seen_pairs: set[frozenset] = set()
    retired_already: set[int] = set()  # dedup — 同一個 drop 只推一次

    for flag in corr.get('flagged', []):
        pair = frozenset({flag['a_id'], flag['b_id']})
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        a_sh = sharpe_by_id.get(flag['a_id'])
        b_sh = sharpe_by_id.get(flag['b_id'])

        # check 1: Sharpe 數據不夠就跳過（沒得比較）
        if a_sh is None or b_sh is None:
            continue

        keep_id, drop_id = (flag['a_id'], flag['b_id']) if a_sh >= b_sh else (flag['b_id'], flag['a_id'])
        keep_sh, drop_sh = (a_sh, b_sh) if keep_id == flag['a_id'] else (b_sh, a_sh)
        drop = strat_map.get(drop_id)
        keep = strat_map.get(keep_id)
        if not drop or not keep:
            continue

        # check 2: dedup — 一個策略最多只推一次 retire
        if drop_id in retired_already:
            continue

        # check 3: 兩邊 Sharpe 差距太小不算「明顯較差」
        if abs(keep_sh - drop_sh) < RETIRE_MIN_SHARPE_DIFF:
            continue

        # check 4: 留下的那支 Sharpe 必須 > 0 才有意義（不然只是比誰更糟）
        if RETIRE_REQUIRE_POSITIVE_KEEP and keep_sh <= 0:
            continue

        # check 5: 同 template_group 兄弟（同策略不同幣種）— 高相關是設計使然，不算冗餘
        if drop.template_group is not None and drop.template_group == keep.template_group:
            continue

        # check 6: 保护期 — 按 timeframe 分级 (14k-30): 高频 1-3 天, 日线 7 天, 周线 21 天
        drop_grace = _dt.datetime.utcnow() - _dt.timedelta(days=_grace_days(drop.timeframe))
        if drop.created_at and drop.created_at > drop_grace:
            continue

        # check 7: 有 open position — retire 不會平倉只是阻新信號，沒救急效果
        if _has_open_position(drop_id):
            continue

        retired_already.add(drop_id)
        items.append({
            'action': 'retire',
            'strategy_id': drop_id,
            'strategy_name': drop.name,
            'severity': 'warn',
            'reason': (
                f'與 #{keep_id} {keep.name} 相關係數 {flag["corr"]:.2f}（高度同質）。'
                f'Sharpe = {drop_sh:.2f} vs {keep_sh:.2f}（差 {abs(keep_sh-drop_sh):.2f}），保留較高那支。'
            ),
            'meta': {'twin_id': keep_id, 'corr': flag['corr']},
        })

    # 2) regime 不匹配 → pause (14k-30: grace 按 TF 分级)
    regime_full_cache: dict[tuple, dict] = {}
    for s in running:
        key = (s.symbol, s.timeframe)
        if key not in regime_full_cache:
            regime_full_cache[key] = detect_regime(s.symbol, s.timeframe)
        rd = regime_full_cache[key]
        regime = rd.get('regime', 'unknown')
        fit = fit_label(s.type, regime)
        if fit != 'bad':
            continue
        # check: regime 數據不可靠（K 線太少 / 數據沒拉到）→ 不推 pause
        if rd.get('n', 0) < 100:
            continue
        # check: grace 按 TF 分级 — 新策略還沒累積實盤數據
        pause_grace = _dt.datetime.utcnow() - _dt.timedelta(days=_grace_days(s.timeframe))
        if s.created_at and s.created_at > pause_grace:
            continue
        # check: 有 open position — pause 不平倉只阻新信號，先讓現有 SL/TP 處理
        has_pos = _has_open_position(s.id)
        items.append({
            'action': 'pause',
            'strategy_id': s.id,
            'strategy_name': s.name,
            'severity': 'info' if has_pos else 'warn',
            'reason': (
                f'類型 {affinity_for(s.type)} 與當前 {s.symbol} {s.timeframe} 市場狀態 '
                f'({regime}) 不匹配，歷史上這個組合通常虧損。'
                + ('（目前有持倉，pause 只阻新信號，現有單會走 SL/TP）' if has_pos else '建議暫停或先做 walk-forward 驗證。')
            ),
            'meta': {'regime': regime, 'affinity': affinity_for(s.type), 'has_open_position': has_pos},
        })

    # 3) 最新優化 → 套用最佳參數（Phase 12.12: 加 freshness 檢查）
    apply_age_cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=APPLY_PARAMS_MAX_AGE_DAYS)
    for s in running:
        opt = _latest_completed_optimization(s.id)
        if not opt or not opt.best_params or opt.best_oos_sharpe is None:
            continue
        # check: 優化太老（> 14 天）→ 跳過，K 線早變了應該重跑
        if opt.completed_at and opt.completed_at < apply_age_cutoff:
            continue
        baseline = opt.baseline_oos_sharpe
        best = opt.best_oos_sharpe
        # baseline 可能是 None（基線就跑不出 Sharpe），這種情況 best > 1 也值得套用
        beats_baseline = baseline is None or (best - baseline) >= apply_lift
        # 幂等：當前 strategy.params 已經是 best 就不再建議
        current_params = dict(s.params or {})
        if best >= 1.0 and beats_baseline and opt.best_params != current_params:
            lift_str = f'+{(best - baseline):.2f}' if baseline is not None else f'從無 Sharpe → {best:.2f}'
            items.append({
                'action': 'apply_params',
                'strategy_id': s.id,
                'strategy_name': s.name,
                'severity': 'info',
                'reason': (
                    f'最近一次參數網格搜尋發現更佳組合：{opt.best_params} → OOS Sharpe = {best:.2f} '
                    f'({lift_str})。基線是 {baseline if baseline is not None else "無"}。'
                ),
                'meta': {
                    'optimization_id': opt.id,
                    'best_params': opt.best_params,
                    'best_oos_sharpe': best,
                    'baseline_oos_sharpe': baseline,
                },
            })

    # 4) MTF 衝突 → 觀望提醒
    for s in running:
        try:
            m = mtf_check(s)
        except Exception:
            continue
        if m.get('consensus', {}).get('label') == 'mixed':
            items.append({
                'action': 'mtf_caution',
                'strategy_id': s.id,
                'strategy_name': s.name,
                'severity': 'info',
                'reason': (
                    f'多時框出現衝突訊號（buy 與 sell 並存），通常代表趨勢轉折，'
                    f'若有實盤訊號建議多看一根 K 再進。'
                ),
                'meta': {'per_tf': m['per_tf'], 'consensus': m['consensus']},
            })

    # 5) fan-out 機會 (14k-30: grace 按 TF 分级)
    fanout_age_cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=FAN_OUT_BACKTEST_MAX_AGE_DAYS)
    for s in running:
        # check: grace 按 TF 分级 — 新策略還沒累積實盤數據, 先別 fan-out
        fanout_grace = _dt.datetime.utcnow() - _dt.timedelta(days=_grace_days(s.timeframe))
        if s.created_at and s.created_at > fanout_grace:
            continue
        bt = _latest_backtest(s.id)
        # 14k-24: DD 警戒区锁 fan_out (别扩张)
        if fan_out_locked:
            continue
        if not bt or bt.sharpe_ratio is None or bt.sharpe_ratio < fan_out_min:
            continue
        # check: backtest 太老 → 數據過時不該基於此推 fan_out
        if bt.created_at and bt.created_at < fanout_age_cutoff:
            continue
        # 無 template_group 或 group 只有自己
        if s.template_group is None or s.template_group == s.id:
            siblings = Strategy.query.filter(
                Strategy.template_group == (s.template_group or s.id),
                Strategy.id != s.id,
            ).count()
            if siblings == 0:
                items.append({
                    'action': 'fan_out',
                    'strategy_id': s.id,
                    'strategy_name': s.name,
                    'severity': 'info',
                    'reason': (
                        f'Sharpe {bt.sharpe_ratio:.2f} 表現良好但只跑 {s.symbol}。考慮一鍵 fan-out 到 ETH/SOL/AVAX '
                        f'等其他幣種分散單一資產風險。'
                    ),
                    'meta': {'current_symbol': s.symbol, 'sharpe': bt.sharpe_ratio},
                })

    # 6) 合格候選 → promote 上線（Phase 12.12: 加 OOS 門檻 + dedup）
    qualified_cands = (
        StrategyCandidate.query
        .filter_by(status='qualified')
        .filter(StrategyCandidate.promoted_strategy_id.is_(None))
        .all()
    )
    # dedup: 已有同 candidate_type + symbol 策略 → 跳過（避免重複上線）
    # 14k-52: stopped > 7d 释放 dedup slot — 老 stopped 不该挡 AI 新提议
    # (cleanup_stale_candidates 会把 stopped+0trades+>7d 自动 retire, 这里 fallback 防 race)
    import datetime as _dt_dedup
    cutoff_dedup = _dt_dedup.datetime.utcnow() - _dt_dedup.timedelta(days=7)
    existing_types = {(s.type, s.symbol) for s in Strategy.query.filter(
        (Strategy.status == 'running') |
        ((Strategy.status == 'stopped') & (Strategy.created_at > cutoff_dedup))
    ).all()}

    for c in qualified_cands:
        bt = c.backtest
        if not bt:
            continue
        wf = (bt.walkforward_json or {}).get('out_sample') or {}
        oos = wf.get('sharpe_ratio')
        if oos is None:
            continue
        # check: OOS Sharpe 必須過 promote 門檻（跟 executor / auto_promote_min_oos_sharpe 同步）
        if oos < PROMOTE_MIN_OOS_SHARPE:
            continue
        # Phase 14k-18: target_symbol 优先从 candidate.source_meta.symbol 拿
        # (catalog clone 自带), 没的话用候选自己回测的 symbol, 兜底 BTC/USDT
        meta = c.source_meta or {}
        target_symbol = meta.get('symbol')
        if not target_symbol and c.backtest_result_id:
            try:
                from app.models import BacktestResult
                bt = BacktestResult.query.get(c.backtest_result_id)
                if bt and bt.symbol:
                    target_symbol = bt.symbol
            except Exception:
                pass
        target_symbol = target_symbol or 'BTC/USDT'
        # check: dedup — 同類型同 symbol 已存在 → 跳過
        if (c.candidate_type, target_symbol) in existing_types:
            continue
        # 14k-18: 友好措辞 — 去 raw candidate_type, 加 symbol
        pretty_type = (c.candidate_type or '').replace('cat_', '').replace('_', ' ').title()
        items.append({
            'action': 'promote_candidate',
            'strategy_id': None,
            'strategy_name': c.source_name or f'候选 #{c.id}',
            'severity': 'info',
            'reason': (
                f'候选 #{c.id} 「{pretty_type}」回测通过 — '
                f'OOS Sharpe {oos:.2f} ≥ 门槛 {PROMOTE_MIN_OOS_SHARPE}, '
                f'建议上线 {target_symbol}'
            ),
            'meta': {
                'candidate_id': c.id,
                'oos_sharpe': oos,
                'candidate_type': c.candidate_type,
                'symbol': target_symbol,
                'source': c.source,
            },
        })

    # Phase 14k-28 L2: AI 账户级 sizing (24h cooldown, 仅当 diff 够大才出 item)
    try:
        sizing_item = _sizing_recommendation_item(user_id)
        if sizing_item:
            items.append(sizing_item)
    except Exception as e:
        print(f'[advisor] sizing_recommendation skipped: {type(e).__name__}: {e}')

    # Phase 14k-28 L3: 单策略 risk_params 调整 (leverage / position_size, 守 backtest 真理不动 SL/TP)
    try:
        for s in running:
            risk_item = _strategy_risk_adjust_item(s, target_ctx)
            if risk_item:
                items.append(risk_item)
    except Exception as e:
        print(f'[advisor] strategy_risk_adjust skipped: {type(e).__name__}: {e}')

    # Phase 14k-29 L4: 单策略 SL/TP 闪测 (走 walk-forward, 过门槛由 task 内自动 apply)
    try:
        for s in running:
            opt_item = _strategy_risk_opt_item(s)
            if opt_item:
                items.append(opt_item)
    except Exception as e:
        print(f'[advisor] strategy_risk_opt skipped: {type(e).__name__}: {e}')

    # Phase 14k-29 L5: AI 提议信号 grid → 触发 ParamOptimization (走现有 apply_params 路径)
    try:
        for s in running:
            grid_item = _signal_grid_propose_item(s, target_ctx)
            if grid_item:
                items.append(grid_item)
    except Exception as e:
        print(f'[advisor] signal_grid_propose skipped: {type(e).__name__}: {e}')

    # Phase 14k-29 L6: 主动 invent 新策略 (目标 lag 模式 + 候选池稀薄)
    try:
        invent_item = _invent_new_strategy_item(user_id, target_ctx)
        if invent_item:
            items.append(invent_item)
    except Exception as e:
        print(f'[advisor] invent_new_strategy skipped: {type(e).__name__}: {e}')

    # 嚴重度排序：critical > warn > info
    sev_rank = {'critical': 0, 'warn': 1, 'info': 2}
    items.sort(key=lambda x: (sev_rank.get(x['severity'], 9), x['action']))

    return {
        'items': items,
        'summary': {
            'total': len(items),
            'critical': sum(1 for i in items if i['severity'] == 'critical'),
            'warn': sum(1 for i in items if i['severity'] == 'warn'),
            'info': sum(1 for i in items if i['severity'] == 'info'),
        },
        'target_context': target_ctx,    # 14k-24: 让 UI / executor 看见 advisor 用了什么 mode
        'thresholds_used': {
            'apply_params_lift': apply_lift,
            'fan_out_min_sharpe': fan_out_min,
            'fan_out_locked': fan_out_locked,
        },
    }


# ====================== Phase 14k-28: L2 + L3 risk advisor ======================

SIZING_COOLDOWN_HOURS = 24      # AI sizing 一天最多推 1 次
SIZING_DIFF_THRESHOLD = 0.25    # 字段差 ≥ 25% 才推
RISK_LEVERAGE_BOUNDS = (1.0, 20.0)
RISK_LEVERAGE_STEP = 1.0        # 单次调幅 cap
RISK_POSITION_BOUNDS_FRAC = (0.3, 3.0)  # position 相对 trade_size_default 的范围
RISK_POSITION_STEP_FRAC = 0.5   # 单次调幅 cap (相对当前)
RISK_ADJUST_COOLDOWN_HOURS = 6  # 单策略 6h 最多调 1 次
RISK_MIN_LIVE_AGE_HOURS = 2     # 策略 running 不足 2h 不调


def _sizing_recommendation_item(user_id: int = 1) -> dict | None:
    """L2: AI 账户级 sizing (trade_size / leverage / max_daily_loss).
    守 backtest 真理: 不动 SL/TP. 24h cooldown 避免 LLM 重复烧钱.
    """
    import datetime as _dt
    from app.models import AuditLog
    from app.services.config_service import get_config
    from app.services.audit import log as audit_log

    cutoff = _dt.datetime.utcnow() - _dt.timedelta(hours=SIZING_COOLDOWN_HOURS)
    last = AuditLog.query.filter(
        AuditLog.event_type == 'sizing_advisor_recommend',
        AuditLog.created_at > cutoff,
    ).first()
    if last:
        return None

    # 拉账户余额 — 失败就 skip (advisor 不该因此挂)
    try:
        from app.services.exchange_service import fetch_balance, _resolve_creds
        creds = _resolve_creds(user_id) if user_id != 1 else None
        balances = fetch_balance(creds=creds) if creds else fetch_balance()
        usd_total = sum(v.get('total', 0) for v in (balances or {}).values())
        free_usdt = (balances or {}).get('USDT', {}).get('free', 0)
    except Exception:
        return None
    if usd_total <= 0:
        return None

    from app.services.llm_prompts.sizing_advisor import recommend_sizing
    r = recommend_sizing(user_id, {'balance': usd_total, 'free_margin': free_usdt, 'unrealized_pnl': 0})
    if not r.get('ok'):
        return None

    rec = r.get('recommended') or {}
    cur = r.get('current') or get_config()

    # 只看不会动 PnL 回测 invariant 的字段 (跳过 SL/TP)
    fields = ['trade_size_usdt', 'leverage', 'max_daily_loss_usdt']
    deltas = {}
    significant = False
    for f in fields:
        rv = rec.get(f)
        cv = cur.get(f)
        if rv is None or cv is None:
            continue
        try:
            rv = float(rv); cv = float(cv)
        except (TypeError, ValueError):
            continue
        if cv == 0:
            if rv > 0.01:
                significant = True
                deltas[f] = 'set'
        else:
            pct = abs(rv - cv) / cv
            deltas[f] = round(pct, 3)
            if pct >= SIZING_DIFF_THRESHOLD:
                significant = True

    # 不管是否 significant, 写 cooldown 记录避免 24h 内重复 LLM
    try:
        audit_log('sizing_advisor_recommend', user_id=user_id,
                  current=cur, recommended=rec, deltas=deltas, significant=significant)
    except Exception:
        pass

    if not significant:
        return None

    new_sizing = {f: float(rec[f]) for f in fields if rec.get(f) is not None}
    return {
        'action': 'adjust_global_sizing',
        'strategy_id': 0,
        'strategy_name': '账户级 sizing',
        'severity': 'info',
        'reason': f'AI 资金顾问: {(rec.get("rationale") or "")[:200]}',
        'meta': {
            'user_id': user_id,   # 14k-30 #3: per-user scoped
            'new_sizing': new_sizing,
            'current': {f: cur.get(f) for f in fields},
            'rationale': rec.get('rationale'),
            'balance': round(usd_total, 2),
        },
    }


def _strategy_risk_adjust_item(strategy, target_ctx: dict) -> dict | None:
    """L3: 单策略 risk_params 启发式调整 (leverage + position_size_usdt).
    不动 SL/TP (那是回测 PnL invariant). 不调 LLM (启发式可解释/可测).
    规则:
      - 策略最近 OOS Sharpe ≥ 2.0 + max_dd_pct 充裕 → leverage +1 (cap 20)
      - 策略最近 OOS Sharpe < 1.0 持续 → leverage -1 (floor 1)
      - 目标 lag > 10% + 策略表现 good → position_size × 1.3 (cap 3× default)
      - 目标 ahead > 15% → 保守, leverage -1
      - 单策略 6h cooldown / 不超 [1, 20] / 调幅 cap 1 步
    """
    import datetime as _dt
    from app.models import AuditLog, BacktestResult
    from app.services.config_service import get_config

    # 守: 创建/启动不足 2h 不动 (新策略让它自己跑跑看)
    if not strategy.created_at:
        return None
    age_h = (_dt.datetime.utcnow() - strategy.created_at).total_seconds() / 3600.0
    if age_h < RISK_MIN_LIVE_AGE_HOURS:
        return None

    # 6h cooldown
    cutoff = _dt.datetime.utcnow() - _dt.timedelta(hours=RISK_ADJUST_COOLDOWN_HOURS)
    last = AuditLog.query.filter(
        AuditLog.event_type == 'advisor_apply_strategy_risk',
        AuditLog.created_at > cutoff,
    ).all()
    if any((a.context or {}).get('strategy_id') == strategy.id for a in last):
        return None

    bt = _latest_backtest(strategy.id)
    sharpe = (bt.sharpe_ratio if bt else None) or 0
    # max_dd 不在所有 backtest 都有, fallback 给一个中性值
    max_dd = abs((bt.max_drawdown_pct if bt else None) or 20)

    params = dict(strategy.params or {})
    rp = dict(params.get('risk_params') or {})
    cur_lev = float(rp.get('leverage') or get_config().get('leverage') or 5)
    cur_size = float(rp.get('position_size_usdt') or get_config().get('trade_size_usdt') or 10)
    trade_size_default = float(get_config().get('trade_size_usdt') or 10)

    new_lev = cur_lev
    new_size = cur_size
    reasons = []

    # Sharpe / DD rule
    if sharpe >= 2.0 and max_dd < 25:
        # 健康 → 允许 +1 leverage
        new_lev = min(RISK_LEVERAGE_BOUNDS[1], cur_lev + RISK_LEVERAGE_STEP)
        if new_lev > cur_lev:
            reasons.append(f'回测 Sharpe {sharpe:.2f} 健康, max DD {max_dd:.1f}% 充裕 → 加杠杆')
    elif sharpe > 0 and sharpe < 1.0:
        new_lev = max(RISK_LEVERAGE_BOUNDS[0], cur_lev - RISK_LEVERAGE_STEP)
        if new_lev < cur_lev:
            reasons.append(f'回测 Sharpe {sharpe:.2f} 偏弱 → 降杠杆')

    # 目标 lag/ahead rule (覆盖 Sharpe 决策, 因为目标驱动优先)
    if not target_ctx.get('none'):
        if target_ctx.get('lag_mode') and sharpe >= 1.2:
            # 落后 + 策略不烂 → 加仓
            target_size = min(trade_size_default * RISK_POSITION_BOUNDS_FRAC[1],
                              cur_size * (1 + RISK_POSITION_STEP_FRAC))
            if target_size > cur_size * 1.05:
                new_size = round(target_size, 2)
                reasons.append(f'目标落后 {target_ctx.get("lag_pct", 0):.1f}% + Sharpe {sharpe:.2f} 可加仓')
        elif target_ctx.get('ahead_mode'):
            # 领先 → 保守, 降杠杆 (不一定就 cur_lev-1, 已被 sharpe 规则可能覆盖)
            new_lev = max(RISK_LEVERAGE_BOUNDS[0], min(new_lev, cur_lev - RISK_LEVERAGE_STEP))
            if new_lev < cur_lev:
                reasons.append(f'目标已领先 → 保守降杠杆')
        if target_ctx.get('dd_warn'):
            # DD 警戒 → 缩仓 (压过 lag 的加仓)
            target_size = max(trade_size_default * RISK_POSITION_BOUNDS_FRAC[0],
                              cur_size * (1 - RISK_POSITION_STEP_FRAC))
            if target_size < cur_size * 0.95:
                new_size = round(target_size, 2)
                reasons.append(f'DD 接近上限 {target_ctx.get("dd_pct", 0):.1f}% → 缩仓')

    # 还是没动 → 不出 item
    if abs(new_lev - cur_lev) < 0.01 and abs(new_size - cur_size) < 0.01:
        return None

    changes = {}
    if abs(new_lev - cur_lev) >= 0.01:
        changes['leverage'] = new_lev
    if abs(new_size - cur_size) >= 0.01:
        changes['position_size_usdt'] = new_size

    return {
        'action': 'adjust_strategy_risk',
        'strategy_id': strategy.id,
        'strategy_name': strategy.name,
        'severity': 'info',
        'reason': '; '.join(reasons) or 'AI 风险调整',
        'meta': {
            'current': {'leverage': cur_lev, 'position_size_usdt': cur_size},
            'new_risk_params': changes,
            'sharpe': sharpe,
            'max_dd': max_dd,
            'target_lag_pct': target_ctx.get('lag_pct'),
            'target_dd_pct': target_ctx.get('dd_pct'),
        },
    }


# ===== Phase 14k-29 L4-L6: AI 自动化突破回测护栏 =====

RISK_OPT_COOLDOWN_HOURS = 24       # 单策略 SL/TP 闪测 24h 一次
RISK_OPT_MIN_LIVE_AGE_HOURS = 6
SIGNAL_GRID_COOLDOWN_HOURS = 24    # 信号 grid optimization 24h 一次
INVENT_COOLDOWN_HOURS = 4          # 14k-60: 新策略 invent 12h → 4h (user 要更快循环)
INVENT_CANDIDATE_POOL_THRESHOLD = 5  # 候选池 qualified 数 < 这个 才考虑 invent


def _strategy_risk_opt_item(strategy) -> dict | None:
    """L4: 排 SL/TP 闪测. executor 触发 async task, task 内部跑 walk-forward + 过门槛 apply.

    14k-44 (撤回 14k-41 anti-pattern): 改 regime-aware force_optimize.
      - 横盘市场下 trend 策略 0 trades 是设计意图, 不是 bug → 不重测 (重测=追屁股)
      - 触发 force 的正确条件:
        · 7d+ 长期 0 trades (真长期空跑, 阈值确实有问题)
        · 或: 0 trades + regime MATCH (策略适合当前 regime 但阈值过严)
      - 0 trades + regime mismatch → 不动, 让 pause/retire 路径处理
    """
    import datetime as _dt
    from app.models import AuditLog, Trade

    if not strategy.created_at:
        return None
    age_h = (_dt.datetime.utcnow() - strategy.created_at).total_seconds() / 3600.0
    if age_h < RISK_OPT_MIN_LIVE_AGE_HOURS:
        return None

    # 14k-44: 长期空跑阈值按 timeframe 缩放 (复用 14k-30 GRACE_DAYS_BY_TF)
    # 15m=1d / 1h=2d / 4h=3d / 1d=7d / 1w=21d — 跟策略本身的 trade frequency 匹配
    idle_days = _grace_days(strategy.timeframe)
    trades_in_window = Trade.query.filter(
        Trade.strategy_id == strategy.id,
        Trade.exit_time > _dt.datetime.utcnow() - _dt.timedelta(days=idle_days),
    ).count()
    long_idle = (trades_in_window == 0 and age_h >= idle_days * 24)

    # 14k-44 + 14k-45 L1: 优先用 AI brief 判 fit (取代单一 regime_detector)
    force_optimize = False
    if long_idle:
        force_optimize = True
    else:
        trades_24h = Trade.query.filter(
            Trade.strategy_id == strategy.id,
            Trade.exit_time > _dt.datetime.utcnow() - _dt.timedelta(hours=24),
        ).count()
        if trades_24h == 0 and age_h >= 6:
            try:
                from app.services.regime_detector import detect_regime
                rd = detect_regime(strategy.symbol, strategy.timeframe)
                fit, _brief = _fit_with_brief(strategy.type, strategy.symbol, rd.get('regime'))
                if fit in ('good', 'ok'):
                    force_optimize = True
            except Exception:
                pass

    if not force_optimize:
        cutoff = _dt.datetime.utcnow() - _dt.timedelta(hours=RISK_OPT_COOLDOWN_HOURS)
        recent = AuditLog.query.filter(
            AuditLog.event_type.in_(['risk_opt_applied', 'risk_opt_no_lift', 'risk_opt_error', 'risk_opt_proposed']),
            AuditLog.created_at > cutoff,
        ).all()
        if any((a.context or {}).get('strategy_id') == strategy.id for a in recent):
            return None

    reason = '24h 未做 SL/TP 闪测, 排一次'
    if long_idle:
        reason = f'{idle_days}d+ 0 trades (按 {strategy.timeframe} TF) → 重测阈值'
    elif force_optimize:
        reason = '24h 0 trades + regime 适合 → 阈值可能过严, 重测'

    return {
        'action': 'optimize_strategy_risk_full',
        'strategy_id': strategy.id,
        'strategy_name': strategy.name,
        'severity': 'info',
        'reason': reason,
        'meta': {'force_optimize': force_optimize, 'long_idle': long_idle},
    }


def _signal_grid_propose_item(strategy, target_ctx: dict) -> dict | None:
    """L5: AI 提议信号 grid → 触发 ParamOptimization → 完成后由现有 apply_params 路径接走.

    14k-44 (撤回 14k-41 anti-pattern): regime-aware + TF-scaled long_idle
    """
    import datetime as _dt
    from app.models import AuditLog, ParamOptimization, Trade

    if not strategy.created_at:
        return None
    age_h = (_dt.datetime.utcnow() - strategy.created_at).total_seconds() / 3600.0
    if age_h < RISK_OPT_MIN_LIVE_AGE_HOURS:
        return None

    # 14k-44: TF-scaled long_idle (15m=1d / 1h=2d / 4h=3d / 1d=7d / 1w=21d)
    idle_days = _grace_days(strategy.timeframe)
    trades_in_window = Trade.query.filter(
        Trade.strategy_id == strategy.id,
        Trade.exit_time > _dt.datetime.utcnow() - _dt.timedelta(days=idle_days),
    ).count()
    long_idle = (trades_in_window == 0 and age_h >= idle_days * 24)

    # 14k-44: regime match 时才考虑 24h 0 trades (策略适合 current 但阈值过严)
    force_optimize = False
    if long_idle:
        force_optimize = True
    else:
        trades_24h = Trade.query.filter(
            Trade.strategy_id == strategy.id,
            Trade.exit_time > _dt.datetime.utcnow() - _dt.timedelta(hours=24),
        ).count()
        if trades_24h == 0 and age_h >= 6:
            try:
                from app.services.regime_detector import detect_regime, fit_label
                rd = detect_regime(strategy.symbol, strategy.timeframe)
                regime = rd.get('regime', 'unknown')
                fit = fit_label(strategy.type, regime)
                if fit in ('good', 'ok'):
                    force_optimize = True
                # mismatch → 不重测, 让 pause 路径处理
            except Exception:
                pass

    if not force_optimize:
        cutoff = _dt.datetime.utcnow() - _dt.timedelta(hours=SIGNAL_GRID_COOLDOWN_HOURS)
        recent_opt = ParamOptimization.query.filter(
            ParamOptimization.strategy_id == strategy.id,
            ParamOptimization.started_at > cutoff,
        ).first()
        if recent_opt:
            return None

    # 触发条件: target lag mode 或 现有 sharpe 偏弱 或 0 trades 空跑
    needs_optim = bool(target_ctx.get('lag_mode')) or force_optimize
    if not needs_optim:
        bt = _latest_backtest(strategy.id)
        sharpe = (bt.sharpe_ratio if bt else None) or 0
        needs_optim = sharpe < 1.5

    if not needs_optim:
        return None

    if not force_optimize:
        # 24h 内 audit 标记防重排
        audit_cutoff = _dt.datetime.utcnow() - _dt.timedelta(hours=SIGNAL_GRID_COOLDOWN_HOURS)
        recent_audit = AuditLog.query.filter(
            AuditLog.event_type == 'signal_grid_proposed',
            AuditLog.created_at > audit_cutoff,
        ).all()
        if any((a.context or {}).get('strategy_id') == strategy.id for a in recent_audit):
            return None

    # 14k-30 #2: 调 LLM 让 AI 真提议 grid
    proposed_grid = None
    rationale = None
    try:
        from app.services.llm_prompts.grid_proposer import propose_signal_grid as _propose
        bt = _latest_backtest(strategy.id)
        metrics = {
            'oos_sharpe': bt.sharpe_ratio if bt else None,
            'oos_dd': bt.max_drawdown_pct if bt else None,
            'win_rate': bt.win_rate if bt else None,    # 14k-65: 字段名是 win_rate 不是 win_rate_pct
            'trades': bt.total_trades if bt else None,
        }
        r = _propose(strategy.type, strategy.params or {}, metrics)
        if r.get('ok'):
            proposed_grid = r.get('grid')
            rationale = r.get('rationale')
    except Exception as e:
        print(f'[advisor] grid_proposer LLM failed: {type(e).__name__}: {e}')

    return {
        'action': 'propose_signal_grid',
        'strategy_id': strategy.id,
        'strategy_name': strategy.name,
        'severity': 'info',
        'reason': rationale or '需要参数优化, 排一次 walk-forward grid search',
        'meta': {
            'target_lag_mode': bool(target_ctx.get('lag_mode')),
            'proposed_grid': proposed_grid,  # AI 提议的 grid (None 则 fallback 死字典)
            'rationale': rationale,
        },
    }


def _promote_eligible_count(user_id: int | None = None) -> int:
    """14k-50/51/54: qualified 池里真能 promote 的数. 两条路径:
    A. catalog / catalog_clone: 看 catalog_meta.verified_oos_sharpe (走 _maybe_auto_apply)
    B. synth / research / improve / github: 看 backtest_result_id walkforward_json out_sample

    14k-54: 加 user_id scope — None=全局 (catalog 全局共享); user_id=N → catalog NULL + user N 私池
    """
    from app.models import StrategyCandidate, BacktestResult
    q = StrategyCandidate.query.filter_by(status='qualified')
    if user_id is not None:
        # catalog 全局 (user_id IS NULL) ∪ 该 user 自己的 individual
        from sqlalchemy import or_
        q = q.filter(or_(StrategyCandidate.user_id.is_(None),
                         StrategyCandidate.user_id == user_id))
    qualified = q.all()
    eligible = 0
    for c in qualified:
        # A. catalog 路径 — verified_oos_sharpe
        cm = c.catalog_meta or {}
        verified = cm.get('verified_oos_sharpe')
        if verified is not None and float(verified) >= PROMOTE_MIN_OOS_SHARPE:
            eligible += 1
            continue
        # B. individual backtest 路径
        if not c.backtest_result_id:
            continue
        bt = BacktestResult.query.get(c.backtest_result_id)
        if not bt or not bt.walkforward_json:
            continue
        oos_sh = (bt.walkforward_json.get('out_sample') or {}).get('sharpe_ratio')
        if oos_sh is not None and oos_sh >= PROMOTE_MIN_OOS_SHARPE:
            eligible += 1
    return eligible


def _system_dry_spell(user_id: int) -> tuple[bool, dict]:
    """14k-49 Trigger T2: 系统干旱期 — 当前 running 策略 24h 0 trades + 7d <3 trades.
    旧 stopped 策略的 trades 不算 (它们退了就不该影响判断).
    返回 (triggered, info_dict).
    """
    import datetime as _dt
    from app.models import Trade, Strategy
    from app.services.user_scope import apply_user_filter
    running_ids = [s.id for s in apply_user_filter(
        Strategy.query.filter_by(status='running'), Strategy).all()]
    if not running_ids:
        return False, {'reason': 'no running strategies'}
    now = _dt.datetime.utcnow()
    trades_24h = Trade.query.filter(
        Trade.strategy_id.in_(running_ids),
        Trade.exit_time > now - _dt.timedelta(hours=24)
    ).count()
    trades_7d = Trade.query.filter(
        Trade.strategy_id.in_(running_ids),
        Trade.exit_time > now - _dt.timedelta(days=7)
    ).count()
    triggered = trades_24h == 0 and trades_7d < 3
    return triggered, {'trades_24h': trades_24h, 'trades_7d': trades_7d,
                       'running_strategies': len(running_ids)}


def _tf_coverage_gap(user_id: int | None = None) -> tuple[bool, dict, str | None]:
    """14k-49 Trigger T3: TF 偏科 — 15m/30m qualified=0 但 4h qualified>5.
    14k-54: 加 user_id scope (catalog NULL ∪ user 私池).
    返回 (triggered, info_dict, missing_tf).
    """
    from app.models import StrategyCandidate
    from sqlalchemy import or_
    q_by_tf = {}
    for tf in ('15m', '30m', '1h', '4h', '1d'):
        q = StrategyCandidate.query.filter_by(status='qualified', timeframe=tf)
        if user_id is not None:
            q = q.filter(or_(StrategyCandidate.user_id.is_(None),
                             StrategyCandidate.user_id == user_id))
        q_by_tf[tf] = q.count()
    # 高频 TF 候选稀薄 + swing TF 充裕 → gap
    # (短 TF total < 3 算稀薄, 因为 scalp/reversion 风格多样, 1-2 个候选不够 AI 选)
    short_tf_total = q_by_tf['15m'] + q_by_tf['30m']
    swing_tf_total = q_by_tf['4h'] + q_by_tf['1d']
    if short_tf_total < 3 and swing_tf_total >= 5:
        # 优先补 15m (业界主流 scalp TF), 除非 15m 已经>0 才补 30m
        missing = '15m' if q_by_tf['15m'] == 0 else ('30m' if q_by_tf['30m'] < 2 else '15m')
        return True, q_by_tf, missing
    return False, q_by_tf, None


def _regime_archetype_mismatch(user_id: int) -> tuple[bool, dict]:
    """14k-49 Trigger T4: 当前 running 策略 archetype 跟市场 regime 不匹配.
    比 brief.recommended_archetype 跟 running.category 不同 → 组合错配.
    """
    from app.models import Strategy
    from app.services.user_scope import apply_user_filter
    from app.services.llm_prompts.market_analyst import analyze_market
    try:
        running = apply_user_filter(
            Strategy.query.filter_by(status='running'), Strategy
        ).all()
    except Exception:
        return False, {}
    if not running:
        return False, {'running_count': 0}
    # 拉 brief (走 cache, 不重 LLM)
    sym = running[0].symbol
    try:
        brief_r = analyze_market(sym, timeframes=['1h', '4h'], user_id=user_id)
    except Exception:
        return False, {}
    if not brief_r.get('ok'):
        return False, {}
    arch = brief_r['brief'].get('recommended_archetype')
    if arch in (None, 'wait'):
        return False, {'archetype': arch}
    # 现有 strategy.category 映射到 archetype
    cat_to_arch = {
        'swing': 'trend_follower', 'long': 'trend_follower',
        'short': 'mean_reverter',  'ultra': 'mean_reverter',
    }
    running_archs = set(cat_to_arch.get(s.category) for s in running if s.category)
    triggered = arch not in running_archs and len(running_archs) > 0
    return triggered, {'brief_archetype': arch, 'running_archetypes': list(running_archs),
                       'mismatch_symbol': sym}


def _invent_new_strategy_item(user_id: int, target_ctx: dict) -> dict | None:
    """14k-29 L6 + 14k-49 多 trigger: 主动让 AI 创新策略.

    OR 多 trigger (任一满足即触发, per-trigger 独立 cooldown):
      T1 lag_pool_thin   — 目标落后 + qualified<5 (旧) → catalog-first
      T2 dry_spell       — 24h 0 trades + 7d <3 trades → LLM synth 高频
      T3 tf_gap          — 15m/30m qualified=0 + 4h >5 → LLM synth 指定 TF
      T4 regime_mismatch — brief.archetype 跟 running 不匹配 → LLM synth 互补

    Cooldown: 12h per trigger type (每天最多 4 次 invent, 不爆 LLM token).
    """
    import datetime as _dt
    from app.models import AuditLog, StrategyCandidate

    if target_ctx.get('none'):
        return None

    # 全局 12h cooldown: 任何 invent 事件 12h 内 → 跳过 (保守, 避免叠加触发)
    cutoff = _dt.datetime.utcnow() - _dt.timedelta(hours=INVENT_COOLDOWN_HOURS)
    recent = AuditLog.query.filter(
        AuditLog.event_type.in_(['advisor_invent_proposed', 'advisor_invent_applied', 'advisor_invent_error']),
        AuditLog.created_at > cutoff,
    ).first()
    if recent:
        return None

    # 14k-50/54: 看 promote-eligible (OOS≥1.5) 而非 qualified count + per-user scope
    eligible_pool = _promote_eligible_count(user_id)

    # T1 (旧): lag + 真正可上线池薄 → catalog-first invent
    if target_ctx.get('lag_mode') and eligible_pool < INVENT_CANDIDATE_POOL_THRESHOLD:
        return {
            'action': 'invent_new_strategy',
            'strategy_id': 0,
            'strategy_name': '寻找新策略 (落后追赶)',
            'severity': 'info',
            'reason': f'目标进度落后 {target_ctx.get("lag_pct", 0):.1f}%, 可用策略只剩 {eligible_pool} 个, AI 去找点新的来追赶',
            'meta': {
                'user_id': user_id,
                'trigger_type': 'lag_pool_thin',
                'invent_method': 'catalog_first',
                'lag_pct': target_ctx.get('lag_pct'),
                'eligible_pool': eligible_pool,
            },
        }

    # T2 dry_spell — 系统连续 0 trades → LLM synth 高频策略
    dry_triggered, dry_info = _system_dry_spell(user_id)
    if dry_triggered:
        return {
            'action': 'invent_new_strategy',
            'strategy_id': 0,
            'strategy_name': '寻找新策略 (最近没开单)',
            'severity': 'warn',
            'reason': f'最近一天没开过单, 一周才 {dry_info["trades_7d"]} 单. AI 想试试更敏感的短线策略, 多抓机会',
            'meta': {
                'user_id': user_id,
                'trigger_type': 'dry_spell',
                'invent_method': 'synth',
                'synth_hint': 'dry_spell',
                **dry_info,
            },
        }

    # T3 tf_gap — 高频 TF 候选空 + swing TF 充裕 → synth 指定 TF
    tf_triggered, tf_info, missing_tf = _tf_coverage_gap(user_id)
    if tf_triggered:
        tf_label = {'15m': '15 分钟短线', '30m': '半小时短线', '1h': '1 小时'}.get(missing_tf, missing_tf)
        return {
            'action': 'invent_new_strategy',
            'strategy_id': 0,
            'strategy_name': f'寻找新策略 ({tf_label})',
            'severity': 'info',
            'reason': f'目前长线策略 {tf_info["4h"]+tf_info["1d"]} 个但短线 ({tf_label}) 一个都没有, AI 去补齐这个时段的策略',
            'meta': {
                'user_id': user_id,
                'trigger_type': 'tf_gap',
                'invent_method': 'synth',
                'synth_hint': 'tf_gap',
                'target_timeframe': missing_tf,
                'tf_distribution': tf_info,
            },
        }

    # T4 regime_mismatch — brief vs running 不匹配 → synth 互补 archetype
    rm_triggered, rm_info = _regime_archetype_mismatch(user_id)
    if rm_triggered:
        arch_zh = {'trend_follower': '趋势跟随', 'mean_reverter': '反弹回归',
                   'breakout': '突破', 'wait': '观望'}
        market_say = arch_zh.get(rm_info["brief_archetype"], rm_info["brief_archetype"])
        running_say = '+'.join(arch_zh.get(a, a) for a in rm_info["running_archetypes"])
        return {
            'action': 'invent_new_strategy',
            'strategy_id': 0,
            'strategy_name': '寻找新策略 (跟市场不搭)',
            'severity': 'info',
            'reason': f'市场现在适合「{market_say}」, 但你现有策略都是「{running_say}」, AI 找互补的来配',
            'meta': {
                'user_id': user_id,
                'trigger_type': 'regime_mismatch',
                'invent_method': 'synth',
                'synth_hint': 'regime_mismatch',
                'symbol': rm_info.get('mismatch_symbol'),
                **rm_info,
            },
        }

    # 没 trigger 匹配
    return None
