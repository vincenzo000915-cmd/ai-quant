"""Phase 15 地基: 策略理解层 — AI 读策略源码 → 生成结构化"策略画像"

蓝图 project-phase15-blueprint。user 2026-05-29 点破的地基:
  **守门员/AI 不懂策略在做什么 → 回测就是空洞数字游戏(儿戏)**。必须先让 AI 读懂每个策略:
  用什么指标、进场逻辑、适合什么行情/周期、edge 来源、什么环境失效。
  有了画像, AI 选策略(这小时用A下小时用B)、守门员回测(用对行情段+解读错配vs没用)、调参 才不是盲的。

画像供: ① AI 决策(advisor/合成/选策略)理解策略 ② 守门员回测时选对行情段+正确解读结果
        ③ 分清"策略没用 vs 周期/行情/参数错配"(user核心: 不可能策略没用, 大部分是参数没对)。
"""
from __future__ import annotations

import json

PROFILE_SCHEMA = {
    "indicators": ["用了哪些技术指标, 如 Donchian通道(20) / MACD / RSI / ATR"],
    "entry_logic": "进场逻辑一句话: 什么条件做多 / 什么条件做空",
    "direction": "long | short | both",
    "regime_fit": {"trend": "good|ok|bad", "range": "good|ok|bad"},
    "timeframe_fit": ["适合的周期, 如 1h / 4h (趋势类偏大周期; 均值回归类可小周期)"],
    "edge_source": "edge 来源/为什么有效 (捕捉什么市场行为)",
    "weakness": "什么环境会失效/被坑 (如震荡假突破、小周期噪音)",
    "summary_zh": "一句话中文画像",
}

SYSTEM_PROMPT = """你是量化策略分析师. 我给你一个交易策略的 signal_fn 源码(Python),
你读懂它在做什么, 输出**结构化策略画像 JSON**(无 markdown).

画像要诚实、具体, 基于源码实际逻辑 (不要泛泛而谈):
{
  "indicators": [...],          // 实际用到的指标(看代码里的 ta./rolling/计算)
  "entry_logic": "...",         // 多/空各什么条件触发 (基于代码)
  "direction": "long|short|both",
  "regime_fit": {"trend": "good|ok|bad", "range": "good|ok|bad"},  // 趋势市/震荡市各适配度
  "timeframe_fit": ["..."],     // 适合周期 (突破/趋势类偏1h+; 均值回归/震荡类可15m-)
  "edge_source": "...",         // 为什么有效, 捕捉什么
  "weakness": "...",            // 什么环境失效/被坑
  "summary_zh": "..."           // 一句话
}

判断 regime_fit / timeframe_fit 要基于策略**本质**: 突破/趋势跟随→trend good/range bad/偏大周期;
均值回归/超买超卖→range good/trend bad/可小周期; 别瞎填."""


def generate_strategy_profile(strategy_type: str, signal_code: str,
                              user_id: int = 1) -> dict:
    """AI 读 signal_fn 源码 → 生成策略画像 dict. 失败返回 {ok: False, error}."""
    from app.services.llm_provider import call_llm
    prompt = f"""## 策略类型
{strategy_type}

## signal_fn 源码
```python
{signal_code[:2500]}
```

读懂这个策略, 输出策略画像 JSON."""
    r = call_llm(
        user_id=user_id, prompt=prompt, system=SYSTEM_PROMPT, max_tokens=900,
        cache_key=f'strat_profile:{strategy_type}',
    )
    if not r.get('ok'):
        return {'ok': False, 'error': r.get('error', 'llm failed')}
    try:
        from app.services.llm_prompts.strategy_generate import _extract_json
        prof = _extract_json(r['text'])
        prof['ok'] = True
        prof['strategy_type'] = strategy_type
        return prof
    except Exception as e:
        return {'ok': False, 'error': f'parse: {e}', 'raw': r.get('text', '')[:300]}


def get_builtin_signal_source(strategy_type: str) -> str | None:
    """提取内置策略(strategy_engine)的 signal_fn 源码, 喂给画像生成."""
    import inspect
    from app.services import strategy_engine as se
    fn_map = {
        'ma_crossover': 'ma_crossover_signal', 'rsi': 'rsi_signal', 'macd': 'macd_signal',
        'bollinger': 'bollinger_signal', 'trend_following': 'trend_following_signal',
        'volatility_breakout': 'volatility_breakout_signal', 'mean_reversion': 'ml_mean_reversion_signal',
        'supertrend': 'supertrend_signal', 'vwap_reversion': 'vwap_reversion_signal',
        'keltner_channel': 'keltner_channel_signal', 'stochastic': 'stochastic_signal',
        'cci_reversal': 'cci_reversal_signal', 'atr_breakout': 'atr_breakout_signal',
        'heikin_ashi': 'heikin_ashi_signal', 'ichimoku': 'ichimoku_signal',
        'tema': 'tema_signal', 'psar': 'psar_signal', 'golden_cross': 'golden_cross_signal',
        'macd_trend_filter': 'macd_trend_filter_signal', 'weekly_pivot': 'weekly_pivot_signal',
    }
    fn_name = fn_map.get(strategy_type)
    if not fn_name or not hasattr(se, fn_name):
        return None
    try:
        return inspect.getsource(getattr(se, fn_name))
    except Exception:
        return None


_BUILTIN_NAMES = {
    'macd': 'MACD 动能', 'rsi': 'RSI 超买超卖', 'bollinger': '布林带', 'stochastic': '随机指标',
    'ma_crossover': '均线交叉', 'trend_following': '趋势跟随', 'volatility_breakout': '波动率突破',
    'mean_reversion': '均值回归', 'supertrend': 'SuperTrend', 'vwap_reversion': 'VWAP 回归',
    'keltner_channel': '肯特纳通道', 'cci_reversal': 'CCI 反转', 'atr_breakout': 'ATR 突破',
    'heikin_ashi': '平均 K 线', 'ichimoku': '一目均衡', 'tema': 'TEMA 均线', 'psar': '抛物线 SAR',
    'golden_cross': '黄金交叉', 'macd_trend_filter': 'MACD 趋势', 'weekly_pivot': '周枢轴点',
}


def strategy_display_name(strategy_type: str) -> str:
    """type → 用户可读策略名 (TG/UI 用; 不暴露 cand_cat_X_u1_timestamp 这种丑函数名)。
    内置→中文名表; cand_*→从 Strategy.name 中段 或 candidate.source_name 取干净名; 兜底美化 type。"""
    if not strategy_type:
        return '策略'
    if strategy_type in _BUILTIN_NAMES:
        return _BUILTIN_NAMES[strategy_type]
    try:
        from app.models import Strategy, StrategyCandidate
        s = Strategy.query.filter_by(type=strategy_type).first()
        if s and s.name and ' · ' in s.name:
            mid = s.name.split(' · ')
            if len(mid) >= 2 and mid[1].strip():
                return mid[1].strip()        # "SUI/USDT · 经典枢轴点突破 · #132" → "经典枢轴点突破"
        ctype = strategy_type[len('cand_'):] if strategy_type.startswith('cand_') else strategy_type
        c = StrategyCandidate.query.filter_by(candidate_type=ctype).order_by(StrategyCandidate.updated_at.desc()).first()
        if c and c.source_name:
            nm = c.source_name.replace('AI 推荐', '').replace('·', '').strip()
            nm = nm.split('(')[0].strip()
            if nm and not nm.startswith('cat_'):
                return nm                    # "AI 推荐 · 经典枢轴点突破" → "经典枢轴点突破"
    except Exception:
        pass
    # 兜底: 去前缀/后缀美化 (cand_cat_pivot_classic_break_u1_2026.. → "Pivot Classic Break")
    base = strategy_type
    if base.startswith('cand_cat_'):
        base = base[len('cand_cat_'):]
    elif base.startswith('cand_'):
        base = base[len('cand_'):]
    import re
    base = re.sub(r'_u\d+_\d+$', '', base)
    return base.replace('_', ' ').title() or strategy_type


def get_candidate_signal_source(strategy_type: str) -> str | None:
    """候选/合成策略 (cand_*) 的信号源码 — 存 StrategyCandidate.parsed_signal (动态编译, inspect 取不到)。"""
    try:
        from app.models import StrategyCandidate
        keys = [strategy_type]
        if strategy_type.startswith('cand_'):
            keys.append(strategy_type[len('cand_'):])
        for k in keys:
            c = (StrategyCandidate.query.filter_by(candidate_type=k, status='promoted')
                 .order_by(StrategyCandidate.updated_at.desc()).first())
            if c and c.parsed_signal:
                return c.parsed_signal
    except Exception:
        pass
    return None


def get_any_signal_source(strategy_type: str) -> str | None:
    """统一取信号源码: 内置 type 走 builtin, cand_* 走 candidate.parsed_signal。"""
    return get_builtin_signal_source(strategy_type) or get_candidate_signal_source(strategy_type)


def backfill_pool_profiles(types: list | None = None, limit: int | None = None,
                           user_id: int = 1) -> dict:
    """给「策略池」(非退役 managed 策略 + 候选) 里缺画像的 type 批量补画像 → 进守门员选择库。
    user 2026-05-30: 20内置=基础 + 策略池也补画像 = AI学习库, 越多守门员选择越多. 飞轮合成产出也走这里。
    **按源码去重** (多个 cand_cat_X 时间戳克隆同逻辑 → 只 LLM 一次, 复制给同源的)。返回 {profiled, skipped, errors}。"""
    import hashlib
    from app.models import db, Strategy, StrategyProfile
    if types is None:
        types = sorted({s.type for s in Strategy.query.filter(Strategy.status != 'retired').all()})
    have = {p.strategy_type for p in StrategyProfile.query.all()}
    todo = [t for t in types if t not in have]
    if limit:
        todo = todo[:limit]
    src_cache = {}   # source_hash -> profile dict (去重)
    profiled = 0; skipped = 0; errors = []
    for t in todo:
        src = get_any_signal_source(t)
        if not src:
            skipped += 1; continue
        h = hashlib.sha256(src.encode()).hexdigest()[:16]
        prof = src_cache.get(h)
        if prof is None:
            r = generate_strategy_profile(t, src, user_id=user_id)
            if not r.get('ok'):
                errors.append(f'{t}: {r.get("error")}'); continue
            prof = {k: r.get(k) for k in ('indicators', 'entry_logic', 'direction',
                    'regime_fit', 'timeframe_fit', 'edge_source', 'weakness', 'summary_zh')}
            src_cache[h] = prof
        try:
            row = StrategyProfile.query.filter_by(strategy_type=t).first()
            if row is None:
                row = StrategyProfile(strategy_type=t, profile=prof,
                                      source='catalog' if t.startswith('cand_') else 'builtin')
                db.session.add(row)
            else:
                row.profile = prof
            db.session.commit()
            profiled += 1
        except Exception as e:
            db.session.rollback(); errors.append(f'{t}: persist {e}')
    return {'profiled': profiled, 'skipped': skipped, 'errors': errors,
            'unique_sources': len(src_cache), 'todo': len(todo)}


def coverage_summary() -> dict:
    """策略池覆盖摘要: regime×周期 格子哪些有策略/哪些空 (供合成AI知道该补哪个缺口, 不重复造)。
    返回 {grid: {regime: {tf: [strategies]}}, gaps: [(regime,tf)], filled: [(regime,tf,n)]}."""
    from app.models import StrategyProfile
    TFS = ['5m', '15m', '1h', '4h']
    grid = {'trend': {tf: [] for tf in TFS}, 'range': {tf: [] for tf in TFS}}
    for p in StrategyProfile.query.all():
        prof = p.profile or {}
        rf = prof.get('regime_fit', {})
        tff = ' '.join(str(x) for x in (prof.get('timeframe_fit') or []))
        for regime in ('trend', 'range'):
            if rf.get(regime) == 'good':
                for tf in TFS:
                    if tf in tff:
                        grid[regime][tf].append(p.strategy_type)
    gaps = [(r, tf) for r in grid for tf in TFS if not grid[r][tf]]
    filled = [(r, tf, len(grid[r][tf])) for r in grid for tf in TFS if grid[r][tf]]
    return {'grid': grid, 'gaps': gaps, 'filled': filled}


def coverage_block() -> str:
    """生成注入合成 prompt 的"策略池覆盖+缺口"文本块。"""
    c = coverage_summary()
    lines = ['## 策略池覆盖 (regime×周期格子)']
    for r in ('trend', 'range'):
        for tf in ['5m', '15m', '1h', '4h']:
            ss = c['grid'][r][tf]
            mark = f"{len(ss)}个: {','.join(ss[:4])}" if ss else '⚠空缺'
            lines.append(f"  {r}/{tf}: {mark}")
    if c['gaps']:
        lines.append(f"**空缺格子(优先补): {', '.join(f'{r}/{tf}' for r, tf in c['gaps'])}**")
    return '\n'.join(lines)
