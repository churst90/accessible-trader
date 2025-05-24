// assets/js/modules/chartRenderer.js

/**
 * A lightweight logging helper.
 */
function log(...args) {
    console.log('[ChartRenderer]', ...args);
}

export default class ChartRenderer {
    constructor(container, handlers = {}) {
        this.container = container;
        this.handlers = handlers; // { onPan, controller, onAnnounce }
        this.chart = null;
        this.state = {
            usingLog: false,
            usingHeikin: false
        };
    }

    /**
     * Completely (re)renders the chart with the given data.
     * @param {{ ohlc: Array, volume: Array, title: string }} data
     */
    render(data) {
        const H = window.Highcharts;
        if (!H) throw new Error('Highcharts not loaded');

        // Destroy existing chart if present
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }

        // Build config
        const cfg = {
            chart: this._buildChartOptions(),
            stockTools: { gui: { enabled: false } }, // Disable the default SVG toolbar
            title: { text: data.title },
            time: { useUTC: false },
            xAxis: this._buildXAxis(),
            yAxis: this._buildYAxes(),
            series: this._buildSeries(data),
            legend: { enabled: true, layout: 'horizontal', align: 'center', verticalAlign: 'bottom' },
            accessibility: {
                enabled: true,
                keyboardNavigation: {
                    enabled: true,
                    seriesNavigation: { mode: 'normal' }
                    // Removed toolbarNavigation since we're using a custom HTML toolbar
                }
            },
            rangeSelector: { enabled: false },
            navigator: { enabled: true },
            scrollbar: { enabled: false },
            plotOptions: { series: { dataGrouping: { enabled: false } } },
            tooltip: { formatter: this._tooltipFormatter.bind(this) }
        };

        // Instantiate the chart
        this.chart = H.stockChart(this.container, cfg);
        log('Chart instanced.');

        // Expose the chart globally for debugging in DevTools
        window.myChart = this.chart;

        // Keep reference for keyboard/tool shortcuts
        this.chart.__controller = this.handlers.controller;

        // Set accessibility attributes for the chart container
        this.container.setAttribute('tabindex', '0');
        this.container.setAttribute('role', 'region');
        this.container.setAttribute(
            'aria-label',
            (this.chart?.title?.textStr || '') + ' interactive chart'
        );
        this.container.focus();

        return this.chart;
    }

    toggleScale() {
        if (!this.chart) return;
        this.state.usingLog = !this.state.usingLog;
        this.chart.yAxis[0].update(
            { type: this.state.usingLog ? 'logarithmic' : 'linear' },
            true
        );
    }

    toggleCandle() {
        if (!this.chart) return;
        this.state.usingHeikin = !this.state.usingHeikin;
        this.chart.get('ohlc').update(
            { type: this.state.usingHeikin ? 'heikinashi' : 'candlestick' },
            true
        );
    }

    _buildChartOptions() {
        const bg = getComputedStyle(document.documentElement)
            .getPropertyValue('--card-bg')
            .trim();
        return {
            backgroundColor: bg,
            panning: { enabled: true, type: 'x' },
            panKey: 'shift',
            zoomType: null
        };
    }

    _buildXAxis() {
        return {
            ordinal: false,
            title: { text: 'Time' },
            labels: {
                formatter() {
                    return window.Highcharts.dateFormat('%Y-%m-%d %H:%M', this.value);
                }
            },
            tickPositioner: function () {
                const extremes = this.getExtremes();
                const min = extremes.min;
                const max = extremes.max;
                const data = this.series[0]?.xData || []; // Get timestamps from the first series (e.g., ohlc)

                // Filter data points within the visible range
                const visiblePoints = data.filter(x => x >= min && x <= max);

                if (visiblePoints.length <= 1) {
                    return [min, max]; // Fallback for very few points
                }

                // Include all visible data points as ticks to ensure no candles are omitted
                return visiblePoints.sort((a, b) => a - b);
            },
            events: { afterSetExtremes: e => this.handlers.onPan?.(e) }
        };
    }

    _buildYAxes() {
        return [
            { height: '60%', type: this.state.usingLog ? 'logarithmic' : 'linear', title: { text: 'Price' } },
            { top: '60%', height: '20%', offset: 0, title: { text: 'Volume' } },
            { top: '80%', height: '20%', offset: 0, title: { text: 'Oscillators' }, gridLineWidth: 1 }
        ];
    }

    _buildSeries({ ohlc, volume }) {
        const priceLine = ohlc.map(bar => [bar[0], bar[4]]);
        return [
            { id: 'price-line', name: 'Price', type: 'line', data: priceLine, yAxis: 0, zIndex: 1 },
            { 
                id: 'ohlc', 
                name: 'Candles', 
                type: 'candlestick', 
                data: ohlc, 
                yAxis: 0, 
                zIndex: 2, 
                accessibility: { enabled: true },
                pointWidth: 10, // Fixed width for candles in pixels
                pointPadding: 0.1, // Spacing between candles (relative to pointWidth)
                groupPadding: 0.2 // Spacing between groups of candles
            },
            { id: 'vol', name: 'Volume', type: 'column', data: volume, yAxis: 1, zIndex: 1 }
        ].filter(series => series.data && series.data.length > 0);
    }

    _tooltipFormatter() {
        const s = this.series;
        if (!s?.type) return '';
        if (s.type === 'candlestick') {
            return `<b>${s.name}</b><br/>O:${this.point.open} H:${this.point.high}<br/>
                    L:${this.point.low} C:${this.point.close}`;
        }
        if (s.type === 'column') {
            return `<b>${s.name}</b><br/>Vol: ${this.point.y}`;
        }
        return `<b>${s.name}</b><br/>Val: ${this.point.y}`;
    }
}