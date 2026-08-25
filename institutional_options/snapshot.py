from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from .models import DataHealth, Quote
from .option_chain import OptionChainSnapshot


@dataclass(frozen=True)
class InstrumentMarketSnapshot:
    underlying: str
    timestamp: datetime
    futures_quote: Quote
    option_chain: OptionChainSnapshot
    spot_price: float
    vwap: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    opening_range_high: float | None = None
    opening_range_low: float | None = None
    metadata: Mapping[str, float | str] | None = None


@dataclass(frozen=True)
class MultiInstrumentSnapshot:
    timestamp: datetime
    instruments: Mapping[str, InstrumentMarketSnapshot]
    global_data_health: DataHealth
