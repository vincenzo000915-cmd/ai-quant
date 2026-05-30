"""Phase 15 UI 重构: 守门员驾驶舱数据层 — 给新 Dashboard 所有块的数据 (一次 fetch)。

规格 project-ui-redesign-spec. 块: ①HERO目标驱动 ②信号预告 ③守门员台 ④AI经理判断流
⑤策略库+覆盖 ⑥飞轮经验. tier 分层由前端按 user.subscription_tier 显隐.
"""
from __future__ import annotations


def _signal_preview(symbols, base_tf='15m'):
    """信号预告: 每标的当下行情 + 匹配策略 + 即将触发什么 (Basic 照此手动, 守门员自动接)。
    = 守门员感知+配对层只读暴露 (不下单)。"""
    from app.services.exchange_service import fetch_ohlcv
    from app.services.market_perception import perceive_market
    from app.services.gatekeeper import match_with_perception
    from app.services.strategy_engine import get_signal, get_candle_df
    from app.services.llm_prompts.strategy_profile import strategy_display_name
    out = []
    for sym in symbols:
        try:
            base = [dict(o=x['open'], h=x['high'], l=x['low'], c=x['close']) for x in []]  # placeholder
            raw_b = fetch_ohlcv(sym, base_tf, limit=400) or []
            raw_a = fetch_ohlcv(sym, '5m', limit=1200) or []
            to_c = lambda r: [{'open': x['open'], 'high': x['high'], 'low': x['low'],
                               'close': x['close'], 'volume': x['volume'], 'timestamp': x['timestamp']} for x in r]
            b = to_c(raw_b); a = to_c(raw_a)
            if len(b) < 60 or len(a) < 60:
                out.append({'symbol': sym, 'ok': False, 'reason': '数据不足'}); continue
            b = [c for c in b if c['timestamp'] >= a[0]['timestamp']]
            perc = perceive_market(sym, b, a, base_tf)
            scored = match_with_perception(perc, base_tf) if perc.get('ok') else []
            df = get_candle_df([dict(c) for c in b])
            matched = []
            for s in scored[:6]:
                try:
                    sig = get_signal(s['strategy'], df, {})
                    triggering = sig in ('buy', 'sell', 'long', 'short')
                    matched.append({'strategy': s['strategy'], 'name': strategy_display_name(s['strategy']),
                                    'score': s['score'], 'triggering': triggering,
                                    'side': ('做多' if sig in ('buy', 'long') else ('做空' if sig in ('sell', 'short') else None)),
                                    'reasons': s.get('reasons', [])[:2]})
                except Exception:
                    continue
            out.append({'symbol': sym, 'ok': True,
                        'regime': perc.get('regime'), 'direction': perc.get('direction'),
                        'volatility': perc.get('volatility'), 'volume': perc.get('volume'),
                        'momentum': (perc.get('price_action') or {}).get('momentum'),
                        'matched': matched,
                        'about_to_trigger': [m for m in matched if m['triggering']]})
        except Exception as e:
            out.append({'symbol': sym, 'ok': False, 'reason': f'{type(e).__name__}: {e}'})
    return out


def gatekeeper_dashboard_data(user_id: int = 1) -> dict:
    """新 Dashboard 一次 fetch 全部块数据。"""
    from app.services.config_service import get_config
    from app.services.gatekeeper_live import WATCHED_SYMBOLS
    from app.services.gatekeeper_live import _target_and_days
    from app.models import StrategyProfile, GatekeeperDecision, Position
    from app.services.llm_prompts.strategy_profile import coverage_summary, strategy_display_name
    from app.services.gatekeeper_learning import summarize_experience

    cfg = get_config()
    target_pct, days = _target_and_days()

    # ① HERO 状态
    mode = cfg.get('gatekeeper_live_mode', 'off')
    gk_positions = (Position.query.filter_by(status='open')
                    .filter(Position.gatekeeper_decision_id.isnot(None)).all())

    # ④ AI 经理判断流 (最近决策: 给参/skip)
    recent = (GatekeeperDecision.query.filter_by(source='live')
              .order_by(GatekeeperDecision.id.desc()).limit(15).all())
    manager_log = []
    for d in recent:
        manager_log.append({
            'symbol': d.symbol, 'regime': d.regime, 'direction': d.direction,
            'action': d.action, 'strategy': strategy_display_name(d.strategy) if d.strategy else None,
            'expected_ev': d.expected_ev, 'realized_pnl': d.realized_pnl, 'outcome': d.outcome,
            'created_at': d.created_at.isoformat() if d.created_at else None,
        })

    # ⑤ 策略库 + 覆盖
    cov = coverage_summary()
    lib_count = StrategyProfile.query.count()

    # ⑥ 飞轮经验
    exp = summarize_experience(min_samples=1)[:10]

    return {
        'hero': {
            'target_pct': target_pct, 'days_remaining': days,
            'gatekeeper_mode': mode, 'halted': cfg.get('halted'),
            'open_positions': [{'symbol': p.symbol, 'side': p.side, 'entry': p.entry_price,
                                'unrealized_pnl': p.unrealized_pnl,
                                'strategy': strategy_display_name((p.gk_exit or {}).get('strategy'))} for p in gk_positions],
        },
        'signal_preview': _signal_preview(WATCHED_SYMBOLS),
        'gatekeeper': {
            'mode': mode, 'watched': WATCHED_SYMBOLS, 'library_size': lib_count,
            'open_count': len(gk_positions),
        },
        'manager_log': manager_log,
        'library': {
            'count': lib_count,
            'coverage': cov.get('grid'), 'gaps': cov.get('gaps'), 'core_thin': cov.get('core_thin'),
        },
        'flywheel': exp,
    }
