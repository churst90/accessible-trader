// assets/js/modules/wsService.js

export default class WebSocketService {
    constructor(params, { onOpen, onMessage, onError, onClose, onFallback, onRetryNotice }) {
        this.params = params; // [cite: 645]
        // { market, provider, symbol, timeframe, since } [cite: 646]
        this.onOpen = onOpen; // [cite: 646]
        this.onMessage = onMessage; // [cite: 647]
        this.onError = onError; // [cite: 647]
        this.onClose = onClose; // [cite: 647]
        this.onFallback = onFallback; // [cite: 647]
        this.onRetryNotice = onRetryNotice; // [cite: 647]

        this.ws = null; // [cite: 647]
        this.reconnectAttempts = 0; // [cite: 648]
        
        // Configuration with defaults
        this.maxReconnects = window.APP_CONFIG?.MAX_WS_RECONNECTS !== undefined ? // [cite: 648]
            parseInt(window.APP_CONFIG.MAX_WS_RECONNECTS, 10) : 5; // [cite: 649]
        this.minReconnectDelay = window.APP_CONFIG?.MIN_WS_RECONNECT_DELAY_MS !== undefined ? parseInt(window.APP_CONFIG.MIN_WS_RECONNECT_DELAY_MS, 10) : 1000; // [cite: 649]
        // Initial reconnect delay [cite: 650]
        this.maxReconnectDelay = window.APP_CONFIG?.MAX_WS_RECONNECT_DELAY_MS !== undefined ? // [cite: 650]
            parseInt(window.APP_CONFIG.MAX_WS_RECONNECT_DELAY_MS, 10) : 30000; // [cite: 651]
        this.reconnectFactor = window.APP_CONFIG?.WS_RECONNECT_FACTOR !== undefined ? parseFloat(window.APP_CONFIG.WS_RECONNECT_FACTOR) : 2; // [cite: 651]
        
        this._shouldReconnect = true; // [cite: 651]
        // Start with true, set to false on explicit stop() [cite: 652]
        this._clientPingIntervalId = null; // [cite: 652]
        this._serverActivityTimeoutId = null; // Timer for detecting server silence [cite: 653]

        this.clientPingIntervalMs = window.APP_CONFIG?.CLIENT_PING_INTERVAL_MS !== undefined ? // [cite: 653]
            parseInt(window.APP_CONFIG.CLIENT_PING_INTERVAL_MS, 10) : 20000;  // [cite: 654]
        this.serverActivityTimeoutMs = window.APP_CONFIG?.SERVER_ACTIVITY_TIMEOUT_MS !== undefined  // [cite: 654]
            ? // [cite: 655]
            parseInt(window.APP_CONFIG.SERVER_ACTIVITY_TIMEOUT_MS, 10)  // [cite: 655]
            : 40000; // [cite: 655]
        // Backend pings every 25s, client timeout is 40s [cite: 656]

        console.log(`[WS Service] Instantiated. Config: clientPingIntervalMs=${this.clientPingIntervalMs}, serverActivityTimeoutMs=${this.serverActivityTimeoutMs}, maxReconnects=${this.maxReconnects}, Params:`, JSON.stringify(params)); // [cite: 656]
    }

    start() {
        console.log('[WS Service] %cstart() called.', 'font-weight: bold; color: green;'); // [cite: 657]
        this._shouldReconnect = true;  // [cite: 658]
        this.reconnectAttempts = 0; // [cite: 658]
        this._connect(); // [cite: 658]
    }

    stop() {
        console.log('[WS Service] %cstop() called.', 'font-weight: bold; color: orange;'); // [cite: 658]
        console.log('[WS Service] stop(): Disabling reconnect and closing active connection.'); // [cite: 659]
        this._shouldReconnect = false;  // [cite: 659]
        this._clearAllKeepAliveTimers(); // [cite: 659]
        if (this.ws) { // [cite: 660]
            if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) { // [cite: 660]
                console.log('[WS Service] stop(): Closing WebSocket connection (client explicit stop).'); // [cite: 660]
                // Remove event listeners before closing to prevent onclose logic from firing for an explicit stop [cite: 661]
                this.ws.onopen = null; // [cite: 661]
                this.ws.onmessage = null; // [cite: 662]
                this.ws.onerror = null; // [cite: 662]
                this.ws.onclose = null;  // [cite: 662]
                this.ws.close(1000, "Client initiated stop"); // [cite: 662]
            }
            this.ws = null; // [cite: 663]
        }
    }

    _clearAllKeepAliveTimers() {
        console.debug('[WS Service] Clearing all keep-alive timers (client PING and server activity).'); // [cite: 664]
        clearTimeout(this._serverActivityTimeoutId); // [cite: 665]
        this._serverActivityTimeoutId = null; // [cite: 665]
        clearInterval(this._clientPingIntervalId); // [cite: 665]
        this._clientPingIntervalId = null; // [cite: 665]
    }

    _connect() {
        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) { // [cite: 665]
            console.warn('[WS Service] _connect(): Connection attempt aborted: WebSocket already open or connecting.'); // [cite: 665]
            return; // [cite: 666]
        }
        this._clearAllKeepAliveTimers();  // [cite: 666]

        const { market, provider, symbol, timeframe, since } = this.params; // [cite: 666]
        const qs = new URLSearchParams({ market, provider, symbols: symbol, timeframe }); // [cite: 667]
        // 'symbols' plural as per backend [cite: 668]
        if (since != null && since > 0) { // [cite: 668]
            qs.set('since', String(since)); // [cite: 669]
        }

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'; // [cite: 669]
        const host = window.location.host; // [cite: 670]
        const path = '/api/ws/subscribe';  // [cite: 670]
        const url = `${protocol}//${host}${path}?${qs.toString()}`; // [cite: 670]
        console.log(`[WS Service] %cAttempting to connect (attempt ${this.reconnectAttempts + 1}/${this.maxReconnects}). URL: ${url}`, 'color: blue;'); // [cite: 671]
        try {
            this.ws = new WebSocket(url); // [cite: 672]
        } catch (error) { // [cite: 673]
            console.error('[WS Service] %cWebSocket constructor FAILED with exception:', 'color: red; font-weight: bold;', error); // [cite: 673]
            this.onError?.(new Error(`WebSocket construction failed: ${error.message || 'Unknown error'}`)); // [cite: 674]
            this._handleDisconnect(true); // Pass true for failedDuringConnect [cite: 674]
            return; // [cite: 674]
        }

        this.ws.onopen = (event) => {  // [cite: 675]
            const isReconnect = this.reconnectAttempts > 0 && event.type === 'open'; // [cite: 675]
            // Check event type to be sure it's the actual open event [cite: 676]
            console.log(`[WS Service] %cWebSocket connection ${isReconnect ? 'RE-ESTABLISHED' : 'OPENED'} successfully.`, 'color: green; font-weight: bold;'); // [cite: 676]
            this.onOpen?.(isReconnect);  // [cite: 677]
            if(!isReconnect) this.reconnectAttempts = 0; // Reset only if it was an initial successful open, not a re-open [cite: 677]
            this._startKeepAliveMonitoring(); // [cite: 677]
        };

        this.ws.onmessage = (event) => { // [cite: 678]
            console.debug('[WS Service] Raw message received from server:', event.data.substring(0, 300)); // [cite: 678]
            this._resetServerActivityTimer(); // CRITICAL: Reset timer on ANY message from server [cite: 679]

            let msgEnvelope; // [cite: 679]
            try {
                msgEnvelope = JSON.parse(event.data); // [cite: 680]
            } catch (e) { // [cite: 681]
                console.warn('[WS Service] Received malformed JSON message:', event.data.substring(0, 200) + "...", e); // [cite: 681]
                this.onError?.(new Error('Received malformed data from server.')); // [cite: 682]
                return; // [cite: 682]
            }
            
            // ***** MODIFIED SECTION FOR PONG *****
            if (msgEnvelope.type === 'ping') {  // [cite: 682]
                console.log(`%c[WS Service] <<< SERVER PING received at ${new Date().toISOString()}. Sending client PONG.`, 'color: blue; font-style: italic;'); // [cite: 682]
                this.sendMessage({ action: 'pong' }); // Changed from 'type' to 'action' [cite: 683]
            } else if (msgEnvelope.type === 'pong') {  // [cite: 683]
            // ***** END OF MODIFICATION FOR PONG *****
                console.log('%c[WS Service] <<< SERVER PONG received (in response to our client PING). Server is responsive.', 'color: blue; font-style: italic;'); // [cite: 683]
            } else { // [cite: 684]
                console.debug('[WS Service] Forwarding message to controller. Type:', msgEnvelope.type, 'Payload preview:', JSON.stringify(msgEnvelope.payload).substring(0,100) + "..."); // [cite: 684]
                this.onMessage?.(msgEnvelope); // [cite: 685]
            }
        };
        this.ws.onerror = (event) => { // [cite: 686]
            console.error('[WS Service] %cWebSocket onerror event fired.', 'color: red;', 'This usually precedes a close event. Event Object:', event); // [cite: 686]
            // Consider not calling onError here directly, as onclose provides more specific info. [cite: 687]
            // If onclose doesn't fire after an error, then this is the only signal. [cite: 688]
            // However, most browsers will fire onclose after onerror for fatal errors. [cite: 689]
        };
        this.ws.onclose = (event) => { // [cite: 690]
            const wasThisTheActiveInstance = (this.ws === event.target); // [cite: 690]
            // Check if event is for the current ws instance [cite: 691]
            this._clearAllKeepAliveTimers(); // [cite: 691]
            const reason = event.reason || (event.code === 1006 ? "Abnormal closure (no specific reason from server)" : "No reason provided"); // [cite: 692]
            console.warn(`[WS Service] %cWebSocket onclose event. Code: ${event.code}, Reason: "${reason}", Clean: ${event.wasClean}, ForCurrentInstance: ${wasThisTheActiveInstance}`, 'color: orange;'); // [cite: 693]
            if (wasThisTheActiveInstance) { // [cite: 694]
                this.ws = null; // [cite: 694]
                // Clear the instance property [cite: 695]
                this.onClose?.(event); // [cite: 695]
                // Notify controller [cite: 696]

                // If closure was not clean and not an explicit client/server stop (1000, 1001)
                if (!event.wasClean && event.code !== 1000 && event.code !== 1001 ) { // [cite: 696]
                    this.onError?.(new Error(`WebSocket closed unexpectedly (Code: ${event.code}, Reason: ${reason}).`)); // [cite: 696]
                }
                this._handleDisconnect(); // [cite: 697]
            } else { // [cite: 698]
                console.log('[WS Service] onclose event received for a stale/previous WebSocket instance. Ignoring for reconnect logic.'); // [cite: 698]
            }
        };
    }
    
    _startKeepAliveMonitoring() {
        console.debug('[WS Service] %cStarting client-side PING timer and server activity timeout monitoring.', 'color: #666;'); // [cite: 699]
        this._clearAllKeepAliveTimers();  // [cite: 700]

        // Client-initiated PING (optional, server also pings)
        this._clientPingIntervalId = setInterval(() => { // [cite: 700]
            if (this.ws && this.ws.readyState === WebSocket.OPEN) { // [cite: 700]
                console.log(`%c[WS Service] >>> Sending client-initiated PING to server at ${new Date().toISOString()}.`, 'color: purple; font-style: italic;'); // [cite: 700]
                // ***** MODIFIED SECTION FOR PING *****
                this.sendMessage({ action: 'ping' }); // Changed from 'type' to 'action'
                // ***** END OF MODIFICATION FOR PING *****
            } else  // [cite: 701]
            {
                 console.debug('[WS Service] Client PING interval: WebSocket not open or null. Cannot send PING.'); // [cite: 701]
            }
        }, this.clientPingIntervalMs); // [cite: 701]
        this._resetServerActivityTimer(); // Start the server activity timer [cite: 702]
    }

    _resetServerActivityTimer() {
        clearTimeout(this._serverActivityTimeoutId); // [cite: 702]
        console.debug(`[WS Service] Server activity timer reset. Will fire in ${this.serverActivityTimeoutMs / 1000}s if no server messages.`); // [cite: 703]
        this._serverActivityTimeoutId = setTimeout(() => { // [cite: 704]
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {  // [cite: 704]
                console.error(`[WS Service] %c!!!! SERVER ACTIVITY TIMEOUT FIRED after ${this.serverActivityTimeoutMs}ms - No message received from server. Closing WS. !!!!`, 'color: red; font-weight: bold; background-color: yellow;'); // [cite: 704]
                this.ws.close(4001, "Client: Server activity timeout"); // Custom close code [cite: 704]
            } else  // [cite: 705]
            {
                 console.warn(`[WS Service] Server activity timeout would have fired, but WS not open/null. State: ${this.ws ? this.ws.readyState : 'null'}`); // [cite: 705]
            }
        }, this.serverActivityTimeoutMs); // [cite: 705]
    }

    _handleDisconnect(failedDuringConnect = false) {
        console.log(`[WS Service] _handleDisconnect called. _shouldReconnect: ${this._shouldReconnect}, ReconnectAttempts: ${this.reconnectAttempts}, FailedDuringInitialConnect: ${failedDuringConnect}`); // [cite: 706]
        this._clearAllKeepAliveTimers();  // [cite: 707]

        if (this._shouldReconnect) { // [cite: 707]
            if (this.reconnectAttempts < this.maxReconnects) { // [cite: 707]
                // Use a simple minReconnectDelay if the very first connection attempt failed. [cite: 707]
                // Otherwise, use exponential backoff. [cite: 708]
                const delay = failedDuringConnect ? // [cite: 708]
                    this.minReconnectDelay : Math.min( // [cite: 709]
                    this.maxReconnectDelay, // [cite: 709]
                    this.minReconnectDelay * Math.pow(this.reconnectFactor, this.reconnectAttempts) // [cite: 709]
                );
                this.reconnectAttempts++; // [cite: 710]
                const retryMsg = `Connection lost. Attempting reconnect ${this.reconnectAttempts}/${this.maxReconnects} in ${Math.round(delay/1000)}s...`; // [cite: 710]
                console.warn(`[WS Service] ${retryMsg}`); // [cite: 710]
                this.onRetryNotice?.(retryMsg); // [cite: 710]
                // Notify UI about retry attempt [cite: 711]
                
                setTimeout(() => { // [cite: 711]
                    if (this._shouldReconnect) { // Check again, stop() might have been called during delay [cite: 711]
                         console.log(`[WS Service] %cExecuting scheduled 
 reconnect attempt #${this.reconnectAttempts}.`, 'color: blue; font-weight: bold;'); // [cite: 712]
                         this._connect(); // [cite: 712]
                    } else { // [cite: 712]
                        console.log("[WS Service] Reconnect attempt aborted as _shouldReconnect became false during delay.") // [cite: 712]
                    }
                }, delay); // [cite: 713]
            } else { // [cite: 714]
                console.error(`[WS Service] %cMaximum reconnect attempts (${this.maxReconnects}) reached. Notifying fallback.`, 'color: red; font-weight: bold;'); // [cite: 714]
                this.onRetryNotice?.(`Failed to connect to live updates after ${this.maxReconnects} attempts. Check connection or try refreshing chart.`); // [cite: 715]
                this._shouldReconnect = false; // [cite: 715]
                // Stop further automatic attempts [cite: 716]
                this.onFallback?.(); // [cite: 716]
                // Trigger fallback mechanism (e.g., switch to HTTP polling) [cite: 717]
            }
        } else { // [cite: 717]
            console.log('[WS Service] Reconnect not attempted: _shouldReconnect is false (likely due to explicit stop or max retries).'); // [cite: 717]
        }
    }

    sendMessage(messageObject) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) { // [cite: 718]
            try {
                const messageString = JSON.stringify(messageObject); // [cite: 718]
                console.debug(`[WS Service] >>> Sending message to server. Type: ${messageObject.action || messageObject.type}`); // MODIFIED to log action or type
                this.ws.send(messageString); // [cite: 719]
            } catch (error) { // [cite: 720]
                console.error('[WS Service] Error stringifying/sending message:', error, messageObject); // [cite: 720]
                this.onError?.(new Error('Failed to send message to server.')); // [cite: 721]
            }
        } else { // [cite: 721]
             console.warn(`[WS Service] Cannot send message: WebSocket not open or null. State: ${this.ws ? this.ws.readyState : 'null'}, Message Type: ${messageObject.action || messageObject.type}`); // MODIFIED
        }
    }
}