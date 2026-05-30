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

MIN_EV = 0.0   # (旧, 保留兼容) 原始USDT EV 门槛
# 期望R 门槛 (user 2026-05-30 定 EV标准=期望R): 回测pnl已净扣费率, ev_r>0=税后有赚;
# 0.1R = 至少期望赚到风险的 1/10 的安全缓冲 (防回测估计误差贴零). 选策略+live开仓都用这个口径.
MIN_EV_R = 0.1


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


def _optimize_params(stype, base_is, aux, base_tf, lev=10.0, fee_pct=0.035):
    """[机械回退] 对一个策略 IS 段扫 SL 宽度找最优 **期望R**。AI 经理失败时守门员回退用这个。
    返回 {sl, ev, ev_r, fills} 最优 (按 ev_r 选, 与主路径同口径)。"""
    from app.services.strategy_engine import get_signal
    from app.services.segment_backtest import segment_backtest
    sig = lambda df, p: get_signal(stype, df, p)
    best = {'sl': 0.8, 'ev': -9, 'ev_r': -9, 'fills': 0}
    for sl in [0.5, 0.8, 1.2]:
        r = segment_backtest(base_is, aux, strategy_type=stype, signal_fn=sig,
                             base_tf=base_tf, aux_tf='5m', leverage=lev, fee_pct=fee_pct,
                             init_sl_pct=sl, use_position_filter=False,
                             lock_at_tp=True, trail_r=0.5)   # 引擎标准: 锁TP台阶+连续trailing (OOS提EV, user定)
        ev = r['ev_per_fill_usdt'] if r['fills'] >= 5 else -9
        risk = _risk_per_fill(10.0, lev, sl)   # 回退用默认 size 10
        ev_r = round(ev / risk, 4) if (risk > 0 and ev > -9) else -9
        if ev_r > best['ev_r']:
            best = {'sl': sl, 'ev': ev, 'ev_r': ev_r, 'fills': r['fills']}
    return best


def _risk_per_fill(size_usdt, lev, init_sl_pct):
    """一笔的风险金 (USDT) = 名义 × 初始止损% = 打到初始SL会亏多少. 期望R 的分母。"""
    return size_usdt * lev * (init_sl_pct / 100.0)


def _ev_for_params(stype, base_is, aux, base_tf, lev, init_sl, tp1_r, tp2_r, tp3_r, size_usdt=10.0,
                   fee_pct=0.035, tp1_frac=0.5, tp2_frac=0.3, funding_apr=0.0):
    """用 AI 经理给的具体参数回测 EV (守门员把关经理的判断)。返回 {ev(USDT), ev_r(期望R), fills}。
    ev_r = 每笔期望盈亏 ÷ 每笔风险金 → **剥掉仓位/杠杆/SL宽度**, 比的是 edge 纯度 (选策略用这个,
    不是原始USDT否则谁开得大谁赢, user 2026-05-30 定 EV标准=期望R)。
    tp1_frac/tp2_frac: 经理给的分批比例 (Gap A); funding_apr: 年化资金费率, 按持仓时长扣 (Gap B)。"""
    from app.services.strategy_engine import get_signal
    from app.services.segment_backtest import segment_backtest
    sig = lambda df, p: get_signal(stype, df, p)
    r = segment_backtest(base_is, aux, strategy_type=stype, signal_fn=sig,
                         base_tf=base_tf, aux_tf='5m', leverage=lev, position_size_usdt=size_usdt,
                         fee_pct=fee_pct, init_sl_pct=init_sl, tp1_r=tp1_r, tp2_r=tp2_r, tp3_r=tp3_r,
                         tp1_frac=tp1_frac, tp2_frac=tp2_frac, funding_apr=funding_apr,
                         use_position_filter=False, lock_at_tp=True, trail_r=0.5)
    ev = r['ev_per_fill_usdt'] if r['fills'] >= 5 else -9
    risk = _risk_per_fill(size_usdt, lev, init_sl)
    ev_r = round(ev / risk, 4) if (risk > 0 and ev > -9) else -9
    return {'ev': ev, 'ev_r': ev_r, 'fills': r['fills']}


def _manager_params_and_ev(symbol, stype, perception, base_is, aux, base_tf,
                           target_pct, days_remaining, fallback_lev, exchange='hyperliquid',
                           available_usdt=None):
    """钥匙: 守门员问 AI 经理要参数 → 回测EV把关。返回 {skip, params, ev, ev_r, fills, manager}。
    经理失败 → 回退机械 _optimize_params (不阻断守门员)。
    EV 回测用本单路由所的真实费率 (HL 0.035 / OKX 0.05) — 否则 EV 与实盘成本脱节。
    available_usdt: 守门员组合层资金闸算好的可用额度, 传给经理在剩余额度内下注。"""
    from app.models import StrategyProfile
    from app.services.ai_manager import ai_manager_params, exchange_fee_pct
    fee = exchange_fee_pct(exchange)
    prof_row = StrategyProfile.query.filter_by(strategy_type=stype).first()
    prof = prof_row.profile if prof_row else {}
    mp = ai_manager_params(symbol, stype, perception, prof, target_pct, days_remaining,
                           exchange=exchange, base_tf=base_tf, available_usdt=available_usdt)
    if mp.get('ok') and mp.get('skip'):
        return {'skip': True, 'manager': {'used': True, 'reason': mp.get('reason_zh')}}
    if mp.get('ok'):
        # 资金费年化 (Gap B): perception 的 rate 是每结算周期(8h)→ ×3×365 年化, 用当前费率当前向估计
        _fr = (perception.get('funding') or {}).get('rate')
        funding_apr = (float(_fr) * 3 * 365) if _fr else 0.0
        r = _ev_for_params(stype, base_is, aux, base_tf, mp['leverage'], mp['init_sl_pct'],
                           mp['tp1_r'], mp['tp2_r'], mp['tp3_r'], mp['position_size_usdt'], fee_pct=fee,
                           tp1_frac=mp.get('tp1_frac', 0.5), tp2_frac=mp.get('tp2_frac', 0.3),
                           funding_apr=funding_apr)
        return {'skip': False, 'ev': r['ev'], 'ev_r': r['ev_r'], 'fills': r['fills'],
                'params': {'init_sl_pct': mp['init_sl_pct'], 'leverage': mp['leverage'],
                           'tp1_r': mp['tp1_r'], 'tp2_r': mp['tp2_r'], 'tp3_r': mp['tp3_r'],
                           'tp1_frac': mp.get('tp1_frac', 0.5), 'tp2_frac': mp.get('tp2_frac', 0.3),
                           'position_size_usdt': mp['position_size_usdt']},
                'manager': {'used': True, 'reason': mp.get('reason_zh'), 'leverage': mp['leverage']}}
    # 经理失败 → 机械回退
    opt = _optimize_params(stype, base_is, aux, base_tf, fallback_lev, fee_pct=fee)
    return {'skip': False, 'ev': opt['ev'], 'ev_r': opt['ev_r'], 'fills': opt['fills'],
            'params': {'init_sl_pct': opt['sl']},
            'manager': {'used': False, 'reason': '经理失败,机械回退: ' + str(mp.get('error'))[:60]}}


def gatekeeper_decide(symbol: str, base_candles: list, aux_candles: list,
                      base_tf: str = '15m', target_pct: float = 5.0,
                      days_remaining: int = 30, lev: float = 10.0,
                      record: bool = False, record_source: str = 'offline',
                      exchange: str = 'hyperliquid', available_usdt=None) -> dict:
    """守门员一次决策 (offline). 返回 {action: 'enter'|'wait', ...}。

    enter: {action, regime, strategy, params, expected_ev, candidates_n, triggered}
    wait:  {action, regime, reason, candidates}

    record=True 时把这次决策留痕进 gatekeeper_decisions (学习飞轮), decision 里带回
    decision_id; 实测/实盘结果后续用 gatekeeper_learning.record_outcome(id, pnl) 回填。
    available_usdt: 守门员组合层资金闸算好的可用额度 (live 传; offline=None→经理拉总权益)。
    """
    decision = _gatekeeper_decide_inner(symbol, base_candles, aux_candles,
                                        base_tf, target_pct, days_remaining, lev, exchange, available_usdt)
    if record:
        try:
            from app.services.gatekeeper_learning import record_decision
            did = record_decision(decision, symbol, base_tf,
                                  perception=decision.get('perception'),
                                  source=record_source)
            if did:
                decision['decision_id'] = did
        except Exception:
            pass
    return decision


def _gatekeeper_decide_inner(symbol, base_candles, aux_candles, base_tf,
                             target_pct, days_remaining, lev, exchange='hyperliquid', available_usdt=None):
    # ① 富市场感知 (regime+方向+波动+量+MTF+形态动能+funding+指标状态)
    from app.services.market_perception import perceive_market
    perc = perceive_market(symbol, base_candles, aux_candles, base_tf)
    if not perc.get('ok') or perc.get('regime') == 'unknown':
        return {'action': 'wait', 'reason': '市场 regime 不明', 'perception': perc}

    # ② 富感知精准配对 (富市场画像 × 策略画像 → 匹配度评分排序)
    scored = match_with_perception(perc, base_tf)
    if not scored:
        return {'action': 'wait', 'regime': perc['regime'], 'direction': perc['direction'],
                'reason': f"无适配 {perc['regime']}/{perc['direction']}/{base_tf} 的策略",
                'perception': perc}

    # ③ 信号检测: 高分候选里哪个此刻触发
    from app.services.strategy_engine import get_signal, get_candle_df
    df = get_candle_df([dict(c) for c in base_candles])
    triggered = []
    for s in scored:
        try:
            sig = get_signal(s['strategy'], df, {})
            if sig in ('buy', 'sell', 'long', 'short'):
                s['side'] = 'long' if sig in ('buy', 'long') else 'short'   # 供 live 下单定方向
                triggered.append(s)
        except Exception:
            continue
    if not triggered:
        return {'action': 'wait', 'regime': perc['regime'], 'direction': perc['direction'],
                'reason': '匹配策略均未触发信号', 'top_match': scored[:3], 'perception': perc}

    # ④ 钥匙: 守门员问 AI 经理要参数 (带难度+富感知+策略画像) → ⑤ 回测EV把关选最优
    best = None; skipped = []
    for s in triggered:
        m = _manager_params_and_ev(symbol, s['strategy'], perc, base_candles, aux_candles,
                                   base_tf, target_pct, days_remaining, lev, exchange, available_usdt)
        if m.get('skip'):
            skipped.append({'strategy': s['strategy'], 'reason': (m.get('manager') or {}).get('reason')})
            continue   # AI 经理判断这单不该开 (行情踩中策略弱点)
        # 选 edge 最强 = 期望R 最高 (剥掉仓位/杠杆影响, 不再"谁开得大谁赢"); 门槛=税后期望R缓冲.
        # expected_ev 仍存原始USDT (学习飞轮 ev_bias 要跟 realized_pnl 同口径对比).
        if m.get('ev_r', -9) >= MIN_EV_R and (best is None or m['ev_r'] > best['expected_ev_r']):
            best = {'strategy': s['strategy'], 'side': s.get('side'),
                    'match_score': s['score'], 'match_reasons': s['reasons'],
                    'params': m['params'], 'expected_ev': m['ev'], 'expected_ev_r': m['ev_r'],
                    'fills': m['fills'], 'manager': m['manager']}
    if best:
        return {'action': 'enter', 'regime': perc['regime'], 'direction': perc['direction'],
                'triggered': [t['strategy'] for t in triggered], 'perception': perc, **best}
    return {'action': 'wait', 'regime': perc['regime'], 'direction': perc['direction'],
            'reason': 'AI经理skip或回测均未达标期望R',
            'triggered': [t['strategy'] for t in triggered], 'manager_skipped': skipped, 'perception': perc}


def match_with_perception(perception: dict, timeframe: str) -> list:
    """富感知精准配对: 当前市场富画像 × 策略画像 → 匹配度评分排序。
    返回 [{strategy, score, reasons}] 按 score 降序。硬过滤(regime/周期/方向冲突)淘汰, 软加分(指标对齐/MTF/猎杀)。"""
    from app.models import StrategyProfile
    regime = perception.get('regime'); direction = perception.get('direction', 'flat')
    want = 'trend' if regime == 'trend' else 'range'
    ind = perception.get('indicators') or {}
    pa = perception.get('price_action') or {}
    out = []
    for p in StrategyProfile.query.all():
        prof = p.profile or {}
        rf = prof.get('regime_fit', {})
        tff = ' '.join(str(x) for x in (prof.get('timeframe_fit') or []))
        # 硬过滤: regime + 周期
        if rf.get(want) != 'good' or timeframe not in tff:
            continue
        sdir = prof.get('direction', 'both')
        # 硬过滤: 趋势市方向冲突 (上涨不用纯空策略, 反之)
        if regime == 'trend' and direction != 'flat':
            if (direction == 'up' and sdir == 'short') or (direction == 'down' and sdir == 'long'):
                continue
        score = 2.0; reasons = [f'{want}+周期匹配']
        if regime == 'trend' and direction != 'flat':
            score += 1; reasons.append(f'方向{direction}对齐')
        # 软加分: 指标状态对齐 (该策略类型关心的指标当前是否利于进场)
        if want == 'range':
            if (ind.get('stochastic', {}).get('state') in ('oversold', 'overbought')
                    or ind.get('cci', {}).get('state') in ('oversold', 'overbought')
                    or ind.get('bollinger', {}).get('state') in ('upper', 'lower')):
                score += 2; reasons.append('震荡指标在极端位(均值回归机会)')
        else:
            up_align = ind.get('ichimoku', {}).get('state') == 'above_cloud' or ind.get('psar', {}).get('state') == 'bullish' or ind.get('donchian', {}).get('state') == 'upper_break'
            dn_align = ind.get('ichimoku', {}).get('state') == 'below_cloud' or ind.get('psar', {}).get('state') == 'bearish' or ind.get('donchian', {}).get('state') == 'lower_break'
            if (direction == 'up' and up_align) or (direction == 'down' and dn_align):
                score += 2; reasons.append('趋势指标方向对齐')
        if perception.get('mtf_aligned'):
            score += 1; reasons.append('MTF多周期对齐')
        if pa.get('hunt'):
            score -= 1.5; reasons.append('⚠有猎杀针(慎)')
        out.append({'strategy': p.strategy_type, 'score': round(score, 1), 'reasons': reasons})
    return sorted(out, key=lambda x: -x['score'])
