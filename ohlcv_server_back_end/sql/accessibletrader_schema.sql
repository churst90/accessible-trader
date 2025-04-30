--
-- PostgreSQL database dump
--

-- Dumped from database version 13.20 (Debian 13.20-0+deb11u1)
-- Dumped by pg_dump version 13.16 (Debian 13.16-0+deb11u1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: timescaledb; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS timescaledb WITH SCHEMA public;


--
-- Name: EXTENSION timescaledb; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION timescaledb IS 'Enables scalable inserts and complex queries for time-series data (Community Edition)';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: ohlcv_data; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.ohlcv_data (
    market text NOT NULL,
    provider text NOT NULL,
    symbol text NOT NULL,
    timeframe text NOT NULL,
    "timestamp" timestamp with time zone NOT NULL,
    base_currency text,
    quote_currency text,
    open double precision NOT NULL,
    high double precision NOT NULL,
    low double precision NOT NULL,
    close double precision NOT NULL,
    volume double precision NOT NULL,
    source text DEFAULT 'api'::text
);


ALTER TABLE public.ohlcv_data OWNER TO postgres;

--
-- Name: _direct_view_10; Type: VIEW; Schema: _timescaledb_internal; Owner: postgres
--

CREATE VIEW _timescaledb_internal._direct_view_10 AS
 SELECT ohlcv_data.market,
    ohlcv_data.provider,
    ohlcv_data.symbol,
    '1y'::text AS timeframe,
    public.time_bucket('1 year'::interval, ohlcv_data."timestamp") AS bucketed_time,
    public.first(ohlcv_data.open, ohlcv_data."timestamp") AS open,
    max(ohlcv_data.high) AS high,
    min(ohlcv_data.low) AS low,
    public.last(ohlcv_data.close, ohlcv_data."timestamp") AS close,
    sum(ohlcv_data.volume) AS volume
   FROM public.ohlcv_data
  WHERE (ohlcv_data.timeframe = '1m'::text)
  GROUP BY ohlcv_data.market, ohlcv_data.provider, ohlcv_data.symbol, (public.time_bucket('1 year'::interval, ohlcv_data."timestamp"));


ALTER TABLE _timescaledb_internal._direct_view_10 OWNER TO postgres;

--
-- Name: _direct_view_2; Type: VIEW; Schema: _timescaledb_internal; Owner: postgres
--

CREATE VIEW _timescaledb_internal._direct_view_2 AS
 SELECT ohlcv_data.market,
    ohlcv_data.provider,
    ohlcv_data.symbol,
    '5m'::text AS timeframe,
    public.time_bucket('00:05:00'::interval, ohlcv_data."timestamp") AS bucketed_time,
    public.first(ohlcv_data.open, ohlcv_data."timestamp") AS open,
    max(ohlcv_data.high) AS high,
    min(ohlcv_data.low) AS low,
    public.last(ohlcv_data.close, ohlcv_data."timestamp") AS close,
    sum(ohlcv_data.volume) AS volume
   FROM public.ohlcv_data
  WHERE (ohlcv_data.timeframe = '1m'::text)
  GROUP BY ohlcv_data.market, ohlcv_data.provider, ohlcv_data.symbol, (public.time_bucket('00:05:00'::interval, ohlcv_data."timestamp"));


ALTER TABLE _timescaledb_internal._direct_view_2 OWNER TO postgres;

--
-- Name: _direct_view_3; Type: VIEW; Schema: _timescaledb_internal; Owner: postgres
--

CREATE VIEW _timescaledb_internal._direct_view_3 AS
 SELECT ohlcv_data.market,
    ohlcv_data.provider,
    ohlcv_data.symbol,
    '15m'::text AS timeframe,
    public.time_bucket('00:15:00'::interval, ohlcv_data."timestamp") AS bucketed_time,
    public.first(ohlcv_data.open, ohlcv_data."timestamp") AS open,
    max(ohlcv_data.high) AS high,
    min(ohlcv_data.low) AS low,
    public.last(ohlcv_data.close, ohlcv_data."timestamp") AS close,
    sum(ohlcv_data.volume) AS volume
   FROM public.ohlcv_data
  WHERE (ohlcv_data.timeframe = '1m'::text)
  GROUP BY ohlcv_data.market, ohlcv_data.provider, ohlcv_data.symbol, (public.time_bucket('00:15:00'::interval, ohlcv_data."timestamp"));


ALTER TABLE _timescaledb_internal._direct_view_3 OWNER TO postgres;

--
-- Name: _direct_view_4; Type: VIEW; Schema: _timescaledb_internal; Owner: postgres
--

CREATE VIEW _timescaledb_internal._direct_view_4 AS
 SELECT ohlcv_data.market,
    ohlcv_data.provider,
    ohlcv_data.symbol,
    '30m'::text AS timeframe,
    public.time_bucket('00:30:00'::interval, ohlcv_data."timestamp") AS bucketed_time,
    public.first(ohlcv_data.open, ohlcv_data."timestamp") AS open,
    max(ohlcv_data.high) AS high,
    min(ohlcv_data.low) AS low,
    public.last(ohlcv_data.close, ohlcv_data."timestamp") AS close,
    sum(ohlcv_data.volume) AS volume
   FROM public.ohlcv_data
  WHERE (ohlcv_data.timeframe = '1m'::text)
  GROUP BY ohlcv_data.market, ohlcv_data.provider, ohlcv_data.symbol, (public.time_bucket('00:30:00'::interval, ohlcv_data."timestamp"));


ALTER TABLE _timescaledb_internal._direct_view_4 OWNER TO postgres;

--
-- Name: _direct_view_5; Type: VIEW; Schema: _timescaledb_internal; Owner: postgres
--

CREATE VIEW _timescaledb_internal._direct_view_5 AS
 SELECT ohlcv_data.market,
    ohlcv_data.provider,
    ohlcv_data.symbol,
    '1h'::text AS timeframe,
    public.time_bucket('01:00:00'::interval, ohlcv_data."timestamp") AS bucketed_time,
    public.first(ohlcv_data.open, ohlcv_data."timestamp") AS open,
    max(ohlcv_data.high) AS high,
    min(ohlcv_data.low) AS low,
    public.last(ohlcv_data.close, ohlcv_data."timestamp") AS close,
    sum(ohlcv_data.volume) AS volume
   FROM public.ohlcv_data
  WHERE (ohlcv_data.timeframe = '1m'::text)
  GROUP BY ohlcv_data.market, ohlcv_data.provider, ohlcv_data.symbol, (public.time_bucket('01:00:00'::interval, ohlcv_data."timestamp"));


ALTER TABLE _timescaledb_internal._direct_view_5 OWNER TO postgres;

--
-- Name: _direct_view_6; Type: VIEW; Schema: _timescaledb_internal; Owner: postgres
--

CREATE VIEW _timescaledb_internal._direct_view_6 AS
 SELECT ohlcv_data.market,
    ohlcv_data.provider,
    ohlcv_data.symbol,
    '4h'::text AS timeframe,
    public.time_bucket('04:00:00'::interval, ohlcv_data."timestamp") AS bucketed_time,
    public.first(ohlcv_data.open, ohlcv_data."timestamp") AS open,
    max(ohlcv_data.high) AS high,
    min(ohlcv_data.low) AS low,
    public.last(ohlcv_data.close, ohlcv_data."timestamp") AS close,
    sum(ohlcv_data.volume) AS volume
   FROM public.ohlcv_data
  WHERE (ohlcv_data.timeframe = '1m'::text)
  GROUP BY ohlcv_data.market, ohlcv_data.provider, ohlcv_data.symbol, (public.time_bucket('04:00:00'::interval, ohlcv_data."timestamp"));


ALTER TABLE _timescaledb_internal._direct_view_6 OWNER TO postgres;

--
-- Name: _direct_view_7; Type: VIEW; Schema: _timescaledb_internal; Owner: postgres
--

CREATE VIEW _timescaledb_internal._direct_view_7 AS
 SELECT ohlcv_data.market,
    ohlcv_data.provider,
    ohlcv_data.symbol,
    '1d'::text AS timeframe,
    public.time_bucket('1 day'::interval, ohlcv_data."timestamp") AS bucketed_time,
    public.first(ohlcv_data.open, ohlcv_data."timestamp") AS open,
    max(ohlcv_data.high) AS high,
    min(ohlcv_data.low) AS low,
    public.last(ohlcv_data.close, ohlcv_data."timestamp") AS close,
    sum(ohlcv_data.volume) AS volume
   FROM public.ohlcv_data
  WHERE (ohlcv_data.timeframe = '1m'::text)
  GROUP BY ohlcv_data.market, ohlcv_data.provider, ohlcv_data.symbol, (public.time_bucket('1 day'::interval, ohlcv_data."timestamp"));


ALTER TABLE _timescaledb_internal._direct_view_7 OWNER TO postgres;

--
-- Name: _direct_view_8; Type: VIEW; Schema: _timescaledb_internal; Owner: postgres
--

CREATE VIEW _timescaledb_internal._direct_view_8 AS
 SELECT ohlcv_data.market,
    ohlcv_data.provider,
    ohlcv_data.symbol,
    '1w'::text AS timeframe,
    public.time_bucket('7 days'::interval, ohlcv_data."timestamp") AS bucketed_time,
    public.first(ohlcv_data.open, ohlcv_data."timestamp") AS open,
    max(ohlcv_data.high) AS high,
    min(ohlcv_data.low) AS low,
    public.last(ohlcv_data.close, ohlcv_data."timestamp") AS close,
    sum(ohlcv_data.volume) AS volume
   FROM public.ohlcv_data
  WHERE (ohlcv_data.timeframe = '1m'::text)
  GROUP BY ohlcv_data.market, ohlcv_data.provider, ohlcv_data.symbol, (public.time_bucket('7 days'::interval, ohlcv_data."timestamp"));


ALTER TABLE _timescaledb_internal._direct_view_8 OWNER TO postgres;

--
-- Name: _direct_view_9; Type: VIEW; Schema: _timescaledb_internal; Owner: postgres
--

CREATE VIEW _timescaledb_internal._direct_view_9 AS
 SELECT ohlcv_data.market,
    ohlcv_data.provider,
    ohlcv_data.symbol,
    '1mon'::text AS timeframe,
    public.time_bucket('1 mon'::interval, ohlcv_data."timestamp") AS bucketed_time,
    public.first(ohlcv_data.open, ohlcv_data."timestamp") AS open,
    max(ohlcv_data.high) AS high,
    min(ohlcv_data.low) AS low,
    public.last(ohlcv_data.close, ohlcv_data."timestamp") AS close,
    sum(ohlcv_data.volume) AS volume
   FROM public.ohlcv_data
  WHERE (ohlcv_data.timeframe = '1m'::text)
  GROUP BY ohlcv_data.market, ohlcv_data.provider, ohlcv_data.symbol, (public.time_bucket('1 mon'::interval, ohlcv_data."timestamp"));


ALTER TABLE _timescaledb_internal._direct_view_9 OWNER TO postgres;

--
-- Name: _hyper_1_1_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TABLE _timescaledb_internal._hyper_1_1_chunk (
    CONSTRAINT constraint_1 CHECK ((("timestamp" >= '2025-04-26 00:00:00+00'::timestamp with time zone) AND ("timestamp" < '2025-04-27 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.ohlcv_data);


ALTER TABLE _timescaledb_internal._hyper_1_1_chunk OWNER TO postgres;

--
-- Name: _hyper_1_6_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TABLE _timescaledb_internal._hyper_1_6_chunk (
    CONSTRAINT constraint_6 CHECK ((("timestamp" >= '2025-04-27 00:00:00+00'::timestamp with time zone) AND ("timestamp" < '2025-04-28 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.ohlcv_data);


ALTER TABLE _timescaledb_internal._hyper_1_6_chunk OWNER TO postgres;

--
-- Name: _materialized_hypertable_2; Type: TABLE; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TABLE _timescaledb_internal._materialized_hypertable_2 (
    market text,
    provider text,
    symbol text,
    timeframe text,
    bucketed_time timestamp with time zone NOT NULL,
    open double precision,
    high double precision,
    low double precision,
    close double precision,
    volume double precision
);


ALTER TABLE _timescaledb_internal._materialized_hypertable_2 OWNER TO postgres;

--
-- Name: _hyper_2_4_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TABLE _timescaledb_internal._hyper_2_4_chunk (
    CONSTRAINT constraint_4 CHECK (((bucketed_time >= '2025-04-22 00:00:00+00'::timestamp with time zone) AND (bucketed_time < '2025-05-02 00:00:00+00'::timestamp with time zone)))
)
INHERITS (_timescaledb_internal._materialized_hypertable_2);


ALTER TABLE _timescaledb_internal._hyper_2_4_chunk OWNER TO postgres;

--
-- Name: _materialized_hypertable_3; Type: TABLE; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TABLE _timescaledb_internal._materialized_hypertable_3 (
    market text,
    provider text,
    symbol text,
    timeframe text,
    bucketed_time timestamp with time zone NOT NULL,
    open double precision,
    high double precision,
    low double precision,
    close double precision,
    volume double precision
);


ALTER TABLE _timescaledb_internal._materialized_hypertable_3 OWNER TO postgres;

--
-- Name: _hyper_3_3_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TABLE _timescaledb_internal._hyper_3_3_chunk (
    CONSTRAINT constraint_3 CHECK (((bucketed_time >= '2025-04-22 00:00:00+00'::timestamp with time zone) AND (bucketed_time < '2025-05-02 00:00:00+00'::timestamp with time zone)))
)
INHERITS (_timescaledb_internal._materialized_hypertable_3);


ALTER TABLE _timescaledb_internal._hyper_3_3_chunk OWNER TO postgres;

--
-- Name: _materialized_hypertable_4; Type: TABLE; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TABLE _timescaledb_internal._materialized_hypertable_4 (
    market text,
    provider text,
    symbol text,
    timeframe text,
    bucketed_time timestamp with time zone NOT NULL,
    open double precision,
    high double precision,
    low double precision,
    close double precision,
    volume double precision
);


ALTER TABLE _timescaledb_internal._materialized_hypertable_4 OWNER TO postgres;

--
-- Name: _hyper_4_2_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TABLE _timescaledb_internal._hyper_4_2_chunk (
    CONSTRAINT constraint_2 CHECK (((bucketed_time >= '2025-04-22 00:00:00+00'::timestamp with time zone) AND (bucketed_time < '2025-05-02 00:00:00+00'::timestamp with time zone)))
)
INHERITS (_timescaledb_internal._materialized_hypertable_4);


ALTER TABLE _timescaledb_internal._hyper_4_2_chunk OWNER TO postgres;

--
-- Name: _materialized_hypertable_5; Type: TABLE; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TABLE _timescaledb_internal._materialized_hypertable_5 (
    market text,
    provider text,
    symbol text,
    timeframe text,
    bucketed_time timestamp with time zone NOT NULL,
    open double precision,
    high double precision,
    low double precision,
    close double precision,
    volume double precision
);


ALTER TABLE _timescaledb_internal._materialized_hypertable_5 OWNER TO postgres;

--
-- Name: _hyper_5_5_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TABLE _timescaledb_internal._hyper_5_5_chunk (
    CONSTRAINT constraint_5 CHECK (((bucketed_time >= '2025-04-22 00:00:00+00'::timestamp with time zone) AND (bucketed_time < '2025-05-02 00:00:00+00'::timestamp with time zone)))
)
INHERITS (_timescaledb_internal._materialized_hypertable_5);


ALTER TABLE _timescaledb_internal._hyper_5_5_chunk OWNER TO postgres;

--
-- Name: _materialized_hypertable_6; Type: TABLE; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TABLE _timescaledb_internal._materialized_hypertable_6 (
    market text,
    provider text,
    symbol text,
    timeframe text,
    bucketed_time timestamp with time zone NOT NULL,
    open double precision,
    high double precision,
    low double precision,
    close double precision,
    volume double precision
);


ALTER TABLE _timescaledb_internal._materialized_hypertable_6 OWNER TO postgres;

--
-- Name: _hyper_6_7_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TABLE _timescaledb_internal._hyper_6_7_chunk (
    CONSTRAINT constraint_7 CHECK (((bucketed_time >= '2025-04-22 00:00:00+00'::timestamp with time zone) AND (bucketed_time < '2025-05-02 00:00:00+00'::timestamp with time zone)))
)
INHERITS (_timescaledb_internal._materialized_hypertable_6);


ALTER TABLE _timescaledb_internal._hyper_6_7_chunk OWNER TO postgres;

--
-- Name: _materialized_hypertable_10; Type: TABLE; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TABLE _timescaledb_internal._materialized_hypertable_10 (
    market text,
    provider text,
    symbol text,
    timeframe text,
    bucketed_time timestamp with time zone NOT NULL,
    open double precision,
    high double precision,
    low double precision,
    close double precision,
    volume double precision
);


ALTER TABLE _timescaledb_internal._materialized_hypertable_10 OWNER TO postgres;

--
-- Name: _materialized_hypertable_7; Type: TABLE; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TABLE _timescaledb_internal._materialized_hypertable_7 (
    market text,
    provider text,
    symbol text,
    timeframe text,
    bucketed_time timestamp with time zone NOT NULL,
    open double precision,
    high double precision,
    low double precision,
    close double precision,
    volume double precision
);


ALTER TABLE _timescaledb_internal._materialized_hypertable_7 OWNER TO postgres;

--
-- Name: _materialized_hypertable_8; Type: TABLE; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TABLE _timescaledb_internal._materialized_hypertable_8 (
    market text,
    provider text,
    symbol text,
    timeframe text,
    bucketed_time timestamp with time zone NOT NULL,
    open double precision,
    high double precision,
    low double precision,
    close double precision,
    volume double precision
);


ALTER TABLE _timescaledb_internal._materialized_hypertable_8 OWNER TO postgres;

--
-- Name: _materialized_hypertable_9; Type: TABLE; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TABLE _timescaledb_internal._materialized_hypertable_9 (
    market text,
    provider text,
    symbol text,
    timeframe text,
    bucketed_time timestamp with time zone NOT NULL,
    open double precision,
    high double precision,
    low double precision,
    close double precision,
    volume double precision
);


ALTER TABLE _timescaledb_internal._materialized_hypertable_9 OWNER TO postgres;

--
-- Name: _partial_view_10; Type: VIEW; Schema: _timescaledb_internal; Owner: postgres
--

CREATE VIEW _timescaledb_internal._partial_view_10 AS
 SELECT ohlcv_data.market,
    ohlcv_data.provider,
    ohlcv_data.symbol,
    '1y'::text AS timeframe,
    public.time_bucket('1 year'::interval, ohlcv_data."timestamp") AS bucketed_time,
    public.first(ohlcv_data.open, ohlcv_data."timestamp") AS open,
    max(ohlcv_data.high) AS high,
    min(ohlcv_data.low) AS low,
    public.last(ohlcv_data.close, ohlcv_data."timestamp") AS close,
    sum(ohlcv_data.volume) AS volume
   FROM public.ohlcv_data
  WHERE (ohlcv_data.timeframe = '1m'::text)
  GROUP BY ohlcv_data.market, ohlcv_data.provider, ohlcv_data.symbol, (public.time_bucket('1 year'::interval, ohlcv_data."timestamp"));


ALTER TABLE _timescaledb_internal._partial_view_10 OWNER TO postgres;

--
-- Name: _partial_view_2; Type: VIEW; Schema: _timescaledb_internal; Owner: postgres
--

CREATE VIEW _timescaledb_internal._partial_view_2 AS
 SELECT ohlcv_data.market,
    ohlcv_data.provider,
    ohlcv_data.symbol,
    '5m'::text AS timeframe,
    public.time_bucket('00:05:00'::interval, ohlcv_data."timestamp") AS bucketed_time,
    public.first(ohlcv_data.open, ohlcv_data."timestamp") AS open,
    max(ohlcv_data.high) AS high,
    min(ohlcv_data.low) AS low,
    public.last(ohlcv_data.close, ohlcv_data."timestamp") AS close,
    sum(ohlcv_data.volume) AS volume
   FROM public.ohlcv_data
  WHERE (ohlcv_data.timeframe = '1m'::text)
  GROUP BY ohlcv_data.market, ohlcv_data.provider, ohlcv_data.symbol, (public.time_bucket('00:05:00'::interval, ohlcv_data."timestamp"));


ALTER TABLE _timescaledb_internal._partial_view_2 OWNER TO postgres;

--
-- Name: _partial_view_3; Type: VIEW; Schema: _timescaledb_internal; Owner: postgres
--

CREATE VIEW _timescaledb_internal._partial_view_3 AS
 SELECT ohlcv_data.market,
    ohlcv_data.provider,
    ohlcv_data.symbol,
    '15m'::text AS timeframe,
    public.time_bucket('00:15:00'::interval, ohlcv_data."timestamp") AS bucketed_time,
    public.first(ohlcv_data.open, ohlcv_data."timestamp") AS open,
    max(ohlcv_data.high) AS high,
    min(ohlcv_data.low) AS low,
    public.last(ohlcv_data.close, ohlcv_data."timestamp") AS close,
    sum(ohlcv_data.volume) AS volume
   FROM public.ohlcv_data
  WHERE (ohlcv_data.timeframe = '1m'::text)
  GROUP BY ohlcv_data.market, ohlcv_data.provider, ohlcv_data.symbol, (public.time_bucket('00:15:00'::interval, ohlcv_data."timestamp"));


ALTER TABLE _timescaledb_internal._partial_view_3 OWNER TO postgres;

--
-- Name: _partial_view_4; Type: VIEW; Schema: _timescaledb_internal; Owner: postgres
--

CREATE VIEW _timescaledb_internal._partial_view_4 AS
 SELECT ohlcv_data.market,
    ohlcv_data.provider,
    ohlcv_data.symbol,
    '30m'::text AS timeframe,
    public.time_bucket('00:30:00'::interval, ohlcv_data."timestamp") AS bucketed_time,
    public.first(ohlcv_data.open, ohlcv_data."timestamp") AS open,
    max(ohlcv_data.high) AS high,
    min(ohlcv_data.low) AS low,
    public.last(ohlcv_data.close, ohlcv_data."timestamp") AS close,
    sum(ohlcv_data.volume) AS volume
   FROM public.ohlcv_data
  WHERE (ohlcv_data.timeframe = '1m'::text)
  GROUP BY ohlcv_data.market, ohlcv_data.provider, ohlcv_data.symbol, (public.time_bucket('00:30:00'::interval, ohlcv_data."timestamp"));


ALTER TABLE _timescaledb_internal._partial_view_4 OWNER TO postgres;

--
-- Name: _partial_view_5; Type: VIEW; Schema: _timescaledb_internal; Owner: postgres
--

CREATE VIEW _timescaledb_internal._partial_view_5 AS
 SELECT ohlcv_data.market,
    ohlcv_data.provider,
    ohlcv_data.symbol,
    '1h'::text AS timeframe,
    public.time_bucket('01:00:00'::interval, ohlcv_data."timestamp") AS bucketed_time,
    public.first(ohlcv_data.open, ohlcv_data."timestamp") AS open,
    max(ohlcv_data.high) AS high,
    min(ohlcv_data.low) AS low,
    public.last(ohlcv_data.close, ohlcv_data."timestamp") AS close,
    sum(ohlcv_data.volume) AS volume
   FROM public.ohlcv_data
  WHERE (ohlcv_data.timeframe = '1m'::text)
  GROUP BY ohlcv_data.market, ohlcv_data.provider, ohlcv_data.symbol, (public.time_bucket('01:00:00'::interval, ohlcv_data."timestamp"));


ALTER TABLE _timescaledb_internal._partial_view_5 OWNER TO postgres;

--
-- Name: _partial_view_6; Type: VIEW; Schema: _timescaledb_internal; Owner: postgres
--

CREATE VIEW _timescaledb_internal._partial_view_6 AS
 SELECT ohlcv_data.market,
    ohlcv_data.provider,
    ohlcv_data.symbol,
    '4h'::text AS timeframe,
    public.time_bucket('04:00:00'::interval, ohlcv_data."timestamp") AS bucketed_time,
    public.first(ohlcv_data.open, ohlcv_data."timestamp") AS open,
    max(ohlcv_data.high) AS high,
    min(ohlcv_data.low) AS low,
    public.last(ohlcv_data.close, ohlcv_data."timestamp") AS close,
    sum(ohlcv_data.volume) AS volume
   FROM public.ohlcv_data
  WHERE (ohlcv_data.timeframe = '1m'::text)
  GROUP BY ohlcv_data.market, ohlcv_data.provider, ohlcv_data.symbol, (public.time_bucket('04:00:00'::interval, ohlcv_data."timestamp"));


ALTER TABLE _timescaledb_internal._partial_view_6 OWNER TO postgres;

--
-- Name: _partial_view_7; Type: VIEW; Schema: _timescaledb_internal; Owner: postgres
--

CREATE VIEW _timescaledb_internal._partial_view_7 AS
 SELECT ohlcv_data.market,
    ohlcv_data.provider,
    ohlcv_data.symbol,
    '1d'::text AS timeframe,
    public.time_bucket('1 day'::interval, ohlcv_data."timestamp") AS bucketed_time,
    public.first(ohlcv_data.open, ohlcv_data."timestamp") AS open,
    max(ohlcv_data.high) AS high,
    min(ohlcv_data.low) AS low,
    public.last(ohlcv_data.close, ohlcv_data."timestamp") AS close,
    sum(ohlcv_data.volume) AS volume
   FROM public.ohlcv_data
  WHERE (ohlcv_data.timeframe = '1m'::text)
  GROUP BY ohlcv_data.market, ohlcv_data.provider, ohlcv_data.symbol, (public.time_bucket('1 day'::interval, ohlcv_data."timestamp"));


ALTER TABLE _timescaledb_internal._partial_view_7 OWNER TO postgres;

--
-- Name: _partial_view_8; Type: VIEW; Schema: _timescaledb_internal; Owner: postgres
--

CREATE VIEW _timescaledb_internal._partial_view_8 AS
 SELECT ohlcv_data.market,
    ohlcv_data.provider,
    ohlcv_data.symbol,
    '1w'::text AS timeframe,
    public.time_bucket('7 days'::interval, ohlcv_data."timestamp") AS bucketed_time,
    public.first(ohlcv_data.open, ohlcv_data."timestamp") AS open,
    max(ohlcv_data.high) AS high,
    min(ohlcv_data.low) AS low,
    public.last(ohlcv_data.close, ohlcv_data."timestamp") AS close,
    sum(ohlcv_data.volume) AS volume
   FROM public.ohlcv_data
  WHERE (ohlcv_data.timeframe = '1m'::text)
  GROUP BY ohlcv_data.market, ohlcv_data.provider, ohlcv_data.symbol, (public.time_bucket('7 days'::interval, ohlcv_data."timestamp"));


ALTER TABLE _timescaledb_internal._partial_view_8 OWNER TO postgres;

--
-- Name: _partial_view_9; Type: VIEW; Schema: _timescaledb_internal; Owner: postgres
--

CREATE VIEW _timescaledb_internal._partial_view_9 AS
 SELECT ohlcv_data.market,
    ohlcv_data.provider,
    ohlcv_data.symbol,
    '1mon'::text AS timeframe,
    public.time_bucket('1 mon'::interval, ohlcv_data."timestamp") AS bucketed_time,
    public.first(ohlcv_data.open, ohlcv_data."timestamp") AS open,
    max(ohlcv_data.high) AS high,
    min(ohlcv_data.low) AS low,
    public.last(ohlcv_data.close, ohlcv_data."timestamp") AS close,
    sum(ohlcv_data.volume) AS volume
   FROM public.ohlcv_data
  WHERE (ohlcv_data.timeframe = '1m'::text)
  GROUP BY ohlcv_data.market, ohlcv_data.provider, ohlcv_data.symbol, (public.time_bucket('1 mon'::interval, ohlcv_data."timestamp"));


ALTER TABLE _timescaledb_internal._partial_view_9 OWNER TO postgres;

--
-- Name: ohlcv_15min; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.ohlcv_15min AS
 SELECT _materialized_hypertable_3.market,
    _materialized_hypertable_3.provider,
    _materialized_hypertable_3.symbol,
    _materialized_hypertable_3.timeframe,
    _materialized_hypertable_3.bucketed_time,
    _materialized_hypertable_3.open,
    _materialized_hypertable_3.high,
    _materialized_hypertable_3.low,
    _materialized_hypertable_3.close,
    _materialized_hypertable_3.volume
   FROM _timescaledb_internal._materialized_hypertable_3;


ALTER TABLE public.ohlcv_15min OWNER TO postgres;

--
-- Name: ohlcv_1d; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.ohlcv_1d AS
 SELECT _materialized_hypertable_7.market,
    _materialized_hypertable_7.provider,
    _materialized_hypertable_7.symbol,
    _materialized_hypertable_7.timeframe,
    _materialized_hypertable_7.bucketed_time,
    _materialized_hypertable_7.open,
    _materialized_hypertable_7.high,
    _materialized_hypertable_7.low,
    _materialized_hypertable_7.close,
    _materialized_hypertable_7.volume
   FROM _timescaledb_internal._materialized_hypertable_7;


ALTER TABLE public.ohlcv_1d OWNER TO postgres;

--
-- Name: ohlcv_1h; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.ohlcv_1h AS
 SELECT _materialized_hypertable_5.market,
    _materialized_hypertable_5.provider,
    _materialized_hypertable_5.symbol,
    _materialized_hypertable_5.timeframe,
    _materialized_hypertable_5.bucketed_time,
    _materialized_hypertable_5.open,
    _materialized_hypertable_5.high,
    _materialized_hypertable_5.low,
    _materialized_hypertable_5.close,
    _materialized_hypertable_5.volume
   FROM _timescaledb_internal._materialized_hypertable_5;


ALTER TABLE public.ohlcv_1h OWNER TO postgres;

--
-- Name: ohlcv_1mon; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.ohlcv_1mon AS
 SELECT _materialized_hypertable_9.market,
    _materialized_hypertable_9.provider,
    _materialized_hypertable_9.symbol,
    _materialized_hypertable_9.timeframe,
    _materialized_hypertable_9.bucketed_time,
    _materialized_hypertable_9.open,
    _materialized_hypertable_9.high,
    _materialized_hypertable_9.low,
    _materialized_hypertable_9.close,
    _materialized_hypertable_9.volume
   FROM _timescaledb_internal._materialized_hypertable_9;


ALTER TABLE public.ohlcv_1mon OWNER TO postgres;

--
-- Name: ohlcv_1w; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.ohlcv_1w AS
 SELECT _materialized_hypertable_8.market,
    _materialized_hypertable_8.provider,
    _materialized_hypertable_8.symbol,
    _materialized_hypertable_8.timeframe,
    _materialized_hypertable_8.bucketed_time,
    _materialized_hypertable_8.open,
    _materialized_hypertable_8.high,
    _materialized_hypertable_8.low,
    _materialized_hypertable_8.close,
    _materialized_hypertable_8.volume
   FROM _timescaledb_internal._materialized_hypertable_8;


ALTER TABLE public.ohlcv_1w OWNER TO postgres;

--
-- Name: ohlcv_1y; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.ohlcv_1y AS
 SELECT _materialized_hypertable_10.market,
    _materialized_hypertable_10.provider,
    _materialized_hypertable_10.symbol,
    _materialized_hypertable_10.timeframe,
    _materialized_hypertable_10.bucketed_time,
    _materialized_hypertable_10.open,
    _materialized_hypertable_10.high,
    _materialized_hypertable_10.low,
    _materialized_hypertable_10.close,
    _materialized_hypertable_10.volume
   FROM _timescaledb_internal._materialized_hypertable_10;


ALTER TABLE public.ohlcv_1y OWNER TO postgres;

--
-- Name: ohlcv_30min; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.ohlcv_30min AS
 SELECT _materialized_hypertable_4.market,
    _materialized_hypertable_4.provider,
    _materialized_hypertable_4.symbol,
    _materialized_hypertable_4.timeframe,
    _materialized_hypertable_4.bucketed_time,
    _materialized_hypertable_4.open,
    _materialized_hypertable_4.high,
    _materialized_hypertable_4.low,
    _materialized_hypertable_4.close,
    _materialized_hypertable_4.volume
   FROM _timescaledb_internal._materialized_hypertable_4;


ALTER TABLE public.ohlcv_30min OWNER TO postgres;

--
-- Name: ohlcv_4h; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.ohlcv_4h AS
 SELECT _materialized_hypertable_6.market,
    _materialized_hypertable_6.provider,
    _materialized_hypertable_6.symbol,
    _materialized_hypertable_6.timeframe,
    _materialized_hypertable_6.bucketed_time,
    _materialized_hypertable_6.open,
    _materialized_hypertable_6.high,
    _materialized_hypertable_6.low,
    _materialized_hypertable_6.close,
    _materialized_hypertable_6.volume
   FROM _timescaledb_internal._materialized_hypertable_6;


ALTER TABLE public.ohlcv_4h OWNER TO postgres;

--
-- Name: ohlcv_5min; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.ohlcv_5min AS
 SELECT _materialized_hypertable_2.market,
    _materialized_hypertable_2.provider,
    _materialized_hypertable_2.symbol,
    _materialized_hypertable_2.timeframe,
    _materialized_hypertable_2.bucketed_time,
    _materialized_hypertable_2.open,
    _materialized_hypertable_2.high,
    _materialized_hypertable_2.low,
    _materialized_hypertable_2.close,
    _materialized_hypertable_2.volume
   FROM _timescaledb_internal._materialized_hypertable_2;


ALTER TABLE public.ohlcv_5min OWNER TO postgres;

--
-- Name: user_configs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.user_configs (
    user_id integer NOT NULL,
    config jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.user_configs OWNER TO postgres;

--
-- Name: _hyper_1_1_chunk source; Type: DEFAULT; Schema: _timescaledb_internal; Owner: postgres
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_1_chunk ALTER COLUMN source SET DEFAULT 'api'::text;


--
-- Name: _hyper_1_6_chunk source; Type: DEFAULT; Schema: _timescaledb_internal; Owner: postgres
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_6_chunk ALTER COLUMN source SET DEFAULT 'api'::text;


--
-- Name: _hyper_1_1_chunk 1_1_ohlcv_data_pkey; Type: CONSTRAINT; Schema: _timescaledb_internal; Owner: postgres
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_1_chunk
    ADD CONSTRAINT "1_1_ohlcv_data_pkey" PRIMARY KEY (market, provider, symbol, timeframe, "timestamp");


--
-- Name: _hyper_1_6_chunk 6_2_ohlcv_data_pkey; Type: CONSTRAINT; Schema: _timescaledb_internal; Owner: postgres
--

ALTER TABLE ONLY _timescaledb_internal._hyper_1_6_chunk
    ADD CONSTRAINT "6_2_ohlcv_data_pkey" PRIMARY KEY (market, provider, symbol, timeframe, "timestamp");


--
-- Name: ohlcv_data ohlcv_data_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ohlcv_data
    ADD CONSTRAINT ohlcv_data_pkey PRIMARY KEY (market, provider, symbol, timeframe, "timestamp");


--
-- Name: user_configs user_configs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_configs
    ADD CONSTRAINT user_configs_pkey PRIMARY KEY (user_id);


--
-- Name: _hyper_1_1_chunk_idx_ohlcv_data_composite; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_1_1_chunk_idx_ohlcv_data_composite ON _timescaledb_internal._hyper_1_1_chunk USING btree (market, provider, symbol, timeframe, "timestamp" DESC);


--
-- Name: _hyper_1_1_chunk_ohlcv_data_timestamp_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_1_1_chunk_ohlcv_data_timestamp_idx ON _timescaledb_internal._hyper_1_1_chunk USING btree ("timestamp" DESC);


--
-- Name: _hyper_1_6_chunk_idx_ohlcv_data_composite; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_1_6_chunk_idx_ohlcv_data_composite ON _timescaledb_internal._hyper_1_6_chunk USING btree (market, provider, symbol, timeframe, "timestamp" DESC);


--
-- Name: _hyper_1_6_chunk_ohlcv_data_timestamp_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_1_6_chunk_ohlcv_data_timestamp_idx ON _timescaledb_internal._hyper_1_6_chunk USING btree ("timestamp" DESC);


--
-- Name: _hyper_2_4_chunk__materialized_hypertable_2_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_2_4_chunk__materialized_hypertable_2_bucketed_time_idx ON _timescaledb_internal._hyper_2_4_chunk USING btree (bucketed_time DESC);


--
-- Name: _hyper_2_4_chunk__materialized_hypertable_2_market_bucketed_tim; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_2_4_chunk__materialized_hypertable_2_market_bucketed_tim ON _timescaledb_internal._hyper_2_4_chunk USING btree (market, bucketed_time DESC);


--
-- Name: _hyper_2_4_chunk__materialized_hypertable_2_provider_bucketed_t; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_2_4_chunk__materialized_hypertable_2_provider_bucketed_t ON _timescaledb_internal._hyper_2_4_chunk USING btree (provider, bucketed_time DESC);


--
-- Name: _hyper_2_4_chunk__materialized_hypertable_2_symbol_bucketed_tim; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_2_4_chunk__materialized_hypertable_2_symbol_bucketed_tim ON _timescaledb_internal._hyper_2_4_chunk USING btree (symbol, bucketed_time DESC);


--
-- Name: _hyper_3_3_chunk__materialized_hypertable_3_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_3_3_chunk__materialized_hypertable_3_bucketed_time_idx ON _timescaledb_internal._hyper_3_3_chunk USING btree (bucketed_time DESC);


--
-- Name: _hyper_3_3_chunk__materialized_hypertable_3_market_bucketed_tim; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_3_3_chunk__materialized_hypertable_3_market_bucketed_tim ON _timescaledb_internal._hyper_3_3_chunk USING btree (market, bucketed_time DESC);


--
-- Name: _hyper_3_3_chunk__materialized_hypertable_3_provider_bucketed_t; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_3_3_chunk__materialized_hypertable_3_provider_bucketed_t ON _timescaledb_internal._hyper_3_3_chunk USING btree (provider, bucketed_time DESC);


--
-- Name: _hyper_3_3_chunk__materialized_hypertable_3_symbol_bucketed_tim; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_3_3_chunk__materialized_hypertable_3_symbol_bucketed_tim ON _timescaledb_internal._hyper_3_3_chunk USING btree (symbol, bucketed_time DESC);


--
-- Name: _hyper_4_2_chunk__materialized_hypertable_4_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_4_2_chunk__materialized_hypertable_4_bucketed_time_idx ON _timescaledb_internal._hyper_4_2_chunk USING btree (bucketed_time DESC);


--
-- Name: _hyper_4_2_chunk__materialized_hypertable_4_market_bucketed_tim; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_4_2_chunk__materialized_hypertable_4_market_bucketed_tim ON _timescaledb_internal._hyper_4_2_chunk USING btree (market, bucketed_time DESC);


--
-- Name: _hyper_4_2_chunk__materialized_hypertable_4_provider_bucketed_t; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_4_2_chunk__materialized_hypertable_4_provider_bucketed_t ON _timescaledb_internal._hyper_4_2_chunk USING btree (provider, bucketed_time DESC);


--
-- Name: _hyper_4_2_chunk__materialized_hypertable_4_symbol_bucketed_tim; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_4_2_chunk__materialized_hypertable_4_symbol_bucketed_tim ON _timescaledb_internal._hyper_4_2_chunk USING btree (symbol, bucketed_time DESC);


--
-- Name: _hyper_5_5_chunk__materialized_hypertable_5_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_5_5_chunk__materialized_hypertable_5_bucketed_time_idx ON _timescaledb_internal._hyper_5_5_chunk USING btree (bucketed_time DESC);


--
-- Name: _hyper_5_5_chunk__materialized_hypertable_5_market_bucketed_tim; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_5_5_chunk__materialized_hypertable_5_market_bucketed_tim ON _timescaledb_internal._hyper_5_5_chunk USING btree (market, bucketed_time DESC);


--
-- Name: _hyper_5_5_chunk__materialized_hypertable_5_provider_bucketed_t; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_5_5_chunk__materialized_hypertable_5_provider_bucketed_t ON _timescaledb_internal._hyper_5_5_chunk USING btree (provider, bucketed_time DESC);


--
-- Name: _hyper_5_5_chunk__materialized_hypertable_5_symbol_bucketed_tim; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_5_5_chunk__materialized_hypertable_5_symbol_bucketed_tim ON _timescaledb_internal._hyper_5_5_chunk USING btree (symbol, bucketed_time DESC);


--
-- Name: _hyper_6_7_chunk__materialized_hypertable_6_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_6_7_chunk__materialized_hypertable_6_bucketed_time_idx ON _timescaledb_internal._hyper_6_7_chunk USING btree (bucketed_time DESC);


--
-- Name: _hyper_6_7_chunk__materialized_hypertable_6_market_bucketed_tim; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_6_7_chunk__materialized_hypertable_6_market_bucketed_tim ON _timescaledb_internal._hyper_6_7_chunk USING btree (market, bucketed_time DESC);


--
-- Name: _hyper_6_7_chunk__materialized_hypertable_6_provider_bucketed_t; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_6_7_chunk__materialized_hypertable_6_provider_bucketed_t ON _timescaledb_internal._hyper_6_7_chunk USING btree (provider, bucketed_time DESC);


--
-- Name: _hyper_6_7_chunk__materialized_hypertable_6_symbol_bucketed_tim; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_6_7_chunk__materialized_hypertable_6_symbol_bucketed_tim ON _timescaledb_internal._hyper_6_7_chunk USING btree (symbol, bucketed_time DESC);


--
-- Name: _materialized_hypertable_10_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_10_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_10 USING btree (bucketed_time DESC);


--
-- Name: _materialized_hypertable_10_market_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_10_market_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_10 USING btree (market, bucketed_time DESC);


--
-- Name: _materialized_hypertable_10_provider_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_10_provider_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_10 USING btree (provider, bucketed_time DESC);


--
-- Name: _materialized_hypertable_10_symbol_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_10_symbol_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_10 USING btree (symbol, bucketed_time DESC);


--
-- Name: _materialized_hypertable_2_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_2_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_2 USING btree (bucketed_time DESC);


--
-- Name: _materialized_hypertable_2_market_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_2_market_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_2 USING btree (market, bucketed_time DESC);


--
-- Name: _materialized_hypertable_2_provider_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_2_provider_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_2 USING btree (provider, bucketed_time DESC);


--
-- Name: _materialized_hypertable_2_symbol_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_2_symbol_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_2 USING btree (symbol, bucketed_time DESC);


--
-- Name: _materialized_hypertable_3_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_3_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_3 USING btree (bucketed_time DESC);


--
-- Name: _materialized_hypertable_3_market_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_3_market_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_3 USING btree (market, bucketed_time DESC);


--
-- Name: _materialized_hypertable_3_provider_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_3_provider_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_3 USING btree (provider, bucketed_time DESC);


--
-- Name: _materialized_hypertable_3_symbol_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_3_symbol_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_3 USING btree (symbol, bucketed_time DESC);


--
-- Name: _materialized_hypertable_4_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_4_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_4 USING btree (bucketed_time DESC);


--
-- Name: _materialized_hypertable_4_market_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_4_market_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_4 USING btree (market, bucketed_time DESC);


--
-- Name: _materialized_hypertable_4_provider_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_4_provider_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_4 USING btree (provider, bucketed_time DESC);


--
-- Name: _materialized_hypertable_4_symbol_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_4_symbol_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_4 USING btree (symbol, bucketed_time DESC);


--
-- Name: _materialized_hypertable_5_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_5_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_5 USING btree (bucketed_time DESC);


--
-- Name: _materialized_hypertable_5_market_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_5_market_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_5 USING btree (market, bucketed_time DESC);


--
-- Name: _materialized_hypertable_5_provider_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_5_provider_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_5 USING btree (provider, bucketed_time DESC);


--
-- Name: _materialized_hypertable_5_symbol_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_5_symbol_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_5 USING btree (symbol, bucketed_time DESC);


--
-- Name: _materialized_hypertable_6_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_6_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_6 USING btree (bucketed_time DESC);


--
-- Name: _materialized_hypertable_6_market_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_6_market_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_6 USING btree (market, bucketed_time DESC);


--
-- Name: _materialized_hypertable_6_provider_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_6_provider_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_6 USING btree (provider, bucketed_time DESC);


--
-- Name: _materialized_hypertable_6_symbol_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_6_symbol_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_6 USING btree (symbol, bucketed_time DESC);


--
-- Name: _materialized_hypertable_7_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_7_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_7 USING btree (bucketed_time DESC);


--
-- Name: _materialized_hypertable_7_market_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_7_market_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_7 USING btree (market, bucketed_time DESC);


--
-- Name: _materialized_hypertable_7_provider_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_7_provider_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_7 USING btree (provider, bucketed_time DESC);


--
-- Name: _materialized_hypertable_7_symbol_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_7_symbol_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_7 USING btree (symbol, bucketed_time DESC);


--
-- Name: _materialized_hypertable_8_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_8_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_8 USING btree (bucketed_time DESC);


--
-- Name: _materialized_hypertable_8_market_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_8_market_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_8 USING btree (market, bucketed_time DESC);


--
-- Name: _materialized_hypertable_8_provider_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_8_provider_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_8 USING btree (provider, bucketed_time DESC);


--
-- Name: _materialized_hypertable_8_symbol_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_8_symbol_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_8 USING btree (symbol, bucketed_time DESC);


--
-- Name: _materialized_hypertable_9_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_9_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_9 USING btree (bucketed_time DESC);


--
-- Name: _materialized_hypertable_9_market_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_9_market_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_9 USING btree (market, bucketed_time DESC);


--
-- Name: _materialized_hypertable_9_provider_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_9_provider_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_9 USING btree (provider, bucketed_time DESC);


--
-- Name: _materialized_hypertable_9_symbol_bucketed_time_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_9_symbol_bucketed_time_idx ON _timescaledb_internal._materialized_hypertable_9 USING btree (symbol, bucketed_time DESC);


--
-- Name: idx_ohlcv_data_composite; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_ohlcv_data_composite ON public.ohlcv_data USING btree (market, provider, symbol, timeframe, "timestamp" DESC);


--
-- Name: ohlcv_data_timestamp_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ohlcv_data_timestamp_idx ON public.ohlcv_data USING btree ("timestamp" DESC);


--
-- Name: _hyper_1_1_chunk ts_cagg_invalidation_trigger; Type: TRIGGER; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TRIGGER ts_cagg_invalidation_trigger AFTER INSERT OR DELETE OR UPDATE ON _timescaledb_internal._hyper_1_1_chunk FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.continuous_agg_invalidation_trigger('1');


--
-- Name: _hyper_1_6_chunk ts_cagg_invalidation_trigger; Type: TRIGGER; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TRIGGER ts_cagg_invalidation_trigger AFTER INSERT OR DELETE OR UPDATE ON _timescaledb_internal._hyper_1_6_chunk FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.continuous_agg_invalidation_trigger('1');


--
-- Name: _materialized_hypertable_10 ts_insert_blocker; Type: TRIGGER; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON _timescaledb_internal._materialized_hypertable_10 FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- Name: _materialized_hypertable_2 ts_insert_blocker; Type: TRIGGER; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON _timescaledb_internal._materialized_hypertable_2 FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- Name: _materialized_hypertable_3 ts_insert_blocker; Type: TRIGGER; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON _timescaledb_internal._materialized_hypertable_3 FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- Name: _materialized_hypertable_4 ts_insert_blocker; Type: TRIGGER; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON _timescaledb_internal._materialized_hypertable_4 FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- Name: _materialized_hypertable_5 ts_insert_blocker; Type: TRIGGER; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON _timescaledb_internal._materialized_hypertable_5 FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- Name: _materialized_hypertable_6 ts_insert_blocker; Type: TRIGGER; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON _timescaledb_internal._materialized_hypertable_6 FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- Name: _materialized_hypertable_7 ts_insert_blocker; Type: TRIGGER; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON _timescaledb_internal._materialized_hypertable_7 FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- Name: _materialized_hypertable_8 ts_insert_blocker; Type: TRIGGER; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON _timescaledb_internal._materialized_hypertable_8 FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- Name: _materialized_hypertable_9 ts_insert_blocker; Type: TRIGGER; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON _timescaledb_internal._materialized_hypertable_9 FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- Name: ohlcv_data ts_cagg_invalidation_trigger; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER ts_cagg_invalidation_trigger AFTER INSERT OR DELETE OR UPDATE ON public.ohlcv_data FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.continuous_agg_invalidation_trigger('1');


--
-- Name: ohlcv_data ts_insert_blocker; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON public.ohlcv_data FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- PostgreSQL database dump complete
--

