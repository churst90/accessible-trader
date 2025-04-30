## Overview
AccessibleTrader is a fully accessible backend designed to power a financial trading platform that prioritizes inclusivity. It integrates seamlessly with Highcharts (including its built-in accessibility features) to present market data in a way that can be understood and interacted with by users of all abilities—including those who rely on screen readers.

This backend handles the heavy lifting of:
- Fetching market data (symbols, OHLCV data, etc.) from various cryptocurrency exchanges via [CCXT](https://github.com/ccxt/ccxt)
- Storing and retrieving data using a TimescaleDB (PostgreSQL) time-series database
- Serving data through a RESTful API that can be easily consumed by accessible frontends
- Offering realtime (WebSocket) endpoints for streaming data updates
- Caching frequently requested data in Redis for performance
- Managing user authentication, roles, and JWT-based token handling
  
The ultimate goal is to provide a reliable, performant, and extensible backend platform that can power a fully accessible trading website front-end.

## Key Features
- Asynchronous Python Backend: Built with [Quart](https://pgjones.gitlab.io/quart/), an async Python framework similar to Flask but with native async/await support.
- Market Data via CCXT: Leverages the CCXT async library to fetch exchange info, symbol lists, and OHLCV market data from supported cryptocurrency exchanges.
- Time-Series Data with TimescaleDB: Uses a Postgres + TimescaleDB backend to store historical OHLCV data, enabling fast aggregation, continuous aggregates, and efficient time-series queries.
- Redis Caching: Speeds up repeated queries by caching results in Redis.
- JWT Authentication and Role-Based Access Control: Secure endpoints with JWT tokens, and restrict certain actions based on user roles.
- WebSockets for Real-Time Data: Subscribe to live market updates over WebSockets.
- Accessibility-Driven: Designed to feed front-end charting libraries like Highcharts configured with accessibility enabled. Responses are structured so they can be easily interpreted by screen readers and other assistive technologies.

## Architecture & Directory Structure
```
project_root/
+- app.py                     # Application factory and main entrypoint
+- start.sh                   # Start script with Hypercorn
+- config.py                  # Configuration loading & validation
+- .env                       # Environment variables (DB credentials, Redis URL, etc.)
¦
+- app_extensions/            # Application lifecycle hooks and extensions init
¦  +- __init__.py             # init_app_extensions to initialize DB, Redis, logging
¦  +- db_pool.py              # Database pool initialization & retrieval
¦  +- redis_manager.py        # Redis cache initialization & retrieval
¦
+- blueprints/                # REST API endpoints organized by Blueprint
¦  +- __init__.py             # Blueprint initialization
¦  +- auth.py                 # Authentication routes (login, refresh token)
¦  +- market.py               # Market data routes (get_exchanges, get_symbols, fetch_ohlcv)
¦  +- websocket.py            # WebSocket route for realtime market data
¦
+- middleware/                # Error handling and authentication middleware
¦  +- __init__.py
¦  +- error_handler.py        # Standardized error responses
¦  +- auth_middleware.py      # JWT and role-based access decorators
¦
+- plugins/                   # Market plugins (e.g., crypto)
¦  +- __init__.py             # Plugin loader & registration
¦  +- crypto.py               # CryptoPlugin using CCXT for exchange data
¦
+- services/                  # Business logic and data orchestration
¦  +- __init__.py
¦  +- auth_service.py         # Authentication, JWT generation/refresh
¦  +- market_service.py       # Market data retrieval, caching, DB interactions
¦  +- websocket_service.py    # Handling websocket subscriptions and broadcasts
¦
+- utils/                     # Utility modules
¦  +- __init__.py
¦  +- cache.py                # Redis-based caching class
¦  +- db_utils.py             # Common DB queries and helpers
¦  +- response.py             # Standard response formatting functions
¦  +- validation.py           # Input validation helpers
¦  +- websocket_manager.py    # Manages active websocket connections and broadcasts
¦
+- accessibletrader_db.sql    # SQL schema and TimescaleDB setup
```

## Prerequisites
- Python 3.9+ recommended
- PostgreSQL + TimescaleDB installed and accessible
- Redis installed and running
- ccxt (async version) installed for market data fetching
- Hypercorn or another ASGI server for running the app in production

## Setup Instructions
1. Clone the Repository
   ```bash
   git clone https://github.com/yourusername/accessibletrader-backend.git
   cd accessibletrader-backend
   ```

2. Create and Activate a Virtual Environment
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. Install Dependencies
   ```bash
   pip install -r requirements.txt
   ```
   
   Ensure the requirements.txt includes all necessary packages such as:
   - quart
   - quart-cors
   - asyncpg
   - aioredis
   - ccxt (async support)
   - bcrypt
   - jwt (PyJWT)
   - pandas
   - python-dotenv
   - hypercorn

4. Set Environment Variables
   Copy `.env.example` to `.env` and fill in the required values:
   - `SECRET_KEY` for JWT
   - `DB_CONNECTION_STRING` (for PostgreSQL/TimescaleDB)
   - `REDIS_URL`
   - `TRUSTED_ORIGINS` (for CORS)
   
   Example:
   ```env
   SECRET_KEY=your-secret-key
   DB_CONNECTION_STRING=postgresql://admin:password@localhost/accessibletrader_db
   REDIS_URL=redis://localhost
   TRUSTED_ORIGINS=https://yourfrontenddomain.com
   ENV=development
   ```

5. Database Setup
   - Make sure TimescaleDB is installed and enabled on your PostgreSQL instance.
   - Run the SQL setup script:
     ```bash
     psql -U admin -h localhost -d accessibletrader_db -f accessibletrader_db.sql
     ```
   This creates all necessary tables, hypertables, and continuous aggregates.

6. Run the Server
   ```bash
   ./start.sh
   ```
   The server should now be running on `https://accessibletrader.com:5000`.

## Testing the Endpoints
- Get Exchanges:  
  ```  
  https://accessibletrader.com:5000/market/get_exchanges?market=crypto
  ```
  This should return a JSON list of supported exchanges.

- Get Symbols for Bitstamp:  
  ```
  https://accessibletrader.com:5000/market/get_symbols?market=crypto&exchange=bitstamp
  ```
  This returns an array of trading pairs available on Bitstamp.

- Fetch OHLCV Data for BTC/USD:  
  ```
  https://accessibletrader.com:5000/market/fetch_ohlcv?market=crypto&exchange=bitstamp&symbol=BTC/USD&timeframe=1h
  ```
  You’ll get OHLCV candlesticks suitable for plotting with Highcharts.

## Authentication & Protected Routes
- /auth/login: POST with JSON `{"username": "youruser", "password": "yourpass"}`  
  Returns a JWT token on success.
  
- /auth/refresh: POST with JSON `{"token": "old_jwt_token"}`  
  Returns a refreshed JWT token if the old one is still valid.

Note: Include `Authorization: Bearer <token>` header when calling protected endpoints once you have a token.

## WebSocket Endpoint
- /ws/subscribe?market=crypto&symbols=BTC/USD  
  Connect via a WebSocket client. You’ll receive periodic simulated price updates for the given symbols.  
  Disconnecting or closing the connection stops the subscription.

## Accessibility Considerations
- The API returns structured JSON data that can be easily formatted into charts rendered by Highcharts with accessibility modules enabled.
- Ensure your front-end uses Highcharts’ [Accessibility Module](https://www.highcharts.com/docs/accessibility/accessibility-module) to present chart data in a screen-reader-friendly manner.
- Responses include clearly named keys and straightforward structures, enabling assistive technologies to provide meaningful feedback to visually impaired users.

## Contributing
1. Fork and clone the repository.
2. Create a branch for your feature or bugfix.
3. Make changes and ensure all tests pass.
4. Submit a Pull Request with a clear description of changes.

## License
This project is licensed under the MIT License. See [LICENSE.md](LICENSE.md) for details.

---

In summary, this backend provides a robust, scalable, and inclusive foundation for a financial trading application. With async operations, reliable data storage, efficient caching, and a focus on accessibility, it’s designed to serve as a backend backbone for a trading platform accessible to all users.
```