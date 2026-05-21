"""Phase 11.1.3: User-scope helpers — 給 routes / 服務 統一過濾規則

設計：
- admin actor (system token 或 user.role='admin') → 看所有 user 數據
- 一般 user → 只能看 / 改 自己的 (user_id = g.current_user_id)
- system actor 在 Celery context (沒 request g) → 看所有，不過濾

主要 API：
- require_actor(view)         decorator — 401 若無 system token / user JWT
- current_user_id() -> int|None
- is_admin_actor() -> bool
- scoped_query(model)         回傳 user-scoped query
- get_owned(model, obj_id)    回傳該 user 能 access 的 obj，否則 None
- assign_user_id(obj)         寫入新 instance 時自動填 user_id
"""
from __future__ import annotations

from functools import wraps

from flask import g, has_request_context, jsonify


def current_user_id() -> int | None:
    """請求中當前 user.id。system actor / 無 request context → None。"""
    if not has_request_context():
        return None
    return getattr(g, 'current_user_id', None)


def has_ai_access() -> bool:
    """Phase 11.5: AI features 訪問權 — admin 或 Pro/Team tier"""
    if not has_request_context():
        return True  # Celery / system context 默認允許
    if getattr(g, 'is_system', False):
        return True
    u = getattr(g, 'current_user', None)
    if not u:
        return False
    if u.role == 'admin':
        return True
    return u.subscription_tier in ('pro', 'team')


def require_pro_tier(view):
    """Decorator: AI 功能 gate — 非 Pro/admin 回 402 Payment Required"""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not has_ai_access():
            return jsonify({
                'error': '此功能需 Pro 訂閱',
                'upgrade_hint': '到 設定 頁綁定 LLM key 並升級到 Pro 層',
            }), 402
        return view(*args, **kwargs)
    return wrapped


def is_admin_actor() -> bool:
    """system token 通過 或 user.role='admin' 都視為 admin（看所有 user 數據）。

    Celery context (無 request) 也視為 admin — task 跨 user 跑。
    """
    if not has_request_context():
        return True
    if getattr(g, 'is_system', False):
        return True
    u = getattr(g, 'current_user', None)
    return bool(u and getattr(u, 'role', '') == 'admin')


def require_actor(view):
    """Decorator: 需要 system token 或 user JWT。否則 401。

    用法：
        @api_bp.route('/positions', methods=['GET'])
        @require_actor
        def list_positions():
            ...
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not has_request_context():
            return view(*args, **kwargs)
        if getattr(g, 'is_system', False):
            return view(*args, **kwargs)
        if getattr(g, 'current_user_id', None):
            return view(*args, **kwargs)
        return jsonify({'error': '未登入'}), 401
    return wrapped


def scoped_query(model, include_null_user=False):
    """回傳對 model 的 query，自動 user-scope。

    - admin actor (system token 或 role=admin) → 不 filter (看所有)
    - 一般 user → filter_by(user_id=current_user_id)
    - include_null_user=True → admin 看所有；user 看自己 + user_id IS NULL (system resource)

    例：
        scoped_query(Strategy).all()                 # 自動過濾
        scoped_query(BacktestResult, include_null_user=True).all()  # 也看候選池 backtest
    """
    q = model.query
    if is_admin_actor():
        return q
    uid = current_user_id()
    if uid is None:
        # 沒鉴权 — 預設不返回任何東西（require_actor 應該已經擋住，這是兜底）
        return q.filter(False)
    if include_null_user:
        q = q.filter((model.user_id == uid) | (model.user_id.is_(None)))
    else:
        q = q.filter(model.user_id == uid)
    return q


def apply_user_filter(query, model, include_null_user=False):
    """給 arbitrary db.session.query(...) 套 user filter。

    用法（pnl/summary 等 SQLAlchemy func 聚合）：
        q = db.session.query(func.sum(Trade.pnl)).filter(Trade.exit_time >= since)
        q = apply_user_filter(q, Trade)
    """
    if is_admin_actor():
        return query
    uid = current_user_id()
    if uid is None:
        return query.filter(False)
    if include_null_user:
        return query.filter((model.user_id == uid) | (model.user_id.is_(None)))
    return query.filter(model.user_id == uid)


def get_owned(model, obj_id, include_null_user=False):
    """從 scoped_query 取 obj_id；無 access → None"""
    return scoped_query(model, include_null_user=include_null_user).filter(model.id == obj_id).first()


def assign_user_id(obj, prefer_user_id=None):
    """寫入 model instance 時自動填 user_id。

    優先順序：prefer_user_id (caller 指定) > current_user_id() > 1 (admin fallback)

    注意：admin 在 request context 下若沒 prefer_user_id 也用 current；
    Celery 任務(無 request) 必須由 caller 顯式傳 prefer_user_id。
    """
    if not hasattr(obj, 'user_id'):
        return obj
    if prefer_user_id is not None:
        obj.user_id = prefer_user_id
        return obj
    cur = current_user_id()
    obj.user_id = cur if cur is not None else 1
    return obj
