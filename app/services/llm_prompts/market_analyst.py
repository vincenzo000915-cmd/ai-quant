"""Phase 14k-45 L1: AI 市场分析 brief

让 LLM 实时综合多 TF K 线 + 关键指标 → 输出当下市场 brief.
取代单一 regime_detector (只看 ADX/Hurst), 给 advisor 更立体的"现在该用什么策略型态"判断.

输出 JSON 直接用于:
  - advisor 选 catalog (score)
  - L2 signal_watcher 创建条件 (watch_indicators)
  - L3 strategy_synthesize 生成实时 signal_fn
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from app.services.llm_provider import call_llm
from app.services.exchange_service import fetch_ohlcv_history

SYSTEM_PROMPT = """你是顶级量化交易员 + 实时市场分析师. 看多 TF K 线 + 关键指标, 输出 **严格 JSON** (无 markdown, 无解释).

输出 schema:
{
  "regime": "trending_up" | "trending_down" | "ranging" | "breakout_imminent" | "high_volatility" | "low_volatility" | "reversal_setup",
  "confidence": 0.0-1.0,
  "recommended_archetype": "trend_follower" | "mean_reverter" | "breakout" | "wait",
  "watch_indicators": [
    "具体可量化的条件 / Specific condition (eg 'RSI(14) 1h < 30 + 4h close > MA50')"
  ],
  "key_levels": {"support": <price>, "resistance": <price>},
  "summary_zh": "1-2 句中文总结当下市场 + 建议动作",
  "summary_en": "1-2 sentence English summary"
}

约束:
- regime / archetype 必须从枚举里选, 不能创新
- watch_indicators 至少 1 个, 最多 3 个, 必须可量化 (有具体数值阈值)
- key_levels 用真实价格 (不是 %), 没有就给 null
- summary 中英双语都必填, 中文为主
"""


def _compute_indicators(candles: list) -> dict:
    """算关键指标 (不依赖外部 ta lib, 简洁版).
    candles: [{open, high, low, close, volume, timestamp}, ...] 升序
    """
    if not candles or len(candles) < 20:
        return {}
    closes = [c['close'] for c in candles]
    highs = [c['high'] for c in candles]
    lows = [c['low'] for c in candles]
    n = len(candles)
    last = closes[-1]

    # SMA / EMA
    sma_20 = sum(closes[-20:]) / 20 if n >= 20 else None
    sma_50 = sum(closes[-50:]) / 50 if n >= 50 else None

    # RSI(14) Wilder simplified
    rsi = None
    if n >= 15:
        gains = []
        losses = []
        for i in range(-14, 0):
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_g = sum(gains) / 14
        avg_l = sum(losses) / 14
        rs = avg_g / avg_l if avg_l > 0 else 0
        rsi = round(100 - 100 / (1 + rs), 1) if avg_l > 0 else 100

    # ATR(14)
    atr = None
    if n >= 15:
        trs = []
        for i in range(-14, 0):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            trs.append(tr)
        atr = round(sum(trs) / 14, 4)

    # Bollinger Band width (20, 2)
    bb_width_pct = None
    if n >= 20 and sma_20:
        variance = sum((c - sma_20) ** 2 for c in closes[-20:]) / 20
        std = math.sqrt(variance)
        bb_width_pct = round((4 * std / sma_20) * 100, 2) if sma_20 else None

    # 24h price change
    pct_24h = None
    if n >= 24:
        old = closes[-24] if n >= 24 else closes[0]
        pct_24h = round((last - old) / old * 100, 2) if old else None

    return {
        'close': last,
        'sma_20': round(sma_20, 4) if sma_20 else None,
        'sma_50': round(sma_50, 4) if sma_50 else None,
        'rsi_14': rsi,
        'atr_14': atr,
        'bb_width_pct': bb_width_pct,
        'pct_24h': pct_24h,
        'highest_24': round(max(highs[-24:]), 4) if n >= 24 else None,
        'lowest_24': round(min(lows[-24:]), 4) if n >= 24 else None,
        'volume_avg_20': round(sum(c['volume'] for c in candles[-20:]) / 20, 2) if n >= 20 else None,
        'volume_last': candles[-1].get('volume'),
    }


def analyze_market(symbol: str, timeframes: list[str] | None = None,
                   user_id: int = 1) -> dict:
    """LLM 实时分析多 TF 市场 → 输出 brief JSON.

    cache: 5-15min (per symbol+TFs combo)
    """
    tfs = timeframes or ['15m', '1h', '4h']

    # 拉 K 线 + 算指标
    per_tf = {}
    for tf in tfs:
        try:
            candles = fetch_ohlcv_history(symbol, tf, total_limit=200)
            if not candles:
                continue
            ind = _compute_indicators(candles)
            per_tf[tf] = ind
        except Exception as e:
            per_tf[tf] = {'error': f'{type(e).__name__}: {e}'}

    if not per_tf:
        return {'ok': False, 'error': '所有 TF K 线拉不到'}

    # LLM prompt
    prompt = f"""## 交易对 {symbol}\n\n"""
    for tf, ind in per_tf.items():
        prompt += f"### {tf} TF 指标\n"
        prompt += json.dumps(ind, ensure_ascii=False) + "\n\n"
    prompt += "请输出 brief JSON (按 schema)."

    sig_key = hashlib.sha256(
        json.dumps([symbol, tfs, {tf: per_tf[tf].get('close') for tf in per_tf}],
                   sort_keys=True, default=str).encode()
    ).hexdigest()[:20]

    r = call_llm(
        user_id=user_id,
        prompt=prompt,
        system=SYSTEM_PROMPT,
        max_tokens=600,
        cache_key=f'market_brief:{sig_key}',
    )
    if not r.get('ok'):
        return {'ok': False, 'error': r.get('error', 'LLM 失败'), 'raw_indicators': per_tf}

    try:
        from app.services.llm_prompts.strategy_generate import _extract_json
        spec = _extract_json(r['text'])
        if not spec:
            return {'ok': False, 'error': 'LLM 输出无法解析为 JSON', 'raw': r.get('text', '')[:300]}

        # 守 schema
        valid_regimes = {'trending_up', 'trending_down', 'ranging', 'breakout_imminent',
                         'high_volatility', 'low_volatility', 'reversal_setup'}
        valid_archetypes = {'trend_follower', 'mean_reverter', 'breakout', 'wait'}
        if spec.get('regime') not in valid_regimes:
            return {'ok': False, 'error': f"regime '{spec.get('regime')}' 非法 (must be in {valid_regimes})"}
        if spec.get('recommended_archetype') not in valid_archetypes:
            return {'ok': False, 'error': f"archetype 非法"}

        return {
            'ok': True,
            'symbol': symbol,
            'timeframes': tfs,
            'brief': spec,
            'indicators': per_tf,
            'llm_meta': {
                'provider_used': r.get('provider_used'),
                'model_used': r.get('model_used'),
                'cached': r.get('cached'),
            },
        }
    except Exception as e:
        return {'ok': False, 'error': f'{type(e).__name__}: {e}'}


def archetype_to_affinity(archetype: str) -> str | None:
    """L1 brief.recommended_archetype → STRATEGY_AFFINITY value (兼容 advisor 评分).
    'wait' → None (advisor 不出 action)
    """
    mapping = {
        'trend_follower': 'trend_follower',
        'mean_reverter': 'mean_reverter',
        'breakout': 'breakout',
        'wait': None,
    }
    return mapping.get(archetype)
