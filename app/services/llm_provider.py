"""Phase 11.5.2 + 11.5.3.1: model-agnostic LLM adapter

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

Phase 11.5.3.1: admin (user_id=1) 預設走 'claude_cli' provider — 用 container 內
的 claude CLI + mount 的 host /root/.claude OAuth (你的 Claude Pro/Max 訂閱)，
免 API token 費。普通 user 仍 BYO API key（SaaS 賣的就是這權限）。

支援 cache_key — 重複輸入直接返回快取（30 分鐘）；用 redis 已有的 cache 模塊。

每次成功 call 後寫 monthly_input_tokens / monthly_output_tokens（給 user 看用量）。
"""
from __future__ import annotations

import json
import os
import subprocess
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
    'claude_cli': 'sonnet',   # claude CLI 的 model 名（不是 API model id）
}

ADMIN_USER_ID = 1

# Provider 不支援 rate-limit fallback 的錯誤（永久性 — 直接 raise，不重試下個）
PERMANENT_ERROR_KEYWORDS = {
    'invalid_api_key', 'invalid x-api-key', 'authentication_error',
    'forbidden', 'permission_denied',
}

# 14k-63: provider-level rate-limit backoff — 防 LLM 限额时雪崩 retry 浪费 + log noise
# 每 provider 连续 N 次 fail → 进 backoff 5 分钟, 期间 call_llm 直接返回 fail 不调 LLM
_BACKOFF_THRESHOLD = 3              # 连续 3 次 fail 触发
_BACKOFF_DURATION_SEC = 300         # 5 分钟
_PROVIDER_BACKOFF: dict[str, dict] = {}    # provider → {fail_count, backoff_until}


def _provider_in_backoff(provider: str) -> tuple[bool, float]:
    """返回 (是否 backoff 中, 剩余秒数)."""
    state = _PROVIDER_BACKOFF.get(provider)
    if not state:
        return False, 0.0
    remaining = state['backoff_until'] - time.time()
    if remaining > 0:
        return True, remaining
    # backoff 过期, reset state
    _PROVIDER_BACKOFF.pop(provider, None)
    return False, 0.0


def _record_provider_fail(provider: str):
    state = _PROVIDER_BACKOFF.setdefault(provider, {'fail_count': 0, 'backoff_until': 0.0})
    state['fail_count'] += 1
    if state['fail_count'] >= _BACKOFF_THRESHOLD:
        state['backoff_until'] = time.time() + _BACKOFF_DURATION_SEC
        print(f'[llm] {provider} 连续 {state["fail_count"]} 次 fail, '
              f'进 backoff {_BACKOFF_DURATION_SEC}s (避免雪崩 retry)')


def _record_provider_success(provider: str):
    """成功 → 清 backoff state."""
    _PROVIDER_BACKOFF.pop(provider, None)


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


# ===== Claude CLI (admin 走訂閱免費路徑) =====

CLAUDE_CLI_TIMEOUT = int(os.environ.get('CLAUDE_CLI_TIMEOUT', '300'))   # 12.17: 大 prompt 需要 5min


def _call_claude_cli(api_key: str | None, prompt: str, system: str | None,
                     max_tokens: int, model: str,
                     allowed_tools: list[str] | None = None,
                     timeout: int | None = None) -> dict:
    """Phase 11.5.3.1: 用 container 內 claude CLI + host mount 的 ~/.claude OAuth。

    不需要 api_key（OAuth 在 mount 的配置裡）；max_tokens 也 claude CLI 不直接控制
    （由訂閱方使用 fairness 限），但 prompt 可以引導長度。

    用 --print 非互動模式 + --output-format json 拿結構化結果（含 model/usage）。

    Phase 12.41: allowed_tools 让 LLM 可主动联网（e.g. ['WebSearch', 'WebFetch']）。
    """
    args = ['claude', '--print', '--output-format', 'json', '--permission-mode', 'default']
    if model:
        args.extend(['--model', model])
    if allowed_tools:
        # claude_cli 接受 --allowedTools "Tool1 Tool2 ..."（空格分隔）
        args.extend(['--allowedTools', ' '.join(allowed_tools)])
    if system:
        args.extend(['--append-system-prompt', system])
    proc = subprocess.run(
        args,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout if timeout is not None else CLAUDE_CLI_TIMEOUT,
    )
    if proc.returncode != 0:
        raise RuntimeError(f'claude CLI exited {proc.returncode}: {(proc.stderr or "").strip()[:300]}')
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        # 退而求其次：把整個 stdout 當 text 回
        return {'text': proc.stdout.strip(), 'model_used': model or 'claude-cli', 'usage': {'input_tokens': 0, 'output_tokens': 0}}
    text = data.get('result') or data.get('response') or ''
    usage = data.get('usage') or {}
    return {
        'text': text,
        'model_used': data.get('model', model or 'claude-cli'),
        'usage': {
            'input_tokens': usage.get('input_tokens', 0),
            'output_tokens': usage.get('output_tokens', 0),
        },
    }


_DISPATCH = {
    'anthropic': _call_anthropic,
    'openai': _call_openai,
    'gemini': _call_gemini,
    'claude_cli': _call_claude_cli,
}


def call_llm(
    user_id: int,
    prompt: str,
    system: str | None = None,
    max_tokens: int = 2048,
    provider_pref: str | None = None,
    cache_key: str | None = None,
    allowed_tools: list[str] | None = None,
    timeout: int | None = None,
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

    # Phase 11.5.3.1: 構建嘗試清單 — admin 預設 claude_cli (免費)，其他 user BYO API
    attempts: list[tuple[str, str | None, str]] = []   # (provider, api_key_or_None, model)

    user_providers = list_for_user(user_id, only_active=True)
    # 14k-75: LLM call 前显式提交/释放 DB transaction
    # 防 SQLAlchemy implicit transaction 把 SELECT 锁住 → LLM call 长跑 → idle in transaction 占满 pool
    # 实测 1:36 worker hang 因 7 idle in transaction 占满 SQLAlchemy 默认 5 pool
    try:
        from app.extensions import db as _db
        _db.session.commit()   # 释放 SELECT 后的隐式事务
    except Exception:
        try:
            from app.extensions import db as _db
            _db.session.rollback()
        except Exception:
            pass
    if user_id == ADMIN_USER_ID and not user_providers:
        # admin 沒綁任何 API → 走 claude_cli (host /root/.claude OAuth via 訂閱)
        attempts.append(('claude_cli', None, DEFAULT_MODELS['claude_cli']))
    else:
        for rec in user_providers:
            api_key = get_decrypted(user_id, rec.provider)
            if not api_key:
                continue
            attempts.append((rec.provider, api_key, rec.default_model or DEFAULT_MODELS.get(rec.provider)))

    # provider_pref 指定 → 把它移到隊頭
    if provider_pref:
        attempts = sorted(attempts, key=lambda a: 0 if a[0] == provider_pref else 1)

    if not attempts:
        if user_id == ADMIN_USER_ID:
            err = 'claude CLI 不可用（檢查 /root/.claude mount 與容器內 claude binary）'
        else:
            err = '尚未綁定任何 LLM provider（去 設定 頁綁定）'
        return {'ok': False, 'error': err, 'text': '', 'provider_used': None}

    last_error = None
    for provider, api_key, model in attempts:
        fn = _DISPATCH.get(provider)
        if not fn:
            last_error = f'{provider}: dispatch missing'
            continue
        # 14k-63: backoff check — provider 在限额冷却期内直接跳过 (省 LLM call + log noise)
        in_bo, remaining = _provider_in_backoff(provider)
        if in_bo:
            last_error = f'{provider}: in backoff ({remaining:.0f}s remaining)'
            continue
        t0 = time.time()
        try:
            # Phase 12.41: 仅 claude_cli 当前支持 allowed_tools + per-call timeout
            if provider == 'claude_cli':
                kwargs = {}
                if allowed_tools:
                    kwargs['allowed_tools'] = allowed_tools
                if timeout is not None:
                    kwargs['timeout'] = timeout
                res = fn(api_key, prompt, system, max_tokens, model, **kwargs)
            else:
                res = fn(api_key, prompt, system, max_tokens, model)
            latency_ms = int((time.time() - t0) * 1000)
            # 14k-63: 成功 → 清 backoff state
            _record_provider_success(provider)
            # 寫用量（claude_cli 不記，因走訂閱沒 API token 帳）
            if provider != 'claude_cli':
                try:
                    record_usage(user_id, provider,
                                 res['usage'].get('input_tokens', 0),
                                 res['usage'].get('output_tokens', 0))
                except Exception:
                    pass
            result = {
                'ok': True,
                'text': res['text'],
                'model_used': res['model_used'],
                'provider_used': provider,
                'usage': res['usage'],
                'latency_ms': latency_ms,
                'cached': False,
            }
            # 寫 cache
            if cache_key:
                try:
                    from app.services.cache import cache_set
                    cache_set(cache_key, result, ttl=1800)
                except Exception:
                    pass
            return result
        except Exception as e:
            err = f'{type(e).__name__}: {e}'
            last_error = f'{provider}: {err}'
            print(f'[llm] {last_error}')
            # 14k-63: 失败计数, 连续 3 次进 backoff (permanent error 不算 — 不会自愈)
            if not _is_permanent_error(err):
                _record_provider_fail(provider)
            if _is_permanent_error(err):
                break

    return {'ok': False, 'error': last_error or '所有 provider 都失敗',
            'text': '', 'provider_used': None}
