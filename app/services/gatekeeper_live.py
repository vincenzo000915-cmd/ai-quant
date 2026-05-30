"""Phase 15 学习飞轮②: 守门员 live 扫描 — 接 live 入场路径 (灰度: off | shadow | live)

蓝图 project-phase15-blueprint 九.6 (user 2026-05-30 授权当学费). 守门员实时扫描市场 →
决策 → (shadow: 记录+通知不下单 / live: 真下单) → 平仓回填真盈亏 → P&L 校准飞轮.

灰度四档 (config gatekeeper_live_mode):
  off    — 不动 (默认)
  shadow — 每15分扫, 记录实时 live 决策 (source='live'), enter 时 TG 通知"现在会开X", **不下单**.
  paper  — 全套机器跑通: 真开仓→引擎分批出场(segment_exit.exit_step)→平仓回填, 但**模拟成交**
           (真实价格, 零真钱). 验证执行保真 + 攒真价格 P&L, 安全. 翻 live 前的坐实档.
  live   — paper 同套机器, 但 _place_order 走真实交易所 **真下单真钱**.

执行保真 (核心): 守门员算 EV 用引擎 segment_backtest(分批TP1/2/3+两段移动止损); live/paper 平仓
跑**同一套** segment_exit.exit_step → 持仓由 gatekeeper_exit_manage 逐 5m bar 推进, check_stop_loss
对守门员仓让路. 否则执行≠算EV的引擎 = 学到假经验.

安全闸 (全守):
  - halted (kill switch 首页按钮 / DD halt) → 直接 skip, 不开仓.
  - 守门员独占: live 开启时现有策略由 _run_signals 让路 (见 strategy_tasks 改动).
  - 仓位/杠杆 = AI 难度基调按 target 自配 (profit_difficulty.leverage_cap), 非手动写死 (user 定).
  - L1 杠杆感知止损下限 + 预算闸 在真下单段复用现有 _place_order 路径.

user 定 (2026-05-30): 先只 ETH+AVAX (已 offline 验证), 15m base + 5m aux (核心小波段维度,
5m 看微观/猎杀/动能/MTF), 每 15 分轮询.
"""
from __future__ import annotations

# user 2026-05-30: 先只 ETH+AVAX (offline 滚动验证过), 坐实后扩
WATCHED_SYMBOLS = ['ETH/USDT', 'AVAX/USDT']
BASE_TF = '15m'   # 策略决策维度 (画像配 15m)
AUX_TF = '5m'     # 更细市场维度 (富感知读 5m 算微观/猎杀/动能/MTF)


def _to_candles(rows) -> list:
    if not rows:
        return []
    return [{'open': x['open'], 'high': x['high'], 'low': x['low'],
             'close': x['close'], 'volume': x['volume'], 'timestamp': x['timestamp']}
            for x in rows]


def _target_and_days() -> tuple[float, int]:
    """从 active ProfitTarget 取 目标% + 剩余天 (AI 难度基调的输入)。无则给保守默认。"""
    try:
        from app.models import ProfitTarget
        import datetime as _dt
        pt = ProfitTarget.query.filter_by(status='active').order_by(ProfitTarget.id.desc()).first()
        if pt:
            days = 30
            if pt.deadline:
                days = max(1, (pt.deadline - _dt.datetime.utcnow()).days)
            return float(pt.target_pct or 5.0), days
    except Exception:
        pass
    return 5.0, 30


def gatekeeper_live_cycle() -> dict:
    """守门员一轮 live 扫描 (beat */15 调). 返回 {mode, scanned, decisions:[...]}。"""
    from app.services.config_service import get_config
    cfg = get_config()
    mode = cfg.get('gatekeeper_live_mode', 'off')
    if mode == 'off':
        return {'mode': 'off', 'scanned': 0, 'decisions': []}
    # 安全闸: kill switch / DD halt 时直接 skip (守门员真下单路径受 halted 管)
    if cfg.get('halted'):
        return {'mode': mode, 'halted': True, 'scanned': 0, 'decisions': [],
                'note': f"halted({cfg.get('halt_reason')}) → 守门员不开仓"}

    from app.services.exchange_service import fetch_ohlcv
    from app.services.gatekeeper import gatekeeper_decide
    from app.services.profit_difficulty import profit_difficulty, monthly_equiv

    target_pct, days_remaining = _target_and_days()
    lev_cap = profit_difficulty(monthly_equiv(target_pct, days_remaining)).get('leverage_cap') or 5
    decisions = []
    for sym in WATCHED_SYMBOLS:
        try:
            base = _to_candles(fetch_ohlcv(sym, BASE_TF, limit=400))
            aux = _to_candles(fetch_ohlcv(sym, AUX_TF, limit=1200))
            if len(base) < 60 or len(aux) < 60:
                decisions.append({'symbol': sym, 'action': 'skip', 'reason': '数据不足'})
                continue
            # base 对齐 aux 起点 (保证两 feed 同窗口, 防 MTF 错位)
            base = [c for c in base if c['timestamp'] >= aux[0]['timestamp']]
            d = gatekeeper_decide(sym, base, aux, BASE_TF,
                                  target_pct=target_pct, days_remaining=days_remaining,
                                  lev=float(lev_cap), record=True, record_source='live')
            d['symbol'] = sym
            decisions.append({k: d.get(k) for k in
                              ('symbol', 'action', 'regime', 'direction', 'strategy',
                               'expected_ev', 'match_score', 'reason', 'decision_id')})
            if d.get('action') == 'enter':
                if mode == 'shadow':
                    _notify_shadow_enter(sym, d, target_pct)
                elif mode in ('paper', 'live'):
                    order_mode = 'paper' if mode == 'paper' else cfg.get('trading_mode', 'paper')
                    _execute_live_enter(sym, d, lev_cap, cfg, order_mode)
        except Exception as e:
            decisions.append({'symbol': sym, 'action': 'error',
                              'reason': f'{type(e).__name__}: {e}'})
    return {'mode': mode, 'scanned': len(WATCHED_SYMBOLS), 'decisions': decisions}


def _notify_shadow_enter(symbol: str, d: dict, target_pct: float):
    """影子档: enter 决策 TG 通知 user "守门员现在会开 X" (不下单, 给 user 看实时决策质量)。"""
    try:
        from app.services import telegram_service
        sym_zh = symbol.split('/')[0]
        txt = (f"👁️ <b>守门员影子决策</b> (未下单)\n"
               f"现在会开: <b>{sym_zh}</b> {d.get('regime')}/{d.get('direction')}\n"
               f"策略: {d.get('strategy')} · 预期EV {d.get('expected_ev'):.3f} · 配对分 {d.get('match_score')}\n"
               f"参数: SL {(d.get('params') or {}).get('init_sl_pct')}%\n"
               f"<i>影子档=只记录看决策对不对, 翻 live 才真下单</i>")
        telegram_service.send(txt, force=True)
    except Exception as e:
        print(f'[gatekeeper_live] notify error: {type(e).__name__}: {e}')


HOST_CATEGORY = 'gatekeeper'
# 引擎出场参数 (= 守门员算 EV 的 segment_backtest 默认, 单一真相源)
ENGINE_EXIT_PARAMS = {
    'use_breakeven': True, 'be_activate_r': 0.3, 'be_lock_pct': 0.0,
    'use_partial_tp': True, 'tp1_r': 0.5, 'tp1_frac': 0.5, 'tp2_r': 1.2, 'tp2_frac': 0.3,
    'tp3_r': 2.0, 'tp1_lock_r': 0.3, 'use_tail_exit': False, 'fee_pct': 0.035,
    # 引擎标准 (user 2026-05-30, OOS验证提EV): 吃到TPn→止损锁到TPn价位 + 连续trailing 0.5R
    'lock_at_tp': True, 'trail_r': 0.5,
}


def _host_strategy(symbol: str, strategy_type: str, params: dict, user_id: int, exchange: str):
    """找/建守门员宿主策略 (满足 Position.strategy_id FK + dashboard 显示;
    status='gatekeeper' 故 _run_signals(status='running') 不扫它, 出场由 gatekeeper_exit_manage 管)。"""
    from app.models import Strategy, db
    s = Strategy.query.filter_by(category=HOST_CATEGORY, symbol=symbol).first()
    if s is None:
        s = Strategy(name=f'守门员 · {symbol.split("/")[0]}', type=strategy_type, symbol=symbol,
                     timeframe=BASE_TF, category=HOST_CATEGORY, status='gatekeeper',
                     user_id=user_id, exchange=exchange, params=params or {})
        db.session.add(s)
    else:
        s.type = strategy_type; s.params = params or {}; s.exchange = exchange
    db.session.commit()
    return s


def _primary_exchange(user_id: int, fallback: str = 'hyperliquid') -> str:
    try:
        from app.services.exchange_binding import routable_exchanges
        vs = [e.lower() for e in (routable_exchanges(user_id) or [])]
        return vs[0] if vs else fallback
    except Exception:
        return fallback


def _resolve_gk_params(user_id: int, ai_lev: float, cfg: dict) -> dict:
    """守门员参数分层解析 (user 2026-05-30 定):
      Team tier — AI 全自动匹配参数, **AI 参数最优先基准** (难度基调 leverage_cap + 系统 sizing).
      Pro  tier — 用户自己在设定里配参数, 守门员按**用户参数**下单 (走 user-scoped config).
    返回 {leverage, size_usdt, source}。"""
    from app.services.config_service import get_config
    try:
        from app.services.exchange_binding import is_team_tier
        team = is_team_tier(user_id)
    except Exception:
        team = False
    if team:
        return {'leverage': float(ai_lev),
                'size_usdt': float(cfg.get('trade_size_usdt') or 10.0), 'source': 'ai(team)'}
    ucfg = get_config(user_id=user_id)
    return {'leverage': float(ucfg.get('leverage') or ai_lev),
            'size_usdt': float(ucfg.get('trade_size_usdt') or 10.0), 'source': 'user(pro)'}


def _execute_live_enter(symbol: str, d: dict, lev: float, cfg: dict, order_mode: str):
    """守门员开仓 (paper=模拟成交真价格 / live=真下单). 仓位杠杆=AI难度基调(lev传入),
    size=cfg trade_size; 建仓后由 gatekeeper_exit_manage 跑引擎分批出场。"""
    from app.models import Position, db
    from app.services.exchange_service import get_ticker
    from app.services.segment_exit import new_exit_state
    from app.tasks.strategy_tasks import _place_order

    side = d.get('side')
    if side not in ('long', 'short'):
        return
    user_id = 1
    # 独占 first-mover: 该 symbol 有任何 open 持仓(守门员或现有策略)→ 跳过, 等平了再开.
    # 防 HL cross-margin 同币 netting 把仓合并 → PnL 归属混乱 (12.35.1 first-mover 同理).
    exists = Position.query.filter_by(symbol=symbol, status='open').first()
    if exists:
        return
    stype = d['strategy']
    mparams = d.get('params') or {}
    init_sl = float(mparams['init_sl_pct'])
    # AI 经理给的参数优先 (钥匙: 经理带难度+感知+画像临场判断的 lev/仓位/TP); 经理没给则 tier 回退
    gp = _resolve_gk_params(user_id, lev, cfg)
    lev = float(mparams.get('leverage') or gp['leverage'])
    size_usdt = float(mparams.get('position_size_usdt') or gp['size_usdt'])
    exchange = _primary_exchange(user_id)
    # HL 最小 $10 notional 闸
    if exchange == 'hyperliquid' and size_usdt * lev < 10:
        print(f'[gatekeeper_live] {symbol} 跳过: notional ${size_usdt*lev:.1f} < HL最小$10')
        return
    price = get_ticker(symbol)['price']
    okx_side = 'buy' if side == 'long' else 'sell'
    host = _host_strategy(symbol, stype, {'risk_params': {'leverage': lev}}, user_id, exchange)
    order = _place_order(symbol, okx_side, size_usdt, price, order_mode, leverage=lev,
                         pos_side=side, user_id=user_id, exchange=exchange)
    if order is None:
        print(f'[gatekeeper_live] {symbol} 下单失败 (mode={order_mode})')
        return
    fill = float(order.get('price') or price)
    base_size = size_usdt * lev / fill
    exit_params = dict(ENGINE_EXIT_PARAMS); exit_params['init_sl_pct'] = init_sl
    for _k in ('tp1_r', 'tp2_r', 'tp3_r'):   # AI 经理给的盈亏比 R 也用上 (出场台阶随经理判断)
        if mparams.get(_k):
            exit_params[_k] = float(mparams[_k])
    state = new_exit_state(side, fill, init_sl)
    import time as _t
    _entry_ts = int(_t.time())   # 出场管理器只处理入场后新 5m bar (防回放入场前K线)
    pos = Position(
        strategy_id=host.id, user_id=user_id, exchange=exchange, symbol=symbol,
        side=side, size=base_size, entry_price=fill, current_price=fill, status='open',
        gatekeeper_decision_id=d.get('decision_id'),
        gk_exit={'state': state, 'params': exit_params, 'last_ts': _entry_ts,
                 'orig_size': base_size, 'margin': size_usdt, 'order_mode': order_mode,
                 'pnl': 0.0, 'strategy': stype, 'lev': lev, 'slippage_pct': 0.03,
                 'native': order_mode == 'live' and (exchange or '').lower() in ('hyperliquid', 'okx'),
                 'oids': {}},
    )
    db.session.add(pos); db.session.commit()
    # live 真钱: 挂原生 SL + TP1/2/3 trigger 单 (服务端执行); paper 走轮询出场管理器(模拟)
    if pos.gk_exit.get('native'):
        _place_native_brackets(pos, side, fill, base_size, exit_params)
    _notify_live_enter(symbol, d, fill, lev, order_mode, pos.id)


def _native_tp_price(side, entry, r, R):
    d = r * R / 100.0
    return entry * (1 + d) if side == 'long' else entry * (1 - d)


HL_MIN_NOTIONAL = 10.5   # HL 单笔最低 $10 (留 0.5 buffer 防触发时价格波动跌破)


def _feasible_tp_plan(base_size, entry, side, exit_params):
    """按 HL $10 最低单笔自适应分批, **防老鼠仓** (user 2026-05-30):
      - 中间档(TP1/TP2): 只在 '本档≥$10 且 平完后剩余仍≥$10'(剩余能被后续TP/SL平) 才单独挂;
        否则 frac 累加进下一档 (合并).
      - 最后一档: **永远平掉全部剩余 frac** → 任何时候不留 <$10 的零头(老鼠仓平不掉).
    大仓位($60)→真50/30/20; 中($30)→TP1+末档全平; 小($20)→单档TP3全平(实际靠棍轮SL在TP台阶出).
    返回 [(level_r, frac, key)]."""
    R = exit_params['init_sl_pct']
    tps = [(exit_params['tp1_r'], exit_params['tp1_frac']),
           (exit_params['tp2_r'], exit_params['tp2_frac']),
           (exit_params['tp3_r'], round(1 - exit_params['tp1_frac'] - exit_params['tp2_frac'], 4))]
    plan = []; placed = 0.0; acc = 0.0; n = len(tps)
    for i, (r, frac) in enumerate(tps):
        acc += frac
        px = _native_tp_price(side, entry, r, R)
        if i == n - 1:
            close_frac = round(1.0 - placed, 4)   # 末档: 平掉全部剩余, 无零头
            if close_frac > 1e-9:
                plan.append((r, close_frac, f'tp{len(plan)+1}'))
            break
        chunk = base_size * acc * px
        remaining = base_size * (1.0 - placed - acc) * px   # 平这档后剩余
        if chunk >= HL_MIN_NOTIONAL and remaining >= HL_MIN_NOTIONAL:
            plan.append((r, round(acc, 4), f'tp{len(plan)+1}'))
            placed += acc; acc = 0.0
    return plan


# ── venue-无关分派 (HL / OKX 同接口) — user 2026-05-30: 多租户, OKX用户也走原生trigger ──
def _native_creds(exchange, user_id):
    if (exchange or '').lower() == 'okx':
        from app.services.exchange_service import _resolve_creds
        return _resolve_creds(user_id)
    from app.services.hyperliquid_creds import get_decrypted_for_user
    return get_decrypted_for_user(user_id)


def _native_place_trigger(exchange, symbol, side, trigger_px, base_size, tpsl, creds):
    if (exchange or '').lower() == 'okx':
        from app.services.exchange_service import place_okx_trigger
        return place_okx_trigger(symbol, side, trigger_px, base_size, tpsl, creds)
    from app.services.hyperliquid_service import place_hl_trigger
    return place_hl_trigger(symbol, side, trigger_px, base_size, tpsl, creds)


def _native_cancel(exchange, symbol, oid, creds):
    if (exchange or '').lower() == 'okx':
        from app.services.exchange_service import cancel_okx_algo
        return cancel_okx_algo(symbol, oid, creds)
    from app.services.hyperliquid_service import cancel_hl_order
    return cancel_hl_order(symbol, oid, creds)


def _native_position_size(exchange, symbol, creds):
    """带符号持仓 base size; API出错返 None (查不到≠没了, 真钱铁律, HL/OKX 同)。"""
    if (exchange or '').lower() == 'okx':
        from app.services.exchange_service import get_okx_position_base
        return get_okx_position_base(symbol, creds)
    from app.services.hyperliquid_service import get_hl_position_size
    return get_hl_position_size(symbol, creds)


def _place_native_brackets(pos, side, entry, base_size, exit_params):
    """开仓后挂原生 reduce-only 止损/分批止盈 trigger 单 (HL/OKX 服务端执行, 按 pos.exchange 分派)。
    SL 全仓 @ init_sl; TP 按 _feasible_tp_plan 自适应. oid 存 gk_exit['oids']。"""
    from app.models import db
    from sqlalchemy.orm.attributes import flag_modified
    ex = pos.exchange
    creds = _native_creds(ex, pos.user_id)
    if not creds:
        print(f'[gatekeeper_live] {pos.symbol} 无 {ex} creds, 不挂原生trigger'); return
    R = exit_params['init_sl_pct']
    oids = {}
    # SL (全仓)
    sl_px = entry * (1 - R / 100) if side == 'long' else entry * (1 + R / 100)
    r_sl = _native_place_trigger(ex, pos.symbol, side, sl_px, base_size, 'sl', creds)
    oids['sl'] = r_sl.get('oid'); oids['sl_px'] = r_sl.get('trigger_px')
    if not r_sl.get('ok'):
        print(f"[gatekeeper_live] {pos.symbol} SL trigger 失败: {r_sl.get('reject_reason')}")
    # 分批 TP — 自适应 $10 最低 (小仓位自动合并, 不再被拒)
    plan = _feasible_tp_plan(base_size, entry, side, exit_params)
    oids['tp_plan'] = []   # [(level_r, frac, oid)] 实际挂上的
    for r_mult, frac, key in plan:
        tp_px = _native_tp_price(side, entry, r_mult, R)
        rr = _native_place_trigger(ex, pos.symbol, side, tp_px, base_size * frac, 'tp', creds)
        oids[key] = rr.get('oid')
        oids['tp_plan'].append({'r': r_mult, 'frac': frac, 'oid': rr.get('oid'), 'notional': round(base_size*frac*tp_px,2)})
        if not rr.get('ok'):
            print(f"[gatekeeper_live] {pos.symbol} {key}(${round(base_size*frac*tp_px,1)}) trigger 失败: {rr.get('reject_reason')}")
    if not plan:
        print(f"[gatekeeper_live] {pos.symbol} 仓位太小凑不出$10分批, 纯靠 SL+trailing 出场")
    pos.gk_exit['oids'] = oids
    flag_modified(pos, 'gk_exit'); db.session.commit()


def _notify_live_enter(symbol, d, fill, lev, order_mode, pos_id):
    try:
        from app.services import telegram_service
        tag = '（纸面演练）' if order_mode == 'paper' else ''
        s = symbol.split('/')[0]
        dir_zh = '做空 🔻' if d.get('side') == 'short' else '做多 🔺'
        sl_pct = (d.get('params') or {}).get('init_sl_pct')
        sl_px = fill * (1 + sl_pct / 100) if d.get('side') == 'short' else fill * (1 - sl_pct / 100)
        regime_zh = {'trend': '趋势', 'range': '震荡'}.get(d.get('regime'), d.get('regime') or '')
        dir_read = {'up': '偏多', 'down': '偏空', 'flat': '横盘'}.get(d.get('direction'), '')
        reasons = '、'.join((d.get('match_reasons') or [])[:2]) if d.get('match_reasons') else ''
        from app.services.llm_prompts.strategy_profile import strategy_display_name
        telegram_service.send(
            f"🎯 <b>守门员开仓</b>{tag}\n"
            f"<b>{s} · {dir_zh}</b>\n"
            f"选用策略：<b>{strategy_display_name(d.get('strategy'))}</b>"
            + (f"（配对分 {d.get('match_score')}）" if d.get('match_score') else "") + "\n"
            f"市场判读：{regime_zh}{('/' + dir_read) if dir_read else ''}"
            + (f" · {reasons}" if reasons else "") + "\n"
            f"入场 <b>{round(fill, 4)}</b> · 杠杆 {lev:.0f} 倍 · 止损 {round(sl_px, 4)}（{sl_pct}%）\n"
            f"打法：锁 TP 台阶、吃头中段不贪尾", force=True)
    except Exception as e:
        print(f'[gatekeeper_live] notify enter error: {type(e).__name__}: {e}')


# ============================================================
# 引擎分批出场管理器 — 逐 5m bar 跑 segment_exit.exit_step (与算EV的引擎同一套)
# beat */5 调; check_stop_loss 对守门员仓让路 → 这里独家管它们的分批TP+两段移动止损。
# ============================================================

def _favorable(side, price, entry):
    return (price - entry) if side == 'long' else (entry - price)


def _tranche_pnl(side, entry, fill_level, frac, margin, lev, slip, fee_pct):
    """一笔分批平仓的 pnl (与 segment_backtest.close_part 同公式, paper 用; live 用真 balChg)。"""
    fill = fill_level * (1 - slip) if side == 'long' else fill_level * (1 + slip)
    move = _favorable(side, fill, entry) / entry
    notional = margin * frac
    return move * notional * lev - notional * (fee_pct / 100.0) * 2, fill


def gatekeeper_exit_manage() -> dict:
    """守门员持仓出场: 逐新 5m bar 推进引擎状态机, 分批/全平。返回 {managed, closed}。"""
    from app.models import Position, Trade, db
    from app.services.exchange_service import fetch_ohlcv, get_ticker
    from app.services.segment_exit import exit_step
    from app.services.gatekeeper_learning import record_outcome
    from sqlalchemy.orm.attributes import flag_modified
    import datetime as _dt

    positions = (Position.query.filter_by(status='open')
                 .filter(Position.gatekeeper_decision_id.isnot(None)).all())
    managed = 0; closed = 0
    for pos in positions:
        gk = pos.gk_exit or {}
        state = gk.get('state'); params = gk.get('params')
        if not state or not params:
            continue
        side = state['side']; entry = state['entry']
        margin = gk.get('margin', 10.0); lev = gk.get('lev', 5.0)
        slip = gk.get('slippage_pct', 0.03) / 100.0; fee_pct = params.get('fee_pct', 0.035)
        order_mode = gk.get('order_mode', 'paper')
        # live 原生 trigger 仓 → fill驱动棍轮 (服务端执行); paper → 轮询模拟 (下面)
        if gk.get('native'):
            try:
                res = _manage_native_position(pos, gk)
                managed += res.get('managed', 0); closed += res.get('closed', 0)
            except Exception as e:
                print(f'[gatekeeper_live] native manage {pos.symbol} error: {type(e).__name__}: {e}')
            continue
        last_ts = gk.get('last_ts', 0)
        try:
            rows = fetch_ohlcv(pos.symbol, AUX_TF, limit=200) or []
        except Exception:
            continue
        new_bars = [r for r in rows if r['timestamp'] > last_ts]
        if not new_bars:
            continue
        managed += 1
        fully = False
        for bar in new_bars:
            r = exit_step(state, bar, params)
            for c in r['closes']:
                pnl, fill = _tranche_pnl(side, entry, c['price'], c['frac'], margin, lev, slip, fee_pct)
                _place_gk_close(pos, c['frac'], fill, order_mode, lev)   # 真平/模拟
                tr = Trade(position_id=pos.id, strategy_id=pos.strategy_id, user_id=pos.user_id,
                           symbol=pos.symbol, side=side, entry_price=entry, exit_price=round(fill, 6),
                           quantity=gk.get('orig_size', pos.size) * c['frac'], pnl=round(pnl, 4),
                           pnl_percent=round(_favorable(side, fill, entry) / entry * 100 * lev, 3),
                           entry_time=pos.opened_at, exit_time=_dt.datetime.utcnow(),
                           reason=('gkpaper_' if order_mode == 'paper' else 'gk_') + c['reason'])
                db.session.add(tr)
                gk['pnl'] = round(gk.get('pnl', 0.0) + pnl, 4)
                pos.size = max(0.0, gk.get('orig_size', pos.size) * state['rem'])
            gk['last_ts'] = bar['timestamp']
            if r['fully_closed']:
                fully = True
                break
        gk['state'] = state
        pos.gk_exit = gk; flag_modified(pos, 'gk_exit')
        if fully:
            pos.status = 'closed'; pos.closed_at = _dt.datetime.utcnow()
            pos.realized_pnl = gk['pnl']
            if pos.gatekeeper_decision_id:
                record_outcome(pos.gatekeeper_decision_id, gk['pnl'])   # 回填真盈亏校准飞轮
            closed += 1
            _notify_gk_close(pos, gk)
        db.session.commit()
    return {'managed': managed, 'closed': closed}


def _place_gk_close(pos, frac, fill, order_mode, lev):
    """守门员分批平仓下单 (reduce_only). paper=模拟; live=真平。"""
    from app.tasks.strategy_tasks import _place_order
    close_side = 'buy' if pos.side == 'short' else 'sell'
    try:
        _place_order(pos.symbol, close_side, frac * (pos.gk_exit or {}).get('orig_size', pos.size) * fill,
                     fill, order_mode, leverage=lev, pos_side=pos.side,
                     user_id=pos.user_id, exchange=pos.exchange, reduce_only=True)
    except Exception as e:
        print(f'[gatekeeper_live] close order error {pos.symbol}: {type(e).__name__}: {e}')


_MILESTONE_ZH = {1: 'TP1', 2: 'TP2', 3: 'TP3'}


def _sl_milestone(side, entry, p, sl_px) -> int:
    """SL 当前锁在第几个 TP 台阶 (0=保本/初始以下, 1=TP1, 2=TP2, 3=TP3)。"""
    R = p['init_sl_pct']
    locked_R = ((sl_px - entry) if side == 'long' else (entry - sl_px)) / entry * 100
    m = 0
    for i, r in enumerate((p.get('tp1_r', 0.5), p.get('tp2_r', 1.2), p.get('tp3_r', 2.0)), 1):
        if locked_R >= r * R - 1e-9:
            m = i
    return m


def _notify_sl_lock(pos, milestone, sl_px, p):
    """止损上移到 TP 台阶 → 通知锁利 (诚实: 是止损锁利, 不是分批成交)。"""
    try:
        from app.services import telegram_service
        s = pos.symbol.split('/')[0]
        r_locked = {1: p.get('tp1_r', 0.5), 2: p.get('tp2_r', 1.2), 3: p.get('tp3_r', 2.0)}.get(milestone)
        telegram_service.send(
            f"🔒 <b>{s} · 止损上移锁利</b>\n"
            f"价格到 {_MILESTONE_ZH.get(milestone)}，移动止损上移到 <b>{round(sl_px, 4)}</b>\n"
            f"现在至少锁定 +{r_locked}R（全吃 {_MILESTONE_ZH.get(milestone)} 保底）", force=True)
    except Exception:
        pass


def _exit_summary(pos, gk):
    """平仓出场归因: 在哪个台阶出 + R 倍数。返回 (label, r_mult)。"""
    p = gk.get('params') or {}
    entry = (gk.get('state') or {}).get('entry') or pos.entry_price
    R = p.get('init_sl_pct') or 1.0
    pnl = gk.get('pnl', 0.0)
    m = gk.get('locked_milestone', 0)
    # 用锁到的台阶判断出场类型
    if m >= 1:
        label = f"全吃 {_MILESTONE_ZH.get(m)} 锁利出"
    elif pnl >= 0:
        label = "保本/小幅获利出"
    else:
        label = "初始止损出"
    # 估 R 倍数 (pnl / 单R风险金额)
    risk_usdt = gk.get('margin', 10) * gk.get('lev', 1) * (R / 100)
    r_mult = (pnl / risk_usdt) if risk_usdt else 0
    return label, r_mult


def _notify_gk_close(pos, gk):
    try:
        from app.services import telegram_service
        tag = '（纸面演练）' if gk.get('order_mode') == 'paper' else ''
        s = pos.symbol.split('/')[0]
        dir_zh = '做空' if pos.side == 'short' else '做多'
        pnl = gk.get('pnl', 0.0)
        emo = '🟢' if pnl >= 0 else '🔴'
        label, r_mult = _exit_summary(pos, gk)
        from app.services.llm_prompts.strategy_profile import strategy_display_name
        stype = strategy_display_name(gk.get('strategy')) if gk.get('strategy') else ''
        telegram_service.send(
            f"{emo} <b>守门员平仓</b>{tag}\n"
            f"<b>{s} · {dir_zh}</b>" + (f" · 策略 {stype}" if stype else "") + "\n"
            f"{label}\n"
            f"实现盈亏 <b>{pnl:+.3f}</b> USDT（{r_mult:+.2f}R）\n"
            f"本笔已记入学习飞轮", force=True)
    except Exception as e:
        print(f'[gatekeeper_live] notify close error: {type(e).__name__}: {e}')


# ============================================================
# live 原生 trigger 仓的 fill 驱动棍轮 (user 2026-05-30 定):
# exit_step 当大脑算 SL 该在哪 (保本/锁TP台阶/trail, 价格驱动); 原生 trigger 当手服务端执行.
# 探 HL 持仓 size: 变小=某TP成交→TG通知+撤旧SL挂新SL到锁定位; size≈0=SL/TP3成交→record_outcome平仓.
# ⚠️ 交易所服务端行为(触发成交/撤单时序/真盈亏)无法paper验证, 第一笔真单必须盯.
# ============================================================

def _compute_native_sl(side, entry, p, closed_frac, tp_plan, peak_px, cur_px):
    """按**真实状态**算 SL 该在的价位 (棍轮取最有利). 不依赖价格猜成交:
      ① 初始 SL ② 保本(价到 be_activate_r → 移 entry+fee) ③ 锁TP台阶(按**真实已平比例**, 平到哪个
      已挂TP的累计frac就锁到那个TP价位) ④ trailing(峰值 ∓ trail_r×R)。"""
    R = p['init_sl_pct']
    def at_r(r):
        d = r * R / 100.0
        return entry * (1 + d) if side == 'long' else entry * (1 - d)
    cands = [entry * (1 - R / 100) if side == 'long' else entry * (1 + R / 100)]   # ① init
    favR = ((cur_px - entry) if side == 'long' else (entry - cur_px)) / entry * 100
    # ② 保本
    if p.get('use_breakeven', True) and favR >= p.get('be_activate_r', 0.3) * R:
        fee_rt = p.get('fee_pct', 0.035) / 100.0 * 2
        cands.append(entry * (1 + fee_rt) if side == 'long' else entry * (1 - fee_rt))
    # ③ 锁TP台阶 (价格驱动满仓棍轮, user 2026-05-30): 价过TP_n → 满仓SL锁到TP_n价位
    #    → 至少全吃已达最深TP_n (止损移到tp1=最少全吃tp1; 继续下探→全吃tp2). 取已达最深里程碑.
    if p.get('lock_at_tp'):
        for r_m in (p.get('tp1_r', 0.5), p.get('tp2_r', 1.2), p.get('tp3_r', 2.0)):
            if favR >= r_m * R:                  # favR是%, 里程碑 = r_m×R%
                cands.append(at_r(r_m))
    # ④ trailing (台阶之间的连续棍轮缓冲)
    tr = p.get('trail_r')
    if tr is not None and peak_px:
        td = tr * R / 100.0
        cands.append(peak_px * (1 - td) if side == 'long' else peak_px * (1 + td))
    target = max(cands) if side == 'long' else min(cands)
    # 防瞬时触发: SL 必须留在当前价的保护侧 (short=高于现价 / long=低于现价) 至少 0.1%
    if side == 'long':
        target = min(target, cur_px * 0.999)
    else:
        target = max(target, cur_px * 1.001)
    return target


def _manage_native_position(pos, gk) -> dict:
    """真·fill驱动: 按 HL 真实持仓 size 减少判定成交(非价格猜) → 才TG通知、才棍轮SL。"""
    from app.models import db
    from app.services.gatekeeper_learning import record_outcome
    from app.services.exchange_service import get_ticker
    from sqlalchemy.orm.attributes import flag_modified
    import datetime as _dt

    state = gk['state']; params = gk['params']; side = state['side']; entry = state['entry']
    orig = gk.get('orig_size', pos.size) or pos.size
    ex = pos.exchange
    creds = _native_creds(ex, pos.user_id)
    if not creds:
        return {'managed': 0, 'closed': 0}
    _raw_size = _native_position_size(ex, pos.symbol, creds)
    if _raw_size is None:
        # ⚠️ 真钱关键: API 查不到 ≠ 仓没了. 出错就跳过本轮(下个*/5重试), 绝不假平仓
        # (否则交易所抖一下就 DB 标平、回填假数据, 仓还活在交易所=真钱敞口失管).
        print(f'[gatekeeper_live] {pos.symbol}@{ex} 持仓查询失败(None), 跳过本轮不动作')
        return {'managed': 1, 'closed': 0}
    cur_size = abs(_raw_size)
    cur_px = get_ticker(pos.symbol)['price']
    tp_plan = (gk.get('oids') or {}).get('tp_plan') or []

    # 全平 (SL 或最后 TP 成交 → 交易所已确认无仓; 上面已挡掉 None=查询失败)
    if orig > 0 and cur_size <= orig * 0.02:
        pnl = _native_realized_pnl(pos, gk, creds)
        for k in ('sl', 'tp1', 'tp2', 'tp3'):
            oid = (gk.get('oids') or {}).get(k)
            if oid:
                _native_cancel(ex, pos.symbol, oid, creds)
        pos.status = 'closed'; pos.closed_at = _dt.datetime.utcnow()
        pos.realized_pnl = pnl; pos.size = 0.0; gk['pnl'] = pnl
        pos.gk_exit = gk; flag_modified(pos, 'gk_exit')
        if pos.gatekeeper_decision_id:
            record_outcome(pos.gatekeeper_decision_id, pnl)
        _notify_gk_close(pos, gk); db.session.commit()
        return {'managed': 1, 'closed': 1}

    # 真实已平比例 (HL 持仓减少 = 真成交; minTradeNtl 被拒不会减 → 不会误判)
    closed_frac = max(0.0, 1 - cur_size / orig) if orig > 0 else 0.0
    last_frac = gk.get('last_closed_frac', 0.0)
    # 峰值 (棍轮 trailing 基准)
    pk = gk.get('peak')
    gk['peak'] = (max(pk, cur_px) if pk else cur_px) if side == 'long' else (min(pk, cur_px) if pk else cur_px)

    # 有**真成交**(持仓真减少) → TG 通知
    if closed_frac > last_frac + 0.02:
        _notify_tp_fill_real(pos, closed_frac, cur_px)
        gk['last_closed_frac'] = closed_frac

    # 算目标 SL (真实状态驱动) → 变了就撤旧挂新 (按当前剩余 size)
    target_sl = _compute_native_sl(side, entry, params, closed_frac, tp_plan, gk['peak'], cur_px)
    cur_sl = (gk.get('oids') or {}).get('sl_px') or state['sl']
    moved = (side == 'long' and target_sl > cur_sl * 1.0001) or (side == 'short' and target_sl < cur_sl * 0.9999)
    if moved:
        state['sl'] = target_sl
        _resync_native_sl(pos, gk, state, cur_size, creds)
        # 止损上移到了新的 TP 台阶 → TG 通知锁利 (诚实: 说"止损锁利", 非"成交")
        m = _sl_milestone(side, entry, params, target_sl)
        if m > gk.get('locked_milestone', 0):
            gk['locked_milestone'] = m
            _notify_sl_lock(pos, m, target_sl, params)

    gk['state'] = state; pos.gk_exit = gk; flag_modified(pos, 'gk_exit'); db.session.commit()
    return {'managed': 1, 'closed': 0}


def _notify_tp_fill_real(pos, closed_frac, cur_px):
    try:
        from app.services import telegram_service
        telegram_service.send(
            f"✅ <b>守门员分批止盈成交</b> ({pos.symbol.split('/')[0]} {pos.side})\n"
            f"已平 <b>{closed_frac*100:.0f}%</b> @ ~{round(cur_px,4)} · 移动止损跟进锁利", force=True)
    except Exception:
        pass
    return {'managed': 1, 'closed': 0}


def _resync_native_sl(pos, gk, state, cur_size, creds):
    """撤旧 SL trigger, 按当前剩余 size 在 state['sl'] 价位挂新 SL (棍轮上移). 按 pos.exchange 分派。"""
    from sqlalchemy.orm.attributes import flag_modified
    from app.models import db
    ex = pos.exchange
    oids = gk.get('oids') or {}
    if oids.get('sl'):
        _native_cancel(ex, pos.symbol, oids['sl'], creds)
    sz = cur_size if cur_size > 0 else gk.get('orig_size', pos.size)
    r = _native_place_trigger(ex, pos.symbol, state['side'], state['sl'], sz, 'sl', creds)
    oids['sl'] = r.get('oid'); oids['sl_px'] = r.get('trigger_px')
    gk['oids'] = oids; pos.gk_exit = gk; flag_modified(pos, 'gk_exit'); db.session.commit()
    if not r.get('ok'):
        print(f"[gatekeeper_live] {pos.symbol} 重挂SL失败: {r.get('reject_reason')}")


def _native_realized_pnl(pos, gk, creds):
    """平仓后真盈亏: HL 拉 fills.closedPnl / OKX 拉 fetch_okx_order_real_pnl; 失败回退引擎估算。"""
    ex = (pos.exchange or '').lower()
    try:
        if ex == 'okx':
            from app.services.exchange_service import fetch_okx_order_real_pnl
            from app.services.symbols import get_inst_id
            # OKX 平仓真pnl — 用最近成交累加 (按inst); 简化: 拉该inst近期fills closedPnl
            r = fetch_okx_order_real_pnl(get_inst_id(pos.symbol), None, creds=creds)
            if r.get('found'):
                return round(r['real_pnl'], 4)
        else:
            from app.services.hyperliquid_service import _exchange_client, hl_base
            _, info = _exchange_client(creds)
            addr = creds.get('main_address')           # HL user-of-record (非 agent signer)
            fills = info.user_fills(addr) or []
            base = hl_base(pos.symbol)
            opened = pos.opened_at.timestamp() * 1000 if pos.opened_at else 0
            tot = 0.0; hit = False
            for f in fills:
                if f.get('coin') == base and float(f.get('time', 0)) >= opened:
                    cp = f.get('closedPnl')
                    if cp is not None:
                        tot += float(cp); hit = True
            if hit:
                return round(tot, 4)
    except Exception as e:
        print(f'[gatekeeper_live] native real_pnl fetch fail: {type(e).__name__}: {e}')
    return round(gk.get('pnl', 0.0), 4)   # 回退: 引擎累计估算


def _notify_tp_fill(pos, tp_label, new_sl):
    try:
        from app.services import telegram_service
        telegram_service.send(
            f"✅ <b>守门员 {tp_label} 成交</b> ({pos.symbol.split('/')[0]} {pos.side})\n"
            f"移动止损已上移到 <b>{round(new_sl, 4)}</b> (锁定利润)", force=True)
    except Exception:
        pass
