// assets/js/modules/drawingPanel.js

import { getChart } from './chartStore.js';

const tools = [
  { key: 'trendline', label: 'Trend Line' },
  { key: 'rectangle', label: 'Rectangle' },
  { key: 'ellipse', label: 'Ellipse' },
  { key: 'circle', label: 'Circle' },
  { key: 'hline', label: 'Horizontal Line' },
  { key: 'vline', label: 'Vertical Line' },
  { key: 'fibonacci', label: 'Fibonacci Retracement' },
  { key: 'text', label: 'Text Note' }
];

export function initDrawingPanel(chart) {
  const openBtn = document.getElementById('stockTools-btn-annotations-advanced');
  const modal = document.getElementById('draw-dialog');
  const list = document.getElementById('draw-tool-list');
  const paramsDiv = document.getElementById('draw-params');
  const placeBtn = document.getElementById('draw-place');
  const cancelBtn = document.getElementById('draw-cancel');
  const activeAnnotationsUl = document.getElementById('active-annotations');

  let selectedTool = null;

  list.innerHTML = '';
  list.setAttribute('role', 'grid');
  list.setAttribute('aria-label', 'Choose a drawing tool');
  tools.forEach(t => {
    const btn = document.createElement('button');
    btn.setAttribute('role', 'gridcell');
    btn.tabIndex = 0;
    btn.textContent = t.label;
    btn.dataset.key = t.key;
    btn.onclick = () => {
      selectedTool = t.key;
      renderParams();
      list.querySelectorAll('button').forEach(b => {
        b.setAttribute('aria-pressed', b.dataset.key === selectedTool);
      });
    };
    list.append(btn);
  });

  function renderParams() {
    paramsDiv.innerHTML = '';
    function twoPts(extra = '') {
      ['Start', 'End'].forEach((lbl, i) => {
        const row = document.createElement('div');
        row.className = 'param-row';
        row.innerHTML = `
          <label>${lbl} Time: <input type="datetime-local" id="dt${i}" required></label>
          <label>${lbl} Price:<input type="number" id="pr${i}" required step="any"></label>
        `;
        paramsDiv.append(row);
      });
      if (extra) {
        const ex = document.createElement('div');
        ex.className = 'param-row';
        ex.innerHTML = extra;
        paramsDiv.append(ex);
      }
    }
    switch (selectedTool) {
      case 'trendline':
      case 'rectangle':
      case 'ellipse':
        twoPts();
        break;
      case 'fibonacci':
        twoPts(`<label>Levels (csv):<input id="levels" value="0.236,0.382,0.5,0.618,0.786"></label>`);
        break;
      case 'circle':
        paramsDiv.innerHTML = `
          <div class="param-row">
            <label>Center Time:<input type="datetime-local" id="dt0" required></label>
            <label>Center Price:<input type="number" id="pr0" required step="any"></label>
            <label>Radius X (ms):<input type="number" id="radX" value="86400000" required></label>
            <label>Radius Y:<input type="number" id="radY" value="100" required step="any"></label>
          </div>`;
        break;
      case 'hline':
        paramsDiv.innerHTML = `<div class="param-row">
          <label>Price:<input type="number" id="pr0" required step="any"></label>
        </div>`;
        break;
      case 'vline':
        paramsDiv.innerHTML = `<div class="param-row">
          <label>Time:<input type="datetime-local" id="dt0" required></label>
        </div>`;
        break;
      case 'text':
        paramsDiv.innerHTML = `<div class="param-row">
          <label>Time:<input type="datetime-local" id="dt0" required></label>
          <label>Price:<input type="number" id="pr0" required step="any"></label>
          <label>Note:<input type="text" id="txt" required></label>
        </div>`;
        break;
    }
    placeBtn.disabled = false;
    placeBtn.focus();
  }

  placeBtn.addEventListener('click', () => {
    const t = selectedTool;
    const val = id => document.getElementById(id).value;
    const dt = id => {
      const value = val(id);
      if (!value) throw new Error(`Time input (${id}) is required.`);
      const parsed = Date.parse(value);
      if (isNaN(parsed)) throw new Error(`Invalid time input (${id}): ${value}`);
      return parsed;
    };
    const pr = id => {
      const value = val(id);
      if (!value) throw new Error(`Price input (${id}) is required.`);
      const num = Number(value);
      if (isNaN(num)) throw new Error(`Invalid price input (${id}): ${value}`);
      return num;
    };

    try {
      const id = `ann-${Date.now()}`;
      let isSeries = false;

      if (['trendline', 'rectangle', 'hline', 'vline'].includes(t)) {
        isSeries = true;
        switch (t) {
          case 'trendline':
            const x1 = dt('dt0'), y1 = pr('pr0'), x2 = dt('dt1'), y2 = pr('pr1');
            chart.addSeries({
              id,
              type: 'line',
              name: 'Trend Line',
              data: [[x1, y1], [x2, y2]],
              showInLegend: true,
              marker: { enabled: false },
              enableMouseTracking: false,
              accessibility: { enabled: true },
              zIndex: 3
            }, false);
            break;
          case 'rectangle':
            const rx1 = dt('dt0'), ry1 = pr('pr0'), rx2 = dt('dt1'), ry2 = pr('pr1');
            chart.addSeries({
              id,
              type: 'polygon',
              name: 'Rectangle',
              data: [[rx1, ry1], [rx2, ry1], [rx2, ry2], [rx1, ry2]],
              showInLegend: true,
              color: 'rgba(200,200,200,0.4)',
              enableMouseTracking: false,
              accessibility: { enabled: true },
              zIndex: 2
            }, false);
            break;
          case 'hline':
            const y = pr('pr0');
            const xExtremes = chart.xAxis[0].getExtremes();
            chart.addSeries({
              id,
              type: 'line',
              name: `H-Line ${y}`,
              data: [[xExtremes.min, y], [xExtremes.max, y]],
              showInLegend: true,
              marker: { enabled: false },
              enableMouseTracking: false,
              accessibility: { enabled: true },
              zIndex: 2
            }, false);
            break;
          case 'vline':
            const x = dt('dt0');
            const yExtremes = chart.yAxis[0].getExtremes();
            chart.addSeries({
              id,
              type: 'line',
              name: `V-Line ${new Date(x).toLocaleString()}`,
              data: [[x, yExtremes.min], [x, yExtremes.max]],
              showInLegend: true,
              marker: { enabled: false },
              enableMouseTracking: false,
              accessibility: { enabled: true },
              zIndex: 2
            }, false);
            break;
        }
      } else {
        let annotation;
        switch (t) {
          case 'ellipse':
            const ex1 = dt('dt0'), ey1 = pr('pr0'), ex2 = dt('dt1'), ey2 = pr('pr1');
            annotation = {
              shapes: [{
                type: 'ellipse',
                x: (ex1 + ex2) / 2,
                y: (ey1 + ey2) / 2,
                rx: Math.abs(ex2 - ex1) / 2,
                ry: Math.abs(ey2 - ey1) / 2,
                xAxis: 0,
                yAxis: 0
              }]
            };
            break;
          case 'circle':
            const cx = dt('dt0'), cy = pr('pr0');
            const radX = Number(val('radX')), radY = Number(val('radY'));
            if (isNaN(radX) || isNaN(radY)) throw new Error('Invalid radius values');
            annotation = {
              shapes: [{
                type: 'circle',
                x: cx,
                y: cy,
                r: Math.max(radX, radY),
                xAxis: 0,
                yAxis: 0
              }]
            };
            break;
          case 'fibonacci':
            const fx1 = dt('dt0'), fy1 = pr('pr0'), fx2 = dt('dt1'), fy2 = pr('pr1');
            const levels = val('levels').split(',').map(Number).filter(n => !isNaN(n));
            if (levels.length === 0) throw new Error('Invalid Fibonacci levels');
            const yExtremes = chart.yAxis[0].getExtremes();
            annotation = {
              type: 'fibonacci',
              xAxis: 0,
              yAxis: 0,
              points: [
                { x: fx1, y: fy1 },
                { x: fx2, y: fy2 }
              ],
              labels: levels.map(level => ({
                point: { x: fx2, y: fy1 + (fy2 - fy1) * level },
                text: `${(level * 100).toFixed(1)}%`
              }))
            };
            break;
          case 'text':
            const tx = dt('dt0'), ty = pr('pr0');
            const text = val('txt');
            if (!text) throw new Error('Text note cannot be empty');
            annotation = {
              labels: [{
                point: { x: tx, y: ty, xAxis: 0, yAxis: 0 },
                text
              }]
            };
            break;
        }
        if (annotation) {
          annotation.id = id;
          chart.addAnnotation(annotation);
        }
      }

      chart.redraw();

      const li = document.createElement('li');
      li.textContent = `${t} `;
      const rm = document.createElement('button');
      rm.type = 'button';
      rm.textContent = 'Remove';
      rm.onclick = () => {
        if (isSeries) {
          chart.get(id)?.remove();
        } else {
          chart.removeAnnotation(id);
        }
        li.remove();
      };
      li.append(rm);
      activeAnnotationsUl.append(li);
    } catch (err) {
      console.error('Error adding annotation:', err);
      const liveRegion = document.getElementById('chartStatus');
      liveRegion.textContent = `Failed to add annotation: ${err.message}`;
    } finally {
      modal.hidden = true;
      openBtn.focus();
    }
  });

  cancelBtn.addEventListener('click', () => {
    modal.hidden = true;
    openBtn.focus();
  });

  modal.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      modal.hidden = true;
      openBtn.focus();
    }
  });

  modal.addEventListener('keydown', e => {
    if (e.key === 'Tab') {
      const focusable = modal.querySelectorAll('button, input, [tabindex="0"]');
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
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