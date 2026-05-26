"""Phase 14k-45 L2: 信号 watcher 算条件 + 触发入场.

工作流:
  1. advisor 拿 AI brief.watch_indicators → LLM 转结构化条件 JSON
  2. SignalWatcher 表存 active watchers
  3. check_signal_watchers task 每 5min 跑算条件 → 满足 → 触发 strategy 一次入场信号
  4. 触发后 status=triggered, 不再算
"""
from __future__ import annotations

import datetime
import json
import re
from typing import Any

from app.extensions import db
from app.models import Candle, SignalWatcher


# 支持的 indicator → 算函数 map (复用 market_analyst._compute_indicators)
def _compute_indicator_value(candles: list, indicator: str) -> float | None:
    """从 candle 序列算单一 indicator 当前值."""
    if not candles:
        return None
    from app.services.llm_prompts.market_analyst import _compute_indicators
    ind = _compute_indicators(candles)
    return ind.get(indicator)


def _evaluate_one_condition(symbol: str, cond: dict) -> tuple[bool, dict]:
    """算一条条件. 返回 (是否满足, debug dict)."""
    tf = cond.get('tf', '1h')
    indicator = cond.get('indicator')
    op = cond.get('op')
    target = cond.get('value')

    if not indicator or not op or target is None:
        return False, {'error': 'missing indicator/op/value'}

    candles = (Candle.query
               .filter_by(symbol=symbol, timeframe=tf)
               .order_by(Candle.timestamp.desc()).limit(60).all())
    candles = list(reversed(candles))
    if len(candles) < 20:
        return False, {'error': f'{symbol} {tf}: only {len(candles)} candles'}
    candles_dict = [{'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close,
                     'volume': c.volume, 'timestamp': c.timestamp} for c in candles]

    actual = _compute_indicator_value(candles_dict, indicator)
    if actual is None:
        return False, {'error': f'cannot compute {indicator}', 'tf': tf}

    target = float(target)
    actual = float(actual)
    if op == '<':   met = actual < target
    elif op == '<=': met = actual <= target
    elif op == '>':  met = actual > target
    elif op == '>=': met = actual >= target
    elif op == '==': met = abs(actual - target) < 1e-9
    else:
        return False, {'error': f'unknown op: {op}'}

    return met, {'tf': tf, 'indicator': indicator, 'op': op, 'target': target, 'actual': actual, 'met': met}


def evaluate_watcher(watcher: SignalWatcher) -> tuple[bool, list[dict]]:
    """算一个 watcher 全部条件 (AND logic). 返回 (是否全满足, 每条 debug)."""
    conds = watcher.conditions or []
    if isinstance(conds, dict):
        conds = [conds]
    if not conds:
        return False, []
    debug = []
    all_met = True
    for c in conds:
        met, d = _evaluate_one_condition(watcher.symbol, c)
        debug.append(d)
        if not met:
            all_met = False
    return all_met, debug


def expire_old_watchers() -> int:
    """把过期的 watcher 标 expired."""
    now = datetime.datetime.utcnow()
    rows = (SignalWatcher.query
            .filter(SignalWatcher.status == 'active', SignalWatcher.expires_at <= now)
            .all())
    for w in rows:
        w.status = 'expired'
    if rows:
        db.session.commit()
    return len(rows)


def parse_brief_watch_indicators(watch_strings: list[str], symbol: str, side: str = 'buy',
                                   user_id: int = 1) -> list[dict]:
    """L2: LLM 把 brief.watch_indicators (自然语言) → 结构化条件 JSON.

    示例输入: ["15m RSI(14) < 30 + 4h close > SMA50"]
    输出: [{tf:'15m', indicator:'rsi_14', op:'<', value:30}, {tf:'4h', indicator:'close', op:'>', value:'sma_50_4h_actual'}]
    """
    from app.services.llm_provider import call_llm

    if not watch_strings:
        return []

    SYSTEM = """你是量化条件解析器. 把自然语言条件 → 严格 JSON list. 不要 markdown.

每个条件支持的字段:
- tf: 15m | 30m | 1h | 4h | 1d
- indicator: rsi_14 | atr_14 | bb_width_pct | sma_20 | sma_50 | pct_24h | close | volume_last
- op: < | <= | > | >= | ==
- value: 数字 (具体阈值)

约束: value 必须是数字; 含"成交量 > 20期均值"这种相对比较 → 转成具体数字; "突破 X 价格" → indicator='close', op='>', value=X.

输出 schema: 一个 JSON list, 每个 dict 是单条件. 多条件代表 AND (全满足才触发).
"""

    prompt = f"""## 自然语言条件
{json.dumps(watch_strings, ensure_ascii=False)}

请转成结构化 JSON list."""

    try:
        r = call_llm(
            user_id=user_id, prompt=prompt, system=SYSTEM,
            max_tokens=400,
            cache_key=f'watch_parse:{hash(tuple(watch_strings))}'[:30],
        )
        if not r.get('ok'):
            return []
        from app.services.llm_prompts.strategy_generate import _extract_json
        result = _extract_json(r['text'])
        if isinstance(result, list):
            # 守 schema
            valid = []
            for c in result:
                if isinstance(c, dict) and c.get('indicator') and c.get('op') and c.get('value') is not None:
                    valid.append({
                        'tf': c.get('tf', '1h'),
                        'indicator': c['indicator'],
                        'op': c['op'],
                        'value': c['value'],
                    })
            return valid
    except Exception as e:
        print(f'[watch_parse] failed: {type(e).__name__}: {e}')
    return []


def create_watchers_from_brief(strategy_id: int, symbol: str, brief: dict,
                                 user_id: int = 1, expires_hours: int = 24) -> list[int]:
    """L2: brief.watch_indicators → 创建 SignalWatcher rows.
    返回 new watcher ids list."""
    watch_strings = brief.get('watch_indicators') or []
    if not watch_strings:
        return []

    conditions = parse_brief_watch_indicators(watch_strings, symbol, user_id=user_id)
    if not conditions:
        return []

    archetype = brief.get('recommended_archetype', '')
    side = 'sell' if 'short' in archetype else 'buy'

    expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=expires_hours)
    # 整组条件 = 一个 watcher (AND)
    w = SignalWatcher(
        strategy_id=strategy_id,
        user_id=user_id,
        symbol=symbol,
        conditions=conditions,
        side=side,
        source='ai_brief',
        status='active',
        expires_at=expires_at,
    )
    db.session.add(w)
    db.session.commit()
    return [w.id]
