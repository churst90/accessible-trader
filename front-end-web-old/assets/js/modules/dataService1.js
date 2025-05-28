// assets/js/modules/dataService.js

/**
 * Central API fetch helper.
 * Accepts optional `init` for POST/PUT.
 */
async function apiFetch(path, init = {}) {
  console.log('[dataService] fetching', path, init);
  const res = await fetch(path, {
    method: init.method || 'GET',
    headers: { 'Content-Type': 'application/json', ...(init.headers || {}) },
    credentials: 'same-origin',
    body: init.body
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} fetching ${path}`);
  }
  const payload = await res.json();
  if (payload.success === false) {
    throw new Error(payload.error?.message || 'API error');
  }
  return payload.data;
}

/** GET /api/market/providers?market=… */
export async function loadProviders(market) {
  const data = await apiFetch(`/api/market/providers?market=${encodeURIComponent(market)}`);
  return Array.isArray(data.providers) ? data.providers : [];
}

/** GET /api/market/symbols?… */
export async function loadSymbols(market, provider) {
  const qs = new URLSearchParams({ market, provider });
  const data = await apiFetch(`/api/market/symbols?${qs}`);
  return Array.isArray(data.symbols) ? data.symbols : [];
}

/**
 * GET /api/market/ohlcv?…&limit=…
 */
export async function fetchOhlcv({ market, provider, symbol, timeframe, since, before, limit = 100 }) {
  const q = { market, provider, symbol, timeframe, limit: `${limit}` };
  if (since  != null) q.since  = `${since}`;
  if (before != null) q.before = `${before}`;
  const qs = new URLSearchParams(q);
  const data = await apiFetch(`/api/market/ohlcv?${qs}`);
  return {
    ohlc:   Array.isArray(data.ohlc)   ? data.ohlc   : [],
    volume: Array.isArray(data.volume) ? data.volume : []
  };
}

/** POST /api/user/chart-configs */
export async function saveChartConfig(name, config) {
  return await apiFetch('/api/user/chart-configs', {
    method: 'POST',
    body: JSON.stringify({ name, config })
  });
}

/** GET /api/user/chart-configs */
export async function loadChartConfigs() {
  const data = await apiFetch('/api/user/chart-configs');
  return Array.isArray(data.configs) ? data.configs : [];
}
