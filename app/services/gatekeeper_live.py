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
    # 独占 first-mover: 该 symbol 已有守门员持仓 → 不重开
    exists = (Position.query.filter_by(symbol=symbol, status='open')
              .filter(Position.gatekeeper_decision_id.isnot(None)).first())
    if exists:
        return
    stype = d['strategy']; init_sl = float(d['params']['init_sl_pct'])
    # 参数分层: Team→AI参数最优先 / Pro→用户自设参数
    gp = _resolve_gk_params(user_id, lev, cfg)
    lev = gp['leverage']; size_usdt = gp['size_usdt']
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
    state = new_exit_state(side, fill, init_sl)
    import time as _t
    _entry_ts = int(_t.time())   # 出场管理器只处理入场后新 5m bar (防回放入场前K线)
    pos = Position(
        strategy_id=host.id, user_id=user_id, exchange=exchange, symbol=symbol,
        side=side, size=base_size, entry_price=fill, current_price=fill, status='open',
        gatekeeper_decision_id=d.get('decision_id'),
        gk_exit={'state': state, 'params': exit_params, 'last_ts': _entry_ts,
                 'orig_size': base_size, 'margin': size_usdt, 'order_mode': order_mode,
                 'pnl': 0.0, 'strategy': stype, 'lev': lev, 'slippage_pct': 0.03},
    )
    db.session.add(pos); db.session.commit()
    _notify_live_enter(symbol, d, fill, lev, order_mode, pos.id)


def _notify_live_enter(symbol, d, fill, lev, order_mode, pos_id):
    try:
        from app.services import telegram_service
        tag = '📝纸面' if order_mode == 'paper' else '🔴真钱'
        s = symbol.split('/')[0]
        telegram_service.send(
            f"🤖 <b>守门员开仓</b> ({tag})\n"
            f"<b>{s}</b> {d.get('side')} · {d.get('strategy')} · 杠杆{lev:.0f}x\n"
            f"入场 {fill} · 预期EV {d.get('expected_ev'):.3f} · SL {(d.get('params') or {}).get('init_sl_pct')}%\n"
            f"<i>引擎分批出场 TP1/2/3 (0.5/1.2/2R) 自动管</i>", force=True)
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
                           reason='gk_' + c['reason'])
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


def _notify_gk_close(pos, gk):
    try:
        from app.services import telegram_service
        tag = '📝纸面' if gk.get('order_mode') == 'paper' else '🔴真钱'
        emo = '🟢' if gk['pnl'] >= 0 else '🔴'
        telegram_service.send(
            f"{emo} <b>守门员平仓</b> ({tag})\n"
            f"<b>{pos.symbol.split('/')[0]}</b> {pos.side} · {gk.get('strategy')}\n"
            f"实现盈亏 <b>{gk['pnl']:+.3f}</b> USDT → 已回填校准飞轮", force=True)
    except Exception as e:
        print(f'[gatekeeper_live] notify close error: {type(e).__name__}: {e}')
