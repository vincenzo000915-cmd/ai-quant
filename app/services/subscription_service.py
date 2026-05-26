"""Phase 12.24: 订阅 + USDT 付款 invoice 服务

核心机制：单地址 + 金额唯一 suffix 识别用户订单
  - USDT TRC20/ERC20/BEP20/SPL 都不支持 memo 字段
  - 用「金额尾数法」：amount_due = base_amount + .ABCDEF（6 位随机 dust）
  - 链上 polling 拉地址 incoming tx，精确 amount 匹配 → 找到对应订单

防冲突：同一 chain 内同时 active 的 pending invoice 不允许同 amount_due
  → 创建 invoice 时检查 + 重试 suffix（最多 100 次）
"""
from __future__ import annotations

import datetime
import decimal
import os
import random

from app.extensions import db
from app.models import PaymentInvoice, Subscription

# 定价（USDT / 月）
PLAN_PRICES = {
    'basic': decimal.Decimal('50'),
    'pro':   decimal.Decimal('125'),
    'team':  decimal.Decimal('250'),
}

# 预付折扣
DISCOUNT_MAP = {
    1:  0,
    3:  10,
    6:  20,
    12: 30,
}

# 支持的链 + .env 地址
SUPPORTED_CHAINS = {
    'trc20': {
        'env_key': 'USDT_TRC20_ADDRESS',
        'label': 'USDT-TRC20',
        'network': 'Tron',
        'fee_estimate': '~$1',
        'confirm_time': '1-3 分钟',
    },
    'erc20': {
        'env_key': 'USDT_ERC20_ADDRESS',
        'label': 'USDT-ERC20',
        'network': 'Ethereum',
        'fee_estimate': '$5-20',
        'confirm_time': '3-5 分钟',
    },
    'bep20': {
        'env_key': 'USDT_BEP20_ADDRESS',
        'label': 'USDT-BEP20',
        'network': 'BNB Chain',
        'fee_estimate': '~$0.3',
        'confirm_time': '1-2 分钟',
    },
    'sol': {
        'env_key': 'USDT_SOL_ADDRESS',
        'label': 'USDT-SPL',
        'network': 'Solana',
        'fee_estimate': '<$0.01',
        'confirm_time': '<10 秒',
    },
}

INVOICE_TTL_MINUTES = 30   # invoice 过期时间


def get_chain_addresses() -> dict:
    """返回前端可用的 chain → address 映射（含 metadata）"""
    out = {}
    for chain, meta in SUPPORTED_CHAINS.items():
        addr = os.environ.get(meta['env_key'], '').strip()
        if addr:
            out[chain] = {
                'address': addr,
                'label': meta['label'],
                'network': meta['network'],
                'fee_estimate': meta['fee_estimate'],
                'confirm_time': meta['confirm_time'],
            }
    return out


def calc_base_amount(plan: str, months: int) -> decimal.Decimal:
    """计算订阅基础金额（不含 suffix）"""
    if plan not in PLAN_PRICES:
        raise ValueError(f'invalid plan: {plan}')
    if months not in DISCOUNT_MAP:
        raise ValueError(f'invalid months: {months}')
    base = PLAN_PRICES[plan] * months
    discount = DISCOUNT_MAP[months]
    if discount:
        base = base * decimal.Decimal(100 - discount) / decimal.Decimal(100)
    # 取整到分（USDT 通常 6 位小数，但用户看 2 位）
    return base.quantize(decimal.Decimal('0.01'))


def _gen_suffix() -> str:
    """生成 6 位随机 dust suffix 字符串 '.123456'"""
    return f'.{random.randint(100000, 999999)}'


def create_invoice(user_id: int, plan: str, months: int, chain: str) -> dict:
    """创建一个 pending invoice。返回 invoice dict 或 {ok: False, error}。"""
    if plan not in PLAN_PRICES:
        return {'ok': False, 'error': f'invalid plan: {plan}'}
    if months not in DISCOUNT_MAP:
        return {'ok': False, 'error': f'invalid months: {months}'}
    if chain not in SUPPORTED_CHAINS:
        return {'ok': False, 'error': f'invalid chain: {chain}'}

    address = os.environ.get(SUPPORTED_CHAINS[chain]['env_key'], '').strip()
    if not address:
        return {'ok': False, 'error': f'chain {chain} 收款地址未配置'}

    base_amount = calc_base_amount(plan, months)

    # 取唯一 suffix — 同 chain + status='pending' 内不重复
    for attempt in range(100):
        suffix = _gen_suffix()
        amount_due = base_amount + decimal.Decimal(suffix) / decimal.Decimal(1000000)
        # 不对 — suffix 是字符串 ".123456"，应该当 dust：用 100 万分位
        # 重写：base_amount 是 USDT，suffix 加到 .xxxxxx 6 位
        suffix_decimal = decimal.Decimal(suffix.lstrip('.')) / decimal.Decimal(1_000_000)
        amount_due = base_amount + suffix_decimal
        amount_due = amount_due.quantize(decimal.Decimal('0.000001'))

        # 检查同 chain pending 内是否冲突
        existing = PaymentInvoice.query.filter_by(
            chain=chain,
            amount_due=amount_due,
            status='pending',
        ).first()
        if not existing:
            break
    else:
        return {'ok': False, 'error': 'suffix 100 次尝试都冲突，请重试'}

    now = datetime.datetime.utcnow()
    expires = now + datetime.timedelta(minutes=INVOICE_TTL_MINUTES)

    inv = PaymentInvoice(
        user_id=user_id,
        plan=plan,
        months=months,
        discount_pct=DISCOUNT_MAP[months],
        base_amount=base_amount,
        suffix=suffix,
        amount_due=amount_due,
        chain=chain,
        address=address,
        status='pending',
        created_at=now,
        expires_at=expires,
    )
    db.session.add(inv)
    db.session.commit()

    return {'ok': True, 'invoice': inv.to_dict()}


def get_invoice(invoice_id: int, user_id: int | None = None) -> dict | None:
    """查询单个 invoice。可选 user_id 限制（用户只能看自己的）"""
    q = PaymentInvoice.query.filter_by(id=invoice_id)
    if user_id is not None:
        q = q.filter_by(user_id=user_id)
    inv = q.first()
    return inv.to_dict() if inv else None


def expire_old_invoices() -> int:
    """cron 跑：把过期的 pending invoice 标 expired。返回处理条数"""
    now = datetime.datetime.utcnow()
    n = PaymentInvoice.query.filter(
        PaymentInvoice.status == 'pending',
        PaymentInvoice.expires_at < now,
    ).update({PaymentInvoice.status: 'expired'}, synchronize_session=False)
    db.session.commit()
    return n


def activate_subscription_from_invoice(invoice: PaymentInvoice) -> Subscription:
    """invoice confirmed 后开通订阅（或延期现有订阅）"""
    user_id = invoice.user_id
    plan = invoice.plan
    months = invoice.months
    now = datetime.datetime.utcnow()

    # 已有 active 订阅 → 延期
    existing = Subscription.query.filter_by(user_id=user_id, status='active').first()
    if existing:
        # 从 max(now, existing.expires_at) 开始延期
        base_start = max(now, existing.expires_at)
        existing.expires_at = base_start + datetime.timedelta(days=30 * months)
        # 升级 plan（如果新 plan tier 更高）
        tier_rank = {'basic': 1, 'pro': 2, 'team': 3}
        if tier_rank.get(plan, 0) > tier_rank.get(existing.plan, 0):
            existing.plan = plan
        existing.invoice_id = invoice.id
        sub = existing
    else:
        sub = Subscription(
            user_id=user_id,
            plan=plan,
            status='active',
            invoice_id=invoice.id,
            activated_at=now,
            expires_at=now + datetime.timedelta(days=30 * months),
            auto_renew=False,
        )
        db.session.add(sub)

    invoice.status = 'confirmed'
    invoice.confirmed_at = now
    db.session.commit()
    return sub


def get_active_subscription(user_id: int) -> Subscription | None:
    """拿 user 当前 active 订阅"""
    now = datetime.datetime.utcnow()
    return Subscription.query.filter(
        Subscription.user_id == user_id,
        Subscription.status == 'active',
        Subscription.expires_at > now,
    ).order_by(Subscription.expires_at.desc()).first()


def get_user_tier(user_id: int) -> str:
    """返回 user 当前 tier: 'preview' / 'basic' / 'pro' / 'team' / 'admin'

    admin 永远是 admin。
    """
    from app.models import User
    user = User.query.get(user_id)
    if user and user.role == 'admin':
        return 'admin'
    sub = get_active_subscription(user_id)
    if sub:
        return sub.plan
    return 'preview'


def has_tier(user_id: int, required: str) -> bool:
    """检查 user 是否达到 required tier。admin 自动通过。"""
    rank = {'preview': 0, 'basic': 1, 'pro': 2, 'team': 3, 'admin': 99}
    return rank.get(get_user_tier(user_id), 0) >= rank.get(required, 0)


# 14k-55: tier-aware invent quota — user 指出 "只有 pro/team 真接 AI 才会有策略爆炸问题"
# Basic 主要复用 catalog 共享池, individual invent 上限低; Pro/Team 真自动 invent 高 quota
INVENT_QUOTA_BY_TIER = {
    'preview': 5,    # 试用 — 几乎不让 invent
    'basic':   20,   # 手动审批为主, catalog 复用就够
    'pro':     100,  # 半自动智能驾驶 + AI 工具集
    'team':    500,  # 完全自动托管, 高 invent 频率
    'admin':   1000, # 内部, 不限制
}


def get_invent_quota(user_id: int) -> int:
    """14k-55: 该 user 自己的 individual candidates 上限 (catalog 共享池不算 quota).
    超过 quota 时 cleanup task 强制 archived 老的, 防失控膨胀.
    """
    tier = get_user_tier(user_id)
    return INVENT_QUOTA_BY_TIER.get(tier, 20)
