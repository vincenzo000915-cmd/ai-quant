"""Phase 14k: per-user Hyperliquid agent wallet 加密存储 + 取用

設計:
- Fernet AES-128-CBC + HMAC-SHA256 (cryptography), 复用 OKX_CREDS_FERNET_KEY
- 加解密發生在 web / Celery process 內存, 不寫 log / 不落磁盤
- agent private key 是 user 在 Hyperliquid 网站派生的 trade-only 钱包私钥
  HL 平台 enforce: agent 只能下单, 无法 transfer/withdraw

公開介面:
- save_for_user(user_id, agent_address, main_address, agent_private_key, network) -> HyperliquidCredentials
- get_for_user(user_id) -> HyperliquidCredentials | None
- get_decrypted_for_user(user_id) -> dict | None  # {agent_address, main_address, agent_private_key, network}
- delete_for_user(user_id) -> bool
- verify_against_hl(user_id) -> {ok, balance/error}
"""
from __future__ import annotations

import datetime
import os
import re

from cryptography.fernet import Fernet, InvalidToken

from app.extensions import db
from app.models import HyperliquidCredentials


def _fernet() -> Fernet:
    # 复用 OKX_CREDS_FERNET_KEY (同 SaaS, 一套加密 key 管所有 user 凭据)
    key = os.environ.get('OKX_CREDS_FERNET_KEY')
    if not key:
        raise RuntimeError(
            'OKX_CREDS_FERNET_KEY 未設定 — 复用此 key 加密 HL agent private key'
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def _encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode('utf-8')).decode('utf-8')


def _decrypt(blob: str) -> str:
    return _fernet().decrypt(blob.encode('utf-8') if isinstance(blob, str) else blob).decode('utf-8')


_ADDR_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')
_PRIVKEY_RE = re.compile(r'^(0x)?[0-9a-fA-F]{64}$')


def _normalize_privkey(pk: str) -> str:
    """Strip '0x' prefix if present, lowercase. Returns 64 hex chars."""
    pk = pk.strip()
    if pk.startswith('0x') or pk.startswith('0X'):
        pk = pk[2:]
    return pk.lower()


def save_for_user(user_id: int, agent_address: str, main_address: str,
                  agent_private_key: str, network: str = 'mainnet',
                  agent_expires_at: datetime.datetime | None = None) -> HyperliquidCredentials:
    """新增或更新某 user 的 HL agent 凭据. idempotent.

    Phase 14k-8: agent_expires_at 动态从 HL info extraAgents 读 actual validUntil.
    - 调 HL 找 main_address 下匹配 agent_address 的 entry, 用真实 validUntil
    - 找不到 agent (未授权 HL) → raise ValueError 强制 user 先去 HL Authorize
    - HL API 失败 → fallback 180 天默认值
    """
    if not _ADDR_RE.match(agent_address.strip()):
        raise ValueError(f'agent_address 不是合法 0x 地址: {agent_address}')
    if not _ADDR_RE.match(main_address.strip()):
        raise ValueError(f'main_address 不是合法 0x 地址: {main_address}')
    if not _PRIVKEY_RE.match(agent_private_key.strip()):
        raise ValueError('agent_private_key 必须是 64 hex (可带 0x 前缀)')
    if network not in ('mainnet', 'testnet'):
        raise ValueError(f'network 必须 mainnet 或 testnet, got: {network}')

    # 14k-8: 从 HL 查 agent 是否真授权 + 真 validUntil
    if agent_expires_at is None:
        try:
            from app.services.hyperliquid_service import fetch_agent_validity
            info = fetch_agent_validity(main_address.strip(), agent_address.strip(), network)
            if info is None:
                # 没在 HL extraAgents 列表里找到 → 未授权或地址不对
                raise ValueError(
                    f'HL 上没找到 agent {agent_address[:10]}… 授权给 main {main_address[:10]}…. '
                    f'去 hyperliquid.xyz/API 检查: 1) main wallet 是否对的 2) agent address 是否已 Authorize/Generate'
                )
            if info.get('valid_until_dt'):
                agent_expires_at = info['valid_until_dt']
        except ValueError:
            raise
        except Exception as e:
            # HL info API 失败 — fallback 180d 默认
            print(f'[hl_creds] fetch_agent_validity failed, fallback 180d: {e}')

    rec = HyperliquidCredentials.query.filter_by(user_id=user_id).first()
    if rec is None:
        rec = HyperliquidCredentials(user_id=user_id, is_active=True)
        db.session.add(rec)
    rec.agent_address = agent_address.strip().lower()
    rec.main_address = main_address.strip().lower()
    rec.encrypted_agent_private_key = _encrypt(_normalize_privkey(agent_private_key))
    rec.network = network
    rec.agent_expires_at = agent_expires_at or (datetime.datetime.utcnow() + datetime.timedelta(days=180))
    rec.expiry_warned_at = None    # 重新绑定 → 清除警告记录
    rec.verified_at = None
    rec.last_error = None
    rec.updated_at = datetime.datetime.utcnow()
    db.session.commit()
    return rec


def is_expired(user_id: int) -> bool:
    """检查 user HL agent 是否已过期."""
    rec = get_for_user(user_id)
    if not rec or not rec.agent_expires_at:
        return False
    return rec.agent_expires_at <= datetime.datetime.utcnow()


def days_until_expiry(user_id: int) -> int | None:
    """返回距过期天数. None = 未绑."""
    rec = get_for_user(user_id)
    if not rec or not rec.agent_expires_at:
        return None
    delta = (rec.agent_expires_at - datetime.datetime.utcnow()).total_seconds()
    return max(0, int(delta // 86400))


def get_for_user(user_id: int) -> HyperliquidCredentials | None:
    return HyperliquidCredentials.query.filter_by(user_id=user_id).first()


def get_decrypted_for_user(user_id: int) -> dict | None:
    """回明文 {agent_address, main_address, agent_private_key, network}.
    None 若无记录 / 解密失败 / disabled."""
    rec = get_for_user(user_id)
    if rec is None or not rec.is_active:
        return None
    try:
        return {
            'agent_address': rec.agent_address,
            'main_address': rec.main_address,
            'agent_private_key': _decrypt(rec.encrypted_agent_private_key),
            'network': rec.network or 'mainnet',
        }
    except (InvalidToken, Exception):
        return None


def delete_for_user(user_id: int) -> bool:
    rec = get_for_user(user_id)
    if rec is None:
        return False
    db.session.delete(rec)
    db.session.commit()
    return True


def set_active(user_id: int, is_active: bool) -> HyperliquidCredentials | None:
    rec = get_for_user(user_id)
    if rec is None:
        return None
    rec.is_active = is_active
    rec.updated_at = datetime.datetime.utcnow()
    db.session.commit()
    return rec


def verify_against_hl(user_id: int) -> dict:
    """调 HL info endpoint 验证 main_address 有效 + 返回 balance."""
    from app.services.hyperliquid_service import fetch_balance
    rec = get_for_user(user_id)
    if rec is None:
        return {'ok': False, 'error': '未绑定 HL agent'}
    try:
        creds = get_decrypted_for_user(user_id)
        bal = fetch_balance(creds=creds)
        rec.verified_at = datetime.datetime.utcnow()
        rec.last_error = None
        db.session.commit()
        return {'ok': True, 'balance': bal}
    except Exception as e:
        rec.last_error = f'{type(e).__name__}: {e}'[:300]
        db.session.commit()
        return {'ok': False, 'error': rec.last_error}
