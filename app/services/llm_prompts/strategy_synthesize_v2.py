"""Phase 14k-62: 升级版 strategy synthesize — A 多步思考 + C 真实 trades 反馈.

诊断 (user 抓的): 14k-45/57 LLM zero-shot 写策略写不出好的, 因为:
1. LLM 看二手 brief (LLM 自己 synth 的数据), garbage compounding
2. catalog few-shot 都是教科书风格, LLM 模仿写出更多教科书
3. LLM 不懂"市场统计现实", 没有真实命中率反馈

修法 (A+C 一起做):

A. 多步思考 + 真实 K 线 (不再用二手 brief)
   Step 1 (LLM): 看 300 根真实 K 线 + 描述市场结构 + 提 structured hypothesis
   Step 2 (Python): verify hypothesis — 算历史命中率 + 样本数
   Step 3 (LLM): hypothesis 通过 (命中率 ≥ 55% + 样本 ≥ 10) 才编 signal_fn

C. 真实 trades 反馈 (不只给代码)
   few-shot 含 promoted strategies 的真实 LIVE trades:
   "cat_ttm_squeeze 真跑过 N 次: 5/22 BTC entry $79k exit $82k profit"
   LLM 看 trade-by-trade 学具体哪种 setup 真赚钱

LLM token: 2x (Step 1 + Step 3), Step 2 Python 算不调 LLM.
"""
from __future__ import annotations

import hashlib
import json

import pandas as pd
import numpy as np
import ta

from app.services.llm_provider import call_llm


# ============= C: 真实 trades few-shot =============

def get_few_shot_with_trades(target_timeframe: str | None = None, max_n: int = 3) -> list[dict]:
    """C: 拉 catalog 优秀模板 + 它们 promoted 后真实 trades 数据.

    Returns: [{candidate_type, signal_code, verified_oos_sharpe, description,
               timeframe, real_trades: [{date, side, entry, exit, pnl_pct, reason}, ...]}, ...]
    """
    from app.models import StrategyCandidate, Strategy, Trade

    try:
        # 1. 拉 catalog 模板 (verified)
        cands = StrategyCandidate.query.filter_by(source='catalog', status='qualified').all()
        scored = []
        for c in cands:
            cm = c.catalog_meta or {}
            v = cm.get('verified_oos_sharpe')
            if v is None or float(v) < 1.5 or not c.parsed_signal:
                continue
            tf_match = (target_timeframe and c.timeframe == target_timeframe)
            scored.append({
                'candidate_type': c.candidate_type,
                'signal_code': c.parsed_signal,
                'verified_oos_sharpe': float(v),
                'description': cm.get('description', ''),
                'timeframe': c.timeframe,
                'tf_match': tf_match,
            })
        scored.sort(key=lambda x: (not x['tf_match'], -x['verified_oos_sharpe']))
        top = scored[:max_n]

        # 2. 拉每个模板的真实 trades (找 promoted_strategy_id 关联的)
        for ex in top:
            # 找以这个 candidate_type 为 prefix 的 Strategy (promoted 后 strategy.type 含 candidate_type)
            related = Strategy.query.filter(
                Strategy.type.like(f'%{ex["candidate_type"]}%')
            ).all()
            trades = []
            for s in related[:3]:    # 最多看 3 个 promoted 实例
                tr = Trade.query.filter_by(strategy_id=s.id).order_by(
                    Trade.exit_time.desc()
                ).limit(5).all()
                for t in tr:
                    trades.append({
                        'symbol': t.symbol,
                        'date': t.exit_time.strftime('%m/%d %H:%M') if t.exit_time else '?',
                        'side': t.side,
                        'entry': round(float(t.entry_price or 0), 2),
                        'exit': round(float(t.exit_price or 0), 2),
                        'pnl_pct': round(float(t.pnl_percent or 0), 2),
                        'reason': t.reason or '?',
                    })
            ex['real_trades'] = trades[:6]   # 每个模板最多 6 笔真 trades

        return top
    except Exception as e:
        print(f'[14k-62] get_few_shot_with_trades error: {type(e).__name__}: {e}')
        return []


# ============= A Step 2: Python verify hypothesis =============

def verify_hypothesis(candles: list, hypothesis: dict) -> dict:
    """A Step 2: Python 算 hypothesis 在历史 K 线上的真实命中率.

    hypothesis schema (LLM Step 1 输出, structured):
    {
      "name": "RSI 超卖反弹",
      "entry_condition": {
        "indicator": "RSI" | "BB_lower_touch" | "MACD_cross" | "EMA_cross" | "ATR_spike",
        "params": {"period": 14},
        "op": "<" | ">" | "cross_up" | "cross_down" | "touch",
        "threshold": 30
      },
      "exit_horizon_bars": 5,
      "expected_direction": "long" | "short",
      "expected_return_pct": 0.5
    }

    Returns: {triggers, hits, hit_rate, avg_return, sample_size, ok}
    """
    if not candles or len(candles) < 50:
        return {'ok': False, 'reason': f'candles 不足 ({len(candles) if candles else 0})'}

    df = pd.DataFrame(candles).sort_values('timestamp').reset_index(drop=True)
    if len(df) < 50:
        return {'ok': False, 'reason': 'candles 不足 50'}

    ec = hypothesis.get('entry_condition', {})
    indicator = ec.get('indicator')
    period = (ec.get('params') or {}).get('period', 14)
    op = ec.get('op', '<')
    threshold = float(ec.get('threshold', 30))
    horizon = int(hypothesis.get('exit_horizon_bars', 5))
    direction = hypothesis.get('expected_direction', 'long')
    expected_return = float(hypothesis.get('expected_return_pct', 0.5))

    # 算 indicator series (14k-64.1 扩到 12 种, 加 PSAR / Donchian / Stoch / CCI / EMA_cross)
    try:
        if indicator == 'RSI':
            series = ta.momentum.RSIIndicator(df['close'], window=period).rsi()
        elif indicator == 'BB_lower_touch':
            bb = ta.volatility.BollingerBands(df['close'], window=period, window_dev=2)
            series = df['close'] / bb.bollinger_lband()    # ratio: 1 = touch lower, <1 = under, >1 = above
        elif indicator == 'BB_upper_touch':
            bb = ta.volatility.BollingerBands(df['close'], window=period, window_dev=2)
            series = df['close'] / bb.bollinger_hband()
        elif indicator == 'MACD_hist':
            macd = ta.trend.MACD(df['close'])
            series = macd.macd_diff()
        elif indicator == 'EMA_ratio':
            ema = ta.trend.EMAIndicator(df['close'], window=period).ema_indicator()
            series = df['close'] / ema
        elif indicator == 'ATR_pct':
            atr = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=period).average_true_range()
            series = atr / df['close'] * 100
        elif indicator == 'volume_ratio':
            vol_ma = df['volume'].rolling(period).mean()
            series = df['volume'] / vol_ma
        # 14k-64.1: PSAR flip — close 跟 PSAR 距离 (>0 价格在 PSAR 上方/趋势上)
        elif indicator == 'PSAR_distance':
            psar = ta.trend.PSARIndicator(df['high'], df['low'], df['close'])
            series = (df['close'] - psar.psar()) / df['close'] * 100   # % 距离
        # Donchian — 价格跟 N 日新高/新低关系
        elif indicator == 'Donchian_high_touch':
            high_n = df['high'].rolling(period).max()
            series = df['close'] / high_n
        elif indicator == 'Donchian_low_touch':
            low_n = df['low'].rolling(period).min()
            series = df['close'] / low_n
        # Stochastic
        elif indicator == 'Stoch_K':
            stoch = ta.momentum.StochasticOscillator(df['high'], df['low'], df['close'], window=period)
            series = stoch.stoch()
        # CCI
        elif indicator == 'CCI':
            series = ta.trend.CCIIndicator(df['high'], df['low'], df['close'], window=period).cci()
        else:
            return {'ok': False, 'reason': f'未知 indicator: {indicator}'}
    except Exception as e:
        return {'ok': False, 'reason': f'指标计算失败: {type(e).__name__}: {e}'}

    # 找触发点
    triggers = []
    for i in range(period + 5, len(df) - horizon):
        v = series.iloc[i]
        if pd.isna(v):
            continue
        if op == '<' and v < threshold:
            triggers.append(i)
        elif op == '>' and v > threshold:
            triggers.append(i)
        elif op == 'cross_up' and not pd.isna(series.iloc[i-1]) and series.iloc[i-1] <= threshold < v:
            triggers.append(i)
        elif op == 'cross_down' and not pd.isna(series.iloc[i-1]) and series.iloc[i-1] >= threshold > v:
            triggers.append(i)
        elif op == 'touch' and abs(v - threshold) < 0.02:    # tolerance for ratio touches
            triggers.append(i)

    if not triggers:
        return {'ok': True, 'triggers': 0, 'hits': 0, 'hit_rate': 0.0,
                'avg_return': 0.0, 'sample_size': 0,
                'reason': 'hypothesis 在历史从未触发'}

    # 算每个触发后 horizon bars 的实际收益
    hits = 0
    returns = []
    for i in triggers:
        entry = df['close'].iloc[i]
        exit_close = df['close'].iloc[i + horizon]
        if direction == 'long':
            ret = (exit_close - entry) / entry * 100
        else:
            ret = (entry - exit_close) / entry * 100
        returns.append(ret)
        if ret >= expected_return:
            hits += 1

    hit_rate = hits / len(triggers)
    avg_return = sum(returns) / len(returns) if returns else 0.0
    return {
        'ok': True,
        'triggers': len(triggers),
        'hits': hits,
        'hit_rate': round(hit_rate, 3),
        'avg_return': round(avg_return, 3),
        'sample_size': len(triggers),
        'reason': f'命中率 {hit_rate:.0%} ({hits}/{len(triggers)} 次), 平均收益 {avg_return:+.2f}%',
    }


# ============= A Step 1 prompt: LLM 看 K 线 + 提 hypothesis =============

STEP1_SYSTEM = """你是量化研究员. 我给你一段真实 K 线 + 已成功的 catalog 策略真实 trades.
任务: 不写代码, 只观察 + 提一个**可验证的假设** (hypothesis).

要求:
1. 看 K 线找 pattern (不要凭空猜)
2. 看 catalog 成功 trades 学风格
3. 提一个 structured hypothesis (Python 可解析验证)
4. hypothesis 描述要具体可验, 不要 "市场会涨"这种废话

输出 **严格 JSON** (无 markdown):
{
  "market_observation": "中文 2-3 句描述当前 K 线最近的 pattern",
  "hypothesis_name": "RSI 超卖反弹 / BB 下轨触底 等",
  "rationale": "为什么这个假设成立 (1-2 句)",
  "entry_condition": {
    "indicator": "RSI | BB_lower_touch | BB_upper_touch | MACD_hist | EMA_ratio | ATR_pct | volume_ratio | PSAR_distance | Donchian_high_touch | Donchian_low_touch | Stoch_K | CCI",
    "params": {"period": 14},
    "op": "< | > | cross_up | cross_down | touch",
    "threshold": 30
  },
  "exit_horizon_bars": 5,
  "expected_direction": "long | short",
  "expected_return_pct": 0.5
}

约束:
- indicator 只能用上面 12 种之一 (Python 能算的)
- PSAR_distance 是价格距 PSAR 的 % (>0 = 上方/上涨趋势; cross_up = 翻多)
- Donchian_high/low_touch 是 close/rolling_max(min) 比例 (touch = 1.0)
- Stoch_K 0-100 (<20 超卖 / >80 超买)
- CCI -∞~+∞ (典型 ±100 极值)
- op 必须严格匹配
- threshold 是数字
- exit_horizon_bars 1-30 (短线 3-5, 长线 10-20)
- expected_return_pct 必须保守 (0.3-2.0)
"""


def _step1_propose_hypothesis(symbol: str, timeframe: str, candles: list,
                              few_shot: list, user_id: int = 1, hint: str | None = None) -> dict:
    """A Step 1: LLM 看 K 线 + few-shot 真 trades → 提 structured hypothesis."""
    # K 线压缩 (太多 token 浪费, LLM 看最近 60 根 + 全段统计)
    recent = candles[-60:]
    closes = [c['close'] for c in candles]
    full_stats = {
        'price_range': [round(min(closes), 2), round(max(closes), 2)],
        'current_price': round(closes[-1], 2),
        'recent_change_pct': round((closes[-1] - closes[-20]) / closes[-20] * 100, 2),
        'volatility_atr_pct': round(
            np.mean([abs(c['high'] - c['low']) for c in candles[-20:]]) / closes[-1] * 100, 2),
    }

    # few-shot trades 格式化
    fs_block = ''
    if few_shot:
        lines = []
        for ex in few_shot:
            lines.append(f"\n### {ex['candidate_type']} ({ex['timeframe']}, OOS Sharpe {ex['verified_oos_sharpe']:.2f})")
            if ex.get('description'):
                lines.append(f"思路: {ex['description'][:100]}")
            if ex.get('real_trades'):
                lines.append(f"真实交易 ({len(ex['real_trades'])} 笔):")
                for t in ex['real_trades']:
                    lines.append(f"  - {t['date']} {t['symbol']} {t['side']} @ ${t['entry']} → ${t['exit']} "
                                f"({t['pnl_pct']:+.2f}%, {t['reason']})")
        fs_block = '\n## 已成功策略的真实 LIVE 交易\n' + '\n'.join(lines)

    hint_block = f"\n## Trigger 提示\n{hint}\n" if hint else ''

    # K 线最近 60 根 (OHLC 简化)
    candle_block = '\n'.join(
        f"  {i}: O={c['open']:.2f} H={c['high']:.2f} L={c['low']:.2f} C={c['close']:.2f} V={c['volume']:.0f}"
        for i, c in enumerate(recent)
    )

    prompt = f"""## 任务
观察 {symbol} ({timeframe}) 最近 K 线, 提一个可验证的入场假设.

## 全段统计 (300 根)
{json.dumps(full_stats, ensure_ascii=False, indent=2)}

## 最近 60 根 K 线
{candle_block}
{fs_block}
{hint_block}
请输出 structured hypothesis JSON.
"""

    r = call_llm(
        user_id=user_id, prompt=prompt, system=STEP1_SYSTEM,
        max_tokens=1500,
        cache_key=f'synth_v2_step1:{symbol}:{timeframe}:{hashlib.sha256(str(closes[-1]).encode()).hexdigest()[:10]}',
    )
    if not r.get('ok'):
        return {'ok': False, 'error': f'Step 1 LLM 失败: {r.get("error")}'}

    try:
        from app.services.llm_prompts.strategy_generate import _extract_json
        spec = _extract_json(r['text'])
        if not spec:
            return {'ok': False, 'error': 'Step 1 JSON 解析失败', 'raw': r.get('text', '')[:300]}
        required = {'market_observation', 'hypothesis_name', 'entry_condition',
                    'exit_horizon_bars', 'expected_direction', 'expected_return_pct'}
        missing = required - set(spec.keys())
        if missing:
            return {'ok': False, 'error': f'Step 1 缺字段: {sorted(missing)}'}
        return {'ok': True, 'hypothesis': spec}
    except Exception as e:
        return {'ok': False, 'error': f'Step 1 parse: {type(e).__name__}: {e}'}


# ============= A Step 3 prompt: LLM 把验证的 hypothesis 编码 =============

STEP3_SYSTEM = """你是 Python 工程师. 我给你一个**Python 已验证过的** trading hypothesis +
catalog 优秀策略的代码风格参考. 把 hypothesis 编成 signal_fn.

输出 **严格 JSON** (无 markdown):
{
  "signal_fn_name": "synth_<short_id>_signal",
  "signal_code": "def synth_<id>_signal(df, params):\\n    ...\\n    return 'buy'/'sell'/'hold'",
  "default_params": {<参数 dict 可在 params 里覆盖>},
  "risk_params": {"leverage": 1-10, "sl_pct": 1-15, "tp_pct": 2-30, "order_type": "market"},
  "category": "long" | "short" | "swing" | "ultra",
  "timeframe": "15m" | "1h" | "4h",
  "rationale_zh": "1-2 句中文 (用 verify 通过的命中率作依据)",
  "rationale_en": "1-2 sentence English"
}

signal_fn 约束:
- 签名 (df: pd.DataFrame, params: dict) → str
- df 列: open, high, low, close, volume, timestamp (升序)
- 只能用 ta, pandas, numpy
- 返回 'buy' / 'sell' / 'hold'
- 长度 < 50 行, 简洁
- **严格按 hypothesis.entry_condition 实现**, 不要瞎加 indicator
- 用 params.get() 取阈值

risk_params 按 timeframe 业界标准 (15m SL≤1.5% / 4h SL 5%).
"""


def _step3_encode_signal(hypothesis: dict, verify_result: dict,
                         symbol: str, timeframe: str, few_shot: list,
                         user_id: int = 1) -> dict:
    """A Step 3: 把 verify 通过的 hypothesis 编成 signal_fn."""
    # few-shot 只给代码 (Step 1 已给 trades 学风格了)
    fs_code_block = ''
    if few_shot:
        codes = []
        for ex in few_shot[:2]:    # 2 个代码足够
            codes.append(f"### {ex['candidate_type']} (OOS Sharpe {ex['verified_oos_sharpe']:.2f})\n"
                        f"```python\n{ex['signal_code'][:800]}\n```")
        fs_code_block = '\n## 代码风格参考\n' + '\n\n'.join(codes)

    prompt = f"""## 已验证的 hypothesis
{json.dumps(hypothesis, ensure_ascii=False, indent=2)}

## Python verify 结果
- 历史触发次数: {verify_result['triggers']}
- 命中次数: {verify_result['hits']}
- 命中率: {verify_result['hit_rate']:.0%}
- 平均收益: {verify_result['avg_return']:+.2f}%

## 目标
- Symbol: {symbol}
- Timeframe: {timeframe}
{fs_code_block}

把上面 hypothesis 编成 Python signal_fn, 输出 JSON.
"""

    r = call_llm(
        user_id=user_id, prompt=prompt, system=STEP3_SYSTEM,
        max_tokens=2000,
        cache_key=f'synth_v2_step3:{hashlib.sha256(json.dumps(hypothesis, sort_keys=True).encode()).hexdigest()[:10]}',
    )
    if not r.get('ok'):
        return {'ok': False, 'error': f'Step 3 LLM 失败: {r.get("error")}'}

    try:
        from app.services.llm_prompts.strategy_generate import _extract_json
        spec = _extract_json(r['text'])
        if not spec:
            return {'ok': False, 'error': 'Step 3 JSON 解析失败', 'raw': r.get('text', '')[:300]}
        required = {'signal_fn_name', 'signal_code', 'default_params', 'risk_params',
                    'category', 'timeframe', 'rationale_zh', 'rationale_en'}
        missing = required - set(spec.keys())
        if missing:
            return {'ok': False, 'error': f'Step 3 缺字段: {sorted(missing)}'}
        # 安全检查
        code = spec['signal_code']
        forbidden = ['os.', 'sys.', 'subprocess', '__import__', 'eval(', 'exec(', 'open(']
        if any(f in code for f in forbidden):
            return {'ok': False, 'error': '代码含禁用 import / eval'}
        return {'ok': True, **spec}
    except Exception as e:
        return {'ok': False, 'error': f'Step 3 parse: {type(e).__name__}: {e}'}


# ============= 主入口 =============

MIN_HIT_RATE = 0.55              # hypothesis verify 命中率门槛
MIN_HIT_RATE_LOW = 0.45          # 14k-66 C: 命中率较低但单笔大也可过
MIN_AVG_RETURN_FOR_LOW_HIT = 0.5 # 14k-66 C: 低命中率时需要平均收益 ≥ 0.5% 才放行
MIN_SAMPLE_SIZE = 10              # 至少 10 次历史触发才可信


def synthesize_strategy_v2(symbol: str, timeframe: str, balance: float,
                            target_pct: float, days_remaining: int,
                            user_id: int = 1, hint: str | None = None) -> dict:
    """14k-62: multi-step + Python verify + real trades few-shot.

    Returns: {ok, signal_fn_name, signal_code, ..., verify_meta} or {ok: False, error, stage}
    """
    from app.services.exchange_service import fetch_ohlcv_history

    # 1. 拉真实 K 线
    candles = fetch_ohlcv_history(symbol, timeframe, total_limit=300)
    if not candles or len(candles) < 100:
        return {'ok': False, 'error': f'K 线不足 ({len(candles) if candles else 0})', 'stage': 'fetch'}

    # 2. C: 拉 few-shot 含真实 trades
    few_shot = get_few_shot_with_trades(target_timeframe=timeframe, max_n=3)

    # 3. A Step 1: LLM 提 hypothesis
    s1 = _step1_propose_hypothesis(symbol, timeframe, candles, few_shot, user_id=user_id, hint=hint)
    if not s1.get('ok'):
        return {'ok': False, 'error': s1.get('error'), 'stage': 'step1'}
    hypothesis = s1['hypothesis']

    # 4. A Step 2: Python verify
    verify = verify_hypothesis(candles, hypothesis)
    if not verify.get('ok'):
        return {'ok': False, 'error': verify.get('reason'), 'stage': 'verify'}
    if verify['sample_size'] < MIN_SAMPLE_SIZE:
        return {'ok': False,
                'error': f'hypothesis 历史样本 {verify["sample_size"]} < {MIN_SAMPLE_SIZE}, 不可信',
                'stage': 'verify', 'verify': verify}
    # 14k-66 C: 两路过门槛 — 高命中率 OR (中等命中率 + 高单笔收益)
    high_hit = verify['hit_rate'] >= MIN_HIT_RATE
    low_hit_high_return = (verify['hit_rate'] >= MIN_HIT_RATE_LOW
                           and verify['avg_return'] >= MIN_AVG_RETURN_FOR_LOW_HIT)
    if not (high_hit or low_hit_high_return):
        return {'ok': False,
                'error': (f'hypothesis 命中率 {verify["hit_rate"]:.0%} + 平均收益 {verify["avg_return"]:+.2f}% '
                          f'未过门槛 (需 命中≥{MIN_HIT_RATE:.0%} 或 命中≥{MIN_HIT_RATE_LOW:.0%}+均收益≥{MIN_AVG_RETURN_FOR_LOW_HIT}%)'),
                'stage': 'verify', 'verify': verify}

    # 5. A Step 3: LLM 编码 (只在 verify 通过后才调)
    s3 = _step3_encode_signal(hypothesis, verify, symbol, timeframe, few_shot, user_id=user_id)
    if not s3.get('ok'):
        return {'ok': False, 'error': s3.get('error'), 'stage': 'step3', 'verify': verify}

    # 合并 meta
    return {
        **s3,
        'symbol': symbol,
        'hypothesis': hypothesis,
        'verify_meta': verify,
    }
