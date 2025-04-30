-- migrate_ohlcv.sql

-- 1) Drop continuous-aggregate views (if they exist)
DROP MATERIALIZED VIEW IF EXISTS ohlcv_5min CASCADE;
DROP MATERIALIZED VIEW IF EXISTS ohlcv_1h   CASCADE;

-- 2) Drop the hypertable (this also drops all chunk tables)
SELECT drop_hypertable('ohlcv_data', cascade => TRUE);

-- 3) Recreate ohlcv_data table with timestamptz
DROP TABLE IF EXISTS ohlcv_data;

CREATE TABLE ohlcv_data (
  market          TEXT      NOT NULL,
  exchange        TEXT      NOT NULL,
  symbol          TEXT      NOT NULL,
  timeframe       TEXT      NOT NULL,
  timestamp       TIMESTAMPTZ NOT NULL,
  base_currency   TEXT,
  quote_currency  TEXT,
  open            DOUBLE PRECISION NOT NULL,
  high            DOUBLE PRECISION NOT NULL,
  low             DOUBLE PRECISION NOT NULL,
  close           DOUBLE PRECISION NOT NULL,
  volume          DOUBLE PRECISION NOT NULL,
  source          TEXT DEFAULT 'api',
  PRIMARY KEY (market, exchange, symbol, timeframe, timestamp)
);

-- 4) Turn it into a hypertable again
SELECT create_hypertable(
  'ohlcv_data',
  'timestamp',
  if_not_exists       => TRUE,
  chunk_time_interval => INTERVAL '1 day'
);

-- 5) Re-create the composite index
CREATE INDEX idx_ohlcv_data_composite
  ON ohlcv_data(market, exchange, symbol, timeframe, timestamp DESC);

-- 6) (Re)create your continuous aggregates

--  6a) 5-minute
CREATE MATERIALIZED VIEW ohlcv_5min
WITH (timescaledb.continuous) AS
SELECT
  market,
  exchange,
  symbol,
  '5m'::TEXT   AS timeframe,
  time_bucket('5 minutes', timestamp) AS bucketed_time,
  first(open, timestamp)  AS open,
  max(high)              AS high,
  min(low)               AS low,
  last(close, timestamp) AS close,
  sum(volume)            AS volume
FROM ohlcv_data
WHERE timeframe = '1m'
GROUP BY market, exchange, symbol, bucketed_time;

--  6b) 1-hour
CREATE MATERIALIZED VIEW ohlcv_1h
WITH (timescaledb.continuous) AS
SELECT
  market,
  exchange,
  symbol,
  '1h'::TEXT   AS timeframe,
  time_bucket('1 hour', timestamp) AS bucketed_time,
  first(open, timestamp)  AS open,
  max(high)              AS high,
  min(low)               AS low,
  last(close, timestamp) AS close,
  sum(volume)            AS volume
FROM ohlcv_data
WHERE timeframe = '1m'
GROUP BY market, exchange, symbol, bucketed_time;

-- 7) Re-add your refresh policies

SELECT add_continuous_aggregate_policy(
  'ohlcv_5min',
  start_offset     => INTERVAL '1 day',
  end_offset       => INTERVAL '0',
  schedule_interval=> INTERVAL '5 minutes'
);

SELECT add_continuous_aggregate_policy(
  'ohlcv_1h',
  start_offset     => INTERVAL '1 day',
  end_offset       => INTERVAL '0',
  schedule_interval=> INTERVAL '1 hour'
);