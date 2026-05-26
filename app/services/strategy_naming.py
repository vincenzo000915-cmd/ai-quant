"""策略命名 helper — 取代直接暴露 candidate_type 给 UI

主路径：catalog entry 在 catalog_meta 里写 display_name (中文)。
Fallback：未来 AI invent 或爬虫候选若没 display_name，prettify candidate_type 也好过 `cat_xxx_uN_<timestamp>` 这种暴露。
"""
import re


def prettify_candidate_type(candidate_type: str | None) -> str:
    """`cat_ttm_squeeze_u1_20260525160550` → `Ttm Squeeze`

    剥 catalog clone 后缀 + cat_ 前缀 + snake → Title Case.
    """
    if not candidate_type:
        return '未命名策略'
    t = candidate_type
    t = re.sub(r'_u\d+_\d{12,16}$', '', t)
    if t.startswith('cat_'):
        t = t[4:]
    if t.endswith('_signal'):
        t = t[:-len('_signal')]
    return ' '.join(p.capitalize() for p in t.split('_') if p) or '未命名策略'


def display_name_for_candidate(candidate) -> str:
    """优先取 catalog_meta.display_name (主路径)，否则 prettify candidate_type。"""
    cm = getattr(candidate, 'catalog_meta', None) or {}
    name = cm.get('display_name')
    if name:
        return name
    sm = getattr(candidate, 'source_meta', None) or {}
    name = sm.get('display_name')
    if name:
        return name
    return prettify_candidate_type(getattr(candidate, 'candidate_type', None))


def format_strategy_name(candidate, symbol: str | None = None) -> str:
    """promote 时给 strategy.name 用 — `BTC/USDT · TTM 挤压突破 · #130`."""
    disp = display_name_for_candidate(candidate)
    cid = getattr(candidate, 'id', None)
    sym = symbol or ((candidate.source_meta or {}).get('symbol') if getattr(candidate, 'source_meta', None) else None)
    parts = []
    if sym:
        parts.append(sym)
    parts.append(disp)
    if cid:
        parts.append(f'#{cid}')
    return ' · '.join(parts)
