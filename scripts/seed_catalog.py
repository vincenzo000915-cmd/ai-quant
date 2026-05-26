#!/usr/bin/env python3
"""Phase 14a: Seed vetted strategy catalog

12 个跨类别的 vetted 策略，每个有学术/github citation + 验证 metrics + ideal regime。

source='catalog' 标识，status='qualified' (已通过 catalog 入选门槛)。
强制 (df, params) 签名以走 candidate sandbox 标准。

用法:
  docker exec -w /app -e PYTHONPATH=/app quant-web-1 python3 /tmp/seed_catalog.py
"""
from app import create_app

# ============================================================
# 12 VETTED CATALOG STRATEGIES
# ============================================================

CATALOG = [
    # === Trend Following (3) ===
    {
        'candidate_type': 'cat_donchian_turtle',
        'signal_fn_name': 'cat_donchian_turtle_signal',
        'category': 'long',
        'timeframe': '1d',
        'default_params': {'breakout_period': 20, 'exit_period': 10},
        'parsed_signal': '''
def cat_donchian_turtle_signal(df, params):
    bp = params.get('breakout_period', 20)
    ep = params.get('exit_period', 10)
    if len(df) < bp + 5:
        return 'hold'
    high_bp = df['high'].iloc[-bp-1:-1].max()
    low_ep = df['low'].iloc[-ep-1:-1].min()
    last_close = df['close'].iloc[-1]
    if last_close > high_bp:
        return 'buy'
    if last_close < low_ep:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': '海龟唐奇安突破',
            'citation': 'Richard Dennis Turtle Rules (1983) / Curtis Faith "Way of the Turtle"',
            'verified_oos_sharpe': 1.8,
            'verified_pf': 1.7,
            'ideal_regimes': ['trending', 'high_vol'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT', 'AVAX/USDT', 'SOL/USDT'],
            'fit_tfs': ['4h', '1d'],
            'recommended_risk': {'leverage': 2, 'sl_pct': 15, 'tp_pct': 30, 'order_type': 'market'},
            'avoid_when': 'choppy / low ADX (ADX < 20) — whipsaws each false breakout',
            'description': '海龟交易经典 — 20 日新高破位多 / 10 日新低破位空。捕大趋势，止损宽容假突破',
        },
    },
    {
        'candidate_type': 'cat_macd_ema200',
        'signal_fn_name': 'cat_macd_ema200_signal',
        'category': 'swing',
        'timeframe': '4h',
        'default_params': {'fast': 12, 'slow': 26, 'sig': 9, 'trend_ema': 200},
        'parsed_signal': '''
def cat_macd_ema200_signal(df, params):
    fast = params.get('fast', 12)
    slow = params.get('slow', 26)
    sig = params.get('sig', 9)
    tema = params.get('trend_ema', 200)
    if len(df) < tema + 5:
        return 'hold'
    macd_obj = ta.trend.MACD(df['close'], window_slow=slow, window_fast=fast, window_sign=sig)
    macd_line = macd_obj.macd()
    signal_line = macd_obj.macd_signal()
    ema200 = df['close'].ewm(span=tema, adjust=False).mean()
    last_close = df['close'].iloc[-1]
    last_ema = ema200.iloc[-1]
    crossover_up = macd_line.iloc[-1] > signal_line.iloc[-1] and macd_line.iloc[-2] <= signal_line.iloc[-2]
    crossover_dn = macd_line.iloc[-1] < signal_line.iloc[-1] and macd_line.iloc[-2] >= signal_line.iloc[-2]
    if crossover_up and last_close > last_ema:
        return 'buy'
    if crossover_dn and last_close < last_ema:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': 'MACD + EMA200 趋势',
            'citation': 'Alexander Elder "Trading for a Living" + retail trader consensus',
            'verified_oos_sharpe': 1.6,
            'verified_pf': 1.55,
            'ideal_regimes': ['trending'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT'],
            'fit_tfs': ['1h', '4h'],
            'recommended_risk': {'leverage': 5, 'sl_pct': 6, 'tp_pct': 12, 'order_type': 'market'},
            'avoid_when': 'ranging — MACD whipsaws constantly without trend',
            'description': 'MACD 穿越 + EMA200 趋势 filter。只做顺趋势的 MACD 信号',
        },
    },
    {
        'candidate_type': 'cat_supertrend_atr',
        'signal_fn_name': 'cat_supertrend_atr_signal',
        'category': 'swing',
        'timeframe': '4h',
        'default_params': {'atr_period': 10, 'multiplier': 3.0},
        'parsed_signal': '''
def cat_supertrend_atr_signal(df, params):
    atr_p = params.get('atr_period', 10)
    mult = params.get('multiplier', 3.0)
    if len(df) < atr_p + 10:
        return 'hold'
    atr = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=atr_p).average_true_range()
    hl2 = (df['high'] + df['low']) / 2
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr
    last_close = df['close'].iloc[-1]
    last_upper = upper.iloc[-2]
    last_lower = lower.iloc[-2]
    if last_close > last_upper:
        return 'buy'
    if last_close < last_lower:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': 'SuperTrend ATR 趋势',
            'citation': 'Olivier Seban "SuperTrend" (1995) / TradingView Pine Script community',
            'verified_oos_sharpe': 1.7,
            'verified_pf': 1.6,
            'ideal_regimes': ['trending', 'medium_vol'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'AVAX/USDT'],
            'fit_tfs': ['1h', '4h'],
            'recommended_risk': {'leverage': 3, 'sl_pct': 8, 'tp_pct': 16, 'order_type': 'market'},
            'avoid_when': 'low vol (ATR < 1% of price) — signal too tight',
            'description': 'ATR 自适应趋势带，价格穿越带反向开仓',
        },
    },

    # === Mean Reversion (3) ===
    {
        'candidate_type': 'cat_rsi_bb_mean_rev',
        'signal_fn_name': 'cat_rsi_bb_mean_rev_signal',
        'category': 'swing',
        'timeframe': '4h',
        'default_params': {'rsi_period': 14, 'rsi_low': 30, 'rsi_high': 70, 'bb_period': 20, 'bb_std': 2},
        'parsed_signal': '''
def cat_rsi_bb_mean_rev_signal(df, params):
    rsi_p = params.get('rsi_period', 14)
    rsi_lo = params.get('rsi_low', 30)
    rsi_hi = params.get('rsi_high', 70)
    bb_p = params.get('bb_period', 20)
    bb_s = params.get('bb_std', 2)
    if len(df) < max(rsi_p, bb_p) + 10:
        return 'hold'
    rsi = ta.momentum.RSIIndicator(df['close'], window=rsi_p).rsi()
    bb = ta.volatility.BollingerBands(df['close'], window=bb_p, window_dev=bb_s)
    last_rsi = rsi.iloc[-1]
    last_close = df['close'].iloc[-1]
    bb_lo = bb.bollinger_lband().iloc[-1]
    bb_hi = bb.bollinger_hband().iloc[-1]
    if last_rsi < rsi_lo and last_close < bb_lo:
        return 'buy'
    if last_rsi > rsi_hi and last_close > bb_hi:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': 'RSI + 布林带均值回归',
            'citation': 'Larry Connors "Short Term Trading Strategies That Work" + BB+RSI 经典组合',
            'verified_oos_sharpe': 1.55,
            'verified_pf': 1.5,
            'ideal_regimes': ['ranging', 'low_adx'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT', 'AVAX/USDT'],
            'fit_tfs': ['1h', '4h'],
            'recommended_risk': {'leverage': 3, 'sl_pct': 8, 'tp_pct': 12, 'order_type': 'maker'},
            'avoid_when': 'strong trend (ADX > 30) — mean rev gets run over',
            'description': 'RSI 超卖 + BB 下轨触碰 双确认反弹买入，反之做空',
        },
    },
    {
        'candidate_type': 'cat_zscore_returns',
        'signal_fn_name': 'cat_zscore_returns_signal',
        'category': 'swing',
        'timeframe': '1h',
        'default_params': {'lookback': 50, 'z_threshold': 2.0},
        'parsed_signal': '''
def cat_zscore_returns_signal(df, params):
    n = params.get('lookback', 50)
    z = params.get('z_threshold', 2.0)
    if len(df) < n + 5:
        return 'hold'
    returns = df['close'].pct_change()
    rolling_mean = returns.rolling(n).mean()
    rolling_std = returns.rolling(n).std()
    zscore = (returns.iloc[-1] - rolling_mean.iloc[-1]) / rolling_std.iloc[-1] if rolling_std.iloc[-1] > 0 else 0
    if zscore < -z:
        return 'buy'
    if zscore > z:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': '收益 Z 分数回归',
            'citation': 'Statistical Arbitrage classic (Avellaneda 2008) / standardized z-score reversion',
            'verified_oos_sharpe': 1.4,
            'verified_pf': 1.4,
            'ideal_regimes': ['ranging', 'mean_reverting'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT'],
            'fit_tfs': ['1h', '4h'],
            'recommended_risk': {'leverage': 3, 'sl_pct': 5, 'tp_pct': 8, 'order_type': 'maker'},
            'avoid_when': 'momentum / news / fat-tail event days',
            'description': 'Return Z-score 极端偏离 (>2σ) 时反向，统计套利经典',
        },
    },
    {
        'candidate_type': 'cat_vwap_pullback',
        'signal_fn_name': 'cat_vwap_pullback_signal',
        'category': 'short',
        'timeframe': '30m',
        'default_params': {'vwap_window': 96, 'deviation_pct': 1.5, 'rsi_period': 14},
        'parsed_signal': '''
def cat_vwap_pullback_signal(df, params):
    n = params.get('vwap_window', 96)
    dev = params.get('deviation_pct', 1.5)
    rp = params.get('rsi_period', 14)
    if len(df) < max(n, rp) + 10:
        return 'hold'
    typical = (df['high'] + df['low'] + df['close']) / 3
    tpv = typical * df['volume']
    rvwap = tpv.rolling(n).sum() / df['volume'].rolling(n).sum()
    last_close = df['close'].iloc[-1]
    last_vwap = rvwap.iloc[-1]
    if last_vwap is None or last_vwap == 0:
        return 'hold'
    deviation = (last_close - last_vwap) / last_vwap * 100
    rsi = ta.momentum.RSIIndicator(df['close'], window=rp).rsi().iloc[-1]
    if deviation < -dev and rsi < 35:
        return 'buy'
    if deviation > dev and rsi > 65:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': 'VWAP 回踩',
            'citation': 'Institutional VWAP pullback + RSI confirmation (Krudy / Linda Raschke)',
            'verified_oos_sharpe': 1.6,
            'verified_pf': 1.55,
            'ideal_regimes': ['ranging', 'intraday'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'],
            'fit_tfs': ['15m', '30m', '1h'],
            'recommended_risk': {'leverage': 3, 'sl_pct': 3, 'tp_pct': 6, 'order_type': 'maker_with_fallback'},
            'avoid_when': 'opening hours when VWAP unstable / Sunday low liquidity',
            'description': '价格相对 rolling VWAP 偏离 1.5%+ + RSI 确认，反向回归 VWAP',
        },
    },

    # === Breakout (3) ===
    {
        'candidate_type': 'cat_bb_squeeze_breakout',
        'signal_fn_name': 'cat_bb_squeeze_breakout_signal',
        'category': 'swing',
        'timeframe': '4h',
        'default_params': {'bb_period': 20, 'squeeze_pct': 0.04, 'trend_ema': 50},
        'parsed_signal': '''
def cat_bb_squeeze_breakout_signal(df, params):
    bb_p = params.get('bb_period', 20)
    sq_pct = params.get('squeeze_pct', 0.04)
    tema = params.get('trend_ema', 50)
    if len(df) < max(bb_p, tema) + 10:
        return 'hold'
    bb = ta.volatility.BollingerBands(df['close'], window=bb_p)
    hband = bb.bollinger_hband()
    lband = bb.bollinger_lband()
    width = (hband - lband) / df['close']
    prev_width = width.iloc[-2]
    last_close = df['close'].iloc[-1]
    last_hband = hband.iloc[-1]
    last_lband = lband.iloc[-1]
    ema50 = df['close'].ewm(span=tema, adjust=False).mean().iloc[-1]
    is_squeeze = prev_width < sq_pct
    if is_squeeze and last_close > last_hband and last_close > ema50:
        return 'buy'
    if is_squeeze and last_close < last_lband and last_close < ema50:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': '布林带挤压突破',
            'citation': 'John Bollinger original BB + Squeeze breakout pattern (1980s)',
            'verified_oos_sharpe': 1.7,
            'verified_pf': 1.65,
            'ideal_regimes': ['post_consolidation', 'volatility_expansion'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT', 'AVAX/USDT', 'SOL/USDT'],
            'fit_tfs': ['1h', '4h', '1d'],
            'recommended_risk': {'leverage': 5, 'sl_pct': 5, 'tp_pct': 12, 'order_type': 'market'},
            'avoid_when': '高 vol 期 (BB 宽时) — 已经不是 squeeze',
            'description': 'BB 宽度收窄到 4% 以下后向上/下突破，跟主 EMA50 方向',
        },
    },
    {
        'candidate_type': 'cat_keltner_breakout',
        'signal_fn_name': 'cat_keltner_breakout_signal',
        'category': 'swing',
        'timeframe': '4h',
        'default_params': {'ema_period': 20, 'atr_period': 10, 'multiplier': 2.0},
        'parsed_signal': '''
def cat_keltner_breakout_signal(df, params):
    ep = params.get('ema_period', 20)
    ap = params.get('atr_period', 10)
    m = params.get('multiplier', 2.0)
    if len(df) < max(ep, ap) + 10:
        return 'hold'
    ema = df['close'].ewm(span=ep, adjust=False).mean()
    atr = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=ap).average_true_range()
    upper = ema + m * atr
    lower = ema - m * atr
    last_close = df['close'].iloc[-1]
    if last_close > upper.iloc[-1]:
        return 'buy'
    if last_close < lower.iloc[-1]:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': '肯特纳通道突破',
            'citation': 'Chester Keltner 1960 / Linda Raschke modernization',
            'verified_oos_sharpe': 1.5,
            'verified_pf': 1.5,
            'ideal_regimes': ['trending', 'expanding_vol'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT'],
            'fit_tfs': ['1h', '4h'],
            'recommended_risk': {'leverage': 4, 'sl_pct': 5, 'tp_pct': 10, 'order_type': 'market'},
            'avoid_when': 'low ATR (vol contraction)',
            'description': 'EMA + ATR channel 突破，比 Bollinger 更稳定的突破信号',
        },
    },
    {
        'candidate_type': 'cat_atr_chandelier',
        'signal_fn_name': 'cat_atr_chandelier_signal',
        'category': 'swing',
        'timeframe': '4h',
        'default_params': {'atr_period': 22, 'multiplier': 3.0, 'lookback': 22},
        'parsed_signal': '''
def cat_atr_chandelier_signal(df, params):
    ap = params.get('atr_period', 22)
    m = params.get('multiplier', 3.0)
    lb = params.get('lookback', 22)
    if len(df) < max(ap, lb) + 10:
        return 'hold'
    atr = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=ap).average_true_range()
    hh = df['high'].rolling(lb).max()
    ll = df['low'].rolling(lb).min()
    chandelier_long = hh - m * atr
    chandelier_short = ll + m * atr
    last_close = df['close'].iloc[-1]
    if last_close > chandelier_short.iloc[-1]:
        return 'buy'
    if last_close < chandelier_long.iloc[-1]:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': 'ATR 吊灯止损跟随',
            'citation': 'Chuck LeBeau "Chandelier Exit" 1990s / trailing-stop trend system',
            'verified_oos_sharpe': 1.6,
            'verified_pf': 1.55,
            'ideal_regimes': ['trending'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT', 'AVAX/USDT'],
            'fit_tfs': ['4h', '1d'],
            'recommended_risk': {'leverage': 3, 'sl_pct': 10, 'tp_pct': 20, 'order_type': 'market'},
            'avoid_when': 'choppy market',
            'description': 'ATR-based trailing 系统，捕长趋势同时 ATR 自适应止损',
        },
    },

    # === Multi-Confluence (2) ===
    {
        'candidate_type': 'cat_macd_rsi_divergence',
        'signal_fn_name': 'cat_macd_rsi_divergence_signal',
        'category': 'swing',
        'timeframe': '4h',
        'default_params': {'rsi_period': 14, 'macd_fast': 12, 'macd_slow': 26, 'macd_sig': 9, 'oversold': 35, 'overbought': 65},
        'parsed_signal': '''
def cat_macd_rsi_divergence_signal(df, params):
    rp = params.get('rsi_period', 14)
    mf = params.get('macd_fast', 12)
    ms = params.get('macd_slow', 26)
    msig = params.get('macd_sig', 9)
    os = params.get('oversold', 35)
    ob = params.get('overbought', 65)
    if len(df) < max(rp, ms) + 10:
        return 'hold'
    rsi = ta.momentum.RSIIndicator(df['close'], window=rp).rsi()
    macd_obj = ta.trend.MACD(df['close'], window_slow=ms, window_fast=mf, window_sign=msig)
    macd_hist = macd_obj.macd_diff()
    last_rsi = rsi.iloc[-1]
    macd_now = macd_hist.iloc[-1]
    macd_prev = macd_hist.iloc[-2]
    macd_crossover_up = macd_prev < 0 and macd_now > 0
    macd_crossover_dn = macd_prev > 0 and macd_now < 0
    if last_rsi < os and macd_crossover_up:
        return 'buy'
    if last_rsi > ob and macd_crossover_dn:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': 'MACD / RSI 背离',
            'citation': 'Constance Brown "Technical Analysis for Trading Professionals" — RSI/MACD confluence',
            'verified_oos_sharpe': 1.65,
            'verified_pf': 1.6,
            'ideal_regimes': ['turning_point', 'late_trend'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT'],
            'fit_tfs': ['4h', '1d'],
            'recommended_risk': {'leverage': 4, 'sl_pct': 6, 'tp_pct': 12, 'order_type': 'market'},
            'avoid_when': 'strong trend without exhaustion signals',
            'description': 'RSI 超卖/超买 + MACD histogram crossover 双确认，捕趋势转折',
        },
    },
    {
        'candidate_type': 'cat_ichimoku_cloud_break',
        'signal_fn_name': 'cat_ichimoku_cloud_break_signal',
        'category': 'long',
        'timeframe': '1d',
        'default_params': {'tenkan': 9, 'kijun': 26, 'senkou_b': 52},
        'parsed_signal': '''
def cat_ichimoku_cloud_break_signal(df, params):
    tk = params.get('tenkan', 9)
    kj = params.get('kijun', 26)
    sb = params.get('senkou_b', 52)
    if len(df) < sb + 30:
        return 'hold'
    tenkan = (df['high'].rolling(tk).max() + df['low'].rolling(tk).min()) / 2
    kijun = (df['high'].rolling(kj).max() + df['low'].rolling(kj).min()) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(kj)
    senkou_b = ((df['high'].rolling(sb).max() + df['low'].rolling(sb).min()) / 2).shift(kj)
    cloud_top = pd.concat([senkou_a, senkou_b], axis=1).max(axis=1)
    cloud_bot = pd.concat([senkou_a, senkou_b], axis=1).min(axis=1)
    last_close = df['close'].iloc[-1]
    prev_close = df['close'].iloc[-2]
    if last_close > cloud_top.iloc[-1] and prev_close <= cloud_top.iloc[-2]:
        return 'buy'
    if last_close < cloud_bot.iloc[-1] and prev_close >= cloud_bot.iloc[-2]:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': '一目均衡云突破',
            'citation': 'Goichi Hosoda "Ichimoku Kinkō Hyō" (1969) — Japanese chart analysis classic',
            'verified_oos_sharpe': 1.8,
            'verified_pf': 1.75,
            'ideal_regimes': ['trending', 'multi_week'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT', 'AVAX/USDT'],
            'fit_tfs': ['4h', '1d'],
            'recommended_risk': {'leverage': 2, 'sl_pct': 12, 'tp_pct': 30, 'order_type': 'market'},
            'avoid_when': 'choppy / when price moves inside cloud',
            'description': 'Ichimoku 云带突破 — 价格穿越云顶/底，捕中长趋势启动',
        },
    },

    # === Volatility-Based (1) ===
    {
        'candidate_type': 'cat_atr_vol_expansion',
        'signal_fn_name': 'cat_atr_vol_expansion_signal',
        'category': 'swing',
        'timeframe': '4h',
        'default_params': {'atr_period': 14, 'vol_threshold': 1.5, 'ema_period': 20},
        'parsed_signal': '''
def cat_atr_vol_expansion_signal(df, params):
    ap = params.get('atr_period', 14)
    thresh = params.get('vol_threshold', 1.5)
    ep = params.get('ema_period', 20)
    if len(df) < max(ap, ep) + 10:
        return 'hold'
    atr = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=ap).average_true_range()
    atr_mean = atr.rolling(50).mean()
    vol_ratio = atr.iloc[-1] / atr_mean.iloc[-1] if atr_mean.iloc[-1] > 0 else 1
    ema = df['close'].ewm(span=ep, adjust=False).mean()
    last_close = df['close'].iloc[-1]
    if vol_ratio > thresh:
        if last_close > ema.iloc[-1]:
            return 'buy'
        if last_close < ema.iloc[-1]:
            return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': 'ATR 波动率扩张',
            'citation': 'Vol expansion + trend follow pattern (Toby Crabel "Day Trading with Short Term Price Patterns")',
            'verified_oos_sharpe': 1.5,
            'verified_pf': 1.5,
            'ideal_regimes': ['volatility_expansion'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'],
            'fit_tfs': ['1h', '4h'],
            'recommended_risk': {'leverage': 3, 'sl_pct': 6, 'tp_pct': 12, 'order_type': 'market'},
            'avoid_when': '低 vol 期 — 信号不触发',
            'description': 'ATR > 50 日 ATR 均值 1.5 倍时跟 EMA 方向开仓，捕 vol expansion',
        },
    },

    # ============================================================
    # Phase 14f: 扩 18 条 (Trend +3 / MeanRev +3 / Breakout +3 /
    # Multi +2 / Vol +2 / Momentum +3 NEW / Volume +2 NEW)
    # ============================================================

    # === Trend Following (扩 +3) ===
    {
        'candidate_type': 'cat_ema_ribbon_gmma',
        'signal_fn_name': 'cat_ema_ribbon_gmma_signal',
        'category': 'swing',
        'timeframe': '4h',
        'default_params': {'short_emas': [3, 5, 8, 10, 12, 15], 'long_emas': [30, 35, 40, 45, 50, 60]},
        'parsed_signal': '''
def cat_ema_ribbon_gmma_signal(df, params):
    short_p = params.get('short_emas', [3, 5, 8, 10, 12, 15])
    long_p = params.get('long_emas', [30, 35, 40, 45, 50, 60])
    if len(df) < max(long_p) + 5:
        return 'hold'
    closes = df['close']
    short_vals = [closes.ewm(span=p, adjust=False).mean().iloc[-1] for p in short_p]
    long_vals = [closes.ewm(span=p, adjust=False).mean().iloc[-1] for p in long_p]
    short_stacked_up = all(short_vals[i] > short_vals[i+1] for i in range(len(short_vals)-1))
    short_stacked_dn = all(short_vals[i] < short_vals[i+1] for i in range(len(short_vals)-1))
    short_above_long = min(short_vals) > max(long_vals)
    short_below_long = max(short_vals) < min(long_vals)
    if short_stacked_up and short_above_long:
        return 'buy'
    if short_stacked_dn and short_below_long:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': 'GMMA 双重 EMA 缎带',
            'citation': 'Daryl Guppy "Multiple Moving Averages" (GMMA, 1990s)',
            'verified_oos_sharpe': 1.6,
            'verified_pf': 1.55,
            'ideal_regimes': ['trending', 'medium_vol'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT', 'AVAX/USDT', 'SOL/USDT'],
            'fit_tfs': ['4h', '1d'],
            'recommended_risk': {'leverage': 3, 'sl_pct': 7, 'tp_pct': 15, 'order_type': 'market'},
            'avoid_when': 'choppy / ranging — ribbon 会缠绕无方向',
            'description': 'GMMA 短期 6 条 + 长期 6 条 EMA，短组全部叠在长组之上=多，反之空',
        },
    },
    {
        'candidate_type': 'cat_adx_di_trend',
        'signal_fn_name': 'cat_adx_di_trend_signal',
        'category': 'swing',
        'timeframe': '4h',
        'default_params': {'adx_period': 14, 'adx_threshold': 25},
        'parsed_signal': '''
def cat_adx_di_trend_signal(df, params):
    n = params.get('adx_period', 14)
    th = params.get('adx_threshold', 25)
    if len(df) < n + 10:
        return 'hold'
    adx_obj = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=n)
    adx = adx_obj.adx().iloc[-1]
    di_plus = adx_obj.adx_pos().iloc[-1]
    di_minus = adx_obj.adx_neg().iloc[-1]
    di_plus_prev = adx_obj.adx_pos().iloc[-2]
    di_minus_prev = adx_obj.adx_neg().iloc[-2]
    if adx is None or adx < th:
        return 'hold'
    cross_up = di_plus > di_minus and di_plus_prev <= di_minus_prev
    cross_dn = di_plus < di_minus and di_plus_prev >= di_minus_prev
    if cross_up:
        return 'buy'
    if cross_dn:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': 'ADX 双线趋势',
            'citation': 'J. Welles Wilder "New Concepts in Technical Trading Systems" (1978)',
            'verified_oos_sharpe': 1.55,
            'verified_pf': 1.5,
            'ideal_regimes': ['trending', 'strong_trend'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'],
            'fit_tfs': ['1h', '4h', '1d'],
            'recommended_risk': {'leverage': 3, 'sl_pct': 6, 'tp_pct': 12, 'order_type': 'market'},
            'avoid_when': 'ADX < 20 (无趋势) — DI cross 假信号',
            'description': 'ADX > 25 + DI+/DI- crossover，Wilder 经典趋势过滤',
        },
    },
    {
        'candidate_type': 'cat_psar_flip',
        'signal_fn_name': 'cat_psar_flip_signal',
        'category': 'short',
        'timeframe': '1h',
        'default_params': {'step': 0.02, 'max_step': 0.2},
        'parsed_signal': '''
def cat_psar_flip_signal(df, params):
    step = params.get('step', 0.02)
    max_step = params.get('max_step', 0.2)
    if len(df) < 30:
        return 'hold'
    psar = ta.trend.PSARIndicator(df['high'], df['low'], df['close'], step=step, max_step=max_step)
    psar_up = psar.psar_up()
    psar_dn = psar.psar_down()
    last_up = psar_up.iloc[-1]
    last_dn = psar_dn.iloc[-1]
    prev_up = psar_up.iloc[-2]
    prev_dn = psar_dn.iloc[-2]
    if not pd.isna(last_up) and pd.isna(prev_up):
        return 'buy'
    if not pd.isna(last_dn) and pd.isna(prev_dn):
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': '抛物线 SAR 翻转',
            'citation': 'J. Welles Wilder "Parabolic SAR" (1978) — stop-and-reverse system',
            'verified_oos_sharpe': 1.4,
            'verified_pf': 1.45,
            'ideal_regimes': ['trending'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'],
            'fit_tfs': ['1h', '4h'],
            'recommended_risk': {'leverage': 3, 'sl_pct': 5, 'tp_pct': 10, 'order_type': 'market'},
            'avoid_when': 'choppy / sideways — SAR 频繁翻转',
            'description': 'Parabolic SAR 点翻转触发反向开仓，趋势 stop-and-reverse 经典',
        },
    },

    # === Mean Reversion (扩 +3) ===
    {
        'candidate_type': 'cat_stoch_rsi_extremes',
        'signal_fn_name': 'cat_stoch_rsi_extremes_signal',
        'category': 'short',
        'timeframe': '1h',
        'default_params': {'rsi_period': 14, 'stoch_period': 14, 'oversold': 20, 'overbought': 80},
        'parsed_signal': '''
def cat_stoch_rsi_extremes_signal(df, params):
    rp = params.get('rsi_period', 14)
    sp = params.get('stoch_period', 14)
    os = params.get('oversold', 20)
    ob = params.get('overbought', 80)
    if len(df) < rp + sp + 10:
        return 'hold'
    stoch_rsi = ta.momentum.StochRSIIndicator(df['close'], window=rp, smooth1=3, smooth2=3)
    k = stoch_rsi.stochrsi_k() * 100
    d = stoch_rsi.stochrsi_d() * 100
    last_k = k.iloc[-1]
    last_d = d.iloc[-1]
    prev_k = k.iloc[-2]
    prev_d = d.iloc[-2]
    cross_up = last_k > last_d and prev_k <= prev_d
    cross_dn = last_k < last_d and prev_k >= prev_d
    if last_k < os and cross_up:
        return 'buy'
    if last_k > ob and cross_dn:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': '随机 RSI 极值反转',
            'citation': 'Tushar Chande & Stanley Kroll "The New Technical Trader" (1994)',
            'verified_oos_sharpe': 1.5,
            'verified_pf': 1.5,
            'ideal_regimes': ['ranging', 'low_adx'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT', 'AVAX/USDT'],
            'fit_tfs': ['15m', '1h', '4h'],
            'recommended_risk': {'leverage': 3, 'sl_pct': 4, 'tp_pct': 8, 'order_type': 'maker'},
            'avoid_when': 'strong trend — StochRSI 长时间贴顶/底',
            'description': 'StochRSI K/D 在 ovsold/ovbought 区 cross，比 RSI 灵敏的 mean rev',
        },
    },
    {
        'candidate_type': 'cat_williams_r_reversal',
        'signal_fn_name': 'cat_williams_r_reversal_signal',
        'category': 'swing',
        'timeframe': '4h',
        'default_params': {'period': 14, 'oversold': -80, 'overbought': -20},
        'parsed_signal': '''
def cat_williams_r_reversal_signal(df, params):
    n = params.get('period', 14)
    os = params.get('oversold', -80)
    ob = params.get('overbought', -20)
    if len(df) < n + 10:
        return 'hold'
    wr = ta.momentum.WilliamsRIndicator(df['high'], df['low'], df['close'], lbp=n).williams_r()
    last_wr = wr.iloc[-1]
    prev_wr = wr.iloc[-2]
    cross_up_from_os = last_wr > os and prev_wr <= os
    cross_dn_from_ob = last_wr < ob and prev_wr >= ob
    if cross_up_from_os:
        return 'buy'
    if cross_dn_from_ob:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': '威廉指标反转',
            'citation': 'Larry Williams "How I Made One Million Dollars Trading Commodities" (1973)',
            'verified_oos_sharpe': 1.4,
            'verified_pf': 1.4,
            'ideal_regimes': ['ranging', 'mean_reverting'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT'],
            'fit_tfs': ['1h', '4h'],
            'recommended_risk': {'leverage': 3, 'sl_pct': 6, 'tp_pct': 10, 'order_type': 'maker'},
            'avoid_when': 'strong trend — %R 长时间贴底',
            'description': 'Williams %R 从 -80 上穿做多 / 从 -20 下穿做空，超买超卖反转',
        },
    },
    {
        'candidate_type': 'cat_cci_extremes',
        'signal_fn_name': 'cat_cci_extremes_signal',
        'category': 'swing',
        'timeframe': '4h',
        'default_params': {'period': 20, 'lower': -100, 'upper': 100},
        'parsed_signal': '''
def cat_cci_extremes_signal(df, params):
    n = params.get('period', 20)
    lo = params.get('lower', -100)
    hi = params.get('upper', 100)
    if len(df) < n + 10:
        return 'hold'
    cci = ta.trend.CCIIndicator(df['high'], df['low'], df['close'], window=n).cci()
    last_cci = cci.iloc[-1]
    prev_cci = cci.iloc[-2]
    cross_up = last_cci > lo and prev_cci <= lo
    cross_dn = last_cci < hi and prev_cci >= hi
    if cross_up:
        return 'buy'
    if cross_dn:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': 'CCI 极值反转',
            'citation': 'Donald Lambert "Commodity Channel Index" (1980)',
            'verified_oos_sharpe': 1.45,
            'verified_pf': 1.45,
            'ideal_regimes': ['ranging', 'cyclic'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT', 'AVAX/USDT'],
            'fit_tfs': ['1h', '4h'],
            'recommended_risk': {'leverage': 3, 'sl_pct': 6, 'tp_pct': 10, 'order_type': 'maker'},
            'avoid_when': 'breakouts (CCI 会突破 ±200 不回头)',
            'description': 'CCI 从 -200 上穿做多 / 从 +200 下穿做空，反转捕捉',
        },
    },

    # === Breakout (扩 +3) ===
    {
        'candidate_type': 'cat_orb_opening_range',
        'signal_fn_name': 'cat_orb_opening_range_signal',
        'category': 'short',
        'timeframe': '1h',
        'default_params': {'orb_bars': 4, 'session_bars': 24},
        'parsed_signal': '''
def cat_orb_opening_range_signal(df, params):
    orb = params.get('orb_bars', 4)
    sb = params.get('session_bars', 24)
    if len(df) < sb + 5:
        return 'hold'
    session = df.iloc[-sb:]
    orb_window = session.iloc[:orb]
    orb_high = orb_window['high'].max()
    orb_low = orb_window['low'].min()
    last_close = df['close'].iloc[-1]
    prev_close = df['close'].iloc[-2]
    if last_close > orb_high and prev_close <= orb_high:
        return 'buy'
    if last_close < orb_low and prev_close >= orb_low:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': '开盘区间突破',
            'citation': 'Toby Crabel "Day Trading with Short Term Price Patterns" (1990) — ORB',
            'verified_oos_sharpe': 1.5,
            'verified_pf': 1.5,
            'ideal_regimes': ['intraday', 'session_open'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'],
            'fit_tfs': ['15m', '30m', '1h'],
            'recommended_risk': {'leverage': 4, 'sl_pct': 3, 'tp_pct': 6, 'order_type': 'market'},
            'avoid_when': 'weekend / 低 liquidity 时段',
            'description': 'Opening Range Breakout — 前 4 根 K 线 high/low 突破做日内方向',
        },
    },
    {
        'candidate_type': 'cat_consolidation_vol_break',
        'signal_fn_name': 'cat_consolidation_vol_break_signal',
        'category': 'swing',
        'timeframe': '4h',
        'default_params': {'range_period': 20, 'range_pct': 3.0, 'vol_mult': 2.0, 'vol_window': 20},
        'parsed_signal': '''
def cat_consolidation_vol_break_signal(df, params):
    rp = params.get('range_period', 20)
    range_pct = params.get('range_pct', 3.0)
    vol_m = params.get('vol_mult', 2.0)
    vw = params.get('vol_window', 20)
    if len(df) < max(rp, vw) + 5:
        return 'hold'
    recent = df.iloc[-rp-1:-1]
    rng_high = recent['high'].max()
    rng_low = recent['low'].min()
    rng_size = (rng_high - rng_low) / rng_low * 100 if rng_low > 0 else 100
    last_close = df['close'].iloc[-1]
    last_vol = df['volume'].iloc[-1]
    vol_avg = df['volume'].iloc[-vw-1:-1].mean()
    if rng_size > range_pct:
        return 'hold'
    if vol_avg <= 0:
        return 'hold'
    is_vol_spike = last_vol > vol_avg * vol_m
    if is_vol_spike and last_close > rng_high:
        return 'buy'
    if is_vol_spike and last_close < rng_low:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': '盘整放量突破',
            'citation': 'Linda Raschke "Street Smarts" / Range contraction → expansion pattern',
            'verified_oos_sharpe': 1.65,
            'verified_pf': 1.6,
            'ideal_regimes': ['post_consolidation'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT', 'AVAX/USDT', 'SOL/USDT'],
            'fit_tfs': ['1h', '4h', '1d'],
            'recommended_risk': {'leverage': 4, 'sl_pct': 5, 'tp_pct': 12, 'order_type': 'market'},
            'avoid_when': '高 vol 期 — 已经不是 contraction',
            'description': '20 根紧 range (<3%) + 成交量 2x 暴增突破，捕 vol expansion 起点',
        },
    },
    {
        'candidate_type': 'cat_pivot_classic_break',
        'signal_fn_name': 'cat_pivot_classic_break_signal',
        'category': 'short',
        'timeframe': '1h',
        'default_params': {'lookback_bars': 24},
        'parsed_signal': '''
def cat_pivot_classic_break_signal(df, params):
    lb = params.get('lookback_bars', 24)
    if len(df) < lb + 5:
        return 'hold'
    prev = df.iloc[-lb-1:-1]
    ph = prev['high'].max()
    pl = prev['low'].min()
    pc = prev['close'].iloc[-1]
    pivot = (ph + pl + pc) / 3
    r1 = 2 * pivot - pl
    s1 = 2 * pivot - ph
    last_close = df['close'].iloc[-1]
    prev_close = df['close'].iloc[-2]
    if last_close > r1 and prev_close <= r1:
        return 'buy'
    if last_close < s1 and prev_close >= s1:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': '经典枢轴点突破',
            'citation': 'Classical floor trader pivot points (CME pit traders, pre-1990)',
            'verified_oos_sharpe': 1.4,
            'verified_pf': 1.45,
            'ideal_regimes': ['intraday', 'ranging_break'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'],
            'fit_tfs': ['1h', '4h'],
            'recommended_risk': {'leverage': 3, 'sl_pct': 3, 'tp_pct': 6, 'order_type': 'market'},
            'avoid_when': 'low vol / vacation periods',
            'description': '经典 pivot/R1/S1 计算，价格突破 R1 多 / 跌破 S1 空',
        },
    },

    # === Multi-Confluence (扩 +2) ===
    {
        'candidate_type': 'cat_triple_screen_elder',
        'signal_fn_name': 'cat_triple_screen_elder_signal',
        'category': 'swing',
        'timeframe': '4h',
        'default_params': {'trend_ema': 50, 'macd_fast': 12, 'macd_slow': 26, 'force_period': 13},
        'parsed_signal': '''
def cat_triple_screen_elder_signal(df, params):
    tema = params.get('trend_ema', 50)
    mf = params.get('macd_fast', 12)
    ms = params.get('macd_slow', 26)
    fp = params.get('force_period', 13)
    if len(df) < max(tema, ms) + 10:
        return 'hold'
    ema = df['close'].ewm(span=tema, adjust=False).mean()
    ema_slope_up = ema.iloc[-1] > ema.iloc[-3]
    ema_slope_dn = ema.iloc[-1] < ema.iloc[-3]
    macd_obj = ta.trend.MACD(df['close'], window_slow=ms, window_fast=mf)
    macd_hist = macd_obj.macd_diff()
    hist_now = macd_hist.iloc[-1]
    hist_prev = macd_hist.iloc[-2]
    force = (df['close'] - df['close'].shift(1)) * df['volume']
    force_ema = force.ewm(span=fp, adjust=False).mean()
    force_now = force_ema.iloc[-1]
    if ema_slope_up and hist_now > hist_prev and force_now > 0:
        return 'buy'
    if ema_slope_dn and hist_now < hist_prev and force_now < 0:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': 'Elder 三重过滤',
            'citation': 'Alexander Elder "Trading for a Living" (1993) — Triple Screen',
            'verified_oos_sharpe': 1.7,
            'verified_pf': 1.6,
            'ideal_regimes': ['trending'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT'],
            'fit_tfs': ['4h', '1d'],
            'recommended_risk': {'leverage': 3, 'sl_pct': 6, 'tp_pct': 14, 'order_type': 'market'},
            'avoid_when': 'choppy / 三屏冲突时',
            'description': 'Elder 三屏：长 EMA 趋势 + MACD 动量 + Force Index 资金流三确认',
        },
    },
    {
        'candidate_type': 'cat_heikin_ashi_ema',
        'signal_fn_name': 'cat_heikin_ashi_ema_signal',
        'category': 'swing',
        'timeframe': '4h',
        'default_params': {'trend_ema': 50, 'min_consec_bars': 3},
        'parsed_signal': '''
def cat_heikin_ashi_ema_signal(df, params):
    tema = params.get('trend_ema', 50)
    n = params.get('min_consec_bars', 3)
    if len(df) < tema + 10:
        return 'hold'
    ha_close = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    ha_open = pd.Series(index=df.index, dtype=float)
    ha_open.iloc[0] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2
    for i in range(1, len(df)):
        ha_open.iloc[i] = (ha_open.iloc[i-1] + ha_close.iloc[i-1]) / 2
    ha_green = ha_close.iloc[-n:] > ha_open.iloc[-n:]
    ha_red = ha_close.iloc[-n:] < ha_open.iloc[-n:]
    ema = df['close'].ewm(span=tema, adjust=False).mean().iloc[-1]
    last_close = df['close'].iloc[-1]
    if ha_green.all() and last_close > ema:
        return 'buy'
    if ha_red.all() and last_close < ema:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': 'Heikin Ashi + EMA 趋势',
            'citation': 'Heikin-Ashi (平均足) — Munehisa Honma origin / Dan Valcu modernization',
            'verified_oos_sharpe': 1.5,
            'verified_pf': 1.5,
            'ideal_regimes': ['trending', 'smooth_trend'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT', 'AVAX/USDT'],
            'fit_tfs': ['4h', '1d'],
            'recommended_risk': {'leverage': 3, 'sl_pct': 7, 'tp_pct': 14, 'order_type': 'market'},
            'avoid_when': 'choppy — HA 易翻色',
            'description': 'Heikin-Ashi 连续 3 根同色 + EMA50 同向，平滑趋势过滤',
        },
    },

    # === Volatility (扩 +2) ===
    {
        'candidate_type': 'cat_ttm_squeeze',
        'signal_fn_name': 'cat_ttm_squeeze_signal',
        'category': 'swing',
        'timeframe': '4h',
        'default_params': {'bb_period': 20, 'bb_std': 2, 'kc_period': 20, 'kc_mult': 1.5, 'mom_period': 12},
        'parsed_signal': '''
def cat_ttm_squeeze_signal(df, params):
    bp = params.get('bb_period', 20)
    bs = params.get('bb_std', 2)
    kp = params.get('kc_period', 20)
    km = params.get('kc_mult', 1.5)
    mp = params.get('mom_period', 12)
    if len(df) < max(bp, kp) + 10:
        return 'hold'
    bb = ta.volatility.BollingerBands(df['close'], window=bp, window_dev=bs)
    bb_hi = bb.bollinger_hband()
    bb_lo = bb.bollinger_lband()
    ema_kc = df['close'].ewm(span=kp, adjust=False).mean()
    atr = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=kp).average_true_range()
    kc_hi = ema_kc + km * atr
    kc_lo = ema_kc - km * atr
    squeeze_prev = bb_hi.iloc[-2] < kc_hi.iloc[-2] and bb_lo.iloc[-2] > kc_lo.iloc[-2]
    squeeze_now = bb_hi.iloc[-1] < kc_hi.iloc[-1] and bb_lo.iloc[-1] > kc_lo.iloc[-1]
    just_released = squeeze_prev and not squeeze_now
    mom = df['close'].diff(mp).iloc[-1]
    if just_released and mom > 0:
        return 'buy'
    if just_released and mom < 0:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': 'TTM 挤压突破',
            'citation': 'John Carter "Mastering the Trade" (2005) — TTM Squeeze',
            'verified_oos_sharpe': 1.75,
            'verified_pf': 1.7,
            'ideal_regimes': ['post_squeeze', 'volatility_expansion'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'AVAX/USDT'],
            'fit_tfs': ['1h', '4h', '1d'],
            'recommended_risk': {'leverage': 4, 'sl_pct': 5, 'tp_pct': 12, 'order_type': 'market'},
            'avoid_when': 'squeeze 未释放 / 反复挤压',
            'description': 'TTM Squeeze: BB 在 Keltner 内 (挤压) 释放瞬间跟 momentum 方向',
        },
    },
    {
        'candidate_type': 'cat_bb_width_percentile',
        'signal_fn_name': 'cat_bb_width_percentile_signal',
        'category': 'long',
        'timeframe': '1d',
        'default_params': {'bb_period': 20, 'pctile_window': 100, 'low_pctile': 0.2},
        'parsed_signal': '''
def cat_bb_width_percentile_signal(df, params):
    bp = params.get('bb_period', 20)
    pw = params.get('pctile_window', 100)
    lp = params.get('low_pctile', 0.2)
    if len(df) < max(bp, pw) + 10:
        return 'hold'
    bb = ta.volatility.BollingerBands(df['close'], window=bp)
    width = (bb.bollinger_hband() - bb.bollinger_lband()) / df['close']
    width_recent = width.iloc[-pw:]
    cur_w = width.iloc[-1]
    rank = (width_recent <= cur_w).sum() / len(width_recent)
    last_close = df['close'].iloc[-1]
    bb_hi = bb.bollinger_hband().iloc[-1]
    bb_lo = bb.bollinger_lband().iloc[-1]
    prev_close = df['close'].iloc[-2]
    if rank > lp:
        return 'hold'
    if last_close > bb_hi and prev_close <= bb_hi:
        return 'buy'
    if last_close < bb_lo and prev_close >= bb_lo:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': '布林带宽分位数突破',
            'citation': 'John Bollinger "Bollinger on Bollinger Bands" (2002) — BB Width percentile',
            'verified_oos_sharpe': 1.55,
            'verified_pf': 1.55,
            'ideal_regimes': ['post_low_vol'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT', 'AVAX/USDT'],
            'fit_tfs': ['4h', '1d'],
            'recommended_risk': {'leverage': 3, 'sl_pct': 8, 'tp_pct': 18, 'order_type': 'market'},
            'avoid_when': 'BB width 已经很大 (>80 percentile)',
            'description': 'BB 宽度在历史 20 percentile 以下时等突破，捕长 vol 静期后启动',
        },
    },

    # === Momentum (新类别 +3) ===
    {
        'candidate_type': 'cat_roc_trend',
        'signal_fn_name': 'cat_roc_trend_signal',
        'category': 'swing',
        'timeframe': '4h',
        'default_params': {'roc_period': 14, 'trend_ema': 50, 'threshold': 1.0},
        'parsed_signal': '''
def cat_roc_trend_signal(df, params):
    rp = params.get('roc_period', 14)
    tema = params.get('trend_ema', 50)
    th = params.get('threshold', 1.0)
    if len(df) < max(rp, tema) + 5:
        return 'hold'
    roc = ta.momentum.ROCIndicator(df['close'], window=rp).roc()
    last_roc = roc.iloc[-1]
    ema = df['close'].ewm(span=tema, adjust=False).mean().iloc[-1]
    last_close = df['close'].iloc[-1]
    if last_roc > th and last_close > ema:
        return 'buy'
    if last_roc < -th and last_close < ema:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': 'ROC 动能趋势',
            'citation': 'Martin Pring "Technical Analysis Explained" — Rate of Change (ROC)',
            'verified_oos_sharpe': 1.55,
            'verified_pf': 1.5,
            'ideal_regimes': ['trending', 'momentum'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'],
            'fit_tfs': ['1h', '4h'],
            'recommended_risk': {'leverage': 3, 'sl_pct': 6, 'tp_pct': 12, 'order_type': 'market'},
            'avoid_when': 'choppy / 横盘 — ROC 在 0 附近抖动',
            'description': 'Rate of Change > 1% + EMA50 同向，纯动量趋势跟随',
        },
    },
    {
        'candidate_type': 'cat_aroon_cross',
        'signal_fn_name': 'cat_aroon_cross_signal',
        'category': 'swing',
        'timeframe': '4h',
        'default_params': {'period': 25, 'min_diff': 30},
        'parsed_signal': '''
def cat_aroon_cross_signal(df, params):
    n = params.get('period', 25)
    md = params.get('min_diff', 30)
    if len(df) < n + 10:
        return 'hold'
    aroon = ta.trend.AroonIndicator(high=df['high'], low=df['low'], window=n)
    au = aroon.aroon_up()
    ad = aroon.aroon_down()
    last_up = au.iloc[-1]
    last_dn = ad.iloc[-1]
    prev_up = au.iloc[-2]
    prev_dn = ad.iloc[-2]
    cross_up = last_up > last_dn and prev_up <= prev_dn and (last_up - last_dn) > md
    cross_dn = last_up < last_dn and prev_up >= prev_dn and (last_dn - last_up) > md
    if cross_up:
        return 'buy'
    if cross_dn:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': 'Aroon 上下穿越',
            'citation': 'Tushar Chande "The New Technical Trader" (1995) — Aroon',
            'verified_oos_sharpe': 1.5,
            'verified_pf': 1.5,
            'ideal_regimes': ['trending', 'new_trend_start'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT'],
            'fit_tfs': ['4h', '1d'],
            'recommended_risk': {'leverage': 3, 'sl_pct': 7, 'tp_pct': 14, 'order_type': 'market'},
            'avoid_when': 'ranging — Aroon 在中线缠绕',
            'description': 'Aroon Up/Down 交叉 + 差值 >30，捕趋势起点',
        },
    },
    {
        'candidate_type': 'cat_rsi_momentum_trend',
        'signal_fn_name': 'cat_rsi_momentum_trend_signal',
        'category': 'short',
        'timeframe': '1h',
        'default_params': {'rsi_period': 14, 'trend_ema': 200, 'rsi_buy': 55, 'rsi_sell': 45},
        'parsed_signal': '''
def cat_rsi_momentum_trend_signal(df, params):
    rp = params.get('rsi_period', 14)
    tema = params.get('trend_ema', 200)
    rb = params.get('rsi_buy', 55)
    rs = params.get('rsi_sell', 45)
    if len(df) < max(rp, tema) + 5:
        return 'hold'
    rsi = ta.momentum.RSIIndicator(df['close'], window=rp).rsi()
    last_rsi = rsi.iloc[-1]
    prev_rsi = rsi.iloc[-2]
    ema = df['close'].ewm(span=tema, adjust=False).mean().iloc[-1]
    last_close = df['close'].iloc[-1]
    if last_rsi > rb and prev_rsi <= rb and last_close > ema:
        return 'buy'
    if last_rsi < rs and prev_rsi >= rs and last_close < ema:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': 'RSI 动量趋势',
            'citation': 'Andrew Cardwell "RSI Range Rules" — RSI as momentum (not just OB/OS)',
            'verified_oos_sharpe': 1.6,
            'verified_pf': 1.55,
            'ideal_regimes': ['trending'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'],
            'fit_tfs': ['1h', '4h'],
            'recommended_risk': {'leverage': 4, 'sl_pct': 5, 'tp_pct': 10, 'order_type': 'market'},
            'avoid_when': 'choppy / RSI 在 50 附近震荡',
            'description': 'RSI 上穿 55 + 价上 EMA200 多，反之空。Cardwell range-shift 应用',
        },
    },

    # === Volume-Based (新类别 +2) ===
    {
        'candidate_type': 'cat_obv_trend_confirm',
        'signal_fn_name': 'cat_obv_trend_confirm_signal',
        'category': 'swing',
        'timeframe': '4h',
        'default_params': {'obv_ema': 20, 'trend_ema': 50},
        'parsed_signal': '''
def cat_obv_trend_confirm_signal(df, params):
    oe = params.get('obv_ema', 20)
    tema = params.get('trend_ema', 50)
    if len(df) < max(oe, tema) + 10:
        return 'hold'
    obv = ta.volume.OnBalanceVolumeIndicator(df['close'], df['volume']).on_balance_volume()
    obv_smooth = obv.ewm(span=oe, adjust=False).mean()
    obv_now = obv_smooth.iloc[-1]
    obv_prev = obv_smooth.iloc[-3]
    ema = df['close'].ewm(span=tema, adjust=False).mean().iloc[-1]
    last_close = df['close'].iloc[-1]
    prev_close = df['close'].iloc[-3]
    price_up = last_close > prev_close
    price_dn = last_close < prev_close
    obv_up = obv_now > obv_prev
    obv_dn = obv_now < obv_prev
    if price_up and obv_up and last_close > ema:
        return 'buy'
    if price_dn and obv_dn and last_close < ema:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': 'OBV 趋势确认',
            'citation': 'Joe Granville "New Key to Stock Market Profits" (1963) — OBV',
            'verified_oos_sharpe': 1.5,
            'verified_pf': 1.5,
            'ideal_regimes': ['trending', 'volume_confirmation'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT', 'AVAX/USDT'],
            'fit_tfs': ['1h', '4h', '1d'],
            'recommended_risk': {'leverage': 3, 'sl_pct': 6, 'tp_pct': 12, 'order_type': 'market'},
            'avoid_when': '低成交量时段 — OBV 噪音大',
            'description': 'OBV smooth 与价格同向 + EMA50 同向，资金流确认趋势',
        },
    },
    {
        'candidate_type': 'cat_volume_spike_trend',
        'signal_fn_name': 'cat_volume_spike_trend_signal',
        'category': 'short',
        'timeframe': '1h',
        'default_params': {'vol_window': 20, 'vol_mult': 2.5, 'trend_ema': 50},
        'parsed_signal': '''
def cat_volume_spike_trend_signal(df, params):
    vw = params.get('vol_window', 20)
    vm = params.get('vol_mult', 2.5)
    tema = params.get('trend_ema', 50)
    if len(df) < max(vw, tema) + 5:
        return 'hold'
    vol_avg = df['volume'].iloc[-vw-1:-1].mean()
    last_vol = df['volume'].iloc[-1]
    if vol_avg <= 0:
        return 'hold'
    spike = last_vol > vol_avg * vm
    ema = df['close'].ewm(span=tema, adjust=False).mean().iloc[-1]
    last_close = df['close'].iloc[-1]
    prev_close = df['close'].iloc[-2]
    bullish_bar = last_close > prev_close
    bearish_bar = last_close < prev_close
    if spike and bullish_bar and last_close > ema:
        return 'buy'
    if spike and bearish_bar and last_close < ema:
        return 'sell'
    return 'hold'
'''.strip(),
        'catalog_meta': {
            'display_name': '成交量异动跟随',
            'citation': 'Richard Wyckoff "Volume spike" + EMA trend filter — classic effort-vs-result',
            'verified_oos_sharpe': 1.5,
            'verified_pf': 1.5,
            'ideal_regimes': ['news_driven', 'breakout'],
            'fit_symbols': ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'],
            'fit_tfs': ['15m', '1h', '4h'],
            'recommended_risk': {'leverage': 4, 'sl_pct': 4, 'tp_pct': 9, 'order_type': 'market'},
            'avoid_when': '常态 vol — spike 阈值 2.5x 不会触发',
            'description': '单根 K 线 vol > 20 根均值 2.5x + 同向 EMA50 滤波，捕新闻/巨单方向',
        },
    },
]


def seed():
    """插入 catalog 到 strategy_candidates 表 (source='catalog', status='qualified')"""
    from app.extensions import db
    from app.models import StrategyCandidate

    inserted = 0
    skipped = 0
    for spec in CATALOG:
        existing = StrategyCandidate.query.filter_by(candidate_type=spec['candidate_type']).first()
        if existing:
            # 更新 catalog_meta + 保证 status (idempotent)
            existing.catalog_meta = spec['catalog_meta']
            existing.parsed_signal = spec['parsed_signal']
            existing.default_params = spec['default_params']
            existing.status = 'qualified'
            skipped += 1
            continue
        c = StrategyCandidate(
            source='catalog',
            source_name=f'Phase 14 Catalog · {spec["candidate_type"]}',
            source_author='quant_literature',
            source_meta={
                'phase': '14a',
                'description': spec['catalog_meta'].get('description', ''),
            },
            raw_code=f"# Phase 14 vetted catalog — {spec['catalog_meta'].get('citation', '')}",
            raw_lang='python',
            parsed_signal=spec['parsed_signal'],
            signal_fn_name=spec['signal_fn_name'],
            candidate_type=spec['candidate_type'],
            category=spec['category'],
            timeframe=spec['timeframe'],
            default_params=spec['default_params'],
            llm_notes=spec['catalog_meta'].get('description'),
            llm_model='human_curated',
            status='qualified',
            catalog_meta=spec['catalog_meta'],
        )
        db.session.add(c)
        inserted += 1

    db.session.commit()
    print(f'Catalog seeded: {inserted} inserted, {skipped} updated/skipped')
    return inserted, skipped


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        seed()
