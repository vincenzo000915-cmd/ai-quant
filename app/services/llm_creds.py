"""Phase 11.5.1: per-user BYO LLM API key 加密儲存

沿用 11.2 的 OKX_CREDS_FERNET_KEY（同一把 key 加密所有敏感字段；
若未來想分離，再生第二把 LLM_CREDS_FERNET_KEY 切換）。

公開介面：
- save_for_user(user_id, provider, api_key, default_model=None, priority=100) -> LlmCredentials
- get_for_user(user_id, provider) -> LlmCredentials | None
- list_for_user(user_id, only_active=True) -> list[LlmCredentials] (按 priority 排序)
- get_decrypted(user_id, provider) -> str | None  (拿明文 key)
- delete_for_user(user_id, provider) -> bool
- set_active(user_id, provider, is_active) -> LlmCredentials | None
- verify(user_id, provider) -> dict  (調 provider /models 端點驗 key)
- record_usage(user_id, provider, input_tokens, output_tokens) — 統計用
"""
from __future__ import annotations

import datetime

from app.extensions import db
from app.models import LlmCredentials
from app.services.okx_creds import encrypt, decrypt   # 重用同一個 Fernet key

VALID_PROVIDERS = {'anthropic', 'openai', 'gemini'}


def _normalize_provider(p: str) -> str:
    p = (p or '').strip().lower()
    if p not in VALID_PROVIDERS:
        raise ValueError(f'provider 必須是 {VALID_PROVIDERS} 之一')
    return p


def save_for_user(user_id: int, provider: str, api_key: str,
                  default_model: str | None = None, priority: int = 100) -> LlmCredentials:
    p = _normalize_provider(provider)
    if not api_key:
        raise ValueError('api_key 必填')
    rec = LlmCredentials.query.filter_by(user_id=user_id, provider=p).first()
    if rec is None:
        rec = LlmCredentials(user_id=user_id, provider=p, is_active=True)
        db.session.add(rec)
    rec.encrypted_api_key = encrypt(api_key.strip())
    rec.default_model = default_model
    rec.priority = priority
    rec.verified_at = None
    rec.last_error = None
    rec.updated_at = datetime.datetime.utcnow()
    db.session.commit()
    return rec


def get_for_user(user_id: int, provider: str) -> LlmCredentials | None:
    return LlmCredentials.query.filter_by(user_id=user_id, provider=_normalize_provider(provider)).first()


def list_for_user(user_id: int, only_active: bool = True) -> list[LlmCredentials]:
    q = LlmCredentials.query.filter_by(user_id=user_id)
    if only_active:
        q = q.filter_by(is_active=True)
    return q.order_by(LlmCredentials.priority.asc(), LlmCredentials.id.asc()).all()


def get_decrypted(user_id: int, provider: str) -> str | None:
    rec = get_for_user(user_id, provider)
    if rec is None or not rec.is_active:
        return None
    try:
        return decrypt(rec.encrypted_api_key)
    except Exception:
        return None


def delete_for_user(user_id: int, provider: str) -> bool:
    rec = get_for_user(user_id, provider)
    if rec is None:
        return False
    db.session.delete(rec)
    db.session.commit()
    return True


def set_active(user_id: int, provider: str, is_active: bool) -> LlmCredentials | None:
    rec = get_for_user(user_id, provider)
    if rec is None:
        return None
    rec.is_active = is_active
    db.session.commit()
    return rec


def set_priority(user_id: int, provider: str, priority: int) -> LlmCredentials | None:
    rec = get_for_user(user_id, provider)
    if rec is None:
        return None
    rec.priority = priority
    db.session.commit()
    return rec


def record_usage(user_id: int, provider: str, input_tokens: int, output_tokens: int) -> None:
    """fire-and-forget 統計，失敗 silent"""
    try:
        rec = get_for_user(user_id, provider)
        if rec is None:
            return
        today = datetime.date.today()
        # 月度重設
        if rec.monthly_reset_at is None or rec.monthly_reset_at.month != today.month:
            rec.monthly_input_tokens = 0
            rec.monthly_output_tokens = 0
            rec.monthly_reset_at = today
        rec.monthly_input_tokens = (rec.monthly_input_tokens or 0) + int(input_tokens or 0)
        rec.monthly_output_tokens = (rec.monthly_output_tokens or 0) + int(output_tokens or 0)
        db.session.commit()
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        print(f'[llm_creds] record_usage failed: {type(e).__name__}: {e}')


def verify(user_id: int, provider: str) -> dict:
    """調 provider 一個輕量端點驗證 key（無副作用）"""
    p = _normalize_provider(provider)
    key = get_decrypted(user_id, p)
    if not key:
        return {'ok': False, 'error': '未綁定或已停用'}

    rec = get_for_user(user_id, p)
    try:
        if p == 'anthropic':
            import anthropic
            client = anthropic.Anthropic(api_key=key)
            # 最便宜的 ping：messages create with max_tokens=1, model haiku
            resp = client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=1,
                messages=[{'role': 'user', 'content': 'hi'}],
            )
            rec.verified_at = datetime.datetime.utcnow()
            rec.last_error = None
            db.session.commit()
            return {'ok': True, 'provider': p, 'model_pinged': resp.model, 'verified_at': rec.verified_at.isoformat()}
        elif p == 'openai':
            # 不引入 openai SDK；用 requests 打 /v1/models
            import urllib.request
            req = urllib.request.Request(
                'https://api.openai.com/v1/models',
                headers={'Authorization': f'Bearer {key}'},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                if r.status != 200:
                    raise RuntimeError(f'HTTP {r.status}')
            rec.verified_at = datetime.datetime.utcnow()
            rec.last_error = None
            db.session.commit()
            return {'ok': True, 'provider': p, 'verified_at': rec.verified_at.isoformat()}
        elif p == 'gemini':
            import urllib.request
            url = f'https://generativelanguage.googleapis.com/v1beta/models?key={key}'
            with urllib.request.urlopen(url, timeout=10) as r:
                if r.status != 200:
                    raise RuntimeError(f'HTTP {r.status}')
            rec.verified_at = datetime.datetime.utcnow()
            rec.last_error = None
            db.session.commit()
            return {'ok': True, 'provider': p, 'verified_at': rec.verified_at.isoformat()}
        else:
            return {'ok': False, 'error': f'unknown provider {p}'}
    except Exception as e:
        err = f'{type(e).__name__}: {e}'
        rec.last_error = err
        db.session.commit()
        return {'ok': False, 'error': err}
