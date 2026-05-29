"""Phase 15 R2: 入场共振信号 — 抓"头/中段"而非追"末段" (user 机构操盘体系核心)

蓝图见 memory project-phase15-blueprint。核心命题 (user 最锋利洞察):
  追随型指标(突破/MACD)滞后 → 永远末段进场 → 起涨起跌(鱼头)抓不到, 吃鱼尾 → 进场即被反转/猎杀。
  解法 = 多指标**共振**(尤其 RSI 背离=动能衰竭=转折前兆/左侧信号) + **末段/乖离识别** →
  争取在头/中段进, 避开末段追入。

纯函数 (像 candle_patterns, 零内部依赖, 回测↔live 同口径)。喂给 R1 段回测引擎当入场 hook。

⚠️ 背离/共振最容易在震荡里乱出信号 + 事后找规则易过拟合 (见蓝图方法论铁律): 必须大样本+OOS
   验证能否真比突破更早抓头中段、且不被震荡假信号骗 — 当前仅建能力, 不预设有效。
"""
from __future__ import annotations

from typing import Optional
from app.services.candle_patterns import _ema_series, macd_histogram_series, compute_atr


# ============================================================
# RSI (纯 Python, Wilder 平滑)
# ============================================================

def rsi_series(candles: list, period: int = 14) -> list:
    """RSI 序列, 等长 candles, 前 period 个为 None。Wilder 平滑 (与 ta.momentum.rsi 同口径)。"""
    n = len(candles)
    if n < period + 1:
        return [None] * n
    closes = [c['close'] for c in candles]
    gains, losses = [], []
    for i in range(1, n):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0)); losses.append(max(-d, 0.0))
    out: list = [None] * n
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    def rsi_of(ag, al):
        if al == 0: return 100.0
        rs = ag / al
        return 100.0 - 100.0 / (1 + rs)
    out[period] = rsi_of(avg_g, avg_l)
    for i in range(period + 1, n):
        avg_g = (avg_g * (period - 1) + gains[i - 1]) / period
        avg_l = (avg_l * (period - 1) + losses[i - 1]) / period
        out[i] = rsi_of(avg_g, avg_l)
    return out


# ============================================================
# 摆动点 (swing high/low) — 背离检测的锚
# ============================================================

def _swings(values: list, left: int = 2, right: int = 2, kind: str = 'low') -> list:
    """找局部摆动低/高点的索引 (前 left 后 right 都不更极端)。返回 [(idx, value), ...]。"""
    out = []
    n = len(values)
    for i in range(left, n - right):
        v = values[i]
        if v is None:
            continue
        window = [values[j] for j in range(i - left, i + right + 1) if values[j] is not None]
        if len(window) < left + right + 1:
            continue
        if kind == 'low' and v == min(window):
            out.append((i, v))
        elif kind == 'high' and v == max(window):
            out.append((i, v))
    return out


# ============================================================
# RSI 背离检测 — 动能衰竭/转折前兆 (左侧信号)
# ============================================================

def detect_rsi_divergence(candles: list, *, period: int = 14,
                          left: int = 2, right: int = 2,
                          max_lookback: int = 60) -> dict:
    """检测最近的 RSI 背离。返回 {type, strength, reason}。

    - 'bullish' 底背离: 价格创**更低低点**, RSI 却**更高低点** → 下跌动能衰竭 → 起涨前兆。
    - 'bearish' 顶背离: 价格创**更高高点**, RSI 却**更低高点** → 上涨动能衰竭 → 起跌前兆。
    比较最近两个同类摆动点 (在 max_lookback 窗口内)。
    """
    rsi = rsi_series(candles, period)
    closes = [c['close'] for c in candles]
    if len([r for r in rsi if r is not None]) < left + right + 3:
        return {'type': None, 'strength': 0.0, 'reason': 'RSI 数据不足'}

    seg = slice(max(0, len(candles) - max_lookback), len(candles))
    base = seg.start

    # 底背离: 价格低点
    plows = [(i, closes[i]) for i in range(base, len(candles))]
    price_lows = _swings([p[1] for p in plows], left, right, 'low')
    if len(price_lows) >= 2:
        (i1, p1), (i2, p2) = price_lows[-2], price_lows[-1]
        gi1, gi2 = base + i1, base + i2
        r1, r2 = rsi[gi1], rsi[gi2]
        if r1 is not None and r2 is not None and p2 < p1 and r2 > r1:
            strength = min(1.0, (r2 - r1) / 10.0)
            return {'type': 'bullish', 'strength': round(strength, 3),
                    'reason': f'RSI底背离: 价低点{p1:.4f}→{p2:.4f}(更低) 但RSI{r1:.1f}→{r2:.1f}(更高) → 跌势动能衰竭'}

    # 顶背离: 价格高点
    price_highs = _swings([p[1] for p in plows], left, right, 'high')
    if len(price_highs) >= 2:
        (i1, p1), (i2, p2) = price_highs[-2], price_highs[-1]
        gi1, gi2 = base + i1, base + i2
        r1, r2 = rsi[gi1], rsi[gi2]
        if r1 is not None and r2 is not None and p2 > p1 and r2 < r1:
            strength = min(1.0, (r1 - r2) / 10.0)
            return {'type': 'bearish', 'strength': round(strength, 3),
                    'reason': f'RSI顶背离: 价高点{p1:.4f}→{p2:.4f}(更高) 但RSI{r1:.1f}→{r2:.1f}(更低) → 涨势动能衰竭'}

    return {'type': None, 'strength': 0.0, 'reason': '无背离'}


# ============================================================
# 乖离率 — 末段识别 (离均线越远越可能是末段, 不该追)
# ============================================================

def deviation_state(candles: list, ma_period: int = 20, atr_period: int = 14) -> dict:
    """价格相对 MA 的乖离 (用 ATR 归一化, 与波动率解耦)。
    返回 {dev_atr, stretched, reason}: dev_atr 大 = 离均线远 = 末段/超买超卖 → 追入易被打。
    """
    closes = [c['close'] for c in candles]
    if len(closes) < ma_period:
        return {'dev_atr': None, 'stretched': False, 'reason': '数据不足'}
    ma = sum(closes[-ma_period:]) / ma_period
    atr = compute_atr(candles, atr_period)
    a = atr[-1] if atr and atr[-1] else None
    if not a:
        return {'dev_atr': None, 'stretched': False, 'reason': 'ATR 不足'}
    dev = (closes[-1] - ma) / a   # 价偏离 MA 多少个 ATR
    stretched = abs(dev) >= 2.0   # 经验阈值: 离 MA >2 ATR = 拉伸/末段
    return {'dev_atr': round(dev, 2), 'stretched': stretched,
            'reason': f'价偏离MA{ma_period} {dev:+.1f}个ATR' + (' → 拉伸末段(慎追)' if stretched else '')}


# ============================================================
# 共振判定 — 多指标同向确认 (头/中段入场)
# ============================================================

def confluence(candles: list, side: str) -> dict:
    """判断开仓方向 side 是否有多指标共振支持 (争取头/中段, 避开末段追入)。
    返回 {ok, score, signals, reason}。score = 共振票数。

    共振要素 (同向):
    - RSI 背离与方向一致 (做多需底背离/做空需顶背离) = 转折前兆 (强, +2)。
    - MACD 柱方向支持 (做多 hist 转正抬头/做空转负) (+1)。
    - 未处于反向拉伸末段 (做多时不在高位>2ATR / 做空时不在低位) (+1)。
    """
    div = detect_rsi_divergence(candles)
    mom_hist = macd_histogram_series(candles)
    h = next((x for x in reversed(mom_hist) if x is not None), None)
    dev = deviation_state(candles)
    want = 'bullish' if side in ('long', 'buy') else 'bearish'

    signals = []
    score = 0.0
    if div['type'] == want:
        score += 2.0; signals.append(('rsi_divergence', div['reason']))
    if h is not None:
        if (want == 'bullish' and h > 0) or (want == 'bearish' and h < 0):
            score += 1.0; signals.append(('macd_align', f'MACD柱{h:+.2f}同向'))
    # 末段拉伸惩罚: 追多于高位拉伸 / 追空于低位拉伸 → 不加分(甚至该躲)
    d = dev.get('dev_atr')
    if d is not None:
        late = (want == 'bullish' and d > 2.0) or (want == 'bearish' and d < -2.0)
        if not late:
            score += 1.0; signals.append(('not_stretched', dev['reason']))
        else:
            signals.append(('STRETCHED_LATE', dev['reason'] + ' ← 末段追入风险'))

    ok = score >= 2.0
    return {'ok': ok, 'score': score, 'signals': signals,
            'reason': ('共振支持' if ok else '共振不足') + f' (score={score})'}


# ============================================================
# Phase 15: 突破-回踩确认入场 (breakout-retest) — user 实战核心入场逻辑
# ============================================================

def breakout_retest_signal(df, params=None):
    """user 实战入场 (2026-05-29): 放量突破前高→回踩不破→进 (做空对称).
    精髓: 不追突破那一下(末段/被猎), 等回踩确认前高变支撑(初段) + 放量 + MACD动能。

    df: DataFrame(open/high/low/close/volume). 返回 'buy'/'sell'/'hold'.
    """
    from app.services.candle_patterns import macd_histogram_series as _mh, detect_candle_pattern, compute_atr
    p = params or {}
    lb = p.get('lookback', 40); vm = p.get('vol_mult', 1.5)
    tol = p.get('retest_tol', 0.004); brk = p.get('break_window', 10)
    require_pattern = p.get('require_pattern', True)   # 是否必须回踩处顶/底形态确认
    if df is None or len(df) < lb + 5:
        return 'hold'
    rows = df.to_dict('records')[-lb:]
    h = [float(r['high']) for r in rows]; l = [float(r['low']) for r in rows]
    c = [float(r['close']) for r in rows]; v = [float(r['volume']) for r in rows]
    avg_vol = sum(v[:-brk]) / len(v[:-brk]) if len(v) > brk else sum(v) / len(v)
    mh = _mh([{'close': x} for x in c])
    hist = next((x for x in reversed(mh) if x is not None), 0.0)
    atr = compute_atr(rows); atr_now = atr[-1] if atr else None
    pat = detect_candle_pattern(rows, atr=atr_now)   # 回踩段最后几根的形态

    # === 做多: 放量突破前高 → 回踩不破 → 底部形态确认 + MACD动能向上 ===
    ph = max(h[:-brk]) if len(h) > brk else max(h)
    if any(c[i] > ph and v[i] > vm * avg_vol for i in range(lb - brk, lb)):
        after_low = min(l[-brk:])
        held = after_low <= ph * (1 + tol) and l[-1] >= ph * (1 - tol) and c[-1] > ph
        # 形态: 要么回踩处出现底部模型(bullish), 要么至少无顶部反向模型 (require_pattern 控严格度)
        form_ok = (pat['direction'] == 'bullish') if require_pattern else (pat['direction'] != 'bearish')
        if held and hist > 0 and form_ok:
            return 'buy'

    # === 做空: 放量跌破前低 → 反弹不破 → 顶部形态确认 + MACD动能向下 ===
    pl = min(l[:-brk]) if len(l) > brk else min(l)
    if any(c[i] < pl and v[i] > vm * avg_vol for i in range(lb - brk, lb)):
        after_high = max(h[-brk:])
        held = after_high >= pl * (1 - tol) and h[-1] <= pl * (1 + tol) and c[-1] < pl
        form_ok = (pat['direction'] == 'bearish') if require_pattern else (pat['direction'] != 'bullish')
        if held and hist < 0 and form_ok:
            return 'sell'
    return 'hold'
