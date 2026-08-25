"""Parser for Fyers /data/options-chain-v3 payloads -> OptionChainSnapshot.

The Fyers chain payload shape (validated against the live API):

    data = {
      "callOi": ...,
      "putOi": ...,
      "indiavixData": {..., "ltp": 11.94, "symbol": "NSE:INDIAVIX-INDEX", ...},
      "expiryData": [{"date": "18-08-2026", "expiry": "1787047800", "expiry_flag": "W"}, ...],
      "optionsChain": [
        {"option_type": "", "strike_price": -1, "ltp": 24281.95, "symbol": "NSE:NIFTY50-INDEX",
         "fyToken": "...", "bid": ..., "ask": ..., ...},          # index row (option_type empty)
        {"option_type": "CE", "strike_price": 24150, "ltp": ..., "bid": ..., "ask": ...,
         "fyToken": "...", "symbol": "NSE:NIFTY2681824150CE", ...},
        ...
      ]
    }

The Fyers chain does NOT provide per-leg greeks, implied volatility, OI or
volume. Those fields are left empty/zero in OptionLeg, which the strategy
layer handles gracefully (delta falls back to a moneyness proxy, IV crush gets
a neutral 50 baseline, and the semantic validator treats missing IV/delta as
warnings). The dashboard shows a "greeks unavailable" note so nobody mistakes
proxied scores for live values.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Any, Mapping, Optional

from .models import Greeks, OptionType, Quote
from .option_chain import (
    OptionChainParseError,
    OptionChainSnapshot,
    OptionLeg,
    OptionStrike,
)


def _f(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    return float(value)


def _i(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    return int(float(value))


def _source_timestamp(raw: Mapping[str, Any], fallback: datetime) -> tuple[datetime, bool]:
    for key in ("timestamp", "exchange_timestamp", "last_traded_time", "exch_trade_time"):
        value = raw.get(key)
        if value in (None, ""):
            continue
        try:
            if isinstance(value, (int, float)):
                return datetime.fromtimestamp(float(value), UTC), True
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return (parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)), True
        except (TypeError, ValueError, OverflowError):
            continue
    return fallback, False


@dataclass(frozen=True)
class FyersExpiry:
    date_str: str
    expiry_ts: int
    flag: str  # "W" weekly / "M" monthly


def parse_expiry_calendar(payload: Mapping[str, Any]) -> tuple[FyersExpiry, ...]:
    data = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(data, Mapping):
        return tuple()
    raw = data.get("expiryData")
    if not isinstance(raw, list):
        return tuple()
    out: list[FyersExpiry] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        try:
            out.append(FyersExpiry(
                date_str=str(item.get("date", "")),
                expiry_ts=int(float(item["expiry"])),
                flag=str(item.get("expiry_flag", "M")),
            ))
        except (ValueError, KeyError, TypeError):
            continue
    return tuple(out)


def parse_india_vix(payload: Mapping[str, Any]) -> Optional[float]:
    data = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(data, Mapping):
        return None
    vix = data.get("indiavixData")
    if not isinstance(vix, Mapping):
        return None
    try:
        ltp = float(vix.get("ltp", 0.0))
    except (TypeError, ValueError):
        return None
    return ltp if ltp > 0 else None


class FyersOptionChainParser:
    @staticmethod
    def parse(payload: Mapping[str, Any], underlying: str, expiry: str,
              timestamp: Optional[datetime] = None) -> OptionChainSnapshot:
        ts = timestamp or datetime.now(UTC)
        data = payload.get("data") if isinstance(payload, Mapping) else None
        if not isinstance(data, Mapping):
            raise OptionChainParseError("Missing data in Fyers option chain payload")
        chain = data.get("optionsChain")
        if not isinstance(chain, list):
            raise OptionChainParseError("Missing data.optionsChain in Fyers payload")

        underlying_price = 0.0
        by_strike: dict[float, dict[str, Mapping[str, Any]]] = {}
        for entry in chain:
            if not isinstance(entry, Mapping):
                continue
            opt_type = str(entry.get("option_type", "")).upper()
            strike = _f(entry.get("strike_price"), -1.0)
            if opt_type in ("", "INDEX") and strike <= 0:
                underlying_price = _f(entry.get("ltp"), underlying_price)
                continue
            if opt_type not in ("CE", "PE") or strike <= 0:
                continue
            by_strike.setdefault(strike, {})[opt_type] = entry

        if underlying_price <= 0:
            raise OptionChainParseError("Underlying price missing in Fyers chain payload")
        if not by_strike:
            raise OptionChainParseError("No option strikes in Fyers chain payload")

        strikes: list[OptionStrike] = []
        for strike in sorted(by_strike):
            legs = by_strike[strike]
            ce = FyersOptionChainParser._leg(strike, OptionType.CE, legs.get("CE"), ts) if "CE" in legs else None
            pe = FyersOptionChainParser._leg(strike, OptionType.PE, legs.get("PE"), ts) if "PE" in legs else None
            strikes.append(OptionStrike(strike, ce, pe))
        return OptionChainSnapshot(underlying.upper(), underlying_price, expiry, ts, tuple(strikes))

    @staticmethod
    def _leg(strike: float, option_type: OptionType, raw: Optional[Mapping[str, Any]],
             timestamp: datetime) -> OptionLeg:
        if raw is None:
            raise OptionChainParseError(f"Missing {option_type.value} at {strike}")
        source_ts, source_available = _source_timestamp(raw, timestamp)
        quote = Quote(
            bid=_f(raw.get("bid")),
            ask=_f(raw.get("ask")),
            bid_qty=0,
            ask_qty=0,
            last=_f(raw.get("ltp")) if raw.get("ltp") is not None else None,
            timestamp=source_ts,
            source_timestamp_available=source_available,
        )
        return OptionLeg(
            strike=strike,
            option_type=option_type,
            security_id=str(raw.get("fyToken") or ""),
            quote=quote,
            greeks=Greeks(),
            implied_volatility=None,
            oi=_i(raw.get("oi")),
            previous_oi=0,
            volume=_i(raw.get("volume")),
            previous_volume=0,
            average_price=None,
            previous_close_price=None,
            source_timestamp=source_ts,
        )
