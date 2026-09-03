from __future__ import annotations
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Mapping, Optional

class FeedHealthState(StrEnum):
    MARKET_CLOSED = "MARKET_CLOSED"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    CHAIN_UNAVAILABLE = "CHAIN_UNAVAILABLE"
    SCHEMA_INCOMPLETE = "SCHEMA_INCOMPLETE"
    DEPTH_UNAVAILABLE = "DEPTH_UNAVAILABLE"
    EXECUTABLE = "EXECUTABLE"

@dataclass(frozen=True)
class FeedQualityReport:
    state: FeedHealthState
    canonical_eligible: bool
    derived_iv_research_eligible: bool
    chain_entries: int
    option_legs: int
    tradable_quotes: int
    source_timestamps: int
    iv_values: int
    bid_ask_quantities: int
    depth_status: str
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["state"] = self.state.value
        out["reasons"] = list(self.reasons)
        return out

def _chain_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    data = payload.get("data") if isinstance(payload, Mapping) else None
    rows = data.get("optionsChain") if isinstance(data, Mapping) else None
    return [x for x in rows if isinstance(x, Mapping)] if isinstance(rows, list) else []

def assess_fyers_payload(payload: Any, *, chain: Any = None, depth_status: str = "UNKNOWN", market_open: bool = True, auth_error: bool = False) -> FeedQualityReport:
    if not market_open:
        return FeedQualityReport(FeedHealthState.MARKET_CLOSED, False, False, 0, 0, 0, 0, 0, 0, depth_status, ("Market closed; snapshot excluded from trading evidence",))
    if auth_error:
        return FeedQualityReport(FeedHealthState.AUTHENTICATION_ERROR, False, False, 0, 0, 0, 0, 0, 0, depth_status, ("Fyers authentication failed",))
    rows = _chain_rows(payload) if isinstance(payload, Mapping) else []
    legs = [x for x in rows if str(x.get("option_type", "")).upper() in {"CE", "PE"}]
    tradable = [x for x in legs if _positive(x.get("bid")) and _positive(x.get("ask")) and float(x.get("ask")) > float(x.get("bid"))]
    iv_values = [x for x in legs if _positive(x.get("iv")) or _positive(x.get("implied_volatility"))]
    source_ts = [x for x in legs if any(x.get(k) not in (None, "") for k in ("timestamp", "exchange_timestamp", "last_traded_time", "exch_trade_time"))]
    quantities = [x for x in legs if _positive(x.get("bid_qty")) and _positive(x.get("ask_qty"))]
    if not rows or chain is None:
        return FeedQualityReport(FeedHealthState.CHAIN_UNAVAILABLE, False, False, len(rows), len(legs), len(tradable), len(source_ts), len(iv_values), len(quantities), depth_status, ("Option-chain payload or parsed chain unavailable",))
    reasons: list[str] = []
    if not iv_values: reasons.append("IV/Greeks absent from Fyers option-chain entries")
    if not source_ts: reasons.append("Exchange source timestamps absent; receipt time only")
    if not quantities: reasons.append("Bid/ask quantities absent from option-chain entries")
    if depth_status not in {"APPLIED", "PARTIAL"}: reasons.append("Separate depth enrichment unavailable")
    derived_ok = len(tradable) > 0 and depth_status in {"APPLIED", "PARTIAL"}
    canonical_ok = bool(tradable) and bool(iv_values) and bool(source_ts) and bool(quantities) and depth_status == "APPLIED"
    if canonical_ok:
        state = FeedHealthState.EXECUTABLE
    elif depth_status not in {"APPLIED", "PARTIAL"}:
        state = FeedHealthState.DEPTH_UNAVAILABLE
    else:
        state = FeedHealthState.SCHEMA_INCOMPLETE
    return FeedQualityReport(state, canonical_ok, derived_ok, len(rows), len(legs), len(tradable), len(source_ts), len(iv_values), len(quantities), depth_status, tuple(reasons))

def _positive(value: Any) -> bool:
    try: return float(value) > 0
    except (TypeError, ValueError): return False
