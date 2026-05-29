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


# ============================================================
# Phase 15 P0b: 微观数据 (盘感输入层) — funding 历史(可回测) + l2 盘口失衡(前向)
# ============================================================

def fetch_funding(symbol: str, lookback_hours: int = 24,
                  network: str = 'mainnet') -> list:
    """HL 资金费率历史. 返回 [{timestamp(秒), funding_rate, premium}, ...] 旧→新.
    info.funding_history(coin, startTimeMs) — 有历史 API, 可回放种子日 (进 P2 回测)."""
    import time
    info = _info_client(network)
    base = hl_base(symbol)
    start_ms = int(time.time() * 1000) - lookback_hours * 3600 * 1000
    raw = info.funding_history(base, start_ms) or []
    out = []
    for r in raw:
        try:
            out.append({
                'timestamp': int(r['time']) // 1000,
                'funding_rate': float(r['fundingRate']),
                'premium': float(r['premium']) if r.get('premium') is not None else None,
            })
        except (KeyError, ValueError, TypeError):
            continue
    out.sort(key=lambda x: x['timestamp'])
    return out


def fetch_l2_features(symbol: str, depth: int = 5,
                      network: str = 'mainnet') -> dict:
    """HL 盘口快照 → 派生失衡特征 (止损猎场地图). 实时, 无历史.
    info.l2_snapshot(coin) → levels=[bids, asks], 每档 {px, sz, n}.

    返回 {mid, best_bid, best_ask, spread_bps, imbalance, bid_depth, ask_depth, ok}.
    imbalance = 近 depth 档 (bid_sz - ask_sz)/(bid_sz + ask_sz): 正=买压堆积/负=卖压.
    判断层用法 (project-edge-ideas): 失衡极端 + 价逼近显眼位 → 翻转默认假设 (放量插破不跟进)."""
    info = _info_client(network)
    base = hl_base(symbol)
    book = info.l2_snapshot(base)
    levels = (book or {}).get('levels') or []
    if len(levels) < 2 or not levels[0] or not levels[1]:
        return {'ok': False, 'reason': 'l2 盘口为空'}
    bids, asks = levels[0][:depth], levels[1][:depth]
    best_bid = float(bids[0]['px'])
    best_ask = float(asks[0]['px'])
    mid = (best_bid + best_ask) / 2.0
    bid_depth = sum(float(b['sz']) for b in bids)
    ask_depth = sum(float(a['sz']) for a in asks)
    denom = bid_depth + ask_depth
    imbalance = ((bid_depth - ask_depth) / denom) if denom > 0 else 0.0
    spread_bps = ((best_ask - best_bid) / mid * 1e4) if mid > 0 else None
    return {
        'ok': True, 'mid': mid, 'best_bid': best_bid, 'best_ask': best_ask,
        'spread_bps': round(spread_bps, 3) if spread_bps is not None else None,
        'imbalance': round(imbalance, 4),
        'bid_depth': round(bid_depth, 4), 'ask_depth': round(ask_depth, 4),
    }


_HL_STABLECOINS = ('USDC', 'USDT0', 'USDH', 'USDE')


def fetch_balance(creds: dict) -> dict:
    """Phase 14k-9 + 14k-105: HL Unified Account 余额 — 修 double-count

    14k-9 原逻辑: total = spot + perp_accountValue
    14k-105 修: HL Unified 下 spot USDC **本身就是** perp collateral
      perp accountValue 含: 已 reserved 的 spot USDC + unrealizedPnl
      spot + accountValue 会重复算 collateral 那部分 (实测多算 $5 / margin_used)

    正确: total = spot + unrealized (or 等价 spot + (accountValue - margin_used))
      实测: spot 70.32 + (4.98 - 5.03) = 70.27 ≈ 真实总值 (含 ETH 浮亏 -$0.05)
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
    # 14k-105: 算 sum of unrealizedPnl across all positions
    perp_upl = 0.0
    for ap in (state.get('assetPositions') or []):
        try:
            perp_upl += float((ap.get('position') or {}).get('unrealizedPnl') or 0)
        except (TypeError, ValueError):
            pass

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
        spot_breakdown['_error'] = str(e)[:80]

    # 14k-105: total = spot + unrealized (accountValue 已含 spot 那部分, double-count fix)
    total = spot_total + perp_upl
    # free: 可立即取 (spot 总 - 已用作 perp margin)
    free = max(0.0, spot_total - perp_margin_used)

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
            'perp_unrealized_pnl': round(perp_upl, 4),
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


def fetch_order_real_pnl(symbol: str, oid: int | str | None = None,
                          max_wait_sec: float = 5.0,
                          creds: dict | None = None) -> dict:
    """Phase 14k-86: 查 HL 真实成交盈亏 + 手续费 (对应 OKX fetch_okx_order_real_pnl)

    HL info.user_fills 返回最近 fills, 每条含:
      coin / px / sz / side / time / closedPnl / fee / oid / tid / dir / hash
    closedPnl = 平仓时实现的 PnL (HL 内部已扣 funding)
    fee = 该笔手续费 (正值, USDC)

    返回 OKX-compat shape:
      {price_pnl, fee, real_pnl, fill_count, found, error?}
      price_pnl = closedPnl 合计 (HL 给的 "实现 PnL", 不含 fee)
      fee = -|fee 合计| (负值表 outflow, 跟 OKX 一致)
      real_pnl = price_pnl + fee (净影响余额)
    """
    import time as _time
    if not creds or not creds.get('main_address'):
        return {'price_pnl': 0.0, 'fee': 0.0, 'real_pnl': 0.0,
                'found': False, 'fill_count': 0, 'error': 'no HL creds'}

    base = hl_base(symbol)
    main = creds['main_address']
    network = creds.get('network') or 'mainnet'

    def _scan() -> tuple[list, str | None]:
        try:
            info = _info_client(network)
            fills = info.user_fills(main) or []
        except Exception as e:
            return [], str(e)
        matches = []
        for f in fills:
            if f.get('coin') != base:
                continue
            # oid 可能是 int 或 str, HL 实际是 int
            if oid is not None and str(f.get('oid')) != str(oid):
                continue
            matches.append(f)
        return matches, None

    deadline = _time.time() + max_wait_sec
    last_err = None
    prev_count = -1
    matches: list = []
    while _time.time() < deadline:
        ms, err = _scan()
        if err:
            last_err = err
        elif ms and len(ms) == prev_count:
            matches = ms
            break
        elif ms:
            matches = ms
            prev_count = len(ms)
        _time.sleep(0.5)

    if not matches:
        return {'price_pnl': 0.0, 'fee': 0.0, 'real_pnl': 0.0,
                'found': False, 'fill_count': 0, 'error': last_err}

    price_pnl = sum(float(m.get('closedPnl') or 0) for m in matches)
    total_fee = sum(float(m.get('fee') or 0) for m in matches)
    # HL fee 是正值 (代表你付了多少), 转为负值跟 OKX shape 一致
    fee_signed = -abs(total_fee)
    return {
        'price_pnl': round(price_pnl, 6),
        'fee': round(fee_signed, 6),
        'real_pnl': round(price_pnl + fee_signed, 6),
        'found': True,
        'fill_count': len(matches),
    }


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
    """市价/限价开仓 OR 平仓 (reduce_only=True) — 返回 HL response dict.

    side: 'buy' (long) | 'sell' (short) — open 用; close 时 SDK 自动按现有 position 反向
    size_usdt:
      - open (reduce_only=False): 名义 USDT (无 leverage), 实际 = size_usdt * leverage / price 张
      - close (reduce_only=True): 名义 USDT (含真实 size 已乘 leverage), 实际 = size_usdt / price 张

    Phase 14k-6: caller 先 check expiry — _place_order in strategy_tasks
    Phase 14k-110: close 路径 size 不再乘 leverage + 改走 market_close (SDK 内部 reduce_only=True)
      旧 bug: close 时 caller 传 pos.size*price (裸 notional 无 leverage), 函数无论何路径都乘
      leverage 算 size → 真发 leverage× size BUY → 平 + 反向开 leverage× 仓.
      ETH #33 短仓 0.0073 平仓后变 0.0145 long (lev=2);
      DOGE #34 短仓 249 平仓后变 1246 long (lev=5).
    """
    if not creds:
        raise RuntimeError('HL creds 必填 (per-user only; admin 用 OKX path)')
    exchange, info = _exchange_client(creds)
    base = hl_base(symbol)
    px = get_ticker(symbol, creds.get('network') or 'mainnet')['price']

    # Phase 14k-110: close 路径 size_usdt 已是真实 close 名义 (含 leverage),
    # 不该再乘 leverage. 否则 close 变 leverage× BUY 把短仓平掉的同时反向开 long.
    if reduce_only:
        notional = size_usdt
    else:
        notional = size_usdt * leverage
    size_base = notional / px
    if size_base <= 0:
        raise ValueError('size 计算 ≤ 0')

    # Phase 14k-101: 按 HL meta 的 szDecimals round size — 否则 "Order has invalid size"
    # 实测今早 3 笔 AVAX orphan close 根因: AVAX szDecimals=2 但 code round 到 6 decimals
    # BTC=5 / ETH=4 / SOL=AVAX=2 / ARB=SUI=LINK=1 / DOGE=0 — 必须按 coin 精度截
    try:
        from app.services.hl_meta import get_hl_entry
        entry = get_hl_entry(symbol)
        sz_dec = int(entry.get('szDecimals')) if entry else 6
    except Exception:
        sz_dec = 6   # fallback (保守, 多数 coin 6 位够)
    size_base_rounded = round(size_base, sz_dec)
    if size_base_rounded <= 0:
        raise ValueError(f'size {size_base} 按 szDecimals={sz_dec} round 后 = 0 (size_usdt 太小)')

    is_buy = side.lower() in ('buy', 'long')

    # 14k-110: leverage 只在 open 时设 (close 不该改 leverage)
    if not reduce_only:
        try:
            exchange.update_leverage(int(leverage), base, is_cross=True)
        except Exception as e:
            # 已经是这个值会被 silent; 其他 raise
            if 'leverage' not in str(e).lower():
                log.warning(f'HL update_leverage {base} {leverage}x failed: {e}')

    # Phase 14k-110: reduce_only 用 SDK market_close (内部 reduce_only=True 守住, 不会反向开仓)
    if reduce_only:
        res = exchange.market_close(
            coin=base,
            sz=size_base_rounded,
            slippage=0.05,
            cloid=None,
        )
    else:
        # HL 用 IOC market or limit. 这里走 market_open helper (IOC).
        res = exchange.market_open(
            name=base,
            is_buy=is_buy,
            sz=size_base_rounded,   # 14k-101: 按 szDecimals 精度
            slippage=0.05,   # 5% max slippage
            cloid=None,      # SDK 内部生成
        )

    # Phase 14k-85: 真校验订单成交, 不只看 outer status
    # HL response: outer status='ok' = 请求合法, 实际 fill/reject 在 statuses[0]
    #   {filled: {oid, totalSz, avgPx}} = 成交 (我们要的)
    #   {error: "Insufficient margin / Min size / ..."} = REJECTED (但 outer 仍 'ok')
    #   {resting: {oid}} = limit order pending (market 单不该出)
    # 之前 bug: 只看 outer ok=True → 本地写 Position → HL 上没仓 → reconcile 误关
    outer_ok = res.get('status') == 'ok'
    statuses = (res.get('response') or {}).get('data', {}).get('statuses') or []
    first_status = statuses[0] if statuses else {}
    filled_ok = 'filled' in first_status
    reject_error = first_status.get('error') if isinstance(first_status, dict) else None

    return {
        'ok': bool(outer_ok and filled_ok),
        'raw': res,
        'symbol': symbol, 'base': base,
        'side': 'long' if is_buy else 'short',
        'size_base': size_base_rounded,   # 14k-101: 真发出的 size (已按 szDecimals round)
        'notional_usdt': round(notional, 2),
        'leverage': leverage,
        'sz_decimals': sz_dec,             # 14k-101: debug 用
        'exchange': 'hyperliquid',
        'reject_reason': reject_error,    # 14k-85: caller 可看具体被拒原因
        'status_kind': ('filled' if filled_ok else
                        ('rejected' if reject_error else
                         ('resting' if 'resting' in first_status else 'unknown'))),
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
