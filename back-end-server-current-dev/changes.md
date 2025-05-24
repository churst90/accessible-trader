# Backend Codebase Changes

This document outlines the major architectural and functional changes introduced in this version of the backend server compared to the previous iteration. The goal is to improve modularity, scalability, maintainability, and robustness.

## 1. Major Architectural Overhaul: Service-Oriented Design

The most significant change is the adoption of a formal service layer and a redesigned plugin architecture.

### 1.1. Plugin System (`plugins/`)

#### `plugins/base.py` - `MarketPlugin` Abstract Base Class (ABC)
- **Introduced**: A new `MarketPlugin` ABC to standardize plugin behavior.
- **Details**:
  - Plugin instances are now configured for a specific `provider_id` (e.g., one `CryptoPlugin` instance for "binance", another for "coinbasepro"), simplifying plugin logic by embedding provider context in the instance.
  - Standardized class methods for plugin discovery:
    - `get_plugin_key()`
    - `get_supported_markets()`
    - `list_configurable_providers()`
  - Added a hierarchy of plugin-specific exceptions:
    - `PluginError`
    - `AuthenticationPluginError`
    - `NetworkPluginError`
    - `PluginFeatureNotSupportedError`

#### `plugins/__init__.py` - `PluginLoader`
- **Enhanced**: `PluginLoader` now discovers plugin classes based on the `MarketPlugin` ABC.
- **Details**:
  - Maps market names (e.g., "crypto", "stocks") to the `plugin_key` of the responsible plugin class, enabling dynamic routing.
  - Facilitates integration of plugins with the service layer.

#### Individual Plugins (`CryptoPlugin`, `AlpacaPlugin`)
- **CryptoPlugin**:
  - Designed to handle a single CCXT exchange ID per instance.
  - Uses `asyncio.Lock` for safer initialization of CCXT exchange objects.
  - Improved error mapping to the new custom plugin exceptions.
- **AlpacaPlugin**:
  - Refactored with a centralized `_request_api` helper for HTTP calls.
  - Improved error handling and request consistency.

### 1.2. Service Layer (`services/`)

The service layer centralizes core business logic and component interactions.

#### `MarketService` (`services/market_service.py`)
- **Functionality**:
  - **Plugin Instance Management**: Caches `MarketPlugin` instances, keyed by plugin class, `provider_id`, a hash of the API key (or public access marker), and testnet status for efficient reuse in multi-user or multi-key scenarios.
  - **Idle Plugin Cleanup**: Implements a periodic background task to close idle plugin instances, optimizing resource usage.
  - **Orchestration Hub**: Delegates complex data fetching to `DataOrchestrator` and historical backfills to `BackfillManager`.
  - **User Credentials**: Handles retrieval of user-specific API credentials (placeholder, pending future database integration).

#### `DataOrchestrator` (`services/data_orchestrator.py`)
- **Introduced**: A new component managing the data fetching pipeline.
- **Details**:
  - Coordinates a chain of `DataSource` instances: Cache, Aggregates, Plugin.
  - Implements pagination logic for fetching data from plugins (`_fetch_from_plugin_with_paging`).
  - Saves new 1-minute data from plugins to the database and cache.
  - Caches resampled data and data from aggregate sources.

#### `DataSource` Subsystem (`services/data_sources/`)
- **Introduced**: A `DataSource` ABC with concrete implementations:
  - **CacheSource**: Fetches from Redis cache with database fallback for 1-minute data; includes resampling logic.
  - **DbSource**: Interacts with the primary OHLCV database, primarily for writes by `DataOrchestrator` and `BackfillManager`.
  - **AggregateSource**: Fetches from TimescaleDB continuous aggregate views for non-1-minute timeframes.
  - **PluginSource**: Adapts the `MarketPlugin` interface for the `DataOrchestrator` pipeline.

#### `CacheManager` (`services/cache_manager.py`)
- **Replaces**: Older `utils/cache.py`.
- **Details**:
  - Introduces a `Cache` ABC with a `RedisCache` implementation.
  - Provides domain-specific methods (e.g., `get_1m_bars`, `store_1m_bars`, `get_resampled`, `set_resampled`).
  - Includes `tenacity` for retry logic on cache operations and Prometheus metrics.

#### `SubscriptionService` & `SubscriptionWorker` (`services/subscription_service.py`, `services/subscription_worker.py`)
- **Refactored**: WebSocket subscription logic.
- **Details**:
  - **SubscriptionService**:
    - Manages client WebSocket connections, initial data dispatch, and `SubscriptionWorker` lifecycle.
  - **SubscriptionWorker**:
    - Polls for live updates for a single subscription key (market/provider/symbol/timeframe).
    - Uses `MarketService` for data fetching.
    - Utilizes `SubscriptionRegistry` for tracking and `BroadcastManager` for sending updates (Redis Pub/Sub implementation pending).

#### `BackfillManager` (`services/backfill_manager.py`)
- **Functionality**:
  - Manages historical data backfills for 1-minute data.
  - Detects data gaps and triggers background tasks to fetch missing data using a specific `MarketPlugin` instance.
  - Handles chunking, retries, API concurrency limits (`_api_semaphore`), and stores data to the database and 1-minute cache.

## 2. Application Setup and Configuration

### `config.py`
- **Updated**: Configuration classes (`BaseConfig`, `DevelopmentConfig`, `ProductionConfig`, `TestingConfig`) now include a `validate()` method to ensure required settings are valid at startup.
- **Details**: More structured and comprehensive configuration management.

### Logging (`app_extensions/__init__.py`)
- **Enhanced**: `configure_logging` function uses `logging.dictConfig` for a robust, configurable logging setup via `app.config`.

### Application Lifecycle (`app.py`, `app_extensions/__init__.py`)
- **Initialization**:
  - Core services (database pool, Redis, `MarketService`, `SubscriptionService`) are initialized via an `@app.before_serving` hook in `app_extensions.init_app_extensions`.
  - `MarketService` is initialized in `create_app` and attached to the app context.
- **Shutdown**:
  - Graceful shutdown of services (`SubscriptionService`, `MarketService`, Redis, database pool) is centralized in an `@app.after_serving` hook in `app.py`.

### `app_extensions/redis_manager.py` & `app_extensions/db_pool.py`
- **Introduced**: Dedicated modules for managing Redis connections (using `services.cache_manager.RedisCache`) and the `asyncpg` database pool.

## 3. API Blueprints (`blueprints/`)

### `market_blueprint.py`
- **Updated**:
  - Endpoints now interact with the refactored `MarketService` and `PluginLoader`.
  - The `/providers` endpoint logic is updated to list providers based on market and plugin capabilities.
  - Error handling aligns with new custom exception types.

### `websocket_blueprint.py`
- **Updated**: Uses the new `SubscriptionService` for managing WebSocket subscriptions and data flow.

## 4. Error Handling
- **Introduced**: A defined hierarchy of custom exceptions:
  - `PluginError` and subclasses (`AuthenticationPluginError`, `NetworkPluginError`, `PluginFeatureNotSupportedError`)
  - `DataSourceError`
- **Details**: Error handling in services and blueprints is more explicit, mapping to appropriate HTTP responses or WebSocket error messages.

## 5. Key Functional Changes
- **Provider-Specific Plugin Instances**:
  - `MarketService` manages plugin instances specific to `provider_id`, API key configuration, and testnet status, unlike the previous model where a single plugin handled multiple providers.
- **Layered Data Fetching**:
  - `DataOrchestrator` implements a clear strategy: Cache -> Aggregates -> Live Plugin.
- **Improved Caching**:
  - `RedisCache` provides specific methods for 1-minute and resampled data.
  - `MarketService` caches plugin instances, enhancing internal plugin caches (e.g., `CryptoPlugin`'s market data cache).
- **Robust Background Task Management**:
  - Improved locking and lifecycle control for backfills (`BackfillManager`) and WebSocket polling (`SubscriptionWorker`).

## 6. Guidance for Developers
- **Service Layer**: Familiarize yourself with the `services/` directory, which contains core logic.
- **Plugin System**: Understand the `MarketPlugin` ABC and how `CryptoPlugin` and `AlpacaPlugin` are instantiated and managed by `MarketService`.
- **Data Fetching**: Note how `DataOrchestrator` uses `DataSource` implementations.
- **WebSocket Logic**: Review `SubscriptionService` and `SubscriptionWorker` for WebSocket handling.
- **Configuration and Logging**: Centralized in `config.py` and `app_extensions/init_app_extensions.py`.
- **API Endpoints**: Defined in the `blueprints/` directory.
- **Goal**: This refactoring provides a stable, extensible, and understandable backend system.