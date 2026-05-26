"""Phase 14k-46: OKX SWAP instruments 动态拉取 + 1h 缓存.

对称 hyperliquid_service.meta() 的 HL 做法 — 不再 hardcode SUPPORTED_SYMBOLS,
直接从 OKX 拉真实合约规格. 上线新币 OKX 上了就能跑, 不用改代码.

被 symbols.py 用来做 is_supported / get_contract_size / get_inst_id 的动态后端.
"""
import logging
import threading
import time

logger = logging.getLogger(__name__)

_CACHE: dict = {}      # symbol "BTC/USDT" -> instrument dict
_CACHE_TS: float = 0.0
_CACHE_TTL = 3600      # 1h — OKX 上新合约不频繁, 但又不能永久缓存防漂移
_CACHE_LOCK = threading.Lock()


def _inst_id_to_symbol(inst_id: str) -> str | None:
    """BTC-USDT-SWAP -> BTC/USDT. 只处理 USDT-margined SWAP."""
    if not inst_id.endswith('-USDT-SWAP'):
        return None
    base = inst_id[:-len('-USDT-SWAP')]
    if not base or '-' in base:
        return None
    return f'{base}/USDT'


def _load_okx_instruments(force: bool = False) -> dict:
    """拉 OKX /api/v5/public/instruments?instType=SWAP 全量, 缓存 1h.

    Return: {'BTC/USDT': {'okx_inst_id', 'contract_size', 'min_size', 'lot_size', 'tick_size'}}
    缓存失败时返回 stale cache; 都没有则返回 {}.
    """
    global _CACHE, _CACHE_TS

    with _CACHE_LOCK:
        now = time.time()
        if not force and _CACHE and (now - _CACHE_TS) < _CACHE_TTL:
            return _CACHE

        try:
            from app.services.exchange_service import _okx_get
            data = _okx_get('/api/v5/public/instruments', {'instType': 'SWAP'})
        except Exception as e:
            logger.warning(f'okx_meta: instruments fetch failed: {e}; using stale cache (entries={len(_CACHE)})')
            return _CACHE  # 网络失败保留旧缓存

        new_cache = {}
        for inst in data or []:
            inst_id = inst.get('instId') or ''
            sym = _inst_id_to_symbol(inst_id)
            if not sym:
                continue
            # 守 state — OKX 偶尔会 list 即将上线 / 已下架的合约
            if (inst.get('state') or 'live') != 'live':
                continue
            try:
                ct_val = float(inst.get('ctVal') or 0)
                lot_sz = float(inst.get('lotSz') or 1)
                min_sz = float(inst.get('minSz') or 1)
                tick_sz = float(inst.get('tickSz') or 0)
            except (TypeError, ValueError):
                continue
            if ct_val <= 0:
                continue
            new_cache[sym] = {
                'okx_inst_id': inst_id,
                'contract_size': ct_val,
                'min_size': int(min_sz) if min_sz >= 1 else min_sz,
                'lot_size': lot_sz,
                'tick_size': tick_sz,
            }

        if not new_cache:
            logger.warning(f'okx_meta: parsed 0 instruments from {len(data or [])} entries; keeping stale cache')
            return _CACHE

        _CACHE = new_cache
        _CACHE_TS = now
        logger.info(f'okx_meta: refreshed {len(_CACHE)} USDT-SWAP instruments')
        return _CACHE


def is_okx_supported(symbol: str) -> bool:
    """OKX 上有这个 USDT-SWAP 合约且 state=live."""
    return symbol in _load_okx_instruments()


def get_okx_instrument(symbol: str) -> dict | None:
    """完整 instrument 元数据. None = 不存在."""
    return _load_okx_instruments().get(symbol)


def get_okx_contract_size(symbol: str) -> float:
    """每张合约对应多少 base ccy. **不存在 raise ValueError** — 杜绝静默 fallback 算出 position=0 (14k-36 根因)."""
    inst = _load_okx_instruments().get(symbol)
    if inst is None:
        raise ValueError(f'okx_meta: {symbol} 不在 OKX USDT-SWAP universe (拉取 {len(_load_okx_instruments())} 实盘合约)')
    return float(inst['contract_size'])


def get_okx_inst_id(symbol: str) -> str:
    """BTC/USDT -> BTC-USDT-SWAP. 不存在 fallback 命名规则（兼容旧调用）."""
    inst = _load_okx_instruments().get(symbol)
    if inst:
        return inst['okx_inst_id']
    return symbol.replace('/', '-') + '-SWAP'


def supported_okx_symbols() -> list[str]:
    """全部 OKX USDT-SWAP universe (按字母排序)."""
    return sorted(_load_okx_instruments().keys())
