// assets/js/modules/uiBindings.js

import { loadProviders, loadSymbols, fetchOhlcv } from './dataService.js';
import { renderChart, toggleScale, toggleCandle } from './chartRenderer.js';
import WebSocketService from './wsService.js';
import { debounce } from './utils.js';
import { getChartInstance } from './chartInstance.js';

/** Announce into an ARIA live region */
function announce(msg, el) {
  if (!el) return;
  el.textContent = '';
  setTimeout(() => el.textContent = msg, 50);
}

export function initToolbar({
  marketDD, providerDD, assetDD,
  multInput, tfDD,
  overlayDD, oscDD,
  switchScaleBtn, switchCandleBtn,
  refreshBtn, announceEl,
  container
}) {
  let chart       = null;
  let wsService   = null;
  let pollerId    = null;
  let minTs = 0, maxTs = 0;
  let usingLog    = false, usingHeikin = false;
  let currentParams = null;

  // Populate overlays & oscillators safely
  const types = Object.keys(window.Highcharts.seriesTypes);
  ['bb','ema','sma','tema'].forEach(name => {
    const o = document.createElement('option');
    o.value = name;
    o.textContent = name.toUpperCase();
    overlayDD.append(o);
  });
  ['rsi','macd','stochastic'].forEach(name => {
    const o = document.createElement('option');
    o.value = name;
    o.textContent = name.toUpperCase();
    oscDD.append(o);
  });

  function buildTF() {
    const n = parseInt(multInput.value, 10) || 1;
    return `${n}${tfDD.value}`;
  }

  function startPolling() {
    if (pollerId) return;
    announce('Polling for updates…', announceEl);
    const tf = buildTF();
    const unit = tf.slice(-1), num = parseInt(tf.slice(0,-1),10)||1;
    const interval = unit==='h'?num*3600_000:unit==='d'?num*86_400_000:num*60_000;
    pollerId = setInterval(async () => {
      try {
        const data = await fetchOhlcv({ ...currentParams, since: maxTs, limit: 1 });
        if (data.ohlc.length) {
          const [ts,o,h,l,c] = data.ohlc[0];
          handleBar({ timestamp: ts, open:o, high:h, low:l, close:c, volume:data.volume[0][1] });
        }
      } catch (err) {
        announce(`Polling error: ${err.message}`, announceEl);
      }
    }, interval);
  }

  function stopPolling() {
    if (pollerId) { clearInterval(pollerId); pollerId = null; }
  }

  function handleBar(bar) {
    chart = getChartInstance();
    if (!chart) return;
    const ts = +bar.timestamp, close = +bar.close;
    if (isNaN(ts)||isNaN(close)) return console.error("[handleBar] invalid", bar);
    if (ts <= maxTs) return;  // skip duplicates
    chart.series[0].addPoint([ts, +bar.open, +bar.high, +bar.low, close], true, true);
    chart.series[1].addPoint([ts, +bar.volume], false, true);
    announce(`New candle at ${new Date(ts).toLocaleTimeString()}, close ${close}`, announceEl);
    maxTs = ts;
  }

  async function refresh() {
    if (!assetDD.value) {
      return announce('Select an asset pair before refreshing', announceEl);
    }
    if (wsService) wsService.stop();
    stopPolling();
    announce('Loading data…', announceEl);

    const tf = buildTF();
    const now = Date.now();
    const unit = tf.slice(-1), num = parseInt(tf.slice(0,-1),10)||1;
    const msPer = unit==='h'?num*3600_000:unit==='d'?num*86400000:num*60000;
    const limit = 100;
    currentParams = {
      market:    marketDD.value,
      provider:  providerDD.value,
      symbol:    assetDD.value,
      timeframe: tf,
      limit, since: now - msPer * limit, before: now
    };

    let data;
    try {
      data = await fetchOhlcv(currentParams);
    } catch (err) {
      return announce(`Error loading data: ${err.message}`, announceEl);
    }

    document.title = `${currentParams.symbol}@${currentParams.provider} (${tf.toUpperCase()})`;
    announce('Rendering chart…', announceEl);
    chart = renderChart(
      container,
      { ...currentParams, ohlc: data.ohlc, volume: data.volume, title:`${currentParams.symbol}@${currentParams.provider}`, usingLog, usingHeikin },
      debounce(async e => {
        if (e.min < minTs) {
          announce('Loading older bars…', announceEl);
          const hist = await fetchOhlcv({ ...currentParams, before: minTs, limit });
          hist.ohlc.forEach((b,i) => {
            if (b[0] < minTs) {
              chart.series[0].addPoint(b, false, false);
              chart.series[1].addPoint(hist.volume[i], false, false);
            }
          });
          minTs = chart.series[0].data[0].x;
          chart.redraw();
          announce('Older bars loaded', announceEl);
        }
      }, 200)
    );

    minTs = data.ohlc[0]?.[0] || 0;
    maxTs = data.ohlc.slice(-1)[0]?.[0] || now;

    wsService = new WebSocketService(currentParams, {
      onOpen:     () => { announce('WS connected', announceEl); stopPolling(); },
      onError:    e  => announce(`WS error: ${e.message}`, announceEl),
      onClose:    () => announce('WS closed; reconnecting…', announceEl),
      onFallback: startPolling,
      onMessage:  handleBar
    });
    wsService.start();

    announce('Chart ready', announceEl);
  }

  // wire up dropdowns safely
  marketDD.addEventListener('change', async () => {
    announce('Loading providers…', announceEl);
    providerDD.innerHTML = '';
    try {
      const exs = await loadProviders(marketDD.value);
      exs.forEach(p => {
        const o = document.createElement('option');
        o.value = p; o.textContent = p;
        providerDD.append(o);
      });
      providerDD.dispatchEvent(new Event('change'));
    } catch (err) {
      announce(`Error loading providers: ${err.message}`, announceEl);
    }
  });

  providerDD.addEventListener('change', async () => {
    announce('Loading symbols…', announceEl);
    assetDD.innerHTML = '';
    try {
      const syms = await loadSymbols(marketDD.value, providerDD.value);
      syms.forEach(s => {
        const o = document.createElement('option');
        o.value = s; o.textContent = s;
        assetDD.append(o);
      });
      if (syms.length) assetDD.value = syms[0];
    } catch (err) {
      announce(`Error loading symbols: ${err.message}`, announceEl);
    }
  });

  refreshBtn.addEventListener('click', refresh);
  switchScaleBtn.addEventListener('click', () => {
    usingLog = !usingLog;
    toggleScale(getChartInstance(), usingLog);
    switchScaleBtn.textContent = usingLog ? 'Switch to Linear Scale' : 'Switch to Log Scale';
    announce(`Scale: ${usingLog?'Logarithmic':'Linear'}`, announceEl);
  });
  switchCandleBtn.addEventListener('click', () => {
    usingHeikin = !usingHeikin;
    toggleCandle(getChartInstance(), usingHeikin);
    switchCandleBtn.textContent = usingHeikin ? 'Switch to Candlestick' : 'Switch to Heikin Ashi';
    announce(`Candles: ${usingHeikin?'Heikin-Ashi':'Standard'}`, announceEl);
  });

  // initial kick-off
  marketDD.dispatchEvent(new Event('change'));
}
