"""Phase 12.24.2: 链上付款 polling — 自动确认 USDT 转账并开通订阅

每 60s 跑一次 check_all_chains():
  - 对每条 chain，拉 admin 主地址最近 50 条 incoming USDT tx
  - 对每条 tx，按 amount 精确匹配 pending invoices
  - 命中 → activate subscription + 标 confirmed + audit log

实现 3 条链（TRC + EVM 2 链）：
  - TRC20: TronGrid 公开 API (无 key 也能用)
  - ERC20: Etherscan API (有 key 更稳)
  - BEP20: BscScan API (有 key 更稳)
  - SOL: 留 placeholder (Helius / Solana RPC 较复杂)
"""
from __future__ import annotations

import decimal
import logging
import os
import time

import requests

from app.extensions import db
from app.models import PaymentInvoice
from app.services.subscription_service import activate_subscription_from_invoice
from app.services.audit import log as audit

logger = logging.getLogger(__name__)

# USDT contract addresses (各链上)
USDT_CONTRACTS = {
    'trc20': 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t',   # Tron USDT
    'erc20': '0xdAC17F958D2ee523a2206206994597C13D831ec7',  # Ethereum USDT
    'bep20': '0x55d398326f99059fF775485246999027B3197955',  # BSC USDT
    'sol':   'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB', # Solana USDT SPL
}

REQUEST_TIMEOUT = 12


def _admin_address(chain: str) -> str | None:
    """读 admin 收款地址 from .env"""
    mapping = {
        'trc20': 'USDT_TRC20_ADDRESS',
        'erc20': 'USDT_ERC20_ADDRESS',
        'bep20': 'USDT_BEP20_ADDRESS',
        'sol':   'USDT_SOL_ADDRESS',
    }
    env_key = mapping.get(chain)
    if not env_key:
        return None
    return (os.environ.get(env_key) or '').strip() or None


def _match_invoice(chain: str, amount: decimal.Decimal, tx_hash: str) -> PaymentInvoice | None:
    """按 (chain, amount, status=pending) 找匹配 invoice。

    精确金额匹配（USDT 6 decimals → 都用 Decimal）。
    如果同金额多张 invoice（理论上 dust suffix 保证唯一，但极端 collision），取最早一条。
    """
    # 防止重复处理：tx_hash 已用过则跳过
    used = PaymentInvoice.query.filter_by(tx_hash=tx_hash).first()
    if used:
        return None

    inv = PaymentInvoice.query.filter(
        PaymentInvoice.chain == chain,
        PaymentInvoice.status == 'pending',
        PaymentInvoice.amount_due == amount,
    ).order_by(PaymentInvoice.created_at.asc()).first()
    return inv


def _confirm(inv: PaymentInvoice, tx_hash: str, from_addr: str | None,
             received_amount: decimal.Decimal, block_number: int | None = None) -> None:
    """命中后开通订阅 + 标 confirmed + audit"""
    inv.tx_hash = tx_hash
    inv.tx_from_address = from_addr
    inv.tx_received_amount = received_amount
    inv.tx_block_number = block_number
    sub = activate_subscription_from_invoice(inv)
    audit('invoice_confirmed_onchain', actor='system',
          user_id=inv.user_id, invoice_id=inv.id,
          chain=inv.chain, tx_hash=tx_hash,
          plan=sub.plan, expires_at=sub.expires_at.isoformat() if sub.expires_at else None)
    logger.info(
        f'[onchain] confirmed invoice #{inv.id} user={inv.user_id} '
        f'plan={inv.plan} chain={inv.chain} amount={inv.amount_due} tx={tx_hash[:10]}...'
    )


# ============================================================
# TRC20 — TronGrid public API
# ============================================================

def check_tron_payments(limit: int = 50) -> dict:
    """轮询 Tron 链上 admin 地址 incoming USDT-TRC20 tx"""
    addr = _admin_address('trc20')
    if not addr:
        return {'ok': False, 'error': 'TRC20 地址未配置'}
    contract = USDT_CONTRACTS['trc20']
    headers = {}
    api_key = (os.environ.get('TRONGRID_API_KEY') or '').strip()
    if api_key:
        headers['TRON-PRO-API-KEY'] = api_key

    url = f'https://api.trongrid.io/v1/accounts/{addr}/transactions/trc20'
    params = {
        'contract_address': contract,
        'limit': limit,
        'only_to': 'true',
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {'ok': False, 'error': f'TronGrid 调用失败: {e}'}

    txs = data.get('data', [])
    confirmed = 0
    for tx in txs:
        try:
            tx_hash = tx.get('transaction_id')
            value_raw = tx.get('value', '0')
            # Tron USDT 6 decimals
            amount = decimal.Decimal(value_raw) / decimal.Decimal(1_000_000)
            amount = amount.quantize(decimal.Decimal('0.000001'))
            from_addr = tx.get('from', '')
            block_ts = tx.get('block_timestamp', 0)

            inv = _match_invoice('trc20', amount, tx_hash)
            if inv:
                _confirm(inv, tx_hash, from_addr, amount, block_number=None)
                confirmed += 1
        except Exception as e:
            logger.warning(f'[onchain trc] parse tx fail: {e}')
            continue

    return {'ok': True, 'chain': 'trc20', 'fetched': len(txs), 'confirmed': confirmed}


# ============================================================
# EVM — Etherscan / BscScan (同接口结构)
# ============================================================

def _check_evm(chain: str, api_url: str, api_key: str, contract: str) -> dict:
    addr = _admin_address(chain)
    if not addr:
        return {'ok': False, 'error': f'{chain} 地址未配置'}

    params = {
        'module': 'account',
        'action': 'tokentx',
        'contractaddress': contract,
        'address': addr,
        'sort': 'desc',
        'page': 1,
        'offset': 50,
    }
    if api_key:
        params['apikey'] = api_key

    try:
        r = requests.get(api_url, params=params, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {'ok': False, 'error': f'{chain} API 调用失败: {e}'}

    if str(data.get('status', '')) != '1':
        # 0 result 也算成功（没人付）
        msg = data.get('message', '')
        if 'No transactions found' in msg or 'OK' in msg:
            return {'ok': True, 'chain': chain, 'fetched': 0, 'confirmed': 0}
        return {'ok': False, 'error': f'{chain} API: {msg}'}

    txs = data.get('result', [])
    confirmed = 0
    addr_lc = addr.lower()
    for tx in txs:
        try:
            # 跳过 outgoing（admin 出币）
            if (tx.get('to') or '').lower() != addr_lc:
                continue
            tx_hash = tx.get('hash')
            value_raw = tx.get('value', '0')
            decimals = int(tx.get('tokenDecimal', '6'))
            amount = decimal.Decimal(value_raw) / decimal.Decimal(10 ** decimals)
            amount = amount.quantize(decimal.Decimal('0.000001'))
            from_addr = tx.get('from', '')
            block_num = int(tx.get('blockNumber', 0))

            inv = _match_invoice(chain, amount, tx_hash)
            if inv:
                _confirm(inv, tx_hash, from_addr, amount, block_number=block_num)
                confirmed += 1
        except Exception as e:
            logger.warning(f'[onchain {chain}] parse tx fail: {e}')
            continue

    return {'ok': True, 'chain': chain, 'fetched': len(txs), 'confirmed': confirmed}


def check_erc20_payments() -> dict:
    return _check_evm(
        chain='erc20',
        api_url='https://api.etherscan.io/api',
        api_key=(os.environ.get('ETHERSCAN_API_KEY') or '').strip(),
        contract=USDT_CONTRACTS['erc20'],
    )


def check_bep20_payments() -> dict:
    return _check_evm(
        chain='bep20',
        api_url='https://api.bscscan.com/api',
        api_key=(os.environ.get('BSCSCAN_API_KEY') or '').strip(),
        contract=USDT_CONTRACTS['bep20'],
    )


# ============================================================
# Solana (placeholder — 用 Helius API)
# ============================================================

def check_sol_payments(limit: int = 30) -> dict:
    """Solana SPL USDT 监听
    优先 Helius（更快 + 解析好），无 key 则 fallback public RPC
      (getSignaturesForAddress + getTransaction)
    """
    addr = _admin_address('sol')
    if not addr:
        return {'ok': False, 'error': 'SOL 地址未配置'}

    helius_key = (os.environ.get('HELIUS_API_KEY') or '').strip()
    if helius_key:
        return _check_sol_via_helius(addr, helius_key, limit)
    return _check_sol_via_rpc(addr, limit)


def _check_sol_via_helius(addr: str, key: str, limit: int) -> dict:
    url = f'https://api.helius.xyz/v0/addresses/{addr}/transactions'
    params = {'api-key': key, 'limit': limit, 'type': 'TRANSFER'}
    try:
        r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        txs = r.json()
    except Exception as e:
        return {'ok': False, 'error': f'Helius 调用失败: {e}'}

    usdt_mint = USDT_CONTRACTS['sol']
    confirmed = 0
    for tx in txs[:limit]:
        try:
            sig = tx.get('signature')
            block_time = tx.get('timestamp')
            for transfer in (tx.get('tokenTransfers') or []):
                if transfer.get('mint') != usdt_mint:
                    continue
                if transfer.get('toUserAccount') != addr:
                    continue
                amount = decimal.Decimal(str(transfer.get('tokenAmount', 0))).quantize(decimal.Decimal('0.000001'))
                from_addr = transfer.get('fromUserAccount', '')
                inv = _match_invoice('sol', amount, sig)
                if inv:
                    _confirm(inv, sig, from_addr, amount, block_number=block_time)
                    confirmed += 1
                    break
        except Exception as e:
            logger.warning(f'[onchain sol helius] parse tx fail: {e}')
    return {'ok': True, 'chain': 'sol', 'fetched': len(txs), 'confirmed': confirmed, 'source': 'helius'}


def _check_sol_via_rpc(addr: str, limit: int) -> dict:
    """无 Helius key fallback — 公共 Solana mainnet RPC
    流程：getSignaturesForAddress → 对每个 sig 调 getTransaction → 解析 SPL transfer
    限速：公共 RPC 每秒 < 5 次，所以 limit 调小（30）。Helius free quota 更高。
    """
    rpc = 'https://api.mainnet-beta.solana.com'
    headers = {'Content-Type': 'application/json'}

    # 1. 拉最近签名
    try:
        r = requests.post(rpc, headers=headers, json={
            'jsonrpc': '2.0', 'id': 1,
            'method': 'getSignaturesForAddress',
            'params': [addr, {'limit': limit}],
        }, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        sigs_data = r.json().get('result', [])
    except Exception as e:
        return {'ok': False, 'error': f'Solana RPC getSignatures 失败: {e}'}

    usdt_mint = USDT_CONTRACTS['sol']
    confirmed = 0
    fetched = 0

    for sig_info in sigs_data:
        sig = sig_info.get('signature')
        if not sig:
            continue
        # 已 confirmed 过的 tx hash 跳过节省 RPC
        if PaymentInvoice.query.filter_by(tx_hash=sig).first():
            continue
        # 2. 拉 tx 详情
        try:
            r = requests.post(rpc, headers=headers, json={
                'jsonrpc': '2.0', 'id': 1,
                'method': 'getTransaction',
                'params': [sig, {'encoding': 'jsonParsed', 'maxSupportedTransactionVersion': 0}],
            }, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            tx_data = (r.json() or {}).get('result')
            fetched += 1
        except Exception as e:
            logger.warning(f'[onchain sol rpc] getTx {sig[:8]}.. failed: {e}')
            continue
        if not tx_data:
            continue
        # 3. 解析 instructions
        try:
            block_time = tx_data.get('blockTime')
            instructions = (tx_data.get('transaction', {}).get('message', {}).get('instructions') or [])
            for ix in instructions:
                if ix.get('program') != 'spl-token':
                    continue
                parsed = ix.get('parsed') or {}
                if parsed.get('type') not in ('transfer', 'transferChecked'):
                    continue
                info = parsed.get('info', {})
                # transfer 不含 mint；transferChecked 含 mint
                if info.get('mint') and info.get('mint') != usdt_mint:
                    continue
                if info.get('destination') and info.get('destination') != addr:
                    continue
                token_amount = info.get('tokenAmount') or {}
                ui_amount = token_amount.get('uiAmountString')
                if ui_amount is None and 'amount' in info:
                    decimals = int(token_amount.get('decimals', 6))
                    ui_amount = decimal.Decimal(info['amount']) / decimal.Decimal(10 ** decimals)
                if ui_amount is None:
                    continue
                amount = decimal.Decimal(str(ui_amount)).quantize(decimal.Decimal('0.000001'))
                from_addr = info.get('source') or info.get('authority')

                inv = _match_invoice('sol', amount, sig)
                if inv:
                    _confirm(inv, sig, from_addr, amount, block_number=block_time)
                    confirmed += 1
                    break
        except Exception as e:
            logger.warning(f'[onchain sol rpc] parse {sig[:8]}.. failed: {e}')
            continue

    return {'ok': True, 'chain': 'sol', 'fetched': fetched, 'confirmed': confirmed, 'source': 'public_rpc'}


# ============================================================
# All chains
# ============================================================

# ============================================================
# Phase 12.24.4: 单 tx 验证 — 给「用户手动上传 tx hash」走自动验证
# ============================================================

def verify_tx_hash(chain: str, tx_hash: str) -> dict:
    """查链上拿到指定 tx 详情。返回 {ok, to, amount, from, confirmations, error?}

    用于：用户付款后 polling 5min 没识别，手动上传 tx hash 时立即验证。
    """
    if chain == 'trc20':
        return _verify_tron_tx(tx_hash)
    if chain in ('erc20', 'bep20'):
        return _verify_evm_tx(chain, tx_hash)
    if chain == 'sol':
        return _verify_sol_tx(tx_hash)
    return {'ok': False, 'error': f'unknown chain: {chain}'}


def _verify_tron_tx(tx_hash: str) -> dict:
    headers = {}
    api_key = (os.environ.get('TRONGRID_API_KEY') or '').strip()
    if api_key:
        headers['TRON-PRO-API-KEY'] = api_key
    # 用 trongrid /v1/transactions/{hash}/events 拿 TRC20 transfer event
    url = f'https://api.trongrid.io/v1/transactions/{tx_hash}/events'
    try:
        r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {'ok': False, 'error': f'TronGrid 查询失败: {e}'}

    events = data.get('data', [])
    usdt_contract = USDT_CONTRACTS['trc20']
    for ev in events:
        if ev.get('contract_address') != usdt_contract:
            continue
        if ev.get('event_name') != 'Transfer':
            continue
        result = ev.get('result', {})
        to_addr = result.get('to', '')
        from_addr = result.get('from', '')
        # value is integer string in token wei (6 decimals)
        value_raw = result.get('value', '0')
        try:
            amount = decimal.Decimal(value_raw) / decimal.Decimal(1_000_000)
            amount = amount.quantize(decimal.Decimal('0.000001'))
        except Exception:
            continue
        return {
            'ok': True, 'chain': 'trc20',
            'to': to_addr, 'from': from_addr,
            'amount': amount, 'confirmations': 1,  # TronGrid 不直接给 confirmations
        }
    return {'ok': False, 'error': 'tx 不是 USDT-TRC20 transfer 或 tx 不存在'}


def _verify_evm_tx(chain: str, tx_hash: str) -> dict:
    """ETH / BSC: tokentx API 直接查 tx hash"""
    if chain == 'erc20':
        api_url = 'https://api.etherscan.io/api'
        api_key = (os.environ.get('ETHERSCAN_API_KEY') or '').strip()
        contract = USDT_CONTRACTS['erc20']
    else:  # bep20
        api_url = 'https://api.bscscan.com/api'
        api_key = (os.environ.get('BSCSCAN_API_KEY') or '').strip()
        contract = USDT_CONTRACTS['bep20']

    # tokentx by tx hash 不直接支持，需要先 eth_getTransactionByHash 看 to / from
    # Etherscan: action=transaction&txhash=...
    params = {
        'module': 'proxy',
        'action': 'eth_getTransactionByHash',
        'txhash': tx_hash,
    }
    if api_key:
        params['apikey'] = api_key
    try:
        r = requests.get(api_url, params=params, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {'ok': False, 'error': f'{chain} 查询失败: {e}'}

    result = data.get('result') or {}
    if not result:
        return {'ok': False, 'error': 'tx hash 不存在或链上未确认'}

    # 检查 to 是否 USDT contract
    if (result.get('to') or '').lower() != contract.lower():
        return {'ok': False, 'error': 'tx 不是 USDT 转账（contract 不匹配）'}

    # 解析 input data: USDT transfer(address,uint256) 的 selector 是 0xa9059cbb
    # input = 0xa9059cbb + 32 bytes to + 32 bytes amount
    input_data = result.get('input', '')
    if not input_data.lower().startswith('0xa9059cbb'):
        return {'ok': False, 'error': 'tx 不是 ERC20 transfer 调用'}
    try:
        to_addr = '0x' + input_data[34:74]   # 取 32-byte 后 20 byte
        value_hex = input_data[74:138]
        amount_raw = int(value_hex, 16)
        amount = decimal.Decimal(amount_raw) / decimal.Decimal(10 ** 6)  # USDT 6 decimals
        amount = amount.quantize(decimal.Decimal('0.000001'))
    except Exception as e:
        return {'ok': False, 'error': f'解析 transfer input 失败: {e}'}

    return {
        'ok': True, 'chain': chain,
        'to': to_addr, 'from': result.get('from'),
        'amount': amount,
        'confirmations': 1,
        'block_number': int(result.get('blockNumber', '0x0'), 16),
    }


def _verify_sol_tx(tx_hash: str) -> dict:
    """Solana: 用 public RPC getTransaction 解析 SPL transfer

    无需 Helius key，公共 RPC 也能用（限速但够单次查询）。
    """
    rpc = 'https://api.mainnet-beta.solana.com'
    try:
        r = requests.post(rpc, json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'getTransaction',
            'params': [tx_hash, {'encoding': 'jsonParsed', 'maxSupportedTransactionVersion': 0}],
        }, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {'ok': False, 'error': f'Solana RPC 查询失败: {e}'}

    result = data.get('result')
    if not result:
        return {'ok': False, 'error': 'Solana tx 不存在或未确认'}

    # 找 SPL transfer instruction
    usdt_mint = USDT_CONTRACTS['sol']
    instructions = (result.get('transaction', {}).get('message', {}).get('instructions') or [])
    for ix in instructions:
        if ix.get('program') != 'spl-token':
            continue
        info = (ix.get('parsed') or {}).get('info', {})
        if info.get('mint') != usdt_mint:
            # 有些 transfer 不含 mint 字段，看是否 transferChecked
            pass
        ix_type = (ix.get('parsed') or {}).get('type', '')
        if ix_type not in ('transfer', 'transferChecked'):
            continue
        token_amount = info.get('tokenAmount') or {}
        ui_amount = token_amount.get('uiAmountString')
        if ui_amount is None and 'amount' in info:
            decimals = int(token_amount.get('decimals', 6))
            try:
                ui_amount = decimal.Decimal(info['amount']) / decimal.Decimal(10 ** decimals)
            except Exception:
                continue
        try:
            amount = decimal.Decimal(str(ui_amount))
            amount = amount.quantize(decimal.Decimal('0.000001'))
        except Exception:
            continue
        return {
            'ok': True, 'chain': 'sol',
            'to': info.get('destination'),
            'from': info.get('source') or info.get('authority'),
            'amount': amount,
            'confirmations': 1,
            'block_time': result.get('blockTime'),
        }

    return {'ok': False, 'error': '未找到 SPL USDT transfer instruction'}


def check_all_chains() -> list[dict]:
    """跑所有链。返回每链结果列表。

    Celery beat task 调这个。失败的链不影响其他链。
    """
    results = []
    for fn in (check_tron_payments, check_erc20_payments, check_bep20_payments, check_sol_payments):
        try:
            r = fn()
            results.append(r)
            if r.get('confirmed', 0) > 0:
                logger.info(f'[onchain] {r["chain"]}: confirmed {r["confirmed"]} new invoices')
        except Exception as e:
            results.append({'ok': False, 'error': str(e), 'fn': fn.__name__})
            logger.exception(f'[onchain] {fn.__name__} crashed')
    return results
