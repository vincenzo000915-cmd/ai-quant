"""Phase 8.4: audit_log helper

簡單 fire-and-forget log helper。任何 mutating event 都 log() 一條。
失敗 silent — 不要因為 log 不出去而阻擋業務動作。
"""
from __future__ import annotations

from flask import request, has_request_context
from app.extensions import db
from app.models import AuditLog


def log(event_type: str, actor: str = 'system', **context):
    """寫一筆 audit。可帶任意 keyword args 進 context dict。"""
    try:
        ip = None
        if has_request_context():
            ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        entry = AuditLog(
            event_type=event_type,
            actor=actor,
            context=context or {},
            ip=ip,
        )
        db.session.add(entry)
        db.session.commit()
    except Exception as e:
        # log 失敗不該影響業務流程
        try:
            db.session.rollback()
        except Exception:
            pass
        print(f'[audit] log({event_type}) failed: {type(e).__name__}: {e}')
