"""Phase 15: 段引擎出场状态机 — 共享纯函数 (回测 ↔ live 单一真相源, 防漂移)

蓝图 project-phase15-blueprint 中层引擎=通用操作守则. 出场层逻辑 (两段移动止损 + 分批
TP1/2/3 + 尾部走) 原本内联在 segment_backtest.manage_exit; 接 live 后 live 平仓必须跑**同一套**
(否则守门员算 EV 的引擎 ≠ 实际执行 → 学到的经验是假的). 故抽成纯函数, 两边共用.

设计 (与原 manage_exit 字节级等价, 见 tests 回归): 处理**一根 bar** (一般是 5m aux bar),
按保守顺序: ①方向对→移保本 ②SL(先判, 平剩余) ③TP1(分批+锁利) ④TP2(分批) ⑤尾部走(动能衰竭)
⑥TP3(剩余全平). R = init_sl_pct (初始风险=entry→init_sl 价格距离%); TP/保本/锁利全按 R 倍数.

state (dict, 可 JSON 持久化到 Position.exit_state):
  side / entry / rem(剩余仓比 0..1) / sl(当前止损价) / tp1 / tp2 / be (bool 标志位)
params (dict): init_sl_pct / use_breakeven / be_activate_r / be_lock_pct / fee_pct /
  use_partial_tp / tp1_r / tp1_frac / tp2_r / tp2_frac / tp3_r / tp1_lock_r / use_tail_exit
"""
from __future__ import annotations


def _favorable(side, price, entry):
    return (price - entry) if side == 'long' else (entry - price)


def new_exit_state(side: str, entry: float, init_sl_pct: float) -> dict:
    """开仓时初始化出场状态 (rem=1 满仓, sl=初始止损价)。"""
    return {
        'side': side, 'entry': float(entry), 'rem': 1.0,
        'tp1': False, 'tp2': False, 'be': False,
        'sl': entry * (1 - init_sl_pct / 100) if side == 'long'
              else entry * (1 + init_sl_pct / 100),
    }


def exit_step(state: dict, bar: dict, params: dict,
              tail_collapsing: bool = False) -> dict:
    """在一根 bar 上推进出场状态机。返回 {closes:[{frac,price,reason}], fully_closed:bool, state}。

    bar: {high, low, close} (一根 5m bar 的极值, 与回测同口径: adverse 用 high/low 保守判)。
    tail_collapsing: 调用方算好的"动能是否衰竭"(回测用 cp.momentum_state(bwin), live 同). use_tail_exit
      关时忽略。抽出来当入参 = 纯函数不依赖 candle 窗口, 回测/live 各自喂。
    与 manage_exit 完全同序: 保本arm → SL → TP1 → TP2 → tail → TP3。
    """
    p = params
    side = state['side']; E = state['entry']
    init_sl = p['init_sl_pct']
    R = init_sl
    fee_pct = p.get('fee_pct', 0.035)
    FEE_RT = (fee_pct / 100.0) * 2
    adverse = bar['high'] if side == 'short' else bar['low']
    fav_hilo = bar['low'] if side == 'short' else bar['high']
    fav_ext = _favorable(side, fav_hilo, E) / E * 100

    closes = []

    def _tp_price(r):
        d = r * R
        return E * (1 + d / 100) if side == 'long' else E * (1 - d / 100)

    # ① 第一次移动止损=保本: 方向对(浮盈≥be_activate_r×R) → SL移保本位(entry+fee, 不亏)
    if p.get('use_breakeven', True) and not state['be'] and fav_ext >= p.get('be_activate_r', 0.3) * R:
        lk = FEE_RT * 100 + p.get('be_lock_pct', 0.0)
        state['sl'] = E * (1 + lk / 100) if side == 'long' else E * (1 - lk / 100)
        state['be'] = True

    # ② SL (保守先判) — 平剩余
    hit = (adverse <= state['sl']) if side == 'long' else (adverse >= state['sl'])
    if hit:
        closes.append({'frac': state['rem'], 'price': state['sl'],
                       'reason': 'breakeven' if state['be'] else 'stop_loss'})
        state['rem'] = 0.0
        return {'closes': closes, 'fully_closed': True, 'state': state}

    # ③④ 分批 TP1 / TP2 (TP_n 距离 = tp_n_r × R)
    if p.get('use_partial_tp', True):
        if not state['tp1'] and fav_ext >= p.get('tp1_r', 0.5) * R:
            closes.append({'frac': p.get('tp1_frac', 0.5), 'price': _tp_price(p.get('tp1_r', 0.5)),
                           'reason': 'tp1'})
            state['rem'] -= p.get('tp1_frac', 0.5); state['tp1'] = True
            # 第二次移动止损: TP1触发 → SL上移到锁利位 (+tp1_lock_r×R)
            lr = p.get('tp1_lock_r', 0.3) * R
            state['sl'] = E * (1 + lr / 100) if side == 'long' else E * (1 - lr / 100)
        if not state['tp2'] and fav_ext >= p.get('tp2_r', 1.2) * R:
            closes.append({'frac': p.get('tp2_frac', 0.3), 'price': _tp_price(p.get('tp2_r', 1.2)),
                           'reason': 'tp2'})
            state['rem'] -= p.get('tp2_frac', 0.3); state['tp2'] = True

    # ⑤ 尾部走: 已过保本 + 动能衰竭 → 不贪尾, 平剩余 (close 价, 调用方给)
    if p.get('use_tail_exit', False) and state['be'] and state['rem'] > 1e-9:
        if tail_collapsing:
            closes.append({'frac': state['rem'], 'price': bar['close'], 'reason': 'tail_exit'})
            state['rem'] = 0.0
            return {'closes': closes, 'fully_closed': True, 'state': state}

    # ⑥ TP3 (吃到 tp3_r × R, 剩余全平)
    if p.get('use_partial_tp', True) and state['rem'] > 1e-9 and fav_ext >= p.get('tp3_r', 2.0) * R:
        closes.append({'frac': state['rem'], 'price': _tp_price(p.get('tp3_r', 2.0)), 'reason': 'tp3'})
        state['rem'] = 0.0
        return {'closes': closes, 'fully_closed': True, 'state': state}

    return {'closes': closes, 'fully_closed': False, 'state': state}
