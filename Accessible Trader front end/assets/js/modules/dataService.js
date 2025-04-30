// assets/js/modules/dataService.js

/**
 * Utility to call your Quart endpoints.
 */
async function apiFetch(path) {
  console.log('[dataService] fetching', path);
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
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

/** GET /api/market/providers?market=crypto|stocks */
export async function loadProviders(market) {
  const data = await apiFetch(`/api/market/providers?market=${encodeURIComponent(market)}`);
  return Array.isArray(data.providers) ? data.providers : [];
}

/** GET /api/market/symbols?market=…&provider=… */
export async function loadSymbols(market, provider) {
  const qs = new URLSearchParams({ market, provider });
  const data = await apiFetch(`/api/market/symbols?${qs}`);
  return Array.isArray(data.symbols) ? data.symbols : [];
}

/**
 * GET /api/market/ohlcv?market=…&provider=…&symbol=…&timeframe=…&limit=…[&since=…][&before=…]
 */
export async function fetchOhlcv({
  market, provider, symbol, timeframe, since, before, limit = 100
}) {
  const q = { market, provider, symbol, timeframe, limit: `${limit}` };
  if (since != null)  q.since  = `${since}`;
  if (before != null) q.before = `${before}`;
  const qs = new URLSearchParams(q);
  const data = await apiFetch(`/api/market/ohlcv?${qs}`);
  return {
    ohlc:   Array.isArray(data.ohlc)   ? data.ohlc   : [],
    volume: Array.isArray(data.volume) ? data.volume : [],
  };
}
