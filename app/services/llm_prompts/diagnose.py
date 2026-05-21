"""Phase 11.5.8: 故障诊断 agent — 「系統怪怪的？」

按 reference_diagnostics.md 的 5 步流程拉數據，請 LLM 分析。
"""
from __future__ import annotations

import datetime
import json

from sqlalchemy import desc
from app.extensions import db
from app.models import Strategy, Position, AuditLog, SystemConfig
from app.services.llm_provider import call_llm
from app.services.user_scope import scoped_query

SYSTEM_PROMPT = """你是這個量化系統的故障診斷 agent。User 報告「系統怪怪的」
或「沒下單」之類問題。我給你健康檢查的 5 步快照數據，請按照以下流程**逐步**
給出診斷與結論：

1. **trading_mode + halt 狀態** → 系統是否被 halt？halt 原因是什麼？
2. **OKX 對賬** → 本地 open positions vs OKX positions 數量是否一致？
3. **策略狀態** → running 數量、有沒有 0 trades 太久的 → 是市場原因（無信號）還是系統卡死？
4. **Celery worker** → tasks total 是否在動？最近 task succeeded？
5. **audit log** → 最近 24h 有沒有異常事件（halt / live_order_blocked / reconcile_orphan）？

最後給出**結論**：

- 如果一切正常：說「系統正常，0 trades 是市場原因」
- 如果有 bug：列出可能根因（按可能性排序），給「下一步建議命令」

注意：
- 中文回答
- 不要說「我去執行」之類，你只負責診斷，user 自己決定動作
- 末尾加：「⚠️ 此為 AI 診斷，建議結合 audit log 人工確認後再動。」"""


def diagnose(user_id: int) -> dict:
    # 1. trading_mode + halt
    cfg = SystemConfig.query.get(1)
    mode_state = {
        'trading_mode': getattr(cfg, 'trading_mode', '?'),
        'halted': bool(getattr(cfg, 'halted', False)),
        'halt_reason': getattr(cfg, 'halt_reason', None),
    }

    # 2. OKX positions vs local（admin 才有 OKX 訪問權；其他 user 顯示「需綁 OKX」）
    okx_count = None
    okx_err = None
    if user_id == 1:
        try:
            from app.services.exchange_service import fetch_okx_positions
            okx = fetch_okx_positions()
            okx_count = len(okx)
        except Exception as e:
            okx_err = f'{type(e).__name__}: {e}'

    local_open = scoped_query(Position).filter_by(status='open').count()

    # 3. 策略狀態
    running = scoped_query(Strategy).filter_by(status='running').all()
    running_count = len(running)

    # 4. Celery stats（直接 inspect 太慢，省略 — 看 audit）

    # 5. audit log 最近 24h
    since = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
    audits = scoped_query(AuditLog).filter(
        AuditLog.created_at >= since,
        AuditLog.event_type.in_([
            'halt', 'unhalt', 'kill_switch', 'live_order_blocked_no_okx_key',
            'live_order_blocked_non_admin', 'reconcile_orphan',
        ])
    ).order_by(desc(AuditLog.created_at)).limit(20).all()

    lines = [
        '## Step 1: trading_mode + halt 狀態',
        json.dumps(mode_state, ensure_ascii=False, indent=2),
        '',
        '## Step 2: 持倉對賬',
        f'本地 open positions: {local_open}',
        f'OKX SWAP positions: {okx_count if okx_count is not None else f"(無法取得: {okx_err})"}',
        '',
        '## Step 3: 策略狀態',
        f'running 策略數: {running_count}',
    ]
    for s in running[:15]:
        lines.append(f'- #{s.id} {s.name} ({s.type}, {s.symbol} {s.timeframe})')

    lines.append('\n## Step 4: 最近 24h audit 異常事件')
    if audits:
        for a in audits:
            lines.append(f'- {a.created_at.isoformat()} {a.event_type} actor={a.actor} ctx={json.dumps(a.context or {}, ensure_ascii=False)[:200]}')
    else:
        lines.append('- 無異常事件')

    return call_llm(
        user_id=user_id,
        prompt='\n'.join(lines),
        system=SYSTEM_PROMPT,
        max_tokens=2000,
        # 不 cache — 每次診斷拉新鮮數據
    )
