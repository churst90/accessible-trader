// assets/js/modules/chartStore.js

/** @type {import('highcharts').Chart| null} */
let _chart = null;

/**
 * Set the current chart instance.
 * @param {import('highcharts').Chart} chart
 */
export function setChart(chart) {
  _chart = chart;
  console.log('[ChartStore] chart instance set');
}

/**
 * Retrieve the current chart instance.
 * @returns {import('highcharts').Chart|null}
 */
export function getChart() {
  return _chart;
}
