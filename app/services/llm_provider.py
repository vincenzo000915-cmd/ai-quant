"""Phase 11.5.2: model-agnostic LLM adapter

統一接口讓 Claude / GPT / Gemini 同樣調用方式：

    from app.services.llm_provider import call_llm
    r = call_llm(
        user_id=42,
        prompt='解釋這個策略...',
        system='你是專業量化分析師',
        max_tokens=2048,
    )
    # r = {ok, text, model_used, provider_used, usage: {input_tokens, output_tokens},
    #       latency_ms, error?}

Fallback 順序：按 user 綁的 provider priority（小優先）依序試。前一個 rate
limit / API error → 自動換下一個。所有 active provider 都失敗 → 返回最後一個錯誤。

支援 cache_key — 重複輸入直接返回快取（30 分鐘）；用 redis 已有的 cache 模塊。

每次成功 call 後寫 monthly_input_tokens / monthly_output_tokens（給 user 看用量）。
"""
from __future__ import annotations

import json
import time

from app.services.llm_creds import (
    list_for_user,
    get_decrypted,
    record_usage,
)


# 預設模型（user 沒設 default_model 時用）
DEFAULT_MODELS = {
    'anthropic': 'claude-sonnet-4-6',
    'openai': 'gpt-4o-mini',
    'gemini': 'gemini-2.0-flash',
}

# Provider 不支援 rate-limit fallback 的錯誤（永久性 — 直接 raise，不重試下個）
PERMANENT_ERROR_KEYWORDS = {
    'invalid_api_key', 'invalid x-api-key', 'authentication_error',
    'forbidden', 'permission_denied',
}


class LlmError(Exception):
    pass


def _is_permanent_error(err_str: str) -> bool:
    low = (err_str or '').lower()
    return any(kw in low for kw in PERMANENT_ERROR_KEYWORDS)


# ===== Anthropic =====

def _call_anthropic(api_key: str, prompt: str, system: str | None,
                    max_tokens: int, model: str) -> dict:
    try:
        from anthropic import Anthropic
    except ImportError as e:
        raise LlmError(f'anthropic SDK 未安裝: {e}')

    client = Anthropic(api_key=api_key)
    messages = [{'role': 'user', 'content': prompt}]
    kwargs = {'model': model, 'max_tokens': max_tokens, 'messages': messages}
    if system:
        kwargs['system'] = system
    resp = client.messages.create(**kwargs)
    # resp.content 是 list[ContentBlock]，TextBlock 有 .text
    text = ''
    for block in resp.content:
        if getattr(block, 'type', '') == 'text':
            text += block.text
    return {
        'text': text,
        'model_used': resp.model,
        'usage': {
            'input_tokens': resp.usage.input_tokens,
            'output_tokens': resp.usage.output_tokens,
        },
    }


# ===== OpenAI =====

def _call_openai(api_key: str, prompt: str, system: str | None,
                 max_tokens: int, model: str) -> dict:
    import urllib.request

    body = {
        'model': model,
        'messages': (
            ([{'role': 'system', 'content': system}] if system else []) +
            [{'role': 'user', 'content': prompt}]
        ),
        'max_tokens': max_tokens,
    }
    req = urllib.request.Request(
        'https://api.openai.com/v1/chat/completions',
        method='POST',
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        data=json.dumps(body).encode('utf-8'),
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode('utf-8'))
    choice = (data.get('choices') or [{}])[0]
    text = (choice.get('message') or {}).get('content', '')
    usage = data.get('usage') or {}
    return {
        'text': text,
        'model_used': data.get('model', model),
        'usage': {
            'input_tokens': usage.get('prompt_tokens', 0),
            'output_tokens': usage.get('completion_tokens', 0),
        },
    }


# ===== Gemini =====

def _call_gemini(api_key: str, prompt: str, system: str | None,
                 max_tokens: int, model: str) -> dict:
    import urllib.request

    body = {
        'contents': [{
            'role': 'user',
            'parts': [{'text': prompt}],
        }],
        'generationConfig': {'maxOutputTokens': max_tokens},
    }
    if system:
        body['systemInstruction'] = {'parts': [{'text': system}]}
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}'
    req = urllib.request.Request(
        url, method='POST',
        headers={'Content-Type': 'application/json'},
        data=json.dumps(body).encode('utf-8'),
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode('utf-8'))
    cands = data.get('candidates') or []
    text = ''
    if cands:
        parts = (cands[0].get('content') or {}).get('parts') or []
        text = ''.join(p.get('text', '') for p in parts)
    usage = data.get('usageMetadata') or {}
    return {
        'text': text,
        'model_used': model,
        'usage': {
            'input_tokens': usage.get('promptTokenCount', 0),
            'output_tokens': usage.get('candidatesTokenCount', 0),
        },
    }


_DISPATCH = {
    'anthropic': _call_anthropic,
    'openai': _call_openai,
    'gemini': _call_gemini,
}


def call_llm(
    user_id: int,
    prompt: str,
    system: str | None = None,
    max_tokens: int = 2048,
    provider_pref: str | None = None,
    cache_key: str | None = None,
) -> dict:
    """主入口 — 自動選 user 綁的 provider 依 priority 嘗試。

    回 {ok, text, model_used, provider_used, usage, latency_ms, error?}
    """
    # cache_key 命中 → 直接回
    if cache_key:
        try:
            from app.services.cache import cache_get
            cached = cache_get(cache_key)
            if cached:
                return {**cached, 'cached': True}
        except Exception:
            pass

    providers = list_for_user(user_id, only_active=True)
    if not providers:
        return {'ok': False, 'error': '尚未綁定任何 LLM provider（去 設定 頁綁定）',
                'text': '', 'provider_used': None}

    # provider_pref 指定 → 把它移到隊頭
    if provider_pref:
        providers = sorted(providers,
                           key=lambda p: (0 if p.provider == provider_pref else 1, p.priority, p.id))

    last_error = None
    for rec in providers:
        api_key = get_decrypted(user_id, rec.provider)
        if not api_key:
            last_error = f'{rec.provider}: decrypt failed'
            continue
        model = rec.default_model or DEFAULT_MODELS.get(rec.provider)
        fn = _DISPATCH.get(rec.provider)
        if not fn:
            last_error = f'{rec.provider}: dispatch missing'
            continue
        t0 = time.time()
        try:
            res = fn(api_key, prompt, system, max_tokens, model)
            latency_ms = int((time.time() - t0) * 1000)
            # 寫用量
            try:
                record_usage(user_id, rec.provider,
                             res['usage'].get('input_tokens', 0),
                             res['usage'].get('output_tokens', 0))
            except Exception:
                pass
            result = {
                'ok': True,
                'text': res['text'],
                'model_used': res['model_used'],
                'provider_used': rec.provider,
                'usage': res['usage'],
                'latency_ms': latency_ms,
                'cached': False,
            }
            # 寫 cache
            if cache_key:
                try:
                    from app.services.cache import cache_set
                    cache_set(cache_key, result, ttl=1800)   # 30 分鐘
                except Exception:
                    pass
            return result
        except Exception as e:
            err = f'{type(e).__name__}: {e}'
            last_error = f'{rec.provider}: {err}'
            print(f'[llm] {last_error}')
            if _is_permanent_error(err):
                # 永久錯不 fallback 到下個（key 是壞的，不是 rate limit）
                break

    return {'ok': False, 'error': last_error or '所有 provider 都失敗',
            'text': '', 'provider_used': None}
