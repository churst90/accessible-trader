#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import asyncio
import time
import logging
from datetime import datetime
from dotenv import load_dotenv

# 1) Load environment variables
load_dotenv()

# 2) Bootstrap the Quart app and DB pool
from app import create_app
from app_extensions.db_pool import init_db_pool

app = create_app()

# 3) Settings
API_BATCH        = 1000      # bars per request
RATE_LIMIT_DELAY = 1         # seconds between requests
TF_PERIOD_MS     = 60_000    # one minute in milliseconds

# 4) Helper: find the earliest stored bar timestamp (ms)
async def fetch_earliest_timestamp(market, provider, symbol):
    from utils.db_utils import fetch_query
    rows = await fetch_query(
        """
        SELECT MIN(timestamp) AS ts
          FROM ohlcv_data
         WHERE market=$1
           AND provider=$2
           AND symbol=$3
           AND timeframe=$4
        """,
        market, provider, symbol, "1m"
    )
    ts = rows[0]["ts"]
    return None if ts is None else int(ts.timestamp() * 1000)


# 5) Backfill one symbol newest?oldest, resuming where it left off
async def backfill_symbol(market, provider, symbol):
    from services.market_service import MarketService
    from utils.db_utils          import insert_ohlcv_to_db

    logging.info(f"Backfilling {market}/{provider}/{symbol} backward in chunks...")

    svc    = MarketService(market, provider)
    plugin = svc.plugin

    # get the raw CCXT exchange so we can pass 'end' in seconds
    ex = plugin._get_exchange_instance(provider)

    # resume from where we left off: oldest bar in DB, or now if none
    earliest = await fetch_earliest_timestamp(market, provider, symbol)
    if earliest is None:
        cursor_ms = int(time.time() * 1000)
    else:
        # move one period before the earliest to fetch older bars
        cursor_ms = earliest - TF_PERIOD_MS

    while True:
        # convert to seconds for the 'end' parameter
        cursor_s = cursor_ms // 1000

        # fetch the next older batch strictly before cursor_s
        raw = await ex.fetch_ohlcv(
            symbol,
            '1m',
            since=None,
            limit=API_BATCH,
            params={'end': cursor_s}
        )

        # convert lists [ts,o,h,l,c,v] into dicts
        batch = [
            {
                "timestamp": bar[0],
                "open":      bar[1],
                "high":      bar[2],
                "low":       bar[3],
                "close":     bar[4],
                "volume":    bar[5],
            }
            for bar in raw
        ]

        if not batch:
            logging.info(f"{symbol} fully backfilled.")
            break

        # upsert into ohlcv_data
        await insert_ohlcv_to_db(market, provider, symbol, '1m', batch)
        oldest_ts = batch[0]["timestamp"]
        logging.info(f"Pulled {len(batch)} bars; oldest now {oldest_ts}")

        # move cursor back by one candle period
        cursor_ms = oldest_ts - TF_PERIOD_MS

        # rate limit
        await asyncio.sleep(RATE_LIMIT_DELAY)

    # clean up HTTP sessions
    try:
        await ex.close()
        logging.info(f"Closed CCXT session for {provider}")
    except Exception:
        logging.warning("Error closing CCXT session for %s", provider)


# 6) Main entrypoint
async def main():
    # initialize DB pool
    pool = await init_db_pool(app)
    app.config['DB_POOL'] = pool

    # push app context for fetch_query, etc.
    async with app.app_context():
        import argparse
        from services.market_service import MarketService

        parser = argparse.ArgumentParser(
            description="Backward-page 1m OHLCV history"
        )
        parser.add_argument('--market',   required=True, help="Market key, e.g. 'crypto'")
        parser.add_argument('--provider', required=True, help="Provider key, e.g. 'bitstamp'")
        parser.add_argument('--symbol',   help="Symbol to backfill, e.g. 'BTC/USD'; omit for all")
        args = parser.parse_args()

        # build list of (market,provider,symbol)
        if args.symbol:
            targets = [(args.market, args.provider, args.symbol)]
        else:
            svc     = MarketService(args.market, args.provider)
            symbols = await svc.get_symbols()
            targets = [(args.market, args.provider, s) for s in symbols]

        # backfill each target
        for m, p, s in targets:
            try:
                await backfill_symbol(m, p, s)
            except Exception:
                logging.exception("Error backfilling %s/%s/%s", m, p, s)


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s"
    )
    asyncio.run(main())
