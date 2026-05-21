"""Phase 8.1 + 11.1: 雙軌鉴权 — System Bearer token (admin) ∥ User JWT (per-user)

- System token：env `API_AUTH_TOKEN`，給 Celery / cron / 管理員 script 用。視同 admin。
- User JWT：Phase 11.1 新增，flask-jwt-extended 簽發，subject = user.id。

設計：
- 兩者共用 `Authorization: Bearer <x>` header
- auth_guard 先試 system token；不匹配再當 JWT 解析
- 解析後寫入 g.current_user / g.is_system / g.current_user_id
- mutating endpoint 缺鉴权 → 401；GET 仍放行（11.1.3 才一個個鎖到 user scope）
- 公開白名單：/health、/api/auth/*、static
"""
from __future__ import annotations

import hmac
import os
from flask import g, jsonify, request

_EXEMPT_PATHS = {
    '/api/auth/check',
    '/api/auth/login',
    '/api/auth/register',
    '/api/auth/me',
    '/health',
}


def _expected_token() -> str | None:
    return os.environ.get('API_AUTH_TOKEN') or None


def is_auth_required(method: str, path: str) -> bool:
    """是否需要鉴权 — POST/PUT/DELETE/PATCH 才擋；豁免 path 直接放行"""
    if method.upper() not in ('POST', 'PUT', 'DELETE', 'PATCH'):
        return False
    if path in _EXEMPT_PATHS:
        return False
    return True


def _try_system_token(given: str) -> bool:
    expected = _expected_token()
    if not expected or not given:
        return False
    return hmac.compare_digest(given, expected)


def _try_user_jwt() -> bool:
    """嘗試用 JWT 解析當前 user。失敗回 False（不寫 g）。成功時設 g.current_user 等。"""
    # 延遲 import 避免循環依賴（auth.py 在 __init__.py 早期載入）
    try:
        from app.services.auth_user import resolve_user_from_jwt
    except Exception:
        return False
    user = resolve_user_from_jwt()
    if not user:
        return False
    g.current_user = user
    g.current_user_id = user.id
    g.is_system = False
    return True


def auth_guard():
    """Flask before_request hook — 雙軌鉴权 + g 注入

    無論 path / method，都嘗試解析 actor（讓 GET endpoint 也能拿到 current_user）。
    僅在 mutating + 非豁免 + 未通過任何鉴权 時 401。
    """
    # 預設值
    g.current_user = None
    g.current_user_id = None
    g.is_system = False

    # 抽 Bearer
    auth = request.headers.get('Authorization', '')
    given = auth[len('Bearer '):].strip() if auth.startswith('Bearer ') else ''

    if given:
        # 先試 system token（比 hmac，快）
        if _try_system_token(given):
            g.is_system = True
            return None
        # 再試 user JWT
        if _try_user_jwt():
            return None

    # 豁免 path 直接放行
    if request.path in _EXEMPT_PATHS:
        return None

    # 非 mutating 全放行（GET 不需要 token 即可訪問）
    if not is_auth_required(request.method, request.path):
        return None

    # mutating + 無有效鉴权 → 401
    detail = 'invalid token' if given else 'missing Bearer token'
    if not _expected_token() and not given:
        # dev 模式：未設 API_AUTH_TOKEN 且也無 user JWT → 放行（向後兼容）
        return None
    return jsonify({'error': 'unauthorized', 'detail': detail}), 401


def check_token() -> tuple[bool, str | None]:
    """legacy 介面 — 保留給可能還在引用的舊代碼用。建議遷移到 auth_guard 後從 g 取狀態。"""
    expected = _expected_token()
    if not expected:
        return True, 'auth disabled (no API_AUTH_TOKEN in env)'
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return False, 'missing Bearer token'
    given = auth[len('Bearer '):].strip()
    if hmac.compare_digest(given, expected):
        return True, None
    return False, 'invalid token'
