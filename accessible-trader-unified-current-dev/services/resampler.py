# services/resampler.py

import logging
from typing import List, Dict, Any

from utils.timeframes import _parse_timeframe_str, UNIT_MS

logger = logging.getLogger("Resampler")

class Resampler:
    """
    In-memory resampling of 1m OHLCV bars into arbitrary target timeframes.
    """
    def resample(self, bars: List[Dict[str, Any]], target_timeframe: str) -> List[Dict[str, Any]]:
        """
        :param bars: List of dicts each with keys ["timestamp", "open", "high", "low", "close", "volume"].
                     Assumed to be 1-minute bars sorted or unsorted.
        :param target_timeframe: e.g. "5m", "1h", "1d", etc.
        :return: List of resampled bars sorted by timestamp.
        """
        if not bars:
            return []
        # Pass through if target is 1m
        if target_timeframe == "1m":
            return sorted(bars, key=lambda b: b.get("timestamp", 0))

        try:
            _, _, period_ms = _parse_timeframe_str(target_timeframe)
        except ValueError:
            logger.error(f"Invalid target timeframe for resampling: {target_timeframe}")
            return []

        # If the requested period is <= 1m, return raw bars
        if period_ms <= UNIT_MS['m']:
            return sorted(bars, key=lambda b: b.get("timestamp", 0))

        grouped: Dict[int, Dict[str, Any]] = {}
        # Ensure chronological order
        sorted_bars = sorted(bars, key=lambda b: b.get("timestamp", 0))

        for bar in sorted_bars:
            try:
                ts = int(bar["timestamp"])
                o = float(bar["open"])
                h = float(bar["high"])
                l = float(bar["low"])
                c = float(bar["close"])
                v = float(bar.get("volume", 0.0))
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"Skipping malformed bar during resampling: {e} in {bar}")
                continue

            # Align to bucket start
            bucket_start = ts - (ts % period_ms)
            if bucket_start not in grouped:
                grouped[bucket_start] = {
                    "timestamp": bucket_start,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": v,
                }
            else:
                agg = grouped[bucket_start]
                agg["high"] = max(agg["high"], h)
                agg["low"] = min(agg["low"], l)
                agg["close"] = c  # last close in bucket
                agg["volume"] = agg.get("volume", 0.0) + v

        # Return in order
        return sorted(grouped.values(), key=lambda b: b["timestamp"])
