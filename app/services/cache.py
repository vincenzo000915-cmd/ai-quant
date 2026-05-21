"""Phase 12.4: simple Redis JSON cache.

Used to memoize expensive read-only computations and OKX REST round-trips.
- TTL based, no manual invalidation
- silently no-op if Redis unreachable (degrade open, don't break the app)
- JSON-encoded so we can inspect via redis-cli
"""
from __future__ import annotations

import functools
import hashlib
import json
import time
from typing import Any, Callable

from redis import Redis
from redis.exceptions import RedisError

_REDIS = None


def _redis() -> Redis | None:
    global _REDIS
    if _REDIS is not None:
        return _REDIS
    try:
        _REDIS = Redis(host='redis', port=6379, db=2, socket_connect_timeout=0.5, socket_timeout=0.5)
        _REDIS.ping()
    except RedisError:
        _REDIS = None
    return _REDIS


def _key(prefix: str, args: tuple, kwargs: dict) -> str:
    """Stable key from prefix + args + kwargs."""
    raw = json.dumps([args, sorted(kwargs.items())], default=str, sort_keys=True)
    if len(raw) > 200:
        raw = hashlib.sha256(raw.encode()).hexdigest()
    return f'cache:{prefix}:{raw}'


def cached(prefix: str, ttl: int):
    """Decorator. Cache function's JSON-serializable return for `ttl` seconds.

    Usage:
        @cached('ohlcv', ttl=60)
        def fetch_ohlcv(symbol, timeframe, limit=500): ...
    """
    def decorator(fn: Callable):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            r = _redis()
            if r is None:
                return fn(*args, **kwargs)
            key = _key(prefix, args, kwargs)
            try:
                hit = r.get(key)
                if hit is not None:
                    return json.loads(hit)
            except (RedisError, ValueError):
                pass

            result = fn(*args, **kwargs)

            try:
                payload = json.dumps(result, default=str)
                r.setex(key, ttl, payload)
            except (RedisError, TypeError, ValueError):
                pass
            return result
        return wrapped
    return decorator


def cached_response(prefix: str, ttl: int):
    """Cache an entire Flask view function's JSON response for TTL seconds.

    Key includes request.full_path so different query strings cache separately.
    The view must return jsonify(...) — we cache the raw JSON string.
    """
    from flask import request, Response

    def decorator(fn: Callable):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            r = _redis()
            if r is None:
                return fn(*args, **kwargs)
            key = f'cache:resp:{prefix}:{request.full_path}'
            try:
                hit = r.get(key)
                if hit is not None:
                    resp = Response(hit, status=200, mimetype='application/json')
                    resp.headers['X-Cache'] = 'HIT'
                    return resp
            except RedisError:
                pass

            result = fn(*args, **kwargs)

            try:
                body = result.get_data(as_text=True) if hasattr(result, 'get_data') else None
                if body and getattr(result, 'status_code', 200) == 200:
                    r.setex(key, ttl, body)
                    if hasattr(result, 'headers'):
                        result.headers['X-Cache'] = 'MISS'
            except (RedisError, AttributeError):
                pass
            return result
        return wrapped
    return decorator


def cache_get(key: str) -> Any | None:
    """Phase 11.5.2: 直接讀 cache key（給 llm_provider 等使用）"""
    r = _redis()
    if r is None:
        return None
    try:
        hit = r.get(f'cache:{key}')
        if hit is not None:
            return json.loads(hit)
    except (RedisError, ValueError):
        pass
    return None


def cache_set(key: str, value: Any, ttl: int) -> None:
    """Phase 11.5.2: 直接寫 cache key，TTL 秒"""
    r = _redis()
    if r is None:
        return
    try:
        r.setex(f'cache:{key}', ttl, json.dumps(value, default=str))
    except (RedisError, TypeError, ValueError):
        pass


def invalidate(prefix: str):
    """Drop all keys for a prefix (best-effort SCAN + DEL)."""
    r = _redis()
    if r is None:
        return 0
    try:
        deleted = 0
        for k in r.scan_iter(f'cache:{prefix}:*'):
            r.delete(k)
            deleted += 1
        return deleted
    except RedisError:
        return 0
