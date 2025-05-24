// assets/js/modules/chartRenderer.js

/**
 * A lightweight logging helper.
 * @param {...any} args - Arguments to log.
 */
function log(...args) {
    console.log('[ChartRenderer]', ...args);
}

export default class ChartRenderer {
    /**
     * Manages the rendering and updating of the Highcharts chart instance.
     * It handles the creation of a new chart or updating an existing one based on data.
     * @param {HTMLElement} container - The DOM element where the Highcharts chart will be rendered.
     * @param {object} handlers - An object containing callback handlers (e.g., onPan, onAnnounce).
     */
    constructor(container, handlers = {}) {
        this.container = container;
        this.handlers = handlers; // { onPan, controller, onAnnounce }
        this.chart = null; // Highcharts.Chart instance managed by this renderer
        this.state = {
            usingLog: false, // Tracks if logarithmic scale is active
            usingHeikin: false // Tracks if Heikin Ashi candles are active
        };
        log('ChartRenderer instantiated.');
    }

    /**
     * Renders or updates the chart with the given data.
     * If this renderer instance already has a `chart` object, it attempts to update its data series.
     * Otherwise, it creates a new Highcharts StockChart. This prevents costly full chart recreations.
     * @param {{ ohlc: Array<Array<number>>, volume: Array<Array<number>>, title: string }} data - The OHLCV data and chart title.
     * @param {boolean} [updateExisting=false] - If true, it explicitly signals an attempt to update the existing chart instance.
     * This flag is used by the calling ChartController to optimize re-renders.
     * @returns {Highcharts.Chart|null} The Highcharts chart instance, or null if rendering/updating failed.
     */
    render(data, updateExisting = false) {
        const H = window.Highcharts;
        if (!H) {
            console.error('[ChartRenderer] Highcharts not loaded. Cannot render chart.');
            throw new Error('Highcharts not loaded');
        }

        // --- If chart already exists and we are asked to update it ---
        // This path is taken when ChartController calls render with `updateExisting = true`.
        if (this.chart && updateExisting) {
            log('Updating existing chart instance with new data.');
            try {
                this.chart.setTitle({ text: data.title }); // Update chart title
                // Update each series with new data. `false` prevents immediate redraw.
                this.chart.get('ohlc')?.setData(data.ohlc, false);
                this.chart.get('price-line')?.setData(data.ohlc.map(b => [b[0], b[4]]), false);
                this.chart.get('vol')?.setData(data.volume, true); // `true` redraws the chart after this series update
                return this.chart; // Return the updated chart instance
            } catch (e) {
                console.error('[ChartRenderer] Error updating existing chart. Attempting full re-render as fallback:', e);
                // If updating fails, destroy the chart and fall through to re-creation
                this.chart.destroy();
                this.chart = null;
            }
        }

        // --- Create a new chart if no existing chart or if updating failed ---
        // This path is taken on initial chart load or if an update failed.
        if (!this.chart) { // Only create if no chart instance currently exists
            log('Creating new Highcharts StockChart instance.');
            const cfg = {
                chart: this._buildChartOptions(), // Basic chart options (background, panning)
                stockTools: { gui: { enabled: false } }, // Disable default Highcharts StockTools UI
                title: { text: data.title }, // Chart title
                time: { useUTC: false }, // Important for timestamp handling (milliseconds since epoch)
                xAxis: this._buildXAxis(), // X-axis configuration
                yAxis: this._buildYAxes(), // Y-axes configuration (price, volume, oscillators)
                series: this._buildSeries(data), // Data series (OHLC, price line, volume)
                legend: { enabled: true, layout: 'horizontal', align: 'center', verticalAlign: 'bottom' },
                accessibility: { // Accessibility features for screen readers
                    enabled: true,
                    keyboardNavigation: {
                        enabled: true,
                        seriesNavigation: { mode: 'normal' }
                    }
                },
                rangeSelector: { enabled: false }, // Disable default range selector
                navigator: { enabled: true }, // Enable navigator (mini chart at bottom)
                scrollbar: { enabled: false }, // Disable default scrollbar (navigator serves this purpose)
                plotOptions: { series: { dataGrouping: { enabled: false } } }, // Disable default data grouping by Highcharts
                tooltip: { formatter: this._tooltipFormatter.bind(this) } // Custom tooltip formatter
            };

            try {
                // Instantiate the Highcharts StockChart
                this.chart = H.stockChart(this.container, cfg);
                log('Highcharts chart instance created successfully.');
                
                // Expose the chart globally for debugging in DevTools (optional)
                window.myChart = this.chart;

                // Keep reference to ChartController for keyboard shortcuts / tool interactions
                this.chart.__controller = this.handlers.controller;

                // Set accessibility attributes for the chart container for better UX
                this.container.setAttribute('tabindex', '0');
                this.container.setAttribute('role', 'region');
                this.container.setAttribute(
                    'aria-label',
                    (this.chart?.title?.textStr || '') + ' interactive chart'
                );
                this.container.focus(); // Focus the chart for keyboard navigation

                return this.chart; // Return the newly created chart instance
            } catch (e) {
                console.error('[ChartRenderer] Error creating new chart instance:', e);
                this.chart = null; // Ensure `chart` is null on creation failure
                return null;
            }
        }
        // If this point is reached, it means this.chart already existed and was updated successfully.
        // It shouldn't fall through to here if updateExisting was true and successful.
        return this.chart; // Should only return if updateExisting was true and successful, or new chart was created.
    }

    /**
     * Toggles between linear and logarithmic y-axis scale.
     */
    toggleScale() {
        if (!this.chart) { log("toggleScale: Chart not ready."); return; }
        this.state.usingLog = !this.state.usingLog;
        this.chart.yAxis[0].update(
            { type: this.state.usingLog ? 'logarithmic' : 'linear' },
            true // Redraw the chart immediately
        );
        log(`Scale set to: ${this.state.usingLog ? 'Logarithmic' : 'Linear'}`);
    }

    /**
     * Toggles between standard candlestick and Heikin Ashi chart types.
     */
    toggleCandle() {
        if (!this.chart) { log("toggleCandle: Chart not ready."); return; }
        this.state.usingHeikin = !this.state.usingHeikin;
        // Update the main OHLC series type
        this.chart.get('ohlc').update(
            { type: this.state.usingHeikin ? 'heikinashi' : 'candlestick' },
            true // Redraw the chart immediately
        );
        log(`Candle type set to: ${this.state.usingHeikin ? 'Heikin Ashi' : 'Candlestick'}`);
    }

    /**
     * Builds basic chart options for Highcharts.
     * @returns {Highcharts.ChartOptions} Chart configuration object.
     * @private
     */
    _buildChartOptions() {
        // Get background color from CSS variable for theme integration
        const bg = getComputedStyle(document.documentElement)
            .getPropertyValue('--card-bg')
            .trim();
        return {
            backgroundColor: bg,
            panning: { enabled: true, type: 'x' }, // Enable panning along the x-axis
            panKey: 'shift', // Use Shift key for panning by default
            zoomType: null // Disable rectangular zoom
        };
    }

    /**
     * Builds x-axis configuration for Highcharts.
     * @returns {Highcharts.XAxisOptions} X-axis configuration object.
     * @private
     */
    _buildXAxis() {
        return {
            ordinal: false, // Treat x-axis as linear time, not ordinal categories
            title: { text: 'Time' },
            labels: {
                // Formatter for x-axis labels to display date and time
                formatter() {
                    return window.Highcharts.dateFormat('%Y-%m-%d %H:%M', this.value);
                }
            },
            tickPositioner: function () { // Custom tick positioner to show all available data points
                const extremes = this.getExtremes(); // Current visible extremes
                const min = extremes.min;
                const max = extremes.max;
                const data = this.series[0]?.xData || []; // Get timestamps from the first series (e.g., ohlc)

                // Filter data points within the visible range to use as tick positions
                const visiblePoints = data.filter(x => x >= min && x <= max);

                if (visiblePoints.length <= 1) {
                    return [min, max]; // Fallback for very few points, show min/max extremes
                }

                // Return all visible data points as ticks to ensure no candles are omitted
                return visiblePoints.sort((a, b) => a - b);
            },
            events: {
                // Event handler for afterSetExtremes, used to trigger historical data loading on pan
                afterSetExtremes: e => {
                    if (this.handlers.onPan) {
                        this.handlers.onPan(e);
                    } else {
                        log("onPan handler not set for xAxis events.");
                    }
                }
            }
        };
    }

    /**
     * Builds y-axes configuration for Highcharts.
     * @returns {Array<Highcharts.YAxisOptions>} Array of Y-axis configuration objects (price, volume, oscillators).
     * @private
     */
    _buildYAxes() {
        return [
            {
                height: '60%', // Price axis takes 60% of chart height
                type: this.state.usingLog ? 'logarithmic' : 'linear', // Log or linear scale
                title: { text: 'Price' },
                resize: { enabled: true } // Allow resizing this axis (e.g., dragging separator)
            },
            {
                top: '60%', // Volume axis starts below price axis
                height: '20%', // Volume axis takes 20%
                offset: 0, // No horizontal offset
                title: { text: 'Volume' },
                resize: { enabled: true }
            },
            {
                top: '80%', // Oscillators axis starts below volume axis
                height: '20%', // Oscillators axis takes 20%
                offset: 0,
                title: { text: 'Oscillators' },
                gridLineWidth: 1, // Grid line at top
                resize: { enabled: true }
            }
        ];
    }

    /**
     * Builds data series configuration for Highcharts.
     * @param {{ ohlc: Array<Array<number>>, volume: Array<Array<number>> }} data - Initial OHLC and volume data.
     * @returns {Array<Highcharts.SeriesOptionsType>} Array of series configuration objects.
     * @private
     */
    _buildSeries({ ohlc, volume }) {
        // Create a separate line series for price, often used for indicators or simpler view
        const priceLine = ohlc.map(bar => [bar[0], bar[4]]); // [timestamp, close]
        return [
            { id: 'price-line', name: 'Price', type: 'line', data: priceLine, yAxis: 0, zIndex: 1 },
            {
                id: 'ohlc', // ID for easy access later (e.g., chart.get('ohlc'))
                name: 'Candles',
                type: 'candlestick', // Default to candlestick type
                data: ohlc, // Initial OHLC data
                yAxis: 0, // Bind to price axis
                zIndex: 2, // Render above price line
                accessibility: { enabled: true },
                pointWidth: 10, // Fixed width for candles in pixels
                pointPadding: 0.1, // Spacing between candles (relative to pointWidth)
                groupPadding: 0.2 // Spacing between groups of candles
            },
            { id: 'vol', name: 'Volume', type: 'column', data: volume, yAxis: 1, zIndex: 1 } // Volume series
        ].filter(series => series.data && series.data.length > 0); // Filter out series with no data
    }

    /**
     * Custom formatter for the chart's tooltip.
     * @returns {string} The formatted tooltip HTML.
     * @private
     */
    _tooltipFormatter() {
        const s = this.series;
        if (!s?.type) return ''; // Ensure series type exists
        // Format tooltip content based on series type
        if (s.type === 'candlestick') {
            return `<b>${s.name}</b><br/>O:${this.point.open} H:${this.point.high}<br/>L:${this.point.low} C:${this.point.close}`;
        }
        if (s.type === 'column') {
            return `<b>${s.name}</b><br/>Vol: ${this.point.y}`;
        }
        return `<b>${s.name}</b><br/>Val: ${this.point.y}`;
    }
}