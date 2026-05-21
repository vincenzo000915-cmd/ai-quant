"""Phase 8.4 + 11.1.3: audit_log helper

簡單 fire-and-forget log helper。任何 mutating event 都 log() 一條。
失敗 silent — 不要因為 log 不出去而阻擋業務動作。

Phase 11.1.3: 自動帶 user_id（從 g.current_user_id；caller 可顯式覆寫 user_id=...）
"""
from __future__ import annotations

from flask import g, has_request_context, request

from app.extensions import db
from app.models import AuditLog


def log(event_type: str, actor: str = 'system', user_id: int | None = None, **context):
    """寫一筆 audit。可帶任意 keyword args 進 context dict。

    user_id 解析優先序：caller 顯式傳 > g.current_user_id > NULL（system context 沒 request）
    若 user_id 對應 user 不存在（被刪 / 偽造）→ FK 衝突時 fallback user_id=NULL 並把原值塞 context。
    """
    try:
        ip = None
        uid = user_id
        if has_request_context():
            ip = request.headers.get('X-Forwarded-For', request.remote_addr)
            if uid is None:
                uid = getattr(g, 'current_user_id', None)
        ctx = dict(context or {})
        # 預檢 user_id 存在（避免每次 INSERT 撞 FK 才回滾）
        if uid is not None:
            from app.models import User
            if not User.query.get(uid):
                ctx['original_user_id'] = uid
                uid = None
        entry = AuditLog(
            event_type=event_type,
            actor=actor,
            user_id=uid,
            context=ctx,
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
