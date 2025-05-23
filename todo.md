# Server Codebase TODO

This document lists tasks to improve the server codebase, focusing on performance, scalability, maintainability, and robustness. Tasks are categorized and prioritized based on impact and complexity.

## High Priority

* **Implement Redis Pub/Sub for WebSocket Broadcasting**
    * **Status**: Not Done
    * **Description**: Replace direct WebSocket queueing with Redis Pub/Sub for scalable broadcasting.
    * **Action**: Modify `SubscriptionService`/`BroadcastManager` to use Redis Pub/Sub channels. Workers publish to Redis; broadcasters subscribe.
    * **Impact**: Horizontal scaling, reduced broadcasting latency.
* **Parallelize Backfill Chunks for a Single Asset**
    * **Status**: Partially Addressed (global semaphore exists, but per-asset chunk/gap parallelism can be improved).
    * **Description**: Speed up historical backfills for a single asset by fetching its missing chunks/gaps in parallel, respecting API limits.
    * **Action**: Modify `BackfillManager._run_historical_backfill` to use `asyncio.gather` for fetching multiple chunks/gaps of *the same asset* concurrently, coordinated by its instance or a finer-grained semaphore if the global one isn't sufficient.
    * **Impact**: Significantly reduces backfill time for individual assets.
* **Develop Unit Tests**
    * **Status**: Not Done
    * **Description**: Create unit tests for core components.
    * **Action**: Use pytest/pytest-asyncio, mock external dependencies. Cover `MarketService`, `DataOrchestrator`, Plugins, `SubscriptionService`, `CacheManager`, `BackfillManager`.
    * **Impact**: Code reliability, safe refactoring.
* **Create Integration Tests**
    * **Status**: Not Done
    * **Description**: Validate end-to-end behavior.
    * **Action**: Test environment with Quart test client, WebSocket test client, mock plugins/DB. Test subscription lifecycle, API calls, error handling.
    * **Impact**: System-level correctness.
* **Implement Finer-Grained Caching for 1m Bars**
    * **Status**: Not Done
    * **Description**: Cache 1m bars in smaller time buckets (e.g., hourly/daily) in `RedisCache` instead of one large list per symbol.
    * **Action**: Update `RedisCache.store_1m_bars` and `get_1m_bars` to use time-bucketed keys.
    * **Impact**: Improves cache hit rates for 1m data, reduces Redis memory for very long series if only partial data is needed.

## Medium Priority

* **Market-Specific Symbol Filtering in Plugins (NEW TASK)**
    * **Status**: Not Done
    * **Description**: Modify `MarketPlugin`'s `get_symbols` method and its implementations (especially for plugins serving multiple asset classes under one provider like `AlpacaPlugin`) to accept a `market` (asset class) parameter. This will allow fetching and displaying symbols relevant only to the user-selected market/asset class.
    * **Action**:
        1.  Update `MarketPlugin.get_symbols` signature in `plugins/base.py` to accept `market: str`.
        2.  Update `MarketService.get_symbols` to pass the `market` argument it receives to `plugin_instance.get_symbols(market=market)`.
        3.  Modify `AlpacaPlugin.get_symbols` (and other relevant plugins) to use the `market` argument to filter symbols, e.g., by setting the `asset_class` parameter in API calls.
        4.  Ensure `AlpacaPlugin.supported_markets` accurately reflects all distinct, filterable asset classes it provides.
    * **Impact**: Correctly filters symbols for multi-asset class providers, improving UX and relevance of data. Essential for supporting diverse asset types from a single provider like Alpaca.
* **Add Backend API Endpoint for Listing All Markets (NEW TASK - related to frontend)**
    * **Status**: Not Done
    * **Description**: Create a new API endpoint (e.g., `/api/markets`) that returns the list of all available markets discovered by `PluginLoader`.
    * **Action**: Add a route in `blueprints/market.py` that calls `PluginLoader.get_all_markets()` and returns the result as JSON. Update frontend to use this endpoint for the market dropdown.
    * **Impact**: Decouples frontend market list from hardcoding, makes it dynamic based on backend capabilities.
* **Refine `RedisCache` Serialization for `None`/`NaN`/`Infinity`**
    * **Status**: Not Done (Still converts to `0.0`)
    * **Description**: `RedisCache._serialize_bars` converts `None`, `NaN`, `Infinity` to `0.0`. This can lead to loss of distinct meaning.
    * **Action**: Modify `_serialize_bars` to serialize `None` as `null`. Handle `NaN`/`Infinity` as strings (e.g., "NaN", "Infinity") or by omitting them if `null` isn't appropriate, ensuring downstream consumers and DB can handle this.
    * **Impact**: Improves data fidelity in cache.
* **Centralize Bar Filtering Logic**
    * **Status**: Not Done
    * **Description**: Similar filtering logic (`since`, `before`, `limit`) exists in `CacheSource._filter_bars` and `DataOrchestrator._apply_filters`.
    * **Action**: Create a common utility function for this filtering logic and use it in both places.
    * **Impact**: Reduces redundancy, improves maintainability.
* **Use Redis Pipelines for Batch Cache Operations**
    * **Status**: Not Done
    * **Description**: Optimize multiple Redis writes in `RedisCache` by using pipelines.
    * **Action**: Modify `RedisCache` methods that perform multiple `setex` or other commands in a loop to use `redis.asyncio.pipeline()`.
    * **Impact**: Improves caching performance, especially for bulk updates.
* **Add Manual Refresh for Continuous Aggregates**
    * **Status**: Not Done
    * **Description**: Implement a way to manually refresh TimescaleDB continuous aggregates.
    * **Action**: Add an admin endpoint or scheduled task to call `CALL refresh_continuous_aggregate(...)`.
    * **Impact**: Data integrity for higher timeframes.
* **Prioritize Real-Time Subscriptions Over Backfill**
    * **Status**: Not Done
    * **Description**: Mechanism to pause/throttle backfills during high load.
    * **Action**: Implement load monitoring in `MarketService` or a global task manager; allow `BackfillManager` tasks to be paused/resumed or their `_api_semaphore` adjusted dynamically.
    * **Impact**: Ensures low latency for real-time clients.
* **Centralize Validation with Pydantic**
    * **Status**: Not Done
    * **Description**: Use Pydantic for request/response schema validation in blueprints.
    * **Action**: Define Pydantic models, integrate with Quart routes.
    * **Impact**: Simplifies maintenance, consistent validation.
* **Expand Prometheus Metrics**
    * **Status**: Partially Addressed (Cache and Backfill have some; DataOrchestrator needs its restored/enhanced).
    * **Description**: Add/restore metrics for `DataOrchestrator` operations (latency, source usage), WebSocket connections, subscription rates.
    * **Action**: Integrate `prometheus_client` further into `DataOrchestrator` and `SubscriptionService`.
    * **Impact**: Enhanced monitoring.
* **Profile Database Queries**
    * **Status**: Not Done (Process)
    * **Description**: Identify and optimize slow DB queries.
    * **Action**: Use `EXPLAIN ANALYZE`.
    * **Impact**: Reduces latency, DB contention.
* **Correct `DEFAULT_BACKFILL_PERIOD_MS` Comment/Value in `config.py`**
    * **Status**: Not Done
    * **Description**: The comment says "~10 years" but the default value is `315576000000 * 10` (100 years).
    * **Action**: Align the comment and the default value in `config.py` to the intended duration.
    * **Impact**: Configuration clarity.
* **Track Per-Client State in SubscriptionService (Refined)**
    * **Status**: Partially Addressed.
    * **Description**: Enhance `SubscriptionService` to better handle scenarios where multiple clients connected to the *same subscription key* might require different catch-up data streams after their initial connection, if this is a desired feature beyond the initial `clientSince`.
    * **Action**: Evaluate if the current model (initial `clientSince` + shared live stream per key) is sufficient. If not, investigate options for more granular per-websocket client catch-up mechanisms or state tracking within `SubscriptionService` or `SubscriptionWorker`.
    * **Impact**: Potentially reduces redundant data transmission if clients on the same key have very different states.

## Low Priority

* **Validate Plugin Parameters**
    * **Status**: Not Done
    * **Description**: Add validation for `plugin_params` passed to `MarketService.fetch_ohlcv`.
    * **Action**: Define allowed params in `MarketPlugin` subclasses; validate in `MarketService` or `DataOrchestrator`.
    * **Impact**: Prevents plugin errors from invalid params.
* **Create OpenAPI Specification**
    * **Status**: Not Done
* **Write High-Level Architecture Documentation**
    * **Status**: Not Done
* **Support Real-Time Tick Data**
    * **Status**: Not Done
* **Implement Trading API**
    * **Status**: Not Done
* **Add Advanced Rate Limiting for Plugins (Global/Redis-based)**
    * **Status**: Partially Addressed (basic per-instance measures exist).
    * **Description**: Implement a more sophisticated, shared rate limiter (e.g., using Redis) for plugin API calls.
    * **Action**: Integrate a library like `aiolimiter` with Redis backing.
    * **Impact**: Robust API limit handling across multiple server instances.
* **Split Large Files (Further Refinement)**
    * **Status**: Partially Addressed (significant refactoring already done).
    * **Description**: Further break up larger service files if they become unwieldy.
    * **Action**: Identify modules within large files that could be standalone.
    * **Impact**: Code organization.
* **User service implementation for user API keys (Full Integration)**
    * **Status**: Partially Addressed (DB/service for general config exists).
    * **Description**: Fully implement the storage and secure retrieval of user-specific API keys and integrate this into `MarketService._get_user_api_credentials`.
    * **Action**: Design secure schema in `user_configs` for API keys. Implement logic in `user_service.py` and `MarketService` to use these keys when instantiating plugins.
    * **Impact**: Enables personalized, authenticated access to data providers for users.
