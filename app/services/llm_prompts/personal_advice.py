"""Phase 11.5.7: 個性化建議 — balance + 持倉 + running strategies + regime"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import func
from app.extensions import db
from app.models import Strategy, Position, Trade
from app.services.llm_provider import call_llm
from app.services.user_scope import apply_user_filter, scoped_query

SYSTEM_PROMPT = """你是專業量化顧問。User 給你他的帳戶數據：餘額、持倉、
running 策略、最近 PnL 趨勢。請用 3 段中文（250 字內）給**具體可操作**建議：

1. **帳戶風險**（餘額 vs 槓桿 vs 持倉密度 — 是否該降槓桿 / 分散）
2. **策略組合**（有沒有過度集中某 type/symbol；建議啟用/停用哪些）
3. **時間框架建議**（看交易頻率與本金大小，給時間框架建議）

注意：
- 不要承諾盈利
- 不給具體買賣信號
- 末尾固定加：「⚠️ 本建議僅供參考，請自負風險。」"""


def personal_advice(user_id: int, account_info: dict) -> dict:
    running = scoped_query(Strategy).filter_by(status='running').all()
    open_positions = scoped_query(Position).filter_by(status='open').all()

    # 最近 7 日 PnL
    import datetime
    since = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    recent_pnl = apply_user_filter(
        db.session.query(func.coalesce(func.sum(Trade.pnl), 0)), Trade
    ).filter(Trade.exit_time >= since).scalar() or 0
    recent_trades = apply_user_filter(
        db.session.query(func.count(Trade.id)), Trade
    ).filter(Trade.exit_time >= since).scalar() or 0

    lines = [
        '## 帳戶資訊',
        f'- 總餘額: ${account_info.get("balance", 0):.2f}',
        f'- 可用保證金: ${account_info.get("free_margin", 0):.2f}',
        f'- 未實現 PnL: ${account_info.get("unrealized_pnl", 0):.2f}',
        '',
        f'## Running 策略 ({len(running)} 個)',
    ]
    type_count = {}
    symbol_count = {}
    for s in running:
        type_count[s.type] = type_count.get(s.type, 0) + 1
        symbol_count[s.symbol] = symbol_count.get(s.symbol, 0) + 1
        lines.append(f'- #{s.id} {s.name} ({s.type}, {s.symbol} {s.timeframe})')
    lines.append('\n## 類型分布')
    for t, c in sorted(type_count.items(), key=lambda kv: -kv[1]):
        lines.append(f'- {t}: {c}')
    lines.append('\n## 幣種分布')
    for sym, c in sorted(symbol_count.items(), key=lambda kv: -kv[1]):
        lines.append(f'- {sym}: {c}')

    lines.append(f'\n## 開倉中持倉 ({len(open_positions)} 個)')
    for p in open_positions:
        lines.append(f'- 策略#{p.strategy_id} {p.symbol} {p.side} size={p.size} entry={p.entry_price} upl={p.unrealized_pnl}')

    lines.append(f'\n## 最近 7 日')
    lines.append(f'- {recent_trades} 筆 trades, 累積 PnL ${recent_pnl:+.2f}')

    sig = json.dumps([
        round(account_info.get('balance', 0), 0),
        len(running), sorted(type_count.items()), sorted(symbol_count.items()),
    ], default=str)
    cache_key = 'padvice:' + hashlib.sha256(sig.encode()).hexdigest()[:24]

    return call_llm(
        user_id=user_id,
        prompt='\n'.join(lines),
        system=SYSTEM_PROMPT,
        max_tokens=1200,
        cache_key=cache_key,
    )
