"""異常檢測 — Phase 6.4

幾個關鍵 invariant：
- BTC 5min 跌幅超過 X% → flash crash，halt
- 同時開倉數 > 配置上限 → 風險過度集中，halt
- （未來）spread 異常、signal storm 等
"""
from __future__ import annotations

from app.extensions import db
from app.models import Position, Candle
from app.services.config_service import get_config, set_halted
from app.services.telegram_service import notify_halt


# 預設門檻 — 之後可改成跟 SystemConfig 走
FLASH_CRASH_PCT = 3.0          # 5min 跌幅超過 3% 觸發
FLASH_CRASH_WINDOW_BARS = 5    # 5 根 1m K 線 ≈ 5 分鐘
MAX_CONCURRENT_POSITIONS = 12  # 同時 12 筆 = $120 名義（$10×12，15× 槓桿 = $1800）


def check_flash_crash() -> dict | None:
    """看 BTC/USDT 1m 最近 N 根 close 是否跌幅超過 FLASH_CRASH_PCT"""
    candles = (Candle.query
               .filter_by(symbol='BTC/USDT', timeframe='1m')
               .order_by(Candle.timestamp.desc())
               .limit(FLASH_CRASH_WINDOW_BARS + 1).all())
    if len(candles) < FLASH_CRASH_WINDOW_BARS + 1:
        # 1m K 線可能還沒被 fetch_market_data 拉進來，跳過
        return None
    closes = [c.close for c in reversed(candles)]   # ascending
    start = closes[0]
    end = closes[-1]
    if start <= 0:
        return None
    pct = (end - start) / start * 100
    if pct <= -FLASH_CRASH_PCT:
        return {
            'type': 'flash_crash',
            'pct': round(pct, 3),
            'window_bars': FLASH_CRASH_WINDOW_BARS,
            'start': start, 'end': end,
        }
    return None


def check_concurrent_positions() -> dict | None:
    """同時 open 持倉數是否超過上限"""
    open_count = Position.query.filter_by(status='open').count()
    if open_count > MAX_CONCURRENT_POSITIONS:
        return {
            'type': 'concurrent_positions',
            'open': open_count,
            'max': MAX_CONCURRENT_POSITIONS,
        }
    return None


def run_all_checks() -> dict:
    """跑所有 anomaly check。檢測到立刻 halt + Telegram。"""
    cfg = get_config()
    if cfg.get('halted'):
        return {'skipped': 'already halted'}

    fired = []
    for check in (check_flash_crash, check_concurrent_positions):
        try:
            r = check()
            if r:
                fired.append(r)
        except Exception as e:
            fired.append({'type': f'{check.__name__}_error', 'error': f'{type(e).__name__}: {e}'})

    if fired:
        # 把所有觸發的原因都塞進 halt_reason
        reasons = []
        for f in fired:
            if f['type'] == 'flash_crash':
                reasons.append(f'flash crash {f["pct"]:.2f}% in {f["window_bars"]}min')
            elif f['type'] == 'concurrent_positions':
                reasons.append(f'positions {f["open"]}>{f["max"]}')
            else:
                reasons.append(f.get('type', 'unknown'))
        reason = 'anomaly: ' + '; '.join(reasons)
        set_halted(reason)
        notify_halt(reason)

    return {'fired': fired, 'halted': bool(fired)}
