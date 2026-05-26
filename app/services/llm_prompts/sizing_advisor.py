"""Phase 11.5.12: AI 推荐仓位 / 杠杆 / SL/TP — 看 balance + 现况输出具体数字

跟 personal_advice 不同：personal_advice 输出叙述性建议，sizing_advisor 输出
**严格 JSON**，可被前端一键 apply 到 SystemConfig。
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import func
from app.extensions import db
from app.models import Strategy, Trade, SystemConfig
from app.services.llm_provider import call_llm
from app.services.user_scope import apply_user_filter, scoped_query

SYSTEM_PROMPT = """你是专业量化风控顾问。User 给你账户状况，请输出**严格 JSON**
（不要 markdown 包围，直接 JSON 物件）— 不要解释，只 JSON。

⚠️ 14k-47 规则更新：SL/TP **per-strategy 自动按 timeframe 决定**:
  15m: SL 1.0%/TP 2.0%  ·  30m: SL 1.5%/TP 3.0%  ·  1h: SL 2.5%/TP 5.0%
  4h:  SL 5.0%/TP 8.0%   ·  1d: SL 10%/TP 18%
你出的 stop_loss_pct/take_profit_pct **只作账户级最后 fallback**（罕用），
不是 per-strategy 推荐 — 实际策略 SL/TP 走 backtest_engine.resolve_default_sl_tp。

输出 schema（所有字段必填）：
{
  "trade_size_usdt": 数字，每笔下单本金。原则：账户余额 < $100 用 4，$100-$500 用 8-15，$500+ 用 20-40
  "leverage": 数字 1-20。原则：余额小 / 策略多 / 最近虧 → 降；余额大 / 策略少 / 最近赚 → 升
  "stop_loss_pct": 数字 1-15。**账户级 fallback 而已**, 保守值 5 (4h 默认)
  "take_profit_pct": 数字 2-30。**账户级 fallback 而已**, 保守值 8 (4h 默认)
  "max_daily_loss_usdt": 数字。原则：余额的 5-10%。$75 余额 → $5-7
  "rationale": 一段中文（100 字内）说明这套参数的逻辑（重点 lev/size/daily_loss, 不是 SL/TP）
}

约束：
- 所有数字必须是 number 不是字符串
- trade_size_usdt × leverage ≤ 余额 × 3（防爆仓）
- 不要返回 null
"""


def recommend_sizing(user_id: int, account_info: dict) -> dict:
    running = scoped_query(Strategy).filter_by(status='running').all()
    cfg = SystemConfig.query.get(1)

    # 最近 7 日 trades
    import datetime
    since = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    recent_pnl = apply_user_filter(
        db.session.query(func.coalesce(func.sum(Trade.pnl), 0)), Trade
    ).filter(Trade.exit_time >= since).scalar() or 0
    recent_count = apply_user_filter(
        db.session.query(func.count(Trade.id)), Trade
    ).filter(Trade.exit_time >= since).scalar() or 0

    prompt = f"""## 账户状况
- 余额: ${account_info.get('balance', 0):.2f}
- 可用保证金: ${account_info.get('free_margin', 0):.2f}
- 未实现 PnL: ${account_info.get('unrealized_pnl', 0):.2f}

## 当前配置
- trade_size_usdt: {cfg.trade_size_usdt if cfg else '?'}
- leverage: {cfg.leverage if cfg else '?'}
- stop_loss_pct: {cfg.stop_loss_pct if cfg else '?'}
- take_profit_pct: {cfg.take_profit_pct if cfg else '?'}
- max_daily_loss_usdt: {cfg.max_daily_loss_usdt if cfg else '?'}

## Running 策略 ({len(running)} 个)
{chr(10).join(f'- {s.name} ({s.symbol} {s.timeframe})' for s in running[:10])}

## 最近 7 日表现
- {recent_count} 笔 trades, 累积 PnL ${recent_pnl:+.2f}

请输出新的推荐参数 JSON。"""

    sig = json.dumps([round(account_info.get('balance', 0), 0), len(running), round(recent_pnl, 1)], default=str)
    cache_key = 'sizing:' + hashlib.sha256(sig.encode()).hexdigest()[:20]

    r = call_llm(
        user_id=user_id,
        prompt=prompt,
        system=SYSTEM_PROMPT,
        max_tokens=800,
        cache_key=cache_key,
    )
    if not r.get('ok'):
        return r

    # 解析 JSON
    try:
        from app.services.llm_prompts.strategy_generate import _extract_json
        spec = _extract_json(r['text'])
        if not spec:
            return {'ok': False, 'error': 'LLM 输出无法解析为 JSON', 'raw': r['text'][:300]}

        # 验证字段 — 14k-47: stop_loss_pct/take_profit_pct 改成可选 (per-strategy TF-aware 主导)
        required = {'trade_size_usdt', 'leverage', 'max_daily_loss_usdt', 'rationale'}
        missing = required - set(spec.keys())
        if missing:
            return {'ok': False, 'error': f'LLM 输出缺字段: {sorted(missing)}', 'spec': spec}

        # 14k-47: SL/TP 没出 → 用 4h 业界保守值作 fallback (反正只在 strategy.params 和 TF-aware 都没的情况下用)
        if 'stop_loss_pct' not in spec:
            spec['stop_loss_pct'] = 5.0
        if 'take_profit_pct' not in spec:
            spec['take_profit_pct'] = 8.0

        # 数字 sanity check
        for k in ['trade_size_usdt', 'leverage', 'stop_loss_pct', 'take_profit_pct', 'max_daily_loss_usdt']:
            try:
                spec[k] = float(spec[k])
            except (TypeError, ValueError):
                return {'ok': False, 'error': f'{k} 不是数字: {spec[k]}'}

        # 当前配置（给 frontend diff 用）
        current = {
            'trade_size_usdt': cfg.trade_size_usdt if cfg else None,
            'leverage': cfg.leverage if cfg else None,
            'stop_loss_pct': cfg.stop_loss_pct if cfg else None,
            'take_profit_pct': cfg.take_profit_pct if cfg else None,
            'max_daily_loss_usdt': cfg.max_daily_loss_usdt if cfg else None,
        }

        return {
            'ok': True,
            'recommended': spec,
            'current': current,
            'llm_meta': {
                'provider_used': r.get('provider_used'),
                'model_used': r.get('model_used'),
                'latency_ms': r.get('latency_ms'),
                'cached': r.get('cached'),
            },
        }
    except Exception as e:
        return {'ok': False, 'error': f'{type(e).__name__}: {e}'}
