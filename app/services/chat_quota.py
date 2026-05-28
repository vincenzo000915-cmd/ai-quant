"""Phase 14k-126: chat per-user daily quota (Redis).

Pro:   50 messages / day
Team:  200 messages / day
admin: unlimited

Redis key: chat:quota:{user_id}:{YYYYMMDD}, INCR + EXPIRE 25h (cover TZ edge)

extraction attempt 单独 throttle:
  Redis key: chat:extraction:{user_id}:{YYYYMMDD}, INCR + EXPIRE 25h
  ≥ 3 次 / 24h → 暂停 chat 24h, audit warn
"""
from __future__ import annotations

import datetime
from typing import Tuple


# 按 tier 配额 (跟 14k-55 invent_quota 同 design)
DAILY_LIMIT_BY_TIER = {
    'preview': 0,
    'basic':   0,    # Basic 没 AI features, chat 也不开
    'pro':     50,
    'team':    200,
    'admin':   10**6,    # 实际 unlimited
}

# 越狱尝试上限 (低 tolerance, 多了就锁)
EXTRACTION_DAILY_BLOCK_THRESHOLD = 3


def _today_key(prefix: str, user_id: int) -> str:
    today = datetime.datetime.utcnow().strftime('%Y%m%d')
    return f'chat:{prefix}:{user_id}:{today}'


def _redis_or_none():
    try:
        from app.services.cache import _redis
        return _redis()
    except Exception:
        return None


def check_and_increment(user_id: int, tier: str) -> Tuple[bool, dict]:
    """检查 user 今日 chat 配额并消耗 1.

    Returns:
        (allowed, info)
        info = {used: int, limit: int, remaining: int, blocked_extraction: bool}
        allowed=True → 消耗 1 个, 继续走 LLM
        allowed=False → quota 满 OR extraction lock, info.remaining=0 或 blocked_extraction=True
    """
    limit = DAILY_LIMIT_BY_TIER.get(tier, 0)
    r = _redis_or_none()
    if not r:
        # Redis 不可用 → 保守: 拒绝, 防滥用
        return False, {'error': 'rate limit service unavailable', 'used': 0, 'limit': limit, 'remaining': 0}

    # 1. 先看 extraction lock
    extract_key = _today_key('extraction', user_id)
    try:
        extract_n = int(r.get(extract_key) or 0)
    except Exception:
        extract_n = 0
    if extract_n >= EXTRACTION_DAILY_BLOCK_THRESHOLD:
        return False, {'used': 0, 'limit': limit, 'remaining': 0,
                       'blocked_extraction': True,
                       'reason': f'≥ {EXTRACTION_DAILY_BLOCK_THRESHOLD} 次 prompt extraction 尝试, 24h 内暂停 chat'}

    # 2. 配额检查 + INCR
    quota_key = _today_key('quota', user_id)
    try:
        used = int(r.incr(quota_key))
        if used == 1:
            r.expire(quota_key, 25 * 3600)
    except Exception as e:
        return False, {'error': f'redis incr fail: {type(e).__name__}', 'used': 0, 'limit': limit, 'remaining': 0}

    if used > limit:
        # 回滚 INCR (避免 used 持续涨)
        try:
            r.decr(quota_key)
        except Exception:
            pass
        return False, {'used': limit, 'limit': limit, 'remaining': 0,
                       'reason': f'今日 chat 配额 {limit} 用完, 明日 UTC 00:00 重置'}

    return True, {'used': used, 'limit': limit, 'remaining': limit - used}


def record_extraction_attempt(user_id: int) -> int:
    """user 命中 jailbreak / extraction 时调用. 返回今日累计次数."""
    r = _redis_or_none()
    if not r:
        return 0
    key = _today_key('extraction', user_id)
    try:
        n = int(r.incr(key))
        if n == 1:
            r.expire(key, 25 * 3600)
        return n
    except Exception:
        return 0


def get_quota_status(user_id: int, tier: str) -> dict:
    """只看不消耗, 用于前端显示 "剩余 X 次" 之类."""
    limit = DAILY_LIMIT_BY_TIER.get(tier, 0)
    r = _redis_or_none()
    if not r:
        return {'used': 0, 'limit': limit, 'remaining': limit}
    try:
        used = int(r.get(_today_key('quota', user_id)) or 0)
        extract_n = int(r.get(_today_key('extraction', user_id)) or 0)
    except Exception:
        used = 0
        extract_n = 0
    return {
        'used': used,
        'limit': limit,
        'remaining': max(0, limit - used),
        'extraction_attempts': extract_n,
        'blocked_extraction': extract_n >= EXTRACTION_DAILY_BLOCK_THRESHOLD,
    }
