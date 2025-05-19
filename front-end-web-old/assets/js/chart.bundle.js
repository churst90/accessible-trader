// assets/js/chart.bundle.js
console.log('[chart.bundle.js] module loaded');

import { initToolbar } from './modules/uiBindings.js';
console.log('[chart.bundle.js] initToolbar is', typeof initToolbar);

document.addEventListener('DOMContentLoaded', () => {
  console.log('[chart.bundle.js] DOM ready — calling initToolbar');

  initToolbar({
    marketDD:        document.getElementById('marketDropdown'),
    providerDD:      document.getElementById('providerDropdown'),
    assetDD:         document.getElementById('assetPairDropdown'),
    multInput:       document.getElementById('multiplierInput'),
    tfDD:            document.getElementById('timeframeDropdown'),
    overlayDD:       document.getElementById('overlayDropdown'),
    oscDD:           document.getElementById('oscillatorsDropdown'),
    switchScaleBtn:  document.getElementById('switch-scale-btn'),
    switchCandleBtn: document.getElementById('switch-candle-btn'),
    refreshBtn:      document.getElementById('refresh-chart'),
    announceEl:      document.getElementById('chartStatus'),
    container:       document.getElementById('container')
  });
});
