# utils/timeframes.py

import re
from typing import Dict

# matches "5m", "1h", "2d", "1w", "1M", "1y"
TIMEFRAME_PATTERN = re.compile(r'^(\d+)([mhdwMy])$')

# milliseconds per unit
UNIT_MS: Dict[str, int] = {
    'm':   60_000,
    'h':3_600_000,
    'd':86_400_000,
    'w':604_800_000,
    'M':2_592_000_000,    # approx 30d
    'y':31_536_000_000,   # approx 365d
}

# seconds per unit (for subscription manager, etc)
UNIT_SEC: Dict[str, int] = {k: v // 1000 for k, v in UNIT_MS.items()}
