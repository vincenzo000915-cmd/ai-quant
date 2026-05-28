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
                ).limit(10).all()
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
            # 14k-133 (Finding B): 不再取最近 6 笔 (可能恰好一串亏损, 与"已成功策略"框架矛盾).
            # 按 pnl 排序取「最赚 4 + 最亏 2」, 都带 pnl 标签 → LLM 评价式学习"何时有效/何时失效".
            trades.sort(key=lambda x: -x['pnl_pct'])
            ex['real_trades'] = (trades[:4] + trades[-2:]) if len(trades) > 6 else trades

        # ---- Part 2 (14k-132): AI 自己合成并实盘盈利的赢家也回流成 few-shot ----
        # Why: 原本 few-shot 只拉 source='catalog' (教科书), AI 学不到自己发现的赢家 →
        #   学习环在"自己的成功"端断开, 永远只模仿教科书. 这里补上: 把 candidate-backed 且
        #   实盘净盈利 (≥3 笔, sum(pnl)>0) 的 promoted 策略, 连同它的盈利 trades 一起喂回.
        #   下游仍有 OOS≥1.5 + paper dry-run 门槛兜底, 故纯增益、安全.
        from app.extensions import db
        from sqlalchemy import func
        existing_types = {t['candidate_type'] for t in top}
        winner_rows = (db.session.query(
                Strategy.id.label('sid'), Strategy.type, Strategy.timeframe,
                Strategy.candidate_id,
                func.coalesce(func.sum(Trade.pnl), 0).label('net'),
                func.count(Trade.id).label('n'))
            .join(Trade, Trade.strategy_id == Strategy.id)
            .filter(Strategy.candidate_id.isnot(None))
            .group_by(Strategy.id, Strategy.type, Strategy.timeframe, Strategy.candidate_id)
            .having(func.sum(Trade.pnl) > 0)
            .having(func.count(Trade.id) >= 3)
            .order_by(func.sum(Trade.pnl).desc())
            .limit(2).all())
        for w in winner_rows:
            c = StrategyCandidate.query.get(w.candidate_id)
            if not c or not c.parsed_signal:
                continue
            base_type = c.candidate_type or w.type
            if base_type in existing_types:
                continue   # catalog 已含同 type, 不重复
            wins = (Trade.query.filter(Trade.strategy_id == w.sid, Trade.pnl > 0)
                    .order_by(Trade.exit_time.desc()).limit(6).all())
            cm = c.catalog_meta or {}
            top.append({
                'candidate_type': base_type + ' [自研赢家·实盘盈利]',
                'signal_code': c.parsed_signal,
                'verified_oos_sharpe': float(cm.get('verified_oos_sharpe') or 0),
                'description': (cm.get('description') or '')[:80] + f' (实盘净盈利 ${float(w.net):.2f} / {w.n} 笔)',
                'timeframe': w.timeframe,
                'real_trades': [{
                    'symbol': t.symbol,
                    'date': t.exit_time.strftime('%m/%d %H:%M') if t.exit_time else '?',
                    'side': t.side,
                    'entry': round(float(t.entry_price or 0), 2),
                    'exit': round(float(t.exit_price or 0), 2),
                    'pnl_pct': round(float(t.pnl_percent or 0), 2),
                    'reason': t.reason or '?',
                } for t in wins],
            })

        return top
    except Exception as e:
        print(f'[14k-62] get_few_shot_with_trades error: {type(e).__name__}: {e}')
        return []


# ============= A Step 2: Python verify hypothesis =============

def verify_hypothesis(candles: list, hypothesis: dict) -> dict:
    """A Step 2: 14k-67 改 — 模拟真实 trade (SL/TP 哪个先到) + 算 EV (期望收益).

    user 哲学: "我们追的是盈利率不是胜率, R:R 不对称 (SL 小 TP 大), 低胜率也能赚"
    例: SL 2% TP 8%, 25% 胜率 = 0.25*8 - 0.75*2 = +0.5%/trade (有正期望)

    hypothesis schema (LLM Step 1 输出):
    {
      "entry_condition": {indicator, params, op, threshold},
      "exit_horizon_bars": 5,    # 最大持仓 bars (SL/TP 都没到才平)
      "expected_direction": "long" | "short",
      "sl_pct": 1.5,             # 14k-67 新: LLM 提议 SL/TP, 自主 R:R
      "tp_pct": 6.0,             # 14k-67 新
    }

    Returns: {triggers, win_rate, avg_pnl, expected_value, profit_factor, sample_size, ok}
    avg_pnl 就是真实 EV (含 SL/TP 触发逻辑)
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
    # 14k-67: LLM 提议 sl/tp, fallback TF-aware 默认 (15m 1%/2% / 4h 5%/8%)
    sl_pct = float(hypothesis.get('sl_pct') or 2.0)
    tp_pct = float(hypothesis.get('tp_pct') or 6.0)

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
        return {'ok': True, 'triggers': 0, 'win_rate': 0.0, 'avg_pnl': 0.0,
                'expected_value': 0.0, 'profit_factor': None, 'sample_size': 0,
                'reason': 'hypothesis 在历史从未触发'}

    # 14k-67: 模拟真实 trade — 每次触发后跟 SL/TP, 哪个先到
    pnl_list = []
    wins = []
    losses = []
    for i in triggers:
        entry = df['close'].iloc[i]
        if direction == 'long':
            sl_price = entry * (1 - sl_pct / 100)
            tp_price = entry * (1 + tp_pct / 100)
        else:
            sl_price = entry * (1 + sl_pct / 100)
            tp_price = entry * (1 - tp_pct / 100)
        # 跟 horizon 内 SL/TP 哪个先到
        trade_pnl = None
        for j in range(1, horizon + 1):
            if i + j >= len(df):
                break
            bar = df.iloc[i + j]
            if direction == 'long':
                # bar 内最低先到 SL → 假设 SL 触发 (悲观假设, 同一根 high/low 谁先到不知道)
                if bar['low'] <= sl_price:
                    trade_pnl = -sl_pct
                    break
                if bar['high'] >= tp_price:
                    trade_pnl = tp_pct
                    break
            else:  # short
                if bar['high'] >= sl_price:
                    trade_pnl = -sl_pct
                    break
                if bar['low'] <= tp_price:
                    trade_pnl = tp_pct
                    break
        if trade_pnl is None:
            # horizon 内 SL/TP 都没到 → 用 horizon 末 close 平
            exit_close = df['close'].iloc[i + horizon]
            if direction == 'long':
                trade_pnl = (exit_close - entry) / entry * 100
            else:
                trade_pnl = (entry - exit_close) / entry * 100
        pnl_list.append(trade_pnl)
        if trade_pnl > 0:
            wins.append(trade_pnl)
        else:
            losses.append(trade_pnl)

    win_rate = len(wins) / len(pnl_list)
    avg_pnl = sum(pnl_list) / len(pnl_list)
    sum_wins = sum(wins) if wins else 0
    sum_losses_abs = abs(sum(losses)) if losses else 0
    profit_factor = (sum_wins / sum_losses_abs) if sum_losses_abs > 0 else (None if not wins else float('inf'))
    pf_str = 'PF ∞' if profit_factor == float('inf') else (f'PF {profit_factor:.2f}' if profit_factor else 'PF 0')
    rr = tp_pct / sl_pct if sl_pct > 0 else None
    # 14k-67: EV (期望收益, per trade) = avg_pnl. 这是 user 哲学的核心: 追盈利率不追胜率
    return {
        'ok': True,
        'triggers': len(triggers),
        'win_rate': round(win_rate, 3),
        'avg_pnl': round(avg_pnl, 3),
        'expected_value': round(avg_pnl, 3),    # alias for clarity
        'profit_factor': (round(profit_factor, 2) if profit_factor and profit_factor != float('inf') else profit_factor),
        'sl_used': sl_pct,
        'tp_used': tp_pct,
        'rr_ratio': round(rr, 2) if rr else None,
        'sample_size': len(triggers),
        'reason': (f'胜率 {win_rate:.0%} | EV {avg_pnl:+.2f}%/trade | {pf_str} | '
                   f'R:R {rr:.1f} (SL {sl_pct}% TP {tp_pct}%) | {len(triggers)} 次触发'),
    }


# ============= A Step 1 prompt: LLM 看 K 线 + 提 hypothesis =============

STEP1_SYSTEM = """你是量化研究员. 我给你一段真实 K 线 + 已成功的 catalog 策略真实 trades.
任务: 不写代码, 只观察 + 提一个**可验证的假设** (hypothesis).

⚠️ 核心哲学 (14k-67): 我们追**盈利率 (EV)** 不追胜率
- 设计 R:R 不对称: SL 紧 TP 大, TP/SL ≥ 2.5 倍 (推荐 3-5)
- 即使胜率 25-30%, 仍赚钱: 例 SL 2% / TP 8% (R:R 4), 25% 胜率 = 0.25*8 - 0.75*2 = +0.5%/trade
- 别写 "高胜率" 策略 — 那是传统量化思维, 加密币真实市场不可能持续
- 你要写 "赔率不对称" 策略: 让赢的一次能吃 3-4 次小亏后还赚

要求:
1. 看 K 线找 pattern + 明确 sl_pct / tp_pct (R:R ≥ 2.5)
2. 看 catalog 成功 trades 学 R:R 风格
3. Python 会模拟真实 trade (SL/TP 哪个先到) 算 EV
4. hypothesis 描述要具体可验

输出 **严格 JSON** (无 markdown):
{
  "market_observation": "中文 2-3 句描述当前 K 线 pattern",
  "hypothesis_name": "RSI 超卖反弹 / Donchian 突破 等",
  "rationale": "为什么这个假设成立 + 为什么 R:R 合理",
  "entry_condition": {
    "indicator": "RSI | BB_lower_touch | BB_upper_touch | MACD_hist | EMA_ratio | ATR_pct | volume_ratio | PSAR_distance | Donchian_high_touch | Donchian_low_touch | Stoch_K | CCI",
    "params": {"period": 14},
    "op": "< | > | cross_up | cross_down | touch",
    "threshold": 30
  },
  "exit_horizon_bars": 10,
  "expected_direction": "long | short",
  "sl_pct": 1.5,
  "tp_pct": 6.0
}

约束:
- indicator 12 种, 选最贴合 hypothesis 的
- PSAR_distance 价格距 PSAR % (>0 上方; cross_up 翻多)
- Donchian touch = close/rolling_max(min) (=1.0 触碰)
- Stoch_K 0-100, CCI 典型 ±100
- op 严格匹配
- exit_horizon_bars 5-30 (给 TP 时间到, 不要太短)
- **tp_pct >= 2.5 × sl_pct** (R:R 至少 2.5)
- sl_pct/tp_pct float (按 TF: 15m 0.8-1.5/2-5, 1h 1-2/3-7, 4h 2-4/6-12)
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
        # 14k-67: schema 改 — 删 expected_return_pct, 加 sl_pct/tp_pct (LLM 自主 R:R)
        required = {'market_observation', 'hypothesis_name', 'entry_condition',
                    'exit_horizon_bars', 'expected_direction', 'sl_pct', 'tp_pct'}
        missing = required - set(spec.keys())
        if missing:
            return {'ok': False, 'error': f'Step 1 缺字段: {sorted(missing)}'}
        # 14k-67: R:R 强制 ≥ 2.5
        try:
            sl_p = float(spec['sl_pct'])
            tp_p = float(spec['tp_pct'])
            if sl_p <= 0 or tp_p <= 0:
                return {'ok': False, 'error': f'sl/tp 必须 > 0 (sl={sl_p}, tp={tp_p})'}
            if tp_p / sl_p < 2.5:
                return {'ok': False,
                        'error': f'R:R {tp_p/sl_p:.1f} < 2.5 (赔率不对称要求, 让 LLM 重写)',
                        'rr_too_low': True}
        except (TypeError, ValueError):
            return {'ok': False, 'error': f'sl/tp 非数字: sl={spec.get("sl_pct")}, tp={spec.get("tp_pct")}'}
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

## Python verify 结果 (模拟真实 trade with SL/TP)
- 历史触发次数: {verify_result['triggers']}
- 胜率: {verify_result['win_rate']:.0%}
- **EV (盈利率/trade): {verify_result['expected_value']:+.2f}%**
- Profit Factor: {verify_result.get('profit_factor')}
- R:R: {verify_result.get('rr_ratio')} (SL {verify_result['sl_used']}% TP {verify_result['tp_used']}%)

## 目标
- Symbol: {symbol}
- Timeframe: {timeframe}
{fs_code_block}

把上面 hypothesis 编成 Python signal_fn (严格按 entry_condition 实现), 输出 JSON.
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

# 14k-67: 撤回 14k-62/66 胜率门槛 — user 哲学 "追盈利率不追胜率"
# 真实 trade 模拟后看 EV (期望收益/trade), > fee+slippage buffer 就过
MIN_EXPECTED_VALUE_PCT = 0.3      # EV ≥ 0.3%/trade (留 fee 0.05+slip 0.05 双边 ~0.2% buffer)
MIN_PROFIT_FACTOR = 1.2           # 总盈利 / 总亏损 ≥ 1.2 (双重保险)
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
    # 14k-67: EV-based 门槛 (user 哲学: 追盈利率不追胜率)
    # 真实模拟 trade (SL/TP 哪个先到) 后 EV ≥ 0.3% (含 fee buffer) + PF ≥ 1.2
    ev = verify['expected_value']
    pf = verify['profit_factor']
    ev_pass = ev >= MIN_EXPECTED_VALUE_PCT
    pf_pass = (pf == float('inf')) or (pf is not None and pf >= MIN_PROFIT_FACTOR)
    if not (ev_pass and pf_pass):
        return {'ok': False,
                'error': (f'未过门槛 — EV {ev:+.2f}%/trade (需≥{MIN_EXPECTED_VALUE_PCT}%) '
                          f'/ PF {pf} (需≥{MIN_PROFIT_FACTOR})'),
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
