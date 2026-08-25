"""Experimental impulse-breakout research and paper-entry gate.

This module is deliberately independent from the canonical opportunity scorer.
It detects an underlying range breakout from real one-minute history, then
applies explicit evidence and portfolio vetoes before it can ever nominate a
paper candidate.  It never places broker orders and does not mutate canonical
gate-learning state.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean
from typing import Any, Iterable, Mapping, Optional


@dataclass(frozen=True)
class ImpulseBreakoutResult:
    status: str
    underlying: str
    direction: str = ""
    option_side: str = ""
    raw_signal: bool = False
    range_high: Optional[float] = None
    range_low: Optional[float] = None
    last_close: Optional[float] = None
    atr_points: Optional[float] = None
    displacement_points: Optional[float] = None
    late_entry_atr: Optional[float] = None
    direction_score: Optional[float] = None
    trend_efficiency: Optional[float] = None
    relative_volume: Optional[float] = None
    history_bars: int = 0
    quote_age_seconds: Optional[float] = None
    trigger_key: str = ""
    candidate_key: str = ""
    reason: str = ""
    candidate: Any = None


class ImpulseBreakoutSelector:
    """Deterministic 30-minute range-breakout evaluator.

    The selector is intentionally conservative about the data it consumes:
    missing or stale history produces an explicit status instead of a signal.
    """

    def __init__(self, config: Optional[Mapping[str, Any]] = None) -> None:
        self.config = dict(config or {})

    def _bool(self, key: str, default: bool) -> bool:
        value = self.config.get(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "y"}

    def _float(self, key: str, default: float) -> float:
        try:
            return float(self.config.get(key, default))
        except (TypeError, ValueError):
            return default

    def _int(self, key: str, default: int) -> int:
        try:
            return int(self.config.get(key, default))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _rows(history: Optional[Iterable], now: datetime) -> list[tuple[datetime, float, float, float, float, float]]:
        rows: list[tuple[datetime, float, float, float, float, float]] = []
        for row in history or []:
            if not isinstance(row, (list, tuple)) or len(row) < 5:
                continue
            try:
                raw_ts = float(row[0])
                # Fyers history timestamps are Unix seconds.  Small or invalid
                # timestamps are rejected rather than treated as current data.
                if raw_ts < 1_000_000_000:
                    continue
                ts = datetime.fromtimestamp(raw_ts, tz=timezone.utc)
                high = float(row[2])
                low = float(row[3])
                close = float(row[4])
                volume = float(row[5]) if len(row) >= 6 else 0.0
            except (TypeError, ValueError, OSError, OverflowError):
                continue
            if high <= 0 or low <= 0 or close <= 0 or high < low:
                continue
            rows.append((ts, high, low, close, max(0.0, volume), raw_ts))
        rows.sort(key=lambda item: item[0])
        return rows

    @staticmethod
    def _atr(rows: list[tuple[datetime, float, float, float, float, float]], fallback: float) -> float:
        if len(rows) < 2:
            return max(0.0, fallback)
        true_ranges: list[float] = []
        previous_close = rows[0][3]
        for _, high, low, close, _, _ in rows[1:]:
            true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
            previous_close = close
        measured = mean(true_ranges[-14:]) if true_ranges else 0.0
        return max(measured, max(0.0, fallback))

    @staticmethod
    def _side(direction: str) -> str:
        return "CE" if direction == "UP" else "PE"

    @staticmethod
    def _candidate_key(evaluation: Any) -> str:
        c = evaluation.candidate
        return f"{c.instrument.underlying}|{c.side.value}|{c.instrument.strike}|{c.instrument.expiry}"

    @staticmethod
    def _quality_key(evaluation: Any) -> tuple:
        c = evaluation.candidate
        return (
            float(evaluation.contract_quality.score),
            float(c.execution_quality_score),
            float(c.convexity_edge_score),
            float(c.opportunity_confidence_score),
            -float(c.market_hostility_score),
            -float(c.iv_crush_risk_score),
            str(c.instrument.underlying),
            str(c.side.value),
            float(c.instrument.strike or 0.0),
        )

    def evaluate(
        self,
        underlying: str,
        history: Optional[Iterable],
        context: Any,
        evaluations: Iterable[Any],
        now: datetime,
        *,
        cost_model_valid: bool,
        portfolio_blocked: bool = False,
        open_position: bool = False,
        cooldown_until: Optional[datetime] = None,
        last_trigger_key: str = "",
    ) -> ImpulseBreakoutResult:
        name = str(underlying).upper()
        if not self._bool("enabled", True):
            return ImpulseBreakoutResult("DISABLED", name, reason="Experimental lane disabled")
        if open_position:
            return ImpulseBreakoutResult("BLOCKED_OPEN_POSITION", name, reason="Global one-position lock active")
        rows = self._rows(history, now)
        lookback = max(5, self._int("range_lookback_minutes", 30))
        minimum_history = max(10, self._int("minimum_history_bars", 20))
        if len(rows) < max(minimum_history, min(lookback + 1, minimum_history + 1)):
            return ImpulseBreakoutResult("INSUFFICIENT_HISTORY", name, history_bars=len(rows), reason=f"Need at least {minimum_history} valid history bars")
        last_ts, _, _, last_close, last_volume, _ = rows[-1]
        now_utc = now.astimezone(timezone.utc)
        quote_age = max(0.0, (now_utc - last_ts).total_seconds())
        max_age = max(30.0, self._float("max_signal_age_seconds", 180.0))
        if quote_age > max_age:
            return ImpulseBreakoutResult("BLOCKED_STALE_HISTORY", name, history_bars=len(rows), quote_age_seconds=quote_age, last_close=last_close, reason=f"Latest history bar is {quote_age:.1f}s old")
        prior = rows[-(lookback + 1):-1]
        if len(prior) < minimum_history:
            prior = rows[:-1]
        if len(prior) < minimum_history:
            return ImpulseBreakoutResult("INSUFFICIENT_RANGE_HISTORY", name, history_bars=len(rows), quote_age_seconds=quote_age, last_close=last_close, reason="Not enough prior bars for the rolling range")
        range_high = max(row[1] for row in prior)
        range_low = min(row[2] for row in prior)
        fallback_atr = float(getattr(context, "atr1", 0.0) or 0.0)
        atr = self._atr(prior, fallback_atr)
        displacement = max(self._float("min_breakout_displacement_points", 0.0), atr * max(0.0, self._float("min_breakout_displacement_atr", 0.75)))
        up = last_close > range_high + displacement
        down = last_close < range_low - displacement
        if up == down:
            return ImpulseBreakoutResult("NO_BREAKOUT", name, range_high=range_high, range_low=range_low, last_close=last_close, atr_points=atr, displacement_points=displacement, history_bars=len(rows), quote_age_seconds=quote_age, reason="Latest close did not break the prior rolling range")
        direction = "UP" if up else "DOWN"
        side = self._side(direction)
        extension = (last_close - range_high) if up else (range_low - last_close)
        late_entry_atr = extension / max(atr, 1e-9)
        trigger_key = f"{name}|{direction}|{range_high:.4f}|{range_low:.4f}"
        base = dict(
            underlying=name, direction=direction, option_side=side, raw_signal=True,
            range_high=range_high, range_low=range_low, last_close=last_close,
            atr_points=atr, displacement_points=displacement, late_entry_atr=late_entry_atr,
            direction_score=float(getattr(context, "direction_score", 0.0) or 0.0),
            trend_efficiency=float(getattr(context, "trend_efficiency", 0.0) or 0.0),
            relative_volume=None, history_bars=len(rows), quote_age_seconds=quote_age,
            trigger_key=trigger_key,
        )
        if last_trigger_key == trigger_key and cooldown_until is not None and now < cooldown_until:
            return ImpulseBreakoutResult("BREAKOUT_SUPPRESSED_ONE_SHOT", reason="Same breakout episode is inside one-shot lockout", **base)
        if last_trigger_key == trigger_key and cooldown_until is not None and now >= cooldown_until:
            # A cooldown alone is not enough for re-entry; a new range key is
            # required by the caller before another episode is accepted.
            return ImpulseBreakoutResult("BREAKOUT_SUPPRESSED_ONE_SHOT", reason="Same breakout episode requires a new rolling range", **base)
        if late_entry_atr > max(0.1, self._float("max_late_entry_atr", 1.5)):
            return ImpulseBreakoutResult("BREAKOUT_BLOCKED_LATE_ENTRY", reason="Breakout extension is too large for a fresh long-option entry", **base)
        direction_score = float(getattr(context, "direction_score", 0.0) or 0.0)
        min_direction = max(0.0, self._float("min_direction_score", 25.0))
        if (direction == "UP" and direction_score < min_direction) or (direction == "DOWN" and direction_score > -min_direction):
            return ImpulseBreakoutResult("BREAKOUT_BLOCKED_DIRECTION", reason=f"Direction score {direction_score:.1f} does not confirm {direction}", **base)
        trend_efficiency = float(getattr(context, "trend_efficiency", 0.0) or 0.0)
        if trend_efficiency < max(0.0, self._float("min_trend_efficiency", 50.0)):
            return ImpulseBreakoutResult("BREAKOUT_BLOCKED_TREND", reason=f"Trend efficiency {trend_efficiency:.1f} is below confirmation floor", **base)
        prior_volumes = [row[4] for row in prior if row[4] > 0]
        relative_volume = (last_volume / (mean(prior_volumes[-10:]) or 1.0)) if last_volume > 0 and prior_volumes else None
        base["relative_volume"] = relative_volume
        if self._bool("require_volume_confirmation", False) and (relative_volume is None or relative_volume < self._float("min_relative_volume", 1.1)):
            return ImpulseBreakoutResult("BREAKOUT_BLOCKED_VOLUME", reason="Volume confirmation is unavailable or below its configured floor", **base)
        matching = []
        for evaluation in evaluations:
            c = evaluation.candidate
            if str(c.instrument.underlying).upper() != name or str(c.side.value).upper() != side:
                continue
            matching.append(evaluation)
        if not matching:
            return ImpulseBreakoutResult("BREAKOUT_NO_OPTION_CANDIDATE", reason="No matching option candidate was built for the breakout side", **base)
        if portfolio_blocked:
            return ImpulseBreakoutResult("BREAKOUT_BLOCKED_PORTFOLIO", reason="Portfolio no-trade veto is active", **base)
        if not cost_model_valid and self._bool("require_cost_model_valid", True):
            return ImpulseBreakoutResult("BREAKOUT_BLOCKED_COST_MODEL", reason="Transaction-cost model is not validated", **base)
        valid_data = [e for e in matching if bool(e.candidate.data_health.valid)]
        if not valid_data and self._bool("require_data_health_valid", True):
            return ImpulseBreakoutResult("BREAKOUT_BLOCKED_DATA_HEALTH", reason="All matching option candidates have invalid data health", **base)
        valid_contracts = [e for e in valid_data if bool(e.contract_quality.valid)]
        if not valid_contracts and self._bool("require_contract_valid", True):
            return ImpulseBreakoutResult("BREAKOUT_BLOCKED_CONTRACT", reason="All matching option candidates fail contract quality", **base)
        candidates = valid_contracts or valid_data or matching
        paper_candidates = [
            e for e in candidates
            if str(getattr(e.candidate, "lifecycle_state", "")).upper() in {"PAPER_ELIGIBLE", "TRADE_ELIGIBLE"}
        ]
        candidates = paper_candidates or candidates
        selected = max(candidates, key=self._quality_key)
        if self._bool("require_canonical_eligibility_for_paper_entry", True) and not bool(selected.eligible):
            return ImpulseBreakoutResult("BREAKOUT_BLOCKED_CANONICAL_GATES", candidate=selected, candidate_key=self._candidate_key(selected), reason="Best experimental option does not pass canonical eligibility gates", **base)
        if self._bool("research_only", True) or not self._bool("paper_entry_enabled", False):
            return ImpulseBreakoutResult("BREAKOUT_RESEARCH_ONLY", candidate=selected, candidate_key=self._candidate_key(selected), reason="Experimental lane is configured for research-only evidence", **base)
        return ImpulseBreakoutResult("BREAKOUT_CANDIDATE_READY", candidate=selected, candidate_key=self._candidate_key(selected), reason="Experimental impulse breakout passed its configured paper-entry gates", **base)
