// assets/js/chart.bundle.js

import IndicatorPanel from './modules/indicatorPanel.js';
import { initToolbar }  from './modules/uiBindings.js';

document.addEventListener('DOMContentLoaded', () => {
  // 1) Kick off the HTML-based Indicators panel
  new IndicatorPanel();

  // 2) Then wire up the chart toolbar
  initToolbar({
    marketDD:        document.getElementById('marketDropdown'),
    providerDD:      document.getElementById('providerDropdown'),
    assetDD:         document.getElementById('assetPairDropdown'),
    multInput:       document.getElementById('multiplierInput'),
    tfDD:            document.getElementById('timeframeDropdown'),
    switchScaleBtn:  document.getElementById('switch-scale-btn'),
    switchCandleBtn: document.getElementById('switch-candle-btn'),
    refreshBtn:      document.getElementById('refresh-chart'),
    sonifyChartBtn:  document.getElementById('sonify-chart'),
    announceEl:      document.getElementById('chartStatus'),
    container:       document.getElementById('container')
  });
});
