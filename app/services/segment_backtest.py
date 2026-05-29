"""Phase 15 R1: 段回测引擎 — 三层架构 (策略层不动 + 位置层 + 出场层)

蓝图 project-phase15-blueprint。user 确认的三层媒合结构 (2026-05-29):
  ① 策略层 (现有 signal_fn, 不动): 回答"何时有机会+多空" — 各策略自己的指标触发。
  ② 位置层 (统一, 策略无关): 回答"这机会在头/中段/尾部?" — 乖离+动能定位, **末段躲避**(否决追尾)。
  ③ 出场层 (统一, 策略无关): 放量保本 → 分批吃中段 → 尾部走。

关注点分离: 策略=机会发现器(不抢它方向判断); 位置层=末段过滤(砍A1追尾被打); 出场层=风险/利润管理。
"段"用乖离(ATR归一)+动能定义 = 任何 symbol/TF/策略通用的坐标系 → 20策略套同一框架, 不各自改。

**每层可独立开关** (use_position_filter / use_breakeven / use_partial_tp / use_tail_exit) →
R4 隔离各层贡献 (防混场景教训: 之前分批+60其实全是宽止损功劳)。全关 ≈ 固定SL+反向信号平仓(baseline)。

⚠️ offline 回测, 零 live. 位置层"乖离定段"+尾部走 均待 R4 大样本+OOS 验证 (R2 已暴露阈值敏感过拟合风险)。
"""
from __future__ import annotations

from app.services.strategy_engine import get_signal, get_candle_df
from app.services import segment_signals as seg
from app.services import candle_patterns as cp

_TF_SEC = {'1m': 60, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600, '4h': 14400, '1d': 86400}


def _favorable(side, price, entry):
    return (price - entry) if side == 'long' else (entry - price)


def segment_backtest(base_candles, aux_candles=None, *, strategy_type='custom',
                     params=None, signal_fn=None, base_tf='1h', aux_tf='5m',
                     leverage=15.0, position_size_usdt=10.0, fee_pct=0.035,
                     slippage_pct=0.03, warmup=60,
                     # ② 位置层
                     use_position_filter=True, stretch_atr=2.0, require_confluence=False,
                     # ③ 出场层
                     init_sl_pct=1.3, use_breakeven=True, be_activate_r=0.3, be_lock_pct=0.0,
                     use_partial_tp=True, tp1_r=0.5, tp1_frac=0.4, tp2_r=1.2, tp2_frac=0.3,
                     tp3_r=2.0, use_tail_exit=True):
    """三层段回测. 返回 {total_pnl, fills, win_rate, ev_per_fill_usdt, profit_factor,
    by_reason, blocked_late, trades}.
    """
    params = params or {}
    slip = slippage_pct / 100.0
    FEE_RT = (fee_pct / 100.0) * 2
    base = sorted(base_candles, key=lambda c: c['timestamp'])
    aux = sorted(aux_candles, key=lambda c: c['timestamp']) if aux_candles else []
    base_sec = _TF_SEC.get(base_tf, 3600); aux_sec = _TF_SEC.get(aux_tf, 300)

    def sig(df):
        return signal_fn(df, params) if signal_fn else get_signal(strategy_type, df, params)

    trades = []; position = None; aux_j = 0; blocked_late = 0

    def close_part(pos, frac, price, reason, ts):
        side = pos['side']
        filled = price * (1 - slip) if side == 'long' else price * (1 + slip)
        move = _favorable(side, filled, pos['entry']) / pos['entry']
        notional = position_size_usdt * frac
        pnl = move * notional * leverage - notional * (fee_pct / 100.0) * 2
        trades.append({'entry_ts': pos['entry_ts'], 'exit_ts': ts, 'side': side,
                       'entry': pos['entry'], 'exit': round(filled, 6), 'frac': frac,
                       'pnl': round(pnl, 4), 'reason': reason})

    # ② 位置层: 末段躲避 (开仓方向在反向拉伸末段→否决)
    def position_ok(bwin, awin, side):
        if not use_position_filter:
            return True, 'filter_off'
        dev = seg.deviation_state(bwin)
        d = dev.get('dev_atr')
        if d is not None:
            if side == 'long' and d > stretch_atr:
                return False, '末段:价高位拉伸+%.1fATR(慎追多)' % d
            if side == 'short' and d < -stretch_atr:
                return False, '末段:价低位拉伸%.1fATR(慎追空)' % d
        if require_confluence:
            c = seg.confluence(awin if awin else bwin, side)
            if not c['ok']:
                return False, '共振不足(score%.0f)' % c['score']
        return True, 'ok'

    # ③ 出场层: 在一根 aux(5m) bar 上跑保本/分批/尾部走/SL. 返回是否全平.
    def manage_exit(pos, ac, bwin):
        side = pos['side']; E = pos['entry']
        adverse = ac['high'] if side == 'short' else ac['low']
        fav_ext = _favorable(side, ac['low'] if side == 'short' else ac['high'], E) / E * 100
        # R = 初始风险 = entry→init_sl 的价格距离% (TP/保本都按 R 倍数, 自动随止损/波动缩放)
        R = init_sl_pct

        # 保本激活 (浮盈达 be_activate_r 倍 R)
        if use_breakeven and not pos['be'] and fav_ext >= be_activate_r * R:
            pos['be'] = True
            lk = FEE_RT * 100 + be_lock_pct
            pos['sl'] = E * (1 + lk / 100) if side == 'long' else E * (1 - lk / 100)
        # SL (保守先判) — 平剩余
        hit = (adverse <= pos['sl']) if side == 'long' else (adverse >= pos['sl'])
        if hit:
            close_part(pos, pos['rem'], pos['sl'], 'breakeven' if pos['be'] else 'stop_loss', ac['timestamp'])
            pos['rem'] = 0.0; return True
        # 分批 TP1/TP2 (盈亏比: TP_n 距离 = tp_n_r × R)
        if use_partial_tp:
            if not pos['tp1'] and fav_ext >= tp1_r * R:
                d = tp1_r * R; px = E * (1 + d / 100) if side == 'long' else E * (1 - d / 100)
                close_part(pos, tp1_frac, px, 'tp1', ac['timestamp']); pos['rem'] -= tp1_frac; pos['tp1'] = True
            if not pos['tp2'] and fav_ext >= tp2_r * R:
                d = tp2_r * R; px = E * (1 + d / 100) if side == 'long' else E * (1 - d / 100)
                close_part(pos, tp2_frac, px, 'tp2', ac['timestamp']); pos['rem'] -= tp2_frac; pos['tp2'] = True
        # 尾部走: 已过保本(浮盈)且**动能衰竭**(MACD柱崩塌) → 不贪尾, 平剩余
        # (user 2026-05-29 定: 尾部走只用动能衰竭, 不用乖离 — 动能衰竭是更直接的"段结束"信号)
        if use_tail_exit and pos['be'] and pos['rem'] > 1e-9:
            if cp.momentum_state(bwin).get('state') == 'collapsing':
                close_part(pos, pos['rem'], ac['close'], 'tail_exit', ac['timestamp']); pos['rem'] = 0.0; return True
        # TP3 (吃到 tp3_r 倍 R, 剩余全平; "让它跑"=tp3_r 给较远, 中途动能衰竭则尾部走先出)
        if use_partial_tp and pos['rem'] > 1e-9 and fav_ext >= tp3_r * R:
            d = tp3_r * R; px = E * (1 + d / 100) if side == 'long' else E * (1 - d / 100)
            close_part(pos, pos['rem'], px, 'tp3', ac['timestamp']); pos['rem'] = 0.0; return True
        return False

    for i in range(warmup, len(base)):
        bar = base[i]; bclose_t = bar['timestamp'] + base_sec
        bwin = base[:i + 1]
        # 出场: 持仓期间逐 5m bar (无 aux 则用 base bar 自身一次)
        if aux:
            while aux_j < len(aux) and (aux[aux_j]['timestamp'] + aux_sec) <= bclose_t:
                ac = aux[aux_j]
                if position and ac['timestamp'] >= position['entry_ts']:
                    if manage_exit(position, ac, bwin):
                        position = None
                aux_j += 1
        elif position:
            if manage_exit(position, bar, bwin):
                position = None

        # ① 策略层信号
        df = get_candle_df([dict(x) for x in bwin])
        try:
            s = sig(df)
        except Exception:
            s = 'hold'
        is_buy = s in ('buy', 'long'); is_sell = s in ('sell', 'short')

        if position is None and (is_buy or is_sell):
            side = 'long' if is_buy else 'short'
            awin = [c for c in aux if c['timestamp'] + aux_sec <= bclose_t] if aux else None
            ok, _ = position_ok(bwin, awin, side)   # ② 位置层过滤
            if not ok:
                blocked_late += 1
            else:
                ef = bar['close'] * (1 + slip) if side == 'long' else bar['close'] * (1 - slip)
                position = {'side': side, 'entry': ef, 'entry_ts': bar['timestamp'], 'rem': 1.0,
                            'tp1': False, 'tp2': False, 'be': False,
                            'sl': ef * (1 - init_sl_pct / 100) if side == 'long' else ef * (1 + init_sl_pct / 100)}
        elif position is not None:
            opp = (position['side'] == 'long' and is_sell) or (position['side'] == 'short' and is_buy)
            if opp:
                close_part(position, position['rem'], bar['close'], 'signal', bar['timestamp']); position = None

    if position:
        close_part(position, position['rem'], base[-1]['close'], 'end', base[-1]['timestamp'])

    n = len(trades); pnls = [t['pnl'] for t in trades]; total = sum(pnls)
    wins = [p for p in pnls if p > 0]; losses = [p for p in pnls if p < 0]
    by_reason = {}
    for t in trades:
        by_reason[t['reason']] = by_reason.get(t['reason'], 0) + 1
    return {'total_pnl': round(total, 4), 'fills': n,
            'win_rate': round(len(wins) / n * 100, 2) if n else 0,
            'ev_per_fill_usdt': round(total / n, 4) if n else 0,
            'profit_factor': round(sum(wins) / abs(sum(losses)), 3) if losses else None,
            'max_single_loss': round(min(pnls), 4) if pnls else 0,
            'blocked_late': blocked_late, 'by_reason': by_reason, 'trades': trades}
