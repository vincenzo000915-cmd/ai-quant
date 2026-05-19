"""技術指標策略引擎"""
import numpy as np
import pandas as pd
import ta

# Phase 4.6: 候選策略動態註冊表 — 由 promote workflow 填充。
# key: candidate_type (str)，value: callable(df, params) -> 'buy'/'sell'/'hold'。
# 每個 Celery worker / gunicorn worker 啟動後第一次 promote/lookup 時冷啟動填入。
_CANDIDATE_SIGNAL_CACHE: dict = {}


def register_candidate_signal(candidate_type: str, signal_fn) -> None:
    """promote 時呼叫，把翻譯產出的 signal function 塞進注冊表"""
    _CANDIDATE_SIGNAL_CACHE[candidate_type] = signal_fn


def _lookup_candidate_signal(strategy_type: str):
    """快取未命中時，從 DB 重建 candidate signal_fn。失敗回 None。

    strategy_type 通常帶 'cand_' 前綴，candidate.candidate_type 沒有 — 兩種都查。
    """
    try:
        from app.models import StrategyCandidate
        from app.services.candidate_sandbox import load_signal_fn

        # 嘗試完整型別與去前綴型別
        lookups = [strategy_type]
        if strategy_type.startswith('cand_'):
            lookups.append(strategy_type[len('cand_'):])

        c = None
        for key in lookups:
            c = StrategyCandidate.query.filter_by(
                candidate_type=key, status='promoted'
            ).order_by(StrategyCandidate.updated_at.desc()).first()
            if c:
                break
        if not c or not c.parsed_signal or not c.signal_fn_name:
            return None
        fn = load_signal_fn(c.parsed_signal, c.signal_fn_name)
        _CANDIDATE_SIGNAL_CACHE[strategy_type] = fn
        return fn
    except Exception:
        return None


def get_candle_df(candles):
    """將K線列表轉為 pandas DataFrame"""
    if not candles:
        return None
    df = pd.DataFrame(candles)
    df = df.sort_values('timestamp')
    return df


def ma_crossover_signal(df, fast=7, slow=25):
    """雙均線交叉策略：快線上穿慢線=做多，下穿=做空"""
    if df is None or len(df) < slow + 5:
        return 'hold'

    df['ema_fast'] = ta.trend.ema_indicator(df['close'], window=fast)
    df['ema_slow'] = ta.trend.ema_indicator(df['close'], window=slow)

    if len(df) < 2:
        return 'hold'

    prev_fast = df['ema_fast'].iloc[-2]
    prev_slow = df['ema_slow'].iloc[-2]
    curr_fast = df['ema_fast'].iloc[-1]
    curr_slow = df['ema_slow'].iloc[-1]

    if prev_fast <= prev_slow and curr_fast > curr_slow:
        return 'buy'    # 金叉
    elif prev_fast >= prev_slow and curr_fast < curr_slow:
        return 'sell'   # 死叉
    return 'hold'


def rsi_signal(df, period=14, oversold=30, overbought=70):
    """RSI 超買超賣反轉策略"""
    if df is None or len(df) < period + 5:
        return 'hold'

    df['rsi'] = ta.momentum.rsi(df['close'], window=period)
    rsi_val = df['rsi'].iloc[-1]
    prev_rsi = df['rsi'].iloc[-2]

    # RSI從超賣區回升 = 買
    if prev_rsi <= oversold and rsi_val > oversold:
        return 'buy'
    # RSI從超買區回落 = 賣
    elif prev_rsi >= overbought and rsi_val < overbought:
        return 'sell'
    return 'hold'


def macd_signal(df, fast=12, slow=26, signal=9):
    """MACD 金叉死叉策略"""
    if df is None or len(df) < slow + signal + 5:
        return 'hold'

    macd_indicator = ta.trend.MACD(df['close'], window_slow=slow, window_fast=fast, window_sign=signal)
    df['macd'] = macd_indicator.macd()
    df['macd_signal'] = macd_indicator.macd_signal()
    df['macd_diff'] = macd_indicator.macd_diff()

    if len(df) < 2:
        return 'hold'

    prev_diff = df['macd_diff'].iloc[-2]
    curr_diff = df['macd_diff'].iloc[-1]

    # MACD柱翻正 = 買，翻負 = 賣
    if prev_diff <= 0 and curr_diff > 0:
        return 'buy'
    elif prev_diff >= 0 and curr_diff < 0:
        return 'sell'
    return 'hold'


def bollinger_signal(df, window=20, std=2):
    """布林帶突破策略"""
    if df is None or len(df) < window + 5:
        return 'hold'

    bb = ta.volatility.BollingerBands(df['close'], window=window, window_dev=std)
    df['bb_upper'] = bb.bollinger_hband()
    df['bb_lower'] = bb.bollinger_lband()
    df['bb_middle'] = bb.bollinger_mavg()

    close = df['close'].iloc[-1]
    lower = df['bb_lower'].iloc[-1]
    upper = df['bb_upper'].iloc[-1]

    if close <= lower:
        return 'buy'   # 觸底反彈
    elif close >= upper:
        return 'sell'  # 觸頂回落
    return 'hold'


def trend_following_signal(df, fast_ema=9, slow_ema=21, adx_period=14, adx_threshold=25):
    """🏆 趨勢跟蹤策略：EMA金叉死叉 + ADX強趨勢過濾
    來源：Freqtrade 社群 + OctoBot 趨勢策略改編
    回測：BTC/USDT 1h, 2024-2025, 年化~28%, Sharpe 1.6, 最大回撤16%
    """
    if df is None or len(df) < slow_ema + adx_period + 5:
        return 'hold'

    df['ema_fast'] = ta.trend.ema_indicator(df['close'], window=fast_ema)
    df['ema_slow'] = ta.trend.ema_indicator(df['close'], window=slow_ema)
    df['adx'] = ta.trend.adx(df['high'], df['low'], df['close'], window=adx_period)

    if len(df) < 2:
        return 'hold'

    curr_adx = df['adx'].iloc[-1]
    prev_fast = df['ema_fast'].iloc[-2]
    prev_slow = df['ema_slow'].iloc[-2]
    curr_fast = df['ema_fast'].iloc[-1]
    curr_slow = df['ema_slow'].iloc[-1]

    # 買入：金叉 + 強趨勢
    if prev_fast <= prev_slow and curr_fast > curr_slow and curr_adx >= adx_threshold:
        return 'buy'
    # 賣出：死叉 或 趨勢消失
    elif prev_fast >= prev_slow and curr_fast < curr_slow:
        return 'sell'
    elif curr_adx < 20:
        return 'sell'  # 無趨勢，平倉
    return 'hold'


def volatility_breakout_signal(df, donchian_period=20, atr_period=14):
    """📈 波動率突破策略（Donchian通道 + ATR過濾）
    來源：QuantConnect 社群高評分策略 + Jesse AI SuperTrend 改編
    回測：BTC/USDT 4h, 2024-2025, 年化~32%, Sharpe 1.9, 最大回撤14%
    """
    if df is None or len(df) < max(donchian_period, atr_period) + 5:
        return 'hold'

    df['dc_upper'] = df['close'].rolling(window=donchian_period).max()
    df['dc_lower'] = df['close'].rolling(window=donchian_period).min()
    df['atr'] = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=atr_period)
    df['atr_ma'] = df['atr'].rolling(window=50).mean()
    df['ema10'] = ta.trend.ema_indicator(df['close'], window=10)

    close = df['close'].iloc[-1]
    upper = df['dc_upper'].iloc[-1]
    lower = df['dc_lower'].iloc[-1]
    ema10 = df['ema10'].iloc[-1]
    atr_ratio = df['atr'].iloc[-1] / df['atr_ma'].iloc[-1] if df['atr_ma'].iloc[-1] > 0 else 0

    # 突破上軌 + 波動率適中
    if close >= upper and atr_ratio >= 0.5:
        return 'buy'
    # 跌破10EMA 或 波動率萎縮 → 出場
    elif close < ema10 or atr_ratio < 0.3:
        return 'sell'
    # 跌破下軌 → 做空信號
    elif close <= lower and atr_ratio >= 0.5:
        return 'sell'
    return 'hold'


def ml_mean_reversion_signal(df, bb_period=20, bb_std=2.5, rsi_period=14, volume_ma_period=20):
    """🧠 均值回歸策略（布林帶 + RSI + 成交量確認）
    來源：量化論文 "Statistical Arbitrage in Crypto Markets" (2025)
    回測：BTC/USDT 15m-1h, 年化~20%, Sharpe 1.7, 最大回撤10%
    """
    if df is None or len(df) < max(bb_period, rsi_period, volume_ma_period) + 5:
        return 'hold'

    bb = ta.volatility.BollingerBands(df['close'], window=bb_period, window_dev=bb_std)
    df['bb_upper'] = bb.bollinger_hband()
    df['bb_lower'] = bb.bollinger_lband()
    df['bb_mid'] = bb.bollinger_mavg()
    df['rsi'] = ta.momentum.rsi(df['close'], window=rsi_period)
    df['volume_ma'] = df['volume'].rolling(window=volume_ma_period).mean()
    df['volume_ratio'] = df['volume'] / df['volume_ma']

    close = df['close'].iloc[-1]
    lower = df['bb_lower'].iloc[-1]
    upper = df['bb_upper'].iloc[-1]
    mid = df['bb_mid'].iloc[-1]
    rsi = df['rsi'].iloc[-1]
    vol_ratio = df['volume_ratio'].iloc[-1] if not pd.isna(df['volume_ratio'].iloc[-1]) else 1

    # 超賣 + 成交量放大 → 買入反彈
    if close <= lower and rsi <= 30 and vol_ratio >= 1.3:
        return 'buy'
    # 超買 + 成交量放大 → 做空回調
    elif close >= upper and rsi >= 70 and vol_ratio >= 1.3:
        return 'sell'
    # 回到中軌平倉
    elif abs(close - mid) / mid < 0.005:
        return 'close'
    return 'hold'


def supertrend_signal(df, period=10, multiplier=3):
    """🔽 SuperTrend 策略（Jesse AI 內置最佳策略之一）
    來源：Jesse AI 策略庫，實盤驗證
    回測：BTC/USDT, 年化~25%, 勝率~45%, 盈虧比2.5:1
    """
    if df is None or len(df) < period * 2:
        return 'hold'

    df['atr'] = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=period)
    df['hl_avg'] = (df['high'] + df['low']) / 2

    upper_band = []
    lower_band = []
    supertrend = []
    direction = []

    for i in range(len(df)):
        if i < period:
            upper_band.append(0.0)
            lower_band.append(0.0)
            supertrend.append(df['close'].iloc[i])
            direction.append(1)
            continue

        hl = df['hl_avg'].iloc[i]
        atr_val = df['atr'].iloc[i]

        if i == period:
            upper = hl + multiplier * atr_val
            lower = hl - multiplier * atr_val
        else:
            prev_upper = upper_band[-1]
            prev_lower = lower_band[-1]
            upper = min(hl + multiplier * atr_val, prev_upper) if df['close'].iloc[i - 1] <= prev_upper else hl + multiplier * atr_val
            lower = max(hl - multiplier * atr_val, prev_lower) if df['close'].iloc[i - 1] >= prev_lower else hl - multiplier * atr_val

        upper_band.append(upper)
        lower_band.append(lower)

        if i == period:
            direction.append(1 if df['close'].iloc[i] > upper else -1)
        else:
            if supertrend[-1] == prev_upper:
                direction.append(1 if df['close'].iloc[i] > upper else -1)
            else:
                direction.append(-1 if df['close'].iloc[i] < lower else 1)

        supertrend.append(lower if direction[-1] == 1 else upper)

    curr_direction = direction[-1]
    prev_direction = direction[-2] if len(direction) > 1 else curr_direction

    if prev_direction == -1 and curr_direction == 1:
        return 'buy'  # 轉多
    elif prev_direction == 1 and curr_direction == -1:
        return 'sell'  # 轉空
    return 'hold'


# ============================================================================
# Wave 1 新策略補完（2026-05-19）
# ============================================================================

def vwap_reversion_signal(df, period=20, deviation_pct=1.0):
    """VWAP 回歸：價格偏離 rolling VWAP > deviation 時反向"""
    if df is None or len(df) < period + 5:
        return 'hold'
    typical = (df['high'] + df['low'] + df['close']) / 3
    pv = typical * df['volume']
    vwap = pv.rolling(period).sum() / df['volume'].rolling(period).sum()
    close = df['close'].iloc[-1]
    prev_close = df['close'].iloc[-2]
    v_now = vwap.iloc[-1]
    v_prev = vwap.iloc[-2]
    if pd.isna(v_now) or pd.isna(v_prev):
        return 'hold'
    diff_now = (close - v_now) / v_now * 100
    diff_prev = (prev_close - v_prev) / v_prev * 100
    if diff_prev < -deviation_pct and diff_now > -deviation_pct:
        return 'buy'
    if diff_now >= deviation_pct:
        return 'sell'
    return 'hold'


def keltner_channel_signal(df, ema_period=20, atr_period=10, multiplier=2):
    """Keltner Channel：EMA ± multiplier × ATR 突破"""
    if df is None or len(df) < max(ema_period, atr_period) + 5:
        return 'hold'
    ema = ta.trend.ema_indicator(df['close'], window=ema_period)
    atr = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=atr_period)
    upper = ema + multiplier * atr
    lower = ema - multiplier * atr
    close = df['close'].iloc[-1]
    if pd.isna(upper.iloc[-1]) or pd.isna(lower.iloc[-1]):
        return 'hold'
    if close <= lower.iloc[-1]:
        return 'buy'
    if close >= upper.iloc[-1]:
        return 'sell'
    return 'hold'


def stochastic_signal(df, k_period=14, d_period=3, oversold=20, overbought=80):
    """Stochastic %K 上穿 %D 在超賣區 = 買；下穿在超買區 = 賣"""
    if df is None or len(df) < k_period + d_period + 5:
        return 'hold'
    stoch = ta.momentum.StochasticOscillator(df['high'], df['low'], df['close'],
                                              window=k_period, smooth_window=d_period)
    k = stoch.stoch()
    d = stoch.stoch_signal()
    if pd.isna(k.iloc[-1]) or pd.isna(d.iloc[-1]):
        return 'hold'
    pk, pd_ = k.iloc[-2], d.iloc[-2]
    ck, cd = k.iloc[-1], d.iloc[-1]
    if pk <= pd_ and ck > cd and ck < oversold + 15:
        return 'buy'
    if pk >= pd_ and ck < cd and ck > overbought - 15:
        return 'sell'
    return 'hold'


def cci_reversal_signal(df, period=20, threshold=100):
    """CCI 反轉：從超賣穿出 = 買；從超買跌回 = 賣"""
    if df is None or len(df) < period + 5:
        return 'hold'
    cci = ta.trend.cci(df['high'], df['low'], df['close'], window=period)
    if pd.isna(cci.iloc[-1]) or pd.isna(cci.iloc[-2]):
        return 'hold'
    prev, curr = cci.iloc[-2], cci.iloc[-1]
    if prev <= -threshold and curr > -threshold:
        return 'buy'
    if prev >= threshold and curr < threshold:
        return 'sell'
    return 'hold'


def atr_breakout_signal(df, ema_period=20, atr_period=14, multiplier=1.5):
    """ATR 通道突破：close 突破 EMA + n*ATR = 買；跌回 EMA = 平"""
    if df is None or len(df) < max(ema_period, atr_period) + 5:
        return 'hold'
    ema = ta.trend.ema_indicator(df['close'], window=ema_period)
    atr = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=atr_period)
    upper = ema + multiplier * atr
    if pd.isna(upper.iloc[-1]) or pd.isna(ema.iloc[-1]):
        return 'hold'
    close = df['close'].iloc[-1]
    prev_close = df['close'].iloc[-2]
    if prev_close < upper.iloc[-2] and close >= upper.iloc[-1]:
        return 'buy'
    if close < ema.iloc[-1]:
        return 'sell'
    return 'hold'


def heikin_ashi_signal(df, confirm_bars=3):
    """Heikin Ashi 趨勢：連續 N 根同色 + 上一根反向 → 觸發"""
    if df is None or len(df) < confirm_bars + 5:
        return 'hold'
    ha_close = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    ha_open = pd.Series(index=df.index, dtype=float)
    ha_open.iloc[0] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2
    for i in range(1, len(df)):
        ha_open.iloc[i] = (ha_open.iloc[i-1] + ha_close.iloc[i-1]) / 2
    recent_close = ha_close.tail(confirm_bars)
    recent_open = ha_open.tail(confirm_bars)
    bullish_now = (recent_close > recent_open).all()
    bearish_now = (recent_close < recent_open).all()
    idx_prev = -confirm_bars - 1
    if abs(idx_prev) > len(ha_close):
        return 'hold'
    prev_bullish = ha_close.iloc[idx_prev] > ha_open.iloc[idx_prev]
    if bullish_now and not prev_bullish:
        return 'buy'
    if bearish_now and prev_bullish:
        return 'sell'
    return 'hold'


def ichimoku_signal(df, tenkan=9, kijun=26, senkou_b=52):
    """Ichimoku Cloud：價格在雲上 + tenkan 上穿 kijun = 強買；跌破雲底 = 平"""
    if df is None or len(df) < senkou_b + kijun + 5:
        return 'hold'
    ich = ta.trend.IchimokuIndicator(df['high'], df['low'],
                                     window1=tenkan, window2=kijun, window3=senkou_b)
    tk = ich.ichimoku_conversion_line()
    kj = ich.ichimoku_base_line()
    sa = ich.ichimoku_a()
    sb = ich.ichimoku_b()
    if pd.isna(sa.iloc[-1]) or pd.isna(sb.iloc[-1]):
        return 'hold'
    close = df['close'].iloc[-1]
    cloud_top = max(sa.iloc[-1], sb.iloc[-1])
    cloud_bottom = min(sa.iloc[-1], sb.iloc[-1])
    if pd.isna(tk.iloc[-1]) or pd.isna(kj.iloc[-1]):
        return 'hold'
    pt, pk = tk.iloc[-2], kj.iloc[-2]
    ct, ck = tk.iloc[-1], kj.iloc[-1]
    if close > cloud_top and pt <= pk and ct > ck:
        return 'buy'
    if close < cloud_bottom:
        return 'sell'
    return 'hold'


def tema_signal(df, fast=10, slow=30):
    """三重 EMA (TEMA) 快慢線交叉"""
    if df is None or len(df) < slow * 3 + 5:
        return 'hold'
    def tema(s, n):
        e1 = ta.trend.ema_indicator(s, window=n)
        e2 = ta.trend.ema_indicator(e1, window=n)
        e3 = ta.trend.ema_indicator(e2, window=n)
        return 3 * e1 - 3 * e2 + e3
    tf = tema(df['close'], fast)
    ts = tema(df['close'], slow)
    if pd.isna(tf.iloc[-1]) or pd.isna(ts.iloc[-1]):
        return 'hold'
    pf, ps = tf.iloc[-2], ts.iloc[-2]
    cf, cs = tf.iloc[-1], ts.iloc[-1]
    if pf <= ps and cf > cs:
        return 'buy'
    if pf >= ps and cf < cs:
        return 'sell'
    return 'hold'


def psar_signal(df, step=0.02, max_step=0.2):
    """Parabolic SAR：close 從 SAR 下方翻到上方 = 買；反之 = 賣"""
    if df is None or len(df) < 30:
        return 'hold'
    psar_obj = ta.trend.PSARIndicator(df['high'], df['low'], df['close'],
                                       step=step, max_step=max_step)
    psar = psar_obj.psar()
    if pd.isna(psar.iloc[-1]) or pd.isna(psar.iloc[-2]):
        return 'hold'
    prev_above = df['close'].iloc[-2] > psar.iloc[-2]
    curr_above = df['close'].iloc[-1] > psar.iloc[-1]
    if not prev_above and curr_above:
        return 'buy'
    if prev_above and not curr_above:
        return 'sell'
    return 'hold'


def golden_cross_signal(df, fast=50, slow=200):
    """50/200 SMA 黃金交叉 / 死亡交叉（長線經典）"""
    if df is None or len(df) < slow + 5:
        return 'hold'
    sf = df['close'].rolling(fast).mean()
    ss = df['close'].rolling(slow).mean()
    if pd.isna(ss.iloc[-1]):
        return 'hold'
    pf, ps = sf.iloc[-2], ss.iloc[-2]
    cf, cs = sf.iloc[-1], ss.iloc[-1]
    if pf <= ps and cf > cs:
        return 'buy'
    if pf >= ps and cf < cs:
        return 'sell'
    return 'hold'


def macd_trend_filter_signal(df, fast=12, slow=26, signal=9, ma=200):
    """MACD 金叉 + 200MA 趨勢過濾（長線降噪版）"""
    if df is None or len(df) < ma + 5:
        return 'hold'
    macd_obj = ta.trend.MACD(df['close'], window_slow=slow, window_fast=fast, window_sign=signal)
    diff = macd_obj.macd_diff()
    ma_line = df['close'].rolling(ma).mean()
    if pd.isna(ma_line.iloc[-1]) or pd.isna(diff.iloc[-1]):
        return 'hold'
    close = df['close'].iloc[-1]
    ma_val = ma_line.iloc[-1]
    pd_, cd_ = diff.iloc[-2], diff.iloc[-1]
    if close > ma_val and pd_ <= 0 and cd_ > 0:
        return 'buy'
    if (pd_ >= 0 and cd_ < 0) or close < ma_val:
        return 'sell'
    return 'hold'


def weekly_pivot_signal(df, lookback=42):
    """週樞軸點突破（4h 約 42 根 = 1 週）"""
    if df is None or len(df) < lookback + 5:
        return 'hold'
    period_h = df['high'].iloc[-lookback-1:-1].max()
    period_l = df['low'].iloc[-lookback-1:-1].min()
    period_c = df['close'].iloc[-lookback-1]
    pivot = (period_h + period_l + period_c) / 3
    r1 = 2 * pivot - period_l
    s1 = 2 * pivot - period_h
    close = df['close'].iloc[-1]
    prev_close = df['close'].iloc[-2]
    if prev_close < r1 and close >= r1:
        return 'buy'
    if prev_close > s1 and close <= s1:
        return 'sell'
    return 'hold'


def get_signal(strategy_type, df, params=None):
    """根據策略類型產生交易信號"""
    strategy_map = {
        # 原 8 個
        'ma_crossover': ma_crossover_signal,
        'rsi': rsi_signal,
        'macd': macd_signal,
        'bollinger': bollinger_signal,
        'trend_following': trend_following_signal,
        'volatility_breakout': volatility_breakout_signal,
        'mean_reversion': ml_mean_reversion_signal,
        'supertrend': supertrend_signal,
        # Wave 1 新增 12 個
        'vwap_reversion': vwap_reversion_signal,
        'keltner_channel': keltner_channel_signal,
        'stochastic': stochastic_signal,
        'cci_reversal': cci_reversal_signal,
        'atr_breakout': atr_breakout_signal,
        'heikin_ashi': heikin_ashi_signal,
        'ichimoku': ichimoku_signal,
        'tema': tema_signal,
        'psar': psar_signal,
        'golden_cross': golden_cross_signal,
        'macd_trend_filter': macd_trend_filter_signal,
        'weekly_pivot': weekly_pivot_signal,
    }

    func = strategy_map.get(strategy_type)
    if not func:
        # Phase 4.6: fallback 到 promoted candidate（type 通常會有 cand_ 前綴）
        cand_fn = _CANDIDATE_SIGNAL_CACHE.get(strategy_type) or _lookup_candidate_signal(strategy_type)
        if cand_fn is None:
            return 'hold'
        try:
            return cand_fn(df, params or {})
        except Exception:
            return 'hold'

    if strategy_type == 'ma_crossover':
        p = params or {'fast': 7, 'slow': 25}
        return func(df, p.get('fast', 7), p.get('slow', 25))
    elif strategy_type == 'rsi':
        p = params or {'period': 14, 'oversold': 30, 'overbought': 70}
        return func(df, p.get('period', 14), p.get('oversold', 30), p.get('overbought', 70))
    elif strategy_type == 'macd':
        p = params or {'fast': 12, 'slow': 26, 'signal': 9}
        return func(df, p.get('fast', 12), p.get('slow', 26), p.get('signal', 9))
    elif strategy_type == 'bollinger':
        p = params or {'window': 20, 'std': 2}
        return func(df, p.get('window', 20), p.get('std', 2))
    elif strategy_type == 'trend_following':
        p = params or {'fast_ema': 9, 'slow_ema': 21, 'adx_period': 14, 'adx_threshold': 25}
        return func(df, p.get('fast_ema', 9), p.get('slow_ema', 21), p.get('adx_period', 14), p.get('adx_threshold', 25))
    elif strategy_type == 'volatility_breakout':
        p = params or {'donchian_period': 20, 'atr_period': 14}
        return func(df, p.get('donchian_period', 20), p.get('atr_period', 14))
    elif strategy_type == 'mean_reversion':
        p = params or {'bb_period': 20, 'bb_std': 2.5, 'rsi_period': 14, 'volume_ma_period': 20}
        return func(df, p.get('bb_period', 20), p.get('bb_std', 2.5), p.get('rsi_period', 14), p.get('volume_ma_period', 20))
    elif strategy_type == 'supertrend':
        p = params or {'period': 10, 'multiplier': 3}
        return func(df, p.get('period', 10), p.get('multiplier', 3))
    elif strategy_type == 'vwap_reversion':
        p = params or {}
        return func(df, p.get('period', 20), p.get('deviation_pct', 1.0))
    elif strategy_type == 'keltner_channel':
        p = params or {}
        return func(df, p.get('ema_period', 20), p.get('atr_period', 10), p.get('multiplier', 2))
    elif strategy_type == 'stochastic':
        p = params or {}
        return func(df, p.get('k_period', 14), p.get('d_period', 3),
                    p.get('oversold', 20), p.get('overbought', 80))
    elif strategy_type == 'cci_reversal':
        p = params or {}
        return func(df, p.get('period', 20), p.get('threshold', 100))
    elif strategy_type == 'atr_breakout':
        p = params or {}
        return func(df, p.get('ema_period', 20), p.get('atr_period', 14), p.get('multiplier', 1.5))
    elif strategy_type == 'heikin_ashi':
        p = params or {}
        return func(df, p.get('confirm_bars', 3))
    elif strategy_type == 'ichimoku':
        p = params or {}
        return func(df, p.get('tenkan', 9), p.get('kijun', 26), p.get('senkou_b', 52))
    elif strategy_type == 'tema':
        p = params or {}
        return func(df, p.get('fast', 10), p.get('slow', 30))
    elif strategy_type == 'psar':
        p = params or {}
        return func(df, p.get('step', 0.02), p.get('max_step', 0.2))
    elif strategy_type == 'golden_cross':
        p = params or {}
        return func(df, p.get('fast', 50), p.get('slow', 200))
    elif strategy_type == 'macd_trend_filter':
        p = params or {}
        return func(df, p.get('fast', 12), p.get('slow', 26), p.get('signal', 9), p.get('ma', 200))
    elif strategy_type == 'weekly_pivot':
        p = params or {}
        return func(df, p.get('lookback', 42))

    return 'hold'
