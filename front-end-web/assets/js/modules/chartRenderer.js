// /assets/js/modules/chartRenderer.js

import { setChartInstance, getChartInstance } from './chartInstance.js';

/**
 * Render a Highcharts Stock chart with:
 *  - delegated keyboard handling
 *  - delegated pan/zoom callbacks
 *  - full accessibility support
 *
 * @param container HTMLElement
 * @param { ohlc, volume, title, usingLog, usingHeikin } cfg
 * @param { onPan(extremes), onKeydown(event) } handlers
 * @returns Highcharts.Chart
 */
export function renderChart(container, { ohlc, volume, title, usingLog, usingHeikin }, handlers) {
  const H = window.Highcharts;

  // destroy any existing instance
  const old = getChartInstance();
  if (old) {
    old.destroy();
  }

  const cfg = {
    chart: {
      backgroundColor: getComputedStyle(document.documentElement)
                            .getPropertyValue('--card-bg').trim(),
      panning:  { enabled: true, type: 'x' },
      panKey:   'shift',
      zoomType: null,
      events: {
        load: function() {
          const chart = this;
          const cont  = chart.container;

          // focusable + ARIA
          cont.tabIndex = 0;
          cont.setAttribute('role', 'region');
          cont.setAttribute('aria-label', `${title} interactive price & volume chart`);
          cont.focus();

          // delegate keyboard
          cont.addEventListener('keydown', handlers.onKeydown);
        }
      }
    },

    // Chart title
    title: {
      text: title
    },

    // Legend in top-right
    legend: {
      enabled: true,
      align: 'right',
      verticalAlign: 'top',
      layout: 'vertical'
    },

    // Custom tooltip showing full OHLC or volume
    tooltip: {
      formatter: function() {
        if (this.series.type === 'candlestick') {
          return `<b>${this.series.name}</b><br/>
                  Open: ${this.point.open}<br/>
                  High: ${this.point.high}<br/>
                  Low: ${this.point.low}<br/>
                  Close: ${this.point.close}`;
        } else if (this.series.type === 'column') {
          return `<b>${this.series.name}</b><br/>Volume: ${this.point.y}`;
        }
        return false;
      }
    },

    time: { useUTC: false },

    boost: {
      useGPUTranslations: true,
      seriesThreshold:    100
    },

    exporting: {
      enabled: true,
      buttons: {
        contextButton: {
          text: '?',
          _titleKey: 'contextButtonTitle',
          menuItems: [
            'viewFullscreen','printChart','separator',
            'downloadPNG','downloadSVG','downloadPDF',
            'separator','viewData'
          ]
        }
      }
    },

    lang: {
      contextButtonTitle: 'Chart menu'
    },

    accessibility: {
      enabled: true,
      screenReaderSection: {
        beforeChartFormat:
          '<h2>{chartTitle}</h2><p>Interactive price & volume chart.</p>',
        afterChartFormat:
          "<p>Use Tab to focus points, arrow keys to navigate, '=', '-' to zoom, '[' , ']' to pan, '\\' to reset.</p>"
      },
      keyboardNavigation: {
        enabled: true,
        seriesNavigation: { mode: 'serialize' }
      },
      // Read full OHLC or volume to screen readers
      pointDescriptionFormatter: function(point) {
        if (point.series.type === 'candlestick') {
          return `On ${H.dateFormat('%A, %b %e %Y %H:%M', point.x)}, `
               + `${point.series.name}: open ${point.open}, high ${point.high}, `
               + `low ${point.low}, close ${point.close}.`;
        }
        if (point.series.type === 'column') {
          return `On ${H.dateFormat('%A, %b %e %Y %H:%M', point.x)}, `
               + `${point.series.name} volume was ${point.y}.`;
        }
        return '';
      },
      series: { describeSingleSeries: true }
    },

    rangeSelector: { enabled: false },
    navigator:     { enabled: true },
    scrollbar:     { enabled: false },

    xAxis: {
      ordinal: false,
      minRange: 3600 * 1000,
      // X-axis title + date/time formatting
      title: { text: 'Time' },
      labels: {
        formatter: function() {
          return H.dateFormat('%Y-%m-%d %H:%M', this.value);
        }
      },
      events: {
        afterSetExtremes: handlers.onPan
      }
    },

    yAxis: [
      {
        // Price axis
        type: usingLog ? 'logarithmic' : 'linear',
        height: '70%',
        title: { text: 'Price' },
        labels: {
          style: {
            color: getComputedStyle(document.documentElement)
                         .getPropertyValue('--text-color').trim()
          }
        }
      },
      {
        // Volume axis
        top:    '75%',
        height: '25%',
        offset: 0,
        title: { text: 'Volume' },
        labels: {
          style: {
            color: getComputedStyle(document.documentElement)
                         .getPropertyValue('--text-color').trim()
          }
        }
      }
    ],

    plotOptions: {
      series: {
        dataGrouping: { enabled: false }
      }
    },

    series: [
      {
        id:   'ohlc',
        name: `${title} price`,
        type: usingHeikin ? 'heikinashi' : 'candlestick',
        data: ohlc,
        // High-contrast green/red + white wicks/borders
        upColor:   'lime',
        color:     'red',
        lineColor: 'white',
        wickColor: 'white'
      },
      {
        id:   'vol',
        name: `${title} volume`,
        type: 'column',
        yAxis: 1,
        data: volume
      }
    ]
  };

  const chart = H.stockChart(container, cfg);
  setChartInstance(chart);
  return chart;
}

export function toggleScale(chart, usingLog) {
  chart.yAxis[0].update({ type: usingLog ? 'logarithmic' : 'linear' }, true);
}

export function toggleCandle(chart, usingHeikin) {
  chart.series[0].update({ type: usingHeikin ? 'heikinashi' : 'candlestick' }, true);
}
