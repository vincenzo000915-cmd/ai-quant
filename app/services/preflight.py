"""Phase 6.6: 切換 LIVE 前的 pre-flight 檢查清單

每項 check 回 {name, ok, message}。任何一項 ok=False 都不允許切到 live。
特意把每個 check 隔離，UI 才能逐項顯示「過 / 沒過 / 為什麼」。
"""
from __future__ import annotations

import os
from app.extensions import db
from app.models import SystemConfig
from app.services.config_service import get_config


def _check_okx_credentials() -> dict:
    missing = [k for k in ('EXCHANGE_API_KEY', 'EXCHANGE_SECRET', 'EXCHANGE_PASSPHRASE') if not os.environ.get(k)]
    if missing:
        return {'name': 'OKX API 憑證', 'ok': False, 'message': f'缺 env: {", ".join(missing)}'}
    return {'name': 'OKX API 憑證', 'ok': True, 'message': '已設定 API_KEY / SECRET / PASSPHRASE'}


def _check_okx_balance_query() -> dict:
    """打 OKX 私有 balance 端點 — 證明 key + secret + passphrase 至少有 Read 權限"""
    import os
    api_key = os.environ.get('EXCHANGE_API_KEY')
    secret = os.environ.get('EXCHANGE_SECRET')
    passphrase = os.environ.get('EXCHANGE_PASSPHRASE')
    if not (api_key and secret and passphrase):
        return {'name': 'OKX Read 權限', 'ok': False, 'message': '憑證未完整'}
    try:
        from app.services.exchange_service import _okx_get_signed
        data = _okx_get_signed('/api/v5/account/balance', api_key, secret, passphrase)
        if data:
            total = data[0].get('totalEq', 'n/a')
            return {'name': 'OKX Read 權限', 'ok': True, 'message': f'帳戶總權益 USD ~{total}'}
        return {'name': 'OKX Read 權限', 'ok': False, 'message': '回應為空'}
    except Exception as e:
        return {'name': 'OKX Read 權限', 'ok': False, 'message': f'{type(e).__name__}: {str(e)[:120]}'}


def _check_okx_trade_scope() -> dict:
    """OKX set-leverage 是 Trade scope 才能呼叫。試一次（idempotent，重設同 leverage 也 OK）"""
    import os
    api_key = os.environ.get('EXCHANGE_API_KEY')
    secret = os.environ.get('EXCHANGE_SECRET')
    passphrase = os.environ.get('EXCHANGE_PASSPHRASE')
    if not (api_key and secret and passphrase):
        return {'name': 'OKX Trade 權限', 'ok': False, 'message': '憑證未完整'}
    try:
        from app.services.exchange_service import _okx_post_signed
        cfg = get_config()
        lev = int(cfg.get('leverage', 15.0))
        _okx_post_signed('/api/v5/account/set-leverage',
                         {'instId': 'BTC-USDT-SWAP', 'lever': str(lev), 'mgnMode': 'cross'},
                         api_key, secret, passphrase)
        return {'name': 'OKX Trade 權限', 'ok': True, 'message': f'set-leverage 成功 (BTC-USDT-SWAP × {lev})'}
    except Exception as e:
        return {'name': 'OKX Trade 權限', 'ok': False, 'message': f'{type(e).__name__}: {str(e)[:160]}'}


def _check_telegram() -> dict:
    """Telegram 憑證 + 實際發一則測試訊息"""
    from app.services.telegram_service import _enabled, send
    if not _enabled():
        return {'name': 'Telegram 告警', 'ok': False, 'message': 'TELEGRAM_BOT_TOKEN/CHAT_ID 未設定（建議補上，halt/kill switch 才會通知）'}
    r = send('🛫 <b>Pre-flight 測試訊息</b>\n這則來自 LIVE 解鎖前的檢查。', force=True)
    if r.get('sent'):
        return {'name': 'Telegram 告警', 'ok': True, 'message': '測試訊息送達'}
    return {'name': 'Telegram 告警', 'ok': False, 'message': f'sendMessage 失敗: {r.get("reason")}'}


def _check_risk_params() -> dict:
    cfg = get_config()
    issues = []
    if cfg.get('max_daily_loss_usdt', 0) <= 0:
        issues.append('max_daily_loss_usdt 必須 > 0 才有 halt 保護')
    if cfg.get('leverage', 0) > 25:
        issues.append(f'leverage={cfg["leverage"]} > 25，實盤建議 ≤ 25')
    if cfg.get('trade_size_usdt', 0) <= 0:
        issues.append('trade_size_usdt 必須 > 0')
    if cfg.get('trade_size_usdt', 0) >= cfg.get('capital_usdt', 1):
        issues.append(f'trade_size {cfg.get("trade_size_usdt")} ≥ capital {cfg.get("capital_usdt")}，單次梭哈太危險')
    if issues:
        return {'name': '風控參數', 'ok': False, 'message': '; '.join(issues)}
    return {'name': '風控參數', 'ok': True,
            'message': f'capital ${cfg["capital_usdt"]}, trade ${cfg["trade_size_usdt"]}, lev {cfg["leverage"]}x, daily-loss-cap ${cfg["max_daily_loss_usdt"]}'}


def _check_not_halted() -> dict:
    cfg = get_config()
    if cfg.get('halted'):
        return {'name': '系統未 halt', 'ok': False, 'message': f'目前 halted: {cfg.get("halt_reason")}'}
    return {'name': '系統未 halt', 'ok': True, 'message': 'halted=False'}


def _check_celery_armed() -> dict:
    """確認 monitor_daily_loss + monitor_anomalies 都註冊在 worker 上"""
    try:
        from app.extensions import celery_app
        registered = set(celery_app.tasks.keys())
        needed = {
            'app.tasks.strategy_tasks.monitor_daily_loss',
            'app.tasks.strategy_tasks.monitor_anomalies',
            'app.tasks.strategy_tasks.monitor_strategy_health',
        }
        missing = needed - registered
        if missing:
            return {'name': 'Celery 風控任務', 'ok': False, 'message': f'未註冊: {", ".join(missing)}'}
        return {'name': 'Celery 風控任務', 'ok': True, 'message': '6.1 / 6.4 / 5.3 監控任務皆就緒'}
    except Exception as e:
        return {'name': 'Celery 風控任務', 'ok': False, 'message': f'{type(e).__name__}: {e}'}


def run_preflight() -> dict:
    """跑全套 pre-flight。回傳 {ok, checks}"""
    checks = [
        _check_okx_credentials(),
        _check_okx_balance_query(),
        _check_okx_trade_scope(),
        _check_telegram(),
        _check_risk_params(),
        _check_not_halted(),
        _check_celery_armed(),
    ]
    return {
        'ok': all(c['ok'] for c in checks),
        'pass_count': sum(1 for c in checks if c['ok']),
        'total': len(checks),
        'checks': checks,
    }
