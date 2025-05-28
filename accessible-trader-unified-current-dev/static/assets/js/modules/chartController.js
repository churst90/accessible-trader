// assets/js/modules/chartController.js

import DataManager from './dataManager.js';
import ChartRenderer from './chartRenderer.js';
// Corrected path assumption if needed, relative to chartController.js
import WebSocketService from './wsService.js';
import { fetchOhlcv } from './dataService.js'; // Used by dataManager.loadMoreHistory and potentially polling
import { setChart } from './chartStore.js'; // Used to set global chart reference

export default class ChartController {
    /**
     * Manages the lifecycle and state of a single chart instance, including data fetching,
     * rendering, and live updates.
     * It orchestrates interactions between the DataManager,
     * ChartRenderer, and WebSocketService to provide a dynamic charting experience.
     * @param {HTMLElement} container - The DOM element where the Highcharts chart will be rendered.
     * @param {HTMLElement} announceEl - The DOM element to display status/error messages to the user.
     * @param {{ market:string, provider:string, symbol:string, timeframe:string }} params - Chart parameters defining the asset and timeframe.
     * @param {{ logFn?:function }} [opts] - Optional logging function for internal messages. Defaults to console.log.
     */
    constructor(container, announceEl, params, { logFn = console.log } = {}) {
        this.container = container; //
        this.announceEl = announceEl; //
        this.params = params; //
        // Bind logging functions for easier debugging with chart-specific context
        this.log = (...args) => logFn('[ChartCtrl]', `[${this.params.symbol}/${this.params.timeframe}]`, ...args); //
        this.errorLog = (...args) => console.error('[ChartCtrl]', `[${this.params.symbol}/${this.params.timeframe}]`, ...args); //

        // DataManager handles client-side data storage and historical data loading
        this.dataManager = new DataManager(params, { logFn: this.log }); //
        // ChartRenderer handles the actual Highcharts rendering and updates.
        // It receives callbacks for pan events and a reference to this controller.
        this.renderer = new ChartRenderer(container, { //
            onPan: this.handlePan.bind(this), //
            onAnnounce: this._announce.bind(this), //
            controller: this // Allows renderer to call back to controller for pan events etc.
        });
        this.chart = null; // Reference to the Highcharts Chart instance (set after initial render)
        this.wsService = null; //
        // WebSocketService instance for live data updates
        this.pollerId = null; //
        // Interval ID for HTTP polling fallback (if WS fails)
        this.isLoadingHist = false; //
        // Flag to prevent concurrent historical data loads via panning
        this.isLiveView = true; //
        // Flag indicating if the chart view is currently at the latest data
        this.minPointsForZoom = 10; //
        // Minimum number of data points required for initial zoom to be applied
        this.initialDataRendered = false; //
        // Flag set after the very first data batch is successfully rendered

        // Promise management for the initial chart load process.
        // This promise resolves once the first data batch is processed and rendered.
        this.initPromise = null; //
        this.resolveCurrentInitPromise = null; //
        this.rejectCurrentInitPromise = null; //
        this.activeInitTimeoutId = null; // Timeout to handle cases where initial data doesn't arrive

        this.log(`ChartController instantiated.`); //
    }

    /**
     * Generates a unique key for localStorage based on chart parameters.
     * Used to save and load the latest timestamp, allowing reconnects to resume from where they left off.
     * @returns {string} The localStorage key string.
     * @private
     */
    _getLocalStorageKey() {
        return `latestTs_${this.params.market}_${this.params.provider}_${this.params.symbol}_${this.params.timeframe}`; //
    }

    /**
     * Saves the latest timestamp from DataManager to localStorage for persistence.
     * This helps the chart reconnect to live data without fetching full history again.
     * @private
     */
    _saveLatestTsToLocalStorage() {
        if (this.dataManager.latestTs !== null && this.dataManager.latestTs > 0) { //
            const storageKey = this._getLocalStorageKey(); //
            try {
                localStorage.setItem(storageKey, String(this.dataManager.latestTs)); //
                this.log(`Saved latestTs ${this.dataManager.latestTs} (${new Date(this.dataManager.latestTs).toISOString()}) to localStorage.`); //
            } catch (e) {
                this.errorLog("Error writing latestTs to localStorage", e); //
            }
        } else {
            this.log(`Skipped saving latestTs to localStorage; DataManager.latestTs is null or invalid: ${this.dataManager.latestTs}`); //
        }
    }

    /**
     * Loads the latest timestamp from localStorage.
     * @returns {number} The loaded timestamp (milliseconds), or 0 if not found/invalid,
     * indicating that the chart should request fresh history from the beginning.
     * @private
     */
    _loadLatestTsFromLocalStorage() {
        const storageKey = this._getLocalStorageKey(); //
        try {
            const storedVal = localStorage.getItem(storageKey); //
            if (storedVal) { //
                const parsedVal = parseInt(storedVal, 10); //
                if (!isNaN(parsedVal) && parsedVal > 0) { //
                    this.log(`Loaded latestTs ${parsedVal} (${new Date(parsedVal).toISOString()}) from localStorage.`); //
                    return parsedVal; //
                }
            }
        } catch (e) {
            this.errorLog("Error reading latestTs from localStorage", e); //
        }
        this.log(`No valid latestTs found in localStorage. Requesting fresh history (clientSince=0).`); //
        return 0; //
    }

    /**
     * Displays messages to the user via the announcement element in the UI.
     * @param {string} msg - The message content to display.
     * @param {boolean} [isError=false] - If true, treats the message as an error and potentially
     * targets a different error display element.
     * @private
     */
    _announce(msg, isError = false) {
        if (isError) { //
            this.errorLog(msg); //
        } else {
            this.log(msg); //
        }
        const el = isError ? (document.getElementById('chartErrorStatus') || this.announceEl) : this.announceEl; //
        if (el) { //
            el.textContent = ''; //
            // Clear existing message immediately for responsiveness
            setTimeout(() => { if (el) el.textContent = msg; }, 50); //
            // Set new message after a brief delay
        }
    }

    /**
     * Convenience method to display an error message to the user.
     * @param {string} msg - The error message.
     * @private
     */
    _error(msg) {
        this._announce(msg, true); //
    }

    /**
     * Resolves or rejects the current initialization promise.
     * This method is called internally
     * to manage the `init()` method's asynchronous flow.
     * @param {boolean} isSuccess - True if initialization was successful, false for failure.
     * @param {any} valueOrError - The value to resolve the promise with, or the error to reject with.
     * @private
     */
    _settleInitPromise(isSuccess, valueOrError) {
        this._clearActiveInitTimeout(); //
        // Clear any pending timeout
        if (isSuccess) { //
            if (this.resolveCurrentInitPromise) { //
                this.log("Resolving current init promise."); //
                this.resolveCurrentInitPromise(valueOrError); //
            } else {
                this.log("Init promise already settled or no resolver, resolve action ignored."); //
            }
        } else {
            if (this.rejectCurrentInitPromise) { //
                this.errorLog("Rejecting current init promise with error:", valueOrError?.message || valueOrError); //
                this.rejectCurrentInitPromise(valueOrError); //
            } else {
                this.errorLog("Init promise already settled or no rejector, reject action ignored. Error was:", valueOrError?.message || valueOrError); //
            }
        }
        // Clear references to prevent multiple settlements and potential memory leaks
        this.resolveCurrentInitPromise = null; //
        this.rejectCurrentInitPromise = null; //
    }

    /**
     * Clears any active initialization timeout (set during `init()`).
     * @private
     */
    _clearActiveInitTimeout() {
        if (this.activeInitTimeoutId) { //
            clearTimeout(this.activeInitTimeoutId); //
            this.activeInitTimeoutId = null; //
            this.log("Cleared active init timeout."); //
        }
    }

    /**
     * Initializes the chart controller for a new chart display.
     * This method is the main entry point
     * for loading any chart configuration.
     * It handles cleaning up previous chart state,
     * fetching initial data via WebSocket, rendering/updating the Highcharts chart,
     * and managing the initialization promise lifecycle.
     * @returns {Promise<Highcharts.Chart|null>} A promise that resolves with the Highcharts chart instance
     * once initial data is rendered, or rejects if initialization fails.
     */
    async init() {
        this.log(`>>> init() started.`); //
        // If a previous init operation is still pending on this controller instance, cancel it.
        // This is crucial for handling rapid chart switching where a new init starts before the old one fully completes.
        if (this.initPromise) { //
            this.log("An init operation may already be in progress. Cancelling previous and proceeding with new init."); //
            this._clearActiveInitTimeout(); //
            if (this.rejectCurrentInitPromise) { //
                this.rejectCurrentInitPromise(new Error("New chart initialization started.")); //
                this.rejectCurrentInitPromise = null; //
                this.resolveCurrentInitPromise = null; //
            }
        }

        // Reset all internal state flags for a fresh initialization of this controller instance
        this.isLoadingHist = false; //
        this.isLiveView = true; //
        this.initialDataRendered = false; //

        // Clean up any existing WebSocket service or poller from a previous session
        this.wsService?.stop(); //
        // Gracefully stop WebSocket connection
        clearInterval(this.pollerId); //
        // Clear any active HTTP polling interval
        this.pollerId = null; //
        this.wsService = null; //
        // Clear reference to old WS service instance

        // The `uiBindings.js` (caller) is expected to have destroyed the *previous* ChartController instance,
        // which would have destroyed its `this.chart`.
        // So, `this.chart` on *this new instance* should be null.
        // We only clear the DataManager for a fresh start for new data.
        this.dataManager.clear(); //

        this._announce('Connecting & fetching initial data...'); //
        // Attempt to load the last known timestamp from localStorage to request historical data from that point.
        // This helps in resuming live data efficiently after a page refresh or re-opening.
        const clientSince = this._loadLatestTsFromLocalStorage(); //
        // Create a new promise for this initialization, to be resolved when initial data is rendered
        // This promise helps manage the async flow of initial data fetching and rendering.
        this.initPromise = new Promise((resolve, reject) => { //
            this.resolveCurrentInitPromise = resolve; //
            this.rejectCurrentInitPromise = reject; //

            this.log(`Starting new live connection for init. clientSince: ${clientSince === 0 ? 'Fresh (0)' : new Date(clientSince).toISOString()}`); //
            this.startLive(clientSince); // Initiates the WebSocket connection and sends the subscription message

            // Set a timeout for 
            // initial data to arrive and render.
            // This prevents the chart from being stuck in a loading state indefinitely if no data arrives.
            const INITIAL_DATA_TIMEOUT_MS = 30000; // 30 seconds
            this.log(`Setting init timeout for ${INITIAL_DATA_TIMEOUT_MS / 1000}s.`); //
            this.activeInitTimeoutId = setTimeout(() => { //
                if (this.rejectCurrentInitPromise && !this.initialDataRendered) { //
                    const errMsg = `Timeout (${INITIAL_DATA_TIMEOUT_MS / 1000}s): Initial chart data not rendered.`; //
                    this.errorLog(`!!!! INIT TIMEOUT FIRED !!!! initialDataRendered: ${this.initialDataRendered}`); //
                    this._error(errMsg); //
                    this._settleInitPromise(false, new Error(errMsg)); //
                    // Reject the promise if timeout
                } else if (this.initialDataRendered && this.resolveCurrentInitPromise) { //
                    // This scenario means data rendered just before timeout, but promise wasn't settled.
                    // Force resolve.
                    this.log(`Init timeout fired, but initialDataRendered is true. Forcing resolution.`); //
                    this._settleInitPromise(true, this.chart); //
                } else { //
                    this.log(`Init timeout callback: No action needed (promise already settled or no rejector).`); //
                }
            }, INITIAL_DATA_TIMEOUT_MS); //
        });
        // Wait for the initialization promise to resolve/reject
        try {
            const chartInstance = await this.initPromise; //
            this.log(`<<< init() SUCCESSFULLY COMPLETED. Chart instance: ${chartInstance ? 'OK' : 'NULL'}`); //
            return chartInstance; //
        } catch (error) { //
            this.errorLog(`<<< init() FAILED: ${error?.message || error}`); //
            if (!this.initialDataRendered) { // Only show general error to UI if initial data was never rendered
                this._error(`Failed to load chart: ${error?.message || 'Unknown error'}`); //
            }
            return null; //
        } finally { //
            this.initPromise = null; //
            // Clear the promise reference regardless of outcome
        }
    }

    /**
     * Applies an initial zoom level to the Highcharts chart once data is loaded.
     * This method ensures the chart is viewable in a sensible range after initial load,
     * typically focusing on the most recent data points.
     * @private
     */
    _applyInitialZoom() {
        if (!this.chart || !this.initialDataRendered) { //
            this.log("Skipping initial zoom: chart not ready or initial data not fully processed."); //
            return; //
        }
        const ohlc = this.dataManager.fullOhlc; //
        const total = ohlc.length; //
        this.log(`Applying initial zoom. Total bars in DataManager: ${total}`); //

        if (total === 0) { //
            this._announce("Chart loaded with no data points. Default zoom."); //
            if (this.chart.series && this.chart.series.length > 0) this.chart.redraw(); // Ensure redraw if no data
            return; //
        }

        if (total >= this.minPointsForZoom) { //
            // Calculate a reasonable number of bars to show for initial zoom (e.g., last 25% or minPointsForZoom)
            let take = Math.max(Math.floor(total * 0.25), this.minPointsForZoom); //
            take = Math.min(take, total); // Ensure 'take' doesn't exceed total bars

            // Get timestamps for the calculated range to set chart extremes
            const minTsIndex = Math.max(0, total - take); //
            const minTs = ohlc[minTsIndex]?.[0]; //
            const maxTs = ohlc[total - 1]?.[0]; //
            if (typeof minTs === 'number' && typeof maxTs === 'number' && minTs <= maxTs) { //
                if (minTs === maxTs && total > 1) { //
                    // Multiple points at same timestamp, Highcharts default zoom.
                    this.log("Initial zoom: Multiple points at same timestamp, Highcharts default zoom."); //
                    if (this.chart.series && this.chart.series.length > 0) this.chart.redraw(); //
                } else if (minTs === maxTs && total === 1) { //
                    // For a single bar, set a small fixed window around it for visibility
                    const pointTime = minTs; //
                    const barDuration = this.dataManager.msPerBar || 60000; //
                    const windowMin = pointTime - (barDuration * 5); //
                    // 5 bars before
                    const windowMax = pointTime + (barDuration * 5); //
                    // 5 bars after
                    this.chart.xAxis[0].setExtremes(windowMin, windowMax, true, false); //
                    // Set extremes without immediate redraw
                    this._announce(`Showing single data point.`); //
                } else { //
                    // Normal zoom: set extremes for the calculated range
                    this.chart.xAxis[0].setExtremes(minTs, maxTs, true, false); //
                    // Set extremes without immediate redraw
                    this._announce(`Chart zoomed to show most recent ${take} bars.`); //
                }
            } else { //
                this.log("Could not set initial zoom extremes (invalid timestamps/range). Defaulting."); //
                if (this.chart.series && this.chart.series.length > 0) this.chart.redraw(); // Fallback redraw
            }
        } else { //
            // If fewer than minPointsForZoom, show all available bars by resetting zoom
            this._announce(`Showing all ${total} available bars.`); //
            this.chart.xAxis[0].setExtremes(null, null, true, false); // Reset zoom to show all data
        }
    }

    /**
     * Handles incoming WebSocket messages from the server.
     * This method is the central dispatcher
     * for all WebSocket data, including initial batches, catch-up data, and live updates.
     * It updates the DataManager and triggers chart rendering/updates.
     * @param {object} msgEnvelope - The message envelope from the WebSocket.
     * @param {string} msgEnvelope.type - The type of message (e.g., 'data', 'update', 'error').
     * @param {string} [msgEnvelope.symbol] - The symbol the message pertains to.
     * @param {string} [msgEnvelope.timeframe] - The timeframe the message pertains to.
     * @param {object} msgEnvelope.payload - The message payload.
     */
    handleWebSocketMessage(msgEnvelope) {
        const { type, symbol, timeframe, payload } = msgEnvelope; //
        this.log(`Handling WS Message: Type=${type}, PayloadKeys=${payload ? Object.keys(payload).join(',') : 'N/A'}. InitialRendered: ${this.initialDataRendered}`); //
        // Ignore messages not intended for the currently active chart instance
        if (symbol && symbol !== this.params.symbol) { //
            this.log(`Ignoring message for different symbol: ${symbol}. Current: ${this.params.symbol}`); //
            return; //
        }
        if (timeframe && timeframe !== this.params.timeframe) { //
            this.log(`Ignoring message for different timeframe: ${timeframe}. Current: ${this.params.timeframe}`); //
            return; //
        }

        // Handle error messages from the server, rejecting the init promise if an error occurs during load
        if (type === 'error') { //
            const errorMsg = payload?.message || //
                'Unknown error from server.'; //
            this._error(`Server Error: ${errorMsg}`); //
            if (this.rejectCurrentInitPromise && !this.initialDataRendered) { //
                this._settleInitPromise(false, new Error(`Server error: ${errorMsg}`)); //
            }
            return; //
        }
        // Handle subscription confirmation messages from the server
        if (type === 'subscribed') { //
            this._announce(`Subscription to ${payload?.symbol || this.params.symbol} ${payload?.timeframe || this.params.timeframe} confirmed. Awaiting initial data...`); //
            return; //
        }
        // Handle general notice or retry messages from the server
        if (type === 'notice' || type === 'retry_notice') { //
            this._announce(payload?.message || 'Notice from server.'); //
            return; //
        }

        // Extract OHLC and Volume data arrays from payload
        const ohlcData = payload?.ohlc || //
            []; //
        const volumeData = payload?.volume || []; //

        // Handle initial data batch or catch-up batches
        if (type === 'data') { //
            if (payload?.initial_batch) { //
                this.log(`Processing initial_batch: ${ohlcData.length} bars. Status: "${payload.status_message || ''}"`); //
                this.dataManager.clear(); // Clear existing data for a fresh start of this chart instance

                // Add all bars from the initial batch to the DataManager
                if (ohlcData.length > 0) { //
                    ohlcData.forEach((barArray, i) => { //
                        const vol = volumeData[i]?.[1] ?? 0; //
                        const fullBarData = [...barArray, vol]; //
                        try {
                            this.dataManager.addBar(fullBarData, false); // Add without allowing updates for initial //
                                // batch
                        } catch (e) { //
                            this.log(`initial_batch: Skipping bar (addBar error: ${e.message}) TS: ${barArray[0]}`); //
                        }
                    }); //
                }

                const chartTitle = `${this.params.symbol} ${this.params.timeframe} @ ${this.params.provider}`; //
                let renderSuccess = false; //

                // FIX: Use `this.renderer.render()` with `updateExisting` flag.
                // This is the core change to fix freezing on chart switches by allowing Highcharts to update
                // existing data series instead of always destroying and recreating the entire chart.
                this.chart = this.renderer.render({ // ChartRenderer.render handles creation OR update
                    ohlc: this.dataManager.fullOhlc, //
                    volume: this.dataManager.fullVol, //
                    title: chartTitle //
                }, this.initialDataRendered); //
                // Pass initialDataRendered: if true, attempt update


                if (this.chart) { //
                    setChart(this.chart); //
                    // Store global reference to the chart instance for external tools
                    this.initialDataRendered = true; //
                    // Mark this controller's chart as initially rendered
                    this._applyInitialZoom(); //
                    // Apply initial zoom after data is in
                    renderSuccess = true; //
                } else { //
                    this._error("CRITICAL: ChartRenderer.render returned null for initial_batch. Chart not displayed."); //
                }

                // Settle the init promise based on rendering success
                if (renderSuccess) { //
                    const message = ohlcData.length > 0 ? //
                        `Chart loaded with ${ohlcData.length} initial bars.` : (payload.status_message || 'Chart loaded. No initial bars. Awaiting live updates.'); //
                    this._announce(message); //
                    if (this.dataManager.latestTs) { //
                        this._saveLatestTsToLocalStorage(); //
                    }
                    this._settleInitPromise(true, this.chart); //
                } else { //
                    this._settleInitPromise(false, new Error("Chart rendering failed for initial_batch.")); //
                }
            } else if (payload?.catch_up_batch) { //
                // This block handles catch-up data received after the initial batch (e.g., from reconnects)
                this.log(`Processing catch_up_batch: ${ohlcData.length} bars.`); //
                if (!this.initialDataRendered && !this.chart) { //
                    this.log("Warning: Received catch_up_batch before initial chart fully rendered. Data will be added to DataManager."); //
                }
                let newBarsAddedToDataManager = 0; //
                if (ohlcData.length > 0) { //
                    ohlcData.forEach((barArray, i) => { //
                        const vol = volumeData[i]?.[1] ?? 0; //
                        const fullBarData = [...barArray, vol]; //
                        try { //
                            const addedOrUpdated = this.dataManager.addBar(fullBarData, true); // Add bars, allowing updates
                            if (addedOrUpdated) newBarsAddedToDataManager++; //
                        } catch (e) { //
                            this.log(`catch_up_batch: Skipping bar (addBar error: ${e.message}) TS: ${barArray[0]}`) //
                        }
                    }); //
                }

                if (newBarsAddedToDataManager > 0) { //
                    // Update chart series for catch-up batch
                    if (this.chart && this.initialDataRendered) { //
                        this.log(`catch_up_batch: Refreshing chart data after ${newBarsAddedToDataManager} 
 bars added/updated.`); //
                        this.chart.get('ohlc')?.setData(this.dataManager.fullOhlc, false); //
                        this.chart.get('price-line')?.setData(this.dataManager.fullOhlc.map(b => [b[0], b[4]]), false); //
                        this.chart.get('vol')?.setData(this.dataManager.fullVol, this.isLiveView); //
                        // Redraw based on live view state
                    }
                    if (this.dataManager.latestTs) this._saveLatestTsToLocalStorage(); //
                    this._announce(`Chart updated with ${newBarsAddedToDataManager} catch-up bars.`); //
                } else { //
                    this._announce('No new bars in catch-up batch.'); //
                }
            } else { //
                // This branch handles 'data' messages that are neither initial_batch nor catch_up_batch.
                // For live updates, these should ideally come as 'update' type.
                this.log(`Received un-flagged 'data' message. Treating as live. Payload Preview: ${JSON.stringify(payload).substring(0, 100)}`); //
                if (ohlcData.length > 0) { //
                    ohlcData.forEach((ohlcBarArray, index) => { //
                        const volumeVal = volumeData[index]?.[1] ?? 0; //
                        const liveBarObject = { //
                            timestamp: ohlcBarArray[0], open: ohlcBarArray[1], high: ohlcBarArray[2], //
                            low: ohlcBarArray[3], close: ohlcBarArray[4], volume: volumeVal //
                        };
                        this.handleLiveBar(liveBarObject); //
                    }); //
                } else { //
                    this.log("Un-flagged 'data' message had empty ohlcData."); //
                }
            }
        } else if (type === 'update') { // Handles live bar updates from backend (e.g., new 1-minute bar or update to last one) //
            this.log(`Received 'update' message. Payload Preview: ${JSON.stringify(payload).substring(0, 100)}`); //
            if (ohlcData.length > 0) { //
                ohlcData.forEach((ohlcBarArray, index) => { //
                    const volumeVal = volumeData[index]?.[1] ?? 0; //
                    const liveBarObject = { //
                        timestamp: ohlcBarArray[0], open: ohlcBarArray[1], high: //
                            ohlcBarArray[2], //
                        low: ohlcBarArray[3], close: ohlcBarArray[4], volume: volumeVal //
                    };
                    this.handleLiveBar(liveBarObject); // Process each live bar
                }); //
            } else { //
                this.log("'update' message had empty ohlcData."); //
            }
        } else { //
            this.log(`Unhandled WebSocket message type: ${type}`); //
        }
    }

    /**
     * Processes a single live OHLCV bar (which could be a new bar or an update to the last bar).
     * It adds the bar to the DataManager and updates the corresponding chart series in Highcharts.
     * @param {object} barData - The bar data object {timestamp, open, high, low, close, volume}.
     */
    handleLiveBar(barData) {
        this.log(`handleLiveBar for TS: ${barData.timestamp}, initialDataRendered: ${this.initialDataRendered}`); //
        // Ensure initial data has been rendered before processing live updates to prevent issues during load
        if (!this.initialDataRendered) { //
            this.log("handleLiveBar: initialDataRendered is false. Ignoring live bar during initial load phase."); //
            return; //
        }
        // Ensure chart object exists before attempting to update it
        if (!this.chart) { //
            this.log("handleLiveBar: Chart object is null. Ignoring live bar."); //
            return; //
        }

        try {
            // Convert barData object to array format for DataManager
            const barArrayForDM = [ //
                +barData.timestamp, +barData.open, +barData.high, //
                +barData.low, +barData.close, +barData.volume || //
                0 //
            ];

            // Add/update bar in DataManager.
            // `true` allows updating the last bar if timestamps match.
            const updateType = this.dataManager.addBar(barArrayForDM, true); //

            const ts = +barData.timestamp; //
            // Data points for Highcharts series
            const ohlcPoint = [ts, +barData.open, +barData.high, +barData.low, +barData.close]; //
            const closePoint = [ts, +barData.close]; //
            const volPoint = [ts, +barData.volume || 0]; //
            // Get Highcharts series instances by their IDs
            const ohlcSeries = this.chart.get('ohlc'); //
            const priceLineSeries = this.chart.get('price-line'); //
            const volSeries = this.chart.get('vol'); //
            let needsRedraw = false; //
            if (updateType === 'updated') { //
                // If the bar updates an existing point (usually the last one)
                if (ohlcSeries?.data.length > 0) { //
                    const lastPt = ohlcSeries.data[ohlcSeries.data.length - 1]; //
                    if (lastPt.x === ts) lastPt.update(ohlcPoint, false); // Update last point
                    else ohlcSeries.addPoint(ohlcPoint, false, false, false); //
                    // Add if not last, but also not a truly new bar
                }
                if (priceLineSeries?.data.length > 0) { //
                    const lastPt = priceLineSeries.data[priceLineSeries.data.length - 1]; //
                    if (lastPt.x === ts) lastPt.update(closePoint, false); //
                    else priceLineSeries.addPoint(closePoint, false, false, false); //
                }
                if (volSeries?.data.length > 0) { //
                    const lastPt = volSeries.data[volSeries.data.length - 1]; //
                    if (lastPt.x === ts) lastPt.update(volPoint, false); //
                    else volSeries.addPoint(volPoint, false, false, false); //
                }
                needsRedraw = true; //
            } else if (updateType === 'added') { //
                // If a new bar is added (timestamp > latest known)
                const shift = (ohlcSeries?.data?.length || 0) > 2000; //
                // Shift oldest point off if series gets too long (e.g., > 2000 points)
                ohlcSeries?.addPoint(ohlcPoint, false, shift, false); //
                priceLineSeries?.addPoint(closePoint, false, shift, false); //
                volSeries?.addPoint(volPoint, false, shift, false); //
                needsRedraw = true; //
            } else { //
                this.log(`Live bar TS: ${barData.timestamp} was not processed by DataManager (updateType: ${updateType}). No chart update.`); //
                return; //
            }

            // Redraw the chart if updates were made and the chart is in live view mode
            if (this.isLiveView && needsRedraw) { //
                this.chart.redraw(); //
            }
            this._saveLatestTsToLocalStorage(); //
            // Save latest timestamp after a successful live update
        } catch (err) { //
            this.errorLog(`handleLiveBar error: ${err.message}`, err); //
        }
    }

    /**
     * Starts the WebSocket service to receive live data for the current chart.
     * This method also clears any existing HTTP polling fallback.
     * @param {number} [clientSince=0] - The timestamp (milliseconds) from which to request historical data
     * from the server (used in the initial subscription message).
     */
    startLive(clientSince = 0) {
        this.log(`startLive called. clientSince: ${clientSince === 0 ? 'Fresh (0)' : new Date(clientSince).toISOString()}`); //
        this.wsService?.stop(); // Stop any existing WS connection
        clearInterval(this.pollerId); //
        // Clear any existing HTTP poller interval
        this.pollerId = null; //
        const wsParams = { ...this.params, since: clientSince }; // Parameters for WebSocket connection URL

        try {
            // Instantiate and start WebSocketService
            this.wsService = new WebSocketService(wsParams, { //
                onOpen: (isReconnectAttempt) => { //
                    this._announce(`WebSocket connected${isReconnectAttempt ? ' (reconnected)' : ''}.`); //
                    this.log(`WebSocket onOpen event. Is Reconnect: ${isReconnectAttempt}.`); //
                    if (this.wsService) { //
                        // ***** THIS IS THE SECTION TO MODIFY *****
                        const subscribeMsg = {
                            action: "subscribe", // Changed from 'type' to 'action'
                            market: this.params.market, //
                            provider: this.params.provider, //
                            symbol: this.params.symbol, //
                            stream_type: "ohlcv", // Added stream_type for OHLCV data
                            timeframe: this.params.timeframe, //
                            since: clientSince // Send client's last known timestamp for historical catch-up
                        };
                        // ***** END OF MODIFICATION *****
                        this.wsService.sendMessage(subscribeMsg); //
                        this.log(`Sent subscribe message: ${JSON.stringify(subscribeMsg)}`); //
                    }
                    if (isReconnectAttempt) { //
                        this._announce('Reconnected. Fetching latest data...'); //
                    } else { //
                        this._announce('Connection established. Awaiting initial chart data...'); //
                    }
                },
                onError: e => { //
                    this._error(`WebSocket error: ${e.message || 'Connection problem.'}`); //
                    // Reject init promise if error occurs during initial load
                    if (this.rejectCurrentInitPromise && !this.initialDataRendered) { //
                        this._settleInitPromise(false, new Error(`WebSocket connection error: ${e.message}`)); //
                    }
                },
                onClose: (event) => { //
                    this._announce(`WebSocket disconnected (Code: ${event.code}).`); //
                    // Reject init promise if disconnected unexpectedly during initial load phase
                    if (this.rejectCurrentInitPromise && !this.initialDataRendered && event.code !== 1000 && event.code !== 1001) { //
                        this._settleInitPromise(false, new Error(`WebSocket disconnected unexpectedly during init. Code: ${event.code}`)); //
                    }
                },
                onFallback: () => { //
                    this._error('WebSocket connection failed permanently. Chart updates will stop.'); //
                    if (this.rejectCurrentInitPromise && !this.initialDataRendered) { //
                        this._settleInitPromise(false, new Error("WebSocket connection failed permanently, cannot load initial data.")); //
                    }
                },
                onMessage: (msgEnvelope) => this.handleWebSocketMessage(msgEnvelope), // Central message handler
                onRetryNotice: msg => this._announce(msg) // Display retry messages to UI
            });
            this.wsService.start(); // Initiate WebSocket connection attempt
        } catch (err) { //
            this._error(`Failed to setup WebSocket service: ${err.message}`); //
            this.errorLog("WS Setup Error:", err); //
            if (this.rejectCurrentInitPromise) { //
                this._settleInitPromise(false, new Error(`WebSocket setup failed: ${err.message}`)); //
            }
        }
    }

    /**
     * Handles pan events on the chart xAxis to trigger loading more historical data
     * when the user scrolls towards the left (older data).
     * This enables infinite scrolling for history.
     * @param {object} event - The Highcharts afterSetExtremes event object from xAxis.
     */
    handlePan(event) {
        if (!this.chart || !this.dataManager || this.isLoadingHist) { //
            if (this.isLoadingHist) this.log("Pan ignored: Already loading history."); //
            return; //
        }
        // If no data loaded yet, panning is meaningless
        if (this.dataManager.earliestTs === null && this.dataManager.fullOhlc.length === 0) { //
            this.log("Pan ignored: No data loaded yet to determine history range."); //
            return; //
        }

        const axis = event.target; //
        // The xAxis that triggered the event
        const extremes = axis.getExtremes(); //
        // Current visible extremes (min, max, dataMin, dataMax)
        
        // Ensure valid numeric extremes
        if (typeof extremes.min !== 'number' || typeof extremes.dataMin !== 'number') { //
            this.log("Pan ignored: Extremes not ready or not numbers."); //
            return; //
        }

        const currentViewRange = extremes.max - extremes.min; //
        // Trigger loading more history if the current view approaches the earliest loaded data
        // (e.g., left edge of view is within 30% of the entire view range from dataMin)
        const bufferToTriggerLoad = currentViewRange * 0.3; //
        const actualEarliestKnownToDataManager = this.dataManager.earliestTs; // Earliest timestamp in client-side data

        // If the left edge of the current visible window is close to the earliest data we have in DataManager
        if (extremes.min < (actualEarliestKnownToDataManager + bufferToTriggerLoad)) { //
            this.log(`Pan triggered history load. ViewMin: ${extremes.min}, DataMin: ${extremes.dataMin}, DM.earliestTs: ${actualEarliestKnownToDataManager}`); //
            this.isLoadingHist = true; // Set flag to prevent multiple concurrent loads
            this._announce('Loading older history…'); //
            // Load more history from the DataManager, which makes an HTTP request to the backend
            this.dataManager.loadMoreHistory() //
                .then(historicalData => { //
                    if (historicalData.ohlc.length > 0) { //
                        this.log(`Prepended ${historicalData.ohlc.length} bars from history load.`); //
                        // Update chart series with the new full dataset from DataManager
                        this.chart.get('ohlc')?.setData(this.dataManager.fullOhlc, false); //
                        this.chart.get('price-line')?.setData(this.dataManager.fullOhlc.map(b => [b[0], b[4]]), false); //
                        this.chart.get('vol')?.setData(this.dataManager.fullVol, false); // Redraw volume series

                        // Preserve current zoom level while extending the x-axis
                        const newChartExtremes = axis.getExtremes(); // Get new data boundaries after new data is added
                        const preservedMin = Math.max(extremes.min, newChartExtremes.dataMin); //
                        // Ensure view doesn't go beyond new dataMin
                        const preservedMax = preservedMin + (extremes.max - extremes.min); //
                        // Maintain the visible range
                        axis.setExtremes(preservedMin, preservedMax, true, false); //
                        // Set new extremes without immediate redraw
                        this._announce(`Loaded ${historicalData.ohlc.length} more historical bars.`); //
                    } else { //
                        this._announce('No more historical data available.'); //
                        if (this.chart.series[0]?.data.length > 0) this.chart.redraw(); // Redraw if no new data, but chart existed
                    }
                })
                .catch(err => { //
                    this._error(`Error loading history: ${err.message}`); //
                    if (this.chart?.series[0]?.data.length > 0) this.chart.redraw(); // Redraw chart on error
                })
                .finally(() => { //
                    this.isLoadingHist = false; // Reset loading flag
                });
        }
        // Determine if chart is currently in live view (panned to the rightmost/newest data)
        const dataMax = this.dataManager.latestTs ?? //
            extremes.dataMax ?? extremes.max; // Get the most recent known data point's timestamp
        this.isLiveView = extremes.max >= dataMax - (this.dataManager.msPerBar || 60000) * 0.5; //
        // Within half a bar of the latest data
        this.log(`Pan finished. isLiveView: ${this.isLiveView}`); //
    }

    /**
     * Starts HTTP polling for live updates as a fallback or alternative to WebSocket.
     * This method is intended for situations where WebSocket connection might be unstable or unavailable.
     * @param {number} [pollSince=0] - The timestamp (milliseconds) from which to start polling for new data.
     */
    startPolling(pollSince = 0) {
        if (this.pollerId !== null) { //
            this.log("Polling already active."); //
            return; //
        }
        const effectivePollSince = this.dataManager.latestTs || pollSince || 0; //
        if (!this.initialDataRendered && effectivePollSince === 0) { //
            this.log("Polling: Not starting as initial data was never rendered and no latestTs known."); //
            return; //
        }

        const intervalMs = Math.max(5000, Math.min(30000, (this.dataManager.msPerBar || 60000) / 2)); //
        // Poll faster for smaller timeframes
        this.log(`Starting HTTP polling every ${intervalMs / 1000}s, for data since ${effectivePollSince > 0 ? new Date(effectivePollSince).toISOString() : 'beginning (or latest if known)'}`); //
        const pollFn = async () => { //
            // Stop polling if there's no data to track updates from
            if (this.dataManager.latestTs === null && effectivePollSince === 0) { //
                this.log("Stopping polling: latest timestamp is null and no effective since."); //
                clearInterval(this.pollerId); //
                this.pollerId = null; //
                return; //
            }
            try {
                const sinceForPoll = this.dataManager.latestTs || //
                    effectivePollSince; //
                // Fetch a small number of recent bars (e.g., 5)
                const data = await fetchOhlcv({ ...this.params, since: sinceForPoll, limit: 5 }); //
                if (data.ohlc.length > 0) { //
                    const latestKnownTsBeforePoll = this.dataManager.latestTs; //
                    let processedNew = false; //
                    // Process each new bar, ensuring it's genuinely newer
                    data.ohlc.forEach((barDataArray, i) => { //
                        if (barDataArray[0] > (latestKnownTsBeforePoll || 0)) { // Only add if newer than what we last had
                            const barObject = { //
                                timestamp: barDataArray[0], open: barDataArray[1], high: barDataArray[2], //
                                low: barDataArray[3], close: barDataArray[4], //
                                volume: data.volume[i]?.[1] ?? 0 //
                            };
                            this.handleLiveBar(barObject); // Use handleLiveBar for processing and updating chart //
                            processedNew = true; //
                        }
                    }); //
                    if (processedNew) this.log(`Polling found and processed new bar(s).`); //
                }
            } catch (err) { //
                this.log(`Polling error: ${err.message}. Polling will continue.`); //
            }
        };
        pollFn(); //
        // Run immediately on start
        this.pollerId = setInterval(pollFn, intervalMs); //
        // Schedule recurring polls
    }

    /**
     * Destroys the ChartController instance, stopping all associated services
     * and ensuring the Highcharts chart object is properly destroyed.
     */
    destroy() {
        this.log("Destroying ChartController..."); //
        // If an init promise is pending, reject it as the controller is being destroyed
        if (this.rejectCurrentInitPromise) { //
            this._settleInitPromise(false, new Error("ChartController destroyed during initialization.")); //
        }
        this._clearActiveInitTimeout(); // Clear any pending init timeouts
        this.wsService?.stop(); //
        // Stop WebSocket service
        clearInterval(this.pollerId); //
        // Clear HTTP poller
        this.pollerId = null; //
        this.wsService = null; //
        // Clear WS service reference
        
        // Destroy the Highcharts instance if it exists
        if (this.chart) { //
            try { 
                this.chart.destroy(); //
            } catch (e) {  //
                this.errorLog("Error destroying chart:", e); //
            }
            this.chart = null; //
            // Clear chart reference
            setChart(null); //
            // Clear global chart reference managed by chartStore
        }
        this.log("ChartController destroyed."); //
    }

    /**
     * Helper to safely execute chart-related actions after ensuring chart readiness.
     * This prevents errors when trying to interact with a chart that hasn't fully loaded.
     * Displays an error message to the user if the chart or its data is not ready.
     * @param {function} fn - The function to execute if the chart is ready.
     * @private
     */
    _tap(fn) {
        if (!this.chart) { //
            this._error("Chart not ready. Please wait for data to load or refresh."); //
            this.log("_tap: Chart is null."); //
            return; //
        }
        const primarySeries = this.chart.get('ohlc') || this.chart.series[0]; //
        if (!this.initialDataRendered && (!primarySeries || primarySeries.data.length === 0)) { //
            this._error("Chart data not yet loaded. Please wait."); //
            this.log("_tap: Initial data not rendered and chart series is empty."); //
            return; //
        }
        try { fn(); } catch (err) { this._error(err.message); this.errorLog("_tap error:", err); } //
    }

    // Public methods for toolbar buttons (delegated to _tap for safety and logging)
    zoomIn() { this._tap(() => { this.log("ZoomIn called"); this._zoom('in'); }); } //
    zoomOut() { this._tap(() => { this.log("ZoomOut called"); this._zoom('out'); }); } //
    panLeft() { this._tap(() => { this.log("PanLeft called"); this._pan('left'); }); } //
    panRight() { this._tap(() => { this.log("PanRight called"); this._pan('right'); }); } //
    resetToLive() { this._tap(() => { this.log("ResetToLive called"); this._pan('reset'); }); } //


    /**
     * Internal method to handle chart zooming.
     * Adjusts the visible range of the xAxis based on the zoom direction.
     * @param {'in'|'out'} dir - Direction of zoom ('in' to zoom in, 'out' to zoom out).
     * @private
     */
    _zoom(dir) {
        this.log(`_zoom(${dir}) called.`); //
        const axis = this.chart.xAxis[0]; //
        const extremes = axis.getExtremes(); //
        const range = extremes.max - extremes.min; //
        if (range <= 0 && dir === 'in') { //
            this._announce("Cannot zoom in further on a zero or negative range."); //
            return; //
        }
        if (typeof extremes.dataMin !== 'number' || typeof extremes.dataMax !== 'number') { //
            this._announce("Cannot zoom: chart data boundaries are unclear."); //
            return; //
        }

        const newRangeFactor = dir === 'in' ? 0.7 : 1.3; //
        // Zoom in by 30%, zoom out by 30%
        let newRange = range * newRangeFactor; //
        const minSensibleRange = (this.dataManager.msPerBar || 60000) * 3; // Minimum range of 3 bars to avoid over-zooming

        if (dir === 'in' && newRange < minSensibleRange && range <= minSensibleRange) { //
            this._announce("Zoom level limit reached."); //
            return; //
        }
        newRange = Math.max(newRange, minSensibleRange); //
        // Ensure new range is at least minSensibleRange
        const maxDataRange = extremes.dataMax - extremes.dataMin; //
        // Total span of available data

        if (dir === 'out' && newRange >= maxDataRange && range >= maxDataRange ) { //
            if (extremes.min !== extremes.dataMin || extremes.max !== extremes.dataMax) { //
                axis.setExtremes(null, null, true, true); //
                // Full zoom out if not already at full extent
                this._announce("Zoomed out fully."); //
            } else { //
                this._announce("Already zoomed out fully."); //
            }
            return; //
        }
        newRange = Math.min(newRange, maxDataRange); //
        // Ensure new range doesn't exceed total data span

        const center = extremes.min + range / 2; //
        // Center of current view
        let newMin = center - newRange / 2; //
        let newMax = center + newRange / 2; //

        // Clamp new extremes to data boundaries to prevent empty space
        newMin = Math.max(extremes.dataMin, newMin); //
        newMax = Math.min(extremes.dataMax, newMax); //

        if (newMin >= newMax) { //
            if (dir === 'in') { //
                this._announce("Zoom level limit reached."); //
                return; //
            }
            // Fallback for pan out resulting in invalid range, stay put
            newMin = extremes.min; //
            newMax = extremes.max; //
        }
        axis.setExtremes(newMin, newMax, true, true); //
        // Set new extremes and trigger redraw
        this._announce(dir === 'in' ? 'Zoomed in.' : 'Zoomed out.'); //
    }

    /**
     * Internal method to handle chart panning (scrolling horizontally).
     * @param {'left'|'right'|'reset'} dir - Direction of pan ('left', 'right') or reset to live view ('reset').
     * @private
     */
    _pan(dir) {
        this.log(`_pan(${dir}) called.`); //
        const axis = this.chart.xAxis[0]; //
        const extremes = axis.getExtremes(); //
        const currentSpan = extremes.max - extremes.min; //
        // Current visible time range

        if (typeof extremes.dataMin !== 'number' || typeof extremes.dataMax !== 'number' || currentSpan <=0) { //
            this._announce("Cannot pan: chart data boundaries or current view are unclear."); //
            return; //
        }

        const moveAmount = currentSpan * 0.25; //
        // Pan by 25% of current visible range
        let newMin, newMax, announcementMsg; //
        if (dir === 'left') { //
            if (extremes.min <= extremes.dataMin) { // Already at the leftmost data
                this._announce("Already at the oldest data."); //
                return; //
            }
            newMin = Math.max(extremes.dataMin, extremes.min - moveAmount); //
            // Pan left, clamped by dataMin
            newMax = newMin + currentSpan; //
            // Maintain current visible span
            newMax = Math.min(newMax, extremes.dataMax); //
            // Ensure newMax doesn't go beyond dataMax
            // If we hit dataMin, adjust newMax to maintain span (or clip if newMax would exceed dataMax)
            if (newMin === extremes.dataMin) newMax = Math.min(extremes.dataMin + currentSpan, extremes.dataMax); //
            announcementMsg = 'Panned left.'; //
        } else if (dir === 'right') { //
            const latestDataPoint = this.dataManager.latestTs ?? //
                extremes.dataMax; // Use latest live TS or dataMax
            if (extremes.max >= latestDataPoint) { // Already at the rightmost data
                this._announce("Already at the newest data."); //
                return; //
            }
            newMax = Math.min(latestDataPoint, extremes.max + moveAmount); //
            // Pan right, clamped by latestDataPoint
            newMin = newMax - currentSpan; //
            // Maintain current visible span
            newMin = Math.max(newMin, extremes.dataMin); //
            // Ensure newMin doesn't go below dataMin
            // If we hit latestDataPoint, adjust newMin to maintain span (or clip if newMin would go below dataMin)
            if (newMax === latestDataPoint) newMin = Math.max(latestDataPoint - currentSpan, extremes.dataMin); //
            announcementMsg = 'Panned right.'; //
        } else if (dir === 'reset') { //
            const latestDataPoint = this.dataManager.latestTs; //
            if (latestDataPoint === null) { //
                this._announce('No live data available to reset to.'); //
                return; //
            }
            newMax = latestDataPoint; //
            // Set max to latest live data point
            newMin = Math.max(extremes.dataMin, latestDataPoint - currentSpan); //
            // Pan to show latest data, maintain span
            // If newMin hits dataMin, ensure newMax doesn't overshoot dataMax while maintaining span
            if (newMin === extremes.dataMin && (newMin + currentSpan > newMax) ){ //
                newMax = Math.min(newMin + currentSpan, extremes.dataMax); //
            }
            announcementMsg = 'Panned to live data.'; //
            this.isLiveView = true; // Set to live view mode
        } else { //
            return; //
            // Invalid pan direction
        }
        
        // Final validation of calculated range
        if (newMin >= newMax) { //
            this.log("Pan resulted in invalid range, not applying."); //
            this._announce("Could not pan further."); //
            return; //
        }

        axis.setExtremes(newMin, newMax, true, true); //
        // Apply new extremes and trigger redraw
        this._announce(announcementMsg); //
    }
}