# blueprints/market.py

import logging

from quart import Blueprint, request
from plugins.base import PluginError
from plugins import PluginLoader
from utils.timeframes import TIMEFRAME_PATTERN
from services.market_service import MarketService
from utils.response import make_error_response, make_success_response, make_highcharts_response

logger = logging.getLogger("market_blueprint")
market_blueprint = Blueprint("market", __name__, url_prefix="/api/market")


def _parse_int(name: str, value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        raise ValueError(f"Parameter '{name}' must be an integer.")


@market_blueprint.route("/providers", methods=["GET"])
async def get_providers():
    market = request.args.get("market")
    if not market:
        return make_error_response("Missing 'market' parameter", code=400)

    # crypto
    if market == "crypto":
        try:
            crypto = PluginLoader.load_plugin("crypto")
            exs    = await crypto.get_exchanges()
            return make_success_response(data={"providers": exs})
        except PluginError as e:
            return make_error_response(str(e), code=400)

    # other markets
    providers = []
    for key in PluginLoader.list_plugins():
        try:
            plugin = PluginLoader.load_plugin(key)
            if market in getattr(plugin, "supported_markets", []):
                providers.append(key)
        except PluginError:
            continue

    if not providers:
        return make_error_response(f"No providers for market '{market}'", code=404)

    return make_success_response(data={"providers": providers})


@market_blueprint.route("/symbols", methods=["GET"])
async def get_symbols():
    market   = request.args.get("market")
    provider = request.args.get("provider")
    if not (market and provider):
        return make_error_response("Missing 'market' or 'provider'", code=400)

    try:
        svc     = MarketService(market, provider)
        symbols = await svc.get_symbols()
        return make_success_response(data={"symbols": symbols})
    except (ValueError, PluginError) as e:
        return make_error_response(str(e), code=400)
    except Exception:
        logger.exception("Unexpected error in get_symbols")
        return make_error_response("Internal server error", code=500)


@market_blueprint.route("/ohlcv", methods=["GET"])
async def fetch_ohlcv():
    market     = request.args.get("market")
    provider   = request.args.get("provider")
    symbol     = request.args.get("symbol")
    timeframe  = request.args.get("timeframe", "1m")
    since_str  = request.args.get("since")
    before_str = request.args.get("before")
    limit_str  = request.args.get("limit")

    if not (market and provider and symbol):
        return make_error_response(
            "Missing one of required parameters: 'market', 'provider', or 'symbol'",
            code=400
        )

    if not TIMEFRAME_PATTERN.match(timeframe):
        return make_error_response(
            f"Invalid 'timeframe' format: '{timeframe}'", code=400
        )

    try:
        since  = _parse_int("since", since_str)
        before = _parse_int("before", before_str)
        limit  = _parse_int("limit", limit_str)
    except ValueError as e:
        return make_error_response(str(e), code=400)

    if before is not None and since is None:
        return make_error_response("'since' is required when 'before' is provided", code=400)
    if since is not None and before is not None and since >= before:
        return make_error_response("'since' must be less than 'before'", code=400)
    if limit is not None and limit <= 0:
        return make_error_response("'limit' must be positive", code=400)

    try:
        svc  = MarketService(market, provider)
        out  = await svc.fetch_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            since=since,
            before=before,
            limit=limit
        )
        return make_highcharts_response(out["ohlc"], out["volume"])
    except (ValueError, PluginError) as e:
        return make_error_response(str(e), code=404)
    except Exception:
        logger.exception("Unexpected error in fetch_ohlcv")
        return make_error_response("Internal server error", code=500)
