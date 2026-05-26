"""Phase 12.40: AI improve 工具箱 — 让 LLM 当真分析师不是赌徒。

3 个核心 helper：

  pull_profitable_references(user_id, limit)
      拉「已经证明能赚钱」的策略 — running 策略+ qualified candidates，按 OOS Sharpe 排
      → 喂 LLM 当正面案例学。

  compute_symbol_stats(candles)
      算 RSI/BB/ADX/vol 实际分布 — LLM 看真实数字而非「Hurst=0.223」摘要。
      → 让它对当前 symbol 有 empirical 直觉。

  quick_backtest(parsed_signal, fn_name, params, symbol, timeframe, candle_limit=2000)
      内存跑 walk-forward，不写 DB — LLM 迭代自测用。返回 IS/OOS 指标 dict。
"""
from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from app.extensions import db
from app.models import Strategy, StrategyCandidate, BacktestResult, Trade
from app.services.user_scope import scoped_query, apply_user_filter
from sqlalchemy import desc, func


def pull_profitable_references(user_id: int, limit: int = 8,
                                cross_user: bool = False) -> list[dict]:
    """拉已证明能赚钱的策略当 LLM 学习样本。

    优先级（高→低）：
      1. 当前 running 策略中 OOS Sharpe ≥1.5 的（user scope，user 自己的最权威）
      2. qualified candidates（已过系统门槛）
      3. 任何 backtest_result OOS Sharpe ≥1.5 的策略（即使已 stopped）

    Phase 12.42 v8: cross_user=True 时 admin 拉全表（看其他 user profitable 策略学）
    return list of {source, type, symbol, timeframe, category, params, metrics}
    """
    refs: list[dict] = []
    seen_types: set[str] = set()

    def _add_from_strategy(s: Strategy):
        if not s or s.type in seen_types:
            return
        # 拉最新 backtest
        bt = apply_user_filter(
            db.session.query(BacktestResult), BacktestResult,
        ).filter(
            BacktestResult.strategy_id == s.id,
            BacktestResult.status == 'completed',
        ).order_by(desc(BacktestResult.created_at)).first()
        if not bt or not bt.walkforward_json:
            return
        wf = bt.walkforward_json
        oos = (wf.get('out_sample') or {}).get('sharpe_ratio')
        if oos is None or oos < 1.0:
            return
        seen_types.add(s.type)
        refs.append({
            'source': 'running_strategy',
            'type': s.type,
            'name': s.name,
            'symbol': s.symbol,
            'timeframe': s.timeframe,
            'category': s.category,
            'params': s.params or {},
            'metrics': {
                'oos_sharpe': round(oos, 2),
                'oos_pf': round((wf.get('out_sample') or {}).get('profit_factor') or 0, 2),
                'oos_trades': (wf.get('out_sample') or {}).get('total_trades'),
                'is_sharpe': round((wf.get('in_sample') or {}).get('sharpe_ratio') or 0, 2),
                'decay_pct': wf.get('decay_pct'),
            },
        })

    def _add_from_candidate(c: StrategyCandidate):
        if not c or c.candidate_type in seen_types or not c.backtest_result_id:
            return
        bt = BacktestResult.query.get(c.backtest_result_id)
        if not bt or not bt.walkforward_json:
            return
        wf = bt.walkforward_json
        oos = (wf.get('out_sample') or {}).get('sharpe_ratio')
        if oos is None or oos < 1.0:
            return
        seen_types.add(c.candidate_type)
        refs.append({
            'source': 'qualified_candidate',
            'type': c.candidate_type,
            'name': c.source_name or c.candidate_type,
            'symbol': (c.source_meta or {}).get('symbol', 'unknown'),
            'timeframe': c.timeframe,
            'category': c.category,
            'params': c.default_params or {},
            'parsed_signal': c.parsed_signal,    # 候选有源代码 → LLM 直接学结构
            'metrics': {
                'oos_sharpe': round(oos, 2),
                'oos_pf': round((wf.get('out_sample') or {}).get('profit_factor') or 0, 2),
                'oos_trades': (wf.get('out_sample') or {}).get('total_trades'),
                'is_sharpe': round((wf.get('in_sample') or {}).get('sharpe_ratio') or 0, 2),
                'decay_pct': wf.get('decay_pct'),
            },
        })

    running = scoped_query(Strategy).filter_by(status='running').all()
    for s in running:
        _add_from_strategy(s)

    quals = StrategyCandidate.query.filter_by(status='qualified').limit(20).all()
    for c in quals:
        _add_from_candidate(c)

    if len(refs) < limit:
        # 兜底：所有有正 OOS 的 backtest（即使 stopped）
        for s in scoped_query(Strategy).all():
            if s.type in seen_types:
                continue
            _add_from_strategy(s)
            if len(refs) >= limit:
                break

    refs.sort(key=lambda r: r['metrics']['oos_sharpe'], reverse=True)
    return refs[:limit]


# Phase 12.41: 内置 20 策略 catalog（用 inspect.getsource 拉源码喂 LLM 学）
BUILTIN_STRATEGY_META = {
    # type → (category, why_it_works summary)
    'ma_crossover':       ('trend',     'EMA fast cross slow — 经典趋势跟随'),
    'rsi':                ('mean_rev',  '超买超卖反转 — 横盘市场强'),
    'macd':               ('momentum',  '动量+信号线穿越 — 趋势启动捕捉'),
    'bollinger':          ('mean_rev',  '布林带触碰反转 — 波动率范围内有效'),
    'trend_following':    ('trend',     'EMA+ADX 双确认 — 强趋势市'),
    'volatility_breakout':('breakout',  'Donchian+ATR 突破 — 趋势启动'),
    'ml_mean_reversion':  ('mean_rev',  'BB+RSI+volume 三重确认 mean-rev (注册名 mean_reversion)'),
    'supertrend':         ('trend',     'ATR-based 动态止损跟随趋势'),
    'vwap_reversion':     ('mean_rev',  '相对 VWAP 偏离回归 — 日内/短期'),
    'keltner_channel':    ('breakout',  'EMA + ATR channel 突破'),
    'stochastic':         ('mean_rev',  '%K/%D 穿越 — 短周期反转'),
    'cci_reversal':       ('mean_rev',  'CCI 极值反转'),
    'atr_breakout':       ('breakout',  'EMA + ATR threshold 突破'),
    'heikin_ashi':        ('trend',     'HA 平滑K线方向 — 趋势确认降噪'),
    'ichimoku':           ('trend',     '云图多重 filter — 中长线'),
    'tema':               ('trend',     'TEMA 三重 EMA 减少 lag'),
    'psar':               ('trend',     'Parabolic SAR 反向止损跟随'),
    'golden_cross':       ('trend',     'EMA50/200 长线金叉'),
    'macd_trend_filter':  ('trend',     'MACD 信号 + EMA200 趋势 filter'),
    'weekly_pivot':       ('breakout',  '周枢轴位 +/- 距离突破'),
}


def pull_builtin_strategy_refs(limit: int = 20, include_source: bool = True) -> list[dict]:
    """提取系统内置 20 个策略的源码 + 元数据 — 让 LLM 看 vetted patterns。

    每条返回 {type, category, summary, fn_source}，fn_source 是 def xxx_signal(...): ... 的源码。
    LLM 看这些是「已经能跑 LIVE 的最低标准」— 学这个结构。
    """
    import inspect
    from app.services import strategy_engine as eng
    refs: list[dict] = []
    for stype, (cat, summary) in BUILTIN_STRATEGY_META.items():
        fn = getattr(eng, f'{stype}_signal', None)
        if fn is None:
            continue
        item = {'type': stype, 'category': cat, 'summary': summary}
        if include_source:
            try:
                src = inspect.getsource(fn)
                # 截断到 800 chars（避免 prompt 总长爆炸 - 20 策略 × 800 = 16k chars）
                if len(src) > 800:
                    src = src[:800] + '\n    # ... (truncated)'
                item['fn_source'] = src
            except OSError:
                item['fn_source'] = None
        refs.append(item)
        if len(refs) >= limit:
            break
    return refs


def pull_translated_candidate_refs(limit: int = 8) -> list[dict]:
    """已翻译候选（含 GitHub 爬取的 + AI 生成的） — 即使没回测也是 vetted code。

    Filter: status IN ('translated', 'qualified')，按 created_at desc。
    返回 {type, category, timeframe, source, source_name, fn_source, params}
    """
    refs: list[dict] = []
    # 14k-51: LLM few-shot 看 qualified + stale_qualified (好但没被 promote 也算正面例)
    # 不看 archived (永远不能 promote, 避免 LLM 学失败案例)
    cands = StrategyCandidate.query.filter(
        StrategyCandidate.status.in_(['translated', 'qualified', 'stale_qualified']),
        StrategyCandidate.parsed_signal.isnot(None),
    ).order_by(desc(StrategyCandidate.created_at)).limit(limit * 2).all()
    seen_types: set[str] = set()
    for c in cands:
        if c.candidate_type in seen_types:
            continue
        seen_types.add(c.candidate_type)
        src = c.parsed_signal or ''
        if len(src) > 1500:
            src = src[:1500] + '\n    # ... (truncated)'
        refs.append({
            'type': c.candidate_type,
            'category': c.category or 'unknown',
            'timeframe': c.timeframe or 'unknown',
            'source': c.source or 'unknown',
            'source_name': c.source_name or '?',
            'fn_source': src,
            'params': c.default_params or {},
        })
        if len(refs) >= limit:
            break
    return refs


def _safe_stat(arr) -> float | None:
    try:
        v = float(arr)
        if np.isnan(v) or np.isinf(v):
            return None
        return round(v, 4)
    except (TypeError, ValueError):
        return None


def compute_symbol_stats(candles: list[dict]) -> dict:
    """计算 symbol 实际 indicator 分布 + 价格统计 — LLM 看真数据。

    返回结构（喂 LLM 大约 300 tokens）:
    {
      'n_candles': 1500,
      'price_now': 23.4,
      'returns': {'mean_pct': 0.05, 'std_pct': 2.1, 'skew': -0.3, 'kurt': 5.2},
      'rsi14': {'mean': 49, 'p10': 28, 'p50': 49, 'p90': 71, 'pct_below_30': 12, 'pct_above_70': 8},
      'bb20': {'width_mean': 0.045, 'width_p10': 0.018, 'width_p90': 0.082},
      'adx14': {'mean': 24, 'p50': 22, 'pct_above_25': 38, 'pct_above_40': 12},
      'volume': {'mean': 1200, 'cv': 0.65},
      'trend': {'ema50_above_ema200_pct': 55, 'flips_per_100bars': 4.2},
      'recent_ohlc_tail_5': [...]  # 最后 5 根原始数据
    }
    """
    if not candles or len(candles) < 50:
        return {'error': f'candles 不足: {len(candles) if candles else 0}'}

    import ta  # 容器内已 install

    df = pd.DataFrame(candles)
    if 'close' not in df.columns:
        return {'error': 'no close column'}

    close = df['close']
    high = df['high'] if 'high' in df.columns else close
    low = df['low'] if 'low' in df.columns else close
    volume = df['volume'] if 'volume' in df.columns else pd.Series(np.zeros(len(df)))

    # Returns
    rets = close.pct_change().dropna() * 100  # in %
    ret_stats = {
        'mean_pct': _safe_stat(rets.mean()),
        'std_pct': _safe_stat(rets.std()),
        'skew': _safe_stat(rets.skew()),
        'kurt': _safe_stat(rets.kurtosis()),
    }

    out: dict[str, Any] = {
        'n_candles': len(df),
        'price_now': _safe_stat(close.iloc[-1]),
        'price_min': _safe_stat(close.min()),
        'price_max': _safe_stat(close.max()),
        'returns': ret_stats,
    }

    try:
        rsi = ta.momentum.RSIIndicator(close, window=14).rsi().dropna()
        out['rsi14'] = {
            'mean': _safe_stat(rsi.mean()),
            'p10': _safe_stat(rsi.quantile(0.10)),
            'p50': _safe_stat(rsi.quantile(0.50)),
            'p90': _safe_stat(rsi.quantile(0.90)),
            'pct_below_30': _safe_stat((rsi < 30).mean() * 100),
            'pct_above_70': _safe_stat((rsi > 70).mean() * 100),
            'now': _safe_stat(rsi.iloc[-1]) if len(rsi) else None,
        }
    except Exception as e:
        out['rsi14'] = {'error': str(e)[:80]}

    try:
        bb = ta.volatility.BollingerBands(close, window=20)
        width = (bb.bollinger_hband() - bb.bollinger_lband()) / close
        width = width.dropna()
        out['bb20'] = {
            'width_mean': _safe_stat(width.mean()),
            'width_p10': _safe_stat(width.quantile(0.10)),
            'width_p50': _safe_stat(width.quantile(0.50)),
            'width_p90': _safe_stat(width.quantile(0.90)),
            'width_now': _safe_stat(width.iloc[-1]) if len(width) else None,
        }
    except Exception as e:
        out['bb20'] = {'error': str(e)[:80]}

    try:
        adx = ta.trend.ADXIndicator(high, low, close, window=14).adx().dropna()
        out['adx14'] = {
            'mean': _safe_stat(adx.mean()),
            'p50': _safe_stat(adx.quantile(0.50)),
            'pct_above_25': _safe_stat((adx > 25).mean() * 100),
            'pct_above_40': _safe_stat((adx > 40).mean() * 100),
            'now': _safe_stat(adx.iloc[-1]) if len(adx) else None,
        }
    except Exception as e:
        out['adx14'] = {'error': str(e)[:80]}

    try:
        vol_mean = volume.mean()
        out['volume'] = {
            'mean': _safe_stat(vol_mean),
            'cv': _safe_stat(volume.std() / vol_mean) if vol_mean and vol_mean > 0 else None,
            'now_vs_mean': _safe_stat(volume.iloc[-1] / vol_mean) if vol_mean and vol_mean > 0 else None,
        }
    except Exception as e:
        out['volume'] = {'error': str(e)[:80]}

    try:
        ema50 = close.ewm(span=50, adjust=False).mean()
        ema200 = close.ewm(span=200, adjust=False).mean()
        above = (ema50 > ema200).iloc[200:]   # skip warmup
        flips = (above != above.shift(1)).sum()
        out['trend'] = {
            'ema50_above_ema200_pct': _safe_stat(above.mean() * 100),
            'flips_per_100bars': _safe_stat(flips * 100 / max(len(above), 1)),
            'ema50_now': _safe_stat(ema50.iloc[-1]),
            'ema200_now': _safe_stat(ema200.iloc[-1]),
            'price_vs_ema50_pct': _safe_stat((close.iloc[-1] / ema50.iloc[-1] - 1) * 100),
            'price_vs_ema200_pct': _safe_stat((close.iloc[-1] / ema200.iloc[-1] - 1) * 100),
        }
    except Exception as e:
        out['trend'] = {'error': str(e)[:80]}

    # Phase 12.41: MACD (12/26/9) — 动量 + 信号穿越
    try:
        macd_obj = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
        macd_line = macd_obj.macd()
        signal_line = macd_obj.macd_signal()
        hist = macd_obj.macd_diff()
        above_signal = (macd_line > signal_line).iloc[50:]
        crosses = (above_signal != above_signal.shift(1)).sum()
        out['macd_12_26_9'] = {
            'line_now': _safe_stat(macd_line.iloc[-1]),
            'signal_now': _safe_stat(signal_line.iloc[-1]),
            'hist_now': _safe_stat(hist.iloc[-1]),
            'hist_above_zero_pct': _safe_stat((hist.dropna() > 0).mean() * 100),
            'bull_cross_pct': _safe_stat(above_signal.mean() * 100),    # % 时间 macd>signal
            'crosses_per_100bars': _safe_stat(crosses * 100 / max(len(above_signal), 1)),
        }
    except Exception as e:
        out['macd_12_26_9'] = {'error': str(e)[:80]}

    # Phase 12.41: Stochastic (14, 3, 3)
    try:
        stoch = ta.momentum.StochasticOscillator(high, low, close, window=14, smooth_window=3)
        k = stoch.stoch().dropna()
        d = stoch.stoch_signal().dropna()
        out['stoch14'] = {
            'k_now': _safe_stat(k.iloc[-1]) if len(k) else None,
            'd_now': _safe_stat(d.iloc[-1]) if len(d) else None,
            'pct_oversold_below20': _safe_stat((k < 20).mean() * 100),
            'pct_overbought_above80': _safe_stat((k > 80).mean() * 100),
            'mean': _safe_stat(k.mean()),
        }
    except Exception as e:
        out['stoch14'] = {'error': str(e)[:80]}

    # Phase 12.41: ATR (14) — 波动率，用来决定 SL/TP 距离
    try:
        atr = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range().dropna()
        atr_pct = (atr / close.shift(0)) * 100   # ATR / 当前价 (%)
        out['atr14'] = {
            'now': _safe_stat(atr.iloc[-1]) if len(atr) else None,
            'pct_of_price_now': _safe_stat(atr_pct.iloc[-1]) if len(atr_pct) else None,
            'pct_of_price_mean': _safe_stat(atr_pct.mean()),
            'pct_of_price_p10': _safe_stat(atr_pct.quantile(0.10)),
            'pct_of_price_p90': _safe_stat(atr_pct.quantile(0.90)),
        }
    except Exception as e:
        out['atr14'] = {'error': str(e)[:80]}

    # Phase 12.41: OBV — 量价配合（趋势确认）
    try:
        obv = ta.volume.OnBalanceVolumeIndicator(close, volume).on_balance_volume()
        obv_ema = obv.ewm(span=20).mean()
        # 近 100 根 OBV 斜率 vs 价格斜率（正相关=量价配合 / 负=背离）
        n = min(100, len(obv) - 1)
        if n > 10:
            obv_chg = obv.iloc[-1] - obv.iloc[-n]
            price_chg = close.iloc[-1] - close.iloc[-n]
            corr_sign = (1 if (obv_chg * price_chg) > 0 else -1)
            out['obv'] = {
                'trend_last_100bars': 'rising' if obv.iloc[-1] > obv_ema.iloc[-1] else 'falling',
                'price_obv_alignment': 'aligned' if corr_sign > 0 else 'divergence',
                'obv_chg_pct_last_100bars': _safe_stat((obv.iloc[-1] / abs(obv.iloc[-n]) - 1) * 100 if obv.iloc[-n] != 0 else 0),
            }
        else:
            out['obv'] = {'note': 'insufficient data'}
    except Exception as e:
        out['obv'] = {'error': str(e)[:80]}

    # Phase 12.41: VWAP (累计 + 近 100 根 rolling)
    try:
        typical = (high + low + close) / 3
        tpv = typical * volume
        # 近 100 根滚动 VWAP（避免起始 anchor 失真）
        n = min(100, len(close))
        rvwap = tpv.rolling(n).sum() / volume.rolling(n).sum()
        rv_now = rvwap.iloc[-1]
        price_now = close.iloc[-1]
        out['vwap'] = {
            'rolling100_now': _safe_stat(rv_now),
            'price_vs_vwap_pct': _safe_stat((price_now / rv_now - 1) * 100) if rv_now and rv_now > 0 else None,
            'pct_above_vwap': _safe_stat((close > rvwap).iloc[n:].mean() * 100),
        }
    except Exception as e:
        out['vwap'] = {'error': str(e)[:80]}

    # Phase 12.41: 最近 swing highs/lows + 距离当前价
    try:
        # 简化 swing 定义: 局部 N 根窗口的极值
        window = 10
        recent = df.tail(200)
        if len(recent) >= 3 * window:
            rolling_max = recent['high'].rolling(2 * window + 1, center=True).max()
            rolling_min = recent['low'].rolling(2 * window + 1, center=True).min()
            swing_highs = recent[(recent['high'] == rolling_max) & rolling_max.notna()]['high']
            swing_lows = recent[(recent['low'] == rolling_min) & rolling_min.notna()]['low']
            # 最近 3 个 swing
            recent_highs = swing_highs.tail(3).tolist()
            recent_lows = swing_lows.tail(3).tolist()
            price_now = close.iloc[-1]
            out['swings_last_200bars'] = {
                'recent_highs': [_safe_stat(x) for x in recent_highs],
                'recent_lows': [_safe_stat(x) for x in recent_lows],
                'dist_to_nearest_high_pct': _safe_stat(min((h - price_now) / price_now * 100 for h in recent_highs if h > price_now), ) if any(h > price_now for h in recent_highs) else None,
                'dist_to_nearest_low_pct': _safe_stat(min((price_now - l) / price_now * 100 for l in recent_lows if l < price_now)) if any(l < price_now for l in recent_lows) else None,
            }
        else:
            out['swings_last_200bars'] = {'note': 'insufficient candles'}
    except Exception as e:
        out['swings_last_200bars'] = {'error': str(e)[:80]}

    # Phase 12.41: Fibonacci retracement — 基于最近大 swing
    try:
        n = min(200, len(close))
        recent_close = close.tail(n)
        hi = recent_close.max()
        lo = recent_close.min()
        rng = hi - lo
        if rng > 0:
            price_now = close.iloc[-1]
            fib_levels = {
                '0.236': lo + 0.236 * rng,
                '0.382': lo + 0.382 * rng,
                '0.500': lo + 0.500 * rng,
                '0.618': lo + 0.618 * rng,
                '0.786': lo + 0.786 * rng,
            }
            # 当前价位于哪个区间
            pos_pct = (price_now - lo) / rng * 100
            out['fib_last_200bars'] = {
                'swing_high': _safe_stat(hi),
                'swing_low': _safe_stat(lo),
                'current_pct_of_range': _safe_stat(pos_pct),
                'levels': {k: _safe_stat(v) for k, v in fib_levels.items()},
            }
        else:
            out['fib_last_200bars'] = {'note': 'zero range'}
    except Exception as e:
        out['fib_last_200bars'] = {'error': str(e)[:80]}

    return out


def quick_backtest(parsed_signal: str, signal_fn_name: str, params: dict,
                   symbol: str, timeframe: str,
                   *, candle_limit: int = 2000,
                   leverage: float | None = None,
                   position_size_usdt: float | None = None,
                   stop_loss_pct: float | None = None,
                   take_profit_pct: float | None = None,
                   cached_candles: list | None = None,
                   order_type: str | None = None) -> dict:
    """内存跑 walk-forward 回测，**不写 DB** — 给 LLM 迭代自测用。

    Phase 12.42 v8: 接受 risk_params overrides — LLM 写的 leverage/SL/TP/pos 直接进回测。
    默认值还是 backtest_engine.run_backtest 的默认（15x leverage / $10 / 5% SL / 8% TP）。

    返回 {ok, error, symbol, timeframe, metrics, walkforward_json, risk_params}
    """
    from app.services.candidate_sandbox import verify_signal_fn, load_signal_fn
    from app.services.exchange_service import fetch_ohlcv_history
    from app.services.backtest_engine import run_walkforward_backtest
    from app.services.config_service import get_config

    # 1. sandbox verify
    v = verify_signal_fn(parsed_signal, signal_fn_name, params or {})
    if not v.get('ok'):
        return {'ok': False, 'error': f'sandbox: {v.get("error")}', 'metrics': None}

    # 2. load fn
    try:
        signal_fn = load_signal_fn(parsed_signal, signal_fn_name)
    except Exception as e:
        return {'ok': False, 'error': f'load: {type(e).__name__}: {e}', 'metrics': None}

    # 3. fetch candles — 优先用调用方传的 cache 避免 OKX rate limit
    if cached_candles and len(cached_candles) >= 200:
        candles = cached_candles
    else:
        try:
            candles = fetch_ohlcv_history(symbol, timeframe, total_limit=candle_limit)
        except Exception as e:
            return {'ok': False, 'error': f'fetch_ohlcv: {type(e).__name__}: {e}', 'metrics': None}
    if not candles or len(candles) < 200:
        return {'ok': False, 'error': f'candles 太少 {len(candles) if candles else 0} < 200', 'metrics': None}

    # 4. run walk-forward (Phase 12.42: 传 risk_params; Phase 13: order_type 影响 fee)
    cfg = get_config()
    # Phase 13: fee 基于 order_type
    fee_map = {
        'market': 0.05,                  # OKX SWAP taker
        'maker': 0.02,                   # OKX SWAP maker (post_only)
        'maker_with_fallback': 0.025,    # 80% maker + 20% taker blend
    }
    fee_pct = fee_map.get(order_type, cfg.get('backtest_fee_pct', 0.05))

    bt_kwargs = {
        'timeframe': timeframe,
        'signal_fn': signal_fn,
        'slippage_pct': cfg.get('backtest_slippage_pct', 0.05),
        'fee_pct': fee_pct,
    }
    # Safety caps (绝不超出 user 系统级 max)
    max_leverage_cap = float(cfg.get('leverage', 15.0))   # user 当前设定的 leverage 当上限
    if leverage is not None:
        bt_kwargs['leverage'] = min(max(float(leverage), 1.0), max(max_leverage_cap, float(leverage)))
    if position_size_usdt is not None:
        bt_kwargs['position_size_usdt'] = max(float(position_size_usdt), 1.0)
    if stop_loss_pct is not None:
        bt_kwargs['stop_loss_pct'] = max(min(float(stop_loss_pct), 30.0), 1.0)
    if take_profit_pct is not None:
        bt_kwargs['take_profit_pct'] = max(min(float(take_profit_pct), 50.0), 1.0)

    try:
        wf = run_walkforward_backtest(
            signal_fn_name or 'candidate',
            params or {},
            candles,
            **bt_kwargs,
        )
    except Exception as e:
        return {'ok': False, 'error': f'walkforward: {type(e).__name__}: {e}', 'metrics': None}

    if wf.get('status') != 'completed':
        return {'ok': False, 'error': wf.get('error_message', 'wf 未完成'), 'metrics': None}

    isr = wf.get('in_sample') or {}
    oos = wf.get('out_sample') or {}
    full = wf.get('full') or {}

    # Phase 12.42: 额外抽出 trade-pattern 给 smart feedback 用
    oos_trades = (oos.get('trades') or [])
    sl_hits = sum(1 for t in oos_trades if t.get('reason') == 'stop_loss')
    tp_hits = sum(1 for t in oos_trades if t.get('reason') == 'take_profit')
    signal_exits = sum(1 for t in oos_trades if t.get('reason') in ('signal', 'reverse'))
    bars_held_list = [t.get('bars_held') for t in oos_trades if t.get('bars_held') is not None]
    avg_bars_held = round(sum(bars_held_list) / len(bars_held_list), 1) if bars_held_list else 0
    win_pnl = sum(t.get('pnl') or 0 for t in oos_trades if (t.get('pnl') or 0) > 0)
    loss_pnl = sum(abs(t.get('pnl') or 0) for t in oos_trades if (t.get('pnl') or 0) < 0)
    win_count = sum(1 for t in oos_trades if (t.get('pnl') or 0) > 0)
    loss_count = sum(1 for t in oos_trades if (t.get('pnl') or 0) < 0)
    avg_win = round(win_pnl / win_count, 2) if win_count else 0
    avg_loss = round(loss_pnl / loss_count, 2) if loss_count else 0

    return {
        'ok': True,
        'error': None,
        'symbol': symbol,
        'timeframe': timeframe,
        'risk_params': {
            'leverage': bt_kwargs.get('leverage'),
            'position_size_usdt': bt_kwargs.get('position_size_usdt'),
            'stop_loss_pct': bt_kwargs.get('stop_loss_pct'),
            'take_profit_pct': bt_kwargs.get('take_profit_pct'),
            'order_type': order_type or 'market',
            'fee_pct_used': fee_pct,
        },
        'trade_patterns': {
            'sl_hit_pct': round(sl_hits * 100 / max(len(oos_trades), 1), 1),
            'tp_hit_pct': round(tp_hits * 100 / max(len(oos_trades), 1), 1),
            'signal_exit_pct': round(signal_exits * 100 / max(len(oos_trades), 1), 1),
            'avg_bars_held': avg_bars_held,
            'avg_win_usdt': avg_win,
            'avg_loss_usdt': avg_loss,
            'win_loss_ratio': round(avg_win / avg_loss, 2) if avg_loss > 0 else None,
        },
        'metrics': {
            'is_sharpe': round(isr.get('sharpe_ratio') or 0, 2),
            'is_pf': round(isr.get('profit_factor') or 0, 2),
            'is_trades': isr.get('total_trades') or 0,
            'oos_sharpe': round(oos.get('sharpe_ratio') or 0, 2),
            'oos_pf': round(oos.get('profit_factor') or 0, 2),
            'oos_trades': oos.get('total_trades') or 0,
            'oos_ar_pct': round(oos.get('annual_return_pct') or 0, 2),
            'oos_wr_pct': round(oos.get('win_rate') or 0, 2),
            'oos_max_dd_pct': round(oos.get('max_drawdown_pct') or 0, 2),
            'decay_pct': wf.get('decay_pct'),
            'full_sharpe': round(full.get('sharpe_ratio') or 0, 2),
            'full_pf': round(full.get('profit_factor') or 0, 2),
            'full_trades': full.get('total_trades') or 0,
            'full_ar_pct': round(full.get('annual_return_pct') or 0, 2),
        },
        'walkforward_json': wf,   # 保留完整结果给最终写 DB 用
    }


# Per-TF promote gates — duplicate from advisor_executor for self-test consistency
TF_GATES = {
    '15m': {'min_pf': 1.5, 'min_trades': 60, 'min_ar': 8},
    '30m': {'min_pf': 1.5, 'min_trades': 50, 'min_ar': 8},
    '1h':  {'min_pf': 1.4, 'min_trades': 40, 'min_ar': 7},
    '4h':  {'min_pf': 1.4, 'min_trades': 30, 'min_ar': 7},
    '1d':  {'min_pf': 1.3, 'min_trades': 12, 'min_ar': 5},
    '1w':  {'min_pf': 1.2, 'min_trades': 8,  'min_ar': 4},
}
MIN_OOS_SHARPE_SELF_TEST = 1.5


def self_test_passes(metrics: dict, timeframe: str) -> tuple[bool, str]:
    """评估 quick_backtest 结果是否过自测门槛。返回 (passed, reason)."""
    if not metrics:
        return False, 'no metrics'
    gate = TF_GATES.get(timeframe, TF_GATES['4h'])
    if metrics['oos_sharpe'] < MIN_OOS_SHARPE_SELF_TEST:
        return False, f'OOS Sharpe {metrics["oos_sharpe"]} < {MIN_OOS_SHARPE_SELF_TEST}'
    if metrics['oos_pf'] < gate['min_pf']:
        return False, f'OOS PF {metrics["oos_pf"]} < {gate["min_pf"]} (TF {timeframe})'
    if metrics['oos_trades'] < gate['min_trades']:
        return False, f'OOS trades {metrics["oos_trades"]} < {gate["min_trades"]} (TF {timeframe})'
    if metrics['oos_ar_pct'] < gate['min_ar']:
        return False, f'OOS AR {metrics["oos_ar_pct"]}% < {gate["min_ar"]}% (TF {timeframe})'
    # decay 检查 — IS 牛 OOS 翻车
    decay = metrics.get('decay_pct')
    if decay is not None and decay > 70:
        return False, f'decay {decay}% > 70% (overfit)'
    return True, 'passed'
