"""Phase 14k-46: 守门切到动态 okx_meta — SUPPORTED_SYMBOLS 仅保留作"推荐种子".

旧 (Phase 9.1 ~ 14k-45):
  SUPPORTED_SYMBOLS hardcode 8 个 OKX SWAP → is_supported / get_contract_size 都 lookup 它.
  问题: OKX 一直在加币, hardcode 名单过期; symbol 不在里头时 get_contract_size silent
  fallback 0.01 (BTC 量级) → AI 推荐路径 _adapt_risk_to_capital 算出 position=0 空跑策略
  (14k-36 已经在 AI 推荐 stage 加 is_supported 守门遏制症状, 但根因 fallback 还在).

新 (14k-46):
  守门走 okx_meta — 真实 OKX instruments endpoint 1h 缓存. OKX 上 ~200+ USDT-SWAP
  全自动可用, 不用改代码. get_contract_size **不存在 raise**, 杜绝 silent 0 root cause.

  SUPPORTED_SYMBOLS dict 改成"推荐种子" — 主流稳定币 + 我们有 catalog 的, UI 推荐 /
  fan_out 默认列表用. 不再充当守门白名单.
"""

# 推荐种子 — 主流稳定币 + 系统 catalog 覆盖较全的. UI 推荐展示 / 默认 fan_out 用.
# 不是守门白名单 — 守门走 okx_meta (动态拉 OKX universe).
RECOMMENDED_SYMBOLS = {
    'BTC/USDT': {'category_hint': 'trend'},
    'ETH/USDT': {'category_hint': 'trend'},
    'SOL/USDT': {'category_hint': 'trend'},
    'AVAX/USDT': {'category_hint': 'trend'},
    'DOGE/USDT': {'category_hint': 'reversion'},
    'XRP/USDT':  {'category_hint': 'reversion'},
    'LINK/USDT': {'category_hint': 'trend'},
    'SUI/USDT':  {'category_hint': 'trend'},
}

# 旧名兼容 alias — 已有调用 import SUPPORTED_SYMBOLS 的地方不破. 内部不再用作守门.
SUPPORTED_SYMBOLS = RECOMMENDED_SYMBOLS


def is_supported(symbol: str, exchange: str | None = 'okx') -> bool:
    """这个 symbol 在指定 exchange 的 universe 里吗.

    14k-46.1: 加 exchange 参数. HL user 跟 OKX user 守门走不同 universe —
    HL universe ~200, OKX USDT-SWAP ~329, 交集大但不完全, HL 独有币不该被 OKX 拒.
    """
    ex = (exchange or 'okx').lower()

    if ex == 'hyperliquid':
        try:
            from app.services.hl_meta import is_hl_supported, _load_hl_universe
            if _load_hl_universe():  # cache 有数据
                return is_hl_supported(symbol)
        except Exception:
            pass
        # HL meta 完全没 cache → fallback 种子 (HL 主流币几乎都在)
        return symbol in RECOMMENDED_SYMBOLS

    # OKX (default)
    try:
        from app.services.okx_meta import is_okx_supported, _load_okx_instruments
        if _load_okx_instruments():
            return is_okx_supported(symbol)
    except Exception:
        pass
    return symbol in RECOMMENDED_SYMBOLS


def get_inst_id(symbol: str) -> str:
    """BTC/USDT -> BTC-USDT-SWAP. 优先 okx_meta, fallback 命名规则."""
    try:
        from app.services.okx_meta import get_okx_inst_id
        return get_okx_inst_id(symbol)
    except Exception:
        return symbol.replace('/', '-') + '-SWAP'


def get_contract_size(symbol: str) -> float:
    """每张合约对应多少 base ccy. **不存在 raise ValueError** (14k-46 根因修).

    旧版 silent return 0.01 → 上游 _adapt_risk_to_capital 算出 position=0 空跑.
    新版让调用方面对异常 — 要么过滤掉 unsupported, 要么显式 fallback.
    """
    try:
        from app.services.okx_meta import get_okx_contract_size, _load_okx_instruments
        if _load_okx_instruments():  # cache 有数据
            return get_okx_contract_size(symbol)
    except ValueError:
        raise  # okx_meta 已经 raise, 直接传
    except Exception:
        pass
    # okx_meta 完全挂掉 → 用种子 dict 兜底 (旧 hardcode 值)
    seed_ctvals = {
        'BTC/USDT': 0.01, 'ETH/USDT': 0.1, 'SOL/USDT': 1.0,
        'AVAX/USDT': 1.0, 'DOGE/USDT': 1000.0, 'XRP/USDT': 100.0,
        'LINK/USDT': 1.0, 'SUI/USDT': 1.0,
    }
    if symbol in seed_ctvals:
        return seed_ctvals[symbol]
    raise ValueError(f'symbols.get_contract_size: {symbol} 既不在 okx_meta cache 也不在 fallback 种子里')


def supported_list() -> list:
    """完整 OKX 可用列表 (动态). 失败时 fallback 推荐种子."""
    try:
        from app.services.okx_meta import _load_okx_instruments
        cache = _load_okx_instruments()
        if cache:
            return [{'symbol': k, **v} for k, v in cache.items()]
    except Exception:
        pass
    return [{'symbol': k, **v} for k, v in RECOMMENDED_SYMBOLS.items()]
