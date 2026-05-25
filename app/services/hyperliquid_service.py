"""Phase 14k: Hyperliquid (DEX perp) 交易服务 — 镜像 okx exchange_service 接口

镜像的接口 (供 strategy_tasks dispatch 用):
- fetch_balance(creds) -> dict     # {USDC: {total, free, used}, ...}
- fetch_positions(creds) -> list   # [{inst_id, pos_contracts, side, avg_px, upl}, ...]
- get_ticker(symbol) -> dict       # {symbol, price}
- place_order_live(symbol, side, size_usdt, leverage, creds, ...) -> dict
- cancel_all_orders(creds, symbol=None) -> dict

HL 设计注意:
- HL 不用 USDT, 用 USDC (Arbitrum bridge over)
- HL symbol 是 base coin name 'BTC' (不带 quote), 内部 mapping
- agent wallet 在 HL 平台 enforce: 只能 trade, 无法 transfer/withdraw
- 'price' returned by all_mids 是当前 mid; orderbook 用 l2_book 拉
"""
from __future__ import annotations

import logging
from typing import Any

from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from eth_account import Account

log = logging.getLogger(__name__)


# ============================================================
# Symbol mapping — BTC/USDT (system) ↔ BTC (HL)
# ============================================================

# HL 支持的主要 perps (与现 catalog 重合的)
_HL_BASE_FROM_SYM = {
    'BTC/USDT': 'BTC',
    'ETH/USDT': 'ETH',
    'SOL/USDT': 'SOL',
    'AVAX/USDT': 'AVAX',
    'ARB/USDT': 'ARB',
    'OP/USDT': 'OP',
    'MATIC/USDT': 'MATIC',
    'DOGE/USDT': 'DOGE',
    'LINK/USDT': 'LINK',
    'APT/USDT': 'APT',
    'INJ/USDT': 'INJ',
    'SUI/USDT': 'SUI',
    'TIA/USDT': 'TIA',
    'BNB/USDT': 'BNB',
}


def hl_base(symbol: str) -> str:
    """'BTC/USDT' → 'BTC'. Fallback: 取 / 之前的 base."""
    if symbol in _HL_BASE_FROM_SYM:
        return _HL_BASE_FROM_SYM[symbol]
    if '/' in symbol:
        return symbol.split('/')[0]
    return symbol


# ============================================================
# Client factory
# ============================================================

def _base_url(network: str) -> str:
    return constants.TESTNET_API_URL if network == 'testnet' else constants.MAINNET_API_URL


def _info_client(network: str = 'mainnet') -> Info:
    """HL public info (no signing)."""
    return Info(_base_url(network), skip_ws=True)


def _exchange_client(creds: dict) -> tuple[Exchange, Info]:
    """authed Exchange + Info pair. creds = decrypted dict."""
    if not creds or not creds.get('agent_private_key'):
        raise RuntimeError('Hyperliquid creds 缺失 (need agent_private_key)')
    network = creds.get('network') or 'mainnet'
    pk = creds['agent_private_key']
    if not pk.startswith('0x'):
        pk = '0x' + pk
    wallet = Account.from_key(pk)
    base_url = _base_url(network)
    info = Info(base_url, skip_ws=True)
    # account_address = main wallet (user-of-record); wallet = agent signer
    exchange = Exchange(wallet, base_url, account_address=creds.get('main_address'))
    return exchange, info


# ============================================================
# Public reads
# ============================================================

def get_ticker(symbol: str, network: str = 'mainnet') -> dict:
    """{symbol, price} — 当前 mid price."""
    info = _info_client(network)
    base = hl_base(symbol)
    mids = info.all_mids()
    px = mids.get(base)
    if px is None:
        raise RuntimeError(f'HL no price for {base} (sym={symbol})')
    return {'symbol': symbol, 'price': float(px)}


_HL_STABLECOINS = ('USDC', 'USDT0', 'USDH', 'USDE')


def fetch_balance(creds: dict) -> dict:
    """Phase 14k-9: HL Unified Account — spot stablecoin + perp accountValue 合算

    HL 现在是统一保证金账户: spot 里的 USDC 可直接当 perp collateral, 不需手动 transfer.
    返回 OKX-compat shape:
      {USDT: {total, free, used}, _native_currency, _breakdown}
    """
    if not creds or not creds.get('main_address'):
        raise RuntimeError('HL creds 缺失 main_address')
    network = creds.get('network') or 'mainnet'
    info = _info_client(network)
    main = creds['main_address']

    # perp 账户
    state = info.user_state(main)
    margin_summary = state.get('marginSummary') or {}
    perp_value = float(margin_summary.get('accountValue', 0))
    perp_margin_used = float(margin_summary.get('totalMarginUsed', 0))
    perp_withdrawable = float(state.get('withdrawable', 0))

    # spot 账户 — 加总所有 stablecoin
    spot_total = 0.0
    spot_breakdown = {}
    try:
        spot_state = info.spot_user_state(main)
        for b in (spot_state.get('balances') or []):
            coin = (b.get('coin') or '').upper()
            if coin in _HL_STABLECOINS:
                amt = float(b.get('total') or 0)
                spot_total += amt
                if amt > 0:
                    spot_breakdown[coin] = amt
    except Exception as e:
        # spot 拉失败不影响 perp 数据
        spot_breakdown['_error'] = str(e)[:80]

    # 统一总额: spot stablecoins + perp accountValue
    total = spot_total + perp_value
    # free: 总余 - 已用作 perp 保证金
    free = max(0.0, total - perp_margin_used)

    return {
        'USDT': {
            'total': round(total, 4),
            'free': round(free, 4),
            'used': round(perp_margin_used, 4),
        },
        '_native_currency': 'USDC',
        '_breakdown': {
            'spot_stablecoins': round(spot_total, 4),
            'spot_per_coin': spot_breakdown,
            'perp_account_value': round(perp_value, 4),
            'perp_margin_used': round(perp_margin_used, 4),
            'perp_withdrawable': round(perp_withdrawable, 4),
        },
    }


def fetch_agent_validity(main_address: str, agent_address: str,
                          network: str = 'mainnet') -> dict | None:
    """查 HL info extraAgents — 找 main_address 下匹配 agent_address 的条目.

    返回 {address, name, valid_until_ms, valid_until_dt} 或 None (未授权)
    """
    if not main_address or not agent_address:
        return None
    info = _info_client(network)
    try:
        # SDK 的 post() 是底层 http; type=extraAgents 是 HL info API
        agents = info.post('/info', {'type': 'extraAgents', 'user': main_address})
    except Exception:
        return None
    if not isinstance(agents, list):
        return None
    target = agent_address.lower()
    import datetime as _dt
    for a in agents:
        if not isinstance(a, dict):
            continue
        if (a.get('address') or '').lower() == target:
            ts_ms = a.get('validUntil')
            return {
                'address': a.get('address'),
                'name': a.get('name'),
                'valid_until_ms': ts_ms,
                'valid_until_dt': _dt.datetime.utcfromtimestamp(ts_ms / 1000) if ts_ms else None,
            }
    return None


def fetch_positions(creds: dict) -> list[dict]:
    """[{inst_id, pos_contracts, side, avg_px, upl, ...}] — 兼容 OKX shape."""
    if not creds or not creds.get('main_address'):
        raise RuntimeError('HL creds 缺失 main_address')
    info = _info_client(creds.get('network') or 'mainnet')
    state = info.user_state(creds['main_address'])
    out = []
    for ap in (state.get('assetPositions') or []):
        pos = ap.get('position') or {}
        szi = float(pos.get('szi', 0))      # +long, -short
        if szi == 0:
            continue
        out.append({
            'inst_id': f"{pos.get('coin', '?')}-PERP",
            'symbol': f"{pos.get('coin', '?')}/USDT",
            'pos_contracts': abs(szi),
            'side': 'long' if szi > 0 else 'short',
            'avg_px': float(pos.get('entryPx', 0)),
            'unrealized_pnl': float(pos.get('unrealizedPnl', 0)),
            'liquidation_px': float(pos.get('liquidationPx', 0) or 0),
            'margin_used': float(pos.get('marginUsed', 0) or 0),
            'leverage': pos.get('leverage', {}).get('value'),
        })
    return out


# ============================================================
# Signed actions (place / cancel order)
# ============================================================

class ExpiredAgentError(RuntimeError):
    """HL agent wallet 已过期 (180 天). user 需重新授权."""


def place_order_live(
    symbol: str,
    side: str,
    size_usdt: float,
    leverage: float = 3.0,
    *,
    creds: dict | None = None,
    client_order_id: str | None = None,
    reduce_only: bool = False,
    order_type: str = 'market',
) -> dict:
    """市价/限价开仓 — 返回 HL response dict.

    side: 'buy' (long) | 'sell' (short)
    size_usdt: 名义 USDT, 实际 = size_usdt * leverage / price 张

    Phase 14k-6: caller 先 check expiry — _place_order in strategy_tasks
    用 user_id 拉 days_until_expiry, 已过期 → 直接 raise (而不是签名失败)
    """
    if not creds:
        raise RuntimeError('HL creds 必填 (per-user only; admin 用 OKX path)')
    exchange, info = _exchange_client(creds)
    base = hl_base(symbol)
    px = get_ticker(symbol, creds.get('network') or 'mainnet')['price']
    notional = size_usdt * leverage
    size_base = notional / px
    if size_base <= 0:
        raise ValueError('size 计算 ≤ 0')

    is_buy = side.lower() in ('buy', 'long')

    # 先设杠杆 (cross margin)
    try:
        exchange.update_leverage(int(leverage), base, is_cross=True)
    except Exception as e:
        # 已经是这个值会被 silent; 其他 raise
        if 'leverage' not in str(e).lower():
            log.warning(f'HL update_leverage {base} {leverage}x failed: {e}')

    # HL 用 IOC market or limit. 这里走 market_open helper (IOC).
    res = exchange.market_open(
        name=base,
        is_buy=is_buy,
        sz=round(size_base, 6),
        slippage=0.05,   # 5% max slippage
        cloid=None,      # SDK 内部生成
    )

    return {
        'ok': res.get('status') == 'ok',
        'raw': res,
        'symbol': symbol, 'base': base,
        'side': 'long' if is_buy else 'short',
        'size_base': round(size_base, 6),
        'notional_usdt': round(notional, 2),
        'leverage': leverage,
        'exchange': 'hyperliquid',
    }


def cancel_all_orders(creds: dict, symbol: str | None = None) -> dict:
    """撤所有 open orders (可选只 symbol)."""
    if not creds:
        raise RuntimeError('HL creds 必填')
    exchange, info = _exchange_client(creds)
    open_orders = info.open_orders(creds['main_address'])
    cancelled = 0
    errors = []
    for o in open_orders:
        base = o.get('coin')
        oid = o.get('oid')
        if symbol and hl_base(symbol) != base:
            continue
        try:
            exchange.cancel(base, oid)
            cancelled += 1
        except Exception as e:
            errors.append(f'{base}#{oid}: {e}')
    return {'cancelled': cancelled, 'errors': errors[:5]}
