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


def cancel_order(order_id, symbol):
    """取消訂單"""
    exchange = get_exchange()
    return exchange.cancel_order(order_id, symbol)


def get_historical_prices(symbol='BTC-USDT', days=30):
    """獲取近期價格數據（OKX 公開 API，1小時K線，近48小時）"""
    inst_id = _okx_symbol(symbol) if '/' in symbol else symbol
    try:
        data = _okx_get('/api/v5/market/candles', {
            'instId': inst_id,
            'bar': '1H',
            'limit': 48,
        })
        if not data:
            raise Exception('No historical data')
        result = []
        now_utc = datetime.utcnow()
        for row in reversed(data):  # OKX 返回按時間倒序
            ts = int(row[0])
            close = float(row[4])
            dt = datetime.utcfromtimestamp(ts / 1000)
            # 格式：如果是今天只顯示時間，否則顯示月-日 時:分
            label = dt.strftime('%H:%M') if dt.date() == now_utc.date() else dt.strftime('%m-%d %H:%M')
            result.append({
                'timestamp': ts,
                'date': label,
                'price': close,
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
