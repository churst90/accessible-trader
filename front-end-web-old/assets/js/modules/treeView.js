// assets/js/modules/treeView.js

import { loadChartConfigs } from './dataService.js';

/**
 * Renders a flat list of saved chart configs as a simple
 * ARIA tree and calls `onSelect(config)` when one is chosen.
 */
export async function initObjectTree(onSelect) {
  const container = document.getElementById('object-tree');
  container.innerHTML = '';
  container.setAttribute('aria-label', 'Saved chart configurations');
  container.setAttribute('role', 'tree');

  let configs = [];
  try {
    configs = await loadChartConfigs();
  } catch (err) {
    console.error('Failed to load saved configs', err);
    return;
  }

  configs.forEach((item, i) => {
    const node = document.createElement('div');
    node.setAttribute('role', 'treeitem');
    node.setAttribute('tabindex', i === 0 ? '0' : '-1');
    node.dataset.config = JSON.stringify(item.config);
    node.textContent = item.name;
    container.append(node);
  });

  container.addEventListener('keydown', e => {
    const focusable = Array.from(container.querySelectorAll('[role="treeitem"]'));
    const idx = focusable.indexOf(document.activeElement);
    let nextIdx = -1;
    if (e.key === 'ArrowDown') nextIdx = Math.min(focusable.length - 1, idx + 1);
    if (e.key === 'ArrowUp')   nextIdx = Math.max(0, idx - 1);
    if (nextIdx >= 0) {
      focusable[nextIdx].focus();
      e.preventDefault();
    }
    if (e.key === 'Enter' && idx >= 0) {
      const cfg = JSON.parse(focusable[idx].dataset.config);
      onSelect(cfg);
    }
  });

  container.addEventListener('click', e => {
    const ti = e.target.closest('[role="treeitem"]');
    if (!ti) return;
    container.querySelector('[role="treeitem"][tabindex="0"]')
             .setAttribute('tabindex','-1');
    ti.setAttribute('tabindex','0');
    ti.focus();
    const cfg = JSON.parse(ti.dataset.config);
    onSelect(cfg);
  });
}
