This document lists tasks to improve the server codebase, focusing on performance, scalability, maintainability, and robustness. Tasks are categorized and prioritized based on impact and complexity.

Implement Redis Pub/Sub for WebSocket Broadcasting (Priority: High)
Description: Replace the single Queue per subscription key in SubscriptionManager with a Redis Pub/Sub model to scale broadcasting across multiple server instances and reduce bottlenecks for high subscriber counts.
Action: Use Redis channels for each subscription key (market/provider/symbol/timeframe). Publish updates to channels and have each server instance subscribe to relevant channels. Update _broadcaster_loop to read from Redis instead of a local queue.
Impact: Enables horizontal scaling and reduces latency for large numbers of WebSocket clients.

Track Per-Client State in SubscriptionManager (Priority: Medium)
Description: Avoid fetching data for clients already up-to-date by tracking each client's last_received_ts in SubscriptionManager. This prevents unnecessary API calls when clients have different client_since values.
Action: Add a dictionary in SubscriptionManager to store per-client state (e.g., client_ws_key -> last_received_ts). Modify _poll_loop to fetch data only for clients needing updates.
Impact: Reduces redundant data fetches, improving performance under mixed client scenarios.

Caching Optimizations
Implement Finer-Grained Caching (Priority: High)
Description: Cache 1m bars in smaller buckets (e.g., per-minute or 5-minute) instead of hourly buckets to improve cache hit rates for small time ranges. This reduces database queries for partial cache hits.
Action: Update _cache_1m_bars_grouped and _get_cached_1m_bars_grouped to use smaller time buckets. Adjust cache key format to include bucket start times (e.g., 1m_bars_5min:market:provider:symbol:ts).
Impact: Increases cache efficiency, reducing database load.

Use Redis Pipelines for Batch Operations (Priority: Medium)
Description: Optimize cache operations in _cache_1m_bars_grouped by using Redis pipelines or batch commands to reduce network round-trips when setting multiple keys.
Action: Modify Cache class to support pipelined operations using redis.asyncio's pipeline API. Update _cache_1m_bars_grouped to batch set calls within a pipeline.
Impact: Improves caching performance, especially during backfills or high write loads.

Reduce Cache Fragmentation for OHLCV Results (Priority: Medium)
Description: Cache keys in fetch_ohlcv include since, before, and limit, leading to fragmentation. Cache individual bars or smaller ranges to improve hit rates across similar requests.
Action: Cache OHLCV results in smaller chunks (e.g., per day or per 100 bars) and reconstruct responses from these chunks. Update fetch_ohlcv to check for partial cache hits.
Impact: Increases cache reuse, reducing redundant data fetches.

Database Optimizations
Optimize Database Queries (Priority: Medium)
Description: Reduce I/O in fetch_ohlcv_from_db by selecting only needed columns (timestamp, open, high, low, close, volume) instead of all columns.
Action: Update fetch_ohlcv_from_db and related DB functions to specify exact columns in SELECT statements. Profile queries with EXPLAIN ANALYZE to identify further optimizations.
Impact: Decreases database load and query latency.

Add Manual Refresh for Continuous Aggregates (Priority: Medium)
Description: Implement a mechanism to manually refresh continuous aggregates (ohlcv_5min, etc.) or handle data gaps if 1m data is incomplete, ensuring higher timeframes remain accurate.
Action: Add an admin endpoint or scheduled task to call CALL refresh_continuous_aggregate(...) for specific views. Log warnings if gaps are detected in 1m data during aggregate refreshes.
Impact: Improves data integrity for higher timeframes.

Backfill Improvements
Parallelize Backfill Chunks (Priority: High)
Description: Speed up historical backfills by fetching multiple chunks in parallel with a rate limiter, rather than sequentially with fixed delays.
Action: Modify _run_historical_backfill to use asyncio.gather for parallel chunk fetches, with a semaphore to limit concurrent API calls. Integrate rate limiting logic from CryptoPlugin._with_retries.
Impact: Reduces backfill time, improving data availability.

Prioritize Real-Time Subscriptions Over Backfill (Priority: Medium)
Description: Add a mechanism to pause or throttle backfill tasks during high server load to prioritize real-time WebSocket subscriptions.
Action: Implement a global task manager in MarketService to monitor server load (e.g., via subscription count or CPU usage). Pause backfill tasks when load exceeds a threshold.
Impact: Ensures low latency for real-time clients during peak usage.

Testing
Develop Unit Tests (Priority: High)
Description: Create unit tests for core components (MarketService, SubscriptionManager, CryptoPlugin, AlpacaPlugin) to ensure reliability and catch regressions.
Action: Use pytest and pytest-asyncio to write tests. Mock external dependencies (e.g., Redis, TimescaleDB, CCXT) using unittest.mock. Cover key methods like fetch_ohlcv, subscribe, and _with_retries.
Impact: Increases code reliability and supports safe refactoring.

Create Integration Tests (Priority: High)
Description: Build integration tests to simulate WebSocket subscriptions and REST API calls, validating end-to-end behavior with a test database and mock plugins.
Action: Set up a test environment using TestingConfig. Use quart test client for REST endpoints and a WebSocket test client (e.g., websocket-client) for subscriptions. Test scenarios like subscription lifecycle and error handling.
Impact: Ensures system-level correctness and robustness.

Validation and Input Handling
Centralize Validation with Pydantic (Priority: Medium)
Description: Reduce duplicated validation logic in market_blueprint and websocket_blueprint by using Pydantic for request/response schemas.
Action: Define Pydantic models for API inputs (e.g., OHLCV request parameters) and outputs (e.g., Highcharts response). Integrate with Quart routes using a middleware or decorator.
Impact: Simplifies maintenance and ensures consistent validation.

Validate Plugin Parameters (Priority: Low)
Description: Add validation for plugin_params in MarketService.fetch_ohlcv to ensure only supported parameters are passed to plugins.
Action: Define allowed plugin_params in each MarketPlugin subclass and validate in fetch_ohlcv before calling plugin methods.
Impact: Prevents plugin errors due to invalid parameters.
Documentation

Add Comprehensive Docstrings (Priority: Medium)
Description: Write detailed docstrings for all public methods and complex internal ones, following a standard like Google Python Style Guide.
Action: Update files like CryptoPlugin.py, MarketService.py, and SubscriptionManager.py to include docstrings for methods like _with_retries, fetch_ohlcv, and _poll_loop. Include parameter descriptions and return types.
Impact: Improves code readability and developer onboarding.

Create OpenAPI Specification (Priority: Medium)
Description: Document REST endpoints and WebSocket protocol using OpenAPI and a WebSocket schema (e.g., JSON Schema for messages).
Action: Use a library like apispec to generate an OpenAPI spec for market_blueprint, auth_blueprint, and user_blueprint. Document WebSocket message formats in a separate schema.
Impact: Facilitates client integration and API clarity.

Write High-Level Architecture Documentation (Priority: Low)
Description: Create a high-level overview of the system architecture, including components (e.g., plugins, MarketService, SubscriptionManager) and data flow.
Action: Add an ARCHITECTURE.md file or update README.md with diagrams (e.g., using Mermaid or PlantUML) and descriptions of key modules.
Impact: Helps new developers understand the system quickly.

Monitoring and Observability
Add Prometheus Metrics (Priority: Medium)
Description: Expose metrics for WebSocket connection counts, subscription rates, cache hit/miss ratios, and plugin API call latencies to improve observability.
Action: Integrate prometheus_client with Quart. Add counters/gauges for key metrics in SubscriptionManager, Cache, and MarketService. Expose a /metrics endpoint.
Impact: Enhances monitoring and debugging in production.

Profile Database Queries (Priority: Medium)
Description: Identify slow database queries under load to optimize performance, especially for ohlcv_data and continuous aggregates.
Action: Use TimescaleDB's EXPLAIN ANALYZE on common queries (e.g., fetch_ohlcv_from_db). Test with a large dataset and high query volume. Optimize indexes or query patterns as needed.
Impact: Reduces latency and database contention.

Future Enhancements
Support Real-Time Tick Data (Priority: Low)
Description: Implement watch_ticks in plugins (e.g., CCXT's WebSocket API for crypto exchanges) to support real-time tick data for low-latency applications.
Action: Extend MarketPlugin to handle WebSocket streams. Update SubscriptionManager to manage tick subscriptions with a separate queue or channel.
Impact: Expands use cases for high-frequency trading or analytics.

Implement Trading API (Priority: Low)
Description: Support trading methods in MarketPlugin (e.g., place_order, fetch_balance) for providers like Alpaca to enable trading functionality.
Action: Implement trading methods in AlpacaPlugin using Alpaca's trade API. Add authenticated endpoints in market_blueprint for order placement and balance queries.
Impact: Broadens the application's scope to include trading.

Add Rate Limiting for Plugins (Priority: Low)
Description: Enhance CryptoPlugin._with_retries with a global rate limiter to prevent exceeding API limits across all plugin instances.
Action: Use a library like aiolimiter to enforce rate limits per provider. Store rate limit state in Redis for multi-instance coordination.
Impact: Prevents API bans and improves reliability.
Miscellaneous

Split Large Files (Priority: Low)
Description: Break up large files like market_service.py and websocket_blueprint.py into smaller modules for better readability and maintainability.
Action: Move related methods (e.g., caching logic in MarketService) to separate files (e.g., services/market_service_cache.py). Update imports accordingly.
Impact: Improves code organization and developer experience.

Handle Broad Exception Catches (Priority: Low)
Description: Replace broad except Exception catches in CryptoPlugin._with_retries and other areas with specific exceptions (e.g., HTTP errors, rate limit errors).
Action: Identify expected error types from CCXT and other libraries. Update exception handling to catch only those types and log unexpected errors separately.
Impact: Improves error handling precision and debugging.

User service implementation for user configuration details (Priority: low)
Description: Implement methods to facilitate the storing and retrieval of user chart configurations, including API key information for customized chart and provider experiences.
Action: Implement a database for this specific task to keep ohlcv and user data separate.
Impact: Personalized user experiences and chart customization for recall per user account.

Prioritization Guide
High Priority: Tasks that significantly impact performance, scalability, or reliability (e.g., native timeframe support, testing, WebSocket scalability).
Medium Priority: Tasks that improve efficiency, maintainability, or observability without immediate critical impact (e.g., caching optimizations, documentation).
Low Priority: Nice-to-have enhancements or future features that expand functionality but aren't urgent (e.g., tick data, trading API).
