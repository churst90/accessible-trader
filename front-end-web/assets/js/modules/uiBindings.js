// assets/js/modules/uiBindings.js

import { loadProviders, loadSymbols, fetchOhlcv } from './dataService.js';
import { renderChart, toggleScale, toggleCandle } from './chartRenderer.js';
import WebSocketService                          from './wsService.js';
import { getChartInstance }                      from './chartInstance.js';

/**
 * Manages all data loading, live updates and user interactions.
 */
class ChartController {
  constructor(container, announceEl) {
    this.container      = container;
    this.announceEl     = announceEl;
    this.chart          = null;
    this.fullOhlc       = [];
    this.fullVol        = [];
    this.earliestTs     = 0;
    this.latestTs       = 0;
    this.msPerBar       = 0;
    this.pageSize       = 0;
    this.isLiveView     = true;
    this.params         = null; // { market, provider, symbol, timeframe }
    this.wsService      = null;
    this.pollerId       = null;
    this.loadingHistory = false;
  }

  announce(msg) {
    this.announceEl.textContent = '';
    setTimeout(() => { this.announceEl.textContent = msg; }, 50);
  }

  /** Fetch and render the first batch of data */
  async loadInitial(params) {
    this.params = { ...params };
    const { market, provider, symbol, timeframe } = this.params;

    // compute msPerBar & pageSize
    const num  = +timeframe.slice(0, -1);
    const unit = timeframe.slice(-1);
    this.msPerBar = unit==='h' ? num*3600000 :
                    unit==='d' ? num*86400000 :
                                 num*60000;
    this.pageSize = unit==='m' ? 1000 : unit==='h' ? 500 : 365;

    // fetch window [now - N*msPerBar, now]
    const now    = Date.now();
    const since  = now - this.pageSize * this.msPerBar;
    const before = now;

    this.announce('Loading data…');
    let data;
    try {
      data = await fetchOhlcv({ ...this.params, since, before, limit: this.pageSize });
    } catch (err) {
      this.announce(`Chart failed to load: ${err.message}`);
      return;
    }

    // stash
    this.fullOhlc   = data.ohlc.slice();
    this.fullVol    = data.volume.slice();
    this.earliestTs = this.fullOhlc[0]?.[0]  || since;
    this.latestTs   = this.fullOhlc[this.fullOhlc.length-1]?.[0] || before;
    this.isLiveView = true;

    // --------------------------------------------------------------------
    // Update browser tab title:
    // Accessible Trader: BTC/USD 4H at Bitstamp
    document.title = `Accessible Trader: ${symbol} ${timeframe} at ${provider}`;

    // Build chart’s internal title
    const chartTitle = `${symbol} ${timeframe} @ ${provider}`;
    // --------------------------------------------------------------------

    // render
    this.chart = renderChart(
      this.container,
      {
        ohlc:       this.fullOhlc,
        volume:     this.fullVol,
        title:      chartTitle,
        usingLog:   false,
        usingHeikin:false
      },
      {
        onPan:     this.handlePan.bind(this),
        onKeydown: this.handleKeydown.bind(this)
      }
    );

    // zoom to last 25%
    const showCount = Math.floor(this.fullOhlc.length / 4);
    const span      = showCount * this.msPerBar;
    const viewMin   = this.latestTs - span;
    this.chart.xAxis[0].setExtremes(viewMin, this.latestTs, true, false);

    this.announce(
      `Chart loaded: showing ${showCount} bars ` +
      `from ${new Date(viewMin).toLocaleString()} to ${new Date(this.latestTs).toLocaleString()}`
    );

    this.startWebSocket();
  }

  /** Page one more chunk of history before earliestTs */
  async loadMoreHistory() {
    if (this.loadingHistory) return;
    this.loadingHistory = true;
    this.announce('Loading older history…');

    const newBefore = this.earliestTs;
    const newSince  = Math.max(0, newBefore - this.pageSize * this.msPerBar);

    let data;
    try {
      data = await fetchOhlcv({
        ...this.params,
        since:  newSince,
        before: newBefore,
        limit:  this.pageSize
      });
    } catch (err) {
      this.announce(`Error loading history: ${err.message}`);
      this.loadingHistory = false;
      return;
    }

    if (data.ohlc.length === 0) {
      this.announce('No more historical data');
    } else {
      // prepend
      this.fullOhlc = data.ohlc.concat(this.fullOhlc);
      this.fullVol  = data.volume.concat(this.fullVol);
      this.earliestTs = this.fullOhlc[0][0];

      // update series all at once
      this.chart.series[0].setData(this.fullOhlc, false);
      this.chart.series[1].setData(this.fullVol,  false);

      // snap viewport to newly-loaded bars
      const ex   = this.chart.xAxis[0].getExtremes();
      const span = ex.max - ex.min;
      this.chart.xAxis[0].setExtremes(this.earliestTs, this.earliestTs + span, true, false);

      this.announce(`Loaded ${data.ohlc.length} bars of history`);
    }

    this.loadingHistory = false;
  }

  handlePan(e) {
    if (e.min < this.earliestTs) this.loadMoreHistory();
    this.isLiveView = e.max >= this.latestTs - (this.pageSize * 10);
  }

  handleKeydown(e) {
    switch (e.key) {
      case '=': case '+': this.zoomIn();    break;
      case '-':            this.zoomOut();   break;
      case '[':            this.panLeft();   break;
      case ']':            this.panRight();  break;
      case '\\':           this.resetToLive(); break;
      default: return;
    }
    e.preventDefault();
  }

  zoomIn() {
    const axis = this.chart.xAxis[0];
    const ex   = axis.getExtremes();
    const inView = this.fullOhlc.filter(b => b[0] >= ex.min && b[0] <= ex.max);
    if (inView.length > 2) {
      const newMin = inView[1][0];
      const newMax = inView[inView.length-2][0];
      axis.setExtremes(newMin, newMax, true, false);
      this.announce(`Zoomed in: showing ${inView.length-2} bars`);
    }
  }

  zoomOut() {
    const axis = this.chart.xAxis[0];
    const ex   = axis.getExtremes();
    const newMin = Math.max(ex.dataMin, ex.min - this.msPerBar);
    const newMax = Math.min(ex.dataMax, ex.max + this.msPerBar);
    axis.setExtremes(newMin, newMax, true, false);
    const count = this.fullOhlc.filter(b => b[0] >= newMin && b[0] <= newMax).length;
    this.announce(`Zoomed out: showing ${count} bars`);
  }

  panLeft() {
    const axis = this.chart.xAxis[0];
    const ex   = axis.getExtremes();
    const span = ex.max - ex.min;
    axis.setExtremes(ex.min - span*0.25, ex.max - span*0.25, true, false);
    this.announce(`Panned left to ${new Date(ex.min - span*0.25).toLocaleString()}`);
  }

  panRight() {
    const axis = this.chart.xAxis[0];
    const ex = axis.getExtremes();
    if (ex.max >= this.latestTs) {
      this.announce('At live edge');
      return;
    }
    const span   = ex.max - ex.min;
    let   newMin = ex.min + span*0.25;
    let   newMax = ex.max + span*0.25;
    if (newMax > this.latestTs) newMax = this.latestTs;
    axis.setExtremes(newMin, newMax, true, false);
    this.announce(`Panned right to ${new Date(newMin).toLocaleString()}`);
  }

  resetToLive() {
    const axis = this.chart.xAxis[0];
    const span = axis.getExtremes().max - axis.getExtremes().min;
    axis.setExtremes(this.latestTs - span, this.latestTs, true, false);
    this.announce('Reset to live view');
  }

  handleLiveBar(bar) {
    const ts = +bar.timestamp;
    this.fullOhlc.push([ts, +bar.open, +bar.high, +bar.low, +bar.close]);
    this.fullVol .push([ts, +bar.volume]);
    this.latestTs = ts;

    this.chart.series[0].addPoint(this.fullOhlc.slice(-1)[0], false, false);
    this.chart.series[1].addPoint(this.fullVol.slice(-1)[0],  false, false);
    this.chart.redraw();

    if (this.isLiveView) {
      const axis = this.chart.xAxis[0];
      const ex   = axis.getExtremes();
      axis.setExtremes(ts - (ex.max-ex.min), ts, true, false);
      this.announce(`New bar at ${new Date(ts).toLocaleTimeString()}`);
    }
  }

  startWebSocket() {
    if (this.wsService) this.wsService.stop();
    this.wsService = new WebSocketService(
      { ...this.params, since: this.latestTs },
      {
        onOpen:        ()  => this.announce('Live updates connected'),
        onError:       e   => this.announce(`Live error: ${e.message}`),
        onClose:       ()  => this.announce('Live disconnected; polling…'),
        onFallback:    ()  => this.startPolling(),
        onMessage:     this.handleLiveBar.bind(this),
        onRetryNotice: msg => this.announce(msg)
      }
    );
    this.wsService.start();
  }

  startPolling() {
    if (this.pollerId) clearInterval(this.pollerId);
    this.pollerId = setInterval(async () => {
      try {
        const { ohlc, volume } = await fetchOhlcv({
          ...this.params,
          since: this.latestTs,
          limit: 1
        });
        if (ohlc.length) {
          this.handleLiveBar({
            timestamp: ohlc[0][0],
            open:      ohlc[0][1],
            high:      ohlc[0][2],
            low:       ohlc[0][3],
            close:     ohlc[0][4],
            volume:    volume[0][1]
          });
        }
      } catch (err) {
        this.announce(`Polling error: ${err.message}`);
      }
    }, this.msPerBar / 2);
  }
}

/**
 * Wire up your dropdowns, buttons and chart.
 */
export function initToolbar({
  marketDD, providerDD, assetDD,
  multInput, tfDD,
  overlayDD, oscDD,
  switchScaleBtn, switchCandleBtn,
  refreshBtn, announceEl,
  container
}) {
  let controller = null;
  let usingLog   = false;
  let usingHeikin= false;

  // populate overlays & oscillators
  ['bb','ema','sma','tema'].forEach(n => overlayDD.append(new Option(n.toUpperCase(), n)));
  ['rsi','macd','stochastic'].forEach(n => oscDD.append(new Option(n.toUpperCase(), n)));

  function buildTF() {
    const n = parseInt(multInput.value, 10) || 1;
    return `${n}${tfDD.value}`;
  }

  marketDD.addEventListener('change', async () => {
    announceEl.textContent = 'Loading providers…';
    providerDD.innerHTML = '';
    try {
      const ps = await loadProviders(marketDD.value);
      ps.forEach(p => providerDD.append(new Option(p, p)));
      providerDD.dispatchEvent(new Event('change'));
    } catch (err) {
      announceEl.textContent = `Error loading providers: ${err.message}`;
    }
  });

  providerDD.addEventListener('change', async () => {
    announceEl.textContent = 'Loading symbols…';
    assetDD.innerHTML = '';
    try {
      const syms = await loadSymbols(marketDD.value, providerDD.value);
      syms.forEach(s => assetDD.append(new Option(s, s)));
      if (syms.length) assetDD.value = syms[0];
    } catch (err) {
      announceEl.textContent = `Error loading symbols: ${err.message}`;
    }
  });

  refreshBtn.addEventListener('click', () => {
    if (controller) {
      controller.wsService?.stop();
      clearInterval(controller.pollerId);
    }
    const params = {
      market:    marketDD.value,
      provider:  providerDD.value,
      symbol:    assetDD.value,
      timeframe: buildTF()
    };
    controller = new ChartController(container, announceEl);
    controller.loadInitial(params);
  });

  switchScaleBtn.addEventListener('click', () => {
    usingLog = !usingLog;
    toggleScale(getChartInstance(), usingLog);
  });

  switchCandleBtn.addEventListener('click', () => {
    usingHeikin = !usingHeikin;
    toggleCandle(getChartInstance(), usingHeikin);
  });

  // kick off
  marketDD.dispatchEvent(new Event('change'));
}
