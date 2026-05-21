"""Phase 11.1: User 認證 — bcrypt 密碼 + JWT 簽發/驗證 + g.current_user resolver

雙軌鉴权設計：
- System Bearer token (env API_AUTH_TOKEN) = 管理員憑證，Celery / cron / 內部 script 用
- User JWT = 一般 user 用，subject = user.id

auth_guard 先試 system token；不對再當 JWT 解析。兩者共用 `Authorization: Bearer <x>` header。

把當前 actor 寫入 flask.g：
- g.current_user      : User | None     (system actor 時為 None)
- g.is_system         : bool            (system token 通過時 True)
- g.current_user_id   : int | None      (方便取，admin context 想 impersonate 時可加 ?user_id=N override)
"""
from __future__ import annotations

import datetime
import re

import bcrypt
from flask import g, request
from flask_jwt_extended import create_access_token, decode_token

from app.extensions import db
from app.models import User

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False


def register_user(email: str, password: str) -> tuple[bool, dict | str]:
    """註冊新 user。回傳 (ok, payload_or_error_msg)"""
    email = (email or '').strip().lower()
    if not email or not EMAIL_RE.match(email):
        return False, '邮箱格式无效'
    if not password or len(password) < 8:
        return False, '密码至少 8 字符'
    if User.query.filter_by(email=email).first():
        return False, '邮箱已注册'

    user = User(
        email=email,
        password_hash=hash_password(password),
        role='user',
        subscription_tier='free',
        is_active=True,
    )
    db.session.add(user)
    db.session.commit()

    token = create_access_token(identity=str(user.id))
    return True, {'user': user.to_dict(), 'access_token': token}


def login_user(email: str, password: str) -> tuple[bool, dict | str]:
    email = (email or '').strip().lower()
    user = User.query.filter_by(email=email).first()
    if not user or not verify_password(password, user.password_hash):
        return False, '邮箱或密码错误'
    if not user.is_active:
        return False, '账户已被停用'

    user.last_login_at = datetime.datetime.utcnow()
    db.session.commit()

    token = create_access_token(identity=str(user.id))
    return True, {'user': user.to_dict(), 'access_token': token}


def resolve_user_from_jwt() -> User | None:
    """從 Authorization header 抽 JWT 並查 user。失敗回 None（不 raise）"""
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    token = auth[len('Bearer '):].strip()
    if not token:
        return None
    try:
        payload = decode_token(token)
    except Exception:
        return None
    sub = payload.get('sub')
    if sub is None:
        return None
    try:
        uid = int(sub)
    except (TypeError, ValueError):
        return None
    return User.query.get(uid)


def current_user_id() -> int | None:
    """便利函式 — 從 g 取當前 user id。system actor 回 None。"""
    return getattr(g, 'current_user_id', None)


def is_admin() -> bool:
    """system token 或 role=admin 的 user 都視為 admin"""
    if getattr(g, 'is_system', False):
        return True
    u = getattr(g, 'current_user', None)
    return bool(u and u.role == 'admin')


def ensure_admin_user_exists(email: str, password: str | None = None) -> User:
    """確保 user_id=1 存在且是 admin（給 Phase 11.1.2 migration / 首次啟動用）

    如果 users 表完全沒記錄，建立 id=1 的 admin。若 user 已存在則不動。
    password 缺時用環境變數或隨機（之後 admin 自己重設）。
    """
    import os
    import secrets
    existing = User.query.filter_by(email=email.lower()).first()
    if existing:
        return existing
    # 也檢查 id=1 是否被佔
    if User.query.get(1):
        # id=1 已是別人 — 後面再處理，這裡直接建普通 user
        pass
    pw = password or os.environ.get('ADMIN_INITIAL_PASSWORD') or secrets.token_urlsafe(16)
    u = User(
        email=email.lower(),
        password_hash=hash_password(pw),
        role='admin',
        subscription_tier='pro',
        is_active=True,
    )
    db.session.add(u)
    db.session.flush()
    db.session.commit()
    return u
