# Server Codebase TODO

This document outlines tasks to enhance the server codebase, focusing on performance, scalability, maintainability, and robustness. Tasks are categorized and prioritized based on impact and complexity.

## High Priority

### Implement Redis Pub/Sub for WebSocket Broadcasting
- **Status**: Not Started
- **Description**: Replace direct WebSocket queueing with Redis Pub/Sub to enable scalable broadcasting.
- **Action**: Modify `SubscriptionService` and `BroadcastManager` to use Redis Pub/Sub channels. Configure workers to publish to Redis and broadcasters to subscribe.
- **Impact**: Enables horizontal scaling and reduces broadcasting latency.

### Parallelize Backfill Chunks for a Single Asset
- **Status**: Partially Complete
  - *Note*: Global semaphore exists, but per-asset chunk/gap parallelism needs improvement.
- **Description**: Accelerate historical backfills for a single asset by fetching missing chunks/gaps in parallel, while adhering to API rate limits.
- **Action**: Modify `BackfillManager._run_historical_backfill` to use `asyncio.gather` for concurrent fetching of multiple chunks/gaps for the same asset. Coordinate using the asset’s instance or a finer-grained semaphore if the global semaphore is insufficient.
- **Impact**: Significantly reduces backfill time for individual assets.

### Develop Unit Tests
- **Status**: Not Started
- **Description**: Create unit tests for core components.
- **Action**: Use `pytest` and `pytest-asyncio` to write tests, mocking external dependencies. Cover `MarketService`, `DataOrchestrator`, Plugins, `SubscriptionService`, `CacheManager`, and `BackfillManager`.
- **Impact**: Improves code reliability and enables safe refactoring.

### Create Integration Tests
- **Status**: Not Started
- **Description**: Validate end-to-end behavior of the system.
- **Action**: Set up a test environment using Quart test client, WebSocket test client, and mock plugins/database. Test subscription lifecycle, API calls, and error handling.
- **Impact**: Ensures system-level correctness.

### Implement Finer-Grained Caching for 1m Bars
- **Status**: Not Started
- **Description**: Cache 1-minute bars in smaller time buckets (e.g., hourly or daily) in `RedisCache` instead of one large list per symbol.
- **Action**: Update `RedisCache.store_1m_bars` and `get_1m_bars` to use time-bucketed keys.
- **Impact**: Improves cache hit rates for 1-minute data and reduces Redis memory usage for long time series when only partial data is needed.

## Medium Priority

### Market-Specific Symbol Filtering in Plugins
- **Status**: Not Started
- **Description**: Modify `MarketPlugin`'s `get_symbols` method and its implementations (e.g., `AlpacaPlugin` for multiple asset classes under one provider) to accept a `market` (asset class) parameter, enabling filtering of symbols relevant to the user-selected market.
- **Action**:
  1. Update `MarketPlugin.get_symbols` signature in `plugins/base.py` to accept a `market: str` parameter.
  2. Modify `MarketService.get_symbols` to pass the `market` argument to `plugin_instance.get_symbols(market=market)`.
  3. Update `AlpacaPlugin.get_symbols` (and other relevant plugins) to filter symbols using the `market` parameter, e.g., by setting the `asset_class` parameter in API calls.
  4. Ensure `AlpacaPlugin.supported_markets` accurately reflects all distinct, filterable asset classes provided.
- **Impact**: Improves user experience by filtering symbols for multi-asset class providers and ensures data relevance. Essential for supporting diverse asset types from a single provider like Alpaca.

### Add Backend API Endpoint for Listing All Markets
- **Status**: Not Started
- **Description**: Create a new API endpoint (e.g., `/api/markets`) to return the list of all available markets discovered by `PluginLoader`.
- **Action**: Add a route in `blueprints/market.py` that calls `PluginLoader.get_all_markets()` and returns the result as JSON. Update the frontend to use this endpoint for the market dropdown.
- **Impact**: Decouples frontend market list from hardcoded values, enabling dynamic updates based on backend capabilities.

### Refine `RedisCache` Serialization for `None`/`NaN`/`Infinity`
- **Status**: Not Started
  - *Note*: Currently converts `None`, `NaN`, and `Infinity` to `0.0`.
- **Description**: Improve `RedisCache._serialize_bars` to handle `None`, `NaN`, and `Infinity` correctly, preventing loss of distinct meaning.
- **Action**: Modify `_serialize_bars` to serialize `None` as `null` and handle `NaN`/`Infinity` as strings (e.g., `"NaN"`, `"Infinity"`) or omit them if `null` is inappropriate, ensuring compatibility with downstream consumers and database.
- **Impact**: Enhances data fidelity in the cache.

### Centralize Bar Filtering Logic
- **Status**: Not Started
- **Description**: Consolidate similar filtering logic (`since`, `before`, `limit`) in `CacheSource._filter_bars` and `DataOrchestrator._apply_filters`.
- **Action**: Create a common utility function for filtering logic and use it in both `CacheSource` and `DataOrchestrator`.
- **Impact**: Reduces code redundancy and improves maintainability.

### Use Redis Pipelines for Batch Cache Operations
- **Status**: Not Started
- **Description**: Optimize multiple Redis writes in `RedisCache` by using pipelines.
- **Action**: Modify `RedisCache` methods that perform multiple `setex` or other commands in a loop to use `redis.asyncio.pipeline()`.
- **Impact**: Improves caching performance, especially for bulk updates.

### Add Manual Refresh for Continuous Aggregates
- **Status**: Not Started
- **Description**: Implement a mechanism to manually refresh TimescaleDB continuous aggregates.
- **Action**: Add an admin endpoint or scheduled task to call `CALL refresh_continuous_aggregate(...)`.
- **Impact**: Ensures data integrity for higher timeframes.

### Prioritize Real-Time Subscriptions Over Backfill
- **Status**: Not Started
- **Description**: Implement a mechanism to pause or throttle backfills during high load to prioritize real-time subscriptions.
- **Action**: Add load monitoring in `MarketService` or a global task manager. Enable `BackfillManager` tasks to be paused/resumed or adjust `_api_semaphore` dynamically.
- **Impact**: Ensures low latency for real-time clients.

### Centralize Validation with Pydantic
- **Status**: Not Started
- **Description**: Use Pydantic for request and response schema validation in blueprints.
- **Action**: Define Pydantic models and integrate them with Quart routes.
- **Impact**: Simplifies maintenance and ensures consistent validation.

### Expand Prometheus Metrics
- **Status**: Partially Complete
  - *Note*: Cache and Backfill have some metrics; `DataOrchestrator` metrics need restoration or enhancement.
- **Description**: Add or restore metrics for `DataOrchestrator` operations (e.g., latency, source usage), WebSocket connections, and subscription rates.
- **Action**: Integrate `prometheus_client` further into `DataOrchestrator` and `SubscriptionService`.
- **Impact**: Enhances system monitoring capabilities.

### Profile Database Queries
- **Status**: Not Started
  - *Note*: Ongoing process.
- **Description**: Identify and optimize slow database queries.
- **Action**: Use `EXPLAIN ANALYZE` to analyze query performance.
- **Impact**: Reduces latency and database contention.

### Correct `DEFAULT_BACKFILL_PERIOD_MS` Comment/Value in `config.py`
- **Status**: Not Started
- **Description**: The comment in `config.py` states "~10 years" but the value is `315576000000 * 10` (100 years).
- **Action**: Align the comment and default value in `config.py` to the intended duration.
- **Impact**: Improves configuration clarity.

### Track Per-Client State in SubscriptionService
- **Status**: Partially Complete
- **Description**: Enhance `SubscriptionService` to handle scenarios where multiple clients with the same subscription key require different catch-up data streams after initial connection, if this is a desired feature beyond `clientSince`.
- **Action**: Evaluate if the current model (`clientSince` + shared live stream per key) is sufficient. If not, investigate granular per-WebSocket client catch-up mechanisms or state tracking in `SubscriptionService` or `SubscriptionWorker`.
- **Impact**: Potentially reduces redundant data transmission for clients with differing states on the same key.

## Low Priority

### Validate Plugin Parameters
- **Status**: Not Started
- **Description**: Add validation for `plugin_params` passed to `MarketService.fetch_ohlcv`.
- **Action**: Define allowed parameters in `MarketPlugin` subclasses and validate them in `MarketService` or `DataOrchestrator`.
- **Impact**: Prevents plugin errors due to invalid parameters.

### Create OpenAPI Specification
- **Status**: Not Started
- **Description**: Develop an OpenAPI specification for the API.
- **Action**: Define API endpoints and schemas using OpenAPI standards.
- **Impact**: Improves API documentation and usability.

### Write High-Level Architecture Documentation
- **Status**: Not Started
- **Description**: Document the high-level architecture of the codebase.
- **Action**: Create documentation outlining system components, interactions, and data flow.
- **Impact**: Enhances onboarding and maintainability.

### Support Real-Time Tick Data
- **Status**: Not Started
- **Description**: Add support for real-time tick data processing.
- **Action**: Implement necessary infrastructure for handling tick data streams.
- **Impact**: Expands system capabilities for high-frequency data.

### Implement Trading API
- **Status**: Not Started
- **Description**: Develop an API for trading functionality.
- **Action**: Design and implement trading-related endpoints and logic.
- **Impact**: Enables trading capabilities for users.

### Add Advanced Rate Limiting for Plugins (Global/Redis-based)
- **Status**: Partially Complete
  - *Note*: Basic per-instance rate limiting exists.
- **Description**: Implement a sophisticated, shared rate limiter (e.g., using Redis) for plugin API calls.
- **Action**: Integrate a library like `aiolimiter` with Redis backing for rate limiting.
- **Impact**: Provides robust API limit handling across multiple server instances.

### Split Large Files (Further Refinement)
- **Status**: Partially Complete
  - *Note*: Significant refactoring already done.
- **Description**: Further break up large service files if they become unwieldy.
- **Action**: Identify modules within large files that can be split into standalone components.
- **Impact**: Improves code organization and maintainability.

### User Service Implementation for User API Keys (Full Integration)
- **Status**: Partially Complete
  - *Note*: Database and service for general configuration exist.
- **Description**: Fully implement storage and secure retrieval of user-specific API keys and integrate into `MarketService._get_user_api_credentials`.
- **Action**: Design a secure schema in `user_configs` for API keys. Implement logic in `user_service.py` and `MarketService` to use these keys when instantiating plugins.
- **Impact**: Enables personalized, authenticated access to data providers for users.