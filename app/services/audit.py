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

    Phase 14k-103: 加 retry — 长 CPU 任务 (walkforward) 后 session connection 可能 dead
    (pool_pre_ping 只在 checkout 检查, mid-session idle 不验)
    OperationalError 'server closed' 时 invalidate + retry 一次
    audit 是 fire-and-forget, 失败业务不阻塞, 但能避免就避免漏 audit
    """
    ip = None
    uid = user_id
    if has_request_context():
        ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        if uid is None:
            uid = getattr(g, 'current_user_id', None)
    ctx = dict(context or {})

    for attempt in range(2):
        try:
            # 預檢 user_id (FK 防撞)
            uid_for_insert = uid
            if uid_for_insert is not None:
                from app.models import User
                if not User.query.get(uid_for_insert):
                    ctx['original_user_id'] = uid_for_insert
                    uid_for_insert = None
            entry = AuditLog(
                event_type=event_type,
                actor=actor,
                user_id=uid_for_insert,
                context=ctx,
                ip=ip,
            )
            db.session.add(entry)
            db.session.commit()
            return
        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass
            err_str = str(e)
            is_conn_dead = ('server closed' in err_str or 'connection' in err_str.lower())
            if attempt == 0 and is_conn_dead:
                # 14k-103: 强制 invalidate stale connection, 让下次 query 拿 fresh
                try:
                    db.session.close()
                    # invalidate 让 pool 把这个 connection 当死的丢掉
                    if hasattr(db.session, 'invalidate'):
                        db.session.invalidate()
                except Exception:
                    pass
                continue
            print(f'[audit] log({event_type}) failed: {type(e).__name__}: {e}')
            return
