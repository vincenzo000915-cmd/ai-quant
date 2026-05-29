"""回測引擎 — 復用 strategy_engine 的 signal function，模擬完整交易流程

設計原則：
1. 跟模擬盤完全同一套規則（槓桿、倉位、止損止盈）
2. 用 strategy_engine.get_signal 計算信號，不重複實作策略邏輯
3. 每根 K 線收盤後決策（避免 lookahead）
4. 詳細記錄每筆 trade + equity curve
"""
import time
import math
import pandas as pd
import numpy as np
from app.services.strategy_engine import get_signal, get_candle_df


# Phase 14k-47: timeframe-aware 默认 SL/TP (业界标准)
# 旧版 hardcode 5%/8% 不分 TF 导致 15m/30m scalp 被 SL 5% 吃光 → Sharpe -10 全 not qualified
# → AI 永远不 promote 高频策略 → user 入场频率被卡死. Root cause of "两天没入场".
TF_DEFAULT_SL_TP = {
    '15m': (1.0, 2.0),
    '30m': (1.5, 3.0),
    '1h':  (2.5, 5.0),
    '4h':  (5.0, 8.0),    # 旧默认, 4h swing 合理
    '1d':  (10.0, 18.0),
}

# Phase 14k-48: timeframe-aware ATR multiplier (ATR-based SL/TP 用)
# 短 TF ATR 计算窗口短, 倍数大会震出止损; 长 TF 倍数可大点抓波段
TF_DEFAULT_ATR_MULT = {
    '15m': (1.5, 2.5),    # SL 1.5× ATR / TP 2.5× ATR
    '30m': (1.8, 3.0),
    '1h':  (2.0, 3.0),
    '4h':  (2.0, 3.0),    # 旧默认
    '1d':  (2.5, 4.0),
}


def resolve_default_sl_tp(timeframe: str) -> tuple[float, float]:
    """按 timeframe 返回业界标准 SL/TP. 未知 TF fallback 5%/8% (4h 老默认)."""
    return TF_DEFAULT_SL_TP.get(timeframe or '4h', (5.0, 8.0))


def leverage_aware_sl_floor(sl_pct: float, tp_pct: float, leverage: float,
                            min_eff_pct: float = 0.8) -> tuple[float, float]:
    """14k-157: 杠杆感知止损下限 — 运行时全局安全不变量 (应用到所有策略, 含显式 risk_params).

    SL/TP 在系统里是"杠杆后 %"语义 (止损触发是比杠杆后 pnl%). 不论 SL 来自显式回测 risk_params
    还是 TF/cfg fallback, 除以高杠杆后有效价格止损 sl/lev 都可能 < 噪音级 (如 1h tf_sl=2.5 ÷
    lev10 = 0.25%, 或 #69 sl5/lev8 = 0.62% → 噪音即扫, 反复打止损流血). 保证 sl/lev >=
    min_eff_pct (0.8%); 抬 SL 时同步抬 TP 维持 R:R>=1.2. 根因见 feedback_sl_leverage_coupling.

    为何覆盖显式 risk_params: 噪音级有效止损的"回测 edge"撑不过实盘 slippage/noise; 且
    grid_proposer(14k-148) 已对所有新提议强制同一 sl/lev>=0.8 不变量, 此 floor 只是把不变量
    补到不满足的存量策略 (非破坏性: 不改 DB risk_params, 只在运行时解析兜底; 方案D迁移仍会
    把存量 risk_params 修到合理值, 届时 floor 不再触发).
    """
    if not leverage or leverage <= 0:
        return sl_pct, tp_pct
    min_sl = leverage * min_eff_pct
    if sl_pct < min_sl:
        sl_pct = min_sl
        if tp_pct < sl_pct * 1.2:
            tp_pct = sl_pct * 1.2
    return sl_pct, tp_pct


def resolve_default_atr_mult(timeframe: str) -> tuple[float, float]:
    """按 timeframe 返回 ATR SL/TP 倍数. 未知 TF fallback 2/3 (4h 老默认)."""
    return TF_DEFAULT_ATR_MULT.get(timeframe or '4h', (2.0, 3.0))


def trailing_sl(side: str, entry_price: float, base_sl: float, peak_price: float,
                atr: float | None, *, trailing_atr_mult: float | None,
                trailing_activate_r: float = 1.0) -> float:
    """14k-158: 移动止盈共享纯函数 — 回测(backtest_engine) 与运行时(check_stop_loss) **必须都调它**,
    否则回测验证的 edge 在实盘是假的 (方案最大风险#2).

    机制 (让利润奔跑): 浮盈达到 trailing_activate_r × 初始风险距离后激活; 激活后有效 SL =
    peak ∓ trailing_atr_mult×ATR, 棘轮只进不退 (long 只上移/short 只下移), 永不低于初始 base_sl.
    未激活 / 无 ATR / 无配置 → 返回 base_sl 不变.

    side: 'long'|'short'; peak_price: long=持仓期最高价 / short=最低价. 返回有效 SL 绝对价.
    """
    if not trailing_atr_mult or atr is None or atr <= 0:
        return base_sl
    risk_dist = abs(entry_price - base_sl)
    if risk_dist <= 0:
        return base_sl
    if side == 'long':
        profit = peak_price - entry_price
        if profit < trailing_activate_r * risk_dist:
            return base_sl
        return max(base_sl, peak_price - trailing_atr_mult * atr)   # 棘轮上移
    else:   # short
        profit = entry_price - peak_price
        if profit < trailing_activate_r * risk_dist:
            return base_sl
        return min(base_sl, peak_price + trailing_atr_mult * atr)   # 棘轮下移


def resolve_backtest_risk_kwargs(strategy) -> dict:
    """Phase 14k-146 (D1): strategy-bound 回测的风险参数单一真理源 — 与运行态 _resolve_risk
    (strategy_tasks.py:380) 同口径. 解决矛盾根因: 回测此前落 run_backtest 默认 leverage=15,
    但实盘用策略实际 lev → SL 语义是"杠杆后%", lev 不一致 → 回测搜出的有效价格止损距离在
    实盘是错的. 返回 {leverage, stop_loss_pct, take_profit_pct} 供回测 kwargs.

    优先级 (同 _resolve_risk): strategy.params.risk_params > TF-aware 业界标准 > 引擎默认.
    无 strategy → 返回 {} (caller 不传 → run_backtest 用自身默认, 裸回测兼容).

    14k-157: 杠杆后有效 SL/TP 必须在"回测完之前"就定下且非噪音级 (user 洞察) — 否则回测验证的
    edge 建立在实盘撑不住的窄止损上. 故此处:
      ① 有效杠杆 = 显式 rp.lev OR cfg 全局 lev (同运行时 _resolve_risk), 始终注入 → 回测用的
         leverage 就是实盘的, "杠杆后 SL" 在回测时即已知 (修 D1 残留: 无显式 lev 时回测/实盘 lev 不一致).
      ② 对 SL/TP 套同一 leverage_aware_sl_floor → 回测验证的就是 sl/lev>=0.8% 的非噪音止损,
         与运行时完全同口径. 根因见 feedback_sl_leverage_coupling.
    """
    if strategy is None:
        return {}
    rp = (getattr(strategy, 'params', None) or {}).get('risk_params') or {}
    tf_sl, tf_tp = resolve_default_sl_tp(getattr(strategy, 'timeframe', None))
    # 有效杠杆: 显式 > cfg 全局 (同 _resolve_risk 的 lev_default)
    cfg_lev = None
    try:
        from app.models import SystemConfig
        sc = SystemConfig.query.get(1)
        cfg_lev = sc.leverage if sc else None
    except Exception:
        cfg_lev = None
    lev = float(rp.get('leverage') or cfg_lev or 10)
    # 14k-158: ATR 模式 — 返回 ATR kwargs (绝对价 SL/TP+trailing), 回测口径=运行时 compute_sl_tp.
    # mult 为 None 时 run_backtest 用 TF-aware/5R 默认. leverage 仍注入(funding/sizing 用).
    if rp.get('sl_mode') == 'atr':
        out = {'leverage': lev, 'sl_mode': 'atr'}
        for _k, _cast in (('atr_sl_mult', float), ('atr_tp_mult', float),
                          ('atr_period', int), ('trailing_atr_mult', float),
                          ('trailing_activate_r', float)):
            if rp.get(_k) is not None:
                out[_k] = _cast(rp[_k])
        return out
    sl = float(rp.get('stop_loss_pct') or rp.get('sl_pct') or tf_sl or 0)
    tp = float(rp.get('take_profit_pct') or rp.get('tp_pct') or tf_tp or 0)
    # 杠杆感知止损下限 — 回测即用运行时真实有效 SL (sl/lev>=0.8%), 抬 SL 同步抬 TP 维持 R:R
    if sl:
        sl, tp = leverage_aware_sl_floor(sl, tp, lev)
    out = {'leverage': lev}
    if sl:
        out['stop_loss_pct'] = sl
    if tp:
        out['take_profit_pct'] = tp
    return out


def _calc_drawdown(equity_series):
    """計算最大回撤（金額 + 百分比）"""
    if not equity_series:
        return 0.0, 0.0
    arr = np.array(equity_series, dtype=float)
    peak = np.maximum.accumulate(arr)
    dd_abs = peak - arr
    dd_pct = np.where(peak > 0, dd_abs / peak * 100, 0)
    return float(dd_abs.max()), float(dd_pct.max())


def _calc_sharpe(daily_returns, periods_per_year=365):
    """簡化 Sharpe（無風險利率 = 0）"""
    if not daily_returns or len(daily_returns) < 2:
        return None
    arr = np.array(daily_returns, dtype=float)
    if arr.std() == 0:
        return None
    return float(arr.mean() / arr.std() * math.sqrt(periods_per_year))


# Phase 14k-30: per-symbol 平均 funding rate (per 8h, decimal).
# 数据来源: 历史均值 (2024-2025 BTC ~0.01% / ETH ~0.008% / alt ~0.012%). 持仓段累加估 funding cost.
# 实际 funding 有正有负, 这里用 abs 平均, 偏保守 (假设 trader 总在 funding 不利方向)
AVG_FUNDING_PER_8H = {
    'BTC/USDT': 0.0001,    # 0.01% / 8h ≈ 11% / yr
    'ETH/USDT': 0.00008,
    'SOL/USDT': 0.00012,
    'BNB/USDT': 0.0001,
    'ARB/USDT': 0.00015,
    'SUI/USDT': 0.00018,
    'AVAX/USDT': 0.00015,
    'DOGE/USDT': 0.00015,
}
DEFAULT_FUNDING_PER_8H = 0.00012   # 没列表的 alt 用这个


def _funding_cost(position_size_usdt: float, leverage: float,
                  hours_held: float, symbol: str) -> float:
    """Phase 14k-30: 估算持仓段 funding 成本 (USDT).
    Funding 按 8h 累计, 杠杆放大 (借的钱也算): cost = position × lev × rate × (hours/8).
    """
    rate = AVG_FUNDING_PER_8H.get(symbol, DEFAULT_FUNDING_PER_8H)
    intervals = hours_held / 8.0
    return position_size_usdt * leverage * rate * intervals


def _compute_atr_series(candles: list, period: int = 14) -> list:
    """Phase 14k-30: 预算 ATR 序列 (Wilder smoothing 简化版).
    回传跟 candles 等长的 list, 前 period 个为 None.
    """
    if not candles or len(candles) < period + 1:
        return [None] * len(candles)
    trs = []
    prev_close = candles[0]['close']
    for c in candles:
        h, l = c['high'], c['low']
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        trs.append(tr)
        prev_close = c['close']
    atrs = [None] * len(candles)
    # 简单 rolling mean 而不是 Wilder, 够用
    for i in range(period, len(candles)):
        atrs[i] = sum(trs[i - period + 1:i + 1]) / period
    return atrs


def _periods_per_year(timeframe):
    """timeframe → 一年的 K 線數量（用於年化、Sharpe）"""
    minutes = {
        '1m': 1, '3m': 3, '5m': 5, '15m': 15, '30m': 30,
        '1h': 60, '2h': 120, '4h': 240, '6h': 360, '12h': 720,
        '1d': 1440, '1w': 10080,
    }.get(timeframe, 240)
    return int(365 * 24 * 60 / minutes)


def run_walkforward_backtest(
    strategy_type: str,
    params: dict,
    candles: list,
    *,
    is_ratio: float = 0.7,
    timeframe: str = '4h',
    signal_fn=None,
    **kwargs,
):
    """Walk-forward 驗證 — 切 IS(70%)/OOS(30%)，兩段獨立回測。

    Phase 5.4 防過擬合：用 IS 回測選參數、用 OOS 驗證真實 alpha。
    若 OOS Sharpe 顯著低於 IS（>50% 衰減）→ 過擬合警訊；qualify 應拒。

    回傳：
    {
      'full': {...全段結果，跟 run_backtest 一樣},
      'in_sample': {...},
      'out_sample': {...},
      'is_ratio': 0.7,
      'split_ts': <分界 timestamp>,
      'decay_pct': <OOS sharpe 相對 IS 的衰減 %，越高越像過擬合>,
    }
    """
    if not candles or len(candles) < 200:
        return {'status': 'error', 'error_message': f'walkforward 至少要 200 根，給了 {len(candles) if candles else 0}'}

    candles = sorted(candles, key=lambda c: c['timestamp'])
    split_idx = int(len(candles) * is_ratio)
    is_candles = candles[:split_idx]
    oos_candles = candles[split_idx:]

    full = run_backtest(strategy_type, params, candles, timeframe=timeframe, signal_fn=signal_fn, **kwargs)
    is_res = run_backtest(strategy_type, params, is_candles, timeframe=timeframe, signal_fn=signal_fn, **kwargs)
    # OOS 用較短 warmup（因為已有指標暖機歷史）— 但簡化起見用預設值
    oos_res = run_backtest(strategy_type, params, oos_candles, timeframe=timeframe, signal_fn=signal_fn, **kwargs)

    is_sh = is_res.get('sharpe_ratio')
    oos_sh = oos_res.get('sharpe_ratio')
    decay = None
    if is_sh is not None and oos_sh is not None and is_sh != 0:
        decay = round((1 - oos_sh / is_sh) * 100, 2) if is_sh > 0 else None

    return {
        'status': full.get('status', 'completed'),
        'full': full,
        'in_sample': is_res,
        'out_sample': oos_res,
        'is_ratio': is_ratio,
        'split_ts': candles[split_idx]['timestamp'] if split_idx < len(candles) else None,
        'decay_pct': decay,
    }


def run_backtest(
    strategy_type: str,
    params: dict,
    candles: list,
    *,
    timeframe: str = '4h',
    leverage: float = 15.0,
    position_size_usdt: float = 10.0,
    stop_loss_pct: float | None = None,    # 14k-47: None → TF-aware default
    take_profit_pct: float | None = None,  # 14k-47: None → TF-aware default
    initial_capital: float = 100.0,
    fee_pct: float = 0.05,         # taker per side; OKX=0.05% / HL=0.035% (Phase 14k-10)
    slippage_pct: float = 0.05,    # 市價單估算滑點 per fill (Phase 9.5)
    warmup: int = 60,
    signal_fn=None,
    exchange: str = 'okx',          # Phase 14k-10: 决定 fee_pct 默认值
    symbol: str | None = None,      # Phase 14k-30: 用于查 funding rate
    # Phase 14k-158: ATR 波动率自适应 SL/TP + 移动止盈 (默认 flat_pct → 行为不变, 向后兼容)
    sl_mode: str = 'flat_pct',      # 'flat_pct'(固定杠杆后%) | 'atr'(绝对价 entry∓mult×ATR)
    atr_sl_mult: float | None = None,   # None → TF-aware resolve_default_atr_mult
    atr_tp_mult: float | None = None,   # None → atr_sl_mult×5 (5R 硬顶, 高 R:R)
    atr_period: int = 14,
    trailing_atr_mult: float | None = None,   # None → =atr_sl_mult (移动止盈距离); 0/False=关
    trailing_activate_r: float = 1.0,         # 浮盈达 N×初始风险距离后激活 trailing
):
    """跑單一策略的完整回測

    candles: [{ timestamp, open, high, low, close, volume }, ...]（按 timestamp 升序）
    signal_fn: 若指定，跳過 get_signal 查表，直接呼叫；用於 Phase 4 候選策略沙箱回測。
    回傳: 詳細統計 + equity curve + trades 列表
    """
    t_start = time.time()

    # Phase 14k-47: TF-aware 默认 SL/TP (root cause of 15m/30m candidates 全 not qualified)
    if stop_loss_pct is None or take_profit_pct is None:
        _sl, _tp = resolve_default_sl_tp(timeframe)
        if stop_loss_pct is None:
            stop_loss_pct = _sl
        if take_profit_pct is None:
            take_profit_pct = _tp

    # Phase 14k-158: ATR 模式倍数解析 (默认高 R:R: TP=5R 硬顶, trailing 距离=1×SL mult)
    if sl_mode == 'atr':
        _dsl, _ = resolve_default_atr_mult(timeframe)
        if atr_sl_mult is None:
            atr_sl_mult = _dsl
        if atr_tp_mult is None:
            atr_tp_mult = atr_sl_mult * 5.0
        if trailing_atr_mult is None:
            trailing_atr_mult = atr_sl_mult

    # Phase 14k-10: 按 exchange 调整 fee (caller 未显式传时)
    # HL taker 0.035% vs OKX 0.05%; HL maker 0.01% vs OKX 0.02%
    if exchange and (exchange or '').lower() == 'hyperliquid':
        # 仅当 caller 用默认 0.05% 时才覆盖, 显式传值优先
        if fee_pct == 0.05:
            fee_pct = 0.035

    if not candles or len(candles) < warmup + 10:
        return {
            'status': 'error',
            'error_message': f'K 線不足（{len(candles) if candles else 0} < {warmup + 10}）',
        }

    # 預先排序
    candles = sorted(candles, key=lambda c: c['timestamp'])

    # 14k-30: timeframe → candle hours (用于 funding 累计 hours_held)
    _tf_minutes_map = {'1m':1,'3m':3,'5m':5,'15m':15,'30m':30,'1h':60,'2h':120,'4h':240,
                       '6h':360,'8h':480,'12h':720,'1d':1440,'3d':4320,'1w':10080}
    candle_hours = _tf_minutes_map.get(timeframe, 240) / 60.0

    # Phase 9.5 + 14k-30: 滑点 — entry 往不利方向偏, exit 也往不利方向
    # 14k-30: ATR 动态化, base slippage_pct 作 floor; 高波动期估高 (实测高波动 0.2-0.5% slip)
    base_slip = slippage_pct / 100.0
    atr_series = _compute_atr_series(candles, period=14)
    ATR_SLIP_MULTIPLIER = 0.15  # ATR/close 1% → slippage 0.15%

    def slip_at(i):
        """返回第 i 根 candle 的有效 slippage (decimal)."""
        if i < len(atr_series) and atr_series[i] and candles[i]['close'] > 0:
            vol = atr_series[i] / candles[i]['close']
            dyn = vol * ATR_SLIP_MULTIPLIER
            return max(base_slip, dyn)
        return base_slip

    def entry_fill(price, side, i):
        s = slip_at(i)
        return price * (1 + s) if side == 'long' else price * (1 - s)
    def exit_fill(price, side, i):
        s = slip_at(i)
        return price * (1 - s) if side == 'long' else price * (1 + s)

    equity = initial_capital
    position = None  # { entry_price, size_btc, opened_idx, opened_ts }
    trades = []
    equity_curve = []
    daily_pnl_by_date = {}
    # 14k-50: signal_fn 异常计数 — 守门员看到 0 trades 时不该误判, 暴露 code error
    signal_fn_error_count = 0
    signal_fn_first_error = None

    for i in range(warmup, len(candles)):
        c = candles[i]
        ts = c['timestamp']
        price = c['close']

        # 1. 檢查止損 / 止盈 — 14k-158: flat_pct(收盘价杠杆后%) 或 atr(绝对价+移动止盈, 用 low/high 保守判)
        if position:
            close_reason = None
            exit_ref_price = price   # flat_pct 用收盘价成交; atr 用触发价成交
            if sl_mode == 'atr' and position.get('sl_abs') is not None:
                _atr_now = atr_series[i] if i < len(atr_series) else None
                if position['side'] == 'long':
                    position['highest_price'] = max(position['highest_price'], c['high'])
                    eff_sl = trailing_sl('long', position['entry_price'], position['sl_abs'],
                                         position['highest_price'], _atr_now,
                                         trailing_atr_mult=trailing_atr_mult,
                                         trailing_activate_r=trailing_activate_r)
                    if c['low'] <= eff_sl:    # 保守: 用最低价判 SL 触发
                        close_reason = 'trailing_stop' if eff_sl > position['sl_abs'] else 'stop_loss'
                        exit_ref_price = eff_sl
                    elif c['high'] >= position['tp_abs']:
                        close_reason = 'take_profit'
                        exit_ref_price = position['tp_abs']
                else:   # short
                    position['lowest_price'] = min(position['lowest_price'], c['low'])
                    eff_sl = trailing_sl('short', position['entry_price'], position['sl_abs'],
                                         position['lowest_price'], _atr_now,
                                         trailing_atr_mult=trailing_atr_mult,
                                         trailing_activate_r=trailing_activate_r)
                    if c['high'] >= eff_sl:   # 保守: 用最高价判 SL 触发
                        close_reason = 'trailing_stop' if eff_sl < position['sl_abs'] else 'stop_loss'
                        exit_ref_price = eff_sl
                    elif c['low'] <= position['tp_abs']:
                        close_reason = 'take_profit'
                        exit_ref_price = position['tp_abs']
            else:
                # flat_pct: 原逻辑一行不动 — 收盘价杠杆后% (不扰动已校准旧分布)
                if position['side'] == 'short':
                    raw_pct = (position['entry_price'] - price) / position['entry_price'] * 100
                else:
                    raw_pct = (price - position['entry_price']) / position['entry_price'] * 100
                pnl_pct = raw_pct * leverage
                if pnl_pct <= -stop_loss_pct:
                    close_reason = 'stop_loss'
                elif pnl_pct >= take_profit_pct:
                    close_reason = 'take_profit'

            if close_reason:
                # 重算 raw_pct 用 filled exit price（flat_pct=收盘价 / atr=触发价, 都过滑点取差侧）
                filled_exit = exit_fill(exit_ref_price, position['side'], i)
                if position['side'] == 'short':
                    raw_pct = (position['entry_price'] - filled_exit) / position['entry_price'] * 100
                else:
                    raw_pct = (filled_exit - position['entry_price']) / position['entry_price'] * 100
                pnl_pct = raw_pct * leverage
                pnl = raw_pct * position['size_btc'] * position['entry_price'] * leverage / 100
                fee = position_size_usdt * (fee_pct / 100) * 2  # 開倉 + 平倉
                # 14k-30: funding cost — 持仓段每 8h 累计
                hours_held = (i - position['opened_idx']) * candle_hours
                funding = _funding_cost(position_size_usdt, leverage, hours_held, symbol or '') if symbol else 0.0
                pnl_net = pnl - fee - funding
                equity += pnl_net
                trades.append({
                    'entry_ts': position['opened_ts'],
                    'exit_ts': ts,
                    'entry_price': position['entry_price'],
                    'exit_price': filled_exit,
                    'size': position['size_btc'],
                    'side': position['side'],
                    'pnl': round(pnl_net, 4),
                    'pnl_pct': round(pnl_pct, 4),
                    'funding_cost': round(funding, 4),
                    'reason': close_reason,
                    'bars_held': i - position['opened_idx'],
                })
                date_key = pd.Timestamp(ts, unit='s').date().isoformat()
                daily_pnl_by_date[date_key] = daily_pnl_by_date.get(date_key, 0) + pnl_net
                position = None

        # 2. 跑策略信號（用 [0..i] 的視窗，含當根收盤）
        window = candles[: i + 1]
        df = get_candle_df([dict(x) for x in window])  # copy
        if signal_fn is not None:
            try:
                signal = signal_fn(df, params)
            except Exception as _sfe:
                # 14k-50: 暴露 signal_fn code error — 旧版静默吞掉, 守门员看到 0 trades 误判
                signal_fn_error_count += 1
                if signal_fn_first_error is None:
                    signal_fn_first_error = f'{type(_sfe).__name__}: {_sfe}'
                signal = 'hold'
        else:
            signal = get_signal(strategy_type, df, params)

        # 3. 處理信號 — Phase 9.2: 支援 short
        is_buy = signal in ('buy', 'long')
        is_sell = signal in ('sell', 'short')

        if position is None:
            # 開倉
            if is_buy or is_sell:
                side_open = 'long' if is_buy else 'short'
                filled_entry = entry_fill(price, side_open, i)
                size_btc = round(position_size_usdt / filled_entry, 6)
                position = {
                    'entry_price': filled_entry,
                    'size_btc': size_btc,
                    'side': side_open,
                    'opened_idx': i,
                    'opened_ts': ts,
                }
                # 14k-158: ATR 模式 — 开仓锁定绝对价 SL/TP (entry∓mult×ATR), 初始化 trailing peak
                if sl_mode == 'atr':
                    _atr_open = atr_series[i] if i < len(atr_series) else None
                    if _atr_open and _atr_open > 0:
                        sl_dist = atr_sl_mult * _atr_open
                        tp_dist = atr_tp_mult * _atr_open
                        if side_open == 'long':
                            position['sl_abs'] = filled_entry - sl_dist
                            position['tp_abs'] = filled_entry + tp_dist
                        else:
                            position['sl_abs'] = filled_entry + sl_dist
                            position['tp_abs'] = filled_entry - tp_dist
                        position['highest_price'] = filled_entry
                        position['lowest_price'] = filled_entry
                    else:
                        position['sl_abs'] = None   # ATR 不可用 → 该仓 fallback flat_pct
        else:
            # 持倉中 — 反向信號平倉
            should_close = (
                (position['side'] == 'long' and is_sell) or
                (position['side'] == 'short' and is_buy) or
                signal == 'close'
            )
            if should_close:
                filled_exit = exit_fill(price, position['side'], i)
                if position['side'] == 'short':
                    raw_pct = (position['entry_price'] - filled_exit) / position['entry_price'] * 100
                else:
                    raw_pct = (filled_exit - position['entry_price']) / position['entry_price'] * 100
                pnl_pct = raw_pct * leverage
                pnl = raw_pct * position['size_btc'] * position['entry_price'] * leverage / 100
                fee = position_size_usdt * (fee_pct / 100) * 2
                # 14k-30: funding cost
                hours_held = (i - position['opened_idx']) * candle_hours
                funding = _funding_cost(position_size_usdt, leverage, hours_held, symbol or '') if symbol else 0.0
                pnl_net = pnl - fee - funding
                equity += pnl_net
                trades.append({
                    'entry_ts': position['opened_ts'],
                    'exit_ts': ts,
                    'entry_price': position['entry_price'],
                    'exit_price': filled_exit,
                    'size': position['size_btc'],
                    'side': position['side'],
                    'funding_cost': round(funding, 4),
                    'pnl': round(pnl_net, 4),
                    'pnl_pct': round(pnl_pct, 4),
                    'reason': 'signal',
                    'bars_held': i - position['opened_idx'],
                })
                date_key = pd.Timestamp(ts, unit='s').date().isoformat()
                daily_pnl_by_date[date_key] = daily_pnl_by_date.get(date_key, 0) + pnl_net
                position = None

        # 4. 紀錄 equity curve（含浮動）
        unrealized = 0.0
        if position:
            if position['side'] == 'short':
                raw_pct = (position['entry_price'] - price) / position['entry_price'] * 100
            else:
                raw_pct = (price - position['entry_price']) / position['entry_price'] * 100
            unrealized = raw_pct * position['size_btc'] * position['entry_price'] * leverage / 100
        equity_curve.append({
            'ts': ts,
            'equity': round(equity + unrealized, 4),
            'realized_equity': round(equity, 4),
        })

    # 收盤時若仍有持倉，按最後收盤價強平 — 支援 long/short
    if position:
        last = candles[-1]
        price = last['close']
        filled_exit = exit_fill(price, position['side'], len(candles) - 1)
        if position['side'] == 'short':
            raw_pct = (position['entry_price'] - filled_exit) / position['entry_price'] * 100
        else:
            raw_pct = (filled_exit - position['entry_price']) / position['entry_price'] * 100
        pnl_pct = raw_pct * leverage
        pnl = raw_pct * position['size_btc'] * position['entry_price'] * leverage / 100
        fee = position_size_usdt * (fee_pct / 100) * 2
        # 14k-30: funding cost
        hours_held = (len(candles) - 1 - position['opened_idx']) * candle_hours
        funding = _funding_cost(position_size_usdt, leverage, hours_held, symbol or '') if symbol else 0.0
        pnl_net = pnl - fee - funding
        equity += pnl_net
        trades.append({
            'entry_ts': position['opened_ts'],
            'exit_ts': last['timestamp'],
            'entry_price': position['entry_price'],
            'exit_price': filled_exit,
            'size': position['size_btc'],
            'side': position['side'],
            'funding_cost': round(funding, 4),
            'pnl': round(pnl_net, 4),
            'pnl_pct': round(pnl_pct, 4),
            'reason': 'end_of_period',
            'bars_held': len(candles) - 1 - position['opened_idx'],
        })

    # === 統計計算 ===
    total = len(trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] < 0]
    total_pnl = sum(t['pnl'] for t in trades)
    win_rate = (len(wins) / total * 100) if total > 0 else 0
    avg_pnl = (total_pnl / total) if total > 0 else 0
    avg_win = (sum(t['pnl'] for t in wins) / len(wins)) if wins else 0
    avg_loss = (sum(t['pnl'] for t in losses) / len(losses)) if losses else 0
    sum_wins = sum(t['pnl'] for t in wins)
    sum_losses_abs = abs(sum(t['pnl'] for t in losses))
    profit_factor = (sum_wins / sum_losses_abs) if sum_losses_abs > 0 else (None if sum_wins == 0 else float('inf'))

    equity_values = [p['equity'] for p in equity_curve]
    max_dd_abs, max_dd_pct = _calc_drawdown(equity_values)

    daily_returns = list(daily_pnl_by_date.values())
    daily_returns_pct = [r / initial_capital for r in daily_returns]
    sharpe = _calc_sharpe(daily_returns_pct, periods_per_year=365)

    # 年化（依 K 線實際跨越時間）
    span_seconds = candles[-1]['timestamp'] - candles[warmup]['timestamp']
    span_years = span_seconds / (365 * 24 * 3600) if span_seconds > 0 else 0
    annual_return_pct = (total_pnl / initial_capital * 100) / span_years if span_years > 0 else 0

    duration_ms = int((time.time() - t_start) * 1000)

    return {
        'status': 'completed',
        'total_trades': total,
        'winning_trades': len(wins),
        'losing_trades': len(losses),
        'win_rate': round(win_rate, 2),
        'total_pnl': round(total_pnl, 4),
        'avg_pnl': round(avg_pnl, 4),
        'avg_win': round(avg_win, 4),
        'avg_loss': round(avg_loss, 4),
        'profit_factor': (None if profit_factor is None else (None if profit_factor == float('inf') else round(profit_factor, 4))),
        'max_drawdown': round(max_dd_abs, 4),
        'max_drawdown_pct': round(max_dd_pct, 4),
        'sharpe_ratio': (None if sharpe is None else round(sharpe, 4)),
        'final_equity': round(equity, 4),
        'annual_return_pct': round(annual_return_pct, 4),
        'period_start': candles[warmup]['timestamp'],
        'period_end': candles[-1]['timestamp'],
        'candle_count': len(candles) - warmup,
        'duration_ms': duration_ms,
        'equity_curve': equity_curve,
        'trades': trades,
        # 14k-50: signal_fn 异常 - 让守门员/调用方能区分"策略真烂" vs "code 错误致 0 trades"
        'signal_fn_error_count': signal_fn_error_count,
        'signal_fn_first_error': signal_fn_first_error,
        # 14k-68: EV (期望收益/trade) — user 哲学 "追盈利率不追胜率"
        # 不该看 win_rate 单维, 而是看 EV (per-trade 净盈亏 %)
        # = avg_pnl / initial_capital × 100, 但更直观: total_pnl / total_trades 给 USD/单
        'ev_per_trade_pct': round(total_pnl / total / initial_capital * 100, 4) if total > 0 else 0.0,
        'ev_per_trade_usdt': round(total_pnl / total, 4) if total > 0 else 0.0,
    }
