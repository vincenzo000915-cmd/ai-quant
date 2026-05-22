// Phase 12.18: OKX 公開 WebSocket — 真實時 K 線推送（取代 5s polling）
//
// 端點: wss://ws.okx.com:8443/ws/v5/public
// 訂閱: candle{bar} channel — 每根 K 線價格變動 < 100ms 推送
// 無需 API key，免費
//
// 設計：
// - 单例 connection（避免每个组件自己建）
// - 多 subscriber 共享：同一个 (symbol, tf) 多个组件订阅只開一個 channel
// - 自動重連（5s backoff + max 10 attempts）
// - 心跳每 25s ping（OKX 30s 超时）

const WS_URL = 'wss://ws.okx.com:8443/ws/v5/public';

// timeframe → OKX bar 名映射（跟 backend exchange_service _TF_TO_OKX_BAR 一致）
const TF_TO_BAR = {
  '15m': '15m',
  '30m': '30m',
  '1h':  '1H',
  '4h':  '4H',
  '1d':  '1D',
  '1w':  '1W',
};

// symbol "BTC/USDT" → "BTC-USDT-SWAP" (OKX SWAP inst_id)
function toInstId(symbol) {
  return symbol.replace('/', '-') + '-SWAP';
}

class OkxWsClient {
  constructor() {
    this.ws = null;
    this.subscribers = new Map();   // key="{instId}:{bar}" → Set<callback>
    this.subscribed = new Set();    // 已发送过 subscribe 的 channel keys
    this.reconnectAttempts = 0;
    this.heartbeat = null;
    this.connecting = false;
  }

  _key(instId, bar) {
    return `${instId}:${bar}`;
  }

  connect() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return;
    if (this.connecting) return;
    this.connecting = true;
    try {
      this.ws = new WebSocket(WS_URL);
    } catch (e) {
      this.connecting = false;
      console.error('[OkxWS] connect error:', e);
      this._scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      console.log('[OkxWS] connected');
      this.connecting = false;
      this.reconnectAttempts = 0;
      // 重连后重新 subscribe 所有 channel
      this.subscribed.clear();
      for (const key of this.subscribers.keys()) {
        const [instId, bar] = key.split(':');
        this._sendSubscribe(instId, bar);
      }
      // 心跳
      this.heartbeat = setInterval(() => {
        if (this.ws?.readyState === WebSocket.OPEN) this.ws.send('ping');
      }, 25000);
    };

    this.ws.onmessage = (event) => {
      if (event.data === 'pong') return;
      let msg;
      try { msg = JSON.parse(event.data); } catch { return; }
      // event 响应（subscribe ack / error）
      if (msg.event) {
        if (msg.event === 'error') console.warn('[OkxWS] error:', msg);
        return;
      }
      // 数据推送：msg = {arg:{channel, instId}, data:[[ts, o, h, l, c, vol_base, vol_ccy, vol_ccy_quote, confirm], ...]}
      if (!msg.arg || !msg.data) return;
      const channel = msg.arg.channel;   // 例 candle1H
      const instId = msg.arg.instId;
      if (!channel || !channel.startsWith('candle')) return;
      const bar = channel.slice(6);      // 1H
      const key = this._key(instId, bar);
      const subs = this.subscribers.get(key);
      if (!subs) return;
      // 转 candle 物件
      for (const row of msg.data) {
        const candle = {
          timestamp: parseInt(row[0], 10),
          open: parseFloat(row[1]),
          high: parseFloat(row[2]),
          low: parseFloat(row[3]),
          close: parseFloat(row[4]),
          volume: parseFloat(row[5]),
          confirm: row[8] === '1',   // 是否最终
        };
        for (const cb of subs) {
          try { cb(candle); } catch (e) { console.error('[OkxWS] sub cb error:', e); }
        }
      }
    };

    this.ws.onerror = (e) => {
      console.warn('[OkxWS] error', e);
    };

    this.ws.onclose = () => {
      console.warn('[OkxWS] closed');
      this.connecting = false;
      if (this.heartbeat) { clearInterval(this.heartbeat); this.heartbeat = null; }
      this.subscribed.clear();
      this._scheduleReconnect();
    };
  }

  _scheduleReconnect() {
    if (this.reconnectAttempts >= 10) {
      console.error('[OkxWS] reconnect exhausted (10 attempts), giving up');
      return;
    }
    this.reconnectAttempts++;
    const delay = Math.min(5000 * this.reconnectAttempts, 30000);
    console.log(`[OkxWS] reconnect in ${delay}ms (attempt ${this.reconnectAttempts}/10)`);
    setTimeout(() => this.connect(), delay);
  }

  _sendSubscribe(instId, bar) {
    if (this.ws?.readyState !== WebSocket.OPEN) return;
    const key = this._key(instId, bar);
    if (this.subscribed.has(key)) return;
    this.subscribed.add(key);
    const msg = {
      op: 'subscribe',
      args: [{ channel: `candle${bar}`, instId }],
    };
    this.ws.send(JSON.stringify(msg));
  }

  _sendUnsubscribe(instId, bar) {
    if (this.ws?.readyState !== WebSocket.OPEN) return;
    const key = this._key(instId, bar);
    if (!this.subscribed.has(key)) return;
    this.subscribed.delete(key);
    const msg = {
      op: 'unsubscribe',
      args: [{ channel: `candle${bar}`, instId }],
    };
    this.ws.send(JSON.stringify(msg));
  }

  /**
   * Subscribe to candle updates for (symbol, timeframe).
   * cb is called with { timestamp, open, high, low, close, volume, confirm }
   * Returns unsubscribe function.
   */
  subscribe(symbol, timeframe, cb) {
    const instId = toInstId(symbol);
    const bar = TF_TO_BAR[timeframe] || '1H';
    const key = this._key(instId, bar);
    if (!this.subscribers.has(key)) this.subscribers.set(key, new Set());
    this.subscribers.get(key).add(cb);

    this.connect();
    this._sendSubscribe(instId, bar);

    return () => {
      const subs = this.subscribers.get(key);
      if (subs) {
        subs.delete(cb);
        if (subs.size === 0) {
          this.subscribers.delete(key);
          this._sendUnsubscribe(instId, bar);
        }
      }
    };
  }
}

const okxWs = new OkxWsClient();
export default okxWs;
