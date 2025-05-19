// assets/js/modules/uiBindings.js

import { loadProviders, loadSymbols } from './dataService.js';
import ChartController from './chartController.js';
// initObjectTree might also need to ensure controller.chart is ready before acting
// For now, focusing on the main toolbar
import { initObjectTree } from './treeView.js'; 
import IndicatorPanel from './indicatorPanel.js';
import { initDrawingPanel } from './drawingPanel.js';

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
    let controller = null; // This will hold the current ChartController instance
    // State for toggles should ideally live in ChartController or ChartRenderer,
    // but for now, uiBindings can manage its button text.
    let usingLog = false;
    let usingHeikin = false;

    function announce(msg) {
        if (announceEl) {
            announceEl.textContent = '';
            setTimeout(() => { if (announceEl) announceEl.textContent = msg; }, 50);
        }
    }

    function buildTimeframe() {
        const n = parseInt(multInput.value, 10) || 1;
        return `${n}${tfDD.value}`;
    }

    // --- Dropdown listeners (remain largely the same) ---
    marketDD.addEventListener('change', async () => {
        announce('Loading providers…');
        providerDD.innerHTML = '<option value="">Loading...</option>'; // Indicate loading
        assetDD.innerHTML = ''; // Clear asset dropdown
        try {
            const providers = await loadProviders(marketDD.value);
            providerDD.innerHTML = ''; // Clear loading message
            if (providers.length === 0) {
                providerDD.append(new Option('No providers found', ''));
            } else {
                providers.forEach(p => providerDD.append(new Option(p, p)));
                if (providers.length) providerDD.value = providers[0];
            }
            providerDD.dispatchEvent(new Event('change')); // Trigger loading symbols
        } catch (err) {
            announce(`Error loading providers: ${err.message}`);
            providerDD.innerHTML = '<option value="">Error</option>';
        }
    });

    providerDD.addEventListener('change', async () => {
        if (!providerDD.value) { // Handle "No providers found" or error state
            assetDD.innerHTML = '';
            return;
        }
        announce('Loading symbols…');
        assetDD.innerHTML = '<option value="">Loading...</option>';
        try {
            const syms = await loadSymbols(marketDD.value, providerDD.value);
            assetDD.innerHTML = '';
            if (syms.length === 0) {
                assetDD.append(new Option('No symbols found', ''));
            } else {
                syms.forEach(s => assetDD.append(new Option(s, s)));
                if (syms.length) assetDD.value = syms[0]; // Auto-select first symbol
            }
        } catch (err) {
            announce(`Error loading symbols: ${err.message}`);
            assetDD.innerHTML = '<option value="">Error</option>';
        }
    });

    // --- Function to wire up chart-dependent UI elements ---
    // This will be called AFTER ChartController confirms its chart is ready.
    // However, with the current structure, ChartController doesn't explicitly call back uiBindings.
    // Instead, the buttons will call methods on the `controller` instance,
    // and those methods in `ChartController` will check `if (!this.chart)`.
    function setupChartSpecificUI(currentController) {
        if (!currentController) return;

        // --- Scale & Candle Toggles ---
        // These interact with controller.renderer which should handle the chart instance check.
        switchScaleBtn.onclick = () => {
            if (!currentController.chart) { announce("Chart not ready for scale toggle."); return; }
            usingLog = !usingLog; // This local state might get out of sync if chart is refreshed.
                                  // Better if ChartRenderer manages its own scale state.
            currentController.renderer.toggleScale(); // toggleScale in renderer should use its own internal state
            switchScaleBtn.textContent = currentController.renderer.state.usingLog
                ? 'Switch to Linear Scale'
                : 'Switch to Log Scale';
             announce(currentController.renderer.state.usingLog ? 'Log scale enabled.' : 'Linear scale enabled.');
        };
        switchCandleBtn.onclick = () => {
            if (!currentController.chart) { announce("Chart not ready for candle toggle."); return; }
            // Similar to scale, renderer should manage its state.
            currentController.renderer.toggleCandle();
            switchCandleBtn.textContent = currentController.renderer.state.usingHeikin
                ? 'Switch to Candlestick'
                : 'Switch to Heikin Ashi';
            announce(currentController.renderer.state.usingHeikin ? 'Heikin Ashi candles enabled.' : 'Standard candlesticks enabled.');
        };

        // --- Highcharts StockTools Proxies ---
        // These buttons will call methods on the `currentController` instance.
        // The controller methods themselves will check `if (!this.chart)`.
        const zoomInBtn = document.getElementById(toolbarButtons.zoomIn);
        const zoomOutBtn = document.getElementById(toolbarButtons.zoomOut);
        // Pan button is special as it toggles Highcharts internal panning state.
        // const panBtn = document.getElementById(toolbarButtons.pan); 
        const resetZoomBtn = document.getElementById(toolbarButtons.resetZoom);
        const toggleAnnotationsBtn = document.getElementById(toolbarButtons.toggleAnnotations);
        // const annotateAdvancedBtn = document.getElementById(toolbarButtons.annotateAdvanced); // Handled by its own module
        // const indicatorsBtn = document.getElementById(toolbarButtons.indicators); // Handled by its own module
        const priceIndicatorBtn = document.getElementById(toolbarButtons.priceIndicator);
        const fullScreenBtn = document.getElementById(toolbarButtons.fullScreen);

        if (zoomInBtn) zoomInBtn.onclick = () => {
            announce('Zooming in...'); // Announce intent
            currentController.zoomIn(); // This method in ChartController has the if(!this.chart) guard
        };
        if (zoomOutBtn) zoomOutBtn.onclick = () => {
            announce('Zooming out...');
            currentController.zoomOut();
        };

        // Pan Chart - this one still needs direct chart access to toggle Highcharts' own panning
        const panBtn = document.getElementById(toolbarButtons.pan);
        if (panBtn) {
            let isPanningEnabledByButton = false; // Local state for the button's toggle
            panBtn.onclick = () => {
                if (!currentController.chart) { announce("Chart not ready for panning."); return; }
                isPanningEnabledByButton = !isPanningEnabledByButton;
                currentController.chart.update({
                    chart: {
                        panning: { enabled: isPanningEnabledByButton, type: 'x' },
                        // Optional: also control pinchType if you want touch panning tied to this button
                        // pinchType: isPanningEnabledByButton ? 'x' : null 
                    }
                });
                panBtn.setAttribute('aria-pressed', isPanningEnabledByButton);
                announce(isPanningEnabledByButton ? 'Chart panning enabled. Use Shift + drag or touch drag.' : 'Chart panning disabled.');
            };
        }


        if (resetZoomBtn) resetZoomBtn.onclick = () => {
            if (!currentController.chart) { announce("Chart not ready for reset zoom."); return; }
            currentController.chart.zoomOut(); // Highcharts own full zoom out
            announce('Zoom reset to full view.');
        };

        if (toggleAnnotationsBtn) {
            let annotationsCurrentlyVisible = true; // Assume they start visible
            toggleAnnotationsBtn.onclick = () => {
                if (!currentController.chart || !currentController.chart.annotations) {
                     announce("Chart or annotations not ready."); return;
                }
                annotationsCurrentlyVisible = !annotationsCurrentlyVisible;
                currentController.chart.annotations.forEach(annotation => {
                    if (annotationsCurrentlyVisible) annotation.show();
                    else annotation.hide();
                });
                toggleAnnotationsBtn.setAttribute('aria-pressed', annotationsCurrentlyVisible);
                announce(annotationsCurrentlyVisible ? 'Annotations shown.' : 'Annotations hidden.');
            };
        }
        
        // Price Indicator - This toggles a series specific option.
        if (priceIndicatorBtn) {
            let priceIndicatorCurrentlyEnabled = false;
            priceIndicatorBtn.onclick = () => {
                if (!currentController.chart) { announce("Chart not ready for price indicator."); return; }
                priceIndicatorCurrentlyEnabled = !priceIndicatorCurrentlyEnabled;
                // Find the main price series (OHLC or a line series representing price)
                const priceSeries = currentController.chart.get('ohlc') || currentController.chart.get('price-line') || currentController.chart.series[0];
                if (priceSeries) {
                     // Highcharts' PriceIndicator is a yAxis feature, not series.
                     // It's typically enabled on a yAxis and links to a series.
                     // Let's assume we want to toggle it for the main price yAxis (index 0)
                     currentController.chart.yAxis[0].update({
                        crosshair: priceIndicatorCurrentlyEnabled ? {
                            snap: true,
                            color: 'gray',
                            dashStyle: 'ShortDot',
                            label: {
                                enabled: true,
                                format: '{value:.2f}', // Adjust format as needed
                                backgroundColor: 'gray',
                                padding: 5,
                                shape: 'rect'
                            }
                        } : {
                            snap: false, // turn off snap
                            label: {enabled: false}
                        }
                     }, true); // Redraw
                }
                priceIndicatorBtn.setAttribute('aria-pressed', priceIndicatorCurrentlyEnabled);
                announce(priceIndicatorCurrentlyEnabled ? 'Price crosshair enabled.' : 'Price crosshair disabled.');
            };
        }


        if (fullScreenBtn) fullScreenBtn.onclick = () => {
            if (!currentController.chart) { announce("Chart not ready for full screen."); return; }
            if (!document.fullscreenElement) {
                currentController.chart.container.requestFullscreen()
                    .then(() => announce('Entered full screen.'))
                    .catch(err => announce(`Error entering full screen: ${err.message}`));
            } else {
                document.exitFullscreen()
                    .then(() => announce('Exited full screen.'))
                    .catch(err => announce(`Error exiting full screen: ${err.message}`));
            }
        };

        // Initialize modal-based tools (Indicators, Advanced Annotations)
        // These modules usually find the chart instance via getChart() or are passed it.
        // Ensure they are robust if controller.chart is not immediately available.
        // However, with the new flow, these should ideally be initialized
        // *after* the chart is confirmed to be ready.
        
        if (currentController.chart) { // Only init these if chart is definitely ready
            try {
                const indicatorPanel = new IndicatorPanel(); // Assumes it uses getChart() or is passed chart
                // If IndicatorPanel constructor needs chart, pass currentController.chart
                const annotateAdvancedBtn = document.getElementById(toolbarButtons.annotateAdvanced);
                if (annotateAdvancedBtn) { // This button opens the drawing panel dialog
                     initDrawingPanel(currentController.chart); // initDrawingPanel needs the chart instance
                     annotateAdvancedBtn.onclick = () => {
                        const modal = document.getElementById('draw-dialog');
                        if (modal) modal.hidden = false;
                        document.getElementById('draw-tool-list')?.focus();
                        announce('Drawing tools dialog opened');
                    };
                }

                const indicatorsBtn = document.getElementById(toolbarButtons.indicators);
                if (indicatorsBtn && indicatorPanel) { // This button uses the indicatorPanel instance
                    indicatorsBtn.onclick = () => {
                        if (indicatorPanel.openBtn) indicatorPanel.openBtn.click(); // Trigger internal open logic
                        else announce("Indicators panel not available.");
                        announce('Indicators dialog opened');
                    };
                }

            } catch(e) {
                console.error("Error initializing modal panels:", e);
                announce("Error initializing some tools.");
            }
        } else {
            announce("Chart not fully ready, some tools may not be initialized yet.");
        }
    }


    // --- Refresh Chart Button ---
    refreshBtn.addEventListener('click', () => {
        announce('Refreshing chart...');
        if (controller) {
            controller.destroy(); // Use the new destroy method in ChartController
            controller = null;
        }

        const params = {
            market: marketDD.value,
            provider: providerDD.value,
            symbol: assetDD.value,
            timeframe: buildTimeframe()
        };
        
        if (!params.market || !params.provider || !params.symbol) {
            announce("Please select Market, Provider, and Symbol to refresh chart.");
            return;
        }

        controller = new ChartController(container, announceEl, params);
        
        // The `init` method now starts the WebSocket connection.
        // UI elements dependent on the chart being fully rendered will be
        // (or should be) handled once the ChartController confirms readiness,
        // or their click handlers should delegate to controller methods that check for chart readiness.
        controller.init()
            .then(() => {
                // init now resolves very quickly after starting WS.
                // The actual chart object isn't available in `controller.chart` immediately here.
                // So, we should call setupChartSpecificUI *after* the chart is known to be rendered.
                // For now, let's assume ChartController methods handle the chart==null case.
                // We can call setupChartSpecificUI here, and its internal button handlers
                // will rely on the ChartController's methods having safety checks.
                // Or, ChartController could take `setupChartSpecificUI` as a callback for when its chart is ready.
                
                // Let's bind the buttons that call controller's own methods (which have guards)
                setupChartSpecificUI(controller); 
            })
            .catch(err => {
                console.error('Chart initialization process failed:', err);
                announce(`Chart load failed: ${err.message}`);
            });
    });

    // Initial setup for saved configs (if any)
    try {
        initObjectTree(savedConfig => {
            announce('Loading saved chart configuration...');
            if (controller) {
                controller.destroy();
            }
            // Update dropdowns to reflect saved config before creating controller
            marketDD.value = savedConfig.market;
            // You'll need to async load providers and symbols then set providerDD and assetDD, then create controller
            // This part needs careful async handling to set dropdowns correctly before init.
            // For now, let's assume savedConfig has all necessary details.
            // A more robust way would be to trigger 'change' on marketDD, wait, then providerDD, wait etc.

            controller = new ChartController(container, announceEl, savedConfig);
            controller.init()
                .then(() => {
                    setupChartSpecificUI(controller);
                     // Update UI dropdowns based on savedConfig AFTER chart controller setup
                     if(marketDD.value !== savedConfig.market) marketDD.value = savedConfig.market;
                     // Simulating change events to reload provider/symbol lists based on saved config
                     // This might be complex due to async nature.
                     // A better way is to make loadProviders/Symbols return promises and chain them.
                })
                .catch(err => {
                    console.error('Saved chart load failed:', err);
                    announce(`Saved chart load failed: ${err.message}`);
                });
        });
    } catch (e) {
        console.warn("Object tree/saved configs not initialized or failed:", e);
    }

    // Initial population of dropdowns (kick things off)
    if (marketDD.options.length > 0) {
         if(!marketDD.value) marketDD.selectedIndex = 0; // Ensure something is selected if list populated
         marketDD.dispatchEvent(new Event('change'));
    } else {
        // Handle case where market dropdown might be initially empty
        announce("Market data not available for selection.");
    }
}