# blueprints/market.py

from typing import Optional, List # List might be needed for other type hints in the file
import logging
from quart import Blueprint, request, current_app # Added current_app for config access
from plugins.base import PluginError
from plugins import PluginLoader
from utils.timeframes import TIMEFRAME_PATTERN
from services.market_service import MarketService
from utils.response import make_error_response, make_success_response, make_highcharts_response

logger = logging.getLogger("market_blueprint")
market_blueprint = Blueprint("market", __name__, url_prefix="/api/market")


def _parse_int(name: str, value: str | None, default: Optional[int] = None) -> int | None:
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        raise ValueError(f"Parameter '{name}' must be an integer.")


@market_blueprint.route("/providers", methods=["GET"])
async def get_providers():
    market_query = request.args.get("market")
    if not market_query:
        logger.warning("/providers - Missing 'market' parameter")
        return make_error_response("Missing 'market' parameter", code=400)

    logger.info(f"/providers - Request for market: {market_query}")
    providers_set = set()

    if market_query == "crypto":
        try:
            crypto_plugin = PluginLoader.load_plugin("crypto")
            exchange_ids = await crypto_plugin.get_exchanges()
            providers_set.update(exchange_ids)
            logger.info(f"/providers - Loaded {len(exchange_ids)} crypto exchange providers from CryptoPlugin for market '{market_query}'.")
        except PluginError as e:
            logger.error(f"/providers - CryptoPlugin failed to load or get_exchanges() failed for market '{market_query}': {e}", exc_info=True)
            # If crypto plugin itself fails, this is a significant issue for the "crypto" market.
            # Depending on requirements, you might return an error immediately or try to proceed if other plugins could serve "crypto".
            # For now, we'll log and let it try to find other plugins, but it's unlikely for "crypto".
        except Exception as e: # Catch any other unexpected error
            logger.error(f"/providers - Unexpected error loading CryptoPlugin for market '{market_query}': {e}", exc_info=True)


    # This loop is more for non-"crypto" market types where each plugin IS a provider,
    # or to discover additional plugins that might support the queried market.
    for plugin_key in PluginLoader.list_plugins():
        # If market is "crypto", we've already tried to get all exchanges from the dedicated "crypto" plugin.
        # Other plugins are unlikely to be crypto exchanges themselves unless specifically designed that way.
        if plugin_key == "crypto" and market_query == "crypto":
            continue 
        try:
            plugin = PluginLoader.load_plugin(plugin_key)
            supported_by_plugin = getattr(plugin, "supported_markets", [])
            if market_query in supported_by_plugin:
                # For these plugins, the plugin_key itself represents the provider ID
                providers_set.add(plugin_key) 
                logger.debug(f"/providers - Plugin '{plugin_key}' supports market '{market_query}'. Added to list.")
        except PluginError:
            logger.warning(f"/providers - Plugin '{plugin_key}' failed to load while listing providers for market '{market_query}'. Skipping.")
        except Exception as e:
             logger.error(f"/providers - Unexpected error processing plugin '{plugin_key}' for market '{market_query}': {e}", exc_info=True)

    if not providers_set:
        logger.warning(f"/providers - No providers found for market '{market_query}' after checking all sources.")
        return make_error_response(f"No providers could be determined for market '{market_query}' at this time.", code=404)

    logger.info(f"/providers - Returning {len(providers_set)} providers for market '{market_query}'.")
    return make_success_response(data={"providers": sorted(list(providers_set))})


@market_blueprint.route("/symbols", methods=["GET"])
async def get_symbols():
    market = request.args.get("market")
    provider = request.args.get("provider") 
    if not (market and provider):
        return make_error_response("Missing 'market' or 'provider' parameter", code=400)

    logger.info(f"/symbols - Request: market='{market}', provider='{provider}'")
    try:
        svc = MarketService(market, provider) # Can raise ValueError on plugin init issues
        symbols = await svc.get_symbols()   # Can raise PluginError
        logger.info(f"/symbols - Successfully fetched {len(symbols)} symbols for {market}/{provider}.")
        return make_success_response(data={"symbols": symbols})
    except ValueError as e: 
        logger.error(f"/symbols - ValueError for {market}/{provider}: {e}", exc_info=True)
        # This often means MarketService couldn't initialize due to plugin issues for this provider
        return make_error_response(f"Provider '{provider}' is not available or there was a configuration error: {str(e)}", code=404)
    except PluginError as e: 
        logger.error(f"/symbols - PluginError for {market}/{provider}: {e}", exc_info=True)
        # Check for specific, common plugin errors to give better feedback
        error_detail = str(e)
        if "525" in error_detail and "SSL handshake failed" in error_detail:
             return make_error_response(f"Error connecting to '{provider}': SSL handshake failed. The exchange API may be down or have SSL issues.", code=524)
        return make_error_response(f"Could not fetch symbols from '{provider}': An external service error occurred.", code=502) # Bad Gateway
    except Exception as e: 
        logger.exception(f"/symbols - Unexpected critical error for {market}/{provider}: {e}")
        return make_error_response("An internal server error occurred while trying to fetch symbols.", code=500)


@market_blueprint.route("/ohlcv", methods=["GET"])
async def fetch_ohlcv_endpoint(): # Renamed to avoid conflict if importing other things named fetch_ohlcv
    market = request.args.get("market")
    provider = request.args.get("provider")
    symbol_param = request.args.get("symbol") # Renamed to avoid clash with imported 'symbol'
    timeframe = request.args.get("timeframe", "1m")
    since_str = request.args.get("since")
    before_str = request.args.get("before")
    limit_str = request.args.get("limit")

    logger.info(f"/ohlcv request: market={market}, provider={provider}, symbol={symbol_param}, timeframe={timeframe}, since={since_str}, before={before_str}, limit={limit_str}")

    if not (market and provider and symbol_param):
        return make_error_response("Missing one of required parameters: 'market', 'provider', or 'symbol'", code=400)

    if not TIMEFRAME_PATTERN.match(timeframe):
        return make_error_response(f"Invalid 'timeframe' format: '{timeframe}'", code=400)

    try:
        since = _parse_int("since", since_str, default=None) # Allow None
        before = _parse_int("before", before_str, default=None)
        # Use app config for default OHLCV limit if not provided by client
        default_api_limit = current_app.config.get("DEFAULT_CHART_POINTS_API", 200) 
        limit = _parse_int("limit", limit_str, default=default_api_limit)

    except ValueError as e: # From _parse_int
        return make_error_response(str(e), code=400)

    # Parameter validation logic (can be expanded)
    if before is not None and since is not None and since >= before: # `since` being None with `before` is allowed for lazy loading
         return make_error_response("'since' must be less than 'before' if both are provided", code=400)
    
    if limit is not None and limit <= 0: # limit should be positive if provided
        return make_error_response("'limit' must be positive if provided", code=400)
    if limit is None: # Should have been set by default in _parse_int, but as a safeguard
        limit = current_app.config.get("DEFAULT_CHART_POINTS_API", 200)


    try:
        svc = MarketService(market, provider) # Can fail for problematic providers
        out = await svc.fetch_ohlcv(
            symbol=symbol_param,
            timeframe=timeframe,
            since=since,
            before=before,
            limit=limit
        )
        logger.info(f"/ohlcv - Successfully fetched {len(out['ohlc'])} OHLCV bars for {market}/{provider}/{symbol_param}.")
        return make_highcharts_response(out["ohlc"], out["volume"])
    except ValueError as e: 
        logger.error(f"/ohlcv - ValueError for {market}/{provider}/{symbol_param}: {e}", exc_info=True)
        return make_error_response(f"Error with request for '{provider}': {str(e)}", code=400 if "Parameter" in str(e) else 404)
    except PluginError as e:
        logger.error(f"/ohlcv - PluginError for {market}/{provider}/{symbol_param}: {e}", exc_info=True)
        return make_error_response(f"Data provider error for '{provider}': {str(e)}", code=502) # Bad Gateway for upstream issues
    except Exception: # Catch-all
        logger.exception(f"/ohlcv - Unexpected error for {market}/{provider}/{symbol_param}")
        return make_error_response("Internal server error fetching chart data.", code=500)