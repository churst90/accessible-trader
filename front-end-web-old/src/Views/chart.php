<?php // src/Views/chart.php ?>
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Accessible Trader – Chart</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="/assets/css/base.css">
  <link rel="stylesheet" href="/assets/css/light-theme.css">
  <link rel="stylesheet" href="/assets/css/dark-theme.css">
</head>
<body data-theme="light">

  <main role="main" class="site-main">
    <!-- Toolbar with everything JS expects -->
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

      <label for="overlayDropdown">Overlay:</label>
      <select id="overlayDropdown">
        <option value="">(none)</option>
      </select>

      <label for="oscillatorsDropdown">Oscillator:</label>
      <select id="oscillatorsDropdown">
        <option value="">(none)</option>
      </select>

      <button type="button" id="switch-scale-btn" data-log="false">Switch to Log Scale</button>
      <button type="button" id="switch-candle-btn" data-heikin="false">Switch to Heikin Ashi</button>
      <button type="button" id="refresh-chart">Refresh Chart</button>
    </section>

    <!-- Chart container -->
    <section
      id="container"
      role="region"
      aria-label="Price and volume chart"
      style="height:60vh; width:100%; max-width:1200px; margin:1rem auto;"
    ></section>

    <!-- Live-region for announcements -->
    <div aria-live="polite"   class="visually-hidden" id="chartStatus"></div>
    <div aria-live="assertive" class="visually-hidden" id="chartErrorStatus"></div>
  </main>

  <!-- 1) Core Highcharts + modules -->
  <script src="https://code.highcharts.com/stock/highstock.js"></script>
  <script src="https://code.highcharts.com/modules/boost.js"></script>
  <script src="https://code.highcharts.com/stock/modules/data.js"></script>
  <script src="https://code.highcharts.com/stock/modules/stock-tools.js"></script>

  <!-- 2) Accessibility & Sonification -->
  <script src="https://code.highcharts.com/modules/accessibility.js"></script>
  <script src="https://code.highcharts.com/modules/sonification.js"></script>

  <!-- 3) Exporting & Data Export -->
  <script src="https://code.highcharts.com/modules/exporting.js"></script>
  <script src="https://code.highcharts.com/modules/export-data.js"></script>
  <script src="https://code.highcharts.com/modules/offline-exporting.js"></script>

  <!-- 4) Built-in indicators -->
  <script src="https://code.highcharts.com/stock/indicators/indicators-all.js"></script>

  <!-- 5) Your application scripts -->
  <script type="module" src="/assets/js/chart.bundle.js"></script>
  <script src="/assets/js/app.bundle.js" defer></script>
</body>
</html>
