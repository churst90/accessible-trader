// assets/js/modules/uiBindings.js

import { loadProviders, loadSymbols, loadAvailableMarkets } from './dataService.js';
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

    // --- Market Dropdown Population (NEW) ---
    async function populateMarketDropdown() {
        announce('Loading available markets…');
        marketDD.innerHTML = '<option value="">Loading Markets...</option>'; // Indicate loading
        try {
            const markets = await loadAvailableMarkets();
            marketDD.innerHTML = ''; // Clear loading message
            if (markets.length === 0) {
                marketDD.append(new Option('No markets available', ''));
                announce('No markets available from server.');
            } else {
                markets.forEach(marketName => marketDD.append(new Option(marketName, marketName)));
                if (marketDD.options.length > 0) {
                    // TODO: Check if there's a saved market preference from localStorage or user settings
                    // and try to select it. Otherwise, default to the first.
                    // For now, just selecting the first one.
                    marketDD.selectedIndex = 0;
                    announce('Markets loaded. Loading providers for default market...');
                    marketDD.dispatchEvent(new Event('change')); // Trigger loading providers for the first market
                } else {
                     announce('Markets loaded, but list is empty.');
                }
            }
        } catch (err) {
            announce(`Error loading markets: ${err.message}`);
            console.error('[UIBindings] Error in populateMarketDropdown:', err);
            marketDD.innerHTML = '<option value="">Error loading markets</option>';
        }
    }

    // --- Dropdown listeners ---
    marketDD.addEventListener('change', async () => {
        if (!marketDD.value) { // If market is empty (e.g. "Error loading markets" or "No markets available")
            providerDD.innerHTML = '';
            assetDD.innerHTML = '';
            announce('Please select a valid market.');
            return;
        }
        announce('Loading providers…');
        providerDD.innerHTML = '<option value="">Loading...</option>'; // Indicate loading
        assetDD.innerHTML = ''; // Clear asset dropdown
        try {
            const providers = await loadProviders(marketDD.value);
            providerDD.innerHTML = ''; // Clear loading message
            if (providers.length === 0) {
                providerDD.append(new Option('No providers found', ''));
                 assetDD.innerHTML = ''; // Ensure asset dropdown is also cleared
            } else {
                providers.forEach(p => providerDD.append(new Option(p, p)));
                if (providers.length) {
                     // TODO: Check for saved provider preference for this market
                    providerDD.value = providers[0]; // Default to first provider
                }
            }
            providerDD.dispatchEvent(new Event('change')); // Trigger loading symbols
        } catch (err) {
            announce(`Error loading providers: ${err.message}`);
            console.error('[UIBindings] Error in marketDD change listener (loading providers):', err);
            providerDD.innerHTML = '<option value="">Error</option>';
            assetDD.innerHTML = '';
        }
    });

    providerDD.addEventListener('change', async () => {
        if (!providerDD.value) { // Handle "No providers found" or error state
            assetDD.innerHTML = '';
            if (marketDD.value) announce('Please select a valid provider.'); // Only announce if a market is selected
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
                if (syms.length) {
                    // TODO: Check for saved symbol preference for this market/provider
                    assetDD.value = syms[0]; // Auto-select first symbol
                }
            }
            // Optionally, trigger chart refresh here if auto-load on symbol change is desired
            // refreshBtn.click(); 
        } catch (err) {
            announce(`Error loading symbols: ${err.message}`);
            console.error('[UIBindings] Error in providerDD change listener (loading symbols):', err);
            assetDD.innerHTML = '<option value="">Error</option>';
        }
    });

    function setupChartSpecificUI(currentController) {
        if (!currentController) return;

        switchScaleBtn.onclick = () => {
            if (!currentController.chart) { announce("Chart not ready for scale toggle."); return; }
            currentController.renderer.toggleScale(); 
            switchScaleBtn.textContent = currentController.renderer.state.usingLog
                ? 'Switch to Linear Scale'
                : 'Switch to Log Scale';
            announce(currentController.renderer.state.usingLog ? 'Log scale enabled.' : 'Linear scale enabled.');
        };
        switchCandleBtn.onclick = () => {
            if (!currentController.chart) { announce("Chart not ready for candle toggle."); return; }
            currentController.renderer.toggleCandle();
            switchCandleBtn.textContent = currentController.renderer.state.usingHeikin
                ? 'Switch to Candlestick'
                : 'Switch to Heikin Ashi';
            announce(currentController.renderer.state.usingHeikin ? 'Heikin Ashi candles enabled.' : 'Standard candlesticks enabled.');
        };

        const zoomInBtn = document.getElementById(toolbarButtons.zoomIn);
        const zoomOutBtn = document.getElementById(toolbarButtons.zoomOut);
        const resetZoomBtn = document.getElementById(toolbarButtons.resetZoom);
        const toggleAnnotationsBtn = document.getElementById(toolbarButtons.toggleAnnotations);
        const priceIndicatorBtn = document.getElementById(toolbarButtons.priceIndicator);
        const fullScreenBtn = document.getElementById(toolbarButtons.fullScreen);

        if (zoomInBtn) zoomInBtn.onclick = () => {
            announce('Zooming in...'); 
            currentController.zoomIn(); 
        };
        if (zoomOutBtn) zoomOutBtn.onclick = () => {
            announce('Zooming out...');
            currentController.zoomOut();
        };

        const panBtn = document.getElementById(toolbarButtons.pan);
        if (panBtn) {
            let isPanningEnabledByButton = false; 
            panBtn.onclick = () => {
                if (!currentController.chart) { announce("Chart not ready for panning."); return; }
                isPanningEnabledByButton = !isPanningEnabledByButton;
                currentController.chart.update({
                    chart: {
                        panning: { enabled: isPanningEnabledByButton, type: 'x' },
                    }
                });
                panBtn.setAttribute('aria-pressed', isPanningEnabledByButton);
                announce(isPanningEnabledByButton ? 'Chart panning enabled. Use Shift + drag or touch drag.' : 'Chart panning disabled.');
            };
        }

        if (resetZoomBtn) resetZoomBtn.onclick = () => {
            if (!currentController.chart) { announce("Chart not ready for reset zoom."); return; }
            currentController.chart.zoomOut(); 
            announce('Zoom reset to full view.');
        };

        if (toggleAnnotationsBtn) {
            let annotationsCurrentlyVisible = true; 
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
        
        if (priceIndicatorBtn) {
            let priceIndicatorCurrentlyEnabled = false;
            priceIndicatorBtn.onclick = () => {
                if (!currentController.chart) { announce("Chart not ready for price indicator."); return; }
                priceIndicatorCurrentlyEnabled = !priceIndicatorCurrentlyEnabled;
                const priceSeries = currentController.chart.get('ohlc') || currentController.chart.get('price-line') || currentController.chart.series[0];
                if (priceSeries && currentController.chart.yAxis[0]) { // Check if yAxis[0] exists
                     currentController.chart.yAxis[0].update({
                        crosshair: priceIndicatorCurrentlyEnabled ? {
                            snap: true,
                            color: 'gray',
                            dashStyle: 'ShortDot',
                            label: {
                                enabled: true,
                                format: '{value:.2f}', 
                                backgroundColor: 'gray',
                                padding: 5,
                                shape: 'rect'
                            }
                        } : {
                            snap: false, 
                            label: {enabled: false}
                        }
                    }, true); 
                } else {
                    announce("Price series or Y-axis not found for indicator.");
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
        
        if (currentController.chart) { 
            try {
                const indicatorPanel = new IndicatorPanel(); 
                const annotateAdvancedBtn = document.getElementById(toolbarButtons.annotateAdvanced);
                if (annotateAdvancedBtn) { 
                     initDrawingPanel(currentController.chart); 
                     annotateAdvancedBtn.onclick = () => {
                        const modal = document.getElementById('draw-dialog');
                        if (modal) modal.hidden = false;
                        document.getElementById('draw-tool-list')?.focus();
                        announce('Drawing tools dialog opened');
                    };
                }

                const indicatorsBtn = document.getElementById(toolbarButtons.indicators);
                if (indicatorsBtn && indicatorPanel) { 
                    indicatorsBtn.onclick = () => {
                        if (indicatorPanel.openBtn) indicatorPanel.openBtn.click(); 
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


    refreshBtn.addEventListener('click', () => {
        announce('Refreshing chart...');
        if (controller) {
            controller.destroy(); 
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

        // Ensure container is empty or Highcharts will error on re-init to same element
        if (container) container.innerHTML = ''; 


        controller = new ChartController(container, announceEl, params);
        
        controller.init()
            .then((chartInstance) => { // init() resolves with the chart instance or null
                if (chartInstance) { // Check if chart was successfully created
                    setupChartSpecificUI(controller); 
                } else {
                    announce('Chart failed to initialize after refresh.');
                }
            })
            .catch(err => {
                console.error('Chart initialization process failed on refresh:', err);
                announce(`Chart load failed: ${err.message}`);
            });
    });

    try {
        initObjectTree(async savedConfig => { // Make this callback async
            announce('Loading saved chart configuration...');
            if (controller) {
                controller.destroy();
                controller = null;
            }
            
            // Update dropdowns to reflect saved config before creating controller
            // This needs to be done sequentially.
            marketDD.value = savedConfig.market;
            await populateMarketDropdown(); // This will set marketDD and trigger provider load

            // Wait for providers to load and then set the provider
            // This is a bit tricky as 'change' events are async.
            // A more robust way is to make loadProviders/Symbols return data and manually set.
            
            // Simple approach: Assume populateMarketDropdown will trigger provider loading,
            // then we manually set provider and symbol from savedConfig IF THEY EXIST in the loaded options.
            // This is still not perfectly robust without more state management or chained promises.

            // A better way:
            // 1. Set marketDD.value
            // 2. Call loadProviders(savedConfig.market)
            // 3. Populate providerDD, set providerDD.value = savedConfig.provider
            // 4. Call loadSymbols(savedConfig.market, savedConfig.provider)
            // 5. Populate assetDD, set assetDD.value = savedConfig.symbol
            // Then init controller.

            // For now, let's assume the saved config is valid and will eventually be selected
            // by the triggered change events, then we make a new controller.
            // This part is complex to get right without a small state machine or careful promise chaining.

            // Simplified: set the values and hope the event chain catches up.
            // A more robust solution would involve awaiting each step of dropdown population.
            if (Array.from(providerDD.options).some(opt => opt.value === savedConfig.provider)) {
                providerDD.value = savedConfig.provider;
            }
            if (Array.from(assetDD.options).some(opt => opt.value === savedConfig.symbol)) {
                assetDD.value = savedConfig.symbol;
            }
            // Potentially parse savedConfig.timeframe for multInput and tfDD
            // e.g. "5m" -> multInput.value = 5, tfDD.value = "m"

            controller = new ChartController(container, announceEl, savedConfig);
            controller.init()
                .then((chartInstance) => {
                    if (chartInstance) {
                        setupChartSpecificUI(controller);
                    }
                })
                .catch(err => {
                    console.error('Saved chart load failed:', err);
                    announce(`Saved chart load failed: ${err.message}`);
                });
        });
    } catch (e) {
        console.warn("Object tree/saved configs not initialized or failed:", e);
    }

    // Initial population of market dropdown
    populateMarketDropdown(); 

} // End of initToolbar