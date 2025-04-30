// assets/js/modules/wsService.js

export default class WebSocketService {
  constructor(params, { onOpen, onMessage, onError, onClose, onFallback, onRetryNotice }) {
    this.params        = params;
    this.onOpen        = onOpen;
    this.onMessage     = onMessage;
    this.onError       = onError;
    this.onClose       = onClose;
    this.onFallback    = onFallback;
    this.onRetryNotice = onRetryNotice;

    this.ws               = null;
    this.reconnectAttempts = 0;
    this.maxReconnects     = 5;
    this._shouldReconnect  = false;
    this._pingIntervalId   = null;
  }

  start() {
    this._shouldReconnect  = true;
    this.reconnectAttempts = 0;
    this._connect();
  }

  stop() {
    this._shouldReconnect = false;
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    if (this._pingIntervalId) {
      clearInterval(this._pingIntervalId);
      this._pingIntervalId = null;
    }
  }

  _connect() {
    const { market, provider, symbol, timeframe, since } = this.params;
    const qs = new URLSearchParams({ market, provider, symbols: symbol, timeframe });
    if (since != null) qs.set('since', String(since));

    const url = `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/ws/subscribe?${qs}`;
    console.log('[WS] connecting to', url);

    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      console.log('[WS] open');
      this.reconnectAttempts = 0;
      this.onOpen?.();
      // heartbeat ping every 20s
      this._pingIntervalId = setInterval(() => {
        if (this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ type: 'ping' }));
        }
      }, 20_000);
    };

    this.ws.onmessage = evt => {
      let msg;
      try {
        msg = JSON.parse(evt.data);
      } catch {
        console.warn('[WS] malformed message', evt.data);
        return;
      }

      switch (msg.type) {
        case 'ping':
          // just a pong
          return;

        case 'subscribed':
        case 'unsubscribed':
          // server ack, nothing to do
          return;

        case 'notice':
        case 'retry_notice':
          // backoff / retry notice
          this.onRetryNotice?.(msg.payload?.message || msg.message);
          return;

        case 'error':
          // server-side error envelope
          this.onError?.(
            new Error(
              msg.payload?.message
              || (typeof msg.payload === 'string' ? msg.payload : msg.message)
            )
          );
          return;

        case 'data':
          // un-wrap each bar and fire onMessage(bar)
          const ohlc   = Array.isArray(msg.payload.ohlc)   ? msg.payload.ohlc   : [];
          const volume = Array.isArray(msg.payload.volume) ? msg.payload.volume : [];
          ohlc.forEach((o, i) => {
            const bar = {
              timestamp: o[0],
              open:      o[1],
              high:      o[2],
              low:       o[3],
              close:     o[4],
              volume:    volume[i]?.[1] ?? null
            };
            this.onMessage?.(bar);
          });
          return;

        default:
          console.warn('[WS] Unknown message type', msg);
          return;
      }
    };

    this.ws.onerror = evt => {
      console.error('[WS] error', evt);
      this.onError?.(new Error('WebSocket error'));
    };

    this.ws.onclose = () => {
      console.log('[WS] close');
      clearInterval(this._pingIntervalId);
      this.onClose?.();
      if (!this._shouldReconnect) return;

      if (this.reconnectAttempts < this.maxReconnects) {
        const delay = Math.min(30_000, 1000 * (2 ** this.reconnectAttempts));
        console.log(`[WS] reconnect in ${delay}ms`);
        setTimeout(() => {
          this.reconnectAttempts++;
          this._connect();
        }, delay);
      } else {
        console.warn('[WS] max reconnects reached, falling back to polling');
        this.onFallback?.();
      }
    };
  }
}
