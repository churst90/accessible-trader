# blueprints/websocket.py

import logging
import asyncio
import json
from typing import List
from urllib.parse import parse_qs

from quart import Blueprint, websocket
from plugins import PluginLoader
from services.subscription_manager import subscription_manager
from services.ws_registry import register, unregister
from utils.timeframes import TIMEFRAME_PATTERN

logger = logging.getLogger("WebSocketBlueprint")
_PING_INTERVAL = 25  # seconds

websocket_blueprint = Blueprint("websocket", __name__, url_prefix="/api/ws")


@websocket_blueprint.websocket("/subscribe")
async def subscribe_ws():
    # 1) track for shutdown
    await register(websocket)

    # 2) parse & validate query params
    raw_qs    = websocket.scope.get("query_string", b"").decode()
    qs        = parse_qs(raw_qs)
    market    = qs.get("market",   [None])[0]
    provider  = qs.get("provider", [None])[0]
    symbols_p = qs.get("symbols",  [None])[0]
    timeframe = qs.get("timeframe",[ "1m"])[0]
    since_str = qs.get("since",    [None])[0]
    since     = int(since_str) if since_str is not None else None

    errors: List[str] = []
    if not (market and provider and symbols_p):
        errors.append("Missing one of: market, provider, symbols")
    if not TIMEFRAME_PATTERN.match(timeframe):
        errors.append(f"Invalid timeframe '{timeframe}'")

    # validate plugin/provider
    if market == "crypto":
        try:
            crypto = PluginLoader.load_plugin("crypto")
            if provider not in await crypto.get_exchanges():
                errors.append(f"Unknown crypto provider '{provider}'")
        except Exception as e:
            errors.append(f"Crypto plugin error: {e}")
    else:
        try:
            plugin = PluginLoader.load_plugin(provider)
            if market not in getattr(plugin, "supported_markets", []):
                errors.append(f"Provider '{provider}' does not support market '{market}'")
        except Exception as e:
            errors.append(f"Provider '{provider}' not found")

    # split symbols
    symbols: List[str] = []
    if symbols_p:
        symbols = [s.strip() for s in symbols_p.split(",") if s.strip()]
        if not symbols:
            errors.append("No valid symbols provided")

    if errors:
        await websocket.send_json({
            "type":    "error",
            "payload": {"message": "Invalid WebSocket parameters", "details": errors}
        })
        await websocket.close(code=4000)
        logger.warning("WS subscribe rejected: %s", errors)
        return

    logger.info(
        "WS subscribe accepted: market=%s, provider=%s, symbols=%s, timeframe=%s, since=%s",
        market, provider, symbols, timeframe, since
    )

    # 3) subscribe each symbol, passing along `since`
    for symbol in symbols:
        try:
            await subscription_manager.subscribe(
                websocket, market, provider, symbol, timeframe, since
            )
        except Exception as e:
            logger.error(
                "Subscription error for %s/%s/%s/%s: %s",
                market, provider, symbol, timeframe, e, exc_info=True
            )
            await websocket.send_json({
                "type":      "error",
                "symbol":    symbol,
                "timeframe": timeframe,
                "payload":   {"message": f"Subscription failed for {symbol}", "details": str(e)}
            })
            await websocket.close(code=4001)
            return

    # 4) heartbeat + ping/pong
    last_pong = asyncio.get_event_loop().time()
    try:
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_json(), timeout=_PING_INTERVAL)
                now = asyncio.get_event_loop().time()
                # explicit pong or any message resets timer
                last_pong = now
            except asyncio.TimeoutError:
                now = asyncio.get_event_loop().time()
                if now - last_pong >= _PING_INTERVAL:
                    await websocket.send_json({"type": "ping"})
                    last_pong = now
            except Exception:
                break
    finally:
        # 5) clean up
        await unregister(websocket)
        for symbol in symbols:
            try:
                await subscription_manager.unsubscribe(websocket, market, provider, symbol, timeframe)
            except Exception:
                logger.exception(
                    "Error during websocket unsubscribe for %s/%s/%s/%s",
                    market, provider, symbol, timeframe
                )
        logger.info("WebSocket handler completed and unsubscribed.")
