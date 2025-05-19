// assets/js/modules/dataManager.js

import { fetchOhlcv } from './dataService.js'; // Used by loadMoreHistory

/**
 * DataManager handles client-side caching of OHLCV data and related state.
 * It's populated by ChartController from WebSocket messages for initial and live data,
 * and can fetch older historical data via HTTP for lazy loading.
 */
export default class DataManager {
    /**
     * @param {{ market:string, provider:string, symbol:string, timeframe:string }} params
     * @param {{ logFn?:function }} [opts]
     */
    constructor(params, { logFn = console.log } = {}) {
        this.params = params;
        this.log = (...args) => logFn('[DataManager]', ...args);

        // Calculate msPerBar from timeframe string
        try {
            const num = parseInt(params.timeframe.slice(0, -1), 10);
            const unit = params.timeframe.slice(-1).toLowerCase(); // Ensure unit is lowercase for map
            const unitMap = { m: 60000, h: 3600000, d: 86400000, w: 604800000, M: 2592000000 };
            if (isNaN(num) || !unitMap[unit]) {
                this.log(`Warning: Could not parse timeframe '${params.timeframe}' for msPerBar. Defaulting to 60000ms (1m).`);
                this.msPerBar = 60000;
            } else {
                this.msPerBar = num * unitMap[unit];
            }
        } catch (e) {
            this.log(`Error parsing timeframe '${params.timeframe}' for msPerBar. Defaulting. Error: ${e}`);
            this.msPerBar = 60000; // Default to 1 minute if parsing fails
        }
        
        // Page size for lazy loading older history via HTTP
        // This can be adjusted based on timeframe if desired
        this.historyPageSize = 200; // Number of bars to fetch per lazy load request

        // Internal state
        this.fullOhlc = []; // Array of [timestamp, open, high, low, close]
        this.fullVol = [];  // Array of [timestamp, volume]
        this.earliestTs = null; // Timestamp of the oldest bar currently held
        this.latestTs = null;   // Timestamp of the newest bar currently held
        this.isLoadingMoreHistory = false; // Flag for loadMoreHistory concurrency
    }

    /** * Clears all cached data and resets state.
     * Called by ChartController before processing an initial_batch from WebSocket.
     */
    clear() {
        this.log('Clearing all cached data and resetting state.');
        this.fullOhlc = [];
        this.fullVol = [];
        this.earliestTs = null;
        this.latestTs = null;
        this.isLoadingMoreHistory = false;
    }

    /**
     * Adds a new bar to the cached data. Updates latestTs.
     * Expects barData in [timestamp, open, high, low, close, volume] format.
     * Throws an error if the bar is not newer than the current latestTs.
     * Called by ChartController when new data arrives (initial, catch-up, or live).
     * @param {Array<number>} barDataArray - [timestamp, open, high, low, close, volume]
     */
    addBar(barDataArray) {
        const [ts, o, h, l, c, v = 0] = barDataArray; // Default volume to 0 if not provided

        if (
            typeof ts !== 'number' || typeof o !== 'number' || typeof h !== 'number' ||
            typeof l !== 'number' || typeof c !== 'number' || typeof v !== 'number'
        ) {
            this.log("Invalid bar data format passed to addBar:", barDataArray);
            throw new Error('Invalid bar data format for DataManager.addBar');
        }

        if (this.latestTs !== null && ts <= this.latestTs) {
            // Allow adding if it's the very first bar being added after a clear()
            if (!(this.fullOhlc.length === 0 && this.latestTs === null)) {
                 this.log(`Attempted to add bar with non-newer timestamp. Current latest: ${this.latestTs}, bar: ${ts}`);
                 throw new Error(`Bar timestamp ${ts} is not newer than latest known timestamp ${this.latestTs}`);
            }
        }

        this.fullOhlc.push([ts, o, h, l, c]);
        this.fullVol.push([ts, v]);
        
        if (this.earliestTs === null || ts < this.earliestTs) {
            this.earliestTs = ts;
        }
        this.latestTs = ts; // Always update latestTs to the timestamp of the bar just added

        // Optional: Prune very old data if fullOhlc grows too large (e.g., > 5000 points)
        // const MAX_POINTS = 5000;
        // if (this.fullOhlc.length > MAX_POINTS) {
        //     this.fullOhlc.splice(0, this.fullOhlc.length - MAX_POINTS);
        //     this.fullVol.splice(0, this.fullVol.length - MAX_POINTS);
        //     this.earliestTs = this.fullOhlc[0]?.[0] ?? null;
        // }
    }
    
    /**
     * Prepends a batch of historical bars. Used by loadMoreHistory.
     * Expects bars to be sorted oldest to newest.
     * @param {Array<Array<number>>} ohlcBars - Array of [ts,o,h,l,c]
     * @param {Array<Array<number>>} volumeBars - Array of [ts,v]
     */
    prependHistoricalBars(ohlcBars, volumeBars) {
        if (!ohlcBars || ohlcBars.length === 0) {
            return;
        }
        // Ensure data is sorted with oldest first if prepending
        ohlcBars.sort((a, b) => a[0] - b[0]);
        volumeBars.sort((a, b) => a[0] - b[0]);

        this.fullOhlc = ohlcBars.concat(this.fullOhlc);
        this.fullVol = volumeBars.concat(this.fullVol);
        
        this.earliestTs = this.fullOhlc[0]?.[0] ?? this.earliestTs; // Update earliestTs
        if (this.latestTs === null && this.fullOhlc.length > 0) { // If cache was empty
            this.latestTs = this.fullOhlc[this.fullOhlc.length -1][0];
        }
        this.log(`Prepended ${ohlcBars.length} historical bars. New earliestTs: ${this.earliestTs ? new Date(this.earliestTs).toISOString() : 'N/A'}`);
    }


    /**
     * Fetches one "page" of older historical data via HTTP (fetchOhlcv)
     * before the current `earliestTs`, prepends it, and updates `earliestTs`.
     * Called by ChartController's handlePan for lazy loading.
     */
    async loadMoreHistory() {
        if (this.isLoadingMoreHistory) {
            this.log('Already loading history, request ignored.');
            return { ohlc: [], volume: [] }; // Or throw error
        }
        if (this.earliestTs === null) {
            this.log('Cannot load more history: Initial data not yet available or earliestTs is null.');
            return { ohlc: [], volume: [] };
        }

        this.isLoadingMoreHistory = true;
        this.log(`Loading more history before ${new Date(this.earliestTs).toISOString()}`);

        const beforeTimestamp = this.earliestTs; // Fetch data strictly older than current earliest
        // Calculate a 'since' for this historical fetch to avoid fetching *all* history if DB is huge
        // This defines a window for the paged load.
        const sinceTimestamp = beforeTimestamp - (this.historyPageSize * this.msPerBar);

        try {
            // fetchOhlcv is an HTTP GET request
            const data = await fetchOhlcv({
                ...this.params,
                since: sinceTimestamp,
                before: beforeTimestamp, // Fetch data exclusively before this timestamp
                limit: this.historyPageSize
            });

            // Data from fetchOhlcv is { ohlc: [[ts,o,h,l,c],...], volume: [[ts,v],...] }
            const fetchedOhlc = data.ohlc || [];
            const fetchedVolume = data.volume || [];

            if (fetchedOhlc.length > 0) {
                this.prependHistoricalBars(fetchedOhlc, fetchedVolume);
            } else {
                this.log('No additional historical data received.');
            }
            return { ohlc: fetchedOhlc, volume: fetchedVolume }; // Return only the newly fetched chunk
        } catch (err) {
            this.log('Error in loadMoreHistory:', err);
            throw err; // Re-throw for ChartController to handle
        } finally {
            this.isLoadingMoreHistory = false;
        }
    }

    /**
     * NOTE: loadInitial() is no longer the primary method for initial chart display.
     * ChartController receives initial data via WebSocket and populates DataManager.
     * This method could be kept for other purposes or removed if not needed.
     * If kept, it should reflect its new role (e.g., generic historical fetch).
     */
    // async loadInitial(bootstrapSince = null) { ... } // Old implementation removed for clarity

}