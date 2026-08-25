"""Versioned research events and conservative counterfactual shadow outcomes."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from .models import OpportunityEvaluation, Quote
from .research_controls import StrategyVersions, exposure_group as compute_exposure_group
from .scoring import PaperFillSimulator


class AppendOnlyCsv:
    def __init__(self, path: str | Path, fields: list[str]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fields = fields
        if not self.path.exists() or self.path.stat().st_size == 0:
            with self.path.open("w", encoding="utf-8", newline="") as f:
                csv.DictWriter(f, fieldnames=fields).writeheader()

    def append(self, row: Mapping[str, Any]) -> None:
        missing = [key for key in row if key not in self.fields]
        if missing:
            with self.path.open("r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            self.fields = self.fields + missing
            tmp = self.path.with_suffix(self.path.suffix + ".schema.tmp")
            with tmp.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.fields)
                writer.writeheader()
                writer.writerows({key: row.get(key, "") for key in self.fields} for row in rows)
            tmp.replace(self.path)
        with self.path.open("a", encoding="utf-8", newline="") as f:
            csv.DictWriter(f, fieldnames=self.fields, extrasaction="ignore").writerow(
                {key: row.get(key, "") for key in self.fields}
            )


class ResearchEventLedger:
    """One stable event schema for replay, audit, and cross-sectional analysis."""

    FIELDS = [
        "event_id", "ts", "event_type", "session_id", "underlying", "exchange",
        "instrument_kind", "instrument_class", "lifecycle_state", "exposure_group",
        "decision_source", "strategy_version", "score_version", "universe_version",
        "parameter_profile", "payload_json",
    ]

    def __init__(self, state_dir: str | Path, versions: StrategyVersions):
        self.versions = versions
        self.events = AppendOnlyCsv(Path(state_dir) / "research_events.csv", self.FIELDS)
        self._counter = 0

    def append(self, event_type: str, *, session_id: str = "", underlying: str = "",
               exchange: str = "", instrument_kind: str = "", instrument_class: str = "",
               lifecycle_state: str = "", exposure_group: str = "", decision_source: str = "", payload: Optional[Mapping[str, Any]] = None,
               ts: Optional[datetime] = None) -> str:
        self._counter += 1
        now = ts or datetime.now(timezone.utc)
        event_id = f"{now.strftime('%Y%m%d%H%M%S%f')}-{self._counter}"
        import json
        self.events.append({
            "event_id": event_id,
            "ts": now.isoformat(),
            "event_type": event_type,
            "session_id": session_id,
            "underlying": underlying,
            "exchange": exchange,
            "instrument_kind": instrument_kind,
            "instrument_class": instrument_class,
            "lifecycle_state": lifecycle_state,
            "exposure_group": exposure_group or compute_exposure_group(underlying, instrument_kind),
            "decision_source": decision_source,
            "strategy_version": self.versions.strategy_version,
            "score_version": self.versions.score_version,
            "universe_version": self.versions.universe_version,
            "parameter_profile": self.versions.parameter_profile,
            "payload_json": json.dumps(dict(payload or {}), sort_keys=True, default=str),
        })
        return event_id


@dataclass
class ShadowTradeState:
    shadow_id: str
    underlying: str
    exchange: str
    instrument_kind: str
    instrument_class: str
    lifecycle_state: str
    exposure_group: str
    side: str
    strike: float
    expiry: str
    entry_time: datetime
    entry_price: float
    entry_mid: float
    stop_points: float
    target_points: float
    tick_size: float
    lot_size: int
    score: float
    threshold: float
    highest: float
    lowest: float
    last_mid: float
    last_quote_time: datetime
    last_quote: Quote


@dataclass(frozen=True)
class ShadowOutcome:
    shadow_id: str
    underlying: str
    instrument_class: str
    lifecycle_state: str
    exposure_group: str
    side: str
    strike: float
    expiry: str
    lot_size: int
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    exit_reason: str
    gross_points: float
    net_points: float
    net_pnl_rupees: float
    r_multiple: float
    hold_seconds: int
    max_adverse_points: float
    max_favorable_points: float
    score: float
    threshold: float
    fillable_entry: bool
    fillable_exit: bool


class ShadowTradeTracker:
    """Tracks only the top shadow candidate per underlying using paper fills.

    It never opens a real position and never calls a broker order endpoint.  A
    shadow trade is a counterfactual observation used for model calibration.
    """

    def __init__(self, fill_simulator: PaperFillSimulator, max_hold_seconds: int = 1800):
        self.fill_simulator = fill_simulator
        self.max_hold_seconds = max_hold_seconds
        self.active: dict[str, ShadowTradeState] = {}
        self._counter = 0

    def observe(self, evaluation: OpportunityEvaluation, now: datetime) -> Optional[ShadowOutcome]:
        c = evaluation.candidate
        key = c.instrument.underlying
        quote = c.quote
        if not quote.is_valid():
            return None
        state = self.active.get(key)
        if state is None or state.side != c.side.value or state.strike != c.instrument.strike or state.expiry != c.instrument.expiry.isoformat():
            if state is not None:
                # A changed top candidate closes the previous counterfactual
                # using that contract’s own last observed quote. Using the new
                # candidate’s quote here would create a cross-contract PnL error.
                closed = self._close(state, state.last_quote, now, "RANK_CHANGE")
            else:
                closed = None
            entry = self.fill_simulator.entry_buy(quote, c.instrument.tick_size)
            if not entry.filled or entry.fill_price is None:
                self.active.pop(key, None)
                return closed
            self._counter += 1
            stop = max(evaluation.risk_plan.hard_stop_points, c.instrument.tick_size)
            state = ShadowTradeState(
                shadow_id=f"shadow-{now.strftime('%Y%m%d%H%M%S%f')}-{self._counter}",
                underlying=key,
                exchange=c.instrument.exchange,
                instrument_kind=c.instrument.instrument_kind,
                instrument_class=c.instrument.instrument_class,
                lifecycle_state=c.lifecycle_state,
                exposure_group=c.exposure_group,
                side=c.side.value,
                strike=float(c.instrument.strike or 0),
                expiry=c.instrument.expiry.isoformat(),
                entry_time=now,
                entry_price=float(entry.fill_price),
                entry_mid=float(quote.mid),
                stop_points=float(stop),
                target_points=float(stop * 2.0),
                tick_size=float(c.instrument.tick_size),
                lot_size=int(c.instrument.lot_size),
                score=float(evaluation.comparable_opportunity_score),
                threshold=float(evaluation.dynamic_excellent_threshold),
                highest=float(quote.mid), lowest=float(quote.mid), last_mid=float(quote.mid),
                last_quote_time=quote.timestamp, last_quote=quote,
            )
            self.active[key] = state
            return closed
        state.highest = max(state.highest, quote.mid)
        state.lowest = min(state.lowest, quote.mid)
        state.last_mid = quote.mid
        state.last_quote_time = quote.timestamp
        state.last_quote = quote
        gain = quote.mid - state.entry_price
        age = (now - state.entry_time).total_seconds()
        if gain >= state.target_points:
            return self._close(state, quote, now, "TARGET")
        if gain <= -state.stop_points:
            return self._close(state, quote, now, "STOP")
        if age >= self.max_hold_seconds:
            return self._close(state, quote, now, "TIME")
        return None

    def _close(self, state: ShadowTradeState, quote: Quote, now: datetime, reason: str) -> ShadowOutcome:
        exit_fill = self.fill_simulator.exit_sell(quote, state.tick_size)
        exit_price = float(exit_fill.fill_price) if exit_fill.filled and exit_fill.fill_price is not None else float(max(quote.bid, 0.0))
        gross_points = exit_price - state.entry_price
        gross_pnl = gross_points * state.lot_size
        # Shadow outcomes intentionally exclude broker charges here; the runner
        # adds its verified CostCalculator result before persistence.
        self.active.pop(state.underlying, None)
        return ShadowOutcome(
            shadow_id=state.shadow_id, underlying=state.underlying,
            instrument_class=state.instrument_class, lifecycle_state=state.lifecycle_state,
            exposure_group=state.exposure_group, side=state.side, strike=state.strike,
            expiry=state.expiry, lot_size=state.lot_size,
            entry_time=state.entry_time.isoformat(), exit_time=now.isoformat(),
            entry_price=state.entry_price, exit_price=exit_price, exit_reason=reason,
            gross_points=gross_points, net_points=gross_points,
            net_pnl_rupees=gross_pnl, r_multiple=gross_points / state.stop_points if state.stop_points else 0.0,
            hold_seconds=int((now - state.entry_time).total_seconds()),
            max_adverse_points=state.entry_price - state.lowest,
            max_favorable_points=state.highest - state.entry_price,
            score=state.score, threshold=state.threshold,
            fillable_entry=True, fillable_exit=exit_fill.filled,
        )


__all__ = ["ResearchEventLedger", "ShadowOutcome", "ShadowTradeTracker"]
