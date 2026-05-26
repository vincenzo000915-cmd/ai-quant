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


def resolve_default_atr_mult(timeframe: str) -> tuple[float, float]:
    """按 timeframe 返回 ATR SL/TP 倍数. 未知 TF fallback 2/3 (4h 老默认)."""
    return TF_DEFAULT_ATR_MULT.get(timeframe or '4h', (2.0, 3.0))


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

        # 1. 檢查止損 / 止盈（基於收盤價）— 支援 long/short
        if position:
            if position['side'] == 'short':
                raw_pct = (position['entry_price'] - price) / position['entry_price'] * 100
            else:
                raw_pct = (price - position['entry_price']) / position['entry_price'] * 100
            pnl_pct = raw_pct * leverage

            close_reason = None
            if pnl_pct <= -stop_loss_pct:
                close_reason = 'stop_loss'
            elif pnl_pct >= take_profit_pct:
                close_reason = 'take_profit'

            if close_reason:
                # 重算 raw_pct 用 filled exit price（之前的 raw_pct 用 raw price）
                filled_exit = exit_fill(price, position['side'], i)
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
    }
