// assets/js/chart.bundle.js

import { initToolbar } from './modules/uiBindings.js';

console.log('chart.bundle.js loaded');

document.addEventListener('DOMContentLoaded', () => {
  initToolbar({
    marketDD:        document.getElementById('marketDropdown'),
    providerDD:      document.getElementById('providerDropdown'),
    assetDD:         document.getElementById('assetPairDropdown'),
    multInput:       document.getElementById('multiplierInput'),
    tfDD:            document.getElementById('timeframeDropdown'),
    switchScaleBtn:  document.getElementById('switch-scale-btn'),
    switchCandleBtn: document.getElementById('switch-candle-btn'),
    refreshBtn:      document.getElementById('refresh-chart'),
    announceEl:      document.getElementById('chartStatus'),
    container:       document.getElementById('container'),

    // New: manual stock-tools buttons
    toolbarButtons: {
      zoomIn:             'stockTools-btn-zoom-in',
      zoomOut:            'stockTools-btn-zoom-out',
      pan:                'stockTools-btn-pan',
      resetZoom:          'stockTools-btn-reset-zoom',
      toggleAnnotations:  'stockTools-btn-toggle-annotations',
      annotateAdvanced:   'stockTools-btn-annotations-advanced',
      indicators:         'stockTools-btn-indicators',
      priceIndicator:     'stockTools-btn-price-indicator',
      fullScreen:         'stockTools-btn-full-screen'
    }
  });
});
