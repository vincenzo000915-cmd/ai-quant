"""Phase 9.1: 支援的交易對清單 + OKX SWAP 合約規格

合約大小（ctVal）來自 OKX instruments endpoint，這裡 hardcode 常見的避免每次 query。
未來要新增交易對：
  - 看 https://www.okx.com/priapi/v5/public/instruments?instType=SWAP&instId=XXX-USDT-SWAP
  - 加進 SUPPORTED_SYMBOLS dict
"""

SUPPORTED_SYMBOLS = {
    # symbol → { okx_inst_id, contract_size (base ccy per contract), category_hint }
    'BTC/USDT': {'okx_inst_id': 'BTC-USDT-SWAP', 'contract_size': 0.01,  'min_size': 1},
    'ETH/USDT': {'okx_inst_id': 'ETH-USDT-SWAP', 'contract_size': 0.1,   'min_size': 1},
    'SOL/USDT': {'okx_inst_id': 'SOL-USDT-SWAP', 'contract_size': 1.0,   'min_size': 1},
    'AVAX/USDT': {'okx_inst_id': 'AVAX-USDT-SWAP', 'contract_size': 1.0, 'min_size': 1},
    'DOGE/USDT': {'okx_inst_id': 'DOGE-USDT-SWAP', 'contract_size': 1000.0, 'min_size': 1},
    'XRP/USDT':  {'okx_inst_id': 'XRP-USDT-SWAP',  'contract_size': 100.0,  'min_size': 1},
    'LINK/USDT': {'okx_inst_id': 'LINK-USDT-SWAP', 'contract_size': 1.0,    'min_size': 1},
    'SUI/USDT':  {'okx_inst_id': 'SUI-USDT-SWAP',  'contract_size': 1.0,    'min_size': 1},
}


def is_supported(symbol: str) -> bool:
    return symbol in SUPPORTED_SYMBOLS


def get_inst_id(symbol: str) -> str:
    return SUPPORTED_SYMBOLS.get(symbol, {}).get('okx_inst_id') or symbol.replace('/', '-') + '-SWAP'


def get_contract_size(symbol: str) -> float:
    """每張合約對應多少 base currency。BTC = 0.01, ETH = 0.1, SOL = 1, DOGE = 1000, …"""
    return SUPPORTED_SYMBOLS.get(symbol, {}).get('contract_size', 0.01)


def supported_list() -> list:
    return [{'symbol': k, **v} for k, v in SUPPORTED_SYMBOLS.items()]
