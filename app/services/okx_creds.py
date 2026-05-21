"""Phase 11.2: per-user OKX API key 加密儲存 + 取用

設計：
- Fernet AES-128-CBC + HMAC-SHA256（cryptography 套件實作）
- key 來自 env OKX_CREDS_FERNET_KEY（44 字 base64）
- 加解密發生在 web / Celery process 內存，不寫 log / 不落磁碟
- 永遠不返回明文，除非 caller 顯式 get_decrypted_for_user()

公開介面：
- save_for_user(user_id, api_key, secret, passphrase) -> OkxCredentials
- get_for_user(user_id) -> OkxCredentials | None
- get_decrypted_for_user(user_id) -> dict {api_key/secret/passphrase} | None
- delete_for_user(user_id) -> bool
- verify_against_okx(user_id) -> {ok, balance/error}
- try_decrypt(blob) -> str | None  (for masked display)
"""
from __future__ import annotations

import datetime
import os

from cryptography.fernet import Fernet, InvalidToken

from app.extensions import db
from app.models import OkxCredentials


def _fernet() -> Fernet:
    key = os.environ.get('OKX_CREDS_FERNET_KEY')
    if not key:
        raise RuntimeError(
            'OKX_CREDS_FERNET_KEY 未設定 — Phase 11.2 加密 key 缺失，'
            '生成方法：python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 然後寫進 .env'
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode('utf-8')).decode('utf-8')


def decrypt(blob: str) -> str:
    return _fernet().decrypt(blob.encode('utf-8') if isinstance(blob, str) else blob).decode('utf-8')


def try_decrypt(blob: str | None) -> str | None:
    if not blob:
        return None
    try:
        return decrypt(blob)
    except (InvalidToken, Exception):
        return None


def save_for_user(user_id: int, api_key: str, secret: str, passphrase: str) -> OkxCredentials:
    """新增或更新某 user 的 OKX 憑證。idempotent，會把 verified_at 重設為 NULL 等下次測試。"""
    if not (api_key and secret and passphrase):
        raise ValueError('api_key / secret / passphrase 都必填')
    rec = OkxCredentials.query.filter_by(user_id=user_id).first()
    if rec is None:
        rec = OkxCredentials(user_id=user_id, is_active=True)
        db.session.add(rec)
    rec.encrypted_api_key = encrypt(api_key.strip())
    rec.encrypted_secret = encrypt(secret.strip())
    rec.encrypted_passphrase = encrypt(passphrase.strip())
    rec.verified_at = None
    rec.last_error = None
    rec.updated_at = datetime.datetime.utcnow()
    db.session.commit()
    return rec


def get_for_user(user_id: int) -> OkxCredentials | None:
    return OkxCredentials.query.filter_by(user_id=user_id).first()


def get_decrypted_for_user(user_id: int) -> dict | None:
    """回傳明文 {api_key, secret, passphrase}；無記錄 / 解密失敗 / disabled 都回 None"""
    rec = get_for_user(user_id)
    if rec is None or not rec.is_active:
        return None
    try:
        return {
            'api_key': decrypt(rec.encrypted_api_key),
            'secret': decrypt(rec.encrypted_secret),
            'passphrase': decrypt(rec.encrypted_passphrase),
        }
    except Exception:
        return None


def delete_for_user(user_id: int) -> bool:
    rec = get_for_user(user_id)
    if rec is None:
        return False
    db.session.delete(rec)
    db.session.commit()
    return True


def set_active(user_id: int, is_active: bool) -> OkxCredentials | None:
    rec = get_for_user(user_id)
    if rec is None:
        return None
    rec.is_active = is_active
    db.session.commit()
    return rec


def verify_against_okx(user_id: int) -> dict:
    """拉 OKX /account/balance 確認 key 有效。成功更新 verified_at。

    回 {ok, error?, balance?, equity?, posMode?, acctLv?}
    """
    creds = get_decrypted_for_user(user_id)
    if creds is None:
        return {'ok': False, 'error': '尚未綁定 OKX 或已停用'}

    rec = get_for_user(user_id)
    try:
        from app.services.exchange_service import _okx_get_signed
        bal = _okx_get_signed('/api/v5/account/balance', creds['api_key'], creds['secret'], creds['passphrase'])
        cfg = _okx_get_signed('/api/v5/account/config', creds['api_key'], creds['secret'], creds['passphrase'])
    except Exception as e:
        rec.last_error = f'{type(e).__name__}: {e}'
        db.session.commit()
        return {'ok': False, 'error': rec.last_error}

    # bal 是 list[{details: [{ccy, eq, ...}], totalEq, ...}]
    total_eq = 0.0
    if bal and isinstance(bal, list) and bal[0].get('totalEq'):
        try:
            total_eq = float(bal[0].get('totalEq') or 0)
        except (TypeError, ValueError):
            pass

    rec.verified_at = datetime.datetime.utcnow()
    rec.last_error = None
    db.session.commit()

    c = (cfg[0] if cfg else {})
    return {
        'ok': True,
        'total_equity_usd': round(total_eq, 4),
        'posMode': c.get('posMode'),
        'acctLv': c.get('acctLv'),
        'verified_at': rec.verified_at.isoformat(),
    }
