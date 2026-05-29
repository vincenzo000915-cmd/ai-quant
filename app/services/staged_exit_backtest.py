"""Phase 15: 分批出场回测引擎 — 验证"顺势entry + 过安全线保本 + TP1/TP2分批"操盘体系

来源: user 机构人工操盘成熟打法 (2026-05-29 对话, 真实12笔实证):
  策略+指标 → 顺势开仓 → 过安全线(浮盈达标) → 止损移进盈利区(这笔不亏) → TP1 平50% / TP2 平剩余。

与 judgment_gate (判断闸/预测反转, 真实数据证否) 的本质区别:
  这是**机械出场风控** — 不预测反转, 纯按价格"过没过线"动作 → 确定性、可回测、机械执行 (最合铁律)。
  真实12笔: 那天 -0.647 → 分批 -0.10~-0.15 (Δ+0.5), #50被猎杀那笔 -0.396→+0.13, 赢家基本保留。

设计:
- entry 走 base TF 策略信号 (顺势, 复用现有 signal_fn); 出场用 **aux 细 TF (5m) 粒度**扫描
  (#50 实证: 1h 粒度太粗错过浮盈高点, 反转/猎杀早在 5m 发生)。
- 出场体系 (按价格距离 %, 与杠杆解耦, 避开 SL×杠杆耦合矛盾):
    1. 保本: 有利浮盈达 be_activate% → SL 移到 entry±(FEE+be_lock) (扣费后至少保本/锁微利)。
    2. TP1: 有利达 tp1% → 平 tp1_frac 仓 (落袋)。
    3. TP2: 剩余有利达 tp2% → 平剩余。
    4. SL: 不利碰当前 SL (初始 init_sl% 或已上移的保本) → 平剩余。
- 同一根 5m bar 多事件: 保守先判不利(SL)再判有利(TP), 避免乐观高估。

⚠️ 纯回测, 零 live 改动. 当前 5m 数据仅~5天 → 验证机制+扫参数, 更长史待 P0b 前向积累.
"""
from __future__ import annotations

from app.services.strategy_engine import get_signal, get_candle_df

_TF_SEC = {'1m': 60, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600,
           '4h': 14400, '1d': 86400}


def _favorable(side: str, price: float, entry: float) -> float:
    """有利方向的价格距离 (正=盈利方向). long: price-entry / short: entry-price."""
    return (price - entry) if side == 'long' else (entry - price)


def staged_backtest(base_candles: list, aux_candles: list, *,
                    strategy_type: str, params: dict, signal_fn=None,
                    base_tf: str = '1h', aux_tf: str = '5m',
                    leverage: float = 15.0, position_size_usdt: float = 10.0,
                    fee_pct: float = 0.035, slippage_pct: float = 0.03,
                    warmup: int = 60,
                    # 分批出场参数 (价格距离 %, 与杠杆解耦)
                    init_sl_pct: float = 1.0,    # 初始硬止损 (价%, 保本未激活前兜底)
                    be_activate_pct: float = 0.5,  # 有利浮盈达此 → SL 移保本
                    be_lock_pct: float = 0.0,     # 保本位再锁多少 (0=纯保本扣费)
                    tp1_pct: float = 0.5, tp1_frac: float = 0.5,  # TP1 目标+平仓比例
                    tp2_pct: float = 1.2) -> dict:
    """跑分批出场回测. 返回 {trades, total_pnl, win_rate, ev_per_trade_usdt, ...}.

    fee/slip 用价格距离 % 口径; pnl = 仓位名义 × 价格变动% × 杠杆 − fee.
    """
    fee = fee_pct / 100.0
    slip = slippage_pct / 100.0
    base = sorted(base_candles, key=lambda c: c['timestamp'])
    aux = sorted(aux_candles, key=lambda c: c['timestamp']) if aux_candles else []
    base_sec = _TF_SEC.get(base_tf, 3600)
    aux_sec = _TF_SEC.get(aux_tf, 300)

    def sig(df):
        if signal_fn:
            return signal_fn(df, params)
        return get_signal(strategy_type, df, params)

    trades = []
    position = None
    aux_j = 0
    FEE_RT = fee * 2  # 往返 fee (价格%口径近似)

    def close_partial(pos, frac, exit_price, reason, ts):
        """平 frac 比例的仓, 记一笔 trade (pnl 为该比例部分的净额)."""
        side = pos['side']
        # 出场滑点: 不利方向
        filled = exit_price * (1 - slip) if side == 'long' else exit_price * (1 + slip)
        move = _favorable(side, filled, pos['entry']) / pos['entry']  # 有利方向收益率(价)
        notional = position_size_usdt * frac
        gross = move * notional * leverage
        f = notional * fee * 2  # 该部分开+平 fee
        pnl = gross - f
        trades.append({
            'entry_ts': pos['entry_ts'], 'exit_ts': ts, 'side': side,
            'entry_price': pos['entry'], 'exit_price': round(filled, 6),
            'frac': frac, 'pnl': round(pnl, 4),
            'pnl_pct': round(move * 100 * leverage, 4), 'reason': reason,
        })

    def staged_check(pos, ac):
        """在一根 aux(5m) bar 上跑分批出场. 修改 pos (remaining/sl/标志), 返回是否全平."""
        side = pos['side']; E = pos['entry']
        hi, lo = ac['high'], ac['low']
        adverse = hi if side == 'short' else lo   # 不利极值 (判 SL)
        fav_ext = _favorable(side, lo if side == 'short' else hi, E) / E * 100  # 最大有利浮盈%

        # 1. 保本激活 (有利浮盈达 be_activate → SL 移保本/锁利)
        if not pos['be_moved'] and fav_ext >= be_activate_pct:
            pos['be_moved'] = True
            lock = (FEE_RT * 100 + be_lock_pct)  # 价% : 扣往返费 + 锁利
            pos['sl_price'] = E * (1 + lock / 100) if side == 'long' else E * (1 - lock / 100)
            # 注: long 保本SL在entry上方(价跌回触发); short 在下方(价涨回触发)

        # 2. SL 检查 (保守先判不利) — 平剩余
        sl = pos['sl_price']
        sl_hit = (adverse <= sl) if side == 'long' else (adverse >= sl)
        if sl_hit:
            reason = 'breakeven' if pos['be_moved'] else 'stop_loss'
            close_partial(pos, pos['remaining'], sl, reason, ac['timestamp'])
            pos['remaining'] = 0.0
            return True

        # 3. TP1 部分平 (有利达 tp1)
        if not pos['tp1_done'] and fav_ext >= tp1_pct:
            tp1_price = E * (1 + tp1_pct / 100) if side == 'long' else E * (1 - tp1_pct / 100)
            close_partial(pos, tp1_frac, tp1_price, 'tp1', ac['timestamp'])
            pos['remaining'] -= tp1_frac
            pos['tp1_done'] = True

        # 4. TP2 平剩余 (有利达 tp2)
        if pos['remaining'] > 1e-9 and fav_ext >= tp2_pct:
            tp2_price = E * (1 + tp2_pct / 100) if side == 'long' else E * (1 - tp2_pct / 100)
            close_partial(pos, pos['remaining'], tp2_price, 'tp2', ac['timestamp'])
            pos['remaining'] = 0.0
            return True
        return False

    for i in range(warmup, len(base)):
        bar = base[i]
        base_close_t = bar['timestamp'] + base_sec
        # 推进 aux 到当前 base bar 收盘, 持仓期间逐根 5m 做 staged 出场
        while aux_j < len(aux) and (aux[aux_j]['timestamp'] + aux_sec) <= base_close_t:
            ac = aux[aux_j]
            if position and ac['timestamp'] >= position['entry_ts']:
                if staged_check(position, ac):
                    position = None
            aux_j += 1

        # base bar 收盘: 信号
        df = get_candle_df([dict(x) for x in base[:i + 1]])
        try:
            s = sig(df)
        except Exception:
            s = 'hold'
        is_buy = s in ('buy', 'long'); is_sell = s in ('sell', 'short')

        if position is None and (is_buy or is_sell):
            side = 'long' if is_buy else 'short'
            entry_fill = bar['close'] * (1 + slip) if side == 'long' else bar['close'] * (1 - slip)
            position = {
                'side': side, 'entry': entry_fill, 'entry_ts': bar['timestamp'],
                'remaining': 1.0, 'tp1_done': False, 'be_moved': False,
                'sl_price': (entry_fill * (1 - init_sl_pct / 100) if side == 'long'
                             else entry_fill * (1 + init_sl_pct / 100)),
            }
        elif position is not None:
            # 反向信号 → 平剩余 (按 base bar 收盘价)
            opp = (position['side'] == 'long' and is_sell) or (position['side'] == 'short' and is_buy)
            if opp:
                close_partial(position, position['remaining'], bar['close'], 'signal', bar['timestamp'])
                position = None

    # 收尾强平
    if position:
        close_partial(position, position['remaining'], base[-1]['close'], 'end', base[-1]['timestamp'])

    # 统计
    n = len(trades)
    pnls = [t['pnl'] for t in trades]
    total = sum(pnls)
    wins = [p for p in pnls if p > 0]; losses = [p for p in pnls if p < 0]
    by_reason = {}
    for t in trades:
        by_reason[t['reason']] = by_reason.get(t['reason'], 0) + 1
    return {
        'total_pnl': round(total, 4),
        'fills': n,
        'win_rate': round(len(wins) / n * 100, 2) if n else 0,
        'ev_per_fill_usdt': round(total / n, 4) if n else 0,
        'sum_wins': round(sum(wins), 4), 'sum_losses': round(sum(losses), 4),
        'profit_factor': round(sum(wins) / abs(sum(losses)), 3) if losses else None,
        'by_reason': by_reason,
        'trades': trades,
    }
