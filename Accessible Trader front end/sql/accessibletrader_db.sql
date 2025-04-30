-- Enable TimescaleDB Extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

----------------------------------------
-- Users Table for Account Management
----------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL, -- Securely hashed password
    role_name VARCHAR(20) NOT NULL CHECK (role_name IN ('user', 'admin', 'premium')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert a default admin user (password: "admin123", already hashed)
INSERT INTO users (username, email, password_hash, role_name)
VALUES (
    'admin',
    'admin@accessibletrader.com',
    '$2y$10$e6R5FkFPpWjscOjIoEHRve4uvGTx.LHFt7O92ewLtthLCKgiIHBpi', 
    'admin'
)
ON CONFLICT (username) DO NOTHING;

----------------------------------------
-- OHLCV Data Table (Primary Data Store)
----------------------------------------
-- This table stores raw OHLCV data at the finest granularity (e.g. 1m).
-- Columns: market, exchange, symbol, timeframe, timestamp, open, high, low, close, volume.
-- Optional columns like base_currency, quote_currency can be retained if needed.
-- The primary key allows upserts.
CREATE TABLE IF NOT EXISTS ohlcv_data (
    market TEXT NOT NULL,
    exchange TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    timestamp TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    base_currency TEXT,
    quote_currency TEXT,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION NOT NULL,
    source TEXT DEFAULT 'api',
    PRIMARY KEY (market, exchange, symbol, timeframe, timestamp)
);

-- Convert ohlcv_data into a TimescaleDB hypertable
-- timestamp is the time dimension. Adjust chunk_time_interval as needed.
SELECT create_hypertable('ohlcv_data', 'timestamp', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 day');

-- Index to optimize queries by market/exchange/symbol/timeframe/timestamp
CREATE INDEX IF NOT EXISTS idx_ohlcv_data_composite 
ON ohlcv_data (market, exchange, symbol, timeframe, timestamp DESC);

----------------------------------------
-- Continuous Aggregates (Materialized Views)
----------------------------------------
-- We'll create two continuous aggregates as examples: 5-minute and 1-hour aggregations.
-- These aggregates roll up raw data from ohlcv_data into coarser time buckets.

-- 5-minute continuous aggregate
CREATE MATERIALIZED VIEW ohlcv_5min
WITH (timescaledb.continuous) AS
SELECT
    market,
    exchange,
    symbol,
    '5m'::text AS timeframe,
    time_bucket('5 minutes', timestamp) AS bucketed_time,
    first(open, timestamp) AS open,
    max(high) AS high,
    min(low) AS low,
    last(close, timestamp) AS close,
    sum(volume) AS volume
FROM ohlcv_data
WHERE timeframe = '1m' -- Assuming your raw data is collected at 1m intervals
GROUP BY market, exchange, symbol, time_bucket('5 minutes', timestamp);

-- 1-hour continuous aggregate
CREATE MATERIALIZED VIEW ohlcv_1h
WITH (timescaledb.continuous) AS
SELECT
    market,
    exchange,
    symbol,
    '1h'::text AS timeframe,
    time_bucket('1 hour', timestamp) AS bucketed_time,
    first(open, timestamp) AS open,
    max(high) AS high,
    min(low) AS low,
    last(close, timestamp) AS close,
    sum(volume) AS volume
FROM ohlcv_data
WHERE timeframe = '1m'
GROUP BY market, exchange, symbol, time_bucket('1 hour', timestamp);

-- Optional: Add refresh policies if desired, to keep continuous aggregates updated
-- For 5m aggregates
SELECT add_continuous_aggregate_policy('ohlcv_5min',
  start_offset => INTERVAL '1 day',
  end_offset => INTERVAL '0',
  schedule_interval => INTERVAL '5 minutes');

-- For 1h aggregates
SELECT add_continuous_aggregate_policy('ohlcv_1h',
  start_offset => INTERVAL '1 day',
  end_offset => INTERVAL '0',
  schedule_interval => INTERVAL '1 hour');


----------------------------------------
-- Trade Logs Table for Recording User Activity
----------------------------------------
CREATE TABLE IF NOT EXISTS trade_logs (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    symbol VARCHAR(50) NOT NULL,
    exchange VARCHAR(50) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    trade_type VARCHAR(10) NOT NULL CHECK (trade_type IN ('buy', 'sell')),
    price DOUBLE PRECISION NOT NULL,
    quantity DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

----------------------------------------
-- API Keys Table for External Access
----------------------------------------
CREATE TABLE IF NOT EXISTS api_keys (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    api_key TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_used TIMESTAMPTZ DEFAULT NULL
);

----------------------------------------
-- Exchange Symbols Table for Caching Symbols
----------------------------------------
CREATE TABLE IF NOT EXISTS exchange_symbols (
    exchange VARCHAR(50) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    base_currency VARCHAR(50) NOT NULL,
    quote_currency VARCHAR(50) NOT NULL,
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (exchange, symbol)
);

CREATE INDEX IF NOT EXISTS idx_exchange_symbols ON exchange_symbols (exchange, symbol);
