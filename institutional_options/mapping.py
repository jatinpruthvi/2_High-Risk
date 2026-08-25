from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional

from .models import InstrumentSpec, OptionType


class InstrumentMappingError(ValueError):
    pass


@dataclass(frozen=True)
class MasterRecord:
    exch_id: str
    segment: str
    security_id: str
    instrument: str
    underlying_symbol: str
    symbol_name: str
    display_name: str
    lot_size: int
    expiry_date: Optional[date]
    strike_price: Optional[float]
    option_type: Optional[str]
    tick_size: float
    freeze_qty: Optional[int]
    buy_sell_indicator: Optional[str]


def _parse_date(value: str | None) -> Optional[date]:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _to_int(value: str | None, default: int = 0) -> int:
    if value is None or value == "":
        return default
    return int(float(value))


def _to_float(value: str | None, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    return float(value)


class InstrumentMaster:
    def __init__(self, records: Iterable[MasterRecord], as_of: Optional[date] = None):
        self.records = tuple(records)
        self.as_of = as_of or date.today()

    @classmethod
    def from_csv(cls, path: str | Path) -> "InstrumentMaster":
        p = Path(path)
        records: list[MasterRecord] = []
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                records.append(
                    MasterRecord(
                        exch_id=(row.get("EXCH_ID") or row.get("exch_id") or "").strip(),
                        segment=(row.get("SEGMENT") or row.get("segment") or "").strip(),
                        security_id=(row.get("SECURITY_ID") or row.get("security_id") or "").strip(),
                        instrument=(row.get("INSTRUMENT") or row.get("instrument") or "").strip(),
                        underlying_symbol=(row.get("UNDERLYING_SYMBOL") or row.get("underlying_symbol") or "").strip(),
                        symbol_name=(row.get("SYMBOL_NAME") or row.get("symbol_name") or "").strip(),
                        display_name=(row.get("DISPLAY_NAME") or row.get("display_name") or "").strip(),
                        lot_size=_to_int(row.get("LOT_SIZE") or row.get("lot_size"), 0),
                        expiry_date=_parse_date(row.get("SM_EXPIRY_DATE") or row.get("expiry_date")),
                        strike_price=_to_float(row.get("STRIKE_PRICE") or row.get("strike_price"), 0.0),
                        option_type=(row.get("OPTION_TYPE") or row.get("option_type") or "").strip() or None,
                        tick_size=_to_float(row.get("TICK_SIZE") or row.get("tick_size"), 0.0),
                        freeze_qty=_to_int(row.get("SM_FREEZE_QTY") or row.get("freeze_qty"), 0),
                        buy_sell_indicator=(row.get("BUY_SELL_INDICATOR") or row.get("buy_sell_indicator") or "").strip() or None,
                    )
                )
        return cls(records)

    def find_index_option(self, underlying: str, expiry: date, strike: float, option_type: OptionType) -> InstrumentSpec:
        matches = [
            r for r in self.records
            if r.exch_id.upper() == "NSE"
            and r.segment.upper() == "D"
            and r.instrument.upper() == "OPTIDX"
            and r.underlying_symbol.upper() == underlying.upper()
            and r.expiry_date == expiry
            and r.strike_price is not None
            and abs(r.strike_price - strike) < 1e-9
            and (r.option_type or "").upper() == option_type.value
        ]
        return self._single_to_spec(matches, option_type=option_type, strike=strike)

    def find_index_future(self, underlying: str, expiry: date) -> InstrumentSpec:
        matches = [
            r for r in self.records
            if r.exch_id.upper() == "NSE"
            and r.segment.upper() == "D"
            and r.instrument.upper() == "FUTIDX"
            and r.underlying_symbol.upper() == underlying.upper()
            and r.expiry_date == expiry
        ]
        return self._single_to_spec(matches, option_type=None, strike=None)

    def _single_to_spec(self, matches: list[MasterRecord], option_type: Optional[OptionType], strike: Optional[float]) -> InstrumentSpec:
        if not matches:
            raise InstrumentMappingError("Instrument mapping missing.")
        if len(matches) > 1:
            raise InstrumentMappingError("Instrument mapping duplicated.")
        r = matches[0]
        if not r.security_id or r.lot_size <= 0 or r.tick_size <= 0 or r.expiry_date is None:
            raise InstrumentMappingError("Instrument mapping invalid: missing security, lot, tick, or expiry.")
        if r.buy_sell_indicator and r.buy_sell_indicator.upper() not in {"A", "B", "S", "Y", "YES", ""}:
            raise InstrumentMappingError("Instrument not allowed by buy/sell indicator.")
        return InstrumentSpec(
            underlying=r.underlying_symbol.upper(),
            security_id=r.security_id,
            instrument=r.instrument.upper(),
            expiry=r.expiry_date,
            lot_size=r.lot_size,
            tick_size=r.tick_size,
            strike=strike,
            option_type=option_type,
            freeze_qty=r.freeze_qty,
            buy_sell_allowed=True,
        )


def round_to_tick(price: float, tick_size: float) -> float:
    if tick_size <= 0:
        raise InstrumentMappingError("Tick size must be positive.")
    return round(round(price / tick_size) * tick_size, 10)
