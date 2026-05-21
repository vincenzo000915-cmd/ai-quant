"""Phase 11.5.6: 週復盤報告 — 過去 7 日 trades + advisor 動作 → 3 段中文"""
from __future__ import annotations

import datetime
import hashlib
import json

from sqlalchemy import desc
from app.extensions import db
from app.models import Trade, AuditLog
from app.services.llm_provider import call_llm
from app.services.user_scope import apply_user_filter

SYSTEM_PROMPT = """你是專業量化交易顧問。User 給你過去 7 日的交易紀錄與
advisor 已套用動作。請用 3 段中文（300 字內）：

1. **本週最賺策略 + 為什麼**（具體 PnL / 勝率，挑一個亮點）
2. **本週最爛策略 + 是否要 retire/pause 建議**（具體 PnL，給可操作建議）
3. **風控異常 highlight**（halt 事件 / 連續虧損 / 異常成交 等；若無就說「無異常」）

注意：
- 不要承諾下週走勢
- 不要說「這策略必賺」之類絕對話
- 末尾固定加：「⚠️ 此為復盤分析，非預測。」"""


def weekly_review(user_id: int) -> dict:
    since = datetime.datetime.utcnow() - datetime.timedelta(days=7)

    trades = apply_user_filter(
        db.session.query(Trade), Trade
    ).filter(Trade.exit_time >= since).order_by(desc(Trade.exit_time)).limit(200).all()

    by_strategy = {}
    for t in trades:
        sid = t.strategy_id
        if sid not in by_strategy:
            by_strategy[sid] = {'wins': 0, 'losses': 0, 'pnl': 0.0, 'trades': 0, 'symbol': t.symbol}
        by_strategy[sid]['trades'] += 1
        by_strategy[sid]['pnl'] += t.pnl or 0
        if (t.pnl or 0) > 0:
            by_strategy[sid]['wins'] += 1
        else:
            by_strategy[sid]['losses'] += 1

    if not trades:
        return {'ok': False, 'error': '過去 7 日無 trades，無從復盤'}

    audits = apply_user_filter(
        db.session.query(AuditLog), AuditLog
    ).filter(
        AuditLog.created_at >= since,
        AuditLog.event_type.in_([
            'halt', 'unhalt', 'kill_switch', 'reconcile',
            'advisor_auto_apply', 'strategy_retire', 'strategy_revive',
            'strategy_params_applied', 'live_order_blocked_no_okx_key',
        ])
    ).order_by(desc(AuditLog.created_at)).limit(50).all()

    # 構造 prompt
    lines = ['## 過去 7 日按策略統計\n']
    sorted_stats = sorted(by_strategy.items(), key=lambda kv: kv[1]['pnl'], reverse=True)
    for sid, st in sorted_stats[:20]:
        wr = (st['wins'] / st['trades'] * 100) if st['trades'] else 0
        lines.append(
            f'- 策略#{sid} ({st["symbol"]}): {st["trades"]} 筆，{wr:.0f}% 勝率，'
            f'PnL ${st["pnl"]:+.2f} ({st["wins"]} 勝 / {st["losses"]} 敗)'
        )
    lines.append('\n## 風控 / advisor 動作\n')
    for a in audits[:30]:
        lines.append(f'- {a.created_at.isoformat()} {a.event_type} actor={a.actor} ctx={json.dumps(a.context or {}, ensure_ascii=False)[:120]}')
    if not audits:
        lines.append('- 無')

    sig = json.dumps(sorted_stats[:5], default=str, sort_keys=True)
    cache_key = 'wreview:' + hashlib.sha256(sig.encode()).hexdigest()[:24]

    return call_llm(
        user_id=user_id,
        prompt='\n'.join(lines),
        system=SYSTEM_PROMPT,
        max_tokens=1500,
        cache_key=cache_key,
    )
