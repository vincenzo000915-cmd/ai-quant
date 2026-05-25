"""Phase 14k-5: 交易所绑定权限 + 主交易所判定

设计 (per user 反馈):
- 普通 user (free/basic/pro): 只能绑 1 个交易所 (OKX OR HL 互斥)
- 团队版 (team) / admin: 可绑多个, 此时策略 .exchange 字段才有意义
- 系统所有路径 (AI 推荐 / 翻译审核 / 规则) 跟 user "主交易所" 走
"""
from __future__ import annotations

from app.services.subscription_service import has_tier
from app.services.okx_creds import get_for_user as okx_get
from app.services.hyperliquid_creds import get_for_user as hl_get


def is_team_tier(user_id: int) -> bool:
    """admin 或 team 才能绑多交易所"""
    return has_tier(user_id, 'team')


def bound_exchanges(user_id: int) -> list[str]:
    """返回 user 已绑且 active 的交易所 list (顺序: ['okx', 'hyperliquid']).
    admin (user_id=1) 默认 OKX 已通过 .env 绑定, 始终包含 'okx'.
    """
    out = []
    if user_id == 1:
        # admin OKX 走 .env (EXCHANGE_API_KEY 等)
        import os
        if os.environ.get('EXCHANGE_API_KEY'):
            out.append('okx')
    else:
        okx = okx_get(user_id)
        if okx and okx.is_active:
            out.append('okx')
    hl = hl_get(user_id)
    if hl and hl.is_active:
        out.append('hyperliquid')
    return out


def primary_exchange(user_id: int) -> str:
    """user 当前的主交易所 — 普通 user 就是绑的那个, team 取第一个绑的, 都没绑默认 okx"""
    bound = bound_exchanges(user_id)
    if not bound:
        return 'okx'
    return bound[0]


def can_bind(user_id: int, target_exchange: str) -> tuple[bool, str]:
    """检查 user 能否绑 target_exchange.
    返回 (allowed, reason_if_blocked).
    普通 user 已绑另一个 → 拒绝 + 提示升级或解绑.
    """
    target = (target_exchange or '').lower()
    if target not in ('okx', 'hyperliquid'):
        return False, f'未知 exchange: {target_exchange}'

    if is_team_tier(user_id):
        return True, ''   # team 随便绑

    current = bound_exchanges(user_id)
    if not current:
        return True, ''   # 没绑过, 第一次绑 OK

    if target in current:
        return True, ''   # 已绑同一个, update 也 OK

    # 普通 user 已经绑了另一个 → 拒绝
    other_name = 'OKX' if current[0] == 'okx' else 'Hyperliquid'
    target_name = 'OKX' if target == 'okx' else 'Hyperliquid'
    return False, (
        f'你已绑定 {other_name}, 普通账户仅支持 1 个交易所. '
        f'要换到 {target_name}: 先解绑 {other_name}, 或升级团队版 (team 可绑多个交易所).'
    )
