"""交易所服務模組 - 封裝 CCXT 接口"""
import ccxt
import requests
import time
import json
import hmac
import base64
from datetime import datetime
from flask import current_app
from app.extensions import db
from app.models import Candle


OKX_REST = 'https://www.okx.com'


def _okx_get(path, params=None):
    """OKX 公開 API GET 請求（無需簽名）"""
    headers = {'Content-Type': 'application/json'}
    url = f'{OKX_REST}{path}'
    if params:
        qs = '&'.join(f'{k}={v}' for k, v in params.items())
        url = f'{url}?{qs}'
    resp = requests.get(url, headers=headers, timeout=8)
    data = resp.json()
    if data.get('code') != '0':
        raise Exception(f'OKX API error: {data.get("msg", "unknown")}')
    return data.get('data', [])


def _okx_post_signed(path, body_dict, api_key, secret, passphrase):
    """OKX 私有 API POST 請求（簽名包含 body）"""
    import json as _json
    ts = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    method = 'POST'
    body = _json.dumps(body_dict, separators=(',', ':')) if body_dict else ''
    msg = f'{ts}{method}{path}{body}'
    mac = hmac.new(secret.encode('utf-8'), msg.encode('utf-8'), 'sha256')
    sign = base64.b64encode(mac.digest()).decode('utf-8')
    headers = {
        'OK-ACCESS-KEY': api_key,
        'OK-ACCESS-SIGN': sign,
        'OK-ACCESS-TIMESTAMP': ts,
        'OK-ACCESS-PASSPHRASE': passphrase,
        'Content-Type': 'application/json',
    }
    resp = requests.post(f'{OKX_REST}{path}', headers=headers, data=body, timeout=10)
    data = resp.json()
    if data.get('code') != '0':
        raise Exception(f'OKX POST {path} error: code={data.get("code")} msg={data.get("msg")} sCode={(data.get("data") or [{}])[0].get("sCode") if data.get("data") else None}')
    return data.get('data', [])


def _okx_get_signed(path, api_key, secret, passphrase):
    """OKX 私有 API GET 請求（帶簽名）"""
    ts = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    method = 'GET'
    body = ''
    msg = f'{ts}{method}{path}{body}'
    mac = hmac.new(
        secret.encode('utf-8'),
        msg.encode('utf-8'),
        'sha256'
    )
    sign = base64.b64encode(mac.digest()).decode('utf-8')
    headers = {
        'OK-ACCESS-KEY': api_key,
        'OK-ACCESS-SIGN': sign,
        'OK-ACCESS-TIMESTAMP': ts,
        'OK-ACCESS-PASSPHRASE': passphrase,
        'Content-Type': 'application/json',
    }
    resp = requests.get(f'{OKX_REST}{path}', headers=headers, timeout=8)
    data = resp.json()
    if data.get('code') != '0':
        raise Exception(f'OKX API error: {data.get("msg", "unknown")}')
    return data.get('data', [])


def get_exchange():
    """取得 CCXT Exchange 實例（支援測試網）"""
    app = current_app._get_current_object()
    config = app.config

    exchange_name = config.get('EXCHANGE_NAME', 'binance')
    api_key = config.get('EXCHANGE_API_KEY', '')
    secret = config.get('EXCHANGE_SECRET', '')
    testnet = config.get('EXCHANGE_TESTNET', True)

    exchange_class = getattr(ccxt, exchange_name)

    exchange_params = {
        'apiKey': api_key,
        'secret': secret,
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'},
        'timeout': 10000,  # 10 second timeout
    }

    # OKX 需要 passphrase
    if exchange_name == 'okx':
        passphrase = config.get('EXCHANGE_PASSPHRASE', '')
        exchange_params['password'] = passphrase

    exchange = exchange_class(exchange_params)

    if testnet:
        if exchange_name == 'binance':
            exchange.set_sandbox_mode(True)
        elif exchange_name == 'okx':
            # OKX 沒有公開測試網，直接使用正式網
            pass

    return exchange


_OKX_TF_MAP = {
    '1m': '1m', '3m': '3m', '5m': '5m', '15m': '15m', '30m': '30m',
    '1h': '1H', '2h': '2H', '4h': '4H', '6h': '6H', '12h': '12H',
    '1d': '1D', '1w': '1W',
}


def _okx_symbol(symbol):
    """BTC/USDT → BTC-USDT"""
    return symbol.replace('/', '-')


def fetch_ohlcv(symbol='BTC/USDT', timeframe='4h', limit=500):
    """獲取K線數據並存入資料庫（直接 OKX REST，繞過 CCXT bug）"""
    inst_id = _okx_symbol(symbol)
    bar = _OKX_TF_MAP.get(timeframe, timeframe.upper())

    # OKX 單次最多 300 筆，limit > 300 要分頁
    all_rows = []
    fetched = 0
    after = ''
    per_page = min(300, limit)

    while fetched < limit:
        params = {'instId': inst_id, 'bar': bar, 'limit': per_page}
        if after:
            params['after'] = after
        data = _okx_get('/api/v5/market/candles', params)
        if not data:
            break
        all_rows.extend(data)
        fetched += len(data)
        if len(data) < per_page:
            break
        after = data[-1][0]  # 最舊的 timestamp 當下一頁起點

    if not all_rows:
        return []

    # OKX 返回 [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
    candles = []
    for r in all_rows:
        ts = int(r[0]) // 1000  # ms → s
        candle = Candle.query.filter_by(
            symbol=symbol, timeframe=timeframe, timestamp=ts
        ).first()

        if not candle:
            candle = Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=ts,
                open=float(r[1]),
                high=float(r[2]),
                low=float(r[3]),
                close=float(r[4]),
                volume=float(r[5]),
            )
            db.session.add(candle)
        else:
            candle.open = float(r[1])
            candle.high = float(r[2])
            candle.low = float(r[3])
            candle.close = float(r[4])
            candle.volume = float(r[5])

        candles.append(candle)

    db.session.commit()

    # 清理舊數據，保留最近 limit 筆
    total = Candle.query.filter_by(symbol=symbol, timeframe=timeframe).count()
    if total > limit:
        to_delete = Candle.query.filter_by(symbol=symbol, timeframe=timeframe)\
            .order_by(Candle.timestamp.asc()).limit(total - limit).all()
        for c in to_delete:
            db.session.delete(c)
        db.session.commit()

    return [c.to_dict() for c in candles]


def create_order(symbol, side, order_type, amount, price=None):
    """下單"""
    exchange = get_exchange()
    try:
        if order_type == 'market':
            order = exchange.create_market_order(symbol, side, amount)
        else:
            order = exchange.create_limit_order(symbol, side, amount, price)
        return order
    except Exception as e:
        raise Exception(f'下單失敗: {str(e)}')


def fetch_balance():
    """獲取帳戶餘額（直接 OKX API，繞過 CCXT bug）"""
    app = current_app._get_current_object()
    config = app.config
    api_key = config.get('EXCHANGE_API_KEY', '')
    secret = config.get('EXCHANGE_SECRET', '')
    passphrase = config.get('EXCHANGE_PASSPHRASE', '')

    try:
        data = _okx_get_signed('/api/v5/account/balance', api_key, secret, passphrase)
        details = data[0].get('details', []) if data else []
        result = {}
        for d in details:
            ccy = d.get('ccy', '')
            total_val = float(d.get('cashBal', 0) or 0)
            avail_val = float(d.get('availBal', 0) or 0)
            if total_val > 0 or ccy in ('USDT', 'BTC', 'ETH'):
                result[ccy] = {
                    'total': total_val,
                    'free': avail_val,
                    'used': total_val - avail_val,
                }
        return result
    except Exception as e:
        raise Exception(f'獲取餘額失敗: {str(e)}')


def fetch_okx_order_real_pnl(inst_id: str, ord_id: str | None = None,
                              max_wait_sec: float = 5.0) -> dict:
    """Phase 12.10 + 12.12.2: 查 OKX 真實成交盈虧（含手續費）。

    用 /api/v5/account/bills 拉最近交易帳單，找匹配 instId（並 ordId）的 type=2 行。
    回傳 {price_pnl, fee, real_pnl, fill_count}：
      price_pnl: OKX 內部 pnl 字段（價格 delta，不含手續費）合計
      fee: 手續費合計（負值）
      real_pnl: 真實對帳戶餘額影響 = price_pnl + fee（balChg）合計
      fill_count: 匹配到的帳單條數（拆單時 > 1）

    Phase 12.12.2: 大單會被 OKX 拆成多筆成交（同 ordId 多條 bill）。
    舊版只取第一條 → 漏算後續部分。新版：
      - 找到至少 1 條後，多 poll 1 次確認沒新增（穩定）
      - 找到後合計所有匹配 bill 的 pnl/fee/balChg
      - 只在 ord_id 明確時才合計（避免不同 order 混在一起）

    OKX 帳單有延遲（< 3s），給 5s buffer。
    """
    import os, time as _time
    api_key = os.environ.get('EXCHANGE_API_KEY')
    secret = os.environ.get('EXCHANGE_SECRET')
    passphrase = os.environ.get('EXCHANGE_PASSPHRASE')
    if not (api_key and secret and passphrase):
        return {'price_pnl': 0.0, 'fee': 0.0, 'real_pnl': 0.0, 'found': False, 'fill_count': 0, 'error': 'no creds'}

    def _scan():
        try:
            bills = _okx_get_signed(
                '/api/v5/account/bills?instType=SWAP&ccy=USDT&limit=50',
                api_key, secret, passphrase,
            )
        except Exception as e:
            return None, str(e)
        ms = []
        for b in bills:
            if b.get('instId') != inst_id:
                continue
            if ord_id and b.get('ordId') != ord_id:
                continue
            if str(b.get('type')) != '2':
                continue
            ms.append(b)
        return ms, None

    deadline = _time.time() + max_wait_sec
    last_err = None
    prev_count = -1
    matches: list[dict] = []
    while _time.time() < deadline:
        ms, err = _scan()
        if err:
            last_err = err
            _time.sleep(0.5)
            continue
        if ms:
            # 找到至少 1 條 — 多 poll 一次確認穩定（OKX 可能還在分批寫）
            if len(ms) == prev_count:
                matches = ms
                break
            prev_count = len(ms)
        _time.sleep(0.7)

    if not matches:
        return {'price_pnl': 0.0, 'fee': 0.0, 'real_pnl': 0.0, 'found': False, 'fill_count': 0,
                'error': last_err or 'timeout'}

    # 多筆累加 — 只在 ord_id 明確時才安全（不同 order 不要混）
    if ord_id:
        agg = [(float(m.get('pnl') or 0), float(m.get('fee') or 0), float(m.get('balChg') or 0)) for m in matches]
        total_pnl = sum(p for p, _, _ in agg)
        total_fee = sum(f for _, f, _ in agg)
        total_bal = sum(b for _, _, b in agg)
        return {
            'price_pnl': total_pnl, 'fee': total_fee, 'real_pnl': total_bal,
            'found': True, 'fill_count': len(matches),
            'ord_id': ord_id, 'bill_ids': [m.get('billId') for m in matches],
        }
    # 沒 ord_id：保留舊行為，只取第一筆
    m = matches[0]
    return {
        'price_pnl': float(m.get('pnl') or 0), 'fee': float(m.get('fee') or 0),
        'real_pnl': float(m.get('balChg') or 0), 'found': True, 'fill_count': 1,
        'bill_id': m.get('billId'), 'ord_id': m.get('ordId'),
    }


def fetch_okx_positions() -> list[dict]:
    """Phase 8.2: 拉 OKX 真實 SWAP 持倉。回傳 [{inst_id, pos_contracts, side, avg_px, upl, ...}]
    pos > 0 → long；pos < 0 → short；pos == 0 → 無持倉（OKX 仍會返回該 entry）。
    """
    import os
    api_key = os.environ.get('EXCHANGE_API_KEY')
    secret = os.environ.get('EXCHANGE_SECRET')
    passphrase = os.environ.get('EXCHANGE_PASSPHRASE')
    if not (api_key and secret and passphrase):
        raise RuntimeError('OKX credentials missing')

    # 用 query string 過濾只看 SWAP
    data = _okx_get_signed('/api/v5/account/positions?instType=SWAP', api_key, secret, passphrase)
    result = []
    for p in data:
        pos = float(p.get('pos') or 0)
        if pos == 0:
            continue  # 無實際持倉的條目跳過
        # hedge mode (long_short_mode) → posSide 字段直接給 'long' / 'short'
        # net mode → posSide='net'，這時才看 pos 符號判方向
        pos_side = p.get('posSide')
        if pos_side in ('long', 'short'):
            side = pos_side
        else:
            side = 'long' if pos > 0 else 'short'
        result.append({
            'inst_id': p.get('instId'),
            'pos_contracts': pos,
            'side': side,
            'avg_px': float(p.get('avgPx') or 0),
            'upl': float(p.get('upl') or 0),
            'lever': float(p.get('lever') or 0),
            'mgn_mode': p.get('mgnMode'),
            'pos_id': p.get('posId'),
            'symbol': (p.get('instId') or '').replace('-SWAP', '').replace('-', '/'),
        })
    return result


# 永久性錯誤碼（不重試）— 來自 OKX docs，重試也是同樣失敗
# 51008 insufficient balance, 51020 below min, 51119 over max
# 51000 / 51001 / 51124 / 51169 等都是參數錯
_OKX_PERMANENT_ERRORS = {
    '51000', '51001', '51002', '51003', '51004', '51005', '51006',
    '51008', '51020', '51119', '51124', '51169',
    '50000', '50004',   # 系統參數 / 服務暫停（不是 5xx 而是 OKX 顯式拒絕）
}


def _is_permanent_okx_error(err_str: str) -> bool:
    """OKX 錯誤訊息含這些 code 視為永久失敗"""
    for code in _OKX_PERMANENT_ERRORS:
        if code in err_str:
            return True
    # 其他 'invalid'/'insufficient' 字眼也視為永久
    low = err_str.lower()
    if 'insufficient' in low or 'invalid parameter' in low or 'parameter error' in low:
        return True
    return False


def _gen_client_order_id() -> str:
    """生成 1-32 字元 alphanumeric clOrdId"""
    import uuid
    # 'q' + 31 字元 hex（uuid4 hex 32 字元，取前 31）
    return 'q' + uuid.uuid4().hex[:31]


def place_order_live(symbol: str, side: str, size_usdt: float, leverage: float = 15.0,
                     client_order_id: str | None = None, max_retries: int = 3,
                     pos_side: str | None = None) -> dict:
    """Phase 6.5 + 8.3: 真實下單 — OKX swap 永續合約（cross margin），ordType=market。

    8.3 加入：
      - client_order_id (clOrdId) — OKX 同 clOrdId 重複呼叫返回原訂單，天然防重
      - exponential backoff retry — 暫時性錯誤（網路 / 5xx）重試最多 max_retries 次
      - 永久性錯誤碼直接 raise，不重試

    回傳 OKX 原始 order data。失敗 raise。
    """
    import os
    import time as _time
    api_key = os.environ.get('EXCHANGE_API_KEY')
    secret = os.environ.get('EXCHANGE_SECRET')
    passphrase = os.environ.get('EXCHANGE_PASSPHRASE')
    if not (api_key and secret and passphrase):
        raise RuntimeError('OKX API credentials missing in env')

    from app.services.symbols import get_inst_id, get_contract_size
    inst_id = get_inst_id(symbol)
    contract_size = get_contract_size(symbol)
    cl_ord_id = client_order_id or _gen_client_order_id()

    # 先設 leverage（OKX 原生 idempotent — 重設同值不 raise）
    try:
        _okx_post_signed('/api/v5/account/set-leverage',
                         {'instId': inst_id, 'lever': str(int(leverage)), 'mgnMode': 'cross'},
                         api_key, secret, passphrase)
    except Exception as e:
        # leverage 已經是這個值的話可能 silent OK；其他錯就 raise
        if 'leverage' not in str(e).lower():
            raise

    # 計算合約張數：依該幣 contract_size 動態算
    notional = size_usdt * leverage
    ticker = get_ticker(symbol)
    price = float(ticker['price'])
    base_amount = notional / price            # 換成 base currency 量
    contracts = round(base_amount / contract_size, 0)
    if contracts < 1:
        contracts = 1

    body = {
        'instId': inst_id,
        'tdMode': 'cross',
        'side': side,            # 'buy' / 'sell'
        'ordType': 'market',
        'sz': str(int(contracts)),
        'clOrdId': cl_ord_id,    # 8.3: 防重
    }
    # 若帳號是 long_short_mode 必須帶 posSide。net mode 不會看這欄。
    # caller 沒傳就推：buy → long，sell → short（只對「開倉」正確；平倉 caller 必須顯式傳）
    if pos_side:
        body['posSide'] = pos_side
    else:
        body['posSide'] = 'long' if side == 'buy' else 'short'

    # 8.3: exponential backoff retry — 暫時性錯誤重試最多 max_retries 次
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            data = _okx_post_signed('/api/v5/trade/order', body, api_key, secret, passphrase)
            return {
                'okx': data[0] if data else {},
                'inst_id': inst_id,
                'contracts': contracts,
                'notional_usdt': notional,
                'entry_price_est': price,
                'client_order_id': cl_ord_id,
                'attempts': attempt + 1,
            }
        except Exception as e:
            err_str = str(e)
            last_err = e
            # 永久錯誤不重試
            if _is_permanent_okx_error(err_str):
                raise
            if attempt < max_retries:
                # exponential backoff: 0.5s, 1s, 2s
                wait = 0.5 * (2 ** attempt)
                _time.sleep(wait)
                continue
            # 已達上限
            break

    raise RuntimeError(f'place_order_live exhausted retries ({max_retries+1} attempts): {last_err}')


def cancel_order(order_id, symbol):
    """取消訂單"""
    exchange = get_exchange()
    return exchange.cancel_order(order_id, symbol)


def fetch_ohlcv_history(symbol='BTC/USDT', timeframe='4h', total_limit=2000):
    """為回測拉大量歷史 K 線（不寫入 Candle 表，純記憶體返回）

    用 OKX history-candles + candles 雙端點分頁拉取。
    返回 [{ timestamp(秒), open, high, low, close, volume }, ...]
    """
    inst_id = _okx_symbol(symbol) if '/' in symbol else symbol
    bar = _OKX_TF_MAP.get(timeframe, timeframe.upper())

    all_rows = []
    after = ''  # 比此時間更早

    # 先用 /candles 拉最近 300
    data = _okx_get('/api/v5/market/candles', {'instId': inst_id, 'bar': bar, 'limit': 300})
    if data:
        all_rows.extend(data)

    # 不夠的話用 history-candles 往前翻
    if all_rows and len(all_rows) < total_limit:
        after = all_rows[-1][0]
        while len(all_rows) < total_limit:
            page = _okx_get('/api/v5/market/history-candles', {
                'instId': inst_id, 'bar': bar, 'limit': 100, 'after': after,
            })
            if not page:
                break
            all_rows.extend(page)
            after = page[-1][0]
            if len(page) < 100:
                break

    # 解析 + 反序（OKX 返回新→舊，我們要舊→新）
    candles = []
    for r in reversed(all_rows):
        candles.append({
            'timestamp': int(r[0]) // 1000,
            'open': float(r[1]),
            'high': float(r[2]),
            'low': float(r[3]),
            'close': float(r[4]),
            'volume': float(r[5]),
        })
    # 去重（兩端點接合處可能重複）
    seen = set()
    deduped = []
    for c in candles:
        if c['timestamp'] in seen:
            continue
        seen.add(c['timestamp'])
        deduped.append(c)
    return deduped


_TF_TO_OKX_BAR = {
    '15m': '15m', '30m': '30m', '1h': '1H', '4h': '4H',
    '1d': '1D', '1w': '1W',
}
_TF_DEFAULT_LIMIT = {
    '15m': 96, '30m': 96, '1h': 72, '4h': 90,
    '1d': 60, '1w': 52,
}


def get_historical_prices(symbol='BTC-USDT', timeframe='1h', limit=None):
    """OKX 公開 K 線（無簽名）。
    支援 timeframe: 15m / 30m / 1h / 4h / 1d / 1w；limit 自動依 timeframe 取合理量。
    """
    inst_id = _okx_symbol(symbol) if '/' in symbol else symbol
    bar = _TF_TO_OKX_BAR.get(timeframe, '1H')
    n = limit or _TF_DEFAULT_LIMIT.get(timeframe, 72)
    try:
        data = _okx_get('/api/v5/market/candles', {
            'instId': inst_id, 'bar': bar, 'limit': n,
        })
        if not data:
            raise Exception('No historical data')
        result = []
        now_utc = datetime.utcnow()
        for row in reversed(data):  # OKX 返回按時間倒序
            ts = int(row[0])
            open_ = float(row[1])
            high = float(row[2])
            low = float(row[3])
            close = float(row[4])
            volume = float(row[5]) if len(row) > 5 else 0.0
            dt = datetime.utcfromtimestamp(ts / 1000)
            # 短週期顯示 HH:MM；長週期顯示 MM-DD；非常長 (>=1d) 顯示 YYYY-MM-DD
            if timeframe in ('15m', '30m', '1h'):
                label = dt.strftime('%H:%M') if dt.date() == now_utc.date() else dt.strftime('%m-%d %H:%M')
            elif timeframe == '4h':
                label = dt.strftime('%m-%d %H:%M')
            elif timeframe == '1d':
                label = dt.strftime('%m-%d')
            else:   # 1w
                label = dt.strftime('%Y-%m-%d')
            result.append({
                'timestamp': ts,
                'date': label,
                'price': close,    # 保留兼容舊前端
                'open': open_,
                'high': high,
                'low': low,
                'close': close,
                'volume': volume,
            })
        return result
    except Exception as e:
        raise Exception(f'獲取歷史價格失敗: {str(e)}')


def get_ticker(symbol='BTC-USDT'):
    """獲取即時價格（OKX 公開 API，無需簽名）"""
    inst_id = _okx_symbol(symbol) if '/' in symbol else symbol
    try:
        data = _okx_get('/api/v5/market/ticker', {'instId': inst_id})
        if not data:
            raise Exception('No ticker data')
        t = data[0]
        return {
            'symbol': symbol,
            'price': float(t.get('last', 0)),
            'change_24h': float(t.get('change24h', t.get('change24h', 0))),
            'high_24h': float(t.get('high24h', t.get('high24h', 0))),
            'low_24h': float(t.get('low24h', t.get('low24h', 0))),
            'volume': float(t.get('vol24h', t.get('vol24h', 0))),
        }
    except Exception as e:
        raise Exception(f'獲取價格失敗: {str(e)}')
