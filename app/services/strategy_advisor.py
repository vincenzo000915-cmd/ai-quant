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
APPLY_PARAMS_LIFT = 0.5    # OOS Sharpe must beat baseline by this much
RETIRE_MIN_SHARPE_DIFF = 0.5    # 兩支 Sharpe 差距 < 0.5 不算明顯，不推 retire
RETIRE_GRACE_DAYS = 7      # 創建 < 7 天的策略不推 retire（跟 monitor_strategy_health 同步）
RETIRE_REQUIRE_POSITIVE_KEEP = True   # 留下的那支 Sharpe 必須 > 0，否則「保留較好的」沒意義


def _latest_backtest_sharpe(strategy_id: int) -> float | None:
    bt = (
        BacktestResult.query
        .filter_by(strategy_id=strategy_id, status='completed')
        .order_by(BacktestResult.created_at.desc())
        .first()
    )
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

    # 2) regime 不匹配 → pause / 用 fan-out 換到適合的市場
    regime_cache: dict[tuple, str] = {}
    for s in running:
        key = (s.symbol, s.timeframe)
        if key not in regime_cache:
            regime_cache[key] = detect_regime(s.symbol, s.timeframe).get('regime', 'unknown')
        regime = regime_cache[key]
        fit = fit_label(s.type, regime)
        if fit == 'bad':
            items.append({
                'action': 'pause',
                'strategy_id': s.id,
                'strategy_name': s.name,
                'severity': 'warn',
                'reason': (
                    f'類型 {affinity_for(s.type)} 與當前 {s.symbol} {s.timeframe} 市場狀態 '
                    f'({regime}) 不匹配，歷史上這個組合通常虧損。建議暫停或先做 walk-forward 驗證。'
                ),
                'meta': {'regime': regime, 'affinity': affinity_for(s.type)},
            })

    # 3) 最新優化 → 套用最佳參數
    for s in running:
        opt = _latest_completed_optimization(s.id)
        if not opt or not opt.best_params or opt.best_oos_sharpe is None:
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

    # 5) fan-out 機會 — Sharpe 高、單一幣種、沒兄弟
    for s in running:
        sh = sharpe_by_id.get(s.id)
        if sh is None or sh < 2.0:
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
                        f'Sharpe {sh:.2f} 表現良好但只跑 {s.symbol}。考慮一鍵 fan-out 到 ETH/SOL/AVAX '
                        f'等其他幣種分散單一資產風險。'
                    ),
                    'meta': {'current_symbol': s.symbol, 'sharpe': sh},
                })

    # 6) 合格候選 → promote 上線（Phase 10.10）
    qualified_cands = (
        StrategyCandidate.query
        .filter_by(status='qualified')
        .filter(StrategyCandidate.promoted_strategy_id.is_(None))
        .all()
    )
    for c in qualified_cands:
        bt = c.backtest
        if not bt:
            continue
        wf = (bt.walkforward_json or {}).get('out_sample') or {}
        oos = wf.get('sharpe_ratio')
        if oos is None:
            continue
        items.append({
            'action': 'promote_candidate',
            'strategy_id': None,
            'strategy_name': c.source_name or f'候選 #{c.id}',
            'severity': 'info',
            'reason': (
                f'候選 #{c.id} ({c.candidate_type}) 已通過 walk-forward 驗證 — '
                f'OOS Sharpe = {oos:.2f}。建議 promote 上線。'
            ),
            'meta': {
                'candidate_id': c.id,
                'oos_sharpe': oos,
                'candidate_type': c.candidate_type,
                'symbol': 'BTC/USDT',
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
