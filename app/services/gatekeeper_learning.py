"""Phase 15 学习飞轮: 守门员决策经验 — 记录 → 聚合 → 喂回合成 AI

蓝图 project-phase15-blueprint 九.6 (user 2026-05-30 愿景, 北极星 P&L 校准+边学):
  守门员每次决策结果 (什么策略 × 什么市场 × 什么参数 → EV) 记录 → 经验积累 →
  整合经验 → AI 写新策略 (基于学到的"什么 work", 非盲合成, 成功率更高).

本模块 = 飞轮的"记录 + 经验积累 + 整合"三段 (offline 先积累回测决策经验; 接 live 后
record_outcome 回填真盈亏 → 完整 P&L 校准). 合成那一段在 strategy_synthesize_v2 step1
注入 experience_block.

⚠️ 铁律 (project-phase15-blueprint 十): 经验是方向性参考非稳赚保证; 样本小要诚实标注,
不能因 n 小的结果好坏就断言 edge 有无. 聚合阈值 min_samples 防过拟合单笔噪音.
"""
from __future__ import annotations


def record_decision(decision: dict, symbol: str, timeframe: str,
                    perception: dict | None = None, source: str = 'offline',
                    realized_pnl: float | None = None) -> int | None:
    """记录守门员一次决策。decision = gatekeeper_decide 返回的 dict。
    realized_pnl 可在记录时直接给 (offline 段回测已知结果), 也可后续 record_outcome 回填 (live)。
    返回 decision row id (失败返回 None, 学习记录不该阻断主流程)。"""
    try:
        from app.models import db, GatekeeperDecision
        perc = perception or decision.get('perception') or {}
        pa = perc.get('price_action') or {}
        params = decision.get('params')
        row = GatekeeperDecision(
            symbol=symbol, timeframe=timeframe,
            regime=decision.get('regime') or perc.get('regime'),
            direction=decision.get('direction') or perc.get('direction'),
            volatility=perc.get('volatility'),
            volume=perc.get('volume'),
            mtf_aligned=perc.get('mtf_aligned'),
            hunt=pa.get('hunt'),
            action=decision.get('action'),
            strategy=decision.get('strategy'),
            match_score=decision.get('match_score'),
            params=params,
            expected_ev=decision.get('expected_ev'),
            realized_pnl=realized_pnl,
            outcome=_classify_outcome(realized_pnl),
            source=source,
            context=_compact_context(perc),
        )
        db.session.add(row)
        db.session.commit()
        return row.id
    except Exception as e:
        try:
            from app.models import db
            db.session.rollback()
        except Exception:
            pass
        print(f'[gatekeeper_learning] record_decision error: {type(e).__name__}: {e}')
        return None


def record_outcome(decision_id: int, realized_pnl: float) -> bool:
    """回填一次决策的实测/实盘结果 (offline 段回测平仓 / live 真平仓后)。"""
    try:
        from app.models import db, GatekeeperDecision
        row = db.session.get(GatekeeperDecision, decision_id)
        if not row:
            return False
        row.realized_pnl = realized_pnl
        row.outcome = _classify_outcome(realized_pnl)
        db.session.commit()
        return True
    except Exception as e:
        try:
            from app.models import db
            db.session.rollback()
        except Exception:
            pass
        print(f'[gatekeeper_learning] record_outcome error: {type(e).__name__}: {e}')
        return False


def _classify_outcome(pnl: float | None) -> str | None:
    if pnl is None:
        return None
    if pnl > 0:
        return 'win'
    if pnl < 0:
        return 'loss'
    return 'flat'


def _compact_context(perc: dict) -> dict:
    """存精简感知快照 (富学习用, 不存整个 indicators 防膨胀)。"""
    if not perc:
        return {}
    ind = perc.get('indicators') or {}
    pa = perc.get('price_action') or {}
    return {
        'vol_pct': perc.get('vol_pct'), 'vol_ratio': perc.get('vol_ratio'),
        'aux_regime': perc.get('aux_regime'),
        'funding': perc.get('funding'),
        'pattern': pa.get('pattern'), 'momentum': pa.get('momentum'),
        'ind_states': {k: (v or {}).get('state') for k, v in ind.items()
                       if isinstance(v, dict)},
    }


def summarize_experience(timeframe: str | None = None, min_samples: int = 3,
                         only_realized: bool = True) -> list[dict]:
    """聚合决策记录看"什么策略×什么市场格子→盈利". 按 (regime, direction, timeframe, strategy)
    分桶, 算: 样本数 / 平均实测pnl / 胜率 / 平均预期EV / 预期vs实测偏差.
    only_realized=True 只看有 realized_pnl 的 (真知道结果的); min_samples 过滤过拟合噪音.
    返回按 avg_realized 降序 (学到的赢家在前)。"""
    try:
        from app.models import GatekeeperDecision
        q = GatekeeperDecision.query.filter(GatekeeperDecision.action == 'enter',
                                            GatekeeperDecision.strategy.isnot(None))
        if timeframe:
            q = q.filter(GatekeeperDecision.timeframe == timeframe)
        if only_realized:
            q = q.filter(GatekeeperDecision.realized_pnl.isnot(None))
        rows = q.all()
    except Exception as e:
        print(f'[gatekeeper_learning] summarize error: {type(e).__name__}: {e}')
        return []

    buckets: dict = {}
    for r in rows:
        key = (r.regime, r.direction, r.timeframe, r.strategy)
        b = buckets.setdefault(key, {'n': 0, 'pnls': [], 'evs': [], 'wins': 0})
        b['n'] += 1
        if r.realized_pnl is not None:
            b['pnls'].append(r.realized_pnl)
            if r.realized_pnl > 0:
                b['wins'] += 1
        if r.expected_ev is not None:
            b['evs'].append(r.expected_ev)

    out = []
    for (regime, direction, tf, strat), b in buckets.items():
        nr = len(b['pnls'])
        if nr < min_samples:
            continue
        avg_realized = sum(b['pnls']) / nr
        avg_ev = (sum(b['evs']) / len(b['evs'])) if b['evs'] else None
        out.append({
            'regime': regime, 'direction': direction, 'timeframe': tf,
            'strategy': strat, 'samples': nr,
            'avg_realized_pnl': round(avg_realized, 4),
            'win_rate': round(b['wins'] / nr, 3),
            'avg_expected_ev': round(avg_ev, 4) if avg_ev is not None else None,
            # 预期 vs 实测偏差: 守门员回测准不准 (正=实测好于预期, 负=高估)
            'ev_bias': (round(avg_realized - avg_ev, 4)
                        if avg_ev is not None else None),
        })
    return sorted(out, key=lambda x: -x['avg_realized_pnl'])


def experience_block(timeframe: str | None = None, min_samples: int = 3,
                     max_lines: int = 8) -> str:
    """给合成 AI 的"学到的经验"文本块。基于守门员历史决策实测, 告诉 AI:
    哪些 (策略×市场格子) 实测盈利可借鉴方向 / 哪些亏损要避开 → 写新策略基于"什么 work"。
    无足够样本返回空串 (诚实: 没积累够就不瞎给经验)。"""
    exp = summarize_experience(timeframe=timeframe, min_samples=min_samples)
    if not exp:
        return ''
    winners = [e for e in exp if e['avg_realized_pnl'] > 0][:max_lines]
    losers = [e for e in exp if e['avg_realized_pnl'] <= 0]
    lines = ['## 守门员实测经验 (历史决策回测积累, 方向性参考非稳赚)']
    if winners:
        lines.append('实测盈利的 (策略 @ 市场格子, 可借鉴这类信号/方向):')
        for e in winners:
            lines.append(
                '  ✓ %s @ %s/%s/%s — 实测均pnl%+.3f 胜率%.0f%% (n=%d)' % (
                    e['strategy'], e['regime'], e['direction'], e['timeframe'],
                    e['avg_realized_pnl'], e['win_rate'] * 100, e['samples']))
    if losers:
        lines.append('实测亏损的 (避开这类格子或别照搬):')
        for e in losers[:3]:
            lines.append('  ✗ %s @ %s/%s/%s — 实测均pnl%+.3f (n=%d)' % (
                e['strategy'], e['regime'], e['direction'], e['timeframe'],
                e['avg_realized_pnl'], e['samples']))
    lines.append('→ 基于"什么 work"的方向写新假设, 别盲目模仿教科书; 样本小=方向非保证.')
    return '\n'.join(lines)
