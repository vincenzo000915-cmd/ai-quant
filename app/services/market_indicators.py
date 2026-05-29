"""Phase 15: 市场指标库 — 补齐策略画像需求的指标当前状态 (喂守门员富感知层配对)

user 点出: 画像的 indicators 字段=每个策略需要的指标; 汇总20策略 → 系统需要的指标全集;
感知层缺的(Ichimoku/SuperTrend/Stochastic/Donchian/Bollinger/CCI/VWAP/PSAR...)要补齐, 否则配对看不到
这些策略关心的指标当前状态. (信号触发由signal_fn自带, 这里是感知层配对/解读用的状态.)

算成**语义状态**(超买/超卖、价在云上/下、通道突破位)而非原始数值 — 配对/感知用状态更直接.
"""
from __future__ import annotations


def compute_market_indicators(candles: list) -> dict:
    """算画像需求指标的当前状态. 用 ta, 转语义状态. 数据不足/某指标失败则跳过该项."""
    if not candles or len(candles) < 60:
        return {}
    try:
        import pandas as pd
        import ta
    except Exception:
        return {}
    df = pd.DataFrame(candles)
    for col in ('high', 'low', 'close', 'volume'):
        df[col] = pd.to_numeric(df[col], errors='coerce')
    h, l, c, v = df['high'], df['low'], df['close'], df['volume']
    px = float(c.iloc[-1])
    out = {}

    def _try(fn):
        try:
            fn()
        except Exception:
            pass

    # Stochastic — 超买/超卖 (震荡策略)
    def _stoch():
        k = float(ta.momentum.StochasticOscillator(h, l, c).stoch().iloc[-1])
        out['stochastic'] = {'k': round(k, 1),
                             'state': 'oversold' if k < 20 else ('overbought' if k > 80 else 'mid')}
    _try(_stoch)

    # CCI — 超买/超卖
    def _cci():
        x = float(ta.trend.CCIIndicator(h, l, c).cci().iloc[-1])
        out['cci'] = {'val': round(x, 1),
                      'state': 'oversold' if x < -100 else ('overbought' if x > 100 else 'mid')}
    _try(_cci)

    # Ichimoku — 价 vs 云层 (趋势方向/强度)
    def _ich():
        ich = ta.trend.IchimokuIndicator(h, l)
        a = float(ich.ichimoku_a().iloc[-1]); b = float(ich.ichimoku_b().iloc[-1])
        top, bot = max(a, b), min(a, b)
        out['ichimoku'] = {'state': 'above_cloud' if px > top else ('below_cloud' if px < bot else 'in_cloud')}
    _try(_ich)

    # PSAR — 多/空方向
    def _psar():
        s = float(ta.trend.PSARIndicator(h, l, c).psar().iloc[-1])
        out['psar'] = {'state': 'bullish' if px > s else 'bearish'}
    _try(_psar)

    # Donchian — 通道突破位 (突破策略)
    def _dc():
        dc = ta.volatility.DonchianChannel(h, l, c, window=20)
        up = float(dc.donchian_channel_hband().iloc[-1]); lo = float(dc.donchian_channel_lband().iloc[-1])
        pos = (px - lo) / (up - lo) if up > lo else 0.5
        out['donchian'] = {'pos': round(pos, 2),
                           'state': 'upper_break' if pos > 0.95 else ('lower_break' if pos < 0.05 else 'mid')}
    _try(_dc)

    # Bollinger — 带位置 (均值回归策略)
    def _bb():
        bb = ta.volatility.BollingerBands(c, window=20)
        up = float(bb.bollinger_hband().iloc[-1]); lo = float(bb.bollinger_lband().iloc[-1])
        pos = (px - lo) / (up - lo) if up > lo else 0.5
        out['bollinger'] = {'pos': round(pos, 2),
                           'state': 'upper' if pos > 0.9 else ('lower' if pos < 0.1 else 'mid')}
    _try(_bb)

    # VWAP — 价 vs VWAP (偏离)
    def _vwap():
        vw = float(ta.volume.VolumeWeightedAveragePrice(h, l, c, v).volume_weighted_average_price().iloc[-1])
        out['vwap'] = {'state': 'above' if px > vw else 'below', 'dev_pct': round((px - vw) / vw * 100, 2)}
    _try(_vwap)

    # SuperTrend — ta 无, 简化: EMA10 方向代理 (SuperTrend/TEMA/HeikinAshi 本质=趋势方向, regime+此项覆盖)
    def _st():
        ema10 = c.ewm(span=10, adjust=False).mean().iloc[-1]
        out['trend_proxy'] = {'state': 'up' if px > ema10 else 'down'}
    _try(_st)

    return out
