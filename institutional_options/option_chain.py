from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Any, Mapping, Optional

from .models import Greeks, OptionType, Quote


class OptionChainParseError(ValueError):
    pass


@dataclass(frozen=True)
class OptionLeg:
    strike: float
    option_type: OptionType
    security_id: str
    quote: Quote
    greeks: Greeks
    implied_volatility: Optional[float]
    oi: int
    previous_oi: int
    volume: int
    previous_volume: int
    average_price: Optional[float] = None
    previous_close_price: Optional[float] = None
    source_timestamp: Optional[datetime] = None

    @property
    def oi_change(self) -> int:
        return self.oi - self.previous_oi


@dataclass(frozen=True)
class OptionStrike:
    strike: float
    ce: Optional[OptionLeg]
    pe: Optional[OptionLeg]


@dataclass(frozen=True)
class OptionChainSnapshot:
    underlying: str
    underlying_price: float
    expiry: str
    timestamp: datetime
    strikes: tuple[OptionStrike, ...]

    def legs(self) -> tuple[OptionLeg, ...]:
        out: list[OptionLeg] = []
        for s in self.strikes:
            if s.ce is not None:
                out.append(s.ce)
            if s.pe is not None:
                out.append(s.pe)
        return tuple(out)

    def nearest_strike(self) -> float:
        if not self.strikes:
            raise OptionChainParseError("Option chain has no strikes")
        return min((s.strike for s in self.strikes), key=lambda k: abs(k - self.underlying_price))

    def leg_at(self, strike: float, option_type: OptionType) -> OptionLeg:
        for s in self.strikes:
            if abs(s.strike - strike) < 1e-9:
                leg = s.ce if option_type == OptionType.CE else s.pe
                if leg is None:
                    raise OptionChainParseError(f"Missing {option_type.value} at strike {strike}")
                return leg
        raise OptionChainParseError(f"Missing strike {strike}")


def _f(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    return float(value)


def _i(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    return int(float(value))


def _leg(strike: float, option_type: OptionType, raw: Mapping[str, Any], timestamp: datetime) -> OptionLeg:
    source_timestamp = timestamp
    source_timestamp_available = False
    for key in ("source_timestamp", "quote_timestamp", "timestamp"):
        raw_value = raw.get(key)
        if raw_value in (None, ""):
            continue
        try:
            parsed = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
            source_timestamp = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            source_timestamp_available = True
            break
        except (TypeError, ValueError):
            continue
    greeks_raw = raw.get("greeks") or {}
    quote = Quote(
        bid=_f(raw.get("top_bid_price")),
        ask=_f(raw.get("top_ask_price")),
        bid_qty=_i(raw.get("top_bid_quantity")),
        ask_qty=_i(raw.get("top_ask_quantity")),
        last=_f(raw.get("last_price")) if raw.get("last_price") is not None else None,
        timestamp=timestamp,
        source_timestamp_available=source_timestamp_available,
    )
    greeks = Greeks(
        delta=_f(greeks_raw.get("delta")) if greeks_raw.get("delta") is not None else None,
        theta=_f(greeks_raw.get("theta")) if greeks_raw.get("theta") is not None else None,
        gamma=_f(greeks_raw.get("gamma")) if greeks_raw.get("gamma") is not None else None,
        vega=_f(greeks_raw.get("vega")) if greeks_raw.get("vega") is not None else None,
        iv=_f(raw.get("implied_volatility")) if raw.get("implied_volatility") is not None else None,
    )
    return OptionLeg(
        strike=strike,
        option_type=option_type,
        security_id=str(raw.get("security_id") or ""),
        quote=quote,
        greeks=greeks,
        implied_volatility=greeks.iv,
        oi=_i(raw.get("oi")),
        previous_oi=_i(raw.get("previous_oi")),
        volume=_i(raw.get("volume")),
        previous_volume=_i(raw.get("previous_volume")),
        average_price=_f(raw.get("average_price")) if raw.get("average_price") is not None else None,
        previous_close_price=_f(raw.get("previous_close_price")) if raw.get("previous_close_price") is not None else None,
        source_timestamp=source_timestamp,
    )




@dataclass(frozen=True)
class OptionChainValidationReport:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


class OptionChainSemanticValidator:
    @staticmethod
    def validate(snapshot: OptionChainSnapshot, require_tradable_quotes: bool = False) -> OptionChainValidationReport:
        errors: list[str] = []
        warnings: list[str] = []
        if snapshot.underlying_price <= 0:
            errors.append("Underlying price missing or non-positive")
        if not snapshot.strikes:
            errors.append("No strikes in option chain")
        last_strike = None
        for strike in snapshot.strikes:
            if last_strike is not None and strike.strike <= last_strike:
                errors.append("Strikes not strictly increasing")
            last_strike = strike.strike
            for leg_name, leg in (("CE", strike.ce), ("PE", strike.pe)):
                if leg is None:
                    warnings.append(f"Missing {leg_name} at {strike.strike}")
                    continue
                if not leg.security_id:
                    errors.append(f"Missing security_id for {leg_name} {strike.strike}")
                if leg.implied_volatility is None or leg.implied_volatility <= 0:
                    warnings.append(f"Invalid IV for {leg_name} {strike.strike}")
                if leg.greeks.delta is None:
                    warnings.append(f"Missing delta for {leg_name} {strike.strike}")
                if require_tradable_quotes and not leg.quote.is_valid():
                    errors.append(f"Invalid bid/ask for {leg_name} {strike.strike}")
        return OptionChainValidationReport(valid=not errors, errors=tuple(errors), warnings=tuple(warnings))


class DhanOptionChainParser:
    @staticmethod
    def parse(payload: Mapping[str, Any], underlying: str, expiry: str, timestamp: Optional[datetime] = None) -> OptionChainSnapshot:
        ts = timestamp or datetime.now(UTC)
        data = payload.get("data") if isinstance(payload, Mapping) else None
        if not isinstance(data, Mapping):
            raise OptionChainParseError("Missing data in option chain payload")
        oc = data.get("oc")
        if not isinstance(oc, Mapping):
            raise OptionChainParseError("Missing data.oc in option chain payload")
        underlying_price = _f(data.get("last_price"))
        strikes: list[OptionStrike] = []
        for strike_text, node in oc.items():
            strike = _f(strike_text)
            ce = _leg(strike, OptionType.CE, node["ce"], ts) if isinstance(node, Mapping) and isinstance(node.get("ce"), Mapping) else None
            pe = _leg(strike, OptionType.PE, node["pe"], ts) if isinstance(node, Mapping) and isinstance(node.get("pe"), Mapping) else None
            strikes.append(OptionStrike(strike, ce, pe))
        strikes.sort(key=lambda x: x.strike)
        return OptionChainSnapshot(underlying.upper(), underlying_price, expiry, ts, tuple(strikes))
