// static/assets/js/modules/dataService.js

const API_ROOT = '/api';

/** Simple logger wrappers */
function log(...args) {
  console.log('[DataService]', ...args);
}
function errorLog(...args) {
  console.error('[DataService]', ...args);
}

// --- JWT Token Management ---
const JWT_TOKEN_KEY = 'jwtToken';

/**
 * Stores the JWT token in localStorage.
 * @param {string} token - The JWT token to store.
 */
function storeToken(token) {
  try {
    localStorage.setItem(JWT_TOKEN_KEY, token);
    log('Token stored in localStorage.');
  } catch (e) {
    errorLog('Error storing token in localStorage:', e);
    // Potentially alert user if localStorage is unavailable (e.g. private Browse, full storage)
  }
}

/**
 * Retrieves the JWT token from localStorage.
 * @returns {string|null} The JWT token or null if not found.
 */
function getToken() {
  try {
    return localStorage.getItem(JWT_TOKEN_KEY);
  } catch (e) {
    errorLog('Error retrieving token from localStorage:', e);
    return null;
  }
}

/**
 * Clears the JWT token from localStorage.
 */
function clearToken() {
  try {
    localStorage.removeItem(JWT_TOKEN_KEY);
    log('Token cleared from localStorage.');
  } catch (e) {
    errorLog('Error clearing token from localStorage:', e);
  }
}

/**
 * Builds a URL query string from an object.
 * @param {Object} params
 * @returns {string} e.g. "?a=1&b=2"
 */
function buildQuery(params = {}) {
  const parts = Object.entries(params)
    .filter(([,v]) => v != null) // Ensure value is not null or undefined before including
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`);
  return parts.length ? `?${parts.join('&')}` : '';
}

/**
 * Performs a JSON API request, throws on HTTP or API-level errors.
 * Automatically includes JWT token in Authorization header if available.
 * @param {string} path  – API endpoint path (e.g., `${API_ROOT}/market/providers`)
 * @param {RequestInit} [init={}] - Options for the fetch call (method, body, custom headers).
 * @returns {Promise<any>}  – `data` field from the API payload on success.
 * @throws {Error} If network error, HTTP error, or API reports failure. Error object may have `status` and `details`.
 */
async function apiFetch(path, init = {}) {
  log('API Fetch:', path, init.method || 'GET');
  let response; // Renamed from res for clarity
  const headers = {
    'Content-Type': 'application/json', // Default content type
    ...(init.headers || {}) // Spread any custom headers from init
  };

  const token = getToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
    // log('Authorization header added with JWT.'); // Can be noisy, remove if not needed for debugging
  }

  try {
    response = await fetch(path, {
      method: init.method ?? 'GET', // Default to GET if not specified
      headers: headers,
      credentials: 'same-origin', // For CSRF protection if backend uses session cookies for other parts
      body: init.body // Should be a JSON string if method is POST/PUT etc.
    });
  } catch (networkErr) {
    errorLog('Network error during API fetch:', path, networkErr);
    throw new Error('Network error. Please check your internet connection and try again.');
  }

  if (!response.ok) {
    let errorPayload = null;
    let errorResponseMessage = `Server error: ${response.status} ${response.statusText}`; // Default message
    try {
        errorPayload = await response.json();
        if (errorPayload && errorPayload.error && errorPayload.error.message) {
            errorResponseMessage = errorPayload.error.message; // Use server's specific error message
        }
    } catch (e) {
        log('Could not parse JSON from error response, using HTTP status text.', e);
    }
    errorLog(`HTTP Error ${response.status} for ${path}. Message:`, errorResponseMessage, 'Details:', errorPayload?.error?.details);
    const errorToThrow = new Error(errorResponseMessage);
    errorToThrow.status = response.status;
    errorToThrow.details = errorPayload?.error?.details;
    throw errorToThrow;
  }

  if (response.status === 204) { // Handle 204 No Content
    log('Received 204 No Content for', path);
    return null;
  }

  let payload;
  try {
    payload = await response.json();
  } catch (err) {
    errorLog('Invalid JSON in API success response:', path, err);
    throw new Error('Invalid server response (expected JSON).');
  }

  if (payload.success === false) { // Handle cases where HTTP is 200 OK but API indicates failure
    const msg = payload.error?.message || 'Unknown API error despite successful HTTP request.';
    errorLog('API reported error:', msg, 'Details:', payload.error?.details);
    const apiError = new Error(msg);
    apiError.details = payload.error?.details;
    throw apiError;
  }

  // log('API Fetch success:', path); // Can be noisy if logging full data
  return payload.data;
}

// --- Authentication API Calls ---

/**
 * Logs in a user.
 * POST /api/auth/login
 * @param {string} username
 * @param {string} password
 * @returns {Promise<string>} JWT token if successful.
 * @throws {Error} If login fails or API error occurs.
 */
export async function loginUser(username, password) {
  log(`Attempting login for user: ${username}`);
  try {
    const responseData = await apiFetch(
      `${API_ROOT}/auth/login`,
      {
        method: 'POST',
        body: JSON.stringify({ username, password })
      }
    );
    if (responseData && responseData.token) {
      storeToken(responseData.token);
      log('Login successful, token stored.');
      document.dispatchEvent(new CustomEvent('authChange', { detail: { loggedIn: true, token: responseData.token } }));
      return responseData.token;
    } else {
      errorLog('Login response did not contain a token:', responseData);
      throw new Error('Login failed: No token received from server.');
    }
  } catch (err) {
    errorLog('Login user error:', err.message, err.details || '');
    document.dispatchEvent(new CustomEvent('authChange', { detail: { loggedIn: false } }));
    throw err;
  }
}

/**
 * Refreshes an existing JWT token.
 * POST /api/auth/refresh
 * @param {string} currentToken The token to refresh.
 * @returns {Promise<string>} New JWT token if successful.
 * @throws {Error} If refresh fails (e.g., token expired, invalid) or API error.
 */
export async function refreshToken(currentToken) {
  log('Attempting to refresh token.');
  if (!currentToken) {
    errorLog('Refresh token: No current token provided to refresh function.');
    throw new Error('No token available to refresh.');
  }
  try {
    const responseData = await apiFetch(
      `${API_ROOT}/auth/refresh`,
      {
        method: 'POST',
        body: JSON.stringify({ token: currentToken })
      }
    );
    if (responseData && responseData.token) {
      storeToken(responseData.token);
      log('Token refreshed successfully.');
      document.dispatchEvent(new CustomEvent('authChange', { detail: { loggedIn: true, token: responseData.token } }));
      return responseData.token;
    } else {
      errorLog('Token refresh response did not contain a new token:', responseData);
      throw new Error('Token refresh failed: No new token received.');
    }
  } catch (err) {
    errorLog('Refresh token error:', err.message);
    clearToken(); // Critical: If refresh fails, the old token is likely invalid.
    document.dispatchEvent(new CustomEvent('authChange', { detail: { loggedIn: false } }));
    throw err;
  }
}

/**
 * Logs out the user by clearing the stored JWT.
 * Dispatches an 'authChange' event.
 */
export function logoutUser() {
  log('Logging out user (clearing token and dispatching authChange event).');
  clearToken();
  document.dispatchEvent(new CustomEvent('authChange', { detail: { loggedIn: false } }));
}

/**
 * Registers a new user.
 * Requires a corresponding backend endpoint (POST /api/auth/register).
 * @param {string} username
 * @param {string} email
 * @param {string} password
 * @returns {Promise<any>} Response data from the server (e.g., { message: "Registration successful." }).
 * @throws {Error} If registration fails or API error occurs.
 */
export async function registerUser(username, email, password) {
  log(`Attempting registration for user: ${username}`);
  try {
    const responseData = await apiFetch(
      `${API_ROOT}/auth/register`,
      {
        method: 'POST',
        body: JSON.stringify({ username, email, password })
      }
    );
    log('Registration API call successful:', responseData);
    // The backend currently returns { message: "Registration successful. Please log in." }
    // It does not auto-login or return a token.
    return responseData; // Contains the success message
  } catch (err) {
    errorLog('Register user error in dataService:', err.message, err.details || '');
    throw err; // Re-throw for the UI (e.g., auth_ui.js) to handle and display
  }
}


// --- Existing Exported API methods ---

/** GET /api/market/providers?market=… */
export async function loadProviders(market) {
  const data = await apiFetch(
    `${API_ROOT}/market/providers${buildQuery({ market })}`
  );
  return Array.isArray(data?.providers) ? data.providers : [];
}

/** GET /api/market/symbols?market=…&provider=… */
export async function loadSymbols(market, provider) {
  const data = await apiFetch(
    `${API_ROOT}/market/symbols${buildQuery({ market, provider })}`
  );
  return Array.isArray(data?.symbols) ? data.symbols : [];
}

/** GET /api/market/ohlcv?… */
export async function fetchOhlcv({ market, provider, symbol, timeframe, since, before, limit = 100 }) {
  const q = { market, provider, symbol, timeframe, limit };
  if (since  != null) q.since  = since;
  if (before != null) q.before = before;
  const data = await apiFetch(`${API_ROOT}/market/ohlcv${buildQuery(q)}`);
  return {
    ohlc:   Array.isArray(data?.ohlc)   ? data.ohlc   : [],
    volume: Array.isArray(data?.volume) ? data.volume : []
  };
}

/** POST /api/user/chart-configs - Needs review for Python backend alignment */
export async function saveChartConfig(name, config) {
  log('saveChartConfig: This function needs to be aligned with a Python backend endpoint for user preferences/layouts.');
  // Example: If you create a POST /api/user/layouts endpoint
  // return await apiFetch(
  //   `${API_ROOT}/user/layouts`,
  //   { method: 'POST', body: JSON.stringify({ layout_name: name, layout_config_json: config, /* other params like symbol/tf */ }) }
  // );
  console.warn("saveChartConfig is not fully implemented against the Python backend yet.");
  return Promise.reject(new Error("Saving chart config not implemented.")); // Indicate it's not ready
}

/** GET /api/user/chart-configs - Needs review for Python backend alignment */
export async function loadChartConfigs() {
  log('loadChartConfigs: This function needs to be aligned with a Python backend endpoint.');
  // Example: If you create a GET /api/user/layouts endpoint
  // const data = await apiFetch(`${API_ROOT}/user/layouts`);
  // return Array.isArray(data?.layouts) ? data.layouts : []; // Assuming backend returns { layouts: [...] }
  console.warn("loadChartConfigs is not fully implemented against the Python backend yet.");
  return Promise.resolve([]); // Return empty array for now
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
    throw err;
  }
}

// --- User Preferences/Settings ---
/**
 * Saves general user preferences.
 * POST /api/user/save_config
 * @param {object} configData - The preference data to save.
 * @returns {Promise<any>}
 */
export async function saveUserGeneralConfig(configData) {
    log('Saving user general config:', configData);
    return await apiFetch(`${API_ROOT}/user/save_config`, {
        method: 'POST',
        body: JSON.stringify(configData)
    });
}

/**
 * Fetches general user data/preferences.
 * GET /api/user/get_user_data
 * @returns {Promise<any>}
 */
export async function getUserGeneralData() {
    log('Fetching user general data.');
    return await apiFetch(`${API_ROOT}/user/get_user_data`);
}


// --- API Credentials ---
/**
 * Adds a new API credential for the user.
 * POST /api/credentials
 * @param {object} credentialData - { service_name, credential_name, api_key, api_secret?, aux_data?, is_testnet?, notes? }
 * @returns {Promise<any>}
 */
export async function addApiCredential(credentialData) {
    log('Adding API credential:', credentialData.credential_name);
    return await apiFetch(`${API_ROOT}/credentials`, {
        method: 'POST',
        body: JSON.stringify(credentialData)
    });
}

/**
 * Lists API credentials for the user.
 * GET /api/credentials
 * @returns {Promise<Array<object>>}
 */
export async function listApiCredentials() {
    log('Listing API credentials.');
    const data = await apiFetch(`${API_ROOT}/credentials`);
    return Array.isArray(data) ? data : []; // Backend directly returns an array of credentials
}

/**
 * Deletes a specific API credential.
 * DELETE /api/credentials/:credential_id
 * @param {number} credentialId
 * @returns {Promise<any>}
 */
export async function deleteApiCredential(credentialId) {
    log('Deleting API credential, ID:', credentialId);
    return await apiFetch(`${API_ROOT}/credentials/${credentialId}`, {
        method: 'DELETE'
    });
}


// --- Trading Endpoints ---
/**
 * Places a trading order.
 * POST /api/trading/order
 * @param {object} orderDetails - { credential_id, market, provider, symbol, side, order_type, amount, price?, params? }
 * @returns {Promise<any>} The order response from the server.
 */
export async function placeOrder(orderDetails) {
    log('Placing order:', orderDetails);
    return await apiFetch(`${API_ROOT}/trading/order`, {
        method: 'POST',
        body: JSON.stringify(orderDetails)
    });
}

/**
 * Gets the status of a specific order.
 * GET /api/trading/orders/:order_id_from_path?credential_id=...&market=...&provider=...&symbol=...
 * @param {string} orderIdFromPath - The exchange's order ID.
 * @param {number} credentialId - The credential ID used for the order.
 * @param {string} marketCategory - The general market category.
 * @param {string} providerName - The specific provider.
 * @param {string} [symbol] - Optional, but often required by exchanges.
 * @returns {Promise<any>} The order status details.
 */
export async function getOrderStatus(orderIdFromPath, credentialId, marketCategory, providerName, symbol) {
    log(`Fetching status for order ${orderIdFromPath} on ${providerName}`);
    const queryParams = { credential_id: credentialId, market: marketCategory, provider: providerName };
    if (symbol) {
        queryParams.symbol = symbol;
    }
    return await apiFetch(`${API_ROOT}/trading/orders/${orderIdFromPath}${buildQuery(queryParams)}`);
}

/**
 * Cancels a specific order.
 * DELETE /api/trading/orders/:order_id_from_path?credential_id=...&market=...&provider=...&symbol=...
 * @param {string} orderIdFromPath - The exchange's order ID.
 * @param {number} credentialId - The credential ID used for the order.
 * @param {string} marketCategory - The general market category.
 * @param {string} providerName - The specific provider.
 * @param {string} [symbol] - Optional, but often required by exchanges.
 * @returns {Promise<any>} The cancellation confirmation.
 */
export async function cancelOrder(orderIdFromPath, credentialId, marketCategory, providerName, symbol) {
    log(`Cancelling order ${orderIdFromPath} on ${providerName}`);
    const queryParams = { credential_id: credentialId, market: marketCategory, provider: providerName };
    if (symbol) {
        queryParams.symbol = symbol;
    }
    return await apiFetch(`${API_ROOT}/trading/orders/${orderIdFromPath}${buildQuery(queryParams)}`, {
        method: 'DELETE'
    });
}

/**
 * Fetches account balances.
 * GET /api/trading/balances?credential_id=...&market=...&provider=...
 * @param {number} credentialId
 * @param {string} marketCategory
 * @param {string} providerName
 * @returns {Promise<any>}
 */
export async function getAccountBalances(credentialId, marketCategory, providerName) {
    log(`Fetching account balances for provider ${providerName}`);
    return await apiFetch(`${API_ROOT}/trading/balances${buildQuery({
        credential_id: credentialId,
        market: marketCategory,
        provider: providerName
    })}`);
}

/**
 * Fetches open positions.
 * GET /api/trading/positions?credential_id=...&market=...&provider=...&symbols=...
 * @param {number} credentialId
 * @param {string} marketCategory
 * @param {string} providerName
 * @param {Array<string>} [symbols] - Optional list of symbols to filter by.
 * @returns {Promise<any>}
 */
export async function getOpenPositions(credentialId, marketCategory, providerName, symbols) {
    log(`Fetching open positions for provider ${providerName}`);
    const queryParams = {
        credential_id: credentialId,
        market: marketCategory,
        provider: providerName
    };
    if (symbols && symbols.length > 0) {
        queryParams.symbols = symbols.join(',');
    }
    return await apiFetch(`${API_ROOT}/trading/positions${buildQuery(queryParams)}`);
}


// --- Trading Bot Endpoints ---
/**
 * Creates a new trading bot configuration.
 * POST /api/bots
 * @param {object} botData
 * @returns {Promise<any>}
 */
export async function createBotConfig(botData) {
    log('Creating bot config:', botData.bot_name);
    return await apiFetch(`${API_ROOT}/bots`, {
        method: 'POST',
        body: JSON.stringify(botData)
    });
}

/**
 * Lists all trading bot configurations for the user.
 * GET /api/bots
 * @returns {Promise<Array<object>>}
 */
export async function listUserBots() {
    log('Listing user bots.');
    const data = await apiFetch(`${API_ROOT}/bots`);
    return Array.isArray(data) ? data : []; // Backend returns an array
}

/**
 * Gets details for a specific bot.
 * GET /api/bots/:bot_id
 * @param {number} botId
 * @returns {Promise<any>}
 */
export async function getBotDetails(botId) {
    log('Fetching details for bot ID:', botId);
    return await apiFetch(`${API_ROOT}/bots/${botId}`);
}

/**
 * Updates an existing bot configuration.
 * PUT /api/bots/:bot_id
 * @param {number} botId
 * @param {object} updateData
 * @returns {Promise<any>}
 */
export async function updateBotConfig(botId, updateData) {
    log('Updating bot config, ID:', botId);
    return await apiFetch(`${API_ROOT}/bots/${botId}`, {
        method: 'PUT',
        body: JSON.stringify(updateData)
    });
}

/**
 * Deletes a bot configuration.
 * DELETE /api/bots/:bot_id
 * @param {number} botId
 * @returns {Promise<any>}
 */
export async function deleteBotConfig(botId) {
    log('Deleting bot config, ID:', botId);
    return await apiFetch(`${API_ROOT}/bots/${botId}`, {
        method: 'DELETE'
    });
}

/**
 * Starts a trading bot.
 * POST /api/bots/:bot_id/start
 * @param {number} botId
 * @returns {Promise<any>}
 */
export async function startBot(botId) {
    log('Starting bot, ID:', botId);
    return await apiFetch(`${API_ROOT}/bots/${botId}/start`, {
        method: 'POST'
    });
}

/**
 * Stops a trading bot.
 * POST /api/bots/:bot_id/stop
 * @param {number} botId
 * @returns {Promise<any>}
 */
export async function stopBot(botId) {
    log('Stopping bot, ID:', botId);
    return await apiFetch(`${API_ROOT}/bots/${botId}/stop`, {
        method: 'POST'
    });
}


// --- Market Data Endpoints (Specific) ---
/**
 * Fetches detailed trading rules and parameters for a specific instrument.
 * GET /api/market/:market/:provider/:symbol/trading-details?market_type=...
 * @param {string} marketCategory - e.g., "crypto"
 * @param {string} providerName - e.g., "binance"
 * @param {string} symbol - e.g., "BTC/USDT" (will be URL encoded)
 * @param {string} [marketType="spot"] - e.g., "spot", "futures"
 * @returns {Promise<any>}
 */
export async function getInstrumentTradingDetails(marketCategory, providerName, symbol, marketType = 'spot') {
    log(`Fetching trading details for ${symbol} on ${providerName}, type ${marketType}`);
    // Symbol might contain slashes, ensure it's properly encoded in the path by fetch,
    // or pre-encode if necessary (though fetch usually handles it for path segments if not part of query).
    // For safety, let's assume symbol is a single segment here. If it can have slashes that need to be part of path,
    // the backend route needs to handle <path:symbol>.
    return await apiFetch(`${API_ROOT}/market/${marketCategory}/${providerName}/${encodeURIComponent(symbol)}/trading-details${buildQuery({ market_type: marketType })}`);
}