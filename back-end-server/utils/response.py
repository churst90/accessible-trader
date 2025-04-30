# utils/response.py
from quart import jsonify
import logging

logger = logging.getLogger("Response")


def make_response(success, data=None, error=None, code=200):
    """
    Create a standardized API response.
    :param success: Boolean indicating whether the request was successful.
    :param data: Optional data payload to include in the response.
    :param error: Optional error message or details.
    :param code: HTTP status code for the response.
    :return: A standardized JSON response.
    """
    response_payload = {
        "success": success,
        "data": data,
        "error": error,
    }

    # Log the response for better traceability
    if not success:
        logger.warning(f"API Response Error: {response_payload} | Status Code: {code}")
    else:
        logger.debug(f"API Response Success: {response_payload} | Status Code: {code}")

    return jsonify(response_payload), code


def make_error_response(error_message, code=400, details=None):
    """
    Create a standardized error response.
    :param error_message: The main error message.
    :param code: HTTP status code for the error response.
    :param details: Optional detailed error information.
    :return: A standardized JSON error response.
    """
    error_payload = {
        "success": False,
        "data": None,
        "error": {
            "message": error_message,
            "details": details,
        },
    }

    # Log the error for debugging and auditing
    logger.error(f"API Error Response: {error_payload} | Status Code: {code}")

    return jsonify(error_payload), code


def make_success_response(data=None, code=200):
    """
    Create a standardized success response.
    :param data: Optional data payload to include in the response.
    :param code: HTTP status code for the success response.
    :return: A standardized JSON success response.
    """
    success_payload = {
        "success": True,
        "data": data,
        "error": None,
    }

    # Log the successful response
    logger.info(f"API Success Response: {success_payload} | Status Code: {code}")

    return jsonify(success_payload), code


def make_highcharts_response(ohlc, volume, code=200):
    """
    Create a standardized response for Highcharts.
    :param ohlc: List of OHLC data arrays.
    :param volume: List of volume data arrays.
    :param code: HTTP status code.
    :return: JSON response for Highcharts.
    """
    response_payload = {
        "success": True,
        "data": {
            "ohlc": ohlc,
            "volume": volume,
        },
        "error": None,
    }

    # Log the Highcharts-specific response
    logger.info(f"Highcharts Response Prepared with {len(ohlc)} OHLC points and {len(volume)} Volume points.")

    return jsonify(response_payload), code
