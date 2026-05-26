"""Telegram 告警 — Phase 6.2

讀 .env 的 TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID。沒設值就靜默 skip
（不要拖累交易主流程）。每則訊息有 dedupe：同一 (event_key, body) 30s 內不重發。

用 urllib 不引入新依賴。
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

_LAST_SENT: dict[str, tuple[str, float]] = {}  # key -> (body_hash, ts)
_DEDUPE_TTL = 30  # 秒


def _enabled() -> bool:
    return bool(os.environ.get('TELEGRAM_BOT_TOKEN')) and bool(os.environ.get('TELEGRAM_CHAT_ID'))


def send(text: str, *, parse_mode: str = 'HTML', event_key: str | None = None, force: bool = False) -> dict:
    """送一則訊息。回傳 dict {'sent': bool, 'reason': str?, 'response': ...?}

    event_key: 同一 key + 同一 text 在 30s 內只發一次（避免風暴）。
    force=True 跳過 dedupe。
    """
    if not _enabled():
        return {'sent': False, 'reason': 'TELEGRAM_BOT_TOKEN/CHAT_ID not set'}

    if event_key and not force:
        key = event_key
        last = _LAST_SENT.get(key)
        now = time.time()
        body_hash = str(hash(text))
        if last and last[0] == body_hash and (now - last[1]) < _DEDUPE_TTL:
            return {'sent': False, 'reason': 'deduped (same event_key + body within 30s)'}
        _LAST_SENT[key] = (body_hash, now)

    token = os.environ['TELEGRAM_BOT_TOKEN']
    chat_id = os.environ['TELEGRAM_CHAT_ID']
    url = f'https://api.telegram.org/bot{token}/sendMessage'

    payload = urllib.parse.urlencode({
        'chat_id': chat_id,
        'text': text,
        'parse_mode': parse_mode,
        'disable_web_page_preview': 'true',
    }).encode()

    try:
        req = urllib.request.Request(url, data=payload, method='POST')
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode('utf-8', errors='ignore'))
        if not body.get('ok'):
            return {'sent': False, 'reason': f'telegram api: {body}'}
        return {'sent': True, 'response': body}
    except Exception as e:
        return {'sent': False, 'reason': f'{type(e).__name__}: {e}'}


# === 高層輔助：常見事件的格式化 ===

# Phase 14k-42: 中英双语映射 — 所有通知中文为主, 英文补 (i18n / SaaS 海外用户友好)
_SIDE_ZH = {'long': '做多', 'short': '做空', 'buy': '买入', 'sell': '卖出'}
_SIDE_EN = {'long': 'LONG', 'short': 'SHORT', 'buy': 'BUY', 'sell': 'SELL'}
_CLOSE_REASON_ZH = {
    'take_profit': '触发止盈',
    'stop_loss': '触发止损',
    'manual': '手动平仓',
    'kill_switch': '紧急平仓',
    'reverse_signal': '反向信号',
    'end_of_period': '回测结束',
    'close': '平仓信号',
}
_CLOSE_REASON_EN = {
    'take_profit': 'Take Profit',
    'stop_loss': 'Stop Loss',
    'manual': 'Manual',
    'kill_switch': 'Kill Switch',
    'reverse_signal': 'Reverse Signal',
    'end_of_period': 'End of Period',
    'close': 'Close Signal',
}


def notify_open(strategy_name: str, symbol: str, side: str, size: float, price: float, notional: float):
    side_zh = _SIDE_ZH.get(str(side).lower(), side)
    side_en = _SIDE_EN.get(str(side).lower(), side.upper())
    text = (f'🟢 <b>开仓 / Open</b> {strategy_name}\n'
            f'{symbol} · {side_zh} ({side_en}) · {size:.6f} · ${price:.2f}\n'
            f'仓位 / Size: ${notional:.0f}')
    return send(text, event_key=f'open:{strategy_name}')


def notify_close(strategy_name: str, symbol: str, price: float, pnl: float, pnl_pct: float, reason: str):
    emoji = '🟢' if pnl > 0 else '🔴'
    reason_zh = _CLOSE_REASON_ZH.get(str(reason).lower(), reason)
    reason_en = _CLOSE_REASON_EN.get(str(reason).lower(), reason)
    text = (f'{emoji} <b>平仓 / Close</b> {strategy_name}\n'
            f'{symbol} @ ${price:.2f}\n'
            f'盈亏 / PnL: ${pnl:+.2f} ({pnl_pct:+.2f}%) · {reason_zh} / {reason_en}')
    return send(text, event_key=f'close:{strategy_name}')


def notify_halt(reason: str):
    text = (f'🛑 <b>系统已自动停单 / System Halted</b>\n'
            f'原因 / Reason: {reason}\n\n'
            f'所有新开仓信号被拒. 请到 Dashboard 解除停单状态后才能继续交易.\n'
            f'All new entry signals rejected. Resolve halt state on Dashboard to resume.')
    return send(text, event_key='halt', force=True)


def notify_retire(strategy_name: str, reason: str):
    text = (f'🪦 <b>策略已退役 / Strategy Retired</b> {strategy_name}\n'
            f'原因 / Reason: {reason}')
    return send(text, event_key=f'retire:{strategy_name}')


def notify_kill_switch(reason: str = '手动'):
    text = (f'🆘 <b>紧急停止已启动 / Kill Switch Activated</b>\n'
            f'触发原因 / Trigger: {reason}\n'
            f'所有策略已停止, 所有持仓已强制平仓.\n'
            f'All strategies stopped, all positions force-closed.')
    return send(text, event_key='kill', force=True)
