# utils/timeframes.py

import re
import logging # Added for logging in normalize_timeframe_ccxt if we re-add it
from datetime import datetime, timezone # Added datetime, timezone
from typing import Dict, Tuple, Optional # Added Optional

logger = logging.getLogger(__name__) # Added logger

# Regular expression to match valid timeframe strings like "5m", "1h", "2d", "1w", "1M", "1y".
# It captures the numeric multiplier and the unit character.
TIMEFRAME_PATTERN = re.compile(r'^(\d+)([mhdwMy])$')

# Dictionary mapping timeframe units to their duration in milliseconds.
UNIT_MS: Dict[str, int] = {
    'm':    60_000,          # Minute
    'h': 3_600_000,         # Hour
    'd': 86_400_000,        # Day
    'w': 604_800_000,       # Week (7 days)
    'M': 2_592_000_000,     # Month (approx 30 days)
    'y': 31_536_000_000,   # Year (approx 365 days)
}

# Dictionary mapping timeframe units to their duration in seconds.
UNIT_SEC: Dict[str, int] = {k: v // 1000 for k, v in UNIT_MS.items()}


def _parse_timeframe_str(tf_str: str) -> Tuple[int, str, int]:
    """
    Parses a timeframe string (e.g., "5m", "1h", "1d").

    This function validates the input string against the TIMEFRAME_PATTERN
    and calculates the total duration in milliseconds based on the multiplier
    and unit.

    Args:
        tf_str: The timeframe string to parse.

    Returns:
        A tuple containing:
            - int: The numeric multiplier (e.g., 5 for "5m").
            - str: The unit character (e.g., 'm' for "5m").
            - int: The total duration of the timeframe in milliseconds.

    Raises:
        ValueError: If the timeframe string format is invalid, the multiplier
                    is not positive, or the unit is unsupported.
    """
    match = TIMEFRAME_PATTERN.match(tf_str)
    if not match:
        raise ValueError(f"Invalid timeframe string format: '{tf_str}'")

    num_str, unit = match.groups()
    num = int(num_str)

    if num <= 0:
        raise ValueError(f"Timeframe multiplier must be positive: '{tf_str}'")

    if unit not in UNIT_MS: # Should be caught by regex, but good for defense
        raise ValueError(f"Unsupported timeframe unit: '{unit}' in '{tf_str}'")

    period_ms = UNIT_MS[unit] * num
    return num, unit, period_ms

def format_timestamp_to_iso(timestamp_ms: Optional[int]) -> str:
    """
    Formats a millisecond timestamp into an ISO 8601 string (UTC).
    Returns "N/A" if the timestamp is None or invalid.
    """
    if timestamp_ms is None:
        return "N/A"
    try:
        # Convert milliseconds to seconds for fromtimestamp
        dt_object = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
        # Return in ISO format, ensuring 'Z' for UTC
        return dt_object.isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError) as e:
        logger.warning(f"Could not format timestamp {timestamp_ms} to ISO: {e}")
        return str(timestamp_ms) # Fallback to string representation of the timestamp

# If you decide to re-add normalize_timeframe_ccxt or similar later, it would go here.
# For now, it's removed as per our discussion to have plugins handle their own specific needs.