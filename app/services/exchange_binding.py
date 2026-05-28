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
    Phase 14k-14: admin 可临时禁用 OKX (config disable_okx_for_admin) 专注 HL 测试.
    """
    out = []
    # 14k-14: admin 临时禁 OKX 的旁路
    admin_okx_disabled = False
    if user_id == 1:
        try:
            from app.services.config_service import get_config
            admin_okx_disabled = bool(get_config().get('disable_okx_for_admin'))
        except Exception:
            pass

    if user_id == 1 and not admin_okx_disabled:
        # admin OKX 走 .env (EXCHANGE_API_KEY 等)
        import os
        if os.environ.get('EXCHANGE_API_KEY'):
            out.append('okx')
    elif user_id != 1:
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


def routable_exchanges(user_id: int) -> list[str]:
    """Phase 14k-141: B1b 跨所路由 / B3 评估 edge 可用的交易所 — tier-aware.
    team/admin → 所有 active 绑定 (可跨所路由); 非 team → 只 primary 一个所
    (即使数据里遗留多个绑定, 如从 team 降级 — 非 team 不该被跨所路由).
    防降级/数据异常让非 team 用户意外获得跨所能力."""
    bound = bound_exchanges(user_id)
    if not bound:
        return []
    if is_team_tier(user_id):
        return bound
    primary = primary_exchange(user_id)
    return [primary] if primary in bound else bound[:1]


def needs_switch(user_id: int, target_exchange: str) -> tuple[bool, str | None]:
    """非 team user 绑新交易所时, 检查是否需要走 atomic switch 流程.

    返回 (needs_switch, from_exchange_or_None).
    - True, 'okx'/'hyperliquid' — 是非 team, 已绑另一个, 应走 switch
    - False, None — team / 没绑过 / 绑的是同一个, 走普通 save
    """
    target = (target_exchange or '').lower()
    if is_team_tier(user_id):
        return False, None
    current = bound_exchanges(user_id)
    if not current:
        return False, None
    if target in current:
        return False, None
    # 非 team, 已绑别的, 不是同一个 → 需 switch
    return True, current[0]


def can_bind(user_id: int, target_exchange: str) -> tuple[bool, str]:
    """检查 user 能否绑 target_exchange (legacy — 仅 team 路径用).

    Phase 14k-7: 非 team user 改走 needs_switch 自动 atomic 切换,
    所以这里只用来挡完全异常的输入.
    """
    target = (target_exchange or '').lower()
    if target not in ('okx', 'hyperliquid'):
        return False, f'未知 exchange: {target_exchange}'
    return True, ''
