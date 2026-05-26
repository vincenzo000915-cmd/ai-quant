"""Phase 14k-46.1: Hyperliquid universe 动态 meta + 1h 缓存. 对称 okx_meta.

旧法 _hl_min_notional 每次拉 meta 不缓存 (strategy_recommend.py:101). 加这层缓存
+ 提供 is_hl_supported / get_hl_meta 给 symbols.is_supported 在 HL 分支用.
"""
import logging
import threading
import time

logger = logging.getLogger(__name__)

_CACHE: dict = {}      # base name "BTC" -> universe entry
_CACHE_TS: float = 0.0
_CACHE_TTL = 3600
_CACHE_LOCK = threading.Lock()


def _symbol_to_base(symbol: str) -> str:
    """BTC/USDT -> BTC (HL 用 base name 不是 BTC/USDT)."""
    if not symbol:
        return ''
    return symbol.split('/')[0].split(':')[0].upper()


def _load_hl_universe(force: bool = False) -> dict:
    """拉 HL info.meta() universe, 缓存 1h. base name -> entry dict."""
    global _CACHE, _CACHE_TS

    with _CACHE_LOCK:
        now = time.time()
        if not force and _CACHE and (now - _CACHE_TS) < _CACHE_TTL:
            return _CACHE

        try:
            from app.services.hyperliquid_service import _info_client
            info = _info_client('mainnet')
            meta = info.meta()
        except Exception as e:
            logger.warning(f'hl_meta: meta fetch failed: {e}; using stale cache (entries={len(_CACHE)})')
            return _CACHE

        new_cache = {}
        for u in (meta.get('universe') or []):
            name = (u.get('name') or '').upper()
            if not name:
                continue
            new_cache[name] = u

        if not new_cache:
            logger.warning(f'hl_meta: parsed 0 universe entries; keeping stale cache')
            return _CACHE

        _CACHE = new_cache
        _CACHE_TS = now
        logger.info(f'hl_meta: refreshed {len(_CACHE)} HL universe entries')
        return _CACHE


def is_hl_supported(symbol: str) -> bool:
    """HL universe 里有这个 base. cache 拉失败 + 没旧 cache 时 return False (保守)."""
    base = _symbol_to_base(symbol)
    if not base:
        return False
    return base in _load_hl_universe()


def get_hl_entry(symbol: str) -> dict | None:
    """HL universe entry (含 szDecimals 等). None = 不在."""
    base = _symbol_to_base(symbol)
    if not base:
        return None
    return _load_hl_universe().get(base)


def supported_hl_symbols() -> list[str]:
    """HL USDC-perp universe (base name 列表)."""
    return sorted(_load_hl_universe().keys())
