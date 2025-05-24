# OHLCV Data Server API

## Description

This project is a Python-based server API designed to collect, store, and serve Open, High, Low, Close, and Volume (OHLCV) data for various financial markets. It features a modular plugin system to support different data providers (e.g., cryptocurrency exchanges via CCXT, stock markets via Alpaca) and leverages a PostgreSQL database with TimescaleDB for efficient time-series data management. The API is built using the Quart web framework and includes functionalities for data fetching, caching, real-time updates via WebSockets, and user authentication.

## Features

* **Modular Plugin System**: Easily extendable to support new data providers and markets.
    * Currently supports cryptocurrency exchanges through CCXT (`CryptoPlugin`).
    * Supports stock markets through Alpaca (`AlpacaPlugin`).
* **Time-series Database**: Utilizes PostgreSQL with TimescaleDB for storing and querying OHLCV data efficiently.
* **Continuous Aggregation**: Pre-aggregates 1-minute OHLCV data into various timeframes (5min, 15min, 30min, 1h, 4h, 1d, 1w, 1mon, 1y) for faster querying.
* **RESTful API**: Provides endpoints to:
    * List available markets and providers.
    * Fetch symbols for a given market/provider.
    * Fetch historical and latest OHLCV data with various parameters (timeframe, since, until, limit).
    * User authentication (login, refresh token).
    * User configuration saving and retrieval.
* **WebSocket Subscriptions**: Allows clients to subscribe to real-time OHLCV updates for specific assets.
* **Data Orchestration**: Manages data fetching from multiple sources (cache, aggregates, live plugins) with pagination and resampling capabilities.
* **Caching**:
    * Caches market data (symbols, etc.) at the plugin instance level.
    * Uses Redis for caching 1-minute OHLCV data and resampled data to reduce database load and improve response times.
* **Backfill Management**: System to find and fill gaps in historical 1-minute data from plugins.
* **Configuration Management**: Flexible configuration setup for different environments (development, production, testing).
* **Error Handling**: Standardized error responses across the API.
* **Authentication Middleware**: JWT-based authentication for protecting user-specific endpoints.

## Technologies Used

* **Backend**: Python
* **Web Framework**: Quart
* **Database**: PostgreSQL with TimescaleDB extension
* **Caching**: Redis (via `aioredis`)
* **Cryptocurrency Data**: CCXT library
* **Stock Data**: Alpaca API (via `aiohttp`)
* **Asynchronous Programming**: `asyncio`

## Project Structure Overview

The project is organized into several key directories and modules:

* **`app.py`**: Main application entry point, creates and configures the Quart app, initializes services and blueprints.
* **`config.py`**: Handles application configuration for different environments (Development, Production, Testing).
* **`plugins/`**: Contains the plugin system for market data integration.
    * `base.py`: Defines the abstract `MarketPlugin` class and custom plugin exceptions.
    * `crypto.py`: Implements `CryptoPlugin` using CCXT for fetching cryptocurrency data.
    * `alpaca.py`: Implements `AlpacaPlugin` using Alpaca API for fetching stock data.
    * `__init__.py` (PluginLoader): Dynamically discovers and manages `MarketPlugin` classes.
* **`services/`**: Contains various services that encapsulate business logic.
    * `market_service.py`: Manages plugin instances, API key configurations, and orchestrates data fetching.
    * `data_orchestrator.py`: Core component for fetching OHLCV data from various sources (cache, aggregates, plugins), handles resampling and caching strategies.
    * `data_sources/`: Defines different data source types.
        * `base.py`: Abstract `DataSource` class.
        * `cache_source.py`: Fetches data from Redis cache with database fallback, handles resampling and caching of resampled data.
        * `db_source.py`: Interacts with the primary OHLCV database for reads and writes.
        * `aggregate_source.py`: Fetches data from TimescaleDB continuous aggregate views.
        * `plugin_source.py`: Adapts `MarketPlugin` instances to the `DataSource` interface.
    * `cache_manager.py`: (Assumed, based on `RedisCache` and `CacheABC`) Abstract interface and Redis implementation for caching.
    * `redis_cache.py`: (Assumed, likely contains `RedisCache` implementation)
    * `resampler.py`: Handles resampling of OHLCV data to different timeframes.
    * `subscription_service.py`: Manages WebSocket client subscriptions and dispatches data updates via workers.
    * `subscription_worker.py`: Periodically polls for new data for a specific subscription and broadcasts updates.
    * `subscription_registry.py`: Keeps track of active WebSocket subscriptions.
    * `subscription_lock.py`: Ensures only one worker polls for a unique subscription key.
    * `broadcast_manager.py`: Handles broadcasting messages to subscribed WebSocket clients.
    * `auth_service.py`: Handles user authentication and JWT generation/refresh.
    * `user_service.py`: Manages user-specific data like configurations.
    * `backfill_manager.py`: Manages the process of fetching and storing missing historical 1-minute data.
* **`blueprints/`**: Quart blueprints for organizing routes.
    * `market.py`: API endpoints for market data (providers, symbols, OHLCV).
    * `auth.py`: API endpoints for user authentication (`/login`, `/refresh`).
    * `user.py`: API endpoints for user-specific operations (`/save_config`, `/get_user_data`).
    * `websocket.py`: WebSocket endpoint (`/subscribe`) for real-time data.
* **`middleware/`**: Custom middleware for the Quart application.
    * `auth_middleware.py`: JWT-based authentication and role enforcement.
    * `error_handler.py`: Global error handlers for common HTTP errors.
* **`utils/`**: Utility functions and classes.
    * `db_utils.py`: Helper functions for database interactions (fetch, execute, data insertion/retrieval for OHLCV).
    * `timeframes.py`: Utilities for parsing and handling timeframe strings and timestamps.
    * `response.py`: Standardized API response formatting.
    * `validation.py`: Request data validation helpers.
* **`app_extensions/`**: Handles initialization of app extensions like database pool, Redis, logging, and other services at startup.
    * `__init__.py`: Orchestrates the initialization of various extensions.
    * `logging_config.py`: Configures application-wide logging.
    * `db_pool.py`: Initializes and manages the `asyncpg` database connection pool.
    * `redis_manager.py`: Initializes and manages the Redis client and `RedisCache` service.
    * `plugin_loader_init.py`: (Assumed) Initializes the `PluginLoader`.
    * `subscription_service_init.py`: (Assumed) Initializes the `SubscriptionService`.

## Database Schema

The primary database schema revolves around storing OHLCV data and managing pre-aggregated views for performance.

* **`ohlcv_data` Table**:
    * Stores raw OHLCV data, typically at 1-minute resolution.
    * Columns: `market` (text), `provider` (text), `symbol` (text), `timeframe` (text), `timestamp` (timestamptz), `base_currency` (text, nullable), `quote_currency` (text, nullable), `open` (float8), `high` (float8), `low` (float8), `close` (float8), `volume` (float8), `source` (text, default 'api').
    * Primary Key: `(market, provider, symbol, timeframe, timestamp)`.
    * This table is a TimescaleDB hypertable, partitioned by `timestamp`.

* **Continuous Aggregates / Materialized Views**:
    * The system uses TimescaleDB continuous aggregates to create materialized views for various timeframes (e.g., `ohlcv_5min`, `ohlcv_15min`, `ohlcv_30min`, `ohlcv_1h`, `ohlcv_4h`, `ohlcv_1d`, `ohlcv_1w`, `ohlcv_1mon`, `ohlcv_1y`).
    * These views are derived from the 1-minute data in `ohlcv_data`.
    * They typically include: `market`, `provider`, `symbol`, `timeframe` (target timeframe), `bucketed_time` (start of the aggregate period), `open` (first open in bucket), `high` (max high), `low` (min low), `close` (last close), `volume` (sum of volume).

* **`preaggregation_configs` Table**:
    * Stores metadata about the pre-aggregated views.
    * Columns: `config_id` (serial, pk), `view_name` (text, unique), `target_timeframe` (text, unique), `base_timeframe` (text), `bucket_interval` (text), `is_active` (boolean), `description` (text).
    * This table is used by `AggregateSource` to dynamically find and query the correct materialized view.

* **Indexes and Triggers**:
    * Various indexes are created on the hypertable chunks and materialized views for query optimization, primarily on `bucketed_time` and combinations of `market`, `provider`, `symbol`, and `bucketed_time`.
    * Triggers (`ts_cagg_invalidation_trigger`) are used for continuous aggregate invalidation when base data in `ohlcv_data` changes.

## API Endpoints

### Market Data (`/api/market`)

* **GET `/providers`**: Get a list of available data providers for a given market.
    * Query Parameters: `market` (string, required)
* **GET `/symbols`**: Get a list of tradable symbols for a given market and provider.
    * Query Parameters: `market` (string, required), `provider` (string, required)
* **GET `/ohlcv`**: Fetch OHLCV data for a given symbol.
    * Query Parameters:
        * `market` (string, required)
        * `provider` (string, required)
        * `symbol` (string, required)
        * `timeframe` (string, default: "1m")
        * `since` (integer, optional, millisecond timestamp)
        * `until` (integer, optional, millisecond timestamp, also accepts `before`)
        * `limit` (integer, optional, default configured by `DEFAULT_CHART_POINTS`)

### Authentication (`/api/auth`)

* **POST `/login`**: Authenticate a user.
    * Request Body: `{"username": "...", "password": "..."}`
    * Response: `{"token": "jwt_token"}`
* **POST `/refresh`**: Refresh an existing JWT.
    * Request Body: `{"token": "existing_jwt_token"}`
    * Response: `{"token": "new_jwt_token"}`

### User (`/api/user`) - Requires JWT Authentication

* **POST `/save_config`**: Save user-specific configuration.
    * Request Body: JSON object with user configuration data.
* **GET `/get_user_data`**: Retrieve user-specific data.

### WebSocket (`/api/ws`)

* **`/subscribe`**: Endpoint for WebSocket connections.
    * Client sends JSON messages:
        * `{"type":"subscribe", "market": "...", "provider": "...", "symbol": "...", "timeframe": "...", "since": ... (optional)}`
        * `{"type":"unsubscribe"}`
    * Server sends data updates and pings.

## Setup and Installation (General Guidance)

1.  **Environment Setup**:
    * Set up a Python virtual environment.
    * Install dependencies from `requirements.txt` (not provided, but typical).
2.  **Database Setup**:
    * Install PostgreSQL.
    * Install the TimescaleDB extension for PostgreSQL.
    * Create a database and user.
    * Apply the schema (from `1.txt` or an equivalent migration script). Specifically, create the `ohlcv_data` hypertable and `preaggregation_configs` table.
    * Configure continuous aggregate policies as defined by the views in `1.txt`.
3.  **Redis Setup**:
    * Install and run a Redis server if caching is desired.
4.  **Configuration**:
    * Set environment variables as defined in `config.py` (e.g., `ENV`, `DB_CONNECTION_STRING`, `REDIS_URL`, `SECRET_KEY`, API keys for providers).
5.  **Running the Application**:
    * Use a command like `quart run` or an ASGI server like Hypercorn.

## How to Run (General Guidance)

```bash
# 1. Set environment variables (example)
export ENV="development"
export DB_CONNECTION_STRING="postgresql://user:password@host:port/database"
export REDIS_URL="redis://localhost:6379/0"
export SECRET_KEY="your_very_secret_key"
export ALPACA_API_KEY="your_alpaca_key"
export ALPACA_API_SECRET="your_alpaca_secret"
# ... other provider API keys as needed

# 2. (If not done) Install dependencies
# pip install -r requirements.txt

# 3. (If not done) Initialize database schema and TimescaleDB extension

# 4. Run the Quart application
quart run --host 0.0.0.0 --port 5000