"""Phase 12.3: lightweight per-endpoint rate limit on top of Redis.

We already depend on Redis for Celery so adding Flask-Limiter would just
duplicate it. This implementation:
- fixed-window counter (INCR + EXPIRE on first hit)
- key = ratelimit:{client_ip}:{endpoint_name}:{window_idx}
- returns 429 JSON + Retry-After header when exceeded
- silently no-ops if Redis is unreachable (don't kill the API for a
  metering miss)

Usage:
    @api_bp.route('/kill', methods=['POST'])
    @rate_limit('5/min')
    def kill(): ...
"""
from __future__ import annotations

import functools
import time
from typing import Callable

from flask import jsonify, request
from redis import Redis
from redis.exceptions import RedisError


_REDIS = None


def _redis() -> Redis | None:
    global _REDIS
    if _REDIS is not None:
        return _REDIS
    try:
        _REDIS = Redis(host='redis', port=6379, db=1, socket_connect_timeout=0.5, socket_timeout=0.5)
        _REDIS.ping()
    except RedisError:
        _REDIS = None
    return _REDIS


def _parse(spec: str) -> tuple[int, int]:
    """'5/min' -> (5, 60); '30/sec' -> (30, 1); '100/hour' -> (100, 3600)"""
    n_str, unit = spec.split('/', 1)
    n = int(n_str)
    unit = unit.strip().lower()
    window = {
        'sec': 1, 's': 1, 'second': 1, 'seconds': 1,
        'min': 60, 'm': 60, 'minute': 60, 'minutes': 60,
        'hour': 3600, 'h': 3600, 'hours': 3600,
    }.get(unit)
    if window is None:
        raise ValueError(f'unknown rate-limit unit: {unit}')
    return n, window


def _client_id() -> str:
    """Identify a client for limiting. Prefer XFF first hop (we sit behind no
    proxy yet, but support it for when nginx lands)."""
    xff = request.headers.get('X-Forwarded-For', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.remote_addr or 'unknown'


def rate_limit(spec: str):
    """Decorator factory. spec like '5/min'."""
    limit, window = _parse(spec)

    def decorator(fn: Callable):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            r = _redis()
            if r is None:
                return fn(*args, **kwargs)  # 沒 Redis 就放行

            client = _client_id()
            bucket = int(time.time() // window)
            key = f'ratelimit:{client}:{fn.__name__}:{bucket}'
            try:
                count = r.incr(key, amount=1)
                if count == 1:
                    r.expire(key, window)
            except RedisError:
                return fn(*args, **kwargs)

            if count > limit:
                # 已超 — 算剩餘時間
                try:
                    ttl = r.ttl(key)
                except RedisError:
                    ttl = window
                retry = max(1, ttl if isinstance(ttl, int) and ttl > 0 else window)
                resp = jsonify({
                    'error': 'rate_limited',
                    'detail': f'最多 {limit} 次 / {window}s，請 {retry}s 後再試',
                    'limit': limit,
                    'window_seconds': window,
                    'retry_after': retry,
                })
                resp.status_code = 429
                resp.headers['Retry-After'] = str(retry)
                resp.headers['X-RateLimit-Limit'] = str(limit)
                resp.headers['X-RateLimit-Remaining'] = '0'
                return resp

            return fn(*args, **kwargs)
        return wrapped
    return decorator
