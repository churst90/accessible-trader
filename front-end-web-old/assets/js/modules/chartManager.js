// assets/js/modules/chartManager.js

/** Store & expose the chart instance for theming / global controls */
let chartInstance = null;

export function setChartInstance(c) {
  chartInstance = c;
  window.appChart = c;
}

export function getChartInstance() {
  return chartInstance;
}
