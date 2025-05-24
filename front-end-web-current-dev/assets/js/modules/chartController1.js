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
            onAnnounce: this._announce.bind(this),
            controller: this
        });

        this.chart = null;
        this.wsService = null;
        this.pollerId = null;
        this.isLoadingHist = false;
        this.isLiveView = true;
        this.minPointsForZoom = 10;
        this.initialDataRendered = false;

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
        return 0;
    }

    _announce(msg, isError = false) {
        if (isError) {
            this.errorLog(msg);
        } else {
            this.log(msg);
        }
        const el = isError ? (document.getElementById('chartErrorStatus') || this.announceEl) : this.announceEl;
        if (el) {
            el.textContent = '';
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
            this._clearActiveInitTimeout();
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
            this.startLive(clientSince);

            const INITIAL_DATA_TIMEOUT_MS = 30000;
            this.log(`[ChartCtrl] Setting init timeout for ${INITIAL_DATA_TIMEOUT_MS / 1000}s.`);
            this.activeInitTimeoutId = setTimeout(() => {
                if (this.rejectCurrentInitPromise && !this.initialDataRendered) {
                    const errMsg = `Timeout (${INITIAL_DATA_TIMEOUT_MS / 1000}s): Initial chart data not rendered.`;
                    this.errorLog(`[ChartCtrl] !!!! INIT TIMEOUT FIRED for ${this.params.symbol} !!!! initialDataRendered: ${this.initialDataRendered}`);
                    this._error(errMsg);
                    this._settleInitPromise(false, new Error(errMsg));
                } else if (this.initialDataRendered && this.resolveCurrentInitPromise) {
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
            if (!this.initialDataRendered) {
                this._error(`Failed to load chart: ${error?.message || 'Unknown error'}`);
            }
            return null;
        } finally {
            this.initPromise = null;
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
            if (this.chart.series && this.chart.series.length > 0) this.chart.redraw();
            return;
        }

        if (total >= this.minPointsForZoom) {
            let take = Math.max(Math.floor(total * 0.25), this.minPointsForZoom);
            take = Math.min(take, total);
            const minTsIndex = Math.max(0, total - take);
            const minTs = ohlc[minTsIndex]?.[0];
            const maxTs = ohlc[total - 1]?.[0];

            if (typeof minTs === 'number' && typeof maxTs === 'number' && minTs <= maxTs) {
                if (minTs === maxTs && total > 1) {
                    this.log("Initial zoom: Multiple points at same timestamp, Highcharts default zoom.");
                    if (this.chart.series && this.chart.series.length > 0) this.chart.redraw();
                } else if (minTs === maxTs && total === 1) {
                    const pointTime = minTs;
                    const barDuration = this.dataManager.msPerBar || 60000;
                    const windowMin = pointTime - (barDuration * 5);
                    const windowMax = pointTime + (barDuration * 5);
                    this.chart.xAxis[0].setExtremes(windowMin, windowMax, true, false);
                    this._announce(`Showing single data point.`);
                } else {
                    this.chart.xAxis[0].setExtremes(minTs, maxTs, true, false);
                    this._announce(`Chart zoomed to show most recent ${take} bars.`);
                }
            } else {
                this.log("Could not set initial zoom extremes (invalid timestamps/range). Defaulting.");
                if (this.chart.series && this.chart.series.length > 0) this.chart.redraw();
            }
        } else {
            this._announce(`Showing all ${total} available bars.`);
            this.chart.xAxis[0].setExtremes(null, null, true, false);
        }
    }

    handleWebSocketMessage(msgEnvelope) {
        const { type, symbol, timeframe, payload } = msgEnvelope;
        this.log(`[ChartCtrl] Handling WS Message: Type=${type}, Symbol=${symbol || 'N/A'}, ForChart=${this.params.symbol}, PayloadKeys=${payload ? Object.keys(payload).join(',') : 'N/A'}. InitialRendered: ${this.initialDataRendered}`);

        if (symbol && symbol !== this.params.symbol) {
            this.log(`[ChartCtrl] Ignoring message for different symbol: ${symbol}`);
            return;
        }
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

        const ohlcData = payload?.ohlc || [];
        const volumeData = payload?.volume || [];

        if (type === 'data') {
            if (payload?.initial_batch) {
                this.log(`[ChartCtrl] Processing initial_batch for ${this.params.symbol}: ${ohlcData.length} bars. Status: "${payload.status_message || ''}"`);
                this.dataManager.clear();
                if (ohlcData.length > 0) {
                    ohlcData.forEach((barArray, i) => {
                        const vol = volumeData[i]?.[1] ?? 0;
                        const fullBarData = [...barArray, vol];
                        try {
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
                        this.initialDataRendered = true;
                        this._applyInitialZoom();
                        renderSuccess = true;
                    } else {
                        this._error("[ChartCtrl] CRITICAL: ChartRenderer.render returned null for initial_batch.");
                    }
                } else {
                    this.log("[ChartCtrl] Updating EXISTING chart with initial_batch data (e.g., after reconnect).");
                    this.chart.get('ohlc')?.setData(this.dataManager.fullOhlc, false);
                    this.chart.get('price-line')?.setData(this.dataManager.fullOhlc.map(b => [b[0], b[4]]), false);
                    this.chart.get('vol')?.setData(this.dataManager.fullVol, true);
                    this.initialDataRendered = true;
                    this._applyInitialZoom();
                    renderSuccess = true;
                }

                if (renderSuccess) {
                    const message = ohlcData.length > 0 ? `Chart loaded with ${ohlcData.length} initial bars.` : (payload.status_message || 'Chart loaded. No initial bars. Awaiting live updates.');
                    this._announce(message);
                    if (this.dataManager.latestTs) {
                        this._saveLatestTsToLocalStorage();
                    }
                    this._settleInitPromise(true, this.chart);
                } else {
                    this._settleInitPromise(false, new Error("Chart rendering failed for initial_batch."));
                }
            } else if (payload?.catch_up_batch) {
                this.log(`[ChartCtrl] Processing catch_up_batch for ${this.params.symbol}: ${ohlcData.length} bars.`);
                // ... (rest of catch_up_batch logic from your first version) ...
                if (!this.initialDataRendered && !this.chart) {
                    this.log("[ChartCtrl] Warning: Received catch_up_batch before initial chart fully rendered. Data will be added to DataManager.");
                }
                let newBarsAddedToDataManager = 0;
                if (ohlcData.length > 0) {
                    ohlcData.forEach((barArray, i) => {
                        const vol = volumeData[i]?.[1] ?? 0;
                        const fullBarData = [...barArray, vol];
                        try {
                            const addedOrUpdated = this.dataManager.addBar(fullBarData, true);
                            if (addedOrUpdated) newBarsAddedToDataManager++;
                        } catch (e) { this.log(`[ChartCtrl] catch_up_batch: Skipping bar (addBar error: ${e.message}) TS: ${barArray[0]}`) }
                    });
                }

                if (newBarsAddedToDataManager > 0) {
                    if (this.chart && this.initialDataRendered) {
                        this.log(`[ChartCtrl] catch_up_batch: Refreshing chart data after ${newBarsAddedToDataManager} bars added/updated.`);
                        this.chart.get('ohlc')?.setData(this.dataManager.fullOhlc, false);
                        this.chart.get('price-line')?.setData(this.dataManager.fullOhlc.map(b => [b[0], b[4]]), false);
                        this.chart.get('vol')?.setData(this.dataManager.fullVol, this.isLiveView);
                    }
                    if (this.dataManager.latestTs) this._saveLatestTsToLocalStorage();
                    this._announce(`Chart updated with ${newBarsAddedToDataManager} catch-up bars.`);
                } else {
                    this._announce('No new bars in catch-up batch.');
                }
            } else {
                // This case handles 'data' messages that are neither initial_batch nor catch_up_batch.
                // These could be, for example, data from an HTTP poll if that were implemented to push via this path.
                // For pure WebSocket live updates, these should ideally come as 'update' type.
                this.log(`[ChartCtrl] Received un-flagged 'data' message. Treating as live. Payload Preview: ${JSON.stringify(payload).substring(0, 100)}`);
                if (ohlcData.length > 0) {
                    ohlcData.forEach((ohlcBarArray, index) => {
                        const volumeVal = volumeData[index]?.[1] ?? 0;
                        const liveBarObject = {
                            timestamp: ohlcBarArray[0], open: ohlcBarArray[1], high: ohlcBarArray[2],
                            low: ohlcBarArray[3], close: ohlcBarArray[4], volume: volumeVal
                        };
                        this.handleLiveBar(liveBarObject);
                    });
                } else {
                    this.log("[ChartCtrl] Un-flagged 'data' message had empty ohlcData.");
                }
            }
        } else if (type === 'update') { // ***** ADDED BLOCK FOR 'update' TYPE *****
            this.log(`[ChartCtrl] Received 'update' message. Payload Preview: ${JSON.stringify(payload).substring(0, 100)}`);
            // Payload for 'update' from backend is: {"ohlc": [[ts,o,h,l,c],...], "volume": [[ts,v],...]}
            // where ohlc/volume arrays might contain one or more new/updated bars.
            if (ohlcData.length > 0) {
                ohlcData.forEach((ohlcBarArray, index) => {
                    const volumeVal = volumeData[index]?.[1] ?? 0;
                    const liveBarObject = {
                        timestamp: ohlcBarArray[0], open: ohlcBarArray[1], high: ohlcBarArray[2],
                        low: ohlcBarArray[3], close: ohlcBarArray[4], volume: volumeVal
                    };
                    // this.log(`[ChartCtrl] Calling handleLiveBar for 'update' TS: ${liveBarObject.timestamp}`);
                    this.handleLiveBar(liveBarObject); // handleLiveBar processes one bar at a time
                });
            } else {
                this.log("[ChartCtrl] 'update' message had empty ohlcData.");
            }
        } else {
            this.log(`[ChartCtrl] Unhandled WebSocket message type: ${type}`);
        }
    }

    handleLiveBar(barData) {
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

            const updateType = this.dataManager.addBar(barArrayForDM, true);

            const ts = +barData.timestamp;
            const ohlcPoint = [ts, +barData.open, +barData.high, +barData.low, +barData.close];
            const closePoint = [ts, +barData.close];
            const volPoint = [ts, +barData.volume || 0];

            const ohlcSeries = this.chart.get('ohlc');
            const priceLineSeries = this.chart.get('price-line');
            const volSeries = this.chart.get('vol');
            let needsRedraw = false;

            if (updateType === 'updated') {
                // this.log(`[ChartCtrl] LiveBar: Updating existing last point for TS ${ts}`);
                if (ohlcSeries?.data.length > 0) {
                    const lastPt = ohlcSeries.data[ohlcSeries.data.length - 1];
                    if (lastPt.x === ts) lastPt.update(ohlcPoint, false); else ohlcSeries.addPoint(ohlcPoint, false, false, false);
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
                // this.log(`[ChartCtrl] LiveBar: Adding new point for TS ${ts}`);
                const shift = (ohlcSeries?.data?.length || 0) > 2000;
                ohlcSeries?.addPoint(ohlcPoint, false, shift, false);
                priceLineSeries?.addPoint(closePoint, false, shift, false);
                volSeries?.addPoint(volPoint, false, shift, false);
                needsRedraw = true;
            } else {
                this.log(`[ChartCtrl] Live bar TS: ${barData.timestamp} was not processed by DataManager (updateType: ${updateType}). No chart update.`);
                return;
            }

            if (this.isLiveView && needsRedraw) {
                this.chart.redraw();
            }
            this._saveLatestTsToLocalStorage();
        } catch (err) {
            this.errorLog(`[ChartCtrl] handleLiveBar error: ${err.message}`, err);
        }
    }

    startLive(clientSince = 0) {
        this.log(`[ChartCtrl] startLive called. clientSince: ${clientSince === 0 ? 'Fresh (0)' : new Date(clientSince).toISOString()}`);
        this.wsService?.stop();
        clearInterval(this.pollerId);
        this.pollerId = null;

        const wsParams = { ...this.params, since: clientSince };

        try {
            this.wsService = new WebSocketService(wsParams, {
                onOpen: (isReconnectAttempt) => {
                    this._announce(`WebSocket connected${isReconnectAttempt ? ' (reconnected)' : ''}.`);
                    this.log(`[ChartCtrl] WebSocket onOpen event. Is Reconnect: ${isReconnectAttempt}.`);
                    if (this.wsService) {
                        const subscribeMsg = {
                            type: "subscribe",
                            market: this.params.market,
                            provider: this.params.provider,
                            symbol: this.params.symbol,
                            timeframe: this.params.timeframe,
                            since: clientSince
                        };
                        this.wsService.sendMessage(subscribeMsg);
                        this.log(`[ChartCtrl] Sent subscribe message: ${JSON.stringify(subscribeMsg)}`);
                    }
                    if (isReconnectAttempt) {
                        this._announce('Reconnected. Fetching latest data...');
                    } else {
                        this._announce('Connection established. Awaiting initial chart data...');
                    }
                },
                onError: e => {
                    this._error(`WebSocket error: ${e.message || 'Connection problem.'}`);
                    if (this.rejectCurrentInitPromise && !this.initialDataRendered) {
                        this._settleInitPromise(false, new Error(`WebSocket connection error: ${e.message}`));
                    }
                },
                onClose: (event) => {
                    this._announce(`WebSocket disconnected (Code: ${event.code}).`);
                    if (this.rejectCurrentInitPromise && !this.initialDataRendered && event.code !== 1000 && event.code !== 1001) {
                        this._settleInitPromise(false, new Error(`WebSocket disconnected unexpectedly during init. Code: ${event.code}`));
                    }
                },
                onFallback: () => {
                    this._error('WebSocket connection failed permanently. Chart updates will stop.');
                    if (this.rejectCurrentInitPromise && !this.initialDataRendered) {
                        this._settleInitPromise(false, new Error("WebSocket connection failed permanently, cannot load initial data."));
                    }
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
        }
    }

    handlePan(event) {
        if (!this.chart || !this.dataManager || this.isLoadingHist) {
            if (this.isLoadingHist) this.log("[ChartCtrl] Pan ignored: Already loading history.");
            return;
        }
        if (this.dataManager.earliestTs === null && this.dataManager.fullOhlc.length === 0) {
             this.log("[ChartCtrl] Pan ignored: No data loaded yet to determine history range.");
             return;
        }

        const axis = event.target;
        const extremes = axis.getExtremes();
        if (typeof extremes.min !== 'number' || typeof extremes.dataMin !== 'number') {
            this.log("[ChartCtrl] Pan ignored: Extremes not ready or not numbers.");
            return;
        }

        const currentViewRange = extremes.max - extremes.min;
        const bufferToTriggerLoad = currentViewRange * 0.3;
        const actualEarliestKnownToDataManager = this.dataManager.earliestTs;

        if (extremes.min < (extremes.dataMin + bufferToTriggerLoad)) {
            this.log(`[ChartCtrl] Pan triggered history load. ViewMin: ${extremes.min}, DataMin: ${extremes.dataMin}, DM.earliestTs: ${actualEarliestKnownToDataManager}`);
            this.isLoadingHist = true;
            this._announce('Loading older history…');
            this.dataManager.loadMoreHistory()
                .then(historicalData => {
                    if (historicalData.ohlc.length > 0) {
                        this.log(`[ChartCtrl] Prepended ${historicalData.ohlc.length} bars from history load.`);
                        this.chart.get('ohlc')?.setData(this.dataManager.fullOhlc, false);
                        this.chart.get('price-line')?.setData(this.dataManager.fullOhlc.map(b => [b[0], b[4]]), false);
                        this.chart.get('vol')?.setData(this.dataManager.fullVol, false);

                        const newChartExtremes = axis.getExtremes();
                        const preservedMin = Math.max(extremes.min, newChartExtremes.dataMin);
                        const preservedMax = preservedMin + (extremes.max - extremes.min);
                        axis.setExtremes(preservedMin, preservedMax, true, false);
                        this._announce(`Loaded ${historicalData.ohlc.length} more historical bars.`);
                    } else {
                        this._announce('No more historical data available.');
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
        const dataMax = this.dataManager.latestTs ?? extremes.dataMax ?? extremes.max;
        this.isLiveView = extremes.max >= dataMax - (this.dataManager.msPerBar || 60000) * 0.5;
        this.log(`[ChartCtrl] Pan finished. isLiveView: ${this.isLiveView}`);
    }

    startPolling(pollSince = 0) {
        if (this.pollerId !== null) {
            this.log("Polling already active.");
            return;
        }
        const effectivePollSince = this.dataManager.latestTs || pollSince || 0;
        if (!this.initialDataRendered && effectivePollSince === 0) {
            this.log("Polling: Not starting as initial data was never rendered and no latestTs known.");
            return;
        }

        const intervalMs = Math.max(5000, Math.min(30000, (this.dataManager.msPerBar || 60000) / 2));
        this.log(`Starting HTTP polling every ${intervalMs / 1000}s, for data since ${effectivePollSince > 0 ? new Date(effectivePollSince).toISOString() : 'beginning (or latest if known)'}`);

        const pollFn = async () => {
            if (this.dataManager.latestTs === null && effectivePollSince === 0) {
                this.log("Stopping polling: latest timestamp is null and no effective since.");
                clearInterval(this.pollerId);
                this.pollerId = null;
                return;
            }
            try {
                const sinceForPoll = this.dataManager.latestTs || effectivePollSince;
                const data = await fetchOhlcv({ ...this.params, since: sinceForPoll, limit: 5 });
                if (data.ohlc.length > 0) {
                    const latestKnownTsBeforePoll = this.dataManager.latestTs;
                    let processedNew = false;
                    data.ohlc.forEach((barDataArray, i) => {
                        if (barDataArray[0] > (latestKnownTsBeforePoll || 0) ) {
                            const barObject = {
                                timestamp: barDataArray[0], open: barDataArray[1], high: barDataArray[2],
                                low: barDataArray[3], close: barDataArray[4],
                                volume: data.volume[i]?.[1] ?? 0
                            };
                            this.handleLiveBar(barObject);
                            processedNew = true;
                        }
                    });
                    if (processedNew) this.log(`Polling found and processed new bar(s).`);
                }
            } catch (err) {
                this.log(`Polling error: ${err.message}. Polling will continue.`);
            }
        };
        pollFn();
        this.pollerId = setInterval(pollFn, intervalMs);
    }

    destroy() {
        this.log("Destroying ChartController...");
        if (this.rejectCurrentInitPromise) {
             this._settleInitPromise(false, new Error("ChartController destroyed during initialization."));
        }
        this._clearActiveInitTimeout();
        this.wsService?.stop();
        clearInterval(this.pollerId);
        this.pollerId = null;
        this.wsService = null;
        if (this.chart) {
            try { this.chart.destroy(); } catch (e) { this.errorLog("Error destroying chart:", e); }
            this.chart = null;
            setChart(null);
        }
        this.log("ChartController destroyed.");
    }

    _tap(fn) {
        if (!this.chart) {
            this._error("Chart not ready. Please wait for data to load or refresh.");
            this.log("_tap: Chart is null.");
            return;
        }
        const primarySeries = this.chart.get('ohlc') || this.chart.series[0];
        if (!this.initialDataRendered && (!primarySeries || primarySeries.data.length === 0)) {
            this._error("Chart data not yet loaded. Please wait.");
            this.log("_tap: Initial data not rendered and chart series is empty.");
            return;
        }
        try { fn(); }
        catch (err) { this._error(err.message); this.errorLog("_tap error:", err); }
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

        if (range <= 0 && dir === 'in') {
            this._announce("Cannot zoom in further on a zero or negative range.");
            return;
        }
        if (typeof extremes.dataMin !== 'number' || typeof extremes.dataMax !== 'number') {
            this._announce("Cannot zoom: chart data boundaries are unclear.");
            return;
        }

        const newRangeFactor = dir === 'in' ? 0.7 : 1.3;
        let newRange = range * newRangeFactor;
        const minSensibleRange = (this.dataManager.msPerBar || 60000) * 3;

        if (dir === 'in' && newRange < minSensibleRange && range <= minSensibleRange) {
            this._announce("Zoom level limit reached.");
            return;
        }
        newRange = Math.max(newRange, minSensibleRange);
        const maxDataRange = extremes.dataMax - extremes.dataMin;

        if (dir === 'out' && newRange >= maxDataRange && range >= maxDataRange ) {
             if (extremes.min !== extremes.dataMin || extremes.max !== extremes.dataMax) {
                axis.setExtremes(null, null, true, true);
                this._announce("Zoomed out fully.");
            } else {
                this._announce("Already zoomed out fully.");
            }
            return;
        }
        newRange = Math.min(newRange, maxDataRange);

        const center = extremes.min + range / 2;
        let newMin = center - newRange / 2;
        let newMax = center + newRange / 2;

        newMin = Math.max(extremes.dataMin, newMin);
        newMax = Math.min(extremes.dataMax, newMax);

        if (newMin >= newMax) {
            if (dir === 'in') {
                 this._announce("Zoom level limit reached.");
                 return;
            }
            newMin = extremes.min;
            newMax = extremes.max;
        }
        axis.setExtremes(newMin, newMax, true, true);
        this._announce(dir === 'in' ? 'Zoomed in.' : 'Zoomed out.');
    }

    _pan(dir) {
        this.log(`_pan(${dir}) called.`);
        const axis = this.chart.xAxis[0];
        const extremes = axis.getExtremes();
        const currentSpan = extremes.max - extremes.min;

        if (typeof extremes.dataMin !== 'number' || typeof extremes.dataMax !== 'number' || currentSpan <=0) {
            this._announce("Cannot pan: chart data boundaries or current view are unclear.");
            return;
        }

        const moveAmount = currentSpan * 0.25;
        let newMin, newMax, announcementMsg;

        if (dir === 'left') {
            if (extremes.min <= extremes.dataMin) {
                this._announce("Already at the oldest data.");
                return;
            }
            newMin = Math.max(extremes.dataMin, extremes.min - moveAmount);
            newMax = newMin + currentSpan;
            newMax = Math.min(newMax, extremes.dataMax);
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
            newMin = Math.max(newMin, extremes.dataMin);
            if (newMax === latestDataPoint) newMin = Math.max(latestDataPoint - currentSpan, extremes.dataMin);
            announcementMsg = 'Panned right.';
        } else if (dir === 'reset') {
            const latestDataPoint = this.dataManager.latestTs;
            if (latestDataPoint === null) {
                this._announce('No live data available to reset to.');
                return;
            }
            newMax = latestDataPoint;
            newMin = Math.max(extremes.dataMin, latestDataPoint - currentSpan);
            if (newMin === extremes.dataMin && (newMin + currentSpan > newMax) ){
                newMax = Math.min(newMin + currentSpan, extremes.dataMax);
            }
            announcementMsg = 'Panned to live data.';
            this.isLiveView = true;
        } else {
            return;
        }
        
        if (newMin >= newMax) {
            this.log("Pan resulted in invalid range, not applying.");
            this._announce("Could not pan further.");
            return;
        }

        axis.setExtremes(newMin, newMax, true, true);
        this._announce(announcementMsg);
    }
}