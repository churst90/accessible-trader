# utils/timeframes.py

import re
from typing import Dict, Tuple # Added Tuple

# Regular expression to match valid timeframe strings like "5m", "1h", "2d", "1w", "1M", "1y".
# It captures the numeric multiplier and the unit character.
TIMEFRAME_PATTERN = re.compile(r'^(\d+)([mhdwMy])$')

# Dictionary mapping timeframe units to their duration in milliseconds.
UNIT_MS: Dict[str, int] = {
    'm':    60_000,          # Minute
    'h': 3_600_000,         # Hour
    'd': 86_400_000,        # Day
    'w': 604_800_000,       # Week (7 days)
    'M': 2_592_000_000,    # Month (approx 30 days)
    'y': 31_536_000_000,   # Year (approx 365 days)
}

# Dictionary mapping timeframe units to their duration in seconds.
# Derived from UNIT_MS, useful for calculations not requiring millisecond precision.
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
    # Attempt to match the input string against the predefined pattern.
    match = TIMEFRAME_PATTERN.match(tf_str)
    if not match:
        # If no match, the format is incorrect.
        raise ValueError(f"Invalid timeframe string format: '{tf_str}'")

    # Extract the numeric part (multiplier) and the unit character from the match groups.
    num_str, unit = match.groups()
    num = int(num_str) # Convert the numeric string part to an integer.

    # Validate the multiplier.
    if num <= 0:
        # Timeframe multipliers must be greater than zero.
        raise ValueError(f"Timeframe multiplier must be positive: '{tf_str}'")

    # Validate the unit (although regex already constrains it).
    if unit not in UNIT_MS:
        # This check is technically redundant due to the regex group [mhdwMy],
        # but kept for explicit clarity and safety in case the regex changes.
        raise ValueError(f"Unsupported timeframe unit: '{unit}' in '{tf_str}'")

    # Calculate the total period in milliseconds.
    period_ms = UNIT_MS[unit] * num

    # Return the parsed components.
    return num, unit, period_ms
