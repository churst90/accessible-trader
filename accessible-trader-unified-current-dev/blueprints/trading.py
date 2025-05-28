# blueprints/trading.py

import logging
from quart import Blueprint, request, g, current_app
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from typing import Dict, Any, Optional, List

# App-specific imports
from utils.response import make_success_response, make_error_response
from middleware.auth_middleware import jwt_required
from services.market_service import MarketService
from plugins.base import (
    MarketPlugin,
    PluginError,
    AuthenticationPluginError,
    PluginFeatureNotSupportedError,
    Order,
    # Position, # Not directly used in this file's type hints but good to be aware of
    # Balance,  # Not directly used in this file's type hints
)
from app_extensions.user_configs_db_setup import user_configs_db_session_scope
from models.user_config_models import UserApiCredential, TradeLog

logger = logging.getLogger("TradingBlueprint")
trading_blueprint = Blueprint("trading", __name__, url_prefix="/api/trading")

async def _log_manual_trade_action(
    user_id: int,
    credential_id: int,
    event_type: str,
    symbol: str,
    exchange_order_id: Optional[str] = None,
    client_order_id: Optional[str] = None,
    order_type: Optional[str] = None,
    side: Optional[str] = None,
    price: Optional[float] = None,
    quantity: Optional[float] = None,
    status: Optional[str] = None,
    notes: Optional[str] = None,
    fee_cost: Optional[float] = None,
    fee_currency: Optional[str] = None
) -> None:
    """
    Asynchronously logs manual trading actions (or their attempts) to the TradeLog table.

    This helper function encapsulates the logic for creating and saving a trade log entry
    within an asynchronous database session.

    Args:
        user_id: The ID of the user performing the action.
        credential_id: The ID of the UserApiCredential used for this action.
        event_type: A string describing the event (e.g., "MANUAL_ORDER_PLACED_SUCCESS",
                    "MANUAL_ORDER_CANCEL_ATTEMPT", "MANUAL_ORDER_PLACEMENT_PLUGIN_ERROR").
        symbol: The trading symbol involved.
        exchange_order_id: The order ID from the exchange, if available.
        client_order_id: The client-generated order ID, if any.
        order_type: The type of order (e.g., "market", "limit").
        side: The side of the order ("buy" or "sell").
        price: The price of the order, especially for limit orders or filled market orders.
        quantity: The quantity of the order.
        status: The status of the order or event (e.g., "submitted", "filled", "cancelled", "error").
        notes: Additional notes or context for the log entry.
        fee_cost: The cost of the fee, if applicable.
        fee_currency: The currency of the fee, if applicable.
    """
    log_prefix = f"LogManualTrade (User:{user_id}, CredID:{credential_id}, Sym:{symbol}, Event:{event_type}):"
    logger.debug(f"{log_prefix} Attempting to log action.")
    try:
        async with user_configs_db_session_scope() as session:  # Use async context manager
            log_entry = TradeLog(
                user_id=user_id,
                bot_id=None,  # Explicitly None for manual trades/actions
                credential_id=credential_id,
                exchange_order_id=exchange_order_id,
                client_order_id=client_order_id,
                symbol=symbol,
                order_type=order_type or "N/A",  # Provide default if None
                side=side or "N/A",
                price=price, # Can be None
                quantity=quantity, # Can be None for certain actions
                status=status or event_type,  # Use event_type as fallback status
                commission_amount=fee_cost,
                commission_asset=fee_currency,
                notes=f"Event: {event_type}. {notes if notes else ''}".strip()
            )
            session.add(log_entry)
            # Commit is handled by the user_configs_db_session_scope on successful exit.
            # No explicit await session.commit() needed here.
            # If you need the ID of log_entry immediately, you might need await session.flush().
            logger.info(f"{log_prefix} Manual trade event logged successfully for order {exchange_order_id or 'N/A'}.")
    except Exception as e:
        # Rollback is handled by user_configs_db_session_scope on exception.
        logger.error(f"{log_prefix} Failed to log manual trade event: {e}", exc_info=True)
        # This logging failure should not typically interrupt the main API response flow,
        # but the error is recorded.

async def _get_authenticated_plugin_for_trading(
    market_category: str, requested_provider_name: str, user_id: int, credential_id: int
) -> MarketPlugin:
    """
    Retrieves and verifies an authenticated MarketPlugin instance suitable for trading.

    This helper function:
    1. Fetches the specified UserApiCredential from the database.
    2. Verifies that the credential belongs to the authenticated user and matches the requested provider.
    3. Obtains a MarketPlugin instance from MarketService, configured with these credentials.
    4. Checks if the plugin instance supports the general "trading_api" feature.

    Args:
        market_category: The general market category (e.g., "crypto", "us_equity")
                         to help MarketService select the correct plugin class.
        requested_provider_name: The specific provider the user intends to trade with
                                 (e.g., "binance", "alpaca").
        user_id: The ID of the authenticated user.
        credential_id: The ID of the UserApiCredential to be used.

    Returns:
        MarketPlugin: An initialized and authenticated MarketPlugin instance.

    Raises:
        AuthenticationPluginError: If credential verification fails or credentials
                                   do not match the provider.
        PluginError: If MarketService is unavailable or plugin instantiation fails.
        PluginFeatureNotSupportedError: If the instantiated plugin does not support
                                        the "trading_api" feature.
    """
    log_prefix = f"GetAuthPlugin (User:{user_id}, Provider:{requested_provider_name}, CredID:{credential_id}):"
    svc: MarketService = getattr(current_app, "market_service")
    if not svc:
        logger.error(f"{log_prefix} MarketService not available.")
        raise PluginError("MarketService unavailable", provider_id=requested_provider_name)

    is_testnet_for_plugin: bool
    provider_service_name_from_cred: str

    try:
        async with user_configs_db_session_scope() as session: # Async DB access
            stmt = select(UserApiCredential).where(
                UserApiCredential.credential_id == credential_id,
                UserApiCredential.user_id == user_id
            )
            result = await session.execute(stmt)
            credential = result.scalars().first()

            if not credential:
                logger.warning(f"{log_prefix} Credential ID {credential_id} not found or not owned by user.")
                raise AuthenticationPluginError(requested_provider_name, f"Credential ID {credential_id} not found or not owned by user.") # [cite: 1429]

            if credential.service_name.lower() != requested_provider_name.lower():
                logger.warning(f"{log_prefix} Credential ID {credential_id} is for service '{credential.service_name}', but trading requested for '{requested_provider_name}'.")
                raise AuthenticationPluginError(requested_provider_name, f"Credential ID {credential_id} is for service '{credential.service_name}', not '{requested_provider_name}'.") # [cite: 1430]
            
            is_testnet_for_plugin = credential.is_testnet
            provider_service_name_from_cred = credential.service_name # Use the exact name from validated credential
            logger.debug(f"{log_prefix} Credential validated. Service: {provider_service_name_from_cred}, Testnet: {is_testnet_for_plugin}.")

    except AuthenticationPluginError: # Re-raise if already this type
        raise
    except Exception as e: # Catch other potential DB or logic errors during credential fetch
        logger.error(f"{log_prefix} Error verifying credential: {e}", exc_info=True)
        raise AuthenticationPluginError(requested_provider_name, f"Credential verification failed: {e}") from e
        
    # Get plugin instance using the validated provider name from the credential
    plugin_instance = await svc.get_plugin_instance(
        market=market_category, # The general market category
        provider=provider_service_name_from_cred, # The specific provider from the credential
        user_id=str(user_id), # MarketService expects user_id as string for its internal key fetching
        is_testnet_override=is_testnet_for_plugin
    )
    
    if not plugin_instance: # Should be caught by MarketService, but defensive check
        logger.error(f"{log_prefix} Failed to initialize plugin for {provider_service_name_from_cred} via MarketService.")
        raise PluginError(f"Failed to initialize plugin for {provider_service_name_from_cred}", provider_id=provider_service_name_from_cred)

    supported_features = await plugin_instance.get_supported_features()
    if not supported_features.get("trading_api"): # [cite: 70]
        logger.warning(f"{log_prefix} Plugin {plugin_instance.plugin_key} for provider {provider_service_name_from_cred} does not support 'trading_api'.")
        raise PluginFeatureNotSupportedError(plugin_instance.plugin_key, provider_service_name_from_cred, "trading_api") # [cite: 4]
    
    logger.info(f"{log_prefix} Authenticated plugin instance obtained for {provider_service_name_from_cred}.")
    return plugin_instance

@trading_blueprint.route("/order", methods=["POST"])
@jwt_required
async def place_manual_order_endpoint() -> tuple[Dict[str, Any], int]:
    """
    Places a manual trading order for the authenticated user.

    Requires JWT authentication. The request body must be JSON and include:
    - `credential_id` (int): ID of a `UserApiCredential` belonging to the user.
    - `market` (str): The general market category (e.g., "crypto", "us_equity").
                      This helps `MarketService` select the appropriate plugin class.
    - `provider` (str): The specific exchange/provider name (e.g., "binance", "alpaca").
                        This must match the `service_name` in the `UserApiCredential`.
    - `symbol` (str): The trading symbol (e.g., "BTC/USDT", "AAPL").
    - `side` (str): "buy" or "sell".
    - `order_type` (str): "market" or "limit".
    - `amount` (float): The quantity of the asset to trade.
    - `price` (float, optional): Required if `order_type` is "limit".
    - `params` (dict, optional): Exchange-specific parameters (e.g., `timeInForce`,
                                 `clientOrderId`, or `type` for derivatives if using CCXT).

    Returns:
        JSON response with the order details upon success, or an error message.
    """
    user_id = g.user["id"]
    data = await request.get_json()
    if not data:
        return make_error_response("Missing JSON payload", code=400)

    log_prefix = f"PlaceOrderAPI (User:{user_id}):"
    logger.info(f"{log_prefix} Request received: {data}")

    required_fields = ["credential_id", "market", "provider", "symbol", "side", "order_type", "amount"]
    missing = [f for f in required_fields if f not in data]
    if missing:
        return make_error_response(f"Missing required fields: {', '.join(missing)}", code=400) # [cite: 1435]

    try:
        credential_id = int(data["credential_id"]) # [cite: 1436]
        market_category = data["market"] # [cite: 1433]
        provider_name = data["provider"] # [cite: 1433]
        symbol = data["symbol"] # [cite: 1433]
        side = data["side"].lower() # [cite: 1433]
        order_type = data["order_type"].lower() # [cite: 1433]
        amount = float(data["amount"]) # [cite: 1433]
        price = float(data["price"]) if data.get("price") is not None and order_type == "limit" else None # [cite: 1433]
        plugin_passthrough_params = data.get("params", {}) # [cite: 1434, 1436]

        if side not in ["buy", "sell"]:
            return make_error_response("Invalid 'side', must be 'buy' or 'sell'.", code=400)
        if order_type not in ["market", "limit"]: # Can be extended later
            return make_error_response("Invalid 'order_type', must be 'market' or 'limit'.", code=400)
        if order_type == "limit" and price is None:
            return make_error_response("Price is required for limit orders.", code=400) # [cite: 1437]
        if amount <= 0:
            return make_error_response("Amount must be a positive number.", code=400) # [cite: 1437]

        plugin = await _get_authenticated_plugin_for_trading(market_category, provider_name, user_id, credential_id)
        
        # The plugin's place_order method is expected to return an Order-like dictionary.
        order_result: Order = await plugin.place_order(
            symbol=symbol,
            order_type=order_type,
            side=side,
            amount=amount,
            price=price,
            params=plugin_passthrough_params # [cite: 1438]
        )
        
        if not order_result or not order_result.get("id"):
            logger.error(f"{log_prefix} Invalid or empty order response from plugin {provider_name} for symbol {symbol}: {order_result}")
            # Log the attempt even if the plugin didn't return a full order ID
            await _log_manual_trade_action( # Ensure this is awaited
                user_id=user_id, credential_id=credential_id,
                event_type="MANUAL_ORDER_PLACEMENT_FAILED_PLUGIN_RESPONSE", symbol=symbol,
                order_type=order_type, side=side, price=price, quantity=amount,
                status="FAILED_PLUGIN_RESPONSE",
                notes=f"Plugin response: {str(order_result)[:200]}"
            ) # [cite: 1439]
            return make_error_response("Failed to place order: Invalid response from provider.", code=502)

        # Log successful placement attempt
        await _log_manual_trade_action( # Ensure this is awaited
            user_id=user_id, credential_id=credential_id,
            event_type="MANUAL_ORDER_PLACED_SUCCESS", symbol=symbol,
            exchange_order_id=order_result.get("id"),
            client_order_id=order_result.get("client_order_id"), # [cite: 10]
            order_type=order_type, side=side,
            price=order_result.get("price", price), # Use reported price if available
            quantity=order_result.get("amount", amount), # Use reported amount
            status=order_result.get("status", "submitted"), # [cite: 10]
            fee_cost=order_result.get("fee", {}).get("cost"), # [cite: 12]
            fee_currency=order_result.get("fee", {}).get("currency"), # [cite: 12]
            notes=f"Order placed via API. Exchange info: {str(order_result.get('info', {}))[:100]}"
        ) # [cite: 1441]
        logger.info(f"{log_prefix} Successfully placed order {order_result.get('id')} for {symbol} on {provider_name}.")
        return make_success_response(data={"order": order_result}, code=201)

    except (ValueError, TypeError) as e_val: 
        logger.warning(f"{log_prefix} Input validation error: {e_val}", exc_info=False)
        return make_error_response(f"Invalid input: {e_val}", code=400)
    except AuthenticationPluginError as e_auth:
        logger.warning(f"{log_prefix} Authentication error for provider {data.get('provider','N/A') if data else 'N/A'}: {e_auth}")
        return make_error_response(str(e_auth), code=403) 
    except PluginFeatureNotSupportedError as e_feat:
        logger.warning(f"{log_prefix} Feature not supported by provider {data.get('provider','N/A') if data else 'N/A'}: {e_feat}")
        return make_error_response(str(e_feat), code=501)
    except PluginError as e_plugin: # Catch other plugin related errors
        logger.error(f"{log_prefix} Plugin error with provider {data.get('provider','N/A') if data else 'N/A'}: {e_plugin}", exc_info=True)
        await _log_manual_trade_action( # Ensure this is awaited
            user_id=user_id, credential_id=data.get("credential_id", -1) if data else -1, # type: ignore
            event_type="MANUAL_ORDER_PLACEMENT_PLUGIN_ERROR", symbol=data.get("symbol","N/A") if data else "N/A",
            order_type=data.get("order_type","N/A") if data else "N/A", side=data.get("side","N/A") if data else "N/A",
            price=data.get("price") if data else None, quantity=data.get("amount") if data else None, # type: ignore
            status="ERROR_PLUGIN", notes=str(e_plugin)
        ) # [cite: 1443]
        return make_error_response(f"Error with provider {data.get('provider','N/A') if data else 'N/A'}: {str(e_plugin)}", code=502)
    except Exception as e_unexpected:
        logger.error(f"{log_prefix} Unexpected error: {e_unexpected}", exc_info=True)
        await _log_manual_trade_action( # Ensure this is awaited
            user_id=user_id, credential_id=data.get("credential_id", -1) if data else -1, # type: ignore
            event_type="MANUAL_ORDER_PLACEMENT_UNEXPECTED_ERROR", symbol=data.get("symbol","N/A") if data else "N/A",
            order_type=data.get("order_type","N/A") if data else "N/A", side=data.get("side","N/A") if data else "N/A",
            price=data.get("price") if data else None, quantity=data.get("amount") if data else None, # type: ignore
            status="ERROR_UNEXPECTED", notes=str(e_unexpected)
        ) # [cite: 1444]
        return make_error_response("An unexpected server error occurred.", code=500)


@trading_blueprint.route("/orders/<order_id_from_path>", methods=["GET"])
@jwt_required
async def get_manual_order_status_endpoint(order_id_from_path: str) -> tuple[Dict[str, Any], int]:
    """
    Retrieves the status of a specific manual order for the authenticated user.

    Requires JWT authentication. Query parameters:
    - `credential_id` (int): The UserApiCredential ID used when the order was placed.
    - `market` (str): The general market category.
    - `provider` (str): The specific exchange/provider name.
    - `symbol` (str, optional): The trading symbol (required by some exchanges to fetch order status).
    """
    user_id = g.user["id"]
    market_category = request.args.get("market")
    provider_name = request.args.get("provider")
    symbol = request.args.get("symbol") # Optional for plugin, but can be required
    
    log_prefix = f"GetOrderStatusAPI (User:{user_id}, OrderID:{order_id_from_path}, Provider:{provider_name}):" # [cite: 1445]
    
    if not all([market_category, provider_name]):
        return make_error_response("Missing 'market' or 'provider' query parameters.", code=400)

    try:
        credential_id_str = request.args.get("credential_id")
        if not credential_id_str:
            return make_error_response("Missing 'credential_id' query parameter.", code=400) # [cite: 1445]
        credential_id = int(credential_id_str) # [cite: 1445]
    except ValueError:
        return make_error_response("'credential_id' must be an integer.", code=400) # [cite: 1445]

    try:
        plugin = await _get_authenticated_plugin_for_trading(market_category, provider_name, user_id, credential_id)
        
        # The plugin's get_order_status is expected to return an Order-like dictionary.
        order_status: Order = await plugin.get_order_status(order_id_from_path, symbol=symbol) # [cite: 1445]
        
        logger.info(f"{log_prefix} Successfully retrieved status for order {order_id_from_path}.")
        return make_success_response(data={"order": order_status}) # [cite: 1446]

    except (ValueError, TypeError) as e_val:
        logger.warning(f"{log_prefix} Input validation error: {e_val}", exc_info=False)
        return make_error_response(f"Invalid input: {e_val}", code=400)
    except AuthenticationPluginError as e_auth:
        logger.warning(f"{log_prefix} Authentication error: {e_auth}")
        return make_error_response(str(e_auth), code=403)
    except PluginFeatureNotSupportedError as e_feat:
        logger.warning(f"{log_prefix} Feature not supported: {e_feat}")
        return make_error_response(str(e_feat), code=501)
    except PluginError as e_plugin:
        logger.error(f"{log_prefix} Plugin error: {e_plugin}", exc_info=True)
        return make_error_response(f"Error with provider {provider_name}: {str(e_plugin)}", code=502)
    except Exception as e_unexpected:
        logger.error(f"{log_prefix} Unexpected error: {e_unexpected}", exc_info=True) # [cite: 1450]
        return make_error_response("An unexpected server error occurred.", code=500)


@trading_blueprint.route("/orders/<order_id_from_path>", methods=["DELETE"])
@jwt_required
async def cancel_manual_order_endpoint(order_id_from_path: str) -> tuple[Dict[str, Any], int]:
    """
    Cancels a specific manual order for the authenticated user.

    Requires JWT authentication. Query parameters:
    - `credential_id` (int): The UserApiCredential ID used.
    - `market` (str): The general market category.
    - `provider` (str): The specific exchange/provider name.
    - `symbol` (str, optional): The trading symbol (required by some exchanges to cancel).
    """
    user_id = g.user["id"]
    market_category = request.args.get("market") # [cite: 1447]
    provider_name = request.args.get("provider") # [cite: 1447]
    symbol = request.args.get("symbol") # [cite: 1447]

    log_prefix = f"CancelOrderAPI (User:{user_id}, OrderID:{order_id_from_path}, Provider:{provider_name}):" # [cite: 1448]

    if not all([market_category, provider_name]):
        return make_error_response("Missing 'market' or 'provider' query parameters.", code=400)

    try:
        credential_id_str = request.args.get("credential_id")
        if not credential_id_str:
            return make_error_response("Missing 'credential_id' query parameter.", code=400) # [cite: 1447]
        credential_id = int(credential_id_str) # [cite: 1447]
    except ValueError:
        return make_error_response("'credential_id' must be an integer.", code=400) # [cite: 1447]

    try:
        plugin = await _get_authenticated_plugin_for_trading(market_category, provider_name, user_id, credential_id)
        
        # The plugin's cancel_order method typically returns a dict with info,
        # or the updated order structure.
        cancel_result: Dict[str, Any] = await plugin.cancel_order(order_id_from_path, symbol=symbol) # [cite: 1448]
        
        # Determine symbol for logging if not provided in request and available in response
        log_symbol = symbol or (cancel_result.get('symbol') if isinstance(cancel_result, dict) else "N/A")
        
        await _log_manual_trade_action( # Ensure this is awaited
            user_id=user_id, credential_id=credential_id,
            event_type="MANUAL_ORDER_CANCELLED_SUCCESS", symbol=str(log_symbol), # Ensure symbol is str
            exchange_order_id=order_id_from_path,
            status=cancel_result.get('status', 'cancelled_attempt') if isinstance(cancel_result, dict) else 'cancelled_attempt', # [cite: 1448]
            notes=f"Cancellation result: {str(cancel_result)[:200]}"
        )
        logger.info(f"{log_prefix} Successfully initiated cancellation for order {order_id_from_path}.")
        return make_success_response(data={"cancellation_details": cancel_result}) # [cite: 1449]

    except (ValueError, TypeError) as e_val:
        logger.warning(f"{log_prefix} Input validation error: {e_val}", exc_info=False)
        return make_error_response(f"Invalid input: {e_val}", code=400)
    except AuthenticationPluginError as e_auth:
        logger.warning(f"{log_prefix} Authentication error: {e_auth}")
        return make_error_response(str(e_auth), code=403)
    except PluginFeatureNotSupportedError as e_feat:
        logger.warning(f"{log_prefix} Feature not supported: {e_feat}")
        return make_error_response(str(e_feat), code=501)
    except PluginError as e_plugin: # Catch other plugin related errors
        logger.error(f"{log_prefix} Plugin error: {e_plugin}", exc_info=True)
        await _log_manual_trade_action( # Ensure this is awaited
            user_id=user_id, credential_id=credential_id,
            event_type="MANUAL_ORDER_CANCEL_PLUGIN_ERROR", symbol=str(symbol or "N/A"),
            exchange_order_id=order_id_from_path, status="ERROR_PLUGIN", notes=str(e_plugin)
        )
        return make_error_response(f"Error with provider {provider_name}: {str(e_plugin)}", code=502)
    except Exception as e_unexpected:
        logger.error(f"{log_prefix} Unexpected error: {e_unexpected}", exc_info=True) # [cite: 1450]
        await _log_manual_trade_action( # Ensure this is awaited
            user_id=user_id, credential_id=credential_id,
            event_type="MANUAL_ORDER_CANCEL_UNEXPECTED_ERROR", symbol=str(symbol or "N/A"),
            exchange_order_id=order_id_from_path, status="ERROR_UNEXPECTED", notes=str(e_unexpected)
        )
        return make_error_response("An unexpected server error occurred.", code=500)


@trading_blueprint.route("/balances", methods=["GET"])
@jwt_required
async def get_account_balances_endpoint() -> tuple[Dict[str, Any], int]:
    """
    Retrieves account balances for the authenticated user from a specific provider.

    Requires JWT authentication. Query parameters:
    - `credential_id` (int): The UserApiCredential ID to use.
    - `market` (str): The general market category.
    - `provider` (str): The specific exchange/provider name.
    """
    user_id = g.user["id"]
    market_category = request.args.get("market") # [cite: 1451]
    provider_name = request.args.get("provider") # [cite: 1451]
    
    log_prefix = f"GetBalancesAPI (User:{user_id}, Provider:{provider_name}):" # [cite: 1451]

    if not all([market_category, provider_name]):
        return make_error_response("Missing 'market' or 'provider' query parameters.", code=400) # [cite: 1451]

    try:
        credential_id_str = request.args.get("credential_id")
        if not credential_id_str:
            return make_error_response("Missing 'credential_id' query parameter.", code=400) # [cite: 1451]
        credential_id = int(credential_id_str) # [cite: 1451]
    except ValueError:
        return make_error_response("'credential_id' must be an integer.", code=400) # [cite: 1451]

    try:
        plugin = await _get_authenticated_plugin_for_trading(market_category, provider_name, user_id, credential_id)
        
        # The plugin's get_account_balance is expected to return Dict[str, Balance]
        balances: Dict[str, Any] = await plugin.get_account_balance() # [cite: 1451]
        
        logger.info(f"{log_prefix} Successfully retrieved account balances from {provider_name}.")
        return make_success_response(data={"balances": balances}) # [cite: 1451]

    except AuthenticationPluginError as e_auth:
        logger.warning(f"{log_prefix} Authentication error: {e_auth}")
        return make_error_response(str(e_auth), code=403)
    except PluginFeatureNotSupportedError as e_feat:
        logger.warning(f"{log_prefix} Feature not supported: {e_feat}")
        return make_error_response(str(e_feat), code=501)
    except PluginError as e_plugin:
        logger.error(f"{log_prefix} Plugin error: {e_plugin}", exc_info=True)
        return make_error_response(f"Error with provider {provider_name}: {str(e_plugin)}", code=502)
    except Exception as e_unexpected:
        logger.error(f"{log_prefix} Unexpected error: {e_unexpected}", exc_info=True) # [cite: 1452]
        return make_error_response("An unexpected server error occurred.", code=500)


@trading_blueprint.route("/positions", methods=["GET"])
@jwt_required
async def get_open_positions_endpoint() -> tuple[Dict[str, Any], int]:
    """
    Retrieves open trading positions for the authenticated user from a specific provider.

    Requires JWT authentication. Query parameters:
    - `credential_id` (int): The UserApiCredential ID to use.
    - `market` (str): The general market category.
    - `provider` (str): The specific exchange/provider name.
    - `symbols` (str, optional): Comma-separated list of symbols to filter positions for.
                                If not provided, fetches all open positions.
    """
    user_id = g.user["id"]
    market_category = request.args.get("market") # [cite: 1453]
    provider_name = request.args.get("provider") # [cite: 1453]
    symbols_str = request.args.get("symbols") # [cite: 1453]
    symbols_list: Optional[List[str]] = [s.strip().upper() for s in symbols_str.split(',')] if symbols_str else None # [cite: 1453]

    log_prefix = f"GetPositionsAPI (User:{user_id}, Provider:{provider_name}, Symbols:{symbols_str or 'All'}):" # [cite: 1453]

    if not all([market_category, provider_name]):
        return make_error_response("Missing 'market' or 'provider' query parameters.", code=400) # [cite: 1453]

    try:
        credential_id_str = request.args.get("credential_id")
        if not credential_id_str:
            return make_error_response("Missing 'credential_id' query parameter.", code=400) # [cite: 1453]
        credential_id = int(credential_id_str) # [cite: 1453]
    except ValueError:
        return make_error_response("'credential_id' must be an integer.", code=400) # [cite: 1453]

    try:
        plugin = await _get_authenticated_plugin_for_trading(market_category, provider_name, user_id, credential_id)
        
        # The plugin's get_open_positions is expected to return List[Position]
        positions: List[Dict[str,Any]] = await plugin.get_open_positions(symbols=symbols_list) # [cite: 1453]
        
        logger.info(f"{log_prefix} Successfully retrieved {len(positions)} open positions from {provider_name}.")
        return make_success_response(data={"positions": positions}) # [cite: 1453]

    except AuthenticationPluginError as e_auth:
        logger.warning(f"{log_prefix} Authentication error: {e_auth}")
        return make_error_response(str(e_auth), code=403)
    except PluginFeatureNotSupportedError as e_feat: # [cite: 1454]
        logger.warning(f"{log_prefix} Feature not supported: {e_feat}")
        return make_error_response(str(e_feat), code=501)
    except PluginError as e_plugin:
        logger.error(f"{log_prefix} Plugin error: {e_plugin}", exc_info=True)
        return make_error_response(f"Error with provider {provider_name}: {str(e_plugin)}", code=502)
    except Exception as e_unexpected:
        logger.error(f"{log_prefix} Unexpected error: {e_unexpected}", exc_info=True) # [cite: 1454]
        return make_error_response("An unexpected server error occurred.", code=500)