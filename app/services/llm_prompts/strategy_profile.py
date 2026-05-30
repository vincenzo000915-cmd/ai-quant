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
