Accessible Trader Back-End

A high-performance, asynchronous back-end server built with Quart for streaming and historical market data via REST and WebSocket APIs. Designed to support live charting for both stocks and cryptocurrencies, with caching, TimescaleDB continuous aggregates, plugin-based data sources, and robust connection management.

Table of Contents

Features

Architecture

Getting Started

Prerequisites

Installation

Configuration

Running the Server

API Endpoints

REST

WebSocket

Data Layer

TimescaleDB & Continuous Aggregates

Redis Caching

Plugin System

Scalability & Performance

Areas for Improvement

License

Features

Async I/O everywhere: Quart + asyncpg + aioredis for non-blocking DB & cache operations.

Historical & live data: REST endpoint for OHLCV, Highcharts-ready responses; WebSocket for live updates.

Subscription de-duplication: Single poll per (market, provider, symbol, timeframe) regardless of number of clients.

Caching layers:

Hourly bucketed Redis cache for raw 1m bars.

TimescaleDB continuous aggregates (5m, 15m, 1h, 1d, etc.).

Final OHLCV & latest-bar caches with configurable TTL.

Plugin-based data sources: Alpaca (stocks) and CCXT (crypto) plugins implement a consistent interface. More plugins are coming soon.

JWT auth & user config: Secure login, token refresh, per-user settings storage.

Graceful startup/shutdown: Lifecycle hooks register DB, Redis, plugin discovery, SubscriptionManager, and clean up on exit.

Heartbeat & timeouts: Detect silent or closed WebSocket clients; ping/pong keeps connections alive.

Architecture

+-----------+    HTTP/REST    +--------+      DB       +-------------+
|  Frontend | <--------------> | Quart  | <----------> | TimescaleDB |
| (React)   |                  | Server |              +-------------+
+-----------+        WS        |        |               Redis Cache
      ^                      / |        | <----------> +-------------+
      |  WebSocket (API)    /  +--------+               | Redis       |
      |                   /                           +-------------+
      +------------------+

Client communicates via REST for historical data and WebSocket for live updates.

Quart routes requests to blueprints (market, auth, user, websocket).

MarketService orchestrates caching, continuous aggregates, and plugin fetch logic.

SubscriptionManager deduplicates polls and broadcasts new bars to subscribed clients.

PluginLoader dynamically discovers and instantiates data plugins (Alpaca, CCXT), others.

Storage:

TimescaleDB hypertable for raw 1m OHLCV.

Continuous aggregates for coarser timeframes.

Redis for caching grouped bars and final responses.

Getting Started

Prerequisites

Python 3.10+

PostgreSQL with TimescaleDB extension

Redis

Environment variables (see Configuration)

Installation

git clone https://github.com/churst90/accessible-trader.git
cd accessible-trader
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

Configuration

Create a .env at project root or set environment variables:

# Core
SECRET_KEY=your_secret_key
DB_CONNECTION_STRING=postgresql://user:pass@localhost:5432/accessibletrader_db
REDIS_URL=redis://localhost:6379/0

# JWT
JWT_EXPIRATION_DELTA=3600

# Plugin credentials (Alpaca example)
ALPACA_API_KEY=your_alpaca_key
ALPACA_API_SECRET=your_alpaca_secret

# CORS origins
TRUSTED_ORIGINS=http://localhost:3000

Also adjust optional caching/pool sizes in config.py as needed.

Running the Server

# Initialize TimescaleDB (see ohlcv-db-setup.sql)
psql -f ohlcv-db-setup.sql

# Start Quart via Hypercorn
./start-server.sh

API Endpoints

REST

Method

Path

Description

GET

/api/market/providers?market={m}

List available providers for a market

GET

/api/market/symbols?market={m}&provider={p}

List symbols for provider

GET

/api/market/ohlcv?market={m}&provider={p}&symbol={s}&timeframe={tf}&since={ms}&before={ms}&limit={n}

Fetch historical OHLCV data (Highcharts)

POST

/api/auth/login

Username/password ? JWT token

POST

/api/auth/refresh

Refresh JWT token

POST

/api/user/save_config

Save per-user config (requires JWT)

GET

/api/user/get_user_data

Get user config (requires JWT)

WebSocket

URL: ws://{host}/api/ws/subscribe?market={m}&provider={p}&symbols=SYM1,SYM2&timeframe={tf}&since={ms}

Handshake: On connect, you receive an initial historical batch.

Live updates: New bars are pushed as individual data messages.

Heartbeat: Server pings every 15s; client should respond with pong or any message.

Data Layer

TimescaleDB & Continuous Aggregates

Raw table ohlcv_data stores 1m bars.

Continuous aggregate views for 5m,15m,30m,1h,4h,1d,1w,1mon,1y auto-refresh on schedule.

Query via Materialized Views when timeframe ? 1m, with fallback to resampling raw data.

Redis Caching

Hourly buckets: Groups of 1m bars keyed 1m_bars_hr:{market}:{provider}:{symbol}:{hourly_ts}.

Final result cache: Highcharts-formatted responses keyed by query params.

Latest bar TTL: Dynamic short-lived cache for real-time polling.

Plugin System

Plugins implement MarketPlugin interface.

AlpacaPlugin for stocks via Alpaca API.

CryptoPlugin for crypto via CCXT.

Discovered at startup; factories manage credentials and LRU instances.

Scalability & Performance

Async architecture: Avoids blocking threads.

Subscription de-duplication: One poll per unique key regardless of client count.

Connection pools: Configurable asyncpg & aioredis pools.

Horizontal scaling caveat: In-process state (subscriptions, WS registry) is not shared—requires external pub/sub for multi-instance.

Resource tuning: Pool sizes, cache TTLs, and poll intervals can be tuned in config.py.

Areas for Improvement

Horizontal scaling: Move subscription registry to Redis Pub/Sub or NATS.

Metrics & monitoring: Integrate Prometheus/Grafana to surface latency, queue depth, error rates.

Back-pressure: Limit per-client buffer sizes; graceful slowdown if clients fall behind.

Security hardening: Rate limiting, input sanitization, stricter CORS, HTTPS enforcement.

Stress testing: Load test with 100+ unique symbols to calibrate connection pools and CPU usage.

License

MIT © Your Name

