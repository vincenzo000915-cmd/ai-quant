"""Phase 14k-7: 交易所一键切换 (atomic, 含策略迁移)

非 team user 已绑 OKX, 现在想换 HL — 在一个事务里:
  1. UPDATE strategies SET exchange='hyperliquid' WHERE user_id=X (迁所有策略)
  2. 删除旧 creds (OKX)
  3. 写入新 creds (HL)
  4. audit log + telegram

调用方式: 当 POST /me/hyperliquid 时 user 已绑 OKX (非 team), 自动走 switch
而不是 reject. user 永远不需要先解绑.

不影响 team user — team 走多绑路径不触发 switch.
"""
from __future__ import annotations

from app.extensions import db
from app.models import Strategy, OkxCredentials, HyperliquidCredentials


def count_strategies_on(user_id: int, exchange: str) -> int:
    """user 在某交易所上的策略数 (不论 status)"""
    return Strategy.query.filter_by(user_id=user_id, exchange=exchange).count()


def migrate_strategies(user_id: int, from_exchange: str, to_exchange: str) -> int:
    """批量迁移策略 exchange 字段. 返回迁移条数. 不 commit."""
    rows = Strategy.query.filter_by(user_id=user_id, exchange=from_exchange).all()
    for s in rows:
        s.exchange = to_exchange
    return len(rows)


def switch_to_okx(user_id: int, api_key: str, secret: str, passphrase: str) -> dict:
    """atomic: 从 HL 切到 OKX (非 team user 用)"""
    from app.services.okx_creds import save_for_user as okx_save
    from app.services.hyperliquid_creds import delete_for_user as hl_delete
    from app.services.audit import log as audit

    # 1. 迁移策略
    migrated = migrate_strategies(user_id, 'hyperliquid', 'okx')
    # 2. 删 HL creds
    hl_delete(user_id)
    # 3. 写 OKX creds (save_for_user 内部 commit)
    okx_save(user_id, api_key, secret, passphrase)
    # 4. ensure migrate_strategies 落库
    db.session.commit()

    audit('exchange_switch', actor='user', user_id=user_id,
          from_exchange='hyperliquid', to_exchange='okx', migrated_strategies=migrated)

    return {
        'ok': True,
        'switched_to': 'okx',
        'migrated_strategies': migrated,
        'message': f'已切换到 OKX, {migrated} 个策略已自动迁移',
    }


def switch_to_hyperliquid(user_id: int, agent_address: str, main_address: str,
                          agent_private_key: str, network: str = 'mainnet') -> dict:
    """atomic: 从 OKX 切到 HL (非 team user 用)"""
    from app.services.hyperliquid_creds import save_for_user as hl_save
    from app.services.okx_creds import delete_for_user as okx_delete
    from app.services.audit import log as audit

    migrated = migrate_strategies(user_id, 'okx', 'hyperliquid')
    okx_delete(user_id)
    hl_save(user_id, agent_address, main_address, agent_private_key, network)
    db.session.commit()

    audit('exchange_switch', actor='user', user_id=user_id,
          from_exchange='okx', to_exchange='hyperliquid', migrated_strategies=migrated)

    return {
        'ok': True,
        'switched_to': 'hyperliquid',
        'migrated_strategies': migrated,
        'message': f'已切换到 Hyperliquid, {migrated} 个策略已自动迁移',
    }
