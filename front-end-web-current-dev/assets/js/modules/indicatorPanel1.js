// assets/js/modules/indicatorPanel.js
import { getChartInstance } from './chartInstance.js';

export default class IndicatorPanel {
  constructor() {
    // 1) grab all the DOM pieces
    this.openBtn    = document.getElementById('indicators-btn');
    this.closeBtn   = document.getElementById('indicator-close');
    this.modal      = document.getElementById('indicator-modal');
    this.paramsEl   = document.getElementById('indicator-params');
    this.addBtn     = document.getElementById('indicator-add');
    this.activeUl   = document.getElementById('active-indicators');
    this.liveRegion = document.getElementById('chartStatus');

    this.tabs = {
      Overlays:    document.getElementById('tab-overlays'),
      Oscillators: document.getElementById('tab-osc'),
      Volume:      document.getElementById('tab-vol'),
    };
    this.panels = {
      Overlays:    document.getElementById('panel-overlays'),
      Oscillators: document.getElementById('panel-osc'),
      Volume:      document.getElementById('panel-vol'),
    };
    this.categoryNames = ['Overlays','Oscillators','Volume'];

    // 2) PROBE all seriesTypes in Highcharts to find indicators:
    const H = window.Highcharts;
    // build a flat list of { type, params: {...} }
    this.allIndicators = Object.entries(H.seriesTypes)
      .filter(([,Ctor]) => Ctor.defaultOptions.params)
      .map(([type, Ctor]) => ({
        type,
        params: { ...Ctor.defaultOptions.params }
      }));

    // 3) STATIC grouping by type ? these arrays identify
    //    which go under Overlays / Oscillators / Volume
    const groups = {
      Overlays:    ['sma','ema','bb','tema','dema','wma','zema'],
      Oscillators: ['rsi','macd','stochastic','cci','adx','momentum'],
      Volume:      ['obv','vbp','force','vwap']
    };

    this.categories = {};
    this.categoryNames.forEach(cat => {
      this.categories[cat] = this.allIndicators
        .filter(i => groups[cat].includes(i.type));
    });

    // catch any oddball ones: put them under Overlays by default
    const used = new Set([].concat(...Object.values(groups)));
    const others = this.allIndicators.filter(i => !used.has(i.type));
    this.categories.Overlays.push(...others);

    // 4) wire up open/close
    this._bindDialog();
  }

  _bindDialog() {
    this.openBtn.addEventListener('click', () => {
      this.chart = getChartInstance();
      if (!this.chart) return alert('Please Refresh Chart first.');

      // rebuild UI fresh
      this._buildTabs();
      this._populatePanels();

      this.modal.hidden = false;
      this.addBtn.disabled = true;
      this.tabs.Overlays.click();
    });

    this.closeBtn.addEventListener('click', () => {
      this.modal.hidden = true;
      this.openBtn.focus();
    });

    this.modal.addEventListener('keydown', e => {
      if (e.key === 'Escape') {
        this.modal.hidden = true;
        this.openBtn.focus();
      }
    });
  }

  _buildTabs() {
    const activate = cat => {
      this.categoryNames.forEach(c => {
        this.tabs[c].setAttribute('aria-selected', c === cat);
        this.panels[c].hidden = c !== cat;
      });
      this.paramsEl.innerHTML = '';
      this.addBtn.disabled = true;
      this.panels[cat].focus();
    };

    this.categoryNames.forEach(cat => {
      const btn = this.tabs[cat];
      btn.onclick = () => activate(cat);
      btn.onkeydown = e => {
        if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
          e.preventDefault();
          let idx = this.categoryNames.indexOf(cat);
          idx = e.key === 'ArrowRight'
            ? (idx + 1) % this.categoryNames.length
            : (idx - 1 + this.categoryNames.length) % this.categoryNames.length;
          activate(this.categoryNames[idx]);
        }
      };
    });
  }

  _populatePanels() {
    const H = window.Highcharts;

    this.categoryNames.forEach(cat => {
      const panel = this.panels[cat];
      panel.innerHTML = '';
      const grid = document.createElement('div');
      grid.setAttribute('role','grid');
      grid.classList.add('indicator-grid');
      panel.append(grid);

      this.categories[cat].forEach(item => {
        const label = (H.getOptions().lang[item.type] || item.type).toUpperCase();
        const btn = document.createElement('button');
        btn.setAttribute('role','gridcell');
        btn.tabIndex = 0;
        btn.textContent = label;
        btn.onclick = () => this._openParamForm(cat, item);
        grid.append(btn);
      });
    });
  }

  _openParamForm(category, item) {
    this.currentCategory = category;
    this.currentItem     = item;
    this.paramsEl.innerHTML = '';

    Object.entries(item.params).forEach(([name, defaultValue]) => {
      const row = document.createElement('div');
      row.className = 'param-row';
      row.innerHTML = `
        <label for="ind-${name}">
          ${name}: 
          <input id="ind-${name}" type="number" value="${defaultValue}" />
        </label>`;
      this.paramsEl.append(row);
    });

    this.addBtn.disabled = false;
    this.addBtn.focus();
    this.addBtn.onclick = () => this._addSeries();
  }

  _addSeries() {
    const H    = window.Highcharts;
    const item = this.currentItem;
    const cat  = this.currentCategory;
    if (!item || !this.chart) return;

    // collect params
    const cfg = {};
    Object.keys(item.params).forEach(name => {
      const el = document.getElementById(`ind-${name}`);
      if (el && el.value !== '') cfg[name] = Number(el.value);
    });

    // name it
    const desc = Object.entries(cfg).map(([k,v])=>`${k}=${v}`).join(',');
    const seriesName = desc
      ? `${item.type.toUpperCase()} (${desc})`
      : item.type.toUpperCase();

    // pick axis
    const axisMap = { Overlays:0, Volume:1, Oscillators:2 };
    const yAxis   = axisMap[cat] ?? 0;

    // add & redraw
    const id = `${item.type}-${Date.now()}`;
    this.chart.addSeries({
      id,
      type: item.type,
      name: seriesName,
      params: cfg,
      yAxis,
      linkedTo: cat==='Overlays'? 'ohlc' : undefined,
      showInLegend: true
    }, false);
    this.chart.redraw();

    // announce & close
    this.liveRegion.textContent = `Added ${seriesName}`;
    this.modal.hidden = true;
    this.openBtn.focus();

    // track active
    const li = document.createElement('li');
    li.textContent = seriesName + ' ';
    const rm = document.createElement('button');
    rm.type = 'button'; rm.textContent = 'Remove';
    rm.onclick = () => { this.chart.get(id)?.remove(); li.remove(); };
    li.append(rm);
    this.activeUl.append(li);
  }
}
