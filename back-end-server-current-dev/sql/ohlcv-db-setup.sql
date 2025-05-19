-- ohlcv-db-setup.sql

-- ====================================================
-- 1) Drop & recreate the entire database
--    (must be run while connected to another DB, e.g. "postgres")
-- ====================================================
DROP DATABASE IF EXISTS accessibletrader_db;
CREATE DATABASE accessibletrader_db
  WITH OWNER = postgres    -- ? change this to your actual DB owner
  ENCODING = 'UTF8'
  LC_COLLATE = 'en_US.UTF-8'
  LC_CTYPE   = 'en_US.UTF-8'
  TEMPLATE    = template0;

\c accessibletrader_db

-- ====================================================
-- 2) Enable TimescaleDB
-- ====================================================
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- ====================================================
-- 3) Raw OHLCV table & hypertable
-- ====================================================
DROP TABLE IF EXISTS public.ohlcv_data;
CREATE TABLE public.ohlcv_data (
  market        TEXT            NOT NULL,
  provider      TEXT            NOT NULL,
  symbol        TEXT            NOT NULL,
  timeframe     TEXT            NOT NULL,
  timestamp     TIMESTAMPTZ     NOT NULL,
  base_currency TEXT,
  quote_currency TEXT,
  open          DOUBLE PRECISION NOT NULL,
  high          DOUBLE PRECISION NOT NULL,
  low           DOUBLE PRECISION NOT NULL,
  close         DOUBLE PRECISION NOT NULL,
  volume        DOUBLE PRECISION NOT NULL,
  source        TEXT DEFAULT 'api',
  PRIMARY KEY (market, provider, symbol, timeframe, timestamp)
);

SELECT create_hypertable(
  'public.ohlcv_data',
  'timestamp',
  if_not_exists       => TRUE,
  chunk_time_interval => INTERVAL '1 day'
);

CREATE INDEX IF NOT EXISTS idx_raw_ohlcv_composite
  ON public.ohlcv_data(market, provider, symbol, timeframe, timestamp DESC);

-- ====================================================
-- 4) Continuous-aggregate views (5 min ? 1 year)
-- ====================================================
-- 5-minute
DROP MATERIALIZED VIEW IF EXISTS public.ohlcv_5min CASCADE;
CREATE MATERIALIZED VIEW public.ohlcv_5min
  WITH (timescaledb.continuous) AS
SELECT
  market, provider, symbol,
  '5m'::TEXT    AS timeframe,
  time_bucket('5 minutes', timestamp) AS bucketed_time,
  first(open, timestamp) AS open,
  max(high)             AS high,
  min(low)              AS low,
  last(close, timestamp) AS close,
  sum(volume)           AS volume
FROM public.ohlcv_data
WHERE timeframe = '1m'
GROUP BY market, provider, symbol, bucketed_time;

-- 15-minute
DROP MATERIALIZED VIEW IF EXISTS public.ohlcv_15min CASCADE;
CREATE MATERIALIZED VIEW public.ohlcv_15min
  WITH (timescaledb.continuous) AS
SELECT
  market, provider, symbol,
  '15m'::TEXT    AS timeframe,
  time_bucket('15 minutes', timestamp) AS bucketed_time,
  first(open, timestamp), max(high), min(low), last(close, timestamp), sum(volume)
FROM public.ohlcv_data
WHERE timeframe = '1m'
GROUP BY market, provider, symbol, bucketed_time;

-- 30-minute
DROP MATERIALIZED VIEW IF EXISTS public.ohlcv_30min CASCADE;
CREATE MATERIALIZED VIEW public.ohlcv_30min
  WITH (timescaledb.continuous) AS
SELECT
  market, provider, symbol,
  '30m'::TEXT    AS timeframe,
  time_bucket('30 minutes', timestamp) AS bucketed_time,
  first(open, timestamp), max(high), min(low), last(close, timestamp), sum(volume)
FROM public.ohlcv_data
WHERE timeframe = '1m'
GROUP BY market, provider, symbol, bucketed_time;

-- 1-hour
DROP MATERIALIZED VIEW IF EXISTS public.ohlcv_1h CASCADE;
CREATE MATERIALIZED VIEW public.ohlcv_1h
  WITH (timescaledb.continuous) AS
SELECT
  market, provider, symbol,
  '1h'::TEXT    AS timeframe,
  time_bucket('1 hour', timestamp) AS bucketed_time,
  first(open, timestamp), max(high), min(low), last(close, timestamp), sum(volume)
FROM public.ohlcv_data
WHERE timeframe = '1m'
GROUP BY market, provider, symbol, bucketed_time;

-- 4-hour
DROP MATERIALIZED VIEW IF EXISTS public.ohlcv_4h CASCADE;
CREATE MATERIALIZED VIEW public.ohlcv_4h
  WITH (timescaledb.continuous) AS
SELECT
  market, provider, symbol,
  '4h'::TEXT    AS timeframe,
  time_bucket('4 hours', timestamp) AS bucketed_time,
  first(open, timestamp), max(high), min(low), last(close, timestamp), sum(volume)
FROM public.ohlcv_data
WHERE timeframe = '1m'
GROUP BY market, provider, symbol, bucketed_time;

-- 1-day
DROP MATERIALIZED VIEW IF EXISTS public.ohlcv_1d CASCADE;
CREATE MATERIALIZED VIEW public.ohlcv_1d
  WITH (timescaledb.continuous) AS
SELECT
  market, provider, symbol,
  '1d'::TEXT    AS timeframe,
  time_bucket('1 day', timestamp) AS bucketed_time,
  first(open, timestamp), max(high), min(low), last(close, timestamp), sum(volume)
FROM public.ohlcv_data
WHERE timeframe = '1m'
GROUP BY market, provider, symbol, bucketed_time;

-- 1-week
DROP MATERIALIZED VIEW IF EXISTS public.ohlcv_1w CASCADE;
CREATE MATERIALIZED VIEW public.ohlcv_1w
  WITH (timescaledb.continuous) AS
SELECT
  market, provider, symbol,
  '1w'::TEXT    AS timeframe,
  time_bucket('7 days', timestamp) AS bucketed_time,
  first(open, timestamp), max(high), min(low), last(close, timestamp), sum(volume)
FROM public.ohlcv_data
WHERE timeframe = '1m'
GROUP BY market, provider, symbol, bucketed_time;

-- 1-month
DROP MATERIALIZED VIEW IF EXISTS public.ohlcv_1mon CASCADE;
CREATE MATERIALIZED VIEW public.ohlcv_1mon
  WITH (timescaledb.continuous) AS
SELECT
  market, provider, symbol,
  '1mon'::TEXT  AS timeframe,
  time_bucket('1 month', timestamp) AS bucketed_time,
  first(open, timestamp), max(high), min(low), last(close, timestamp), sum(volume)
FROM public.ohlcv_data
WHERE timeframe = '1m'
GROUP BY market, provider, symbol, bucketed_time;

-- 1-year
DROP MATERIALIZED VIEW IF EXISTS public.ohlcv_1y CASCADE;
CREATE MATERIALIZED VIEW public.ohlcv_1y
  WITH (timescaledb.continuous) AS
SELECT
  market, provider, symbol,
  '1y'::TEXT    AS timeframe,
  time_bucket('1 year', timestamp) AS bucketed_time,
  first(open, timestamp), max(high), min(low), last(close, timestamp), sum(volume)
FROM public.ohlcv_data
WHERE timeframe = '1m'
GROUP BY market, provider, symbol, bucketed_time;

-- ====================================================
-- 5) Refresh policies
--    (start_offset = twice bucket, end_offset = 0)
-- ====================================================
SELECT add_continuous_aggregate_policy('public.ohlcv_5min',
  start_offset => INTERVAL '10 minutes',  end_offset => INTERVAL '0', schedule_interval => INTERVAL '5 minutes');
SELECT add_continuous_aggregate_policy('public.ohlcv_15min',
  start_offset => INTERVAL '30 minutes',  end_offset => INTERVAL '0', schedule_interval => INTERVAL '15 minutes');
SELECT add_continuous_aggregate_policy('public.ohlcv_30min',
  start_offset => INTERVAL '1 hour',     end_offset => INTERVAL '0', schedule_interval => INTERVAL '30 minutes');
SELECT add_continuous_aggregate_policy('public.ohlcv_1h',
  start_offset => INTERVAL '2 hours',    end_offset => INTERVAL '0', schedule_interval => INTERVAL '1 hour');
SELECT add_continuous_aggregate_policy('public.ohlcv_4h',
  start_offset => INTERVAL '8 hours',    end_offset => INTERVAL '0', schedule_interval => INTERVAL '4 hours');
SELECT add_continuous_aggregate_policy('public.ohlcv_1d',
  start_offset => INTERVAL '2 days',     end_offset => INTERVAL '0', schedule_interval => INTERVAL '1 day');
SELECT add_continuous_aggregate_policy('public.ohlcv_1w',
  start_offset => INTERVAL '2 weeks',    end_offset => INTERVAL '0', schedule_interval => INTERVAL '1 week');
SELECT add_continuous_aggregate_policy('public.ohlcv_1mon',
  start_offset => INTERVAL '2 months',   end_offset => INTERVAL '0', schedule_interval => INTERVAL '1 month');
SELECT add_continuous_aggregate_policy('public.ohlcv_1y',
  start_offset => INTERVAL '2 years',    end_offset => INTERVAL '0', schedule_interval => INTERVAL '1 year');
