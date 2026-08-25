from __future__ import annotations

from datetime import datetime

from .models import DataHealth, Quote


class DataHealthChecker:
    def __init__(self, futures_invalid_sec: float, option_invalid_sec: float):
        self.futures_invalid_sec = futures_invalid_sec
        self.option_invalid_sec = option_invalid_sec

    def quote_health(self, quote: Quote, now: datetime, max_age_seconds: float) -> DataHealth:
        if not quote.is_valid():
            return DataHealth(False, False, "Invalid bid/ask")
        age = (now - quote.timestamp).total_seconds()
        if age > max_age_seconds:
            return DataHealth(False, False, f"Quote stale: {age:.2f}s")
        return DataHealth(True, False, "")
