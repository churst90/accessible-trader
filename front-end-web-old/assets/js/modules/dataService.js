// assets/js/modules/dataService.js

const API_ROOT = '/api';

/** Simple logger wrappers */
function log(...args) {
  console.log('[DataService]', ...args);
}
function errorLog(...args) {
  console.error('[DataService]', ...args);
}

/**
 * Builds a URL query string from an object.
 * @param {Object} params
 * @returns {string} e.g. "?a=1&b=2"
 */
function buildQuery(params = {}) {
  const parts = Object.entries(params)
    .filter(([,v]) => v != null)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`);
  return parts.length ? `?${parts.join('&')}` : '';
}

/**
 * Performs a JSON API request, throws on HTTP or API-level errors.
 * @param {string} path  – full path including query string
 * @param {RequestInit} init
 * @returns {Promise<any>}  – `data` field from the API payload
 */
async function apiFetch(path, init = {}) {
  log('?', path, init);
  let res;
  try {
    res = await fetch(path, {
      method: init.method ?? 'GET',
      headers: { 'Content-Type': 'application/json', ...(init.headers || {}) },
      credentials: 'same-origin',
      body: init.body
    });
  } catch (networkErr) {
    errorLog('Network error:', networkErr);
    throw new Error('Network error, please check your connection.');
  }

  if (!res.ok) {
    errorLog(`HTTP ${res.status} ${res.statusText}`);
    throw new Error(`Server returned ${res.status}`);
  }

  let payload;
  try {
    payload = await res.json();
  } catch (err) {
    errorLog('Invalid JSON:', err);
    throw new Error('Invalid server response');
  }

  if (payload.success === false) {
    const msg = payload.error?.message || 'Unknown API error';
    errorLog('API error payload:', msg);
    throw new Error(msg);
  }

  return payload.data;
}

// ——— Exported API methods ———

/** GET /api/market/providers?market=… */
export async function loadProviders(market) {
  const data = await apiFetch(
    `${API_ROOT}/market/providers${buildQuery({ market })}`
  );
  return Array.isArray(data.providers) ? data.providers : [];
}

/** GET /api/market/symbols?market=…&provider=… */
export async function loadSymbols(market, provider) {
  const data = await apiFetch(
    `${API_ROOT}/market/symbols${buildQuery({ market, provider })}`
  );
  return Array.isArray(data.symbols) ? data.symbols : [];
}

/** GET /api/market/ohlcv?… */
export async function fetchOhlcv({ market, provider, symbol, timeframe, since, before, limit = 100 }) {
  const q = { market, provider, symbol, timeframe, limit };
  if (since  != null) q.since  = since;
  if (before != null) q.before = before;
  const data = await apiFetch(`${API_ROOT}/market/ohlcv${buildQuery(q)}`);
  return {
    ohlc:   Array.isArray(data.ohlc)   ? data.ohlc   : [],
    volume: Array.isArray(data.volume) ? data.volume : []
  };
}

/** POST /api/user/chart-configs */
export async function saveChartConfig(name, config) {
  return await apiFetch(
    `${API_ROOT}/user/chart-configs`,
    { method: 'POST', body: JSON.stringify({ name, config }) }
  );
}

/** GET /api/user/chart-configs */
export async function loadChartConfigs() {
  const data = await apiFetch(`${API_ROOT}/user/chart-configs`);
  return Array.isArray(data.configs) ? data.configs : [];
}

/** GET /api/market/markets */
export async function loadAvailableMarkets() {
  log('Fetching available markets...');
  try {
    const data = await apiFetch(`${API_ROOT}/market/markets`);
    if (data && Array.isArray(data.markets)) {
      log('Available markets loaded:', data.markets);
      return data.markets;
    }
    errorLog('No markets array in response or data is null:', data);
    return [];
  } catch (err) {
    errorLog('Failed to load available markets:', err);
    throw err; // Re-throw for the caller to handle
  }
}
