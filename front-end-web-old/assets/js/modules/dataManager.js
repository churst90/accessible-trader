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

        try {
            const num = parseInt(params.timeframe.slice(0, -1), 10);
            const unit = params.timeframe.slice(-1).toLowerCase();
            const unitMap = { m: 60000, h: 3600000, d: 86400000, w: 604800000, M: 2592000000 }; // M for month approx
            if (isNaN(num) || !unitMap[unit]) {
                this.log(`Warning: Could not parse timeframe '${params.timeframe}' for msPerBar. Defaulting to 60000ms (1m).`);
                this.msPerBar = 60000;
            } else {
                this.msPerBar = num * unitMap[unit];
            }
        } catch (e) {
            this.log(`Error parsing timeframe '${params.timeframe}' for msPerBar. Defaulting. Error: ${e}`);
            this.msPerBar = 60000;
        }
        
        this.historyPageSize = 200; // Number of bars to fetch per historical chunk

        this.fullOhlc = [];
        this.fullVol = [];
        this.earliestTs = null;
        this.latestTs = null;
        this.isLoadingMoreHistory = false;
    }

    clear() {
        this.log('Clearing all cached data and resetting state.');
        this.fullOhlc = [];
        this.fullVol = [];
        this.earliestTs = null;
        this.latestTs = null;
        this.isLoadingMoreHistory = false;
    }

    /**
     * Adds or updates a bar in the cached data.
     * Expects barDataArray in [timestamp, open, high, low, close, volume] format.
     * @param {Array<number>} barDataArray - [timestamp, open, high, low, close, volume]
     * @param {boolean} allowUpdate - If true, and bar timestamp matches latestTs, updates the last bar.
     * @returns {string|null} 'added' if a new bar is appended, 
     * 'updated' if the latest bar is updated,
     * or null if no action was taken (e.g., duplicate timestamp and allowUpdate is false).
     * @throws {Error} if bar data is invalid or if adding an older bar when not expected.
     */
    addBar(barDataArray, allowUpdate = false) {
        const [ts, o, h, l, c, v = 0] = barDataArray;

        if (
            typeof ts !== 'number' || typeof o !== 'number' || typeof h !== 'number' ||
            typeof l !== 'number' || typeof c !== 'number' || typeof v !== 'number'
        ) {
            this.log("Invalid bar data format passed to addBar:", barDataArray);
            throw new Error('Invalid bar data format for DataManager.addBar');
        }

        // Case 1: This is the very first bar being added after a clear() or initial load
        if (this.latestTs === null) {
            this.fullOhlc.push([ts, o, h, l, c]);
            this.fullVol.push([ts, v]);
            this.earliestTs = ts;
            this.latestTs = ts;
            this.log(`Added first bar. TS: ${ts}`);
            return 'added';
        }

        // Case 2: Bar timestamp matches the latest known timestamp
        if (ts === this.latestTs) {
            if (allowUpdate) {
                if (this.fullOhlc.length > 0) {
                    // Update the last element
                    this.fullOhlc[this.fullOhlc.length - 1] = [ts, o, h, l, c];
                    this.fullVol[this.fullVol.length - 1] = [ts, v];
                    // earliestTs remains the same, latestTs is already correct
                    this.log(`Updated existing bar. TS: ${ts}`);
                    return 'updated';
                } else {
                    // This state (latestTs is set but fullOhlc is empty) should ideally not occur.
                    // However, to be robust, treat as adding the first bar.
                    this.log("Warning: latestTs is set but fullOhlc array is empty. Treating as new bar.");
                    this.fullOhlc.push([ts, o, h, l, c]);
                    this.fullVol.push([ts, v]);
                    if (this.earliestTs === null) this.earliestTs = ts; // Should already be set if latestTs was set
                    this.log(`Added bar (recovering from inconsistent state). TS: ${ts}`);
                    return 'added';
                }
            } else {
                this.log(`Bar with same timestamp ${ts} as latest, but update not allowed. No action taken.`);
                return null; // Explicitly return null if no action is taken
            }
        }

        // Case 3: Bar timestamp is newer than the latest known timestamp
        if (ts > this.latestTs) {
            this.fullOhlc.push([ts, o, h, l, c]);
            this.fullVol.push([ts, v]);
            // earliestTs remains the same
            this.latestTs = ts; // Update latestTs
            this.log(`Added new bar. TS: ${ts}`);
            return 'added';
        }

        // Case 4: Bar timestamp is older than the latest known timestamp (ts < this.latestTs)
        // This typically indicates an out-of-order bar or an issue with data feed.
        // For live updates, this is generally an error or should be ignored.
        // The original logic threw an error. Maintaining that for now.
        this.log(`Attempted to add bar with older timestamp. Current latest: ${this.latestTs}, bar: ${ts}. Throwing error.`);
        throw new Error(`Bar timestamp ${ts} is older than latest known timestamp ${this.latestTs}.`);
    }
    
    /**
     * Prepends historical OHLCV data to the beginning of the cached arrays.
     * @param {Array<Array<number>>} ohlcBars - Array of [ts,o,h,l,c]
     * @param {Array<Array<number>>} volumeBars - Array of [ts,v]
     */
    prependHistoricalBars(ohlcBars, volumeBars) {
        if (!ohlcBars || ohlcBars.length === 0) {
            this.log("prependHistoricalBars called with no OHLC data. No action taken.");
            return;
        }
        // Ensure data is sorted by timestamp, just in case
        ohlcBars.sort((a, b) => a[0] - b[0]);
        if (volumeBars && volumeBars.length > 0) {
            volumeBars.sort((a, b) => a[0] - b[0]);
        } else {
            volumeBars = []; // Ensure it's an array if null/undefined
        }

        // Filter out any bars that might already be covered by existing earliestTs
        const currentEarliest = this.earliestTs;
        if (currentEarliest !== null) {
            ohlcBars = ohlcBars.filter(bar => bar[0] < currentEarliest);
            volumeBars = volumeBars.filter(bar => bar[0] < currentEarliest);
        }
        
        if (ohlcBars.length === 0) {
            this.log("No new historical bars to prepend after filtering against earliestTs.");
            return;
        }

        this.fullOhlc = ohlcBars.concat(this.fullOhlc);
        this.fullVol = volumeBars.concat(this.fullVol); // Safe even if volumeBars is empty
        
        this.earliestTs = this.fullOhlc[0]?.[0] ?? this.earliestTs; // Update earliestTs to the new earliest
        if (this.latestTs === null && this.fullOhlc.length > 0) { // If latestTs wasn't set (e.g., empty cache before)
            this.latestTs = this.fullOhlc[this.fullOhlc.length -1][0];
        }
        this.log(`Prepended ${ohlcBars.length} historical bars. New earliestTs: ${this.earliestTs ? new Date(this.earliestTs).toISOString() : 'N/A'}`);
    }

    /**
     * Fetches older historical data from the API and prepends it.
     * @returns {Promise<{ohlc: Array<Array<number>>, volume: Array<Array<number>>}>} The newly fetched chunk.
     */
    async loadMoreHistory() {
        if (this.isLoadingMoreHistory) {
            this.log('Already loading history, request ignored.');
            return { ohlc: [], volume: [] };
        }
        if (this.earliestTs === null) {
            this.log('Cannot load more history: Initial data not yet available or earliestTs is null.');
            // This could happen if the chart was initialized without any data at all.
            return { ohlc: [], volume: [] };
        }

        this.isLoadingMoreHistory = true;
        this.log(`Loading more history before ${new Date(this.earliestTs).toISOString()}`);

        // Calculate 'since' and 'before' for the API request
        // We want data *before* the current earliestTs.
        const beforeTimestamp = this.earliestTs;
        // Calculate a 'since' that is 'historyPageSize' bars *before* 'beforeTimestamp'.
        // This is an approximation; the server will ultimately determine the exact bars.
        const sinceTimestamp = beforeTimestamp - (this.historyPageSize * this.msPerBar);

        try {
            // fetchOhlcv is an HTTP GET request defined in dataService.js
            const data = await fetchOhlcv({
                ...this.params,
                since: sinceTimestamp, // Request data from this point
                before: beforeTimestamp, // Up to (but not including) this point
                limit: this.historyPageSize // Server-side limit might also apply
            });

            const fetchedOhlc = data.ohlc || [];
            const fetchedVolume = data.volume || [];

            if (fetchedOhlc.length > 0) {
                this.prependHistoricalBars(fetchedOhlc, fetchedVolume);
            } else {
                this.log('No additional historical data received.');
            }
            return { ohlc: fetchedOhlc, volume: fetchedVolume };
        } catch (err) {
            this.log('Error in loadMoreHistory:', err);
            // Re-throw for ChartController to handle (e.g., display an error message)
            throw err;
        } finally {
            this.isLoadingMoreHistory = false;
        }
    }
}