// assets/js/modules/uiBindings.js

import { loadProviders, loadSymbols } from './dataService.js';
import ChartController from './chartController.js';
import { initObjectTree } from './treeView.js';
import IndicatorPanel from './indicatorPanel.js'; // Import IndicatorPanel for the indicators modal
import { initDrawingPanel } from './drawingPanel.js'; // Import drawing panel initializer for annotations modal

export function initToolbar({
  marketDD,
  providerDD,
  assetDD,
  multInput,
  tfDD,
  switchScaleBtn,
  switchCandleBtn,
  refreshBtn,
  announceEl,
  container,
  toolbarButtons // Contains IDs of your custom buttons
}) {
  let controller = null;
  let usingLog = false;
  let usingHeikin = false;

  // Helper to send announcements to the live region
  function announce(msg) {
    announceEl.textContent = '';
    setTimeout(() => { announceEl.textContent = msg; }, 50);
  }

  // Build a timeframe string like "5m" or "1h"
  function buildTimeframe() {
    const n = parseInt(multInput.value, 10) || 1;
    return `${n}${tfDD.value}`;
  }

  // 1) Market ? Provider ? Symbol dropdowns
  marketDD.addEventListener('change', async () => {
    announce('Loading providers…');
    providerDD.innerHTML = '';
    try {
      const providers = await loadProviders(marketDD.value);
      providers.forEach(p => providerDD.append(new Option(p, p)));
      if (providers.length) providerDD.value = providers[0];
      providerDD.dispatchEvent(new Event('change'));
    } catch (err) {
      announce(`Error loading providers: ${err.message}`);
    }
  });

  providerDD.addEventListener('change', async () => {
    announce('Loading symbols…');
    assetDD.innerHTML = '';
    try {
      const syms = await loadSymbols(marketDD.value, providerDD.value);
      syms.forEach(s => assetDD.append(new Option(s, s)));
      if (syms.length) assetDD.value = syms[0];
    } catch (err) {
      announce(`Error loading symbols: ${err.message}`);
    }
  });

  // 2) Refresh / load chart
  refreshBtn.addEventListener('click', () => {
    if (controller) {
      controller.wsService?.stop();
      clearInterval(controller.pollerId);
    }

    const params = {
      market: marketDD.value,
      provider: providerDD.value,
      symbol: assetDD.value,
      timeframe: buildTimeframe()
    };

    controller = new ChartController(container, announceEl, params);

    controller.init()
      .then(() => {
        const chart = controller.chart;

        // 3) Wire up scale & candle toggles
        switchScaleBtn.onclick = () => {
          usingLog = !usingLog;
          controller.renderer.toggleScale();
          switchScaleBtn.textContent = usingLog
            ? 'Switch to Linear Scale'
            : 'Switch to Log Scale';
        };
        switchCandleBtn.onclick = () => {
          usingHeikin = !usingHeikin;
          controller.renderer.toggleCandle();
          switchCandleBtn.textContent = usingHeikin
            ? 'Switch to Candlestick'
            : 'Switch to Heikin Ashi';
        };

        // 4) Initialize the indicator and drawing panels
        const indicatorPanel = new IndicatorPanel();
        indicatorPanel.chart = chart; // Pass the chart instance

        initDrawingPanel(chart); // Initialize drawing panel with chart

        // 5) Hook up custom toolbar buttons to Highcharts actions
        const zoomInBtn = document.getElementById(toolbarButtons.zoomIn);
        const zoomOutBtn = document.getElementById(toolbarButtons.zoomOut);
        const panBtn = document.getElementById(toolbarButtons.pan);
        const resetZoomBtn = document.getElementById(toolbarButtons.resetZoom);
        const toggleAnnotationsBtn = document.getElementById(toolbarButtons.toggleAnnotations);
        const annotateAdvancedBtn = document.getElementById(toolbarButtons.annotateAdvanced);
        const indicatorsBtn = document.getElementById(toolbarButtons.indicators);
        const priceIndicatorBtn = document.getElementById(toolbarButtons.priceIndicator);
        const fullScreenBtn = document.getElementById(toolbarButtons.fullScreen);

        // Zoom In
        zoomInBtn.onclick = () => {
          const axis = chart.xAxis[0];
          const extremes = axis.getExtremes();
          const range = (extremes.max - extremes.min) * 0.25;
          axis.setExtremes(extremes.min + range, extremes.max - range, true);
          announce('Zoomed in');
        };

        // Zoom Out
        zoomOutBtn.onclick = () => {
          const axis = chart.xAxis[0];
          const extremes = axis.getExtremes();
          const range = (extremes.max - extremes.min) * 0.25;
          axis.setExtremes(extremes.min - range, extremes.max + range, true);
          announce('Zoomed out');
        };

        // Pan Chart (toggle panning mode)
        let isPanning = false;
        panBtn.onclick = () => {
          isPanning = !isPanning;
          chart.update({
            chart: {
              panning: { enabled: isPanning, type: 'x' },
              pinchType: isPanning ? 'x' : ''
            }
          });
          panBtn.setAttribute('aria-pressed', isPanning);
          announce(isPanning ? 'Panning enabled' : 'Panning disabled');
        };

        // Reset Zoom
        resetZoomBtn.onclick = () => {
          chart.zoomOut();
          announce('Zoom reset');
        };

        // Toggle Annotations (show/hide annotations)
        let annotationsVisible = true;
        toggleAnnotationsBtn.onclick = () => {
          annotationsVisible = !annotationsVisible;
          chart.annotations.forEach(annotation => {
            if (annotationsVisible) annotation.show();
            else annotation.hide();
          });
          toggleAnnotationsBtn.setAttribute('aria-pressed', annotationsVisible);
          announce(annotationsVisible ? 'Annotations shown' : 'Annotations hidden');
        };

        // Annotations Advanced (open drawing modal)
        annotateAdvancedBtn.onclick = () => {
          const modal = document.getElementById('draw-dialog');
          modal.hidden = false;
          const list = document.getElementById('draw-tool-list');
          list.focus();
          announce('Drawing tools dialog opened');
        };

        // Indicators (open indicator modal)
        indicatorsBtn.onclick = () => {
          indicatorPanel.openBtn.click();
          announce('Indicators dialog opened');
        };

        // Price Indicator (toggle price indicator)
        let priceIndicatorEnabled = false;
        priceIndicatorBtn.onclick = () => {
          priceIndicatorEnabled = !priceIndicatorEnabled;
          chart.series.forEach(series => {
            if (series.options.id === 'price-line') {
              series.update({ priceIndicator: { enabled: priceIndicatorEnabled } }, true);
            }
          });
          priceIndicatorBtn.setAttribute('aria-pressed', priceIndicatorEnabled);
          announce(priceIndicatorEnabled ? 'Price indicator enabled' : 'Price indicator disabled');
        };

        // Full Screen
        fullScreenBtn.onclick = () => {
          if (!document.fullscreenElement) {
            chart.container.requestFullscreen();
            announce('Entered full screen');
          } else {
            document.exitFullscreen();
            announce('Exited full screen');
          }
        };
      })
      .catch(err => {
        console.error('Chart load failed:', err);
        announce(`Chart load failed: ${err.message}`);
      });
  });

  // 5) Saved-config tree (optional)
  try {
    initObjectTree(savedConfig => {
      controller?.wsService?.stop();
      clearInterval(controller.pollerId);
      controller = new ChartController(container, announceEl, savedConfig);
      controller.init().catch(err => {
        console.error('Chart load failed:', err);
        announce(`Chart load failed: ${err.message}`);
      });
    });
  } catch {}

  // 6) Kick things off by loading providers initially
  marketDD.dispatchEvent(new Event('change'));
}