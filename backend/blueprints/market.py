from quart import Blueprint, request
from services.market_service import MarketService
from utils.response import make_response, make_error_response, make_success_response

market_blueprint = Blueprint("market", __name__, url_prefix="/market")

@market_blueprint.route("/get_exchanges", methods=["GET"])
async def exchanges():
    market = request.args.get("market")
    if not market:
        return make_error_response("Missing 'market' parameter", code=400)

    try:
        service = MarketService(market)
        exchanges = await service.get_exchanges()  # now async
        if not exchanges:
            return make_error_response("No exchanges found for the specified market", code=404)
        return make_success_response(data={"exchanges": exchanges})
    except ValueError as ve:
        return make_error_response(str(ve), code=400)
    except Exception as e:
        return make_error_response(f"Failed to retrieve exchanges: {str(e)}", code=500)


@market_blueprint.route("/get_symbols", methods=["GET"])
async def symbols():
    market = request.args.get("market")
    exchange = request.args.get("exchange")

    if not market or not exchange:
        return make_error_response(
            "Missing required parameters: 'market' and 'exchange' are mandatory", code=400
        )

    try:
        service = MarketService(market)
        symbols = await service.get_symbols(exchange)
        if not symbols:
            return make_error_response("No symbols found for the specified exchange", code=404)
        return make_success_response(data={"symbols": symbols})
    except ValueError as ve:
        return make_error_response(str(ve), code=400)
    except Exception as e:
        return make_error_response(f"Failed to retrieve symbols: {str(e)}", code=500)


@market_blueprint.route("/fetch_ohlcv", methods=["GET"])
async def ohlcv():
    market = request.args.get("market")
    exchange = request.args.get("exchange")
    symbol = request.args.get("symbol")
    timeframe = request.args.get("timeframe", "1h")
    since = request.args.get("since")
    limit = request.args.get("limit")

    if not market or not exchange or not symbol:
        return make_error_response(
            "Missing required parameters: 'market', 'exchange', and 'symbol' are mandatory", code=400
        )

    try:
        service = MarketService(market)
        since = int(since) if since else None
        limit = int(limit) if limit else None

        ohlcv_data = await service.fetch_ohlcv(exchange, symbol, timeframe, since, limit)
        if not ohlcv_data:
            return make_error_response("No OHLCV data found for the specified parameters", code=404)

        formatted_data = service.format_for_highcharts(ohlcv_data)
        return make_success_response(data=formatted_data)
    except ValueError as ve:
        return make_error_response(str(ve), code=400)
    except Exception as e:
        return make_error_response(f"Failed to fetch OHLCV data: {str(e)}", code=500)
