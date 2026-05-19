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
    stop_loss_pct: float = 5.0,
    take_profit_pct: float = 8.0,
    initial_capital: float = 100.0,
    fee_pct: float = 0.1,   # 0.1% taker fee per side
    warmup: int = 60,       # 暖機 K 線數量（給指標累積足夠資料）
    signal_fn=None,         # Phase 4: 傳入 callable(df, params) → 'buy'/'sell'/'hold'，覆寫 strategy_type 查表
):
    """跑單一策略的完整回測

    candles: [{ timestamp, open, high, low, close, volume }, ...]（按 timestamp 升序）
    signal_fn: 若指定，跳過 get_signal 查表，直接呼叫；用於 Phase 4 候選策略沙箱回測。
    回傳: 詳細統計 + equity curve + trades 列表
    """
    t_start = time.time()

    if not candles or len(candles) < warmup + 10:
        return {
            'status': 'error',
            'error_message': f'K 線不足（{len(candles) if candles else 0} < {warmup + 10}）',
        }

    # 預先排序
    candles = sorted(candles, key=lambda c: c['timestamp'])

    equity = initial_capital
    position = None  # { entry_price, size_btc, opened_idx, opened_ts }
    trades = []
    equity_curve = []
    daily_pnl_by_date = {}

    for i in range(warmup, len(candles)):
        c = candles[i]
        ts = c['timestamp']
        price = c['close']

        # 1. 檢查止損 / 止盈（基於收盤價）
        if position:
            raw_pct = (price - position['entry_price']) / position['entry_price'] * 100
            pnl_pct = raw_pct * leverage

            close_reason = None
            if pnl_pct <= -stop_loss_pct:
                close_reason = 'stop_loss'
            elif pnl_pct >= take_profit_pct:
                close_reason = 'take_profit'

            if close_reason:
                pnl = (price - position['entry_price']) * position['size_btc'] * leverage
                fee = position_size_usdt * (fee_pct / 100) * 2  # 開倉 + 平倉
                pnl_net = pnl - fee
                equity += pnl_net
                trades.append({
                    'entry_ts': position['opened_ts'],
                    'exit_ts': ts,
                    'entry_price': position['entry_price'],
                    'exit_price': price,
                    'size': position['size_btc'],
                    'side': 'long',
                    'pnl': round(pnl_net, 4),
                    'pnl_pct': round(pnl_pct, 4),
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
            except Exception:
                signal = 'hold'  # 候選策略 runtime 報錯就跳過該根
        else:
            signal = get_signal(strategy_type, df, params)

        # 3. 處理信號
        if signal in ('buy', 'long') and position is None:
            size_btc = position_size_usdt / price
            size_btc = round(size_btc, 6)
            position = {
                'entry_price': price,
                'size_btc': size_btc,
                'opened_idx': i,
                'opened_ts': ts,
            }

        elif signal in ('sell', 'close') and position is not None:
            pnl_raw = (price - position['entry_price']) * position['size_btc'] * leverage
            fee = position_size_usdt * (fee_pct / 100) * 2
            pnl_net = pnl_raw - fee
            raw_pct = (price - position['entry_price']) / position['entry_price'] * 100
            pnl_pct = raw_pct * leverage
            equity += pnl_net
            trades.append({
                'entry_ts': position['opened_ts'],
                'exit_ts': ts,
                'entry_price': position['entry_price'],
                'exit_price': price,
                'size': position['size_btc'],
                'side': 'long',
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
            unrealized = (price - position['entry_price']) * position['size_btc'] * leverage
        equity_curve.append({
            'ts': ts,
            'equity': round(equity + unrealized, 4),
            'realized_equity': round(equity, 4),
        })

    # 收盤時若仍有持倉，按最後收盤價強平
    if position:
        last = candles[-1]
        price = last['close']
        pnl_raw = (price - position['entry_price']) * position['size_btc'] * leverage
        fee = position_size_usdt * (fee_pct / 100) * 2
        pnl_net = pnl_raw - fee
        raw_pct = (price - position['entry_price']) / position['entry_price'] * 100
        pnl_pct = raw_pct * leverage
        equity += pnl_net
        trades.append({
            'entry_ts': position['opened_ts'],
            'exit_ts': last['timestamp'],
            'entry_price': position['entry_price'],
            'exit_price': price,
            'size': position['size_btc'],
            'side': 'long',
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
    }
