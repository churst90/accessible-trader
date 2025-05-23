# blueprints/market.py

from typing import Optional, List, Type, Any, Dict # Added Dict and Any
import logging
from quart import Blueprint, request, current_app # Ensure current_app is imported
from plugins.base import PluginError, MarketPlugin # For type hinting
from plugins import PluginLoader # Import PluginLoader to access its class methods
from utils.timeframes import TIMEFRAME_PATTERN, format_timestamp_to_iso # Assuming you have these
from services.market_service import MarketService # For type hinting and direct use if needed
from services.data_orchestrator import OHLCVBar # Import OHLCVBar for type hinting fetch_ohlcv return
from utils.response import make_error_response, make_success_response, make_highcharts_response

logger = logging.getLogger("market_blueprint") # Consistent logger name
market_blueprint = Blueprint("market", __name__, url_prefix="/api/market")


def _parse_int(name: str, value: Optional[str], default: Optional[int] = None) -> Optional[int]:
    """
    Helper function to parse a string value to an integer.
    Args:
        name (str): The name of the parameter (for error messages).
        value (Optional[str]): The string value to parse.
        default (Optional[int]): The default value to return if 'value' is None.
    Returns:
        Optional[int]: The parsed integer or the default value.
    Raises:
        ValueError: If 'value' is not None and cannot be converted to an integer.
    """
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
    This endpoint dynamically determines providers based on registered plugins and their capabilities.

    Query Parameters:
        market (str): The market type for which to list providers (e.g., "crypto", "stocks"). Required.

    Returns:
        JSON response with a list of provider names or an error message.
    """
    market_query: Optional[str] = request.args.get("market")
    if not market_query:
        logger.warning("/providers - Call missing 'market' query parameter.")
        return make_error_response("Missing 'market' query parameter", code=400)

    log_prefix = f"/providers (Market: {market_query}):"
    logger.info(f"{log_prefix} Request received.")

    try:
        # PluginLoader's methods are class methods, so we call them directly.
        # Ensure PluginLoader has been initialized (discovery run)
        if not PluginLoader.list_plugins(): # This also triggers discovery if not already run
            logger.warning(f"{log_prefix} PluginLoader has no plugins listed. Discovery might not have run or no plugins found.")
            # It's okay if discovery runs again here if it's idempotent.

        # 1. Determine the plugin_key of the CLASS that handles this market
        plugin_class_key = PluginLoader.get_plugin_key_for_market(market_query)

        if not plugin_class_key:
            logger.warning(f"{log_prefix} No plugin directly mapped to handle market '{market_query}'.")
            # As a fallback, check if the market_query itself is a plugin_key
            # (e.g. for a single-market plugin like "alpaca" where market="alpaca")
            if market_query.lower() in PluginLoader.list_plugins():
                plugin_class_key = market_query.lower()
                logger.info(f"{log_prefix} Using market query '{market_query}' as plugin_class_key.")
            else:
                logger.error(f"{log_prefix} No plugin configured or found for market '{market_query}'. Available plugin keys: {PluginLoader.list_plugins()}")
                return make_error_response(f"No plugin or providers could be determined for market '{market_query}'.", code=404)

        # 2. Get the plugin class using the determined key
        # Using the corrected method name: get_plugin_class_by_key
        plugin_class: Optional[Type[MarketPlugin]] = PluginLoader.get_plugin_class_by_key(plugin_class_key)

        if not plugin_class:
            logger.error(f"{log_prefix} Could not load plugin class for key '{plugin_class_key}' (intended for market: '{market_query}').")
            return make_error_response(f"Configuration error: Plugin class for market '{market_query}' (key: '{plugin_class_key}') is not loadable.", code=500)

        # 3. Call the class method to list providers supported by this specific plugin class
        if hasattr(plugin_class, 'list_configurable_providers') and callable(plugin_class.list_configurable_providers):
            try:
                providers_list: List[str] = plugin_class.list_configurable_providers()
            except Exception as e_list_providers:
                logger.error(f"{log_prefix} Error calling list_configurable_providers for plugin class '{plugin_class.__name__}': {e_list_providers}", exc_info=True)
                return make_error_response(f"Error retrieving providers from plugin for market '{market_query}'.", 500)

            if not providers_list:
                 logger.warning(f"{log_prefix} Plugin '{plugin_class_key}' for market '{market_query}' returned an empty list of configurable providers.")
                 return make_error_response(f"No specific providers listed by the plugin for market '{market_query}'.", code=404)

            logger.info(f"{log_prefix} Market '{market_query}' (handled by Plugin '{plugin_class_key}'): Found {len(providers_list)} configurable providers.")
            return make_success_response(data={"providers": sorted(list(set(providers_list)))})
        else:
            logger.error(f"{log_prefix} Plugin class '{plugin_class.__name__}' (key: '{plugin_class_key}') does not have a callable 'list_configurable_providers' method.")
            return make_error_response(f"Plugin for market '{market_query}' is not correctly configured to list its providers.", 501) # 501 Not Implemented

    except PluginError as e:
        logger.error(f"{log_prefix} PluginError encountered: {e}", exc_info=True)
        return make_error_response(str(e), code=500) 
    except Exception as e:
        logger.error(f"{log_prefix} Unexpected error: {e}", exc_info=True)
        return make_error_response(f"Could not determine providers for market '{market_query}' due to an internal server error.", code=500) # Changed to 500 from 502


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
        # Access the main MarketService instance from the app context
        svc: Optional[MarketService] = getattr(current_app, 'market_service', None)
        if not svc or not isinstance(svc, MarketService):
            logger.error(f"{log_prefix} MarketService not found or not correctly initialized on current_app.")
            return make_error_response("Internal server configuration error: MarketService unavailable.", code=500)

        # MarketService.get_symbols will internally use get_plugin_instance
        symbols_list: List[str] = await svc.get_symbols(market=market, provider=provider) # user_id can be added if needed
        logger.info(f"{log_prefix} Successfully fetched {len(symbols_list)} symbols.")
        return make_success_response(data={"symbols": symbols_list})

    except ValueError as e: # From MarketService if plugin/provider mapping or validation fails
        logger.error(f"{log_prefix} ValueError: {e}", exc_info=True)
        return make_error_response(f"Configuration error or invalid request for market '{market}' and provider '{provider}': {str(e)}", code=404)
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
    """
    Fetch OHLCV (Open, High, Low, Close, Volume) data for a given symbol.
    """
    market: Optional[str] = request.args.get("market")
    provider: Optional[str] = request.args.get("provider")
    symbol_param: Optional[str] = request.args.get("symbol")
    timeframe: str = request.args.get("timeframe", "1m") # Default to "1m"
    since_str: Optional[str] = request.args.get("since")
    until_str: Optional[str] = request.args.get("until") # Prefer 'until' for clarity
    if until_str is None:
        until_str = request.args.get("before") # Fallback to 'before'
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
        if limit_val is None: limit_val = default_api_limit # Should be set by default now
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

        # MarketService.fetch_ohlcv now returns List[OHLCVBar]
        ohlcv_bars: List[OHLCVBar] = await svc.fetch_ohlcv(
            market=market,
            provider=provider,
            symbol=symbol_param,
            timeframe=timeframe,
            since=since_ms,
            until=until_ms, 
            limit=limit_val
            # user_id can be added here if OHLCV access becomes user-specific
        )
        logger.info(f"{log_prefix} Successfully fetched {len(ohlcv_bars)} OHLCV bars from MarketService.")
        
        # Transform List[OHLCVBar] to Highcharts format here in the blueprint
        ohlc_for_chart: List[List[Any]] = []
        volume_for_chart: List[List[Any]] = []
        for bar in ohlcv_bars:
            ohlc_for_chart.append([bar['timestamp'], bar['open'], bar['high'], bar['low'], bar['close']])
            volume_for_chart.append([bar['timestamp'], bar['volume']])
            
        return make_highcharts_response(ohlc_for_chart, volume_for_chart)

    except ValueError as e_val: # From MarketService if params are invalid before plugin call
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