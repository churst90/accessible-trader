# Project TODO List (Backend & Frontend Integration)

This document outlines tasks to enhance the server codebase and integrate the frontend, focusing on performance, scalability, maintainability, usability, and robustness.

## Critical Priority (Frontend Integration & Core Functionality)

### Finalize Quart Serving HTML Pages
- **Status**: Partially Complete
- **Description**: Ensure Quart backend correctly serves all static HTML shell pages for the frontend application (`index.html`, `chart.html`, `login.html`, `register.html`, `faq.html`, `support.html`, and future pages like `credentials.html`, `bots.html`, `profile.html`).
- **Action**:
    - Verify all routes in `views.py` correctly render the corresponding Jinja2 templates from the `templates/` directory.
    - Confirm `app.static_folder` and `app.static_url_path` in `app.py` are correctly configured and serving CSS/JS from `static/assets/`.
    - Test all page navigations.
- **Impact**: Essential for the new frontend structure to function.

### Implement Client-Side Authentication UI & Logic
- **Status**: Partially Complete (Backend login/refresh/register exists, `dataService.js` updated, `auth_ui.js` started)
- **Description**: Enable full client-side user login and registration flows, JWT management, and dynamic UI updates based on authentication state.
- **Action**:
    1.  **`auth_ui.js`:**
        * Complete and test `handleLoginFormSubmit` to use `dataService.loginUser`, store JWT, update UI via `authChange` event, and redirect.
        * Complete and test `handleRegisterFormSubmit` to use `dataService.registerUser`, display success/error, and redirect to login.
        * Refine `updateAuthUI` to correctly show/hide all auth-dependent navigation links (`Profile`, `API Keys`, `Trading Bots`, `Logout`) and the "Trading Dashboard" section on the chart page based on JWT presence in `localStorage`.
        * Implement logic to fetch user details (e.g., username for "Profile" link) after login if JWT doesn't contain all needed display info (may require a new `/api/user/me` endpoint).
    2.  **`dataService.js`:**
        * Ensure `apiFetch` correctly handles various success/error responses from the Python backend and propagates them for UI display.
    3.  **HTML Templates:**
        * Ensure `login.html` and `register.html` forms have correct element IDs for `auth_ui.js` to target.
        * Ensure `layout.html` has correct IDs and classes for auth-dependent navigation links.
- **Impact**: Core user functionality for accessing protected features and personalization.

### Develop API Credentials Management UI (Frontend)
- **Status**: Not Started (Backend endpoints exist)
- **Description**: Create the frontend page and JavaScript logic for users to add, list, and delete their API credentials.
- **Action**:
    1.  Create `templates/credentials.html` (served by `views.py`, requires login).
    2.  Create `static/assets/js/credentials_ui.js` (or similar).
    3.  Use `dataService.js` functions (`listApiCredentials`, `addApiCredential`, `deleteApiCredential`) to interact with `/api/credentials` endpoints.
    4.  Display credentials in a table, provide forms for adding new ones.
    5.  Ensure secure handling of displaying any sensitive info (though keys should remain encrypted on backend and not be sent back to UI).
- **Impact**: Allows users to connect their exchange accounts for trading and bot functionality.

## High Priority (Backend & Core Features)

### Parallelize Backfill Chunks for a Single Asset
- **Status**: Partially Complete
  - *Note*: Global semaphore exists, but per-asset chunk/gap parallelism needs improvement.
- **Description**: Accelerate historical backfills for a single asset by fetching missing chunks/gaps in parallel, while adhering to API rate limits.
- **Action**: Modify `BackfillManager._run_historical_backfill` to use `asyncio.gather` for concurrent fetching of multiple chunks/gaps for the same asset. Coordinate using the asset’s instance or a finer-grained semaphore if the global semaphore is insufficient.
- **Impact**: Significantly reduces backfill time for individual assets.

### Develop Unit Tests
- **Status**: Not Started
- **Description**: Create unit tests for core backend components.
- **Action**: Use `pytest` and `pytest-asyncio` to write tests, mocking external dependencies. Cover `MarketService`, `DataOrchestrator`, Plugins (especially `CCXTPlugin` transformations), `SubscriptionService`, `StreamingManager`, `CacheManager`, and `BackfillManager`. Test `auth.py` and `user_credentials.py` blueprint logic.
- **Impact**: Improves code reliability and enables safe refactoring.

### Create Integration Tests
- **Status**: Not Started
- **Description**: Validate end-to-end behavior of the system.
- **Action**: Set up a test environment using Quart test client, WebSocket test client, and mock plugins/database. Test API calls (auth, market data, credentials, bots, trading), WebSocket subscription lifecycle, and error handling.
- **Impact**: Ensures system-level correctness.

### Implement Finer-Grained Caching for 1m Bars
- **Status**: Not Started
- **Description**: Cache 1-minute bars in smaller time buckets (e.g., hourly or daily) in `RedisCache` instead of one large list per symbol.
- **Action**: Update `RedisCache.store_1m_bars` and `get_1m_bars` to use time-bucketed keys.
- **Impact**: Improves cache hit rates for 1-minute data and reduces Redis memory usage for long time series when only partial data is needed.

### User Service: Full CRUD for User Preferences & Saved Entities
- **Status**: Partially Complete (`save_user_config`, `get_user_data` exist for general prefs)
- **Description**: Expand `user_service.py` and corresponding blueprints for full CRUD operations on `UserChartLayouts` and `UserIndicatorPresets`.
- **Action**:
    1. Define models in `user_config_models.py` (already done).
    2. Implement service functions in `user_service.py`.
    3. Create blueprint routes in `blueprints/user.py` (or a new dedicated blueprint e.g., `user_preferences.py`) for these entities.
    4. Update `dataService.js` with functions to call these new endpoints.
    5. Implement UI for saving/loading chart layouts (using `initObjectTree` in `uiBindings.js`) and indicator presets (in `IndicatorPanel.js`).
- **Impact**: Enables user personalization and persistence of settings.

## Medium Priority

### Frontend: Trading Panel Implementation
- **Status**: Not Started (HTML placeholders exist)
- **Description**: Implement the full functionality of the "Trading Dashboard" on `chart.html`.
- **Action**:
    1.  **`tradingPanel.js` (New):** Create this module.
    2.  **Credential Selection:** Populate "Active API Credential" dropdown. On selection, enable trading features.
    3.  **Manual Trade Form:**
        * Populate "Symbol" from the current chart.
        * Handle "Limit" order type showing/hiding price input.
        * On submit, use `dataService.placeOrder`. Display success/error.
        * Fetch and display instrument trading details (`getInstrumentTradingDetails`) to guide user input for precision/limits.
    4.  **Order Book & Live Trades:**
        * Implement `orderBookDisplay.js` and `tradesFeedDisplay.js`.
        * Modify `ChartController` or `wsService` to allow subscriptions to `order_book` and `trades` stream types.
        * `ChartController` or these modules receive WebSocket updates and render them.
    5.  **Open Orders & Positions:**
        * Implement "Refresh" buttons to call `dataService.getOrderStatus` (needs `/api/trading/orders` GET endpoint for multiple open orders), `dataService.getOpenPositions`.
        * Display data in tables/lists. Implement "Cancel" for open orders.
    6.  **Account Balances:** Fetch and display using `dataService.getAccountBalances`.
- **Impact**: Enables core manual trading functionality from the UI.

### Frontend: Bot Management UI
- **Status**: Not Started (Backend endpoints exist)
- **Description**: Develop the frontend page (`bots.html`) for users to manage their trading bots.
- **Action**:
    1. Create `templates/bots.html`.
    2. Create `static/assets/js/bot_manager_ui.js` (or similar).
    3. Use `dataService.js` functions (`listUserBots`, `createBotConfig`, `getBotDetails`, `updateBotConfig`, `deleteBotConfig`, `startBot`, `stopBot`).
    4. Implement UI for: listing bots, viewing status, starting/stopping, creating new bot configurations (form), editing existing ones, deleting.
- **Impact**: Allows users to utilize the automated trading features.

### Market-Specific Symbol Filtering in Plugins (Backend)
- **Status**: Partially Complete / Framework in Place
- **Description**: Ensure `MarketPlugin.get_symbols` method and its implementations correctly use the `market` (asset class/type) parameter to filter symbols relevant to the user-selected market. This is crucial for plugins handling multiple distinct asset classes or types under one provider.
- **Action**:
    1.  `MarketPlugin.get_symbols` signature updated to accept `market: str`. (**DONE**)
    2.  `MarketService.get_symbols` passes the `market` argument to the plugin. (**DONE**)
    3.  **For `CCXTPlugin`**:
        * Currently returns all active symbols from the exchange, assuming they all fall under its `supported_markets = ["crypto"]`. The `market` parameter is passed but not used for further sub-filtering by instrument type (e.g., spot, future).
        * **Further Action (If Needed)**: If granular market definitions like "crypto_spot" or "crypto_futures" are added to `CCXTPlugin.supported_markets` and exposed to the user, then `CCXTPlugin.get_symbols` needs to be updated to filter its results based on `market_data['type']` matching the specific `market` argument (e.g., if `market == "crypto_spot"`, only return symbols where `market_data['type'] == 'spot'`).
    4.  **For Future Plugins (e.g., AlpacaPlugin)**: When implementing, ensure `get_symbols(self, market: str)` correctly filters symbols based on the provided `market` (e.g., if `market="stocks"`, only return stock symbols, if `market="crypto"`, only crypto symbols).
    5.  Ensure each plugin's `supported_markets` static variable accurately reflects all distinct, filterable market categories or types it can provide symbols for.
- **Impact**: Improves user experience by filtering symbols for multi-asset class/type providers and ensures data relevance.

### Refine `RedisCache` Serialization for `None`/`NaN`/`Infinity`
- **Status**: Not Started
  - *Note*: Currently converts `None`, `NaN`, and `Infinity` to `0.0` in `_serialize_bars`.
- **Description**: Improve `RedisCache._serialize_bars` to handle `None`, `NaN`, and `Infinity` correctly, preventing loss of distinct meaning.
- **Action**: Modify `_serialize_bars` to serialize `None` as `null` and handle `NaN`/`Infinity` as strings (e.g., `"NaN"`, `"Infinity"`), ensuring compatibility.
- **Impact**: Enhances data fidelity in the cache.

### Centralize Bar Filtering Logic (Backend)
- **Status**: Not Started
- **Description**: Consolidate similar filtering logic (`since`, `before`, `limit`) in `CacheSource._filter_bars` and `DataOrchestrator._apply_filters`.
- **Action**: Create a common utility function for filtering logic and use it.
- **Impact**: Reduces code redundancy.

### Use Redis Pipelines for Batch Cache Operations (Backend)
- **Status**: Not Started
- **Description**: Optimize multiple Redis writes in `RedisCache` by using pipelines.
- **Action**: Modify `RedisCache` methods that perform multiple `setex` or other commands in a loop to use `redis.asyncio.pipeline()`.
- **Impact**: Improves caching performance.

### Add Manual Refresh for Continuous Aggregates (Backend)
- **Status**: Not Started
- **Description**: Implement a mechanism to manually refresh TimescaleDB continuous aggregates.
- **Action**: Add an admin endpoint or scheduled task to call `CALL refresh_continuous_aggregate(...)`.
- **Impact**: Ensures data integrity for higher timeframes.

### Prioritize Real-Time Subscriptions Over Backfill (Backend)
- **Status**: Not Started
- **Description**: Implement a mechanism to pause or throttle backfills during high load.
- **Action**: Add load monitoring. Enable `BackfillManager` tasks to be paused/resumed or adjust `_api_semaphore` dynamically.
- **Impact**: Ensures low latency for real-time clients.

### Centralize Validation with Pydantic (Backend)
- **Status**: Not Started
- **Description**: Use Pydantic for request and response schema validation in API blueprints.
- **Action**: Define Pydantic models and integrate them with Quart routes.
- **Impact**: Simplifies maintenance and ensures consistent validation.

### Expand Prometheus Metrics (Backend)
- **Status**: Partially Complete
- **Description**: Add/restore metrics for `DataOrchestrator`, WebSocket connections, and subscription rates.
- **Action**: Integrate `prometheus_client` further.
- **Impact**: Enhances system monitoring.

### Correct `DEFAULT_BACKFILL_PERIOD_MS` Comment/Value in `config.py`
- **Status**: Not Started
- **Description**: The comment in `config.py` for `DEFAULT_BACKFILL_PERIOD_MS` states "~10 years" but the value is `315576000000`, which is 10 years. The `.env` file, however, has `DEFAULT_BACKFILL_PERIOD_MS=2592000000` (30 days). The actual default being used is from `config.py` if the env var isn't set or is overridden.
- **Action**: Clarify the intended default backfill period. Ensure the comment in `config.py` matches the default value set there, and that the `.env` variable is understood as an override. The current Python default is 10 years (`str(3155760000000)`) which seems too long if the .env has 30 days.
- **Impact**: Improves configuration clarity and ensures intended backfill behavior. *Correction: The previous value was for 100 years, then updated to 10 years in code. The `.env` uses 30 days. The `config.py` has `str(315576000000)` which is 10 years for `DEFAULT_BACKFILL_PERIOD_MS`. The current discrepancy is between this 10-year default in code and the 30-day example in the `.env` comments you provided with the original code dump (actual `.env` has 30 days).*

## Low Priority

### Frontend: Profile Page
- **Status**: Not Started
- **Description**: Implement a basic user profile page.
- **Action**: Create `templates/profile.html`. Display user information (username, email, registration date - may need a `/api/user/me` endpoint). Allow changing profile details (e.g., nickname, bio - requires backend update to `user_service.py` and `blueprints/user.py`).
- **Impact**: Basic user account management.

### Validate Plugin Parameters (Backend)
- **Status**: Not Started
- **Description**: Add validation for `plugin_params` passed to `MarketService.fetch_ohlcv`.
- **Action**: Define allowed parameters in `MarketPlugin` subclasses and validate.
- **Impact**: Prevents plugin errors due to invalid parameters.

### Create OpenAPI Specification (Backend)
- **Status**: Not Started
- **Description**: Develop an OpenAPI specification for the API.
- **Action**: Define API endpoints and schemas.
- **Impact**: Improves API documentation and usability.

### Write High-Level Architecture Documentation
- **Status**: Not Started
- **Description**: Document the high-level architecture.
- **Action**: Create documentation outlining components, interactions, and data flow.
- **Impact**: Enhances onboarding and maintainability.

### Advanced Rate Limiting for Plugins (Backend, Global/Redis-based)
- **Status**: Partially Complete
  - *Note*: Basic per-instance rate limiting exists in CCXT.
- **Description**: Implement a sophisticated, shared rate limiter for plugin API calls.
- **Action**: Integrate a library like `aiolimiter` with Redis backing.
- **Impact**: Robust API limit handling across multiple server instances.