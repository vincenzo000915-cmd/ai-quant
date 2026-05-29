"""Phase 15 核心: 守门员实时循环 (offline 骨架, 不接 live)

蓝图 project-phase15-blueprint 第九节。user 定的正确循环 (取代原"静态回测筛选"儿戏守门):
  持续扫描市场 × 策略池 → 按画像匹配适合的策略 → 信号触发 → AI给参/优化 → 即时回测选最优EV → 下单.

本模块 = 守门员"一次决策"的编排 (offline 返回决策, 不真下单):
  ① 市场感知: 当前 regime (趋势/震荡)
  ② 画像匹配: 按 regime+周期 从 strategy_profiles 选适合的策略子集 (不懂策略=儿戏, 故靠画像)
  ③ 信号检测: 匹配策略里哪个此刻触发
  ④ 参数优化: 对触发策略, 难度基调约束下 walk-forward 找最优参数 EV (=测最优参数)
  ⑤ 选最优: 多触发→选 EV 最高的 → 决策 enter / 否则 wait

⚠️ offline: 返回"该下单的策略+参数+预期EV"决策, 不接 live. 接 live(实时扫描+真下单)等观察期满+过门.
"""
from __future__ import annotations

MIN_EV = 0.0   # offline 验证用; live 时应 > fee buffer (与 synthesize MIN_EXPECTED_VALUE_PCT 对齐)


def regime_from_candles(candles: list) -> str:
    """从 candles 算 regime (趋势/震荡), 不实时查 DB (回测时点正确)。
    复用 regime_detector 纯函数 (_classify + hurst), adx 用 ta。返回 trend|range|unknown。"""
    if not candles or len(candles) < 60:
        return 'unknown'
    try:
        import pandas as pd
        import ta
        from app.services.regime_detector import _classify, hurst_exponent
        df = pd.DataFrame(candles)
        adx_s = ta.trend.adx(df['high'], df['low'], df['close'], window=14)
        adx = float(adx_s.iloc[-1]) if not adx_s.dropna().empty else None
        hurst = hurst_exponent(df['close'].values, max_lag=min(100, len(df) // 3))
        cls = _classify(adx, hurst)   # strong_trend/weak_trend/range/unknown
        if 'trend' in cls:
            return 'trend'
        if cls == 'range':
            return 'range'
        return 'unknown'
    except Exception:
        return 'unknown'


def match_strategies(regime: str, timeframe: str) -> list:
    """画像匹配: 按 regime + 周期 选适合的策略 (查 strategy_profiles)。
    trend→regime_fit.trend=good; range→range=good; 且 timeframe_fit 含该周期。"""
    from app.models import StrategyProfile
    want = 'trend' if regime == 'trend' else 'range'
    out = []
    for p in StrategyProfile.query.all():
        prof = p.profile or {}
        rf = prof.get('regime_fit', {})
        tff = ' '.join(str(x) for x in (prof.get('timeframe_fit') or []))
        if rf.get(want) == 'good' and timeframe in tff:
            out.append(p.strategy_type)
    return out


def _optimize_params(stype, base_is, aux, base_tf, lev=10.0):
    """对一个策略, IS 段扫 SL 宽度找最优 EV (=测最优参数; 完整版扫更多维+难度基调)。
    返回 {sl, ev, fills} 最优。"""
    from app.services.strategy_engine import get_signal
    from app.services.segment_backtest import segment_backtest
    sig = lambda df, p: get_signal(stype, df, p)
    best = {'sl': 0.8, 'ev': -9, 'fills': 0}
    for sl in [0.5, 0.8, 1.2]:
        r = segment_backtest(base_is, aux, strategy_type=stype, signal_fn=sig,
                             base_tf=base_tf, aux_tf='5m', leverage=lev,
                             init_sl_pct=sl, use_position_filter=False)
        ev = r['ev_per_fill_usdt'] if r['fills'] >= 5 else -9
        if ev > best['ev']:
            best = {'sl': sl, 'ev': ev, 'fills': r['fills']}
    return best


def gatekeeper_decide(symbol: str, base_candles: list, aux_candles: list,
                      base_tf: str = '15m', target_pct: float = 5.0,
                      days_remaining: int = 30, lev: float = 10.0) -> dict:
    """守门员一次决策 (offline). 返回 {action: 'enter'|'wait', ...}。

    enter: {action, regime, strategy, params, expected_ev, candidates_n, triggered}
    wait:  {action, regime, reason, candidates}
    """
    # ① 市场感知
    regime = regime_from_candles(base_candles)
    if regime == 'unknown':
        return {'action': 'wait', 'regime': regime, 'reason': '市场 regime 不明'}

    # ② 画像匹配 (按 regime+周期 选适合策略)
    candidates = match_strategies(regime, base_tf)
    if not candidates:
        return {'action': 'wait', 'regime': regime, 'reason': f'无适配 {regime}/{base_tf} 的策略', 'candidates': []}

    # ③ 信号检测: 匹配策略里哪个此刻触发
    from app.services.strategy_engine import get_signal, get_candle_df
    df = get_candle_df([dict(c) for c in base_candles])
    triggered = []
    for s in candidates:
        try:
            sig = get_signal(s, df, {})
            if sig in ('buy', 'sell', 'long', 'short'):
                triggered.append(s)
        except Exception:
            continue
    if not triggered:
        return {'action': 'wait', 'regime': regime, 'reason': '匹配策略均未触发信号',
                'candidates': candidates}

    # ④ 参数优化 + ⑤ 选最优EV (IS段优化, 这里用全段作IS的简化; live时滚动)
    best = None
    for s in triggered:
        opt = _optimize_params(s, base_candles, aux_candles, base_tf, lev)
        if opt['ev'] >= MIN_EV and (best is None or opt['ev'] > best['expected_ev']):
            best = {'strategy': s, 'params': {'init_sl_pct': opt['sl']},
                    'expected_ev': opt['ev'], 'fills': opt['fills']}
    if best:
        return {'action': 'enter', 'regime': regime, 'candidates_n': len(candidates),
                'triggered': triggered, **best}
    return {'action': 'wait', 'regime': regime, 'reason': '触发策略均未达标 EV',
            'triggered': triggered}
