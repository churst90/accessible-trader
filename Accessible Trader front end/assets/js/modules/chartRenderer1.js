// assets/js/modules/chartRenderer.js

import { setChartInstance, getChartInstance } from './chartInstance.js';

/**
 * Render a Highcharts Stock chart with:
 *  - keyboard zoom: = / -
 *  - keyboard pan: [ / ]
 *  - reset to live: \
 *  - mouse panning (shift+drag)
 *  - full point-by-point arrow-key navigation
 *  - labeled export menu
 */
export function renderChart(container, { ohlc, volume, title, usingLog, usingHeikin }, afterExt) {
  const H = window.Highcharts;
  const announceEl = document.getElementById('chartStatus');

  // destroy any existing instance
  const old = getChartInstance();
  if (old) old.destroy();

  const cfg = {
    chart: {
      backgroundColor: getComputedStyle(document.documentElement)
                           .getPropertyValue('--card-bg').trim(),
      // allow shift-drag panning
      panning:    { enabled: true, type: 'x' },
      panKey:     'shift',
      zoomType:   null,
      events: {
        load: function() {
          const chart = this;
          const cont  = chart.container;

          // Make the container focusable and ARIA-labelled
          cont.tabIndex = 0;
          cont.setAttribute('role', 'region');
          cont.setAttribute('aria-label', `${title} interactive price & volume chart`);

          // Figure out one “bar width” in ms
          let barWidth = null;
          const pts = chart.series[0].data;
          if (pts.length > 1) {
            barWidth = pts[1].x - pts[0].x;
          }

          cont.addEventListener('keydown', e => {
            const axis = chart.xAxis[0];
            const ex   = axis.getExtremes();
            const { min, max, dataMin, dataMax } = ex;
            const span = max - min;
            let   newMin = min, newMax = max, msg;

            switch (e.key) {
              // ZOOM IN: = or +
              case '=':
              case '+': {
                const inView = pts.filter(p => p.x >= min && p.x <= max);
                if (inView.length > 2) {
                  newMin = inView[1].x;
                  newMax = inView[inView.length - 2].x;
                  msg    = `Showing ${inView.length - 2} bars`;
                } else {
                  return;
                }
                break;
              }

              // ZOOM OUT: -
              case '-': {
                if (!barWidth) return;
                newMin = Math.max(dataMin, min - barWidth);
                newMax = Math.min(dataMax, max + barWidth);
                const count = pts.filter(p => p.x >= newMin && p.x <= newMax).length;
                msg = `Showing ${count} bars`;
                break;
              }

              // PAN LEFT: [
              case '[': {
                if (!barWidth) return;
                newMin = min - span * 0.25;
                newMax = max - span * 0.25;
                if (newMin < dataMin) {
                  // lazy-load older bars if we crossed minTs
                  afterExt({ min: newMin });
                }
                const count = pts.filter(p => p.x >= newMin && p.x <= newMax).length;
                const s = H.dateFormat('%b %e %Y %H:%M', newMin);
                const e = H.dateFormat('%b %e %Y %H:%M', newMax);
                msg = `Now viewing ${count} bars from ${s} to ${e}`;
                break;
              }

              // PAN RIGHT: ]
              case ']': {
                // if we're already at or past live edge, just announce and bail
                if (max >= dataMax) {
                  msg = 'No newer bars';
                  // announce immediately, then return without calling setExtremes
                  if (announceEl) {
                    announceEl.textContent = '';
                    setTimeout(() => announceEl.textContent = msg, 50);
                  }
                  e.preventDefault();
                  return;
                }
                if (!barWidth) return;
                newMin = min + span * 0.25;
                newMax = max + span * 0.25;
                if (newMax > dataMax) newMax = dataMax;
                const countR = pts.filter(p => p.x >= newMin && p.x <= newMax).length;
                const sR = H.dateFormat('%b %e %Y %H:%M', newMin);
                const eR = H.dateFormat('%b %e %Y %H:%M', newMax);
                msg = `Now viewing ${countR} bars from ${sR} to ${eR}`;
                break;
              }

              // RESET TO LIVE EDGE: \
              case '\\': {
                newMax = dataMax;
                newMin = dataMax - span;
                const count = pts.filter(p => p.x >= newMin && p.x <= newMax).length;
                msg = `Showing latest ${count} bars`;
                break;
              }

              default:
                // allow other keys (e.g. arrow keys) to fall back to Highcharts’ own nav
                return;
            }

            // apply the new extremes
            axis.setExtremes(newMin, newMax, true, false);

            // announce
            if (announceEl && msg) {
              announceEl.textContent = '';
              setTimeout(() => announceEl.textContent = msg, 50);
            }

            e.preventDefault();
          });
        }
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
          // give the “hamburger” an accessible label
          text: '?',
          _titleKey: 'contextButtonTitle',
          menuItems: [
            'viewFullscreen',
            'printChart',
            'separator',
            'downloadPNG',
            'downloadSVG',
            'downloadPDF',
            'separator',
            'viewData'
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
          '<p>Use Tab to focus points, arrow keys to navigate, ‘=’/‘-’ to zoom, ‘[’/‘]’ to pan, ‘\\’ to reset.</p>'
      },
      keyboardNavigation: {
        enabled: true,
        seriesNavigation: { mode: 'serialize' }
      },
      pointDescriptionFormatter: point =>
        `On ${H.dateFormat('%A, %b %e %Y %H:%M', point.x)}, ` +
        `${point.series.name} was ${point.y}.`,
      series: { describeSingleSeries: true }
    },

    // remove Highcharts’ stock range-selector UI (we’re handling keyboard ourselves)
    rangeSelector: { enabled: false },
    navigator:     { enabled: true },   // keep the little draggable navigator strip
    scrollbar:     { enabled: false },

    xAxis: {
      ordinal: false,
      minRange:  3600 * 1000,
      events: {
        afterSetExtremes: afterExt
      }
    },

    yAxis: [
      {
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
        top:    '75%',
        height: '25%',
        offset: 0,
        title:  { text: 'Volume' },
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
        data: ohlc
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

  // create & store
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
