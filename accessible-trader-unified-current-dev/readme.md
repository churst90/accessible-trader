# Accessible Trader: OHLCV Data Server & Trading API

## Description

This project is a Python-based server API designed to collect, store, and serve Open, High, Low, Close, and Volume (OHLCV) data for various financial markets, and to provide a platform for manual and automated trading. It features a modular plugin system to support different data providers (e.g., cryptocurrency exchanges via CCXT) and leverages multiple databases: PostgreSQL with TimescaleDB for efficient time-series OHLCV data management, and MariaDB/MySQL for user authentication, API credentials, bot configurations, and user preferences.

The application is built using the Quart web framework. It serves both a comprehensive API and the HTML frontend for the application. Key functionalities include advanced data fetching and orchestration, robust caching, real-time data updates via WebSockets using Redis Pub/Sub, user authentication, secure credential management, and a framework for deploying and managing trading bots.

## Features

* **Python-Served Frontend**: Quart serves HTML templates (Jinja2) and static assets, enabling a unified application structure.
* **Client-Side UI**: Interactive frontend built with vanilla JavaScript modules, handling API interactions, WebSocket connections, and dynamic UI updates.
* **Modular Plugin System**: Easily extendable to support new data providers and markets.
    * Currently supports cryptocurrency exchanges through CCXT (`CCXTPlugin`).
* **Multiple Database Support**:
    * **OHLCV Data**: PostgreSQL with TimescaleDB for storing and querying OHLCV data efficiently.
    * **Authentication Data**: MariaDB/MySQL (`auth_db`) for user accounts and roles.
    * **User Configurations**: MariaDB/MySQL (`user_configs_db`) for API credentials, bot settings, trade logs, chart layouts, and general user preferences.
* **Continuous Aggregation**: (For OHLCV DB) Pre-aggregates 1-minute OHLCV data into various timeframes for faster querying.
* **RESTful API**: Provides endpoints to:
    * List available markets and providers.
    * Fetch symbols for a given market/provider.
    * Fetch historical and latest OHLCV data.
    * Fetch detailed instrument trading parameters.
    * User authentication (login, register, refresh token).
    * Manage user API credentials (CRUD).
    * Manage user trading bot configurations (CRUD, start/stop).
    * Execute manual trading operations (place/cancel order, get order status, balances, positions).
    * Save and retrieve general user preferences.
* **WebSocket Subscriptions**: Allows clients to subscribe to real-time data updates (OHLCV, trades, order book, user orders) for specific assets, managed via Redis Pub/Sub for scalability.
* **Data Orchestration**: `DataOrchestrator` manages fetching from multiple sources (cache, aggregates, live plugins) with pagination and resampling.
* **Advanced Caching**:
    * Plugin instances are cached by `MarketService`.
    * Uses Redis for caching 1-minute OHLCV data and resampled data.
* **Real-time Stream Management**: `StreamingManager` handles connections to plugin data sources (native streaming or polling fallback) and publishes data to Redis Pub/Sub. `SubscriptionService` consumes from Redis and distributes to WebSocket clients.
* **Backfill Management**: System to find and fill gaps in historical 1-minute data.
* **Trading Bot Framework**:
    * Allows users to configure and run automated trading bots.
    * `BotManagerService` manages bot lifecycles.
    * `TradingBot` class executes strategies and interacts with exchanges.
    * Support for custom trading strategies.
* **Secure Credential Management**: User-provided API keys are encrypted before storage.
* **Configuration Management**: Flexible configuration for different environments.
* **Error Handling**: Standardized error responses and robust exception handling.
* **Authentication Middleware**: JWT-based authentication for API endpoints.

## Technologies Used

* **Backend**: Python
* **Web Framework**: Quart (with Jinja2 for templating)
* **Databases**:
    * PostgreSQL with TimescaleDB (for OHLCV data)
    * MariaDB/MySQL (for user authentication and configurations)
* **ORM/Database Drivers**:
    * `asyncpg` (for PostgreSQL/TimescaleDB)
    * SQLAlchemy 2.x Async (for MariaDB/MySQL) with `asyncmy` driver
* **Caching & Messaging**: Redis (via `aioredis`)
* **Cryptocurrency Data**: CCXT library
* **Asynchronous Programming**: `asyncio`
* **Frontend**: Vanilla JavaScript (ES Modules), HTML5, CSS3
* **Charting Library**: Highcharts Stock

## Project Structure Overview

* **`app.py`**: Main application entry point (Quart app factory).
* **`config.py`**: Application configuration.
* **`views.py`**: Quart blueprint for serving frontend HTML pages.
* **`templates/`**: Jinja2 HTML templates for the frontend.
* **`static/`**: Static assets (CSS, JavaScript, images) for the frontend.
    * `assets/js/modules/`: Client-side JavaScript modules (`dataService.js`, `chartController.js`, `wsService.js`, `auth_ui.js`, etc.).
* **`plugins/`**: Backend plugin system for market data integration.
    * `base.py`: `MarketPlugin` ABC.
    * `ccxt.py`: `CCXTPlugin` implementation.
    * `__init__.py`: `PluginLoader`.
* **`services/`**: Backend business logic services.
    * `market_service.py`: Manages plugins, orchestrates data.
    * `data_orchestrator.py`: Fetches, resamples, caches OHLCV.
    * `data_sources/`: `CacheSource`, `DbSource`, `AggregateSource`, `PluginSource`.
    * `cache_manager.py`: `Cache` ABC and `RedisCache`.
    * `streaming_manager.py`: Manages live data streams from plugins to Redis.
    * `subscription_registry.py`: Tracks WebSocket client view subscriptions.
    * `subscription_service.py`: Manages WebSocket client connections and data flow from Redis.
    * `auth_service.py`: User authentication, JWTs.
    * `user_service.py`: User general preferences.
    * `encryption_service.py`: Data encryption.
    * `backfill_manager.py`: Historical data backfilling.
* **`trading/`**: Backend trading bot functionality.
    * `bot_manager_service.py`: Manages bot lifecycles.
    * `bot.py`: `TradingBot` class.
    * `strategies/`: Base strategy and predefined strategies.
* **`blueprints/`**: Backend API route definitions.
    * `market.py`, `auth.py`, `user.py`, `websocket.py`, `user_credentials.py`, `trading_bot.py`, `trading.py`.
* **`middleware/`**: Custom Quart middleware.
    * `auth_middleware.py`, `error_handler.py`.
* **`models/`**: SQLAlchemy ORM models.
    * `auth_models.py` (for `auth_db`).
    * `user_config_models.py` (for `user_configs_db` - API keys, bots, trade logs, etc.).
* **`utils/`**: Backend utility functions.
    * `db_utils.py` (for `asyncpg` OHLCV DB interactions), `timeframes.py`, `response.py`, `validation.py`.
* **`app_extensions/`**: Initialization of app extensions (DBs, Redis, logging, services).

## Database Schemas

### 1. OHLCV Database (PostgreSQL with TimescaleDB)
* **`ohlcv_data` Table**: Stores raw 1-minute OHLCV data. Hypertable partitioned by `timestamp`.
    * Columns: `market`, `provider`, `symbol`, `timeframe`, `timestamp`, `open`, `high`, `low`, `close`, `volume`.
* **Continuous Aggregates**: Pre-aggregated views (e.g., `ohlcv_5min`, `ohlcv_1h`) derived from `ohlcv_data`.
* **`preaggregation_configs` Table**: Metadata for aggregate views.

### 2. Authentication Database (`auth_db` - MariaDB/MySQL)
* **`users` Table**: Stores user credentials and profile information.
    * Columns: `id`, `username`, `password` (hashed), `email`, `role`, `last_login`, `registration_date`, etc.
* (Optionally `roles`, `permissions`, `role_permissions` tables if implementing fine-grained RBAC).
* **`password_resets` Table**: For password reset functionality.

### 3. User Configurations Database (`user_configs_db` - MariaDB/MySQL)
* **`user_api_credentials` Table**: Stores encrypted user API keys for exchanges/providers.
    * Columns: `credential_id`, `user_id`, `service_name`, `credential_name`, `encrypted_api_key`, `encrypted_api_secret`, `encrypted_aux_data`, `is_testnet`, `notes`.
* **`user_trading_bots` Table**: Stores configurations for user-defined trading bots.
    * Columns: `bot_id`, `user_id`, `bot_name`, `credential_id` (FK), `strategy_name`, `strategy_params_json`, `market`, `symbol`, `timeframe`, `is_active`, `status_message`.
* **`trade_logs` Table**: Logs trades executed by bots or manual actions.
    * Columns: `trade_log_id`, `user_id`, `bot_id` (nullable, FK), `credential_id` (FK), `exchange_order_id`, `client_order_id`, `timestamp`, `symbol`, `order_type`, `side`, `price`, `quantity`, `status`, `commission_amount`, `commission_asset`, `notes`.
* **`user_chart_layouts` Table**: Stores user-saved chart configurations.
* **`user_general_preferences` Table**: General UI and application preferences per user.
* **`user_indicator_presets` Table**: User-defined presets for indicator configurations.

*(Detailed schemas for `auth_db` and `user_configs_db` are in their respective SQL or model files.)*

## API Endpoints

### Market Data (`/api/market`)
* **GET `/providers?market=<market_name>`**: List available data providers.
* **GET `/symbols?market=<market_name>&provider=<provider_name>`**: List tradable symbols.
* **GET `/ohlcv?market=...&provider=...&symbol=...&timeframe=...`**: Fetch OHLCV data.
    * Optional query params: `since`, `until` (or `before`), `limit`.
* **GET `/markets`**: List all unique market categories supported by available plugins.
* **GET `/<market>/<provider>/<symbol>/trading-details?market_type=...`**: Get detailed trading rules for an instrument. (Requires JWT)

### Authentication (`/api/auth`)
* **POST `/login`**: Authenticate user, returns JWT.
* **POST `/register`**: Register a new user.
* **POST `/refresh`**: Refresh an existing JWT.

### User Preferences (`/api/user`) - Requires JWT
* **POST `/save_config`**: Save general user preferences.
* **GET `/get_user_data`**: Retrieve general user preferences.
    *(Endpoints for chart layouts and indicator presets to be added here)*

### User API Credentials (`/api/credentials`) - Requires JWT
* **POST `/`**: Add a new API credential set.
* **GET `/`**: List all API credentials for the user.
* **DELETE `/<credential_id>`**: Delete a specific API credential.

### Trading Operations (`/api/trading`) - Requires JWT
* **POST `/order`**: Place a manual trading order.
* **GET `/orders/<order_id_from_path>?credential_id=...&...`**: Get status of a specific order.
* **DELETE `/orders/<order_id_from_path>?credential_id=...&...`**: Cancel a specific order.
* **GET `/balances?credential_id=...&...`**: Get account balances for a credential.
* **GET `/positions?credential_id=...&...`**: Get open positions for a credential.

### Trading Bots (`/api/bots`) - Requires JWT
* **POST `/`**: Create a new trading bot configuration.
* **GET `/`**: List all bot configurations for the user.
* **GET `/<bot_id>`**: Get details for a specific bot configuration and its live status.
* **PUT `/<bot_id>`**: Update an existing bot configuration.
* **DELETE `/<bot_id>`**: Delete a bot configuration (stops the bot if active).
* **POST `/<bot_id>/start`**: Start a configured trading bot.
* **POST `/<bot_id>/stop`**: Stop an active trading bot.

### WebSocket (`/api/ws`)
* **`/subscribe`**: Endpoint for WebSocket connections.
    * Client sends JSON messages for `subscribe` (to ohlcv, trades, order_book, user_orders) and `unsubscribe`.
    * Server sends data updates, status, errors, and pings.

## Setup and Installation

1.  **Backend Environment**:
    * Python 3.10+ and virtual environment recommended.
    * Install dependencies: `pip install -r requirements.txt` (create this file based on project imports).
2.  **Databases**:
    * **PostgreSQL**: Install PostgreSQL & TimescaleDB extension. Create database (e.g., `ohlcv_db`). Apply schema for `ohlcv_data`, `preaggregation_configs`, and TimescaleDB hypertable/aggregates setup.
    * **MariaDB/MySQL**: Install MariaDB or MySQL. Create databases (e.g., `auth_db`, `user_configs_db`). Apply schemas (e.g., from `models/auth_models.py` and `models/user_config_models.py` definitions, potentially using Alembic for migrations).
3.  **Redis**: Install and run a Redis server.
4.  **Configuration (`.env` file)**:
    * Create a `.env` file in the project root.
    * Set `ENV` (development/production).
    * Database connection strings: `OHLCV_DB_CONNECTION_STRING`, `AUTH_DB_CONNECTION_STRING`, `USER_CONFIGS_DB_CONNECTION_STRING`.
    * `REDIS_URL`.
    * `SECRET_KEY` (strong, random string for JWTs and session encryption).
    * `ENCRYPTION_KEY_FERNET` (for encrypting API keys, generate using `Fernet.generate_key().decode()`).
    * Other settings as defined in `config.py`.
5.  **Database Migrations (Recommended for `auth_db` & `user_configs_db`):**
    * Consider using Alembic with SQLAlchemy to manage schema migrations for the MariaDB/MySQL databases.
6.  **Frontend Assets**:
    * Ensure Node.js/npm is available if you plan to use a JavaScript bundler (Webpack, Parcel) for `static/assets/js/*.bundle.js` files. If not bundling, ensure individual JS modules are correctly linked.

## Running the Application

1.  **Start Backend Server**:
    * Ensure all databases and Redis are running.
    * Set environment variables (or ensure `.env` is loaded by `config.py`).
    * Run the Quart application using Hypercorn (as per `start-server.sh`):
        ```bash
        # From your Python project root
        ./start-server.sh
        ```
        This typically starts Hypercorn listening on `127.0.0.1:5000`.
2.  **Configure Web Server (Apache/Nginx) as Reverse Proxy**:
    * Set up your main web server (e.g., Apache listening on port 80/443 for `accessibletrader.com`) to reverse proxy requests to the Hypercorn server (`http://127.0.0.1:5000`).
    * Ensure WebSocket proxying is correctly configured.
3.  **Access Frontend**:
    * Open `https://accessibletrader.com` (or your configured domain) in a web browser.

## Development Notes

* The frontend now expects to be served by the Quart application.
* Client-side authentication relies on JWTs stored in `localStorage`.
* API interactions are handled by JavaScript modules in `static/assets/js/`.
* Pay attention to CORS configuration in `config.py` if the frontend is ever served from a different domain than the API during development (though with Quart serving HTML, this is less of an issue).