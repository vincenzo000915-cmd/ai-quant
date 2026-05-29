"""Phase 15 P0c: K线反转形态识别 + MTF 动能判别器 — AI 操盘手盘感判断层的「料」

定位 (project-edge-ideas 北极星 / project-profit-protection-exit):
- 这是**确定性纯函数**, 喂给判断层 (judgment_gate, Phase 2) 当输入特征, 不做 LLM 实时裁量。
- 核心是 user 在 5m 上肉眼看到、系统却看不到的两样东西:
    1. **顶/底反转形态 (拒绝针 / 吞没 / 星线)** — 尤其放量的「猎杀针」(流动性扫损后回落)。
       5-29 ETH #44 15:15 那根 (O2019.96 H2027.42 L2014.49 C2018.24, vol1952): 上影是实体 4.3 倍、
       收在区间下部、放量 → 经典射击之星/猎杀拒绝针。系统当时连 5m 都没有 → 瞎着被扫顶。
    2. **MACD 柱方向判别器** — project-profit-protection-exit 的核心实证 (n=2 对照):
       #43 AVAX give-back 时柱**扩张** (动能没死→诱多 head-fake→续跌→TP+10%, 该扛);
       #44 ETH give-back 时柱**崩塌** (-1.785→-0.123→+0.73 冲向0→真反转→该锁利)。
       "诱多 vs 真反转" 在这两笔被 MACD柱方向分对了 = "多看一步" 雏形。

设计纪律 (铁律):
- **自包含、零内部依赖** (自己算 EMA/MACD/ATR, 不 import backtest_engine/strategy_engine),
  避免循环依赖, 回测↔运行时↔判断层三处都能调同一份口径 (防漂移, 同 14k-157/158 共享纯函数思路)。
- 纯函数、无副作用、确定性: 同输入永远同输出 (可回测/可归因/可复现)。
- 输入统一为 candles = list[dict] {open,high,low,close,volume,timestamp}, **旧→新** 排序
  (与 backtest_engine / fetch_ohlcv 一致)。
- 形态识别本身**不知道仓位方向**; 它只报"这根是顶部拒绝 (bearish) 还是底部拒绝 (bullish)"。
  方向性的用法 (持空时拒绝针=确认别被吓平 / 想开多时拒绝针=否决追多) 由 judgment_gate 结合 side 决定。

⚠️ 形态/动能须经回测证明提 EV 才进 live (P2 硬门) — 单笔看对 (5-29 ETH) 只是 sanity check, 非验证。
"""
from __future__ import annotations

from typing import Optional


# ============================================================
# K线几何 helper (纯函数)
# ============================================================

def _body(c: dict) -> float:
    """实体绝对大小 |close - open|。"""
    return abs(c['close'] - c['open'])


def _upper_wick(c: dict) -> float:
    """上影线长度 = high - max(open, close)。"""
    return c['high'] - max(c['open'], c['close'])


def _lower_wick(c: dict) -> float:
    """下影线长度 = min(open, close) - low。"""
    return min(c['open'], c['close']) - c['low']


def _range(c: dict) -> float:
    """全幅 = high - low (含影线)。"""
    return c['high'] - c['low']


def _is_bullish(c: dict) -> bool:
    return c['close'] > c['open']


def _is_bearish(c: dict) -> bool:
    return c['close'] < c['open']


def _close_position(c: dict) -> float:
    """收盘价在全幅中的相对位置 0(最低)~1(最高)。中性时 0.5。"""
    rng = _range(c)
    if rng <= 0:
        return 0.5
    return (c['close'] - c['low']) / rng


# ============================================================
# 自包含指标: ATR / EMA / MACD histogram (纯 Python, 不依赖 pandas/ta)
# ============================================================

def compute_atr(candles: list, period: int = 14) -> list:
    """ATR 序列 (简化 rolling-mean TR, 与 backtest_engine._compute_atr_series 同口径)。
    回传与 candles 等长, 前 period 个为 None。
    """
    n = len(candles)
    if not candles or n < period + 1:
        return [None] * n
    trs = []
    prev_close = candles[0]['close']
    for c in candles:
        h, l = c['high'], c['low']
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        trs.append(tr)
        prev_close = c['close']
    atrs: list = [None] * n
    for i in range(period, n):
        atrs[i] = sum(trs[i - period + 1:i + 1]) / period
    return atrs


def _ema_series(values: list, span: int) -> list:
    """标准 EMA, 与 ta/pandas adjust=False 同口径。回传等长 list。"""
    if not values:
        return []
    alpha = 2.0 / (span + 1.0)
    out = [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out


def macd_histogram_series(candles: list, fast: int = 12, slow: int = 26,
                          signal: int = 9) -> list:
    """MACD 柱 (histogram = macd_line - signal_line) 序列, 等长 candles。
    口径与 strategy_engine.macd_signal / ta.trend.MACD 的 macd_diff 一致 (EMA adjust=False)。
    数据不足时该位置为 None。
    """
    n = len(candles)
    if n < slow + signal:
        return [None] * n
    closes = [c['close'] for c in candles]
    ema_fast = _ema_series(closes, fast)
    ema_slow = _ema_series(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = _ema_series(macd_line, signal)
    hist = [m - s for m, s in zip(macd_line, signal_line)]
    # 前 slow+signal 段 EMA 未稳定, 置 None 避免误读
    warmup = slow + signal
    return [None] * warmup + hist[warmup:] if n > warmup else [None] * n


# ============================================================
# MACD 柱方向判别器 — "诱多 vs 真反转" 核心 (project-profit-protection-exit n=2 实证)
# ============================================================

def momentum_state(candles: list, lookback: int = 3, fast: int = 12,
                   slow: int = 26, signal: int = 9) -> dict:
    """读 MACD 柱最近 lookback 根的方向, 判别动能在「扩张」还是「崩塌」。

    返回 {
      'hist': float|None,        # 当前柱值 (正=多动能/负=空动能)
      'slope': float|None,       # 最近 lookback 根柱的平均逐根变化 (向 0 收敛为负绝对值)
      'state': str,              # 'expanding' / 'collapsing' / 'flat' / 'unknown'
      'toward_zero': bool,       # 柱在向 0 收敛 (动能衰减, 反转 tell)
      'reason': str,
    }

    判别哲学 (5-29 对照):
    - #43 AVAX: give-back 时柱**扩张** (|hist| 在变大, 同向动能没死) → 诱多 head-fake, 该扛。
    - #44 ETH: 柱**崩塌** (-1.785→-0.123→+0.73, |hist| 急速向 0 并翻号) → 真反转, 该锁利。
    → "向 0 收敛/翻号" = collapsing = 反转 tell; "远离 0" = expanding = 趋势延续。
    """
    hist = macd_histogram_series(candles, fast, slow, signal)
    vals = [h for h in hist[-lookback:] if h is not None]
    if len(vals) < 2:
        return {'hist': None, 'slope': None, 'state': 'unknown',
                'toward_zero': False, 'reason': 'MACD 柱数据不足'}

    cur = vals[-1]
    prev = vals[0]
    # 逐根平均变化
    slope = (vals[-1] - vals[0]) / (len(vals) - 1)
    # |hist| 是在变大(扩张/趋势)还是变小(崩塌/向0/反转)?
    toward_zero = abs(cur) < abs(prev)
    flipped = (cur > 0) != (prev > 0)  # 翻号 = 动能反向, 最强反转信号

    # flat 阈值: 用柱自身近窗口幅度的小比例, 避免噪音误判
    span = max(abs(v) for v in vals) or 1e-9
    if abs(slope) < 0.05 * span and not flipped:
        state = 'flat'
        reason = 'MACD 柱走平, 动能不明'
    elif flipped or (toward_zero and abs(slope) >= 0.05 * span):
        state = 'collapsing'
        reason = ('MACD 柱翻号 (动能反向)' if flipped
                  else 'MACD 柱向 0 收敛 (同向动能崩塌→反转 tell)')
    else:
        state = 'expanding'
        reason = 'MACD 柱远离 0 (同向动能扩张→趋势延续, give-back 多为诱多 head-fake)'

    return {'hist': cur, 'slope': slope, 'state': state,
            'toward_zero': toward_zero, 'flipped': flipped, 'reason': reason}


# ============================================================
# 单/多根反转形态识别
# ============================================================

def detect_candle_pattern(candles: list, *, atr: Optional[float] = None,
                          wick_body_ratio: float = 2.0,
                          wick_range_ratio: float = 0.5,
                          body_atr_max: float = 0.6) -> dict:
    """识别最后一根 (含必要的前 1~2 根组合) 的顶/底反转形态。

    返回 {
      'pattern': str|None,    # 'shooting_star'/'hammer'/'bearish_engulfing'/
                              #  'bullish_engulfing'/'evening_star'/'morning_star'/None
      'direction': str|None,  # 'bearish'(顶部拒绝) / 'bullish'(底部拒绝)
      'strength': float,      # 0~1 形态强度 (影线越长/吞没越彻底越高)
      'reason': str,
    }

    参数:
    - wick_body_ratio: 影线须 >= 实体的几倍 (默认 2x, 业界射击之星/锤子标准)。
    - wick_range_ratio: 影线须占全幅几成 (默认 0.5)。
    - body_atr_max: 星线/拒绝针的小实体须 <= 几倍 ATR (默认 0.6, 过滤大实体假信号)。
      atr 为 None 时跳过此过滤 (只用相对几何), 仍可工作。
    """
    if not candles:
        return {'pattern': None, 'direction': None, 'strength': 0.0,
                'reason': '无 K 线'}
    c = candles[-1]
    rng = _range(c)
    if rng <= 0:
        return {'pattern': None, 'direction': None, 'strength': 0.0,
                'reason': '十字一线 (无波幅)'}
    body = _body(c)
    uw = _upper_wick(c)
    lw = _lower_wick(c)
    body_small = (body <= body_atr_max * atr) if atr else (body < 0.34 * rng)

    # --- 单根: 射击之星 (顶部拒绝针) ---
    if (uw >= wick_body_ratio * max(body, 1e-9) and uw >= wick_range_ratio * rng
            and _close_position(c) <= 0.45 and body_small):
        strength = min(1.0, (uw / rng) * 1.2)
        return {'pattern': 'shooting_star', 'direction': 'bearish',
                'strength': round(strength, 3),
                'reason': f'射击之星: 上影占全幅{uw/rng:.0%}、是实体{uw/max(body,1e-9):.1f}倍、收区间下部 → 顶部拒绝'}

    # --- 单根: 锤子线 (底部拒绝针) ---
    if (lw >= wick_body_ratio * max(body, 1e-9) and lw >= wick_range_ratio * rng
            and _close_position(c) >= 0.55 and body_small):
        strength = min(1.0, (lw / rng) * 1.2)
        return {'pattern': 'hammer', 'direction': 'bullish',
                'strength': round(strength, 3),
                'reason': f'锤子线: 下影占全幅{lw/rng:.0%}、是实体{lw/max(body,1e-9):.1f}倍、收区间上部 → 底部拒绝'}

    # --- 双根: 吞没 ---
    if len(candles) >= 2:
        p = candles[-2]
        pbody = _body(p)
        if (_is_bearish(c) and _is_bullish(p) and body > pbody
                and c['close'] <= p['open'] and c['open'] >= p['close']):
            strength = min(1.0, body / max(pbody, 1e-9) / 2.0)
            return {'pattern': 'bearish_engulfing', 'direction': 'bearish',
                    'strength': round(strength, 3),
                    'reason': '看跌吞没: 阴线实体完全吞没前阳线 → 顶部反转'}
        if (_is_bullish(c) and _is_bearish(p) and body > pbody
                and c['close'] >= p['open'] and c['open'] <= p['close']):
            strength = min(1.0, body / max(pbody, 1e-9) / 2.0)
            return {'pattern': 'bullish_engulfing', 'direction': 'bullish',
                    'strength': round(strength, 3),
                    'reason': '看涨吞没: 阳线实体完全吞没前阴线 → 底部反转'}

    # --- 三根: 黄昏星 / 晨星 ---
    if len(candles) >= 3:
        a, b, d = candles[-3], candles[-2], candles[-1]
        b_small = _body(b) < 0.5 * _body(a) if _body(a) > 0 else False
        # 黄昏星: 大阳 → 小实体(犹豫) → 大阴收回阳线一半以下
        if (_is_bullish(a) and b_small and _is_bearish(d)
                and d['close'] < (a['open'] + a['close']) / 2):
            return {'pattern': 'evening_star', 'direction': 'bearish',
                    'strength': 0.7,
                    'reason': '黄昏星: 涨→犹豫→放量回收 → 顶部三根反转'}
        # 晨星: 大阴 → 小实体 → 大阳收回阴线一半以上
        if (_is_bearish(a) and b_small and _is_bullish(d)
                and d['close'] > (a['open'] + a['close']) / 2):
            return {'pattern': 'morning_star', 'direction': 'bullish',
                    'strength': 0.7,
                    'reason': '晨星: 跌→犹豫→放量收复 → 底部三根反转'}

    return {'pattern': None, 'direction': None, 'strength': 0.0,
            'reason': '无明显反转形态'}


# ============================================================
# 放量拒绝针 = 猎杀针 (流动性扫损后回落)
# ============================================================

def detect_hunt_wick(candles: list, *, vol_lookback: int = 20,
                     vol_mult: float = 1.8, atr: Optional[float] = None) -> dict:
    """识别「猎杀针」: 拒绝针 (射击之星/锤子) + 放量 → 价格捅破显眼位扫损后被打回。
    = project-edge-ideas "明显位放量插破不跟进=猎杀, 反着读" 的显式探测。

    返回 {
      'is_hunt': bool,
      'direction': str|None,   # bearish(上插猎多头止损后回落) / bullish(下插猎空头止损后回落)
      'vol_ratio': float|None, # 当根量 / 近窗口均量
      'strength': float,
      'reason': str,
    }
    """
    pat = detect_candle_pattern(candles, atr=atr)
    if pat['pattern'] not in ('shooting_star', 'hammer'):
        return {'is_hunt': False, 'direction': None, 'vol_ratio': None,
                'strength': 0.0, 'reason': f"非拒绝针 ({pat['pattern']})"}

    if len(candles) < vol_lookback + 1:
        return {'is_hunt': False, 'direction': pat['direction'], 'vol_ratio': None,
                'strength': 0.0, 'reason': '量能历史不足'}

    cur_vol = candles[-1].get('volume') or 0.0
    prior = [c.get('volume') or 0.0 for c in candles[-vol_lookback - 1:-1]]
    avg_vol = (sum(prior) / len(prior)) if prior else 0.0
    if avg_vol <= 0:
        return {'is_hunt': False, 'direction': pat['direction'], 'vol_ratio': None,
                'strength': 0.0, 'reason': '均量为 0'}
    vol_ratio = cur_vol / avg_vol

    if vol_ratio >= vol_mult:
        # 放量拒绝 = 真的有流动性被吃 (扫损) 后回落, 比缩量假针可信
        strength = min(1.0, pat['strength'] * min(vol_ratio / vol_mult, 2.0) / 2.0 + 0.4)
        return {'is_hunt': True, 'direction': pat['direction'],
                'vol_ratio': round(vol_ratio, 2), 'strength': round(strength, 3),
                'reason': (f"猎杀针: {pat['pattern']} + 放量{vol_ratio:.1f}x均量 "
                           f"→ 捅破显眼位扫损后被打回 ({pat['direction']})")}
    return {'is_hunt': False, 'direction': pat['direction'],
            'vol_ratio': round(vol_ratio, 2), 'strength': 0.0,
            'reason': f"拒绝针但缩量({vol_ratio:.1f}x) → 可能假针/动能虚"}


# ============================================================
# 一站式盘感读数 — 给 judgment_gate (Phase 2) 的综合特征
# ============================================================

def read_price_action(candles: list, *, atr_period: int = 14) -> dict:
    """把上述纯函数打包成一份盘感特征 dict, 供判断层 (judgment_gate) 编排。
    不做任何方向性/仓位判断 — 只产出确定性特征, 由调用方结合 side/regime 决策。
    """
    if not candles:
        return {'ok': False, 'reason': '无 K 线'}
    atr_series = compute_atr(candles, period=atr_period)
    atr_now = atr_series[-1] if atr_series else None
    pat = detect_candle_pattern(candles, atr=atr_now)
    hunt = detect_hunt_wick(candles, atr=atr_now)
    mom = momentum_state(candles)
    return {
        'ok': True,
        'pattern': pat,
        'hunt': hunt,
        'momentum': mom,
        'atr': atr_now,
        'last_close': candles[-1]['close'],
    }
