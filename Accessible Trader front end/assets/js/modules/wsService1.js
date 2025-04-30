// assets/js/modules/wsService.js

export default class WebSocketService {
  constructor(
    params,
    { onOpen, onMessage, onError, onClose, onFallback, onRetryNotice }
  ) {
    this.params            = params;
    this.onOpen            = onOpen;
    this.onMessage         = onMessage;
    this.onError           = onError;
    this.onClose           = onClose;
    this.onFallback        = onFallback;
    this.onRetryNotice     = onRetryNotice;
    this.ws                = null;
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

    const url = `${
      location.protocol === 'https:' ? 'wss:' : 'ws:'
    }//${location.host}/api/ws/subscribe?${qs}`;
    console.log('[WS] connecting to', url);

    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      console.log('[WS] open');
      this.reconnectAttempts = 0;
      this.onOpen?.();
      // heartbeat ping to server
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
        console.warn('[WS] malformed JSON');
        return;
      }

      switch (msg.type) {
        case 'ping':
          // server heartbeat—ignore
          return;

        case 'subscribed':
          // initial ACK that we’re subscribed—no-op
          console.log('[WS] subscription acknowledged');
          return;

        case 'notice':
          // pause/backoff notice from server
          this.onRetryNotice?.(msg.payload?.message ?? msg.message);
          return;

        case 'data':
          // unpack each bar in payload.ohlc + payload.volume
          const ohlcArr   = Array.isArray(msg.payload?.ohlc)   ? msg.payload.ohlc   : [];
          const volumeArr = Array.isArray(msg.payload?.volume) ? msg.payload.volume : [];
          ohlcArr.forEach((bar, i) => {
            const [ timestamp, open, high, low, close ] = bar;
            const volume = (volumeArr[i] && volumeArr[i][1]) || 0;
            this.onMessage?.({ timestamp, open, high, low, close, volume });
          });
          return;

        default:
          // anything else we didn’t explicitly handle
          console.warn('[WS] Unhandled payload', msg);
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
