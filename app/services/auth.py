"""Phase 8.1: 簡單 Bearer token 鉴权 — 防止 mutating endpoint 被公網誤觸

設計考量：
- 單一 token（API_AUTH_TOKEN env var）共享 — 等 Phase 11.1 SaaS 化才搞多用户
- 只擋 POST/PUT/DELETE/PATCH；GET 全開（dashboard 顯示無需登入）
- 額外白名單：/health、/api/auth/* 自身、static assets
"""
from __future__ import annotations

import hmac
import os
from flask import request, jsonify

# 不要求 token 的 PATH（即使是 POST 也放行）
_EXEMPT_PATHS = {
    '/api/auth/check',     # 給前端驗 token 用
    '/api/auth/login',     # 留位給 Phase 11
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


def check_token() -> tuple[bool, str | None]:
    """從 Authorization header 抽 token 並比對。回傳 (ok, reason)"""
    expected = _expected_token()
    if not expected:
        # 未設定 token = 不啟用鉴权（dev 模式）。生產務必設。
        return True, 'auth disabled (no API_AUTH_TOKEN in env)'

    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return False, 'missing Bearer token'
    given = auth[len('Bearer '):].strip()
    if hmac.compare_digest(given, expected):
        return True, None
    return False, 'invalid token'


def auth_guard():
    """Flask before_request hook"""
    if not is_auth_required(request.method, request.path):
        return None
    ok, reason = check_token()
    if not ok:
        return jsonify({'error': 'unauthorized', 'detail': reason}), 401
    return None
