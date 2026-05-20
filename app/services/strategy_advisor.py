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
RETIRE_GRACE_DAYS = 7           # 創建 < 7 天的策略不推 retire（跟 monitor_strategy_health 同步）
RETIRE_REQUIRE_POSITIVE_KEEP = True   # 留下的那支 Sharpe 必須 > 0，否則「保留較好的」沒意義
PAUSE_GRACE_DAYS = 7            # pause 推薦也走 grace
PROMOTE_MIN_OOS_SHARPE = 1.5    # promote_candidate 至少這 Sharpe 才推（跟 executor 阈值同步）
FAN_OUT_MIN_SHARPE = 2.0
FAN_OUT_BACKTEST_MAX_AGE_DAYS = 14   # backtest 太老 → 不推 fan_out
FAN_OUT_GRACE_DAYS = 7


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


def build_recommendations() -> dict:
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
    grace_cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=RETIRE_GRACE_DAYS)

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

        # check 6: 7 天保護期 — 新策略還沒累積 live 數據，不該被 backtest fallback 殺
        if drop.created_at and drop.created_at > grace_cutoff:
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

    # 2) regime 不匹配 → pause（Phase 12.12: 加 grace + open position + 數據可靠檢查）
    pause_grace_cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=PAUSE_GRACE_DAYS)
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
        # check: 7 天 grace — 新策略還沒累積實盤數據
        if s.created_at and s.created_at > pause_grace_cutoff:
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
        beats_baseline = baseline is None or (best - baseline) >= APPLY_PARAMS_LIFT
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

    # 5) fan-out 機會（Phase 12.12: 加 backtest freshness + 7 天 grace）
    fanout_age_cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=FAN_OUT_BACKTEST_MAX_AGE_DAYS)
    fanout_grace_cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=FAN_OUT_GRACE_DAYS)
    for s in running:
        # check: 7 天 grace — 新策略還沒累積實盤數據，先別 fan-out
        if s.created_at and s.created_at > fanout_grace_cutoff:
            continue
        bt = _latest_backtest(s.id)
        if not bt or bt.sharpe_ratio is None or bt.sharpe_ratio < FAN_OUT_MIN_SHARPE:
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
    # dedup: 已有同 candidate_type + symbol running 策略 → 跳過（避免重複上線）
    existing_types = {(s.type, s.symbol) for s in Strategy.query.filter(
        Strategy.status.in_(['running', 'stopped'])
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
        # check: dedup — 同類型同 symbol 已存在 → 跳過
        target_symbol = 'BTC/USDT'
        if (c.candidate_type, target_symbol) in existing_types:
            continue
        items.append({
            'action': 'promote_candidate',
            'strategy_id': None,
            'strategy_name': c.source_name or f'候選 #{c.id}',
            'severity': 'info',
            'reason': (
                f'候選 #{c.id} ({c.candidate_type}) 已通過 walk-forward 驗證 — '
                f'OOS Sharpe = {oos:.2f} ≥ {PROMOTE_MIN_OOS_SHARPE}。建議 promote 上線。'
            ),
            'meta': {
                'candidate_id': c.id,
                'oos_sharpe': oos,
                'candidate_type': c.candidate_type,
                'symbol': target_symbol,
                'source': c.source,
            },
        })

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
    }
