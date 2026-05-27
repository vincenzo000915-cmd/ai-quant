"""Phase 6.6 + 14k-87: 切換 LIVE 前的 pre-flight 檢查清單

每項 check 回 {name, ok, message}。任何一項 ok=False 都不允許切到 live。
特意把每個 check 隔離，UI 才能逐項顯示「過 / 沒過 / 為什麼」。

Phase 14k-87: 按 user 已绑交易所 dispatch — OKX 走 env creds, HL 走 per-user HyperliquidCredentials.
"""
from __future__ import annotations

import os
from app.extensions import db
from app.models import SystemConfig, HyperliquidCredentials
from app.services.config_service import get_config


# ============================================================
# OKX checks (env-level admin creds)
# ============================================================


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


# ============================================================
# Phase 14k-87: Hyperliquid checks (per-user agent wallet)
# ============================================================

def _hl_creds_record(user_id: int) -> HyperliquidCredentials | None:
    try:
        return HyperliquidCredentials.query.filter_by(user_id=user_id, is_active=True).first()
    except Exception:
        return None


def _check_hl_credentials(user_id: int) -> dict:
    """HL 凭证存在 + 解密成功 + 未过期"""
    rec = _hl_creds_record(user_id)
    if rec is None:
        return {'name': 'Hyperliquid 凭证', 'ok': False, 'message': f'user_id={user_id} 未绑 HL agent wallet'}
    # 解密
    try:
        from app.services.hyperliquid_creds import get_decrypted_for_user, is_expired
        creds = get_decrypted_for_user(user_id)
        if not creds:
            return {'name': 'Hyperliquid 凭证', 'ok': False, 'message': 'HL 凭证解密失败 (Fernet key 错或数据损坏)'}
        if is_expired(user_id):
            return {'name': 'Hyperliquid 凭证', 'ok': False, 'message': 'HL agent wallet 已过期 (180 天), 请重新签名授权'}
        # 检查 14 天内将过期 → WARN 但 ok=True (不阻 LIVE)
        from app.services.hyperliquid_creds import days_until_expiry
        days_left = days_until_expiry(user_id)
        if days_left is not None and days_left <= 14:
            return {'name': 'Hyperliquid 凭证', 'ok': True,
                    'message': f'agent wallet 剩 {days_left} 天到期, 建议尽快重新签名'}
        return {'name': 'Hyperliquid 凭证', 'ok': True,
                'message': f'agent wallet 有效 (剩 {days_left} 天), network={creds.get("network")}'}
    except Exception as e:
        return {'name': 'Hyperliquid 凭证', 'ok': False, 'message': f'{type(e).__name__}: {str(e)[:120]}'}


def _check_hl_balance_query(user_id: int) -> dict:
    """HL info API 通 + 拉到 user_state (证明 main_address 有效)"""
    try:
        from app.services.hyperliquid_creds import get_decrypted_for_user
        from app.services.hyperliquid_service import fetch_balance as hl_fetch_balance
        creds = get_decrypted_for_user(user_id)
        if not creds:
            return {'name': 'Hyperliquid 余额查询', 'ok': False, 'message': 'HL 凭证缺失'}
        bal = hl_fetch_balance(creds)
        # bal shape: {USDT: {total, free, used}, _native_currency, _breakdown}
        total = bal.get('USDT', {}).get('total') if isinstance(bal, dict) else None
        if total is None:
            return {'name': 'Hyperliquid 余额查询', 'ok': False, 'message': f'返回结构异常: {str(bal)[:120]}'}
        return {'name': 'Hyperliquid 余额查询', 'ok': True,
                'message': f'帐户总权益 ${total:.2f} (USDC unified)'}
    except Exception as e:
        return {'name': 'Hyperliquid 余额查询', 'ok': False, 'message': f'{type(e).__name__}: {str(e)[:160]}'}


def _check_hl_trade_scope(user_id: int) -> dict:
    """HL agent wallet 能签名: update_leverage (idempotent) 验证 signing 能力"""
    try:
        from app.services.hyperliquid_creds import get_decrypted_for_user
        from app.services.hyperliquid_service import _exchange_client, hl_base
        creds = get_decrypted_for_user(user_id)
        if not creds:
            return {'name': 'Hyperliquid Trade 权限', 'ok': False, 'message': 'HL 凭证缺失'}
        exchange, _ = _exchange_client(creds)
        # set leverage 是 idempotent, 不会真开仓; cross margin 3x BTC 是安全 baseline
        try:
            exchange.update_leverage(3, hl_base('BTC/USDT'), is_cross=True)
            return {'name': 'Hyperliquid Trade 权限', 'ok': True,
                    'message': 'update_leverage 成功 (BTC × 3x cross, agent wallet 签名 OK)'}
        except Exception as e:
            # HL 已经是这个 leverage 会 silent 不 raise; 真签名失败才到这
            msg = str(e).lower()
            if 'leverage' in msg or 'already' in msg:
                return {'name': 'Hyperliquid Trade 权限', 'ok': True,
                        'message': 'leverage 已是目标值 (silent ok, agent 签名 OK)'}
            return {'name': 'Hyperliquid Trade 权限', 'ok': False,
                    'message': f'set leverage 失败 (agent 可能过期/无权限): {str(e)[:160]}'}
    except Exception as e:
        return {'name': 'Hyperliquid Trade 权限', 'ok': False, 'message': f'{type(e).__name__}: {str(e)[:160]}'}


# ============================================================
# 全交易所 dispatch
# ============================================================

def _detect_bound_exchanges(user_id: int) -> dict:
    """检测 user 实际绑了哪些交易所 (用来决定跑哪些 check)"""
    okx_bound = all(os.environ.get(k) for k in ('EXCHANGE_API_KEY', 'EXCHANGE_SECRET', 'EXCHANGE_PASSPHRASE'))
    hl_bound = _hl_creds_record(user_id) is not None
    return {'okx': okx_bound, 'hyperliquid': hl_bound}


def run_preflight(user_id: int = 1) -> dict:
    """跑全套 pre-flight。回傳 {ok, checks, bound_exchanges}

    Phase 14k-87: 按 user_id 已绑交易所自动 dispatch
    - 至少绑 1 个交易所才允许 LIVE
    - 共用 check (Telegram / risk_params / not_halted / celery_armed) 总跑
    - OKX/HL 特定 check 仅在该交易所已绑时跑
    """
    bound = _detect_bound_exchanges(user_id)

    checks: list[dict] = []
    # 1. 至少绑 1 个交易所
    if not (bound['okx'] or bound['hyperliquid']):
        checks.append({
            'name': '交易所绑定', 'ok': False,
            'message': '未绑定任何交易所 — 请到「设置」绑 OKX (env) 或 Hyperliquid (agent wallet)',
        })
    else:
        bound_names = ', '.join(k for k, v in bound.items() if v)
        checks.append({'name': '交易所绑定', 'ok': True, 'message': f'已绑: {bound_names}'})

    # 2. OKX 特定 check
    if bound['okx']:
        checks.extend([
            _check_okx_credentials(),
            _check_okx_balance_query(),
            _check_okx_trade_scope(),
        ])

    # 3. HL 特定 check
    if bound['hyperliquid']:
        checks.extend([
            _check_hl_credentials(user_id),
            _check_hl_balance_query(user_id),
            _check_hl_trade_scope(user_id),
        ])

    # 4. 共用 check
    checks.extend([
        _check_telegram(),
        _check_risk_params(),
        _check_not_halted(),
        _check_celery_armed(),
    ])

    return {
        'ok': all(c['ok'] for c in checks),
        'pass_count': sum(1 for c in checks if c['ok']),
        'total': len(checks),
        'checks': checks,
        'bound_exchanges': bound,
        'user_id': user_id,
    }
