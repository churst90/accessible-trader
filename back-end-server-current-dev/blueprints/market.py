# blueprints/market.py

from typing import Optional, List, Type, Any, Dict 
import logging
from quart import Blueprint, request, current_app
from plugins.base import PluginError, MarketPlugin
from plugins import PluginLoader 
from utils.timeframes import TIMEFRAME_PATTERN, format_timestamp_to_iso
from services.market_service import MarketService
from services.data_orchestrator import OHLCVBar
from utils.response import make_error_response, make_success_response, make_highcharts_response

logger = logging.getLogger("market_blueprint")
market_blueprint = Blueprint("market", __name__, url_prefix="/api/market")


def _parse_int(name: str, value: Optional[str], default: Optional[int] = None) -> Optional[int]:
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        raise ValueError(f"Parameter '{name}' must be an integer.")


@market_blueprint.route("/providers", methods=["GET"])
async def get_providers() -> tuple[Dict[str, Any], int]:
    """
    Get a list of available data providers for a given market (e.g., "crypto", "stocks").
    This endpoint dynamically determines providers based on ALL registered plugins
    that support the given market and their capabilities.
    """
    market_query: Optional[str] = request.args.get("market")
    if not market_query:
        logger.warning("/providers - Call missing 'market' query parameter.")
        return make_error_response("Missing 'market' query parameter", code=400)

    log_prefix = f"/providers (Market: {market_query}):"
    logger.info(f"{log_prefix} Request received.")

    try:
        # MODIFIED: Get all plugin keys that support the market
        plugin_class_keys: List[str] = PluginLoader.get_plugin_keys_for_market(market_query)

        if not plugin_class_keys:
            # No plugins explicitly list this market in their supported_markets.
            # The original fallback was to check if market_query itself is a plugin_key.
            # This behavior might be desired if a user directly asks for providers of "alpaca" (plugin_key).
            # However, the primary purpose of this endpoint is providers *for a market type*.
            # For now, let's stick to finding plugins based on the market they claim to support.
            logger.warning(f"{log_prefix} No plugin keys found directly mapped to handle market '{market_query}'.")
            # Check if any plugin class has this market_query as ITS plugin_key AND supports it.
            # This case is implicitly handled if plugins correctly list their supported markets.
            # If get_plugin_keys_for_market returns empty, it means no plugin declared this market.
            return make_error_response(f"No plugins are configured to support the market '{market_query}'.", code=404)

        all_providers_set: set[str] = set() # Use a set to automatically handle duplicates

        for plugin_key in plugin_class_keys:
            plugin_class: Optional[Type[MarketPlugin]] = PluginLoader.get_plugin_class_by_key(plugin_key)

            if not plugin_class:
                logger.error(f"{log_prefix} Could not load plugin class for key '{plugin_key}' (intended for market: '{market_query}'). Skipping this plugin key.")
                continue # Skip to the next plugin key

            if hasattr(plugin_class, 'list_configurable_providers') and callable(plugin_class.list_configurable_providers):
                try:
                    # Each plugin class lists providers it can be configured with.
                    # e.g., CryptoPlugin -> ["binance", "kraken"], AlpacaPlugin -> ["alpaca"]
                    current_plugin_providers: List[str] = plugin_class.list_configurable_providers()
                    if current_plugin_providers:
                        all_providers_set.update(current_plugin_providers)
                        logger.debug(f"{log_prefix} Plugin '{plugin_key}' contributed providers: {current_plugin_providers}")
                    else:
                        logger.debug(f"{log_prefix} Plugin '{plugin_key}' returned no configurable providers.")
                except Exception as e_list_providers:
                    logger.error(f"{log_prefix} Error calling list_configurable_providers for plugin class '{plugin_class.__name__}' (key: {plugin_key}): {e_list_providers}", exc_info=True)
                    # Decide if one plugin failing should stop all provider listing. For now, continue.
            else:
                logger.warning(f"{log_prefix} Plugin class '{plugin_class.__name__}' (key: '{plugin_key}') does not have 'list_configurable_providers'. Skipping.")
        
        final_providers_list = sorted(list(all_providers_set))

        if not final_providers_list:
            logger.warning(f"{log_prefix} No providers found in total for market '{market_query}' from any supporting plugin.")
            return make_error_response(f"No providers available for market '{market_query}'.", code=404)
            
        logger.info(f"{log_prefix} Market '{market_query}': Found {len(final_providers_list)} unique providers from {len(plugin_class_keys)} plugin type(s): {final_providers_list}")
        return make_success_response(data={"providers": final_providers_list})

    except Exception as e: # Catch-all for unexpected errors in this new logic
        logger.error(f"{log_prefix} Unexpected error while aggregating providers: {e}", exc_info=True)
        return make_error_response(f"Could not determine providers for market '{market_query}' due to an internal server error.", code=500)


# ... (rest of market.py: /symbols, /ohlcv, /markets endpoints remain the same) ...

@market_blueprint.route("/symbols", methods=["GET"])
async def get_symbols() -> tuple[Dict[str, Any], int]:
    """
    Get a list of tradable symbols for a given market and provider.
    """
    market: Optional[str] = request.args.get("market")
    provider: Optional[str] = request.args.get("provider")

    if not (market and provider):
        logger.warning("/symbols - Call missing 'market' or 'provider' query parameter.")
        return make_error_response("Missing 'market' or 'provider' query parameter", code=400)

    log_prefix = f"/symbols (Market: {market}, Provider: {provider}):"
    logger.info(f"{log_prefix} Request received.")
    try:
        svc: Optional[MarketService] = getattr(current_app, 'market_service', None)
        if not svc or not isinstance(svc, MarketService):
            logger.error(f"{log_prefix} MarketService not found or not correctly initialized on current_app.")
            return make_error_response("Internal server configuration error: MarketService unavailable.", code=500)

        symbols_list: List[str] = await svc.get_symbols(market=market, provider=provider) 
        logger.info(f"{log_prefix} Successfully fetched {len(symbols_list)} symbols.")
        return make_success_response(data={"symbols": symbols_list})

    except ValueError as e: 
        logger.error(f"{log_prefix} ValueError: {e}", exc_info=True)
        return make_error_response(f"Configuration error or invalid request for market '{market}' and provider '{provider}': {str(e)}", code=404) # 404 if "not found"
    except PluginError as e: 
        logger.error(f"{log_prefix} PluginError: {e}", exc_info=True)
        status_code = 502 
        if "Authentication" in e.__class__.__name__: status_code = 401
        elif "NotSupported" in e.__class__.__name__: status_code = 501
        elif "Network" in e.__class__.__name__: status_code = 504
        return make_error_response(f"Could not fetch symbols from '{provider}': {str(e)}", code=status_code)
    except Exception as e:
        logger.exception(f"{log_prefix} Unexpected critical error: {e}")
        return make_error_response("An internal server error occurred while trying to fetch symbols.", code=500)


@market_blueprint.route("/ohlcv", methods=["GET"])
async def fetch_ohlcv_endpoint() -> tuple[Dict[str, Any], int]:
    market: Optional[str] = request.args.get("market")
    provider: Optional[str] = request.args.get("provider")
    symbol_param: Optional[str] = request.args.get("symbol")
    timeframe: str = request.args.get("timeframe", "1m") 
    since_str: Optional[str] = request.args.get("since")
    until_str: Optional[str] = request.args.get("until") 
    if until_str is None:
        until_str = request.args.get("before") 
    limit_str: Optional[str] = request.args.get("limit")

    log_prefix = f"/ohlcv (M:{market},P:{provider},S:{symbol_param},TF:{timeframe}):"
    logger.info(f"{log_prefix} Request: since={since_str}, until/before={until_str}, limit={limit_str}")

    if not (market and provider and symbol_param):
        return make_error_response("Missing one of required parameters: 'market', 'provider', or 'symbol'", code=400)

    if not TIMEFRAME_PATTERN.match(timeframe):
        return make_error_response(f"Invalid 'timeframe' format: '{timeframe}'. Expected e.g., '1m', '1h', '1d'.", code=400)

    try:
        since_ms: Optional[int] = _parse_int("since", since_str)
        until_ms: Optional[int] = _parse_int("until", until_str)
        
        default_api_limit: int = current_app.config.get("DEFAULT_CHART_POINTS", 200)
        limit_val: Optional[int] = _parse_int("limit", limit_str, default=default_api_limit)
        if limit_val is None: limit_val = default_api_limit 
        if limit_val <= 0: 
            return make_error_response("'limit' must be a positive integer.", code=400)

    except ValueError as e_parse:
        logger.warning(f"{log_prefix} Invalid integer parameter: {e_parse}")
        return make_error_response(str(e_parse), code=400)

    if until_ms is not None and since_ms is not None and since_ms >= until_ms:
        return make_error_response("'since' timestamp must be less than 'until'/'before' timestamp if both are provided.", code=400)
        
    try:
        svc: Optional[MarketService] = getattr(current_app, 'market_service', None)
        if not svc or not isinstance(svc, MarketService):
            logger.error(f"{log_prefix} MarketService not found or not correctly initialized on current_app.")
            return make_error_response("Internal server configuration error: MarketService unavailable.", code=500)

        ohlcv_bars: List[OHLCVBar] = await svc.fetch_ohlcv(
            market=market,
            provider=provider,
            symbol=symbol_param,
            timeframe=timeframe,
            since=since_ms,
            until=until_ms, 
            limit=limit_val
        )
        logger.info(f"{log_prefix} Successfully fetched {len(ohlcv_bars)} OHLCV bars from MarketService.")
        
        ohlc_for_chart: List[List[Any]] = []
        volume_for_chart: List[List[Any]] = []
        for bar in ohlcv_bars:
            ohlc_for_chart.append([bar['timestamp'], bar['open'], bar['high'], bar['low'], bar['close']])
            volume_for_chart.append([bar['timestamp'], bar['volume']])
            
        return make_highcharts_response(ohlc_for_chart, volume_for_chart)

    except ValueError as e_val: 
        logger.warning(f"{log_prefix} ValueError: {e_val}", exc_info=False)
        code = 404 if "not found" in str(e_val).lower() or "unavailable" in str(e_val).lower() else 400
        return make_error_response(f"Request error for '{provider}': {str(e_val)}", code=code)
    except PluginError as e_plugin:
        logger.error(f"{log_prefix} PluginError: {e_plugin}", exc_info=True)
        status_code = 502 
        if "Authentication" in e_plugin.__class__.__name__: status_code = 401
        elif "NotSupported" in e_plugin.__class__.__name__: status_code = 501
        elif "Network" in e_plugin.__class__.__name__: status_code = 504
        return make_error_response(f"Data provider error for '{provider}': {str(e_plugin)}", code=status_code)
    except Exception as e_critical:
        logger.exception(f"{log_prefix} Unexpected critical error: {e_critical}")
        return make_error_response("Internal server error fetching chart data.", code=500)

@market_blueprint.route("/markets", methods=["GET"])
async def get_all_available_markets() -> tuple[Dict[str, Any], int]:
    """
    Get a list of all unique market names discovered and supported by available plugins.
    e.g., ["crypto", "stocks", "us_equity"]
    """
    log_prefix = "/markets:"
    logger.info(f"{log_prefix} Request received to list all available markets.")

    try:
        all_markets_list: List[str] = PluginLoader.get_all_markets()

        if not all_markets_list:
            logger.warning(f"{log_prefix} No markets found by PluginLoader.")
            return make_success_response(data={"markets": []})

        logger.info(f"{log_prefix} Successfully retrieved {len(all_markets_list)} markets: {all_markets_list}")
        return make_success_response(data={"markets": all_markets_list})

    except Exception as e:
        logger.error(f"{log_prefix} Unexpected error while fetching all markets: {e}", exc_info=True)
        return make_error_response("An internal server error occurred while trying to fetch available markets.", code=500)