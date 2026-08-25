from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Mapping


IST = timezone(timedelta(hours=5, minutes=30))
VALID_MODES = {"NORMAL", "DEFENSIVE", "SURVIVAL"}
MODE_SEVERITY = {"NORMAL": 0, "DEFENSIVE": 1, "SURVIVAL": 2}
IV_CONTEXT_FIELDS = (
    "event_risk",
    "recent_iv_expansion_pct",
    "iv_realized_spread_pct",
    "term_structure_risk",
    "skew_risk",
)
DEFAULT_IV_CONTEXT = {
    "event_risk": 10.0,
    "recent_iv_expansion_pct": 0.0,
    "iv_realized_spread_pct": 0.0,
    "term_structure_risk": 15.0,
    "skew_risk": 15.0,
}


@dataclass(frozen=True)
class DailyModeDecision:
    computed_mode: str
    effective_mode: str
    status: str
    reason: str
    path: str


@dataclass(frozen=True)
class MarketContextDecision:
    values: Mapping[str, float]
    status: str
    reason: str
    path: str
    as_of: str = ""
    expires_at: str = ""
    source: str = ""


def _parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=IST)


def _now(now: datetime | None = None) -> datetime:
    current = now or datetime.now(IST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=IST)
    return current.astimezone(IST)


def load_daily_mode(path: str | Path, computed_mode: str, now: datetime | None = None) -> DailyModeDecision:
    computed = str(computed_mode or "NORMAL").upper()
    if computed not in VALID_MODES:
        computed = "NORMAL"
    p = Path(path)
    if not p.exists():
        return DailyModeDecision(computed, computed, "UNAVAILABLE", "Daily mode file not present; computed mode retained", str(p))
    try:
        lines = [line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    except OSError as exc:
        return DailyModeDecision(computed, computed, "INVALID", f"Daily mode file unreadable: {exc}", str(p))
    if not lines:
        return DailyModeDecision(computed, computed, "INVALID", "Daily mode file is empty", str(p))
    mode = lines[0].split("=", 1)[1].strip().upper() if "=" in lines[0] else lines[0].upper()
    if mode not in VALID_MODES:
        return DailyModeDecision(computed, computed, "INVALID", f"Unsupported daily mode: {mode}", str(p))
    metadata: dict[str, str] = {}
    for line in lines[1:]:
        if "=" in line:
            key, value = line.split("=", 1)
            metadata[key.strip().lower()] = value.strip()
    current = _now(now)
    as_of = metadata.get("as_of", current.date().isoformat())
    if as_of != current.date().isoformat():
        return DailyModeDecision(computed, computed, "STALE", f"Daily mode is for {as_of}, not {current.date().isoformat()}", str(p))
    expires_at = _parse_dt(metadata.get("expires_at"))
    if expires_at is None or current.astimezone(expires_at.tzinfo) > expires_at:
        return DailyModeDecision(computed, computed, "INVALID", "Daily mode requires a valid future expires_at", str(p))
    effective = mode if MODE_SEVERITY[mode] >= MODE_SEVERITY[computed] else computed
    reason = "Manual mode is at least as conservative as computed mode" if effective == mode else "Computed mode retained because it is more conservative than manual mode"
    return DailyModeDecision(computed, effective, "APPLIED", reason, str(p))


def load_market_context(path: str | Path, now: datetime | None = None) -> MarketContextDecision:
    p = Path(path)
    current = _now(now)
    if not p.exists():
        return MarketContextDecision(dict(DEFAULT_IV_CONTEXT), "UNAVAILABLE", "Daily market context file not present; conservative proxy defaults retained", str(p))
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return MarketContextDecision(dict(DEFAULT_IV_CONTEXT), "INVALID", f"Daily market context unreadable: {exc}", str(p))
    if not isinstance(raw, Mapping):
        return MarketContextDecision(dict(DEFAULT_IV_CONTEXT), "INVALID", "Daily market context must be an object", str(p))
    if raw.get("enabled", True) is False:
        return MarketContextDecision(dict(DEFAULT_IV_CONTEXT), "DISABLED", "Daily market context is disabled until operator review", str(p), as_of=str(raw.get("as_of", "")), expires_at=str(raw.get("expires_at", "")), source=str(raw.get("source", "")))
    as_of = str(raw.get("as_of", ""))
    if as_of != current.date().isoformat():
        return MarketContextDecision(dict(DEFAULT_IV_CONTEXT), "STALE", f"Daily market context is for {as_of or 'unknown date'}", str(p), as_of=as_of, expires_at=str(raw.get("expires_at", "")), source=str(raw.get("source", "")))
    expires_at_raw = raw.get("expires_at")
    expires_at = _parse_dt(expires_at_raw)
    if expires_at is None or current.astimezone(expires_at.tzinfo) > expires_at:
        return MarketContextDecision(dict(DEFAULT_IV_CONTEXT), "STALE", "Daily market context is expired or has invalid expires_at", str(p), as_of=as_of, expires_at=str(expires_at_raw or ""), source=str(raw.get("source", "")))
    source = str(raw.get("source", "")).strip()
    if not source:
        return MarketContextDecision(dict(DEFAULT_IV_CONTEXT), "INVALID", "Daily market context requires source", str(p), as_of=as_of, expires_at=str(expires_at_raw), source=source)
    values: dict[str, float] = {}
    for field in IV_CONTEXT_FIELDS:
        try:
            value = float(raw[field])
        except (KeyError, TypeError, ValueError):
            return MarketContextDecision(dict(DEFAULT_IV_CONTEXT), "INVALID", f"Daily market context missing or invalid {field}", str(p), as_of=as_of, expires_at=str(expires_at_raw), source=source)
        if not 0.0 <= value <= 100.0:
            return MarketContextDecision(dict(DEFAULT_IV_CONTEXT), "INVALID", f"Daily market context {field} must be between 0 and 100", str(p), as_of=as_of, expires_at=str(expires_at_raw), source=source)
        values[field] = value
    return MarketContextDecision(values, "APPLIED", "Validated daily market context applied as manual proxy research input", str(p), as_of=as_of, expires_at=str(expires_at_raw), source=source)


def iv_context_payload(decision: MarketContextDecision) -> dict[str, Any]:
    return {
        **{key: float(decision.values.get(key, DEFAULT_IV_CONTEXT[key])) for key in IV_CONTEXT_FIELDS},
        "status": decision.status,
        "reason": decision.reason,
        "path": decision.path,
        "as_of": decision.as_of,
        "expires_at": decision.expires_at,
        "source": decision.source,
    }
