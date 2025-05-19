// assets/js/modules/chartController.js

import DataManager from './dataManager.js';
import ChartRenderer from './chartRenderer.js';
import WebSocketService from './wsService.js';
import { fetchOhlcv } from './dataService.js'; // Used by dataManager.loadMoreHistory and potentially polling
import { setChart } from './chartStore.js';

export default class ChartController {
    constructor(container, announceEl, params, { logFn = console.log } = {}) {
        this.container = container;
        this.announceEl = announceEl;
        this.params = params; // { market, provider, symbol, timeframe }
        this.log = (...args) => logFn('[ChartCtrl]', ...args);
        this.errorLog = (...args) => console.error('[ChartCtrl]', ...args);

        this.dataManager = new DataManager(params, { logFn });
        this.renderer = new ChartRenderer(container, {
            onPan: this.handlePan.bind(this),
            onAnnounce: this._announce.bind(this), // Pass announce helper
            controller: this
        });

        this.chart = null;
        this.wsService = null;
        this.pollerId = null;
        this.isLoadingHist = false;
        this.isLiveView = true; // Assume live view initially
        this.minPointsForZoom = 10; // Min points required to attempt initial zoom setting
        this.initialDataRendered = false;

        // For managing the init() promise and its timeout
        this.initPromise = null;
        this.resolveCurrentInitPromise = null;
        this.rejectCurrentInitPromise = null;
        this.activeInitTimeoutId = null;
        this.log(`ChartController instantiated for ${params.symbol || 'N/A'} on ${params.provider}`);
    }

    _getLocalStorageKey() {
        return `latestTs_${this.params.market}_${this.params.provider}_${this.params.symbol}_${this.params.timeframe}`;
    }

    _saveLatestTsToLocalStorage() {
        if (this.dataManager.latestTs !== null && this.dataManager.latestTs > 0) {
            const storageKey = this._getLocalStorageKey();
            try {
                localStorage.setItem(storageKey, String(this.dataManager.latestTs));
                this.log(`Saved latestTs ${this.dataManager.latestTs} (${new Date(this.dataManager.latestTs).toISOString()}) to localStorage for ${storageKey}`);
            } catch (e) {
                this.errorLog("Error writing latestTs to localStorage", e);
            }
        } else {
            this.log(`Skipped saving latestTs to localStorage; DataManager.latestTs is null or invalid: ${this.dataManager.latestTs}`);
        }
    }

    _loadLatestTsFromLocalStorage() {
        const storageKey = this._getLocalStorageKey();
        try {
            const storedVal = localStorage.getItem(storageKey);
            if (storedVal) {
                const parsedVal = parseInt(storedVal, 10);
                if (!isNaN(parsedVal) && parsedVal > 0) {
                    this.log(`Loaded latestTs ${parsedVal} (${new Date(parsedVal).toISOString()}) from localStorage for ${storageKey}`);
                    return parsedVal;
                }
            }
        } catch (e) {
            this.errorLog("Error reading latestTs from localStorage", e);
        }
        this.log(`No valid latestTs found in localStorage for ${storageKey}. Requesting fresh history (clientSince=0).`);
        return 0; // Default to 0 for a fresh load (request all available recent history)
    }

    _announce(msg, isError = false) {
        if (isError) {
            this.errorLog(msg);
        } else {
            this.log(msg);
        }
        const el = isError ? (document.getElementById('chartErrorStatus') || this.announceEl) : this.announceEl;
        if (el) {
            el.textContent = ''; // Clear previous for screen reader accessibility
            setTimeout(() => { if (el) el.textContent = msg; }, 50);
        }
    }

    _error(msg) {
        this._announce(msg, true);
    }

    _settleInitPromise(isSuccess, valueOrError) {
        this._clearActiveInitTimeout();
        if (isSuccess) {
            if (this.resolveCurrentInitPromise) {
                this.log("[ChartCtrl] Resolving current init promise.");
                this.resolveCurrentInitPromise(valueOrError);
            } else {
                this.log("[ChartCtrl] Init promise already settled or no resolver, resolve action ignored.");
            }
        } else {
            if (this.rejectCurrentInitPromise) {
                this.errorLog("[ChartCtrl] Rejecting current init promise with error:", valueOrError?.message || valueOrError);
                this.rejectCurrentInitPromise(valueOrError);
            } else {
                this.errorLog("[ChartCtrl] Init promise already settled or no rejector, reject action ignored. Error was:", valueOrError?.message || valueOrError);
            }
        }
        this.resolveCurrentInitPromise = null;
        this.rejectCurrentInitPromise = null;
    }

    _clearActiveInitTimeout() {
        if (this.activeInitTimeoutId) {
            clearTimeout(this.activeInitTimeoutId);
            this.activeInitTimeoutId = null;
            this.log("[ChartCtrl] Cleared active init timeout.");
        }
    }

    async init() {
        this.log(`>>> ChartController init() started for: ${this.params.symbol}, TF: ${this.params.timeframe}`);

        if (this.initPromise) {
            this.log("[ChartCtrl] An init operation may already be in progress. Clearing previous and proceeding with new init.");
            this._clearActiveInitTimeout(); // Clear timeout of any previous init
            // Attempt to reject any pending promise from a previous init call if it's still hanging around
            if (this.rejectCurrentInitPromise) {
                this.rejectCurrentInitPromise(new Error("New chart initialization started."));
                this.rejectCurrentInitPromise = null;
                this.resolveCurrentInitPromise = null;
            }
        }

        this.isLoadingHist = false;
        this.isLiveView = true;
        this.initialDataRendered = false;

        this.wsService?.stop();
        clearInterval(this.pollerId);
        this.pollerId = null;

        if (this.chart) {
            try {
                this.chart.destroy();
                this.log("Previous chart instance destroyed.");
            } catch (e) {
                this.errorLog("Error destroying previous chart:", e);
            }
            this.chart = null;
            setChart(null);
        }
        this.dataManager.clear();

        this._announce('Connecting & fetching initial data...');
        const clientSince = this._loadLatestTsFromLocalStorage();

        this.initPromise = new Promise((resolve, reject) => {
            this.resolveCurrentInitPromise = resolve;
            this.rejectCurrentInitPromise = reject;

            this.log(`[ChartCtrl] Starting new live connection for init. clientSince: ${clientSince > 0 ? new Date(clientSince).toISOString() : '0 (Fresh)'}`);
            this.startLive(clientSince); // This will now send the subscribe message

            const INITIAL_DATA_TIMEOUT_MS = 30000; // 30 seconds timeout for initial data
            this.log(`[ChartCtrl] Setting init timeout for ${INITIAL_DATA_TIMEOUT_MS / 1000}s.`);
            this.activeInitTimeoutId = setTimeout(() => {
                if (this.rejectCurrentInitPromise && !this.initialDataRendered) {
                    const errMsg = `Timeout (${INITIAL_DATA_TIMEOUT_MS / 1000}s): Initial chart data not rendered.`;
                    this.errorLog(`[ChartCtrl] !!!! INIT TIMEOUT FIRED for ${this.params.symbol} !!!! initialDataRendered: ${this.initialDataRendered}`);
                    this._error(errMsg); // Announce error to user
                    this._settleInitPromise(false, new Error(errMsg));
                } else if (this.initialDataRendered && this.resolveCurrentInitPromise) {
                    // This case should ideally not be hit if _settleInitPromise was called correctly upon render.
                    this.log(`[ChartCtrl] Init timeout fired, but initialDataRendered is true. Promise should ideally be settled. Forcing resolution.`);
                    this._settleInitPromise(true, this.chart);
                } else {
                     this.log(`[ChartCtrl] Init timeout callback: No action needed (promise already settled or no rejector).`);
                }
            }, INITIAL_DATA_TIMEOUT_MS);
        });

        try {
            const chartInstance = await this.initPromise;
            this.log(`<<< ChartController init() SUCCESSFULLY COMPLETED for ${this.params.symbol}. Chart instance: ${chartInstance ? 'OK' : 'NULL'}`);
            return chartInstance;
        } catch (error) {
            this.errorLog(`<<< ChartController init() FAILED for ${this.params.symbol}: ${error?.message || error}`);
            // Ensure UI reflects failure if not already handled by timeout's _error
            if (!this.initialDataRendered) { // Check this flag, as timeout might have already announced
                this._error(`Failed to load chart: ${error?.message || 'Unknown error'}`);
            }
            return null;
        } finally {
            this.initPromise = null; // Clear the promise regardless of outcome
        }
    }

    _applyInitialZoom() {
        if (!this.chart || !this.initialDataRendered) {
            this.log("Skipping initial zoom: chart not ready or initial data not fully processed.");
            return;
        }
        const ohlc = this.dataManager.fullOhlc;
        const total = ohlc.length;
        this.log(`Applying initial zoom. Total bars in DataManager: ${total}`);

        if (total === 0) {
            this._announce("Chart loaded with no data points. Default zoom.");
            // Highcharts default zoom will apply if no data or extremes set. Redraw if necessary.
            if (this.chart.series && this.chart.series.length > 0) this.chart.redraw();
            return;
        }

        if (total >= this.minPointsForZoom) {
            let take = Math.max(Math.floor(total * 0.25), this.minPointsForZoom); // Show last 25% or minPointsForZoom
            take = Math.min(take, total); // Cannot take more than available
            const minTsIndex = Math.max(0, total - take);

            const minTs = ohlc[minTsIndex]?.[0];
            const maxTs = ohlc[total - 1]?.[0];

            if (typeof minTs === 'number' && typeof maxTs === 'number' && minTs <= maxTs) {
                if (minTs === maxTs && total > 1) { // Multiple points at the same timestamp
                    this.log("Initial zoom: Multiple points at same timestamp, Highcharts default zoom.");
                    if (this.chart.series && this.chart.series.length > 0) this.chart.redraw();
                } else if (minTs === maxTs && total === 1) { // Single data point
                    const pointTime = minTs;
                    const barDuration = this.dataManager.msPerBar || 60000; // Default to 1 min if not set
                    const windowMin = pointTime - (barDuration * 5); // Show some context around the single bar
                    const windowMax = pointTime + (barDuration * 5);
                    this.chart.xAxis[0].setExtremes(windowMin, windowMax, true, false);
                    this._announce(`Showing single data point.`);
                } else { // Regular case with enough points and a valid range
                    this.chart.xAxis[0].setExtremes(minTs, maxTs, true, false);
                    this._announce(`Chart zoomed to show most recent ${take} bars.`);
                }
            } else {
                this.log("Could not set initial zoom extremes (invalid timestamps/range). Defaulting.");
                if (this.chart.series && this.chart.series.length > 0) this.chart.redraw();
            }
        } else { // Less than minPointsForZoom but more than 0
            this._announce(`Showing all ${total} available bars.`);
            // Let Highcharts decide the zoom for few points, or set extremes to null,null for full view.
            this.chart.xAxis[0].setExtremes(null, null, true, false);
        }
    }

    handleWebSocketMessage(msgEnvelope) {
        const { type, symbol, timeframe, payload } = msgEnvelope;
        // Added more detailed logging for payload
        this.log(`[ChartCtrl] Handling WS Message: Type=${type}, Symbol=${symbol || 'N/A'}, ForChart=${this.params.symbol}, PayloadKeys=${payload ? Object.keys(payload).join(',') : 'N/A'}. InitialRendered: ${this.initialDataRendered}`);


        if (symbol && symbol !== this.params.symbol) {
            this.log(`[ChartCtrl] Ignoring message for different symbol: ${symbol}`);
            return;
        }
        // Ensure timeframe also matches if present in message (good practice)
        if (timeframe && timeframe !== this.params.timeframe) {
            this.log(`[ChartCtrl] Ignoring message for different timeframe: ${timeframe}`);
            return;
        }

        if (type === 'error') {
            const errorMsg = payload?.message || 'Unknown error from server.';
            this._error(`Server Error for ${this.params.symbol}: ${errorMsg}`);
            if (this.rejectCurrentInitPromise && !this.initialDataRendered) {
                this._settleInitPromise(false, new Error(`Server error: ${errorMsg}`));
            }
            return;
        }
        if (type === 'subscribed') {
            this._announce(`Subscription to ${payload?.symbol || this.params.symbol} ${payload?.timeframe || this.params.timeframe} confirmed. Awaiting initial data...`);
            return;
        }
        if (type === 'notice' || type === 'retry_notice') {
            this._announce(payload?.message || 'Notice from server.');
            return;
        }

        if (type === 'data') {
            const ohlcData = payload?.ohlc || [];
            const volumeData = payload?.volume || [];

            if (payload?.initial_batch) {
                this.log(`[ChartCtrl] Processing initial_batch for ${this.params.symbol}: ${ohlcData.length} bars. Status: "${payload.status_message || ''}"`);

                this.dataManager.clear();
                if (ohlcData.length > 0) {
                    ohlcData.forEach((barArray, i) => {
                        const vol = volumeData[i]?.[1] ?? 0;
                        const fullBarData = [...barArray, vol];
                        try {
                             // For initial batch, allowUpdate should be false as these are distinct historical bars
                            this.dataManager.addBar(fullBarData, false);
                        } catch (e) {
                            this.log(`[ChartCtrl] initial_batch: Skipping bar (addBar error: ${e.message}) TS: ${barArray[0]}`);
                        }
                    });
                }

                const chartTitle = `${this.params.symbol} ${this.params.timeframe} @ ${this.params.provider}`;
                let renderSuccess = false;
                if (!this.chart) {
                    this.log("[ChartCtrl] Rendering NEW chart with initial_batch data.");
                    this.chart = this.renderer.render({ ohlc: this.dataManager.fullOhlc, volume: this.dataManager.fullVol, title: chartTitle });
                    if (this.chart) {
                        setChart(this.chart);
                        this.initialDataRendered = true; // CRITICAL: Set before applyInitialZoom and settling promise
                        this._applyInitialZoom();
                        renderSuccess = true;
                    } else {
                        this._error("[ChartCtrl] CRITICAL: ChartRenderer.render returned null for initial_batch.");
                    }
                } else { // Chart exists, likely a reconnect scenario if we get initial_batch again
                    this.log("[ChartCtrl] Updating EXISTING chart with initial_batch data (e.g., after reconnect).");
                    this.chart.get('ohlc')?.setData(this.dataManager.fullOhlc, false);
                    this.chart.get('price-line')?.setData(this.dataManager.fullOhlc.map(b => [b[0], b[4]]), false);
                    this.chart.get('vol')?.setData(this.dataManager.fullVol, true); // Redraw after volume
                    this.initialDataRendered = true; // Ensure it's true
                    this._applyInitialZoom();
                    renderSuccess = true;
                }

                if (renderSuccess) {
                    const message = ohlcData.length > 0 ? `Chart loaded with ${ohlcData.length} initial bars.` : (payload.status_message || 'Chart loaded. No initial bars. Awaiting live updates.');
                    this._announce(message);
                    if (this.dataManager.latestTs) {
                        this._saveLatestTsToLocalStorage();
                    }
                    this._settleInitPromise(true, this.chart); // Resolve the init promise
                } else {
                    this._settleInitPromise(false, new Error("Chart rendering failed for initial_batch."));
                }

            } else if (payload?.catch_up_batch) {
                this.log(`[ChartCtrl] Processing catch_up_batch for ${this.params.symbol}: ${ohlcData.length} bars.`);
                if (!this.initialDataRendered && !this.chart) {
                    this.log("[ChartCtrl] Warning: Received catch_up_batch before initial chart fully rendered. Data will be added to DataManager.");
                }
                let newBarsAddedToDataManager = 0;
                if (ohlcData.length > 0) {
                    ohlcData.forEach((barArray, i) => {
                        const vol = volumeData[i]?.[1] ?? 0;
                        const fullBarData = [...barArray, vol];
                        try {
                            const addedOrUpdated = this.dataManager.addBar(fullBarData, true); // Allow update for catch-up
                            if (addedOrUpdated) newBarsAddedToDataManager++;
                        } catch (e) { this.log(`[ChartCtrl] catch_up_batch: Skipping bar (addBar error: ${e.message}) TS: ${barArray[0]}`) }
                    });
                }

                if (newBarsAddedToDataManager > 0) {
                    if (this.chart && this.initialDataRendered) {
                        this.log(`[ChartCtrl] catch_up_batch: Refreshing chart data after ${newBarsAddedToDataManager} bars added/updated.`);
                        this.chart.get('ohlc')?.setData(this.dataManager.fullOhlc, false);
                        this.chart.get('price-line')?.setData(this.dataManager.fullOhlc.map(b => [b[0], b[4]]), false);
                        this.chart.get('vol')?.setData(this.dataManager.fullVol, this.isLiveView); // Redraw if live
                    }
                    if (this.dataManager.latestTs) this._saveLatestTsToLocalStorage();
                    this._announce(`Chart updated with ${newBarsAddedToDataManager} catch-up bars.`);
                } else {
                    this._announce('No new bars in catch-up batch.');
                }

            } else { // Regular live update (single bar usually, or small batch not marked as initial/catchup)
                this.log(`[ChartCtrl] Received LIVE DATA message for ${this.params.symbol}. Payload Preview: ${JSON.stringify(payload).substring(0, 100)}`);
                if (ohlcData.length > 0) {
                    // Process each bar in the ohlcData array if it's a batch of live updates
                    ohlcData.forEach((ohlcBarArray, index) => {
                        const volumeVal = volumeData[index]?.[1] ?? 0; // Get corresponding volume
                        const liveBarObject = {
                            timestamp: ohlcBarArray[0], open: ohlcBarArray[1], high: ohlcBarArray[2],
                            low: ohlcBarArray[3], close: ohlcBarArray[4], volume: volumeVal
                        };
                        this.log(`[ChartCtrl] Calling handleLiveBar for TS: ${liveBarObject.timestamp}`);
                        this.handleLiveBar(liveBarObject);
                    });
                } else {
                    this.log("[ChartCtrl] Live data message had empty ohlcData.");
                }
            }
        } else {
            this.log(`[ChartCtrl] Unhandled WebSocket message type: ${type}`);
        }
    }

    handleLiveBar(barData) { // barData is an object {timestamp, open, high, low, close, volume}
        this.log(`[ChartCtrl] handleLiveBar for TS: ${barData.timestamp}, initialDataRendered: ${this.initialDataRendered}`);
        if (!this.initialDataRendered) {
            this.log("[ChartCtrl] handleLiveBar: initialDataRendered is false. Ignoring live bar during initial load phase.");
            return;
        }
        if (!this.chart) {
            this.log("[ChartCtrl] handleLiveBar: Chart object is null. Ignoring live bar.");
            return;
        }
        try {
            const barArrayForDM = [
                +barData.timestamp, +barData.open, +barData.high,
                +barData.low, +barData.close, +barData.volume || 0
            ];

            const updateType = this.dataManager.addBar(barArrayForDM, true); // true to allow update of current candle

            const ts = +barData.timestamp;
            const ohlcPoint = [ts, +barData.open, +barData.high, +barData.low, +barData.close];
            const closePoint = [ts, +barData.close]; // For price line series
            const volPoint = [ts, +barData.volume || 0];

            const ohlcSeries = this.chart.get('ohlc');
            const priceLineSeries = this.chart.get('price-line');
            const volSeries = this.chart.get('vol');
            let needsRedraw = false;

            if (updateType === 'updated') {
                this.log(`[ChartCtrl] LiveBar: Updating existing last point for TS ${ts}`);
                if (ohlcSeries?.data.length > 0) {
                    const lastPt = ohlcSeries.data[ohlcSeries.data.length - 1];
                    if (lastPt.x === ts) lastPt.update(ohlcPoint, false); else ohlcSeries.addPoint(ohlcPoint, false, false, false); // Fallback if somehow not last
                }
                if (priceLineSeries?.data.length > 0) {
                    const lastPt = priceLineSeries.data[priceLineSeries.data.length - 1];
                    if (lastPt.x === ts) lastPt.update(closePoint, false); else priceLineSeries.addPoint(closePoint, false, false, false);
                }
                if (volSeries?.data.length > 0) {
                    const lastPt = volSeries.data[volSeries.data.length - 1];
                    if (lastPt.x === ts) lastPt.update(volPoint, false); else volSeries.addPoint(volPoint, false, false, false);
                }
                needsRedraw = true;
            } else if (updateType === 'added') {
                this.log(`[ChartCtrl] LiveBar: Adding new point for TS ${ts}`);
                const shift = (ohlcSeries?.data?.length || 0) > 2000; // Example: Shift if more than 2000 points
                ohlcSeries?.addPoint(ohlcPoint, false, shift, false);
                priceLineSeries?.addPoint(closePoint, false, shift, false);
                volSeries?.addPoint(volPoint, false, shift, false);
                needsRedraw = true;
            } else { // Bar was not processed by DataManager (e.g., older, or duplicate not for update)
                this.log(`[ChartCtrl] Live bar TS: ${barData.timestamp} was not processed by DataManager (updateType: ${updateType}). No chart update.`);
                return;
            }

            if (this.isLiveView && needsRedraw) {
                this.chart.redraw();
                // this.log(`[ChartCtrl] Redrew chart after live bar TS: ${ts}`);
            }
            this._saveLatestTsToLocalStorage(); // Save latest TS after processing a new/updated bar
        } catch (err) {
            // More specific check for "timestamp is not newer" can be tricky if DataManager's error message changes.
            // Relying on addBar's return value is safer if it returns null for "no action".
            this.errorLog(`[ChartCtrl] handleLiveBar error: ${err.message}`, err);
        }
    }

    startLive(clientSince = 0) {
        this.log(`[ChartCtrl] startLive called. clientSince: ${clientSince === 0 ? 'Fresh (0)' : new Date(clientSince).toISOString()}`);
        this.wsService?.stop();
        clearInterval(this.pollerId);
        this.pollerId = null;

        const wsParams = { ...this.params, since: clientSince }; // 'since' here is for the WS connection parameters if needed by backend on connect string

        try {
            this.wsService = new WebSocketService(wsParams, {
                onOpen: (isReconnectAttempt) => {
                    this._announce(`WebSocket connected${isReconnectAttempt ? ' (reconnected)' : ''}.`);
                    this.log(`[ChartCtrl] WebSocket onOpen event. Is Reconnect: ${isReconnectAttempt}.`);

                    // ***** CRUCIAL: Send the subscribe message *****
                    if (this.wsService) {
                        const subscribeMsg = {
                            type: "subscribe",
                            market: this.params.market,
                            provider: this.params.provider,
                            symbol: this.params.symbol,
                            timeframe: this.params.timeframe,
                            since: clientSince // This is the clientSince from localStorage, passed into startLive
                        };
                        this.wsService.sendMessage(subscribeMsg);
                        this.log(`[ChartCtrl] Sent subscribe message: ${JSON.stringify(subscribeMsg)}`);
                    }
                    // ***** END OF SUBSCRIBE MESSAGE *****

                    if (isReconnectAttempt) {
                        this._announce('Reconnected. Fetching latest data...');
                        // Backend should send initial_batch again on reconnect if clientSince is handled.
                    } else {
                        // Message already set in init(): "Connecting & fetching initial data..."
                        // Or here:
                        this._announce('Connection established. Awaiting initial chart data...');
                    }
                },
                onError: e => {
                    this._error(`WebSocket error: ${e.message || 'Connection problem.'}`);
                    // If init is still pending and WS errors out, fail the init
                    if (this.rejectCurrentInitPromise && !this.initialDataRendered) {
                        this._settleInitPromise(false, new Error(`WebSocket connection error: ${e.message}`));
                    }
                },
                onClose: (event) => { // event is a CloseEvent
                    this._announce(`WebSocket disconnected (Code: ${event.code}).`);
                    // If init is still pending and WS closes unexpectedly, fail the init
                    if (this.rejectCurrentInitPromise && !this.initialDataRendered && event.code !== 1000 && event.code !== 1001) { // 1000: Normal, 1001: Going Away
                        this._settleInitPromise(false, new Error(`WebSocket disconnected unexpectedly during init. Code: ${event.code}`));
                    }
                    // Reconnect/fallback is handled by WebSocketService's internal logic
                },
                onFallback: () => { // Called by WebSocketService if max reconnects reached
                    this._error('WebSocket connection failed permanently. Chart updates will stop.');
                    if (this.rejectCurrentInitPromise && !this.initialDataRendered) {
                        this._settleInitPromise(false, new Error("WebSocket connection failed permanently, cannot load initial data."));
                    }
                    // Optionally, you could start HTTP polling here as a last resort if desired for live updates,
                    // but initial load failure is the primary concern for initPromise.
                    // this.startPolling(this.dataManager.latestTs || 0);
                },
                onMessage: (msgEnvelope) => this.handleWebSocketMessage(msgEnvelope),
                onRetryNotice: msg => this._announce(msg)
            });
            this.wsService.start();
        } catch (err) {
            this._error(`Failed to setup WebSocket service: ${err.message}`);
            this.errorLog("WS Setup Error:", err);
            if (this.rejectCurrentInitPromise) {
                this._settleInitPromise(false, new Error(`WebSocket setup failed: ${err.message}`));
            }
            // Fallback to polling could be considered here too if WS can't even be constructed.
            // this.startPolling(this.dataManager.latestTs || 0);
        }
    }

    handlePan(event) {
        if (!this.chart || !this.dataManager || this.isLoadingHist) {
            if (this.isLoadingHist) this.log("[ChartCtrl] Pan ignored: Already loading history.");
            return;
        }
        // dataManager.earliestTs can be null if no data ever loaded
        if (this.dataManager.earliestTs === null && this.dataManager.fullOhlc.length === 0) {
             this.log("[ChartCtrl] Pan ignored: No data loaded yet to determine history range.");
             return;
        }


        const axis = event.target;
        const extremes = axis.getExtremes();
        // Ensure extremes and dataMin are numbers before proceeding
        if (typeof extremes.min !== 'number' || typeof extremes.dataMin !== 'number') {
            this.log("[ChartCtrl] Pan ignored: Extremes not ready or not numbers.");
            return;
        }


        const currentViewRange = extremes.max - extremes.min;
        // Load if current view minimum is within 30% of the dataMin from the start of the view range
        const bufferToTriggerLoad = currentViewRange * 0.3;

        // Trigger condition: if the user has scrolled left such that the current minimum
        // of the viewport (extremes.min) is close to the absolute earliest data point
        // displayed in the chart (extremes.dataMin).
        // We also need to ensure there's actually older data known to DataManager (this.dataManager.earliestTs)
        // that is even older than what's currently displayed (extremes.dataMin).

        const actualEarliestKnownToDataManager = this.dataManager.earliestTs;

        if (extremes.min < (extremes.dataMin + bufferToTriggerLoad)) {
            // And if there's a possibility of older data (DataManager's earliest is less than chart's dataMin,
            // or DataManager thinks it can fetch older than its current earliestTs)
            // This second part of condition may need refinement based on whether DataManager knows if "no more data"
             if (actualEarliestKnownToDataManager !== null && actualEarliestKnownToDataManager < extremes.dataMin) {
                 // This condition means dataManager has data older than what chart currently shows at its leftmost. This shouldn't normally happen if setData is correct.
                 // More likely: we want to load if extremes.min is near extremes.dataMin AND dataManager indicates it might have more.
             }
            // Simplified: if we pan near left edge (dataMin), try loading. DataManager will know if it's truly the end.
            this.log(`[ChartCtrl] Pan triggered history load. ViewMin: ${extremes.min}, DataMin: ${extremes.dataMin}, DM.earliestTs: ${actualEarliestKnownToDataManager}`);
            this.isLoadingHist = true;
            this._announce('Loading older history…');
            this.dataManager.loadMoreHistory()
                .then(historicalData => {
                    if (historicalData.ohlc.length > 0) {
                        this.log(`[ChartCtrl] Prepended ${historicalData.ohlc.length} bars from history load.`);
                        // DataManager has prepended. Chart needs full new dataset.
                        this.chart.get('ohlc')?.setData(this.dataManager.fullOhlc, false);
                        this.chart.get('price-line')?.setData(this.dataManager.fullOhlc.map(b => [b[0], b[4]]), false);
                        this.chart.get('vol')?.setData(this.dataManager.fullVol, false); // Redraw=false initially

                        // Try to maintain user's view by setting extremes to what they were,
                        // but ensure the new min is not beyond the new dataMin.
                        const newChartExtremes = axis.getExtremes(); // Get updated dataMin after setData
                        const preservedMin = Math.max(extremes.min, newChartExtremes.dataMin);
                        const preservedMax = preservedMin + (extremes.max - extremes.min); // Maintain span

                        axis.setExtremes(preservedMin, preservedMax, true, false); // animation=false
                        this._announce(`Loaded ${historicalData.ohlc.length} more historical bars.`);
                    } else {
                        this._announce('No more historical data available.');
                         // If user panned but no new data, chart might need a redraw to settle scrollbar etc.
                        if (this.chart.series[0]?.data.length > 0) this.chart.redraw();
                    }
                })
                .catch(err => {
                    this._error(`Error loading history: ${err.message}`);
                    if (this.chart?.series[0]?.data.length > 0) this.chart.redraw();
                })
                .finally(() => {
                    this.isLoadingHist = false;
                });
        }
        // Update isLiveView status based on whether the rightmost edge of the viewport is near the latest data point.
        const dataMax = this.dataManager.latestTs ?? extremes.dataMax ?? extremes.max;
        // Consider live if max is within half a bar duration of the latest known data point.
        this.isLiveView = extremes.max >= dataMax - (this.dataManager.msPerBar || 60000) * 0.5;
        this.log(`[ChartCtrl] Pan finished. isLiveView: ${this.isLiveView}`);
    }

    startPolling(pollSince = 0) {
        if (this.pollerId !== null) {
            this.log("Polling already active.");
            return;
        }
        // Use latestTs from DataManager if available, otherwise use the provided pollSince or default to 0.
        const effectivePollSince = this.dataManager.latestTs || pollSince || 0;

        // Do not start polling if initial data was never rendered AND we don't have a valid timestamp to poll from.
        if (!this.initialDataRendered && effectivePollSince === 0) {
            this.log("Polling: Not starting as initial data was never rendered and no latestTs known.");
            return;
        }

        const intervalMs = Math.max(5000, Math.min(30000, (this.dataManager.msPerBar || 60000) / 2));
        this.log(`Starting HTTP polling every ${intervalMs / 1000}s, for data since ${effectivePollSince > 0 ? new Date(effectivePollSince).toISOString() : 'beginning (or latest if known)'}`);

        const pollFn = async () => {
            if (this.dataManager.latestTs === null && effectivePollSince === 0) { // Guard against polling without a start point
                this.log("Stopping polling: latest timestamp is null and no effective since.");
                clearInterval(this.pollerId);
                this.pollerId = null;
                return;
            }
            try {
                // Poll for data since the last known timestamp from DataManager
                const sinceForPoll = this.dataManager.latestTs || effectivePollSince;
                const data = await fetchOhlcv({ ...this.params, since: sinceForPoll, limit: 5 }); // Fetch a few bars

                if (data.ohlc.length > 0) {
                    const latestKnownTsBeforePoll = this.dataManager.latestTs;
                    let processedNew = false;
                    data.ohlc.forEach((barDataArray, i) => {
                        // Only process bars strictly newer than what DataManager already has,
                        // or if DataManager has no latestTs (e.g. first poll after init fail but before any data)
                        if (barDataArray[0] > (latestKnownTsBeforePoll || 0) ) {
                            const barObject = {
                                timestamp: barDataArray[0], open: barDataArray[1], high: barDataArray[2],
                                low: barDataArray[3], close: barDataArray[4],
                                volume: data.volume[i]?.[1] ?? 0
                            };
                            this.handleLiveBar(barObject); // This will update DataManager and chart
                            processedNew = true;
                        }
                    });
                    if (processedNew) this.log(`Polling found and processed new bar(s).`);
                }
            } catch (err) {
                this.log(`Polling error: ${err.message}. Polling will continue.`);
            }
        };

        pollFn(); // Run once immediately
        this.pollerId = setInterval(pollFn, intervalMs);
    }

    destroy() {
        this.log("Destroying ChartController...");
        // Settle any pending init promise to prevent unhandled rejections if destroyed mid-init
        if (this.rejectCurrentInitPromise) {
             this._settleInitPromise(false, new Error("ChartController destroyed during initialization."));
        }
        this._clearActiveInitTimeout(); // Ensure timeout is cleared

        this.wsService?.stop();
        clearInterval(this.pollerId);
        this.pollerId = null;
        this.wsService = null;

        if (this.chart) {
            try {
                this.chart.destroy();
            } catch (e) {
                this.errorLog("Error destroying chart:", e);
            }
            this.chart = null;
            setChart(null); // Clear global reference
        }
        // Optionally clear DataManager if it shouldn't persist across controller instances for the same params
        // this.dataManager.clear();
        this.log("ChartController destroyed.");
    }

    // --- UI Interaction Methods (Zoom and Pan) ---
    _tap(fn) {
        if (!this.chart) {
            this._error("Chart not ready. Please wait for data to load or refresh.");
            this.log("_tap: Chart is null.");
            return;
        }
        // Check if there's any data in the primary series before allowing interaction
        const primarySeries = this.chart.get('ohlc') || this.chart.series[0];
        if (!this.initialDataRendered && (!primarySeries || primarySeries.data.length === 0)) {
            this._error("Chart data not yet loaded. Please wait.");
            this.log("_tap: Initial data not rendered and chart series is empty.");
            return;
        }
        try {
            fn();
        } catch (err) {
            this._error(err.message);
            this.errorLog("_tap error:", err);
        }
    }

    zoomIn() { this._tap(() => { this.log("ZoomIn called"); this._zoom('in'); }); }
    zoomOut() { this._tap(() => { this.log("ZoomOut called"); this._zoom('out'); }); }
    panLeft() { this._tap(() => { this.log("PanLeft called"); this._pan('left'); }); }
    panRight() { this._tap(() => { this.log("PanRight called"); this._pan('right'); }); }
    resetToLive() { this._tap(() => { this.log("ResetToLive called"); this._pan('reset'); }); }

    _zoom(dir) {
        this.log(`_zoom(${dir}) called.`);
        const axis = this.chart.xAxis[0];
        const extremes = axis.getExtremes();
        const range = extremes.max - extremes.min;

        // Ensure there's a valid range to zoom
        if (range <= 0 && dir === 'in') {
            this._announce("Cannot zoom in further on a zero or negative range.");
            return;
        }
         // If dataMax/dataMin are undefined (e.g. no data), cannot determine zoom limits
        if (typeof extremes.dataMin !== 'number' || typeof extremes.dataMax !== 'number') {
            this._announce("Cannot zoom: chart data boundaries are unclear.");
            return;
        }


        const newRangeFactor = dir === 'in' ? 0.7 : 1.3;
        let newRange = range * newRangeFactor;

        // Prevent zooming in too far (e.g., less than ~3 bars worth of time)
        const minSensibleRange = (this.dataManager.msPerBar || 60000) * 3;
        if (dir === 'in' && newRange < minSensibleRange && range <= minSensibleRange) { // Check current range too
            this._announce("Zoom level limit reached.");
            return;
        }
        newRange = Math.max(newRange, minSensibleRange); // Don't allow newRange to be smaller than min sensible

        // Prevent zooming out beyond data limits (dataMax - dataMin)
        const maxDataRange = extremes.dataMax - extremes.dataMin;
        if (dir === 'out' && newRange >= maxDataRange && range >= maxDataRange ) { // Check current range too
             if (extremes.min !== extremes.dataMin || extremes.max !== extremes.dataMax) {
                axis.setExtremes(null, null, true, true); // Zoom out fully
                this._announce("Zoomed out fully.");
            } else {
                this._announce("Already zoomed out fully.");
            }
            return;
        }
        newRange = Math.min(newRange, maxDataRange); // Don't allow newRange to be larger than max data range

        const center = extremes.min + range / 2;
        let newMin = center - newRange / 2;
        let newMax = center + newRange / 2;

        // Clamp to data extremes, ensuring newMin and newMax don't cross
        newMin = Math.max(extremes.dataMin, newMin);
        newMax = Math.min(extremes.dataMax, newMax);

        // Adjust if clamping made the range too small or invalid
        if (newMin >= newMax) { // This can happen if zoomed in fully and tried to zoom more
            if (dir === 'in') { // If trying to zoom in on an already minimal range
                 this._announce("Zoom level limit reached.");
                 return;
            }
            // If clamping caused issues, try to reset to a sensible default or do nothing
            newMin = extremes.min;
            newMax = extremes.max;
        }


        axis.setExtremes(newMin, newMax, true, true); // Redraw, animate
        this._announce(dir === 'in' ? 'Zoomed in.' : 'Zoomed out.');
    }

    _pan(dir) {
        this.log(`_pan(${dir}) called.`);
        const axis = this.chart.xAxis[0];
        const extremes = axis.getExtremes();
        const currentSpan = extremes.max - extremes.min;

        // Ensure data boundaries are known
        if (typeof extremes.dataMin !== 'number' || typeof extremes.dataMax !== 'number' || currentSpan <=0) {
            this._announce("Cannot pan: chart data boundaries or current view are unclear.");
            return;
        }

        const moveAmount = currentSpan * 0.25; // Pan by 25% of the current view
        let newMin, newMax, announcementMsg;

        if (dir === 'left') {
            if (extremes.min <= extremes.dataMin) {
                this._announce("Already at the oldest data.");
                return;
            }
            newMin = Math.max(extremes.dataMin, extremes.min - moveAmount);
            newMax = newMin + currentSpan;
            // Ensure newMax doesn't exceed dataMax if newMin was heavily clamped
            newMax = Math.min(newMax, extremes.dataMax);
             // If clamping newMin caused newMax to also need adjustment to maintain span (or part of it)
            if (newMin === extremes.dataMin) newMax = Math.min(extremes.dataMin + currentSpan, extremes.dataMax);


            announcementMsg = 'Panned left.';
        } else if (dir === 'right') {
            const latestDataPoint = this.dataManager.latestTs ?? extremes.dataMax;
            if (extremes.max >= latestDataPoint) {
                this._announce("Already at the newest data.");
                return;
            }
            newMax = Math.min(latestDataPoint, extremes.max + moveAmount);
            newMin = newMax - currentSpan;
            // Ensure newMin doesn't go below dataMin if newMax was heavily clamped
            newMin = Math.max(newMin, extremes.dataMin);
            // If clamping newMax caused newMin to also need adjustment
            if (newMax === latestDataPoint) newMin = Math.max(latestDataPoint - currentSpan, extremes.dataMin);

            announcementMsg = 'Panned right.';
        } else if (dir === 'reset') { // Go to live edge, showing the most recent data
            const latestDataPoint = this.dataManager.latestTs;
            if (latestDataPoint === null) {
                this._announce('No live data available to reset to.');
                return;
            }
             // Try to show a view ending at the latest data point, maintaining current zoom span
            newMax = latestDataPoint;
            newMin = Math.max(extremes.dataMin, latestDataPoint - currentSpan);
            // If the calculated span is now different due to clamping at dataMin, adjust newMax
            if (newMin === extremes.dataMin && (newMin + currentSpan > newMax) ){
                newMax = Math.min(newMin + currentSpan, extremes.dataMax);
            }

            announcementMsg = 'Panned to live data.';
            this.isLiveView = true; // Explicitly set when resetting to live
        } else {
            return; // Unknown direction
        }
        
        // Final check for valid range
        if (newMin >= newMax) {
            this.log("Pan resulted in invalid range, not applying.");
            this._announce("Could not pan further.");
            return;
        }

        axis.setExtremes(newMin, newMax, true, true); // Redraw, animate
        this._announce(announcementMsg);
    }
}