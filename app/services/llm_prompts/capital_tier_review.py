"""Phase 14k-124: 资金跨档时 AI 重评估 running 策略 mix.

触发: profit_monitor 检测到 balance 跨过 $100/$500/$2000 → 调本 prompt.

跟现有 prompt 的分工:
  - sizing_advisor: 全局账户参数 (trade_size / lev / daily_loss) — 不动这个
  - strategy_recommend: 推**新**策略 (catalog clone / 候选池 promote) — 已 hooked profit_monitor
  - 14k-124 本 prompt: **重评 EXISTING 策略 mix**, 看新档应该:
    · 砍掉哪些表现不好或冗余的 (fan_out 重复 / 同 TF 过度集中)
    · 哪些应该 fan_out 到更多 symbol 分散
    · 哪些应该升 lev (资金多了能承担)
    · 是否应该加 TF (例 全 4h 现在可加 15m/1h 短线分散时间域)

不直接 retire 现有策略 — 输出 suggestions 让 advisor + user 决定;
只 auto-apply 低风险 action (fan_out / adjust_strategy_risk + lev up).
"""
from __future__ import annotations

import json
import datetime
from app.extensions import db
from app.models import Strategy, Trade
from app.services.llm_provider import call_llm
from app.services.user_scope import scoped_query


SYSTEM_PROMPT = """你是资深量化组合经理. User 资金刚跨过新档位 (e.g. $100 → $500), 你要重新
评估现有 running 策略 mix 是否最优, 输出**严格 JSON** (不要 markdown 包围, 不要解释).

评估原则:
1. **TF 多样性**: 资金小 (<$200) 集中 4h 低频可接受; 资金 $500+ 应该 mix 短/中/长 TF 分散
   时间风险 (15m 抓 intraday / 1h-4h 中线 / 1d 长线)
2. **Symbol 多样性**: 同一 symbol 多 strategy 接近 fan_out 上限, 不要继续推同 symbol
3. **lev 弹性**: 资金大了 + 策略健康 (Sharpe ≥1.5 + 最近 7d 真盈利) 可适度升 lev (但 ≤ TF
   合理上限: 15m 5-8 / 1h 4-6 / 4h 3-5 / 1d 2-3)
4. **保守底线**: 不主动 retire/pause 现有 (那是 weekly_review 看表现的事), 你只 propose:
   fan_out / adjust_strategy_risk / suggest_pause (suggest 给 user 看, 不自动执行)

输出 schema (所有字段必填):
{
  "analysis": "1-2 句中文总结: 资金 X → Y 应该怎么调结构 (e.g. '4 个全 4h 同时间域, 加 1h 分散')",
  "auto_actions": [           // 低风险, AI 自己 apply (经 advisor 守门员)
    {
      "action": "fan_out" | "adjust_strategy_risk",
      "strategy_id": 数字,
      "params": { ... },      // action 对应参数, 例 fan_out: {target_symbols: ["ETH/USDT"]}
                              //                adjust_strategy_risk: {new_leverage: 5}
      "reason": "中文 1 句"
    }
  ],
  "user_suggestions": [        // 给 user 看 TG, 不自动执行
    {
      "kind": "pause" | "retire" | "add_tf",
      "target": "strategy_id 或 TF 名称",
      "reason": "中文 1 句"
    }
  ]
}

约束:
- auto_actions 最多 3 个 (避免大动)
- fan_out target_symbols 必须不在 strategy 已有 symbol 内
- adjust_strategy_risk new_leverage 必须 ≤ 当前 +50% (一次别升太狠)
- 不要 propose 修改 SL/TP / sl_pct / tp_pct (走 risk_optimizer 渠道, 不归你管)
"""


def review_mix_for_capital_tier(user_id: int, old_tier_usd: float, new_tier_usd: float,
                                  current_balance: float) -> dict:
    """Phase 14k-124: 跨档时 AI 重评 mix.

    返回:
      {ok: bool, raw: ...,
       analysis: str,
       auto_actions: [{action, strategy_id, params, reason}],
       user_suggestions: [{kind, target, reason}],
       error?: str}
    """
    running = scoped_query(Strategy).filter_by(status='running').all()
    if not running:
        return {'ok': False, 'error': 'no running strategies to review'}

    # 收集 mix 信息
    week_ago = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    strategies_info = []
    tf_count = {}
    symbol_count = {}
    for s in running:
        # 排除 reconcile_orphan (14k-100/121 同口径)
        orphan = ['reconcile_orphan_hl', 'reconcile_orphan_okx', 'reconcile_orphan']
        recent_trades = Trade.query.filter(
            Trade.strategy_id == s.id,
            Trade.exit_time > week_ago,
            ~Trade.reason.in_(orphan),
        ).all()
        pnl_7d = sum(float(t.pnl or 0) for t in recent_trades)
        rp = (s.params or {}).get('risk_params') or {}
        strategies_info.append({
            'id': s.id,
            'name': s.name[:40],
            'symbol': s.symbol,
            'timeframe': s.timeframe,
            'type': s.type,
            'category': s.category,
            'current_leverage': rp.get('leverage', 3),
            'trades_7d': len(recent_trades),
            'pnl_7d': round(pnl_7d, 2),
        })
        tf_count[s.timeframe or '?'] = tf_count.get(s.timeframe or '?', 0) + 1
        symbol_count[s.symbol or '?'] = symbol_count.get(s.symbol or '?', 0) + 1

    prompt = f"""## 资金跨档
- 旧档: ${old_tier_usd:.0f} → 新档: ${new_tier_usd:.0f}
- 当前真实余额: ${current_balance:.2f}

## 现有 running 策略 mix ({len(running)} 个)
{json.dumps(strategies_info, ensure_ascii=False, indent=2)}

## TF 分布
{json.dumps(tf_count, ensure_ascii=False)}

## Symbol 分布
{json.dumps(symbol_count, ensure_ascii=False)}

请按 system prompt 评估新档应该怎么调 mix, 输出 JSON."""

    r = call_llm(
        user_id=user_id,
        prompt=prompt,
        system=SYSTEM_PROMPT,
        max_tokens=1200,
        cache_key=f'tier_review:{user_id}:{int(new_tier_usd)}',
    )
    if not r.get('ok'):
        return {'ok': False, 'error': r.get('error', 'LLM call failed')}

    # 解析 JSON
    try:
        from app.services.llm_prompts.strategy_generate import _extract_json
        spec = _extract_json(r['text'])
        if not spec:
            return {'ok': False, 'error': 'LLM 输出无法解析为 JSON', 'raw': r['text'][:300]}
    except Exception as e:
        return {'ok': False, 'error': f'parse: {type(e).__name__}: {e}', 'raw': r['text'][:300]}

    return {
        'ok': True,
        'analysis': spec.get('analysis', ''),
        'auto_actions': spec.get('auto_actions', []),
        'user_suggestions': spec.get('user_suggestions', []),
        'raw': r.get('text', '')[:500],
    }
