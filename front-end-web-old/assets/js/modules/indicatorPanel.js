// assets/js/modules/indicatorPanel.js
import { getChart } from './chartStore.js';
import IndicatorSettings from './indicatorSettings.js'; // Import IndicatorSettings

export default class IndicatorPanel {
  constructor() {
    this.openBtn = document.getElementById('stockTools-btn-indicators');
    this.closeBtn = document.getElementById('indicator-close');
    this.modal = document.getElementById('indicator-modal');
    this.paramsEl = document.getElementById('indicator-params');
    this.addBtn = document.getElementById('indicator-add');
    this.activeUl = document.getElementById('active-indicators');
    this.liveRegion = document.getElementById('chartStatus');

    this.tabs = {
      Overlays: document.getElementById('tab-overlays'),
      Oscillators: document.getElementById('tab-osc'),
      Volume: document.getElementById('tab-vol'),
    };
    this.panels = {
      Overlays: document.getElementById('panel-overlays'),
      Oscillators: document.getElementById('panel-osc'),
      Volume: document.getElementById('panel-vol'),
    };
    this.categoryNames = ['Overlays', 'Oscillators', 'Volume'];

    const H = window.Highcharts;

    // Define default parameters for all indicators
    const defaultParams = {
      sma: { period: 14 },
      ema: { period: 14 },
      bb: { period: 20, standardDeviation: 2 },
      tema: { period: 14 },
      dema: { period: 14 },
      wma: { period: 14 },
      zema: { period: 14 },
      vwap: {},
      rsi: { period: 14 },
      macd: { fastPeriod: 12, slowPeriod: 26, signalPeriod: 9 },
      stochastic: { period: 14, kPeriod: 3, dPeriod: 3 },
      cci: { period: 20 },
      adx: { period: 14 },
      momentum: { period: 14 },
      mfi: { period: 14 },
      chaikin: {},
      obv: {},
      vbp: { volumeByPriceLength: 12 }
    };

    this.allIndicators = Object.keys(defaultParams).map(type => ({
      type,
      params: defaultParams[type]
    }));

    const groups = {
      Overlays: ['sma', 'ema', 'bb', 'tema', 'dema', 'wma', 'zema', 'vwap'],
      Oscillators: ['rsi', 'macd', 'stochastic', 'cci', 'adx', 'momentum', 'mfi', 'chaikin'],
      Volume: ['obv', 'vbp']
    };

    this.categories = {};
    this.categoryNames.forEach(cat => {
      this.categories[cat] = this.allIndicators
        .filter(i => groups[cat].includes(i.type));
    });

    const used = new Set([].concat(...Object.values(groups)));
    const others = this.allIndicators.filter(i => !used.has(i.type));
    this.categories.Overlays.push(...others);

    this._bindDialog();
  }

  _bindDialog() {
    this.openBtn.addEventListener('click', () => {
      this.chart = getChart();
      if (!this.chart) return alert('Please Refresh Chart first.');

      this._buildTabs();
      this._populatePanels();

      this.modal.hidden = false;
      this.addBtn.disabled = true;
      this.tabs.Overlays.focus();
      this._trapFocus();
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

  _trapFocus() {
    const focusable = this.modal.querySelectorAll('button, input, [tabindex="0"]');
    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    this.modal.addEventListener('keydown', e => {
      if (e.key === 'Tab') {
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
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
      grid.setAttribute('role', 'grid');
      grid.classList.add('indicator-grid');
      panel.append(grid);

      this.categories[cat].forEach(item => {
        const label = (H.getOptions().lang[item.type] || item.type).toUpperCase();
        const btn = document.createElement('button');
        btn.setAttribute('role', 'gridcell');
        btn.tabIndex = 0;
        btn.textContent = label;
        btn.onclick = () => this._openParamForm(cat, item);
        grid.append(btn);
      });
    });

    if (['Overlays', 'Oscillators'].includes(this.currentCategory)) {
      const seriesRow = document.createElement('div');
      seriesRow.className = 'param-row';
      seriesRow.innerHTML = `
        <label for="series-select">Link to Series:</label>
        <select id="series-select"></select>
      `;
      this.paramsEl.append(seriesRow);
      this._populateSeriesDropdown();
    }
  }

  _populateSeriesDropdown() {
    const select = this.paramsEl.querySelector('#series-select');
    if (!select || !this.chart) return;

    select.innerHTML = '';
    this.chart.series.forEach(series => {
      if (series.options.id && series.options.id !== 'vol' && series.options.id !== 'price-line') {
        const option = new Option(series.name, series.options.id);
        select.append(option);
      }
    });
    select.value = 'ohlc';
  }

  _openParamForm(category, item) {
    this.currentCategory = category;
    this.currentItem = item;
    this.paramsEl.innerHTML = '';

    if (['Overlays', 'Oscillators'].includes(category)) {
      const seriesRow = document.createElement('div');
      seriesRow.className = 'param-row';
      seriesRow.innerHTML = `
        <label for="series-select">Link to Series:</label>
        <select id="series-select"></select>
      `;
      this.paramsEl.append(seriesRow);
      this._populateSeriesDropdown();
    }

    const params = item.params || {};
    Object.entries(params).forEach(([name, defaultValue]) => {
      const row = document.createElement('div');
      row.className = 'param-row';
      row.innerHTML = `
        <label for="ind-${name}">
          ${name.charAt(0).toUpperCase() + name.slice(1)}: 
          <input id="ind-${name}" type="number" value="${defaultValue || ''}" />
        </label>`;
      this.paramsEl.append(row);
    });

    this.addBtn.disabled = false;
    this.addBtn.focus();
    this.addBtn.onclick = () => this._addSeries();
  }

  _addSeries() {
    const H = window.Highcharts;
    const item = this.currentItem;
    const cat = this.currentCategory;
    if (!item || !this.chart) return;

    try {
      const params = item.params || {};
      const cfg = {};
      Object.keys(params).forEach(name => {
        const el = document.getElementById(`ind-${name}`);
        if (el && el.value !== '') cfg[name] = Number(el.value);
      });

      let linkedTo;
      if (['Overlays', 'Oscillators'].includes(cat)) {
        linkedTo = this.paramsEl.querySelector('#series-select')?.value || 'ohlc';
      }

      const desc = Object.entries(cfg).map(([k, v]) => `${k}=${v}`).join(',');
      const seriesName = desc
        ? `${item.type.toUpperCase()} (${desc})`
        : item.type.toUpperCase();

      // Define Y-axis mapping
      const axisMap = { Overlays: 0, Volume: 1 };
      let yAxis = axisMap[cat] ?? 0;

      // Handle volume-dependent indicators
      const requiresVolume = ['mfi', 'obv', 'vbp', 'vwap', 'chaikin'].includes(item.type);
      if (requiresVolume) {
        const volSeries = this.chart.get('vol');
        if (!volSeries) {
          console.log(`Creating 'vol' series for ${item.type}`);
          this.chart.addSeries({
            id: 'vol',
            name: 'Volume',
            type: 'column',
            data: [],
            yAxis: 1,
            zIndex: 1
          }, false);
        } else {
          console.log(`'vol' series found for ${item.type}, data length: ${volSeries.data.length}`);
        }
        cfg.volumeSeriesID = 'vol';
      }

      const id = `${item.type}-${Date.now()}`;
      const seriesOptions = {
        id,
        type: item.type,
        name: seriesName,
        params: cfg,
        yAxis,
        linkedTo: linkedTo,
        showInLegend: true
      };

      // Special handling for volume indicators
      if (cat === 'Volume') {
        // Ensure volume panel exists
        const volAxis = this.chart.yAxis.find(axis => axis.userOptions.id === 'volume-axis');
        if (!volAxis) {
          this.chart.addAxis({
            id: 'volume-axis',
            title: { text: 'Volume' },
            height: '15%',
            top: '65%',
            offset: 0,
            opposite: false
          }, false);
          seriesOptions.yAxis = 'volume-axis';
        } else {
          seriesOptions.yAxis = 'volume-axis';
        }

        // For OBV, add a secondary Y-axis within the volume panel
        if (item.type === 'obv') {
          const obvAxis = this.chart.yAxis.find(axis => axis.userOptions.id === 'obv-axis');
          if (!obvAxis) {
            this.chart.addAxis({
              id: 'obv-axis',
              title: { text: 'OBV' },
              height: '15%',
              top: '65%',
              offset: 0,
              opposite: true
            }, false);
            seriesOptions.yAxis = 'obv-axis';
          } else {
            seriesOptions.yAxis = 'obv-axis';
          }
        }
      }

      // Each oscillator gets its own panel
      if (cat === 'Oscillators') {
        // Count existing oscillator axes to determine the position
        const oscAxes = this.chart.yAxis.filter(axis => axis.userOptions.id && axis.userOptions.id.startsWith('oscillator-'));
        const panelIndex = oscAxes.length;
        const panelHeight = 10; // Each oscillator panel is 10% height
        const baseTop = 80; // Start after volume panel (65% + 15%)
        const top = baseTop + (panelIndex * panelHeight);

        const axisId = `oscillator-${item.type}-${id}`;
        this.chart.addAxis({
          id: axisId,
          title: { text: seriesName },
          height: `${panelHeight}%`,
          top: `${top}%`,
          offset: 0,
          opposite: false
        }, false);
        seriesOptions.yAxis = axisId;
      }

      console.log(`Adding ${item.type} with id=${id}, yAxis=${seriesOptions.yAxis}, params=`, cfg);
      this.chart.addSeries(seriesOptions, false);
      this.chart.redraw();
      this.liveRegion.textContent = `Added ${seriesName}`;

      // Add to active indicators list with Edit and Remove buttons
      const li = document.createElement('li');
      const indicatorLabel = document.createElement('span');
      indicatorLabel.textContent = seriesName;
      li.appendChild(indicatorLabel);

      // Edit button
      const editBtn = document.createElement('button');
      editBtn.type = 'button';
      editBtn.textContent = 'Edit';
      editBtn.setAttribute('aria-label', `Edit ${seriesName} indicator`);
      editBtn.onclick = () => {
        const indicatorData = {
          id,
          type: item.type,
          params: cfg,
          yAxis: seriesOptions.yAxis
        };
        new IndicatorSettings(
          indicatorData,
          updatedSettings => {
            // Update the series with new settings
            const series = this.chart.get(id);
            if (series) {
              const newName = Object.entries(updatedSettings.params)
                .map(([k, v]) => `${k}=${v}`)
                .join(',');
              const updatedSeriesName = newName ? `${item.type.toUpperCase()} (${newName})` : item.type.toUpperCase();
              series.update({
                name: updatedSeriesName,
                params: updatedSettings.params,
                color: updatedSettings.visual.color,
                lineWidth: updatedSettings.visual.lineWidth,
                sonification: {
                  enabled: true,
                  instrument: updatedSettings.sonify.instrument,
                  masterVolume: updatedSettings.sonify.volume
                }
              }, false);
              // Update the Y-axis title if it's an oscillator
              if (cat === 'Oscillators') {
                const axis = this.chart.yAxis.find(ax => ax.userOptions.id === seriesOptions.yAxis);
                if (axis) {
                  axis.update({ title: { text: updatedSeriesName } }, false);
                }
              }
              this.chart.redraw();
              indicatorLabel.textContent = updatedSeriesName;
              this.liveRegion.textContent = `Updated ${updatedSeriesName}`;
            }
          },
          () => {
            this.openBtn.focus();
          }
        );
      };

      // Remove button
      const rmBtn = document.createElement('button');
      rmBtn.type = 'button';
      rmBtn.textContent = 'Remove';
      rmBtn.setAttribute('aria-label', `Remove ${seriesName} indicator`);
      rmBtn.onclick = () => {
        const series = this.chart.get(id);
        if (series) {
          series.remove();
          li.remove();
          this.liveRegion.textContent = `Removed ${seriesName}`;
        }
      };

      li.append(editBtn, rmBtn);
      this.activeUl.append(li);
    } catch (err) {
      console.error(`Error adding indicator ${item.type}:`, err);
      this.liveRegion.textContent = `Failed to add indicator: ${err.message}`;
    } finally {
      this.modal.hidden = true;
      this.openBtn.focus();
    }
  }
}