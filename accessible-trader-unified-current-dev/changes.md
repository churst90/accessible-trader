# Project Changes (Backend & Frontend Integration)

This document outlines the major architectural and functional changes in this version of the application, encompassing both backend server enhancements and the integration of a Python-served frontend. The goal is to create a modular, scalable, maintainable, and robust full-stack trading application.

## 1. Major Architectural Overhaul: Service-Oriented Backend & Python-Served Frontend

### 1.1. Backend: Service Layer & Plugin Architecture (`services/`, `plugins/`)

The backend has adopted a formal service layer and a redesigned plugin architecture.

#### `plugins/base.py` - `MarketPlugin` Abstract Base Class (ABC)
- **Status**: Implemented
- **Details**:
    - Standardizes plugin behavior for market data and trading operations.
    - Plugin instances are configured for a specific `provider_id` (e.g., one `CCXTPlugin` instance for "binance").
    - Standardized class methods for plugin discovery: `get_plugin_key()`, `get_supported_markets()`, `list_configurable_providers()`.
    - Introduced a hierarchy of plugin-specific exceptions: `PluginError`, `AuthenticationPluginError`, `NetworkPluginError`, `PluginFeatureNotSupportedError`.

#### `plugins/__init__.py` - `PluginLoader`
- **Status**: Implemented
- **Details**:
    - Discovers plugin classes based on the `MarketPlugin` ABC.
    - Maps market names (e.g., "crypto") to `plugin_key`s for dynamic routing by `MarketService`.

#### `plugins/ccxt.py` - `CCXTPlugin`
- **Status**: Implemented
- **Details**:
    - Generic plugin using the CCXT library for multiple crypto exchanges.
    - Handles a single CCXT exchange ID per instance.
    - Implements a wide range of `MarketPlugin` methods for data fetching, trading, and streaming.
    - Includes error mapping and data transformation helpers.
    - Manages WebSocket `watch_*` tasks for streaming.

### 1.2. Backend: Core Services (`services/`)

#### `MarketService` (`services/market_service.py`)
- **Status**: Implemented
- **Details**:
    - **Plugin Instance Management**: Caches `MarketPlugin` instances, keyed appropriately for reuse.
    - **Idle Plugin Cleanup**: Periodic background task to close idle plugin instances.
    - **Orchestration Hub**: Delegates data fetching to `DataOrchestrator` and backfills to `BackfillManager`.
    - **User Credentials**: Retrieves user-specific API credentials from `user_configs_db` via `_get_user_api_credentials`.

#### `DataOrchestrator` (`services/data_orchestrator.py`)
- **Status**: Implemented
- **Details**:
    - Manages the data fetching pipeline: Cache -> Aggregates -> Plugin.
    - Handles pagination for plugin data (`_fetch_from_plugin_with_paging`).
    - Saves new 1m plugin data to DB and cache; caches resampled/aggregate data.

#### `DataSource` Subsystem (`services/data_sources/`)
- **Status**: Implemented
- **Details**: `DataSource` ABC with implementations: `CacheSource`, `DbSource`, `AggregateSource`, `PluginSource`.

#### `CacheManager` & `RedisCache` (`services/cache_manager.py`)
- **Status**: Implemented
- **Details**: `Cache` ABC and `RedisCache` implementation with domain-specific methods, retries, and Prometheus metrics.

#### `StreamingManager` (`services/streaming_manager.py`)
- **Status**: Implemented
- **Details**:
    - Manages real-time data feed subscriptions to plugins.
    - Supports native plugin streaming (e.g., WebSockets via CCXT's `watch_*` methods) and falls back to REST polling if native streaming is unavailable.
    - Publishes all acquired data to standardized Redis Pub/Sub channels.
    - Manages reference counts for streams to start/stop underlying plugin feeds.

#### `SubscriptionRegistry` (`services/subscription_registry.py`)
- **Status**: Implemented
- **Details**: Tracks active WebSocket client subscriptions, allowing multiple distinct data views per client connection. Manages mapping between WebSockets and `SubscriptionKey`s.

#### `SubscriptionService` (`services/subscription_service.py`)
- **Status**: Implemented
- **Details**:
    - Manages client WebSocket connections and their specific data view subscriptions using `SubscriptionRegistry`.
    - For each client view, ensures the underlying data stream is active via `StreamingManager`.
    - Spawns dedicated `asyncio.Task` (`_redis_listener_for_client_channel`) for each client view to listen to the relevant Redis Pub/Sub channel (populated by `StreamingManager`) and forward formatted data to the client.
    - Handles fetching initial historical data for new subscriptions.

#### `BackfillManager` (`services/backfill_manager.py`)
- **Status**: Implemented
- **Details**: Manages historical 1m data backfills, detects gaps, fetches in chunks via plugins, uses an API semaphore, and stores to DB/cache.

#### User & Credential Services
- **`EncryptionService` (`services/encryption_service.py`):** Implemented for encrypting/decrypting sensitive data like API keys.
- **`AuthService` (`services/auth_service.py`):** Implemented for user authentication, JWT generation/refresh/decoding, and authorization checks against `auth_db`.
- **`UserService` (`services/user_service.py`):** Implemented for saving/retrieving user general preferences from `user_configs_db`.

#### Trading Services
- **`BotManagerService` (`trading/bot_manager_service.py`):** Implemented to manage trading bot lifecycles (load, create from config, start, stop, status updates) using `user_configs_db` and `MarketService`.
- **`TradingBot` (`trading/bot.py`):** Implemented with a run loop, strategy execution, signal handling, and trade logging.
- **`TradingStrategyBase` (`trading/strategies/base_strategy.py`):** ABC for strategies implemented, along with `Signal` and `StrategyMarketData` types.
- **`SMACrossoverStrategy` (`trading/strategies/predefined/sma_crossover_strategy.py`):** Example strategy implemented.

### 1.3. Frontend Architecture (New Focus)
- **Quart Serving HTML**: The Python Quart backend is now configured to serve the main HTML shell pages for the application (e.g., `index.html`, `chart.html`, `login.html`). [No specific code cite for this change in v5, but discussed and implemented in this session]
- **Static Asset Serving**: Quart serves static assets (CSS, JS) from a `static/` directory. [No specific code cite for this change in v5, but discussed and implemented in this session]
- **Client-Side JS Modules**: Frontend logic is organized into JavaScript modules (`static/assets/js/modules/`).
- **Single Page Application (SPA) Characteristics**: The frontend will operate more like an SPA, with JavaScript handling UI updates, API interactions, and authentication state management after initial page load.

## 2. Application Setup and Configuration (`config.py`, `app.py`, `app_extensions/`)

### Backend Configuration (`config.py`)
- **Status**: Implemented
- **Details**: Robust configuration classes (`BaseConfig`, `DevelopmentConfig`, etc.) with a `validate()` method.

### Logging (`app_extensions/__init__.py`, `app.py`)
- **Status**: Implemented
- **Details**: Uses `logging.dictConfig` for a comprehensive setup via `app.config`.

### Application Lifecycle (`app.py`, `app_extensions/__init__.py`)
- **Status**: Implemented
- **Initialization**: Core services (DB pools, Redis, `MarketService`, `StreamingManager`, `SubscriptionService`, `BotManagerService`, Auth DBs, User Configs DB) initialized via `@app.before_serving` or directly in `create_app`.
- **Shutdown**: Graceful shutdown of services in `@app.after_serving`.

### Database & Redis Management (`app_extensions/`)
- **Status**: Implemented
- **Details**:
    - `db_pool.py`: Manages `asyncpg` pool for OHLCV DB.
    - `redis_manager.py`: Manages `aioredis` client and `RedisCache` instance.
    - `auth_db_setup.py`: Manages SQLAlchemy async engine/sessions for `auth_db`.
    - `user_configs_db_setup.py`: Manages SQLAlchemy async engine/sessions for `user_configs_db`.

## 3. API Blueprints & Frontend Routes

### Backend API Blueprints (`blueprints/`)
- **Status**: Implemented
- **Details**:
    - `market_blueprint.py`: Interacts with `MarketService`. `/providers` endpoint logic updated.
    - `auth_blueprint.py`: Handles `/login`, `/refresh`. **NEW**: `/register` endpoint added.
    - `websocket_blueprint.py`: Uses `SubscriptionService` for WebSocket subscriptions.
    - `user_blueprint.py`: Handles user general preferences.
    - `user_credentials_bp.py`: CRUD for user API credentials.
    - `trading_bot_bp.py`: CRUD for bot configurations, start/stop controls.
    - `trading_blueprint.py`: Manual trading operations (place/cancel order, get status, balances, positions).

### Frontend View Routes (`views.py` - New)
- **Status**: Implemented (in this session)
- **Description**: A new `frontend_bp` Blueprint created to serve HTML pages from the `templates/` directory.
- **Action**:
    - Created routes for `/`, `/chart`, `/login`, `/register`, `/faq`, `/support`.
    - Placeholder routes for `/profile`, `/credentials`, `/bots` can be added.
- **Impact**: Enables Quart to serve the frontend application shell.

## 4. Error Handling (Backend)
- **Status**: Implemented
- **Details**: Hierarchy of custom exceptions (`PluginError`, `DataSourceError`, etc.) used throughout the backend. Global HTTP error handlers in `middleware/error_handler.py`.

## 5. Frontend Client-Side Logic (JavaScript)

### `dataService.js` (`static/assets/js/modules/`)
- **Status**: Updated (in this session)
- **Details**:
    - Added JWT management functions (`storeToken`, `getToken`, `clearToken`).
    - Modified `apiFetch` to automatically include `Authorization: Bearer <token>` header.
    - Implemented `loginUser`, `logoutUser`, `refreshToken`.
    - Implemented `registerUser` to call the new backend registration endpoint.
    - Added stubs or full functions for interacting with user preferences, API credentials, trading, and bot management endpoints.

### `auth_ui.js` (`static/assets/js/`)
- **Status**: Implemented (in this session)
- **Description**: New module to handle client-side authentication UI.
- **Details**:
    - Handles login and registration form submissions using `dataService.js`.
    - Updates UI elements (navigation links, visibility of trading dashboard) based on authentication state by listening to an `authChange` custom event.

### HTML Templates (`templates/`)
- **Status**: Created (in this session)
- **Description**: New Jinja2 HTML templates created (`layout.html`, `index.html`, `chart.html`, `login.html`, `register.html`, `faq.html`, `support.html`).
- **Details**:
    - `layout.html` provides common structure, navigation, and script/CSS includes.
    - Other templates extend `layout.html`.
    - Placeholders for auth-dependent UI elements and new features like the trading dashboard.

## 6. Key Functional Changes Summary

- **Unified Serving**: Python/Quart backend now serves both the API and the frontend HTML pages. (New in this session)
- **Client-Side Authentication**: Frontend JavaScript now manages JWTs for API authentication and updates UI accordingly. (New in this session)
- **Provider-Specific Plugin Instances**: `MarketService` manages specific plugin instances.
- **Layered Data Fetching**: `DataOrchestrator` uses a clear Cache -> Aggregates -> Plugin strategy.
- **Real-time Data Flow**: `StreamingManager` fetches/polls data, publishes to Redis. `SubscriptionService` subscribes to Redis and sends updates to WebSocket clients.
- **Modular Services**: Dedicated services for major functionalities (market data, user configs, auth, trading bots).
- **Comprehensive Bot Management**: Backend services and API for creating, configuring, and controlling trading bots.
- **Manual Trading API**: Endpoints for users to place/manage orders and view account status.
- **User API Credential Management**: Secure storage and management of user API keys.