"""Phase 9.3: 動態倉位計算

三種模式（SystemConfig.sizing_mode）：
- 'flat'             : 用 base trade_size_usdt（原本行為）
- 'vol_target'       : 反向 scale — 高波動時減倉、低波動時加倉
                       multiplier = target_vol_pct / realized_vol_pct
                       clamp 到 [sizing_min_mult, sizing_max_mult]
- 'sharpe_weighted'  : 用該策略最近一次 backtest Sharpe 加權
                       multiplier = sharpe / 2  (Sharpe 2 = 1.0x base, 4 = 2.0x)
                       clamp 同上

回傳：實際 trade_size_usdt（含 multiplier）
"""
from __future__ import annotations

import numpy as np
from app.models import Candle, BacktestResult


_TF_BARS_PER_DAY = {
    '15m': 96, '30m': 48, '1h': 24, '4h': 6, '1d': 1, '1w': 1/7,
}


def _realized_vol_pct(symbol: str, prefer_tf: str = '1d', window: int = 20) -> tuple[float | None, str | None]:
    """估計日波動率 %。優先用 1d K 線；沒有就用較細的 TF 縮放到日。

    回傳 (vol_pct, tf_used)
    """
    for tf in [prefer_tf, '4h', '1h', '1d', '15m']:
        rows = (Candle.query.filter_by(symbol=symbol, timeframe=tf)
                .order_by(Candle.timestamp.desc()).limit(window + 1).all())
        if len(rows) < window:
            continue
        closes = np.array([r.close for r in reversed(rows)], dtype=float)
        log_returns = np.diff(np.log(closes))
        if len(log_returns) < 2 or np.std(log_returns) == 0:
            continue
        # 該 TF 的 std × √(每日 TF 數量) 換算成日波動
        bars_per_day = _TF_BARS_PER_DAY.get(tf, 1)
        daily_vol = float(np.std(log_returns) * np.sqrt(bars_per_day) * 100)
        return daily_vol, tf
    return None, None


def _strategy_sharpe(strategy_id: int) -> float | None:
    bt = (BacktestResult.query.filter_by(strategy_id=strategy_id, status='completed')
          .order_by(BacktestResult.created_at.desc()).first())
    if not bt or bt.sharpe_ratio is None:
        return None
    return float(bt.sharpe_ratio)


def compute_size(strategy, cfg: dict, base_size_usdt: float) -> tuple[float, dict]:
    """回傳 (final_size, debug_info)"""
    mode = cfg.get('sizing_mode', 'flat')
    min_mult = cfg.get('sizing_min_mult', 0.3)
    max_mult = cfg.get('sizing_max_mult', 3.0)

    if mode == 'flat':
        return base_size_usdt, {'mode': 'flat', 'multiplier': 1.0}

    multiplier = 1.0
    debug: dict = {'mode': mode}

    if mode == 'vol_target':
        target_vol = cfg.get('target_vol_pct', 1.5)
        vol, tf_used = _realized_vol_pct(strategy.symbol, '1d', 20)
        debug['realized_vol_pct'] = round(vol, 3) if vol else None
        debug['target_vol_pct'] = target_vol
        debug['vol_source_tf'] = tf_used
        if vol is None or vol == 0:
            debug['fallback'] = 'no vol data; use flat'
            return base_size_usdt, debug
        multiplier = target_vol / vol

    elif mode == 'sharpe_weighted':
        sh = _strategy_sharpe(strategy.id)
        debug['sharpe'] = sh
        if sh is None or sh <= 0:
            debug['fallback'] = 'no valid sharpe; use flat'
            return base_size_usdt, debug
        multiplier = sh / 2.0   # Sharpe 2.0 = 1.0x

    # 夾在合理範圍
    multiplier = max(min_mult, min(max_mult, multiplier))
    debug['multiplier'] = round(multiplier, 3)
    return round(base_size_usdt * multiplier, 2), debug
