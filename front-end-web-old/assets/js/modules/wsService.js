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
            : 40000; // Backend pings every 25s, client timeout is 40s

        console.log(`[WS Service] Instantiated. Config: clientPingIntervalMs=${this.clientPingIntervalMs}, serverActivityTimeoutMs=${this.serverActivityTimeoutMs}, maxReconnects=${this.maxReconnects}, Params:`, JSON.stringify(params));
    }

    start() {
        console.log('[WS Service] %cstart() called.', 'font-weight: bold; color: green;');
        this._shouldReconnect = true; 
        this.reconnectAttempts = 0;
        this._connect();
    }

    stop() {
        console.log('[WS Service] %cstop() called.', 'font-weight: bold; color: orange;');
        console.log('[WS Service] stop(): Disabling reconnect and closing active connection.');
        this._shouldReconnect = false; 
        this._clearAllKeepAliveTimers(); 
        if (this.ws) {
            if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) {
                console.log('[WS Service] stop(): Closing WebSocket connection (client explicit stop).');
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
        console.debug('[WS Service] Clearing all keep-alive timers (client PING and server activity).');
        clearTimeout(this._serverActivityTimeoutId);
        this._serverActivityTimeoutId = null;
        clearInterval(this._clientPingIntervalId);
        this._clientPingIntervalId = null;
    }

    _connect() {
        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
            console.warn('[WS Service] _connect(): Connection attempt aborted: WebSocket already open or connecting.');
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

        console.log(`[WS Service] %cAttempting to connect (attempt ${this.reconnectAttempts + 1}/${this.maxReconnects}). URL: ${url}`, 'color: blue;');

        try {
            this.ws = new WebSocket(url);
        } catch (error) {
            console.error('[WS Service] %cWebSocket constructor FAILED with exception:', 'color: red; font-weight: bold;', error);
            this.onError?.(new Error(`WebSocket construction failed: ${error.message || 'Unknown error'}`));
            this._handleDisconnect(true); // Pass true for failedDuringConnect
            return;
        }

        this.ws.onopen = (event) => { 
            const isReconnect = this.reconnectAttempts > 0 && event.type === 'open'; // Check event type to be sure it's the actual open event
            console.log(`[WS Service] %cWebSocket connection ${isReconnect ? 'RE-ESTABLISHED' : 'OPENED'} successfully.`, 'color: green; font-weight: bold;');
            
            this.onOpen?.(isReconnect); 
            if(!isReconnect) this.reconnectAttempts = 0; // Reset only if it was an initial successful open, not a re-open
            this._startKeepAliveMonitoring(); 
        };

        this.ws.onmessage = (event) => {
            console.debug('[WS Service] Raw message received from server:', event.data.substring(0, 300));
            this._resetServerActivityTimer(); // CRITICAL: Reset timer on ANY message from server

            let msgEnvelope;
            try {
                msgEnvelope = JSON.parse(event.data);
            } catch (e) {
                console.warn('[WS Service] Received malformed JSON message:', event.data.substring(0, 200) + "...", e);
                this.onError?.(new Error('Received malformed data from server.'));
                return;
            }
            
            if (msgEnvelope.type === 'ping') { 
                console.log(`%c[WS Service] <<< SERVER PING received at ${new Date().toISOString()}. Sending client PONG.`, 'color: blue; font-style: italic;');
                this.sendMessage({ type: 'pong' });
            } else if (msgEnvelope.type === 'pong') { 
                console.log('%c[WS Service] <<< SERVER PONG received (in response to our client PING). Server is responsive.', 'color: blue; font-style: italic;');
            } else {
                console.debug('[WS Service] Forwarding message to controller. Type:', msgEnvelope.type, 'Payload preview:', JSON.stringify(msgEnvelope.payload).substring(0,100) + "...");
                this.onMessage?.(msgEnvelope);
            }
        };

        this.ws.onerror = (event) => {
            console.error('[WS Service] %cWebSocket onerror event fired.', 'color: red;', 'This usually precedes a close event. Event Object:', event);
             // Consider not calling onError here directly, as onclose provides more specific info.
             // If onclose doesn't fire after an error, then this is the only signal.
             // However, most browsers will fire onclose after onerror for fatal errors.
        };

        this.ws.onclose = (event) => {
            const wasThisTheActiveInstance = (this.ws === event.target); // Check if event is for the current ws instance
            this._clearAllKeepAliveTimers(); 
            
            const reason = event.reason || (event.code === 1006 ? "Abnormal closure (no specific reason from server)" : "No reason provided");
            console.warn(`[WS Service] %cWebSocket onclose event. Code: ${event.code}, Reason: "${reason}", Clean: ${event.wasClean}, ForCurrentInstance: ${wasThisTheActiveInstance}`, 'color: orange;');
            
            if (wasThisTheActiveInstance) {
                this.ws = null; // Clear the instance property
                this.onClose?.(event); // Notify controller

                // If closure was not clean and not an explicit client/server stop (1000, 1001)
                if (!event.wasClean && event.code !== 1000 && event.code !== 1001 ) {
                    this.onError?.(new Error(`WebSocket closed unexpectedly (Code: ${event.code}, Reason: ${reason}).`));
                }
                this._handleDisconnect(); 
            } else {
                console.log('[WS Service] onclose event received for a stale/previous WebSocket instance. Ignoring for reconnect logic.');
            }
        };
    }
    
    _startKeepAliveMonitoring() {
        console.debug('[WS Service] %cStarting client-side PING timer and server activity timeout monitoring.', 'color: #666;');
        this._clearAllKeepAliveTimers(); 

        // Client-initiated PING (optional, server also pings)
        this._clientPingIntervalId = setInterval(() => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                console.log(`%c[WS Service] >>> Sending client-initiated PING to server at ${new Date().toISOString()}.`, 'color: purple; font-style: italic;');
                this.sendMessage({ type: 'ping' });
            } else {
                 console.debug('[WS Service] Client PING interval: WebSocket not open or null. Cannot send PING.');
            }
        }, this.clientPingIntervalMs);

        this._resetServerActivityTimer(); // Start the server activity timer
    }

    _resetServerActivityTimer() {
        clearTimeout(this._serverActivityTimeoutId);
        console.debug(`[WS Service] Server activity timer reset. Will fire in ${this.serverActivityTimeoutMs / 1000}s if no server messages.`);
        this._serverActivityTimeoutId = setTimeout(() => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) { 
                console.error(`[WS Service] %c!!!! SERVER ACTIVITY TIMEOUT FIRED after ${this.serverActivityTimeoutMs}ms - No message received from server. Closing WS. !!!!`, 'color: red; font-weight: bold; background-color: yellow;');
                this.ws.close(4001, "Client: Server activity timeout"); // Custom close code
            } else {
                 console.warn(`[WS Service] Server activity timeout would have fired, but WS not open/null. State: ${this.ws ? this.ws.readyState : 'null'}`);
            }
        }, this.serverActivityTimeoutMs);
    }

    _handleDisconnect(failedDuringConnect = false) {
        console.log(`[WS Service] _handleDisconnect called. _shouldReconnect: ${this._shouldReconnect}, ReconnectAttempts: ${this.reconnectAttempts}, FailedDuringInitialConnect: ${failedDuringConnect}`);
        this._clearAllKeepAliveTimers(); 

        if (this._shouldReconnect) {
            if (this.reconnectAttempts < this.maxReconnects) {
                // Use a simple minReconnectDelay if the very first connection attempt failed.
                // Otherwise, use exponential backoff.
                const delay = failedDuringConnect ? this.minReconnectDelay : Math.min(
                    this.maxReconnectDelay,
                    this.minReconnectDelay * Math.pow(this.reconnectFactor, this.reconnectAttempts)
                );
                this.reconnectAttempts++;
                const retryMsg = `Connection lost. Attempting reconnect ${this.reconnectAttempts}/${this.maxReconnects} in ${Math.round(delay/1000)}s...`;
                console.warn(`[WS Service] ${retryMsg}`);
                this.onRetryNotice?.(retryMsg); // Notify UI about retry attempt
                
                setTimeout(() => {
                    if (this._shouldReconnect) { // Check again, stop() might have been called during delay
                         console.log(`[WS Service] %cExecuting scheduled reconnect attempt #${this.reconnectAttempts}.`, 'color: blue; font-weight: bold;');
                         this._connect();
                    } else {
                        console.log("[WS Service] Reconnect attempt aborted as _shouldReconnect became false during delay.")
                    }
                }, delay);
            } else {
                console.error(`[WS Service] %cMaximum reconnect attempts (${this.maxReconnects}) reached. Notifying fallback.`, 'color: red; font-weight: bold;');
                this.onRetryNotice?.(`Failed to connect to live updates after ${this.maxReconnects} attempts. Check connection or try refreshing chart.`);
                this._shouldReconnect = false; // Stop further automatic attempts
                this.onFallback?.(); // Trigger fallback mechanism (e.g., switch to HTTP polling)
            }
        } else {
            console.log('[WS Service] Reconnect not attempted: _shouldReconnect is false (likely due to explicit stop or max retries).');
        }
    }

    sendMessage(messageObject) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            try {
                const messageString = JSON.stringify(messageObject);
                console.debug(`[WS Service] >>> Sending message to server. Type: ${messageObject.type}`); 
                this.ws.send(messageString);
            } catch (error) {
                console.error('[WS Service] Error stringifying/sending message:', error, messageObject);
                this.onError?.(new Error('Failed to send message to server.'));
            }
        } else {
             console.warn(`[WS Service] Cannot send message: WebSocket not open or null. State: ${this.ws ? this.ws.readyState : 'null'}, Message Type: ${messageObject.type}`);
        }
    }
}