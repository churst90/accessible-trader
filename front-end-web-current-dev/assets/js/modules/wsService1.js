// assets/js/modules/wsService.js

export default class WebSocketService {
    constructor(params, { onOpen, onMessage, onError, onClose, onFallback, onRetryNotice }) {
        this.params = params; // { market, provider, symbol, timeframe, since }
        this.onOpen = onOpen;
        this.onMessage = onMessage;
        this.onError = onError;
        this.onClose = onClose;
        this.onFallback = onFallback;
        this.onRetryNotice = onRetryNotice;

        this.ws = null;
        this.reconnectAttempts = 0;
        
        // Configuration with defaults
        this.maxReconnects = window.APP_CONFIG?.MAX_WS_RECONNECTS !== undefined ? parseInt(window.APP_CONFIG.MAX_WS_RECONNECTS, 10) : 5;
        this.minReconnectDelay = window.APP_CONFIG?.MIN_WS_RECONNECT_DELAY_MS !== undefined ? parseInt(window.APP_CONFIG.MIN_WS_RECONNECT_DELAY_MS, 10) : 1000; // Initial reconnect delay
        this.maxReconnectDelay = window.APP_CONFIG?.MAX_WS_RECONNECT_DELAY_MS !== undefined ? parseInt(window.APP_CONFIG.MAX_WS_RECONNECT_DELAY_MS, 10) : 30000;
        this.reconnectFactor = window.APP_CONFIG?.WS_RECONNECT_FACTOR !== undefined ? parseFloat(window.APP_CONFIG.WS_RECONNECT_FACTOR) : 2;
        
        this._shouldReconnect = true; // Start with true, set to false on explicit stop()
        this._clientPingIntervalId = null; 
        this._serverActivityTimeoutId = null; // Timer for detecting server silence

        this.clientPingIntervalMs = window.APP_CONFIG?.CLIENT_PING_INTERVAL_MS !== undefined ? parseInt(window.APP_CONFIG.CLIENT_PING_INTERVAL_MS, 10) : 20000; 
        this.serverActivityTimeoutMs = window.APP_CONFIG?.SERVER_ACTIVITY_TIMEOUT_MS !== undefined 
            ? parseInt(window.APP_CONFIG.SERVER_ACTIVITY_TIMEOUT_MS, 10) 
            : 40000; // Using 40 seconds (backend pings every 25s)

        console.log(`[WS Service] Instantiated. Config: clientPingIntervalMs=${this.clientPingIntervalMs}, serverActivityTimeoutMs=${this.serverActivityTimeoutMs}, maxReconnects=${this.maxReconnects}`);
    }

    start() {
        console.log('[WS Service] start() called.');
        this._shouldReconnect = true; 
        this.reconnectAttempts = 0;
        this._connect();
    }

    stop() {
        console.log('[WS Service] stop() called. Disabling reconnect and closing active connection.');
        this._shouldReconnect = false; 
        this._clearAllKeepAliveTimers(); 
        if (this.ws) {
            if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) {
                console.log('[WS Service] Closing WebSocket connection (client explicit stop).');
                // Remove event listeners before closing to prevent onclose logic from firing for an explicit stop
                this.ws.onopen = null;
                this.ws.onmessage = null;
                this.ws.onerror = null;
                this.ws.onclose = null; 
                this.ws.close(1000, "Client initiated stop"); 
            }
            this.ws = null; 
        }
    }

    _clearAllKeepAliveTimers() {
        // console.debug('[WS Service] Clearing all keep-alive timers (client PING and server activity).');
        clearTimeout(this._serverActivityTimeoutId);
        this._serverActivityTimeoutId = null;
        clearInterval(this._clientPingIntervalId);
        this._clientPingIntervalId = null;
    }

    _connect() {
        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
            console.log('[WS Service] Connection attempt aborted: WebSocket already open or connecting.');
            return;
        }
        this._clearAllKeepAliveTimers(); 

        const { market, provider, symbol, timeframe, since } = this.params;
        const qs = new URLSearchParams({ market, provider, symbols: symbol, timeframe }); // 'symbols' plural as per backend
        if (since != null && since > 0) {
            qs.set('since', String(since));
        }

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host;
        const path = '/api/ws/subscribe'; 
        const url = `${protocol}//${host}${path}?${qs.toString()}`;

        console.log(`[WS Service] Attempting to connect (attempt ${this.reconnectAttempts + 1}/${this.maxReconnects}). URL: ${url}`);

        try {
            this.ws = new WebSocket(url);
        } catch (error) {
            console.error('[WS Service] WebSocket constructor FAILED with exception:', error);
            this.onError?.(new Error(`WebSocket construction failed: ${error.message || 'Unknown error'}`));
            this._handleDisconnect(true); 
            return;
        }

        this.ws.onopen = (event) => { 
            const isReconnect = this.reconnectAttempts > 0; 
            console.log(`[WS Service] WebSocket connection ${isReconnect ? 'RE-ESTABLISHED' : 'OPENED'} successfully.`);
            
            this.onOpen?.(isReconnect); 
            this.reconnectAttempts = 0; 
            this._startKeepAliveMonitoring(); 
        };

        this.ws.onmessage = (event) => {
            this._resetServerActivityTimer(); // CRITICAL: Reset timer on ANY message from server

            let msgEnvelope;
            try {
                msgEnvelope = JSON.parse(event.data);
            } catch (e) {
                console.warn('[WS Service] Received malformed JSON message:', event.data.substring(0, 200) + "...", e);
                this.onError?.(new Error('Received malformed data from server.'));
                return;
            }
            
            // console.debug('[WS Service] Raw message received from server:', event.data.substring(0, 300));


            if (msgEnvelope.type === 'ping') { 
                console.log('[WS Service] <<< SERVER PING received. Sending client PONG.');
                this.sendMessage({ type: 'pong' });
            } else if (msgEnvelope.type === 'pong') { 
                console.log('[WS Service] <<< SERVER PONG received (in response to our client PING). Server is responsive.');
            } else {
                // console.debug('[WS Service] Forwarding message to controller:', msgEnvelope.type);
                this.onMessage?.(msgEnvelope);
            }
        };

        this.ws.onerror = (event) => {
            // This event is often generic. The 'close' event provides more details.
            console.error('[WS Service] WebSocket onerror event fired. This usually precedes a close event. Event:', event);
        };

        this.ws.onclose = (event) => {
            const wasThisTheActiveInstance = (this.ws === event.target);
            this._clearAllKeepAliveTimers(); 
            
            const reason = event.reason || (event.code === 1006 ? "Abnormal closure (no specific reason from server)" : "No reason provided");
            console.warn(`[WS Service] WebSocket onclose event. Code: ${event.code}, Reason: "${reason}", Clean: ${event.wasClean}, ForCurrentInstance: ${wasThisTheActiveInstance}`);
            
            if (wasThisTheActiveInstance) {
                this.ws = null; 
                this.onClose?.(event); 

                if (!event.wasClean && event.code !== 1000 && event.code !== 1001 ) {
                    this.onError?.(new Error(`WebSocket closed unexpectedly (Code: ${event.code}, Reason: ${reason}).`));
                }
                this._handleDisconnect(); 
            } else {
                console.log('[WS Service] onclose event received for a stale/previous WebSocket instance. Ignoring.');
            }
        };
    }
    
    _startKeepAliveMonitoring() {
        console.debug('[WS Service] Starting client-side PING timer and server activity timeout monitoring.');
        this._clearAllKeepAliveTimers(); 

        this._clientPingIntervalId = setInterval(() => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                console.log('[WS Service] >>> Sending client-initiated PING to server.');
                this.sendMessage({ type: 'ping' });
            } else {
                // console.warn('[WS Service] Client PING interval: WebSocket not open. Cannot send PING.');
            }
        }, this.clientPingIntervalMs);

        this._resetServerActivityTimer(); 
    }

    _resetServerActivityTimer() {
        clearTimeout(this._serverActivityTimeoutId);
        // console.debug(`[WS Service] Server activity timer reset for ${this.serverActivityTimeoutMs}ms.`);
        this._serverActivityTimeoutId = setTimeout(() => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) { 
                console.error(`[WS Service] !!!! SERVER ACTIVITY TIMEOUT FIRED after ${this.serverActivityTimeoutMs}ms - No message received from server. Closing WS. !!!!`);
                this.ws.close(4001, "Client: Server activity timeout"); 
            } else {
                 console.warn(`[WS Service] Server activity timeout would have fired, but WS not open/null. State: ${this.ws ? this.ws.readyState : 'null'}`);
            }
        }, this.serverActivityTimeoutMs);
    }

    _handleDisconnect(failedDuringConnect = false) {
        console.log(`[WS Service] _handleDisconnect called. _shouldReconnect: ${this._shouldReconnect}, ReconnectAttempts: ${this.reconnectAttempts}, FailedDuringConnect: ${failedDuringConnect}`);
        this._clearAllKeepAliveTimers(); 

        if (this._shouldReconnect) {
            if (this.reconnectAttempts < this.maxReconnects) {
                const delay = failedDuringConnect ? this.minReconnectDelay : Math.min(
                    this.maxReconnectDelay,
                    this.minReconnectDelay * Math.pow(this.reconnectFactor, this.reconnectAttempts)
                );
                this.reconnectAttempts++;
                const retryMsg = `Connection lost. Attempting reconnect ${this.reconnectAttempts}/${this.maxReconnects} in ${Math.round(delay/1000)}s...`;
                console.log(`[WS Service] ${retryMsg}`);
                this.onRetryNotice?.(retryMsg);
                
                setTimeout(() => {
                    if (this._shouldReconnect) { 
                         console.log(`[WS Service] Executing scheduled reconnect attempt #${this.reconnectAttempts}.`);
                         this._connect();
                    } else {
                        console.log("[WS Service] Reconnect attempt aborted as _shouldReconnect became false during delay.")
                    }
                }, delay);
            } else {
                console.error(`[WS Service] Maximum reconnect attempts (${this.maxReconnects}) reached. Notifying fallback.`);
                this.onRetryNotice?.(`Failed to connect to live updates after ${this.maxReconnects} attempts. Check connection or try refreshing.`);
                this._shouldReconnect = false; 
                this.onFallback?.(); 
            }
        } else {
            console.log('[WS Service] Reconnect not attempted: _shouldReconnect is false.');
        }
    }

    sendMessage(messageObject) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            try {
                const messageString = JSON.stringify(messageObject);
                // console.debug('[WS Service] Sending message to server:', messageObject.type); 
                this.ws.send(messageString);
            } catch (error) {
                console.error('[WS Service] Error sending message:', error, messageObject);
                this.onError?.(new Error('Failed to send message to server.'));
            }
        } else {
             // console.warn('[WS Service] Cannot send message: WebSocket not open. State:', this.ws ? this.ws.readyState : 'null');
        }
    }
}