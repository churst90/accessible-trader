// assets/js/modules/chartRenderer.js

import { setChartInstance, getChartInstance } from './chartInstance.js';

/**
 * Render a Highcharts Stock chart with:
 *  - full accessibility (keyboard nav, screen-reader support)
 *  - three panes: Price, Volume, Oscillators
 *  - pan/zoom via Shift + mouse or keyboard
 *  - built-in stock tools for annotations & fullscreen
 *  - sonification on chart / series / points
 */
export function renderChart(
  container,
  { ohlc, volume, title, usingLog, usingHeikin },
  handlers
) {
  const H = window.Highcharts;

  // Destroy prior instance
  const old = getChartInstance();
  if (old) old.destroy();

  const priceLineData = ohlc.map(bar => [bar[0], bar[4]]);

  const cfg = {
    chart: {
      backgroundColor: getComputedStyle(document.documentElement)
        .getPropertyValue('--card-bg').trim(),
      panning: { enabled: true, type: 'x' },
      panKey: 'shift',
      zoomType: null,
      events: {
        load: function () {
          const svg = this.container;
          svg.tabIndex = 0;
          svg.setAttribute('role', 'region');
          svg.setAttribute('aria-label', `${title} interactive price & volume chart`);
          svg.focus();
          svg.addEventListener('keydown', e => {
            if (['=', '+', '-', '[', ']', '\\'].includes(e.key)) {
              e.preventDefault();
              handlers.onKeydown(e);
              svg.focus();
            }
          });
        }
      }
    },

    title: { text: title },

    legend: {
      enabled: true,
      align: 'right',
      verticalAlign: 'top',
      layout: 'vertical',
      itemTabIndex: 0
    },

    tooltip: {
      formatter: function () {
        const s = this.series;
        if (s.type === 'candlestick') {
          return `<b>${s.name}</b><br/>
                  Open: ${this.point.open}<br/>
                  High: ${this.point.high}<br/>
                  Low: ${this.point.low}<br/>
                  Close: ${this.point.close}`;
        }
        if (s.type === 'column') {
          return `<b>${s.name}</b><br/>Volume: ${this.point.y}`;
        }
        return `<b>${s.name}</b><br/>Value: ${this.point.y}`;
      }
    },

    time: { useUTC: false },

    accessibility: {
      enabled: true,
      screenReaderSection: {
        beforeChartFormat:
          '<h2>{chartTitle}</h2><p>Interactive price & volume chart.</p>',
        afterChartFormat:
          "<p>Use Tab to focus toolbar & chart; arrows to move points; '=', '-' to zoom; '[' , ']' to pan; '\\\\' to reset.</p>"
      },
      keyboardNavigation: {
        enabled: true,
        seriesNavigation: { mode: 'serialize', wrapAround: false },
        axisNavigation: { enabled: true, mode: 'normal', wrapAround: false }
      },
      pointDescriptionFormatter: function (point) {
        const dt = H.dateFormat('%A, %b %e %Y %H:%M', point.x);
        if (point.series.type === 'candlestick') {
          return `On ${dt}, ${point.series.name}: open ${point.open}, high ${point.high}, low ${point.low}, close ${point.close}.`;
        }
        return `On ${dt}, ${point.series.name}: value ${point.y}.`;
      },
      series: { describeSingleSeries: true }
    },

    rangeSelector: { enabled: false },
    navigator: { enabled: true },
    scrollbar: { enabled: false },

    xAxis: {
      ordinal: false,
      title: { text: 'Time' },
      labels: {
        formatter: function () {
          return H.dateFormat('%Y-%m-%d %H:%M', this.value);
        }
      },
      events: { afterSetExtremes: handlers.onPan }
    },

    yAxis: [
      {
        height: '60%',
        type: usingLog ? 'logarithmic' : 'linear',
        title: { text: 'Price' }
      },
      {
        top: '60%',
        height: '20%',
        offset: 0,
        title: { text: 'Volume' }
      },
      {
        top: '80%',
        height: '20%',
        offset: 0,
        title: { text: 'Oscillators' },
        gridLineWidth: 1
      }
    ],

    plotOptions: {
      series: {
        dataGrouping: { enabled: false },
        accessibility: { enabled: true },
        marker: { enabled: true, radius: 3 }
      }
    },

    series: [
      {
        id: 'price-line',
        name: 'Price',
        type: 'line',
        data: priceLineData,
        marker: { enabled: true, radius: 3 },
        yAxis: 0,
        accessibility: { enabled: true }
      },
      {
        id: 'ohlc',
        name: 'Candles',
        type: usingHeikin ? 'heikinashi' : 'candlestick',
        data: ohlc,
        upColor: 'lime',
        color: 'red',
        lineColor: 'white',
        wickColor: 'white',
        yAxis: 0,
        accessibility: { enabled: true }
      },
      {
        id: 'vol',
        name: 'Volume',
        type: 'column',
        data: volume,
        yAxis: 1,
        accessibility: { enabled: true }
      }
    ],

    stockTools: {
      gui: {
        enabled: true,
        buttons: ['toggleAnnotations', 'fullScreen']
      }
    },

    navigation: {
      bindings: H.stockToolsBindings
    }
  };

  const chart = H.stockChart(container, cfg);
  setChartInstance(chart);
  return chart;
}

/** Toggle linear/log on yAxis 0 */
export function toggleScale(chart, usingLog) {
  chart.yAxis[0].update(
    { type: usingLog ? 'logarithmic' : 'linear' },
    true
  );
}

/** Toggle Candle type on series “ohlc” */
export function toggleCandle(chart, usingHeikin) {
  chart.get('ohlc').update(
    { type: usingHeikin ? 'heikinashi' : 'candlestick' },
    true
  );
}
