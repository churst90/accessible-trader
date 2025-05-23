Backend Codebase Changes
This document outlines the major architectural and functional changes introduced in this version of the backend server compared to the previous iteration. The goal of these changes was to improve modularity, scalability, maintainability, and robustness.

1. Major Architectural Overhaul: Service-Oriented Design
The most significant change is the introduction of a more formal service layer and a redesigned plugin architecture.

1.1. Plugin System (plugins/)
plugins/base.py - Abstract Base Class (MarketPlugin):

Introduced a new MarketPlugin Abstract Base Class (ABC).

Plugin instances are now configured for a specific provider_id (e.g., one CryptoPlugin instance for 'binance', another for 'coinbasepro'). This simplifies plugin logic as the provider context is inherent to the instance.

Standardized class methods for plugin discovery: get_plugin_key(), get_supported_markets(), list_configurable_providers().

Introduced a refined hierarchy of plugin-specific exceptions (PluginError, AuthenticationPluginError, NetworkPluginError, PluginFeatureNotSupportedError).

plugins/__init__.py - PluginLoader:

PluginLoader has been significantly enhanced. It now discovers plugin classes based on the new MarketPlugin ABC.

It maps market names (e.g., "crypto", "stocks") to the plugin_key of the class responsible for that market, facilitating dynamic routing.

Individual Plugins (CryptoPlugin, AlpacaPlugin):

CryptoPlugin: Now designed so each instance handles a single CCXT exchange ID. It uses an asyncio.Lock for safer CCXT exchange object initialization and features improved error mapping to the new custom plugin exceptions.

AlpacaPlugin: Refactored with a centralized _request_api helper for HTTP calls, improving error handling and request consistency.

1.2. Service Layer (services/)
This new layer centralizes core business logic and interactions between components.

MarketService (services/market_service.py):

Plugin Instance Management: Now caches MarketPlugin instances. Instances are keyed by plugin class, provider ID, a hash of the API key (or a public access marker), and testnet status. This allows for efficient reuse of configured plugin instances, especially in multi-user or multi-key scenarios.

Idle Plugin Cleanup: Implements a periodic background task to check for and close idle plugin instances, improving resource management.

Orchestration Hub: Delegates complex data fetching to DataOrchestrator and historical backfills to BackfillManager.

Handles retrieval of user-specific API credentials (currently a placeholder, intended for future database integration).

DataOrchestrator (services/data_orchestrator.py):

A new component responsible for the data fetching pipeline.

Manages a chain of DataSource instances (Cache, Aggregates, Plugin).

Implements logic for fetching data from plugins with pagination (_fetch_from_plugin_with_paging).

Handles saving new 1m data from plugins to the database and cache.

Caches resampled data and data from aggregate sources.

DataSource Subsystem (services/data_sources/):

Introduced a DataSource ABC.

Concrete implementations:

CacheSource: Fetches from Redis cache, with DB fallback for 1m data; includes resampling logic.

DbSource: Interacts directly with the primary OHLCV database (primarily for writes by DataOrchestrator and BackfillManager).

AggregateSource: Fetches from TimescaleDB continuous aggregate views for non-1m timeframes.

PluginSource: Adapts the MarketPlugin interface for use within the DataOrchestrator's pipeline.

CacheManager (services/cache_manager.py):

Replaces the older utils/cache.py.

Introduces a Cache ABC and a RedisCache implementation.

Features domain-specific methods (e.g., get_1m_bars, store_1m_bars, get_resampled, set_resampled).

Includes tenacity for retry logic on cache operations and Prometheus metrics.

SubscriptionService & SubscriptionWorker (services/subscription_service.py, services/subscription_worker.py):

WebSocket subscription logic has been refactored.

SubscriptionService: Manages client WebSocket connections, initial data dispatch, and the lifecycle of SubscriptionWorker instances.

SubscriptionWorker: Dedicated to polling for live updates for a single subscription key (market/provider/symbol/timeframe). It uses the main application's MarketService for data fetching.

Utilizes SubscriptionRegistry for tracking and BroadcastManager for sending updates (though Pub/Sub is a TODO).

BackfillManager (services/backfill_manager.py):

Manages historical data backfills for 1-minute data.

Detects data gaps and triggers background tasks to fetch missing data using a specific MarketPlugin instance.

Handles chunking, retries, API concurrency limits (_api_semaphore), and stores data to DB and 1m cache.

2. Application Setup and Configuration
config.py:

Configuration classes (BaseConfig, DevelopmentConfig, ProductionConfig, TestingConfig) now include a validate() method to ensure required settings are present and valid at startup.

More structured and comprehensive.

Logging (app_extensions/__init__.py):

configure_logging function now uses logging.dictConfig for a more robust and detailed logging setup, configurable via app.config.

Application Lifecycle (app.py, app_extensions/__init__.py):

Initialization of core services (DB pool, Redis, MarketService, SubscriptionService) is now primarily handled via an @app.before_serving hook in app_extensions.init_app_extensions.

MarketService itself is initialized in create_app and attached to the app context.

Graceful shutdown of services (SubscriptionService, MarketService, Redis, DB pool) is centralized in an @app.after_serving hook in app.py.

app_extensions/redis_manager.py & app_extensions/db_pool.py:

Dedicated modules for initializing and managing Redis connections (now using services.cache_manager.RedisCache) and the asyncpg database pool.

3. API Blueprints (blueprints/)
market_blueprint.py:

Endpoints now interact with the refactored MarketService and PluginLoader.

The /providers endpoint logic is updated to correctly list providers based on the market and plugin capabilities.

Error handling is more aligned with the new custom exception types.

websocket_blueprint.py:

Now uses the new SubscriptionService for managing WebSocket subscriptions and data flow.

4. Error Handling
A more defined hierarchy of custom exceptions has been introduced (e.g., PluginError and its subclasses, DataSourceError).

Error handling within services and blueprints is generally more explicit, mapping to appropriate HTTP responses or WebSocket error messages.

5. Key Functional Changes
Provider-Specific Plugin Instances: MarketService now manages instances of plugins that are specific to a provider ID, API key configuration, and testnet status. This is a fundamental shift from the previous model where a single plugin instance might have handled multiple providers internally.

Layered Data Fetching: DataOrchestrator implements a clear strategy for fetching data: Cache -> Aggregates -> Live Plugin.

Improved Caching:

RedisCache offers more specific caching methods for 1m and resampled data.

MarketService caches plugin instances, making internal plugin caches (like CryptoPlugin's market data cache) more effective.

Robust Background Task Management: For backfills (BackfillManager) and WebSocket polling (SubscriptionWorker), with better locking and lifecycle control.

For Developers Working on This Codebase:
Familiarize yourself with the new service layer in the services/ directory, as it contains most ofclassName the core logic.

Understand the MarketPlugin ABC and how individual plugins (CryptoPlugin, AlpacaPlugin) are now instantiated and managed by MarketService.

Note how DataOrchestrator uses the DataSource implementations.

The SubscriptionService and SubscriptionWorker handle WebSocket logic.

Configuration is centralized in config.py and logging in app_extensions/init_app_extensions.py.

API endpoints are defined in the blueprints/ directory.

This refactoring aims to provide a more stable, extensible, and understandable backend system.