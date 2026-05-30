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
                     slippage_pct=0.03, warmup=60, funding_apr=0.0,
                     # ② 位置层
                     use_position_filter=True, stretch_atr=2.0, require_confluence=False,
                     # ③ 出场层
                     init_sl_pct=1.3, use_breakeven=True, be_activate_r=0.3, be_lock_pct=0.0,
                     use_partial_tp=True, tp1_r=0.5, tp1_frac=0.5, tp2_r=1.2, tp2_frac=0.3,
                     tp3_r=2.0, tp1_lock_r=0.3, use_tail_exit=False, trail_r=None,
                     lock_at_tp=False):
                     # 两段移动止损: ①方向对(浮盈≥手续费)→移保本 ②TP1触发→移到+tp1_lock_r倍R锁利
                     # be_activate_r 废弃; 尾部走(动能)默认关(user定TP硬性不看动能)
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
        # Gap B (user 2026-05-30): 资金费按持仓时长扣在**名义**上 (正费率=多头付空头 → 做多成本/做空收益).
        # funding_apr=0 时无影响 (其它回测调用方不变). 持仓越久(长线)累积越明显.
        if funding_apr:
            hold_frac = max(0, ts - pos['entry_ts']) / 31_536_000.0   # /秒每年
            pnl += (position_size_usdt * frac * leverage) * funding_apr * hold_frac * (1 if side == 'short' else -1)
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
    # Phase 15: 决策逻辑外移到 segment_exit.exit_step (回测↔live 单一真相源, 防漂移);
    # 这里只保留 close_part 的滑点/pnl 计算 + 喂 tail 动能 (回测特有的 bwin 窗口).
    _exit_params = {
        'init_sl_pct': init_sl_pct, 'fee_pct': fee_pct,
        'use_breakeven': use_breakeven, 'be_activate_r': be_activate_r, 'be_lock_pct': be_lock_pct,
        'use_partial_tp': use_partial_tp, 'tp1_r': tp1_r, 'tp1_frac': tp1_frac,
        'tp2_r': tp2_r, 'tp2_frac': tp2_frac, 'tp3_r': tp3_r, 'tp1_lock_r': tp1_lock_r,
        'use_tail_exit': use_tail_exit, 'trail_r': trail_r, 'lock_at_tp': lock_at_tp,
    }

    def manage_exit(pos, ac, bwin):
        from app.services.segment_exit import exit_step
        # 只在尾部走开启时算动能 (省成本); be/rem 门控交给 exit_step 内部 (与原 manage_exit 同序)
        tail_collapsing = (use_tail_exit
                           and cp.momentum_state(bwin).get('state') == 'collapsing')
        r = exit_step(pos, ac, _exit_params, tail_collapsing=tail_collapsing)
        for c in r['closes']:
            close_part(pos, c['frac'], c['price'], c['reason'], ac['timestamp'])
        return r['fully_closed']

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
