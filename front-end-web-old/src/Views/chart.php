<?php // src/Views/chart.php ?>
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Accessible Trader – Chart</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <!-- Your CSS themes -->
  <link rel="stylesheet" href="/assets/css/base.css">
  <link rel="stylesheet" href="/assets/css/light-theme.css">
  <link rel="stylesheet" href="/assets/css/dark-theme.css">

  <style>
    /* Dialog overlay and content */
    .dialog-content {
      background: white;
      padding: 1rem;
      border-radius: 4px;
      max-width: 400px;
      width: 90%;
      margin: auto;
    }
    #indicator-modal,
    #draw-dialog,
    #sonification-dialog,
    #indicator-settings-modal {
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0,0,0,0.5);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 10000;
    }
    [hidden] { display: none !important; }
    .param-row { margin-bottom: 0.5rem; }
    .param-row label { display: block; margin-bottom: 0.2rem; }
    .dialog-buttons { text-align: right; margin-top: 1rem; }
    .dialog-buttons button { margin-left: 0.5rem; }
    #draw-tool-list li[role="option"] { padding: 0.2rem; cursor: pointer; }
    #draw-tool-list li[aria-selected="true"] { background: #ddd; }
    /* Style for active indicators list */
    #active-indicators li {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      margin-bottom: 0.5rem;
    }
  </style>
</head>
<body data-theme="light">

  <main role="main" class="site-main">
    <!-- Toolbar -->
    <section id="toolbar" role="toolbar" aria-label="Chart controls" class="toolbar">
      <label for="marketDropdown">Market:</label>
      <select id="marketDropdown">
        <option value="crypto" selected>Crypto</option>
        <option value="stocks">Stocks</option>
      </select>

      <label for="providerDropdown">Provider:</label>
      <select id="providerDropdown"></select>

      <label for="assetPairDropdown">Symbol/Ticker:</label>
      <select id="assetPairDropdown"></select>

      <label for="multiplierInput">Timeframe Multiplier:</label>
      <input type="number" id="multiplierInput" value="1" min="1" step="1">

      <label for="timeframeDropdown">Timeframe Unit:</label>
      <select id="timeframeDropdown">
        <option value="m">Minute</option>
        <option value="h">Hour</option>
        <option value="d">Day</option>
      </select>

      <button type="button" id="switch-scale-btn">Switch to Log Scale</button>
      <button type="button" id="switch-candle-btn">Switch to Heikin Ashi</button>

      <!-- Accessible proxies for Stock-Tools icons -->
      <button type="button" id="stockTools-btn-zoom-in"                 aria-label="Zoom In">Zoom In</button>
      <button type="button" id="stockTools-btn-zoom-out"                aria-label="Zoom Out">Zoom Out</button>
      <button type="button" id="stockTools-btn-pan"                     aria-label="Pan Chart">Pan Chart</button>
      <button type="button" id="stockTools-btn-reset-zoom"              aria-label="Reset Zoom">Reset Zoom</button>
      <button type="button" id="stockTools-btn-toggle-annotations"      aria-label="Toggle Annotations">Toggle Annotations</button>
      <button type="button" id="stockTools-btn-annotations-advanced"    aria-label="Annotations…">Annotations…</button>
      <button type="button" id="stockTools-btn-indicators"              aria-label="Indicators…">Indicators…</button>
      <button type="button" id="stockTools-btn-price-indicator"         aria-label="Price Indicator">Price Indicator</button>
      <button type="button" id="stockTools-btn-full-screen"             aria-label="Full Screen">Full Screen</button>

      <button type="button" id="refresh-chart">Refresh Chart</button>
    </section>

    <!-- Chart container -->
    <section
      id="container"
      role="region"
      aria-label="Price and volume chart"
      style="height:60vh; width:100%; max-width:1200px; margin:1rem auto;"
    ></section>

    <!-- Live-region announcements -->
    <div aria-live="polite"   class="visually-hidden" id="chartStatus"></div>
    <div aria-live="assertive" class="visually-hidden" id="chartErrorStatus"></div>

    <!-- Indicators Dialog -->
    <div id="indicator-modal" role="dialog" aria-modal="true" aria-labelledby="indicator-dialog-title" hidden>
      <div class="dialog-content">
        <h2 id="indicator-dialog-title">Indicators</h2>
        <div role="tablist" aria-label="Indicator categories">
          <button role="tab" id="tab-overlays" aria-selected="true">Overlays</button>
          <button role="tab" id="tab-osc"      aria-selected="false">Oscillators</button>
          <button role="tab" id="tab-vol"      aria-selected="false">Volume</button>
        </div>
        <div role="tabpanel" id="panel-overlays" aria-labelledby="tab-overlays" tabindex="0"></div>
        <div role="tabpanel" id="panel-osc"      aria-labelledby="tab-osc"      tabindex="0" hidden></div>
        <div role="tabpanel" id="panel-vol"      aria-labelledby="tab-vol"      tabindex="0" hidden></div>

        <div id="indicator-params"></div>
        <button id="indicator-add" type="button" disabled>Add</button>
        <button id="indicator-close" type="button">Close</button>

        <h3>Active Indicators</h3>
        <ul id="active-indicators"></ul>
      </div>
    </div>

    <!-- Drawing Tools Dialog -->
    <div id="draw-dialog" role="dialog" aria-modal="true" aria-labelledby="draw-dialog-title" hidden>
      <div class="dialog-content">
        <h2 id="draw-dialog-title">Drawing Tools</h2>
        <ul id="draw-tool-list" role="listbox" tabindex="0" aria-label="Choose a drawing tool"></ul>
        <div id="draw-params"></div>
        <div class="dialog-buttons">
          <button id="draw-cancel" type="button">Cancel</button>
          <button id="draw-place"  type="button" disabled>Place</button>
        </div>
        <h3>Active Annotations</h3>
        <ul id="active-annotations"></ul>
      </div>
    </div>

    <!-- Sonification Settings Dialog -->
    <div id="sonification-dialog" role="dialog" aria-modal="true" aria-labelledby="sonifyDialogTitle" hidden>
      <div class="dialog-content">
        <h2 id="sonifyDialogTitle">Sonification Settings</h2>
        <form id="sonifyForm">
          <label for="sonification-duration">Duration (ms):</label>
          <input type="number" id="sonification-duration" value="8000" min="100" step="100">

          <label for="sonification-instrument">Instrument:</label>
          <select id="sonification-instrument">
            <option value="sine">Sine</option>
            <option value="triangle">Triangle</option>
            <option value="square">Square</option>
            <option value="sawtooth">Sawtooth</option>
          </select>

          <label>
            <input type="checkbox" id="sonification-grouping" checked>
            Group Data Points
          </label>

          <div class="dialog-buttons">
            <button type="submit">Play Sonification</button>
            <button type="button" id="sonifyCancel">Cancel</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Indicator Settings Dialog -->
    <div id="indicator-settings-modal" role="dialog" aria-modal="true" aria-labelledby="indicator-settings-title" hidden>
      <div class="dialog-content">
        <h2 id="indicator-settings-title">Edit Indicator Settings</h2>
        <div id="indicator-settings-params"></div>
        <h3>Visual Settings</h3>
        <div id="indicator-settings-visual"></div>
        <h3>Sonification Settings</h3>
        <div id="indicator-settings-sonify"></div>
        <div class="dialog-buttons">
          <button id="indicator-settings-cancel" type="button">Cancel</button>
          <button id="indicator-settings-save" type="button">Save</button>
        </div>
      </div>
    </div>

    <!-- Saved Configs Tree -->
    <section id="object-tree" role="tree" aria-label="Saved chart configurations"></section>
  </main>

  <!-- 1) Core Highcharts + Indicators Engine -->
  <script src="https://code.highcharts.com/stock/highstock.js"></script>
  <script src="https://code.highcharts.com/stock/indicators/indicators-all.js"></script>

  <!-- 2) Stock Tools modules -->
  <script src="https://code.highcharts.com/modules/drag-panes.js"></script>
  <script src="https://code.highcharts.com/modules/annotations-advanced.js"></script>
  <script src="https://code.highcharts.com/modules/price-indicator.js"></script>
  <script src="https://code.highcharts.com/modules/full-screen.js"></script>
  <script src="https://code.highcharts.com/stock/modules/stock-tools.js"></script>
  <link rel="stylesheet" href="https://code.highcharts.com/css/stocktools/gui.css">

  <!-- 3) Accessibility & Sonification -->
  <script src="https://code.highcharts.com/modules/accessibility.js"></script>
  <script src="https://code.highcharts.com/modules/sonification.js"></script>

  <!-- 4) Exporting Modules -->
  <script src="https://code.highcharts.com/modules/exporting.js"></script>
  <script src="https://code.highcharts.com/modules/export-data.js"></script>
  <script src="https://code.highcharts.com/modules/offline-exporting.js"></script>

  <!-- 5) Your Application Scripts -->
  <script type="module" src="/assets/js/chart.bundle.js"></script>
  <script src="/assets/js/app.bundle.js" defer></script>
</body>
</html>