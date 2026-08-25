"""Paper-session evidence collection and phase-2 evidence reports.

The phase-2 dry-run gate (`phase2.DryRunValidator`) and its evidence review
(`phase2.EvidenceAnalyzer`) consume two CSV datasets:

  * `mtil.csv`      - one row per CLOSED paper trade, with the proxy scores at
                      entry plus the realised net PnL and R-multiple.
  * `skipped.csv`   - one row per evaluated-but-not-selected candidate (top-N
                      per ranking cycle), so the gate's "minimum paper trade
                      candidates" and "minimum ranking cycles" can be met even
                      on days when no trade fires.
  * `candidates_log.csv` - one row per evaluated candidate (sampled 1/min),
                      source for the per-day top-N report used to calibrate the
                      excellent-gate threshold.

The collector writes exactly the field names the phase-2 machinery already
reads (`OpportunityScore`, `DirectionScore`, `net_pnl_rupees`, `r_multiple`,
...), so `DryRunValidator`/`EvidenceAnalyzer` work unchanged on the
accumulated data. The score-bucket calibration in the report is the core
proxy-validation evidence: does a higher proxy score actually produce a
higher win rate / average R?

Usage:
    python -m institutional_options.paper_evidence [--state-dir paper_state]

Writes paper_state/evidence_report.txt and prints it.
"""
from __future__ import annotations

import csv
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from .analytics import summarize_pnl
from .config import SystemConfig
from .models import OptionType, PaperTrade
from .phase2 import CsvDataset, DryRunValidator, EvidenceAnalyzer
from .records import MTILRecordBuilder, SkippedCandidateRecordBuilder
from .research_controls import StrategyVersions, class_for_metadata, version_fingerprint
from .research_ledger import ShadowOutcome


class AppendingCsv:
    """Tiny append-only CSV writer that preserves the header from row keys."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fields: Optional[list[str]] = None
        if self.path.exists():
            with self.path.open("r", encoding="utf-8-sig", newline="") as f:
                first = f.readline().strip()
            if first:
                self._fields = [c.strip() for c in first.split(",") if c.strip()]

    def append(self, record: Mapping[str, Any]) -> None:
        if self._fields is None:
            self._fields = list(record.keys())
            with self.path.open("w", encoding="utf-8", newline="") as f:
                csv.DictWriter(f, fieldnames=self._fields).writeheader()
        missing = [key for key in record if key not in self._fields]
        if missing:
            with self.path.open("r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            expanded = self._fields + missing
            tmp = self.path.with_suffix(self.path.suffix + ".schema.tmp")
            with tmp.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=expanded)
                writer.writeheader()
                writer.writerows({key: row.get(key, "") for key in expanded} for row in rows)
            tmp.replace(self.path)
            self._fields = expanded
        row = {k: record.get(k, "") for k in self._fields}
        with self.path.open("a", encoding="utf-8", newline="") as f:
            csv.DictWriter(f, fieldnames=self._fields, extrasaction="ignore").writerow(row)


class PaperEvidenceCollector:
    """Writes phase-2 datasets (mtil.csv / skipped.csv / candidates_log.csv)
    from paper sessions."""

    def __init__(self, state_dir: str | Path, versions: Optional[StrategyVersions] = None):
        self.state_dir = Path(state_dir)
        self.versions = versions or StrategyVersions("unversioned", "unversioned", "unversioned")
        self.mtil = AppendingCsv(self.state_dir / "mtil.csv")
        self.skipped = AppendingCsv(self.state_dir / "skipped.csv")
        self.candidates = AppendingCsv(self.state_dir / "candidates_log.csv")
        # Separate diagnostics streams keep historical schemas stable while
        # exposing the strategy gates and research-only index observations.
        self.diagnostics = AppendingCsv(self.state_dir / "candidate_diagnostics.csv")
        self.shadow_candidates = AppendingCsv(self.state_dir / "shadow_candidates.csv")
        self.shadow_diagnostics = AppendingCsv(self.state_dir / "shadow_candidate_diagnostics.csv")
        self.monitor_diagnostics = AppendingCsv(self.state_dir / "monitor_diagnostics.csv")
        self.shadow_outcomes = AppendingCsv(self.state_dir / "shadow_outcomes.csv")
        self.skipped_forward_queue = AppendingCsv(self.state_dir / "skipped_forward_queue.csv")
        self.skipped_forward_outcomes = AppendingCsv(self.state_dir / "skipped_forward_outcomes.csv")
        self.revalidation = AppendingCsv(self.state_dir / "revalidation_audit.csv")
        self.fill_attempts = AppendingCsv(self.state_dir / "paper_fill_audit.csv")
        self.calibration_trades = AppendingCsv(self.state_dir / "paper_calibration_trades.csv")

    def record_revalidation(self, evaluation, passed: bool, reasons: Iterable[str] = (), stage: str = "PRE_ENTRY", ts: Optional[datetime] = None) -> None:
        c = evaluation.candidate
        now = ts or datetime.now()
        self.revalidation.append({
            "ts": now.isoformat(), "date": now.date().isoformat(),
            "stage": stage, "underlying": c.instrument.underlying,
            "instrument_class": c.instrument.instrument_class,
            "exchange": c.instrument.exchange, "instrument_kind": c.instrument.instrument_kind,
            "side": c.side.value, "strike": c.instrument.strike,
            "passed": bool(passed), "reasons": "; ".join(str(x) for x in reasons),
            "score": evaluation.comparable_opportunity_score,
            "gate_snapshot_id": (c.notes or {}).get("gate_snapshot_id", ""),
            "strategy_version": self.versions.strategy_version,
            "score_version": self.versions.score_version,
            "universe_version": self.versions.universe_version,
            "parameter_profile": self.versions.parameter_profile,
        })

    def record_fill_attempt(self, evaluation, stage: str, filled: bool, fill_price: Optional[float], reason: str = "", ts: Optional[datetime] = None) -> None:
        c = evaluation.candidate
        now = ts or datetime.now()
        self.fill_attempts.append({
            "ts": now.isoformat(), "date": now.date().isoformat(),
            "stage": stage, "underlying": c.instrument.underlying,
            "instrument_class": c.instrument.instrument_class,
            "exchange": c.instrument.exchange, "instrument_kind": c.instrument.instrument_kind,
            "side": c.side.value, "strike": c.instrument.strike,
            "filled": bool(filled), "fill_price": "" if fill_price is None else fill_price,
            "reason": reason, "gate_snapshot_id": (c.notes or {}).get("gate_snapshot_id", ""),
            "strategy_version": self.versions.strategy_version,
            "score_version": self.versions.score_version,
            "universe_version": self.versions.universe_version,
            "parameter_profile": self.versions.parameter_profile,
        })

    def record_calibration_trade(self, record: Any, cost_model_valid: bool = False) -> None:
        """Persist bounded proxy-mode paper outcomes outside canonical MTIL."""
        self.calibration_trades.append({
            "trade_id": getattr(record, "trade_id", ""),
            "underlying": getattr(record, "underlying", ""),
            "side": getattr(record, "side", ""),
            "expiry": getattr(record, "expiry", ""),
            "strike": getattr(record, "strike", ""),
            "entry_time": getattr(record, "entry_time", ""),
            "exit_time": getattr(record, "exit_time", ""),
            "entry_fill": getattr(record, "entry_fill", ""),
            "exit_fill": getattr(record, "exit_fill", ""),
            "exit_reason": getattr(record, "exit_reason", ""),
            "gross_points": getattr(record, "gross_points", ""),
            "gross_pnl": getattr(record, "gross_pnl", ""),
            "costs": getattr(record, "costs", ""),
            "net_pnl": getattr(record, "net_pnl", ""),
            "hold_seconds": getattr(record, "hold_seconds", ""),
            "max_adverse_points": getattr(record, "max_adverse_points", ""),
            "max_favorable_points": getattr(record, "max_favorable_points", ""),
            "entry_mode": "PAPER_CALIBRATION",
            "research_only": True,
            "cost_model_valid": bool(cost_model_valid),
            "strategy_version": self.versions.strategy_version,
            "score_version": self.versions.score_version,
            "universe_version": self.versions.universe_version,
            "parameter_profile": self.versions.parameter_profile,
        })

    def record_trade(self, trade: PaperTrade, net_pnl_rupees: float,
                     r_multiple: float, gross_pnl_rupees: Optional[float] = None,
                     total_costs_rupees: float = 0.0) -> None:
        """One MTIL row per closed trade, including proxy scores at entry."""
        record = MTILRecordBuilder.from_paper_trade(
            trade,
            net_pnl_rupees=net_pnl_rupees,
            r_multiple=r_multiple,
            gross_pnl_rupees=gross_pnl_rupees,
            total_costs_rupees=total_costs_rupees,
            strategy_version=self.versions.strategy_version,
            score_version=self.versions.score_version,
            universe_version=self.versions.universe_version,
        )
        record.update({
            "strategy_version": self.versions.strategy_version,
            "score_version": self.versions.score_version,
            "universe_version": self.versions.universe_version,
            "parameter_profile": self.versions.parameter_profile,
        })
        self.mtil.append(record)

    def record_skipped(self, evaluations: Iterable, ranking_cycle_id: str,
                       top_n: int = 5) -> None:
        """Top-N evaluated-but-not-selected candidates for one ranking cycle."""
        evals = list(evaluations)
        ranked = sorted(evals, key=lambda e: e.comparable_opportunity_score, reverse=True)
        for rank, e in enumerate(ranked[:top_n], start=1):
            why = "; ".join(e.reasons) if e.reasons else f"grade={e.grade.value} below threshold"
            row = SkippedCandidateRecordBuilder.from_evaluation(
                e,
                ranking_cycle_id=ranking_cycle_id,
                rank=rank,
                why=why,
                strategy_version=self.versions.strategy_version,
                score_version=self.versions.score_version,
                universe_version=self.versions.universe_version,
            )
            row["parameter_profile"] = self.versions.parameter_profile
            self.skipped.append(row)
            c = e.candidate
            self.skipped_forward_queue.append({
                "skip_id": row["skip_id"],
                "created_at": row["timestamp"],
                "underlying": c.instrument.underlying,
                "expiry": c.instrument.expiry.isoformat(),
                "strike": c.instrument.strike,
                "side": c.side.value,
                "entry_mid": c.quote.mid,
                "entry_bid": c.quote.bid,
                "entry_ask": c.quote.ask,
                "hard_stop_points": e.risk_plan.hard_stop_points,
                "target_r": float((c.notes or {}).get("target_r", 2.0)),
                "ComparableOpportunityScore": e.comparable_opportunity_score,
                "gate_snapshot_id": (c.notes or {}).get("gate_snapshot_id", ""),
                "gate_features_json": row.get("gate_features_json", ""),
                "instrument_id": c.instrument.underlying,
                "instrument_class": c.instrument.instrument_class,
                "evidence_profile": (c.notes or {}).get("evidence_profile", self.versions.parameter_profile),
                "parameter_profile": self.versions.parameter_profile,
                "strategy_version": self.versions.strategy_version,
                "score_version": self.versions.score_version,
                "universe_version": self.versions.universe_version,
                "veto_reason": row.get("veto_reason", ""),
                "why_not_traded": row.get("why_not_traded", ""),
                "expected_value_r": c.expected_value_r,
                "expected_value_status": (c.notes or {}).get("expected_value_status", "UNAVAILABLE"),
                "observed_elasticity_status": (c.notes or {}).get("observed_elasticity_status", "UNAVAILABLE"),
            })

    def observe_skipped_forward(self, chains: Mapping[str, Any], now: datetime, windows_minutes: tuple[int, ...] = (5, 15, 30)) -> list[dict[str, Any]]:
        """Record attributable future bid outcomes for previously skipped candidates.

        The returned rows are research-only proxy outcomes. They are never treated
        as fills or paper trades; the runner may use them with a conservative
        weight for gate research after joining the original feature snapshot.
        """
        queue_path = self.state_dir / "skipped_forward_queue.csv"
        if not queue_path.exists():
            return []
        with queue_path.open("r", encoding="utf-8-sig", newline="") as f:
            queue = list(csv.DictReader(f))
        done_path = self.state_dir / "skipped_forward_outcomes.csv"
        done = set()
        if done_path.exists():
            with done_path.open("r", encoding="utf-8-sig", newline="") as f:
                done = {(str(r.get("skip_id", "")), str(r.get("window_minutes", ""))) for r in csv.DictReader(f)}
        emitted: list[dict[str, Any]] = []
        for row in queue:
            try:
                created = datetime.fromisoformat(str(row["created_at"]))
                compare_now = now
                if created.tzinfo is None and now.tzinfo is not None:
                    created = created.replace(tzinfo=now.tzinfo)
                elif created.tzinfo is not None and now.tzinfo is None:
                    compare_now = now.replace(tzinfo=created.tzinfo)
                entry_mid = float(row.get("entry_mid", 0.0))
                stop = float(row.get("hard_stop_points", 0.0))
                target = entry_mid + stop * float(row.get("target_r", 2.0))
                stop_price = entry_mid - stop
            except (TypeError, ValueError, KeyError):
                continue
            for window in windows_minutes:
                key = (str(row.get("skip_id", "")), str(window))
                if key in done or (compare_now - created).total_seconds() < window * 60:
                    continue
                chain = chains.get(str(row.get("underlying", "")))
                quote = None
                reason = ""
                if chain is not None:
                    try:
                        leg = chain.leg_at(float(row["strike"]), OptionType(str(row["side"])))
                        quote = leg.quote
                    except Exception as exc:
                        reason = f"Future quote unavailable: {type(exc).__name__}"
                base = {
                    "skip_id": row.get("skip_id", ""),
                    "window_minutes": window,
                    "observed_at": now.isoformat(),
                    "underlying": row.get("underlying", ""),
                    "instrument_id": row.get("instrument_id", row.get("underlying", "")),
                    "instrument_class": row.get("instrument_class", ""),
                    "gate_snapshot_id": row.get("gate_snapshot_id", ""),
                    "gate_features_json": row.get("gate_features_json", ""),
                    "ComparableOpportunityScore": row.get("ComparableOpportunityScore", row.get("score", "")),
                    "side": row.get("side", ""),
                    "veto_reason": row.get("veto_reason", ""),
                    "why_not_traded": row.get("why_not_traded", ""),
                    "setup_type": row.get("setup_type", ""),
                    "expected_value_r": row.get("expected_value_r", ""),
                    "expected_value_status": row.get("expected_value_status", "UNAVAILABLE"),
                    "observed_elasticity_status": row.get("observed_elasticity_status", "UNAVAILABLE"),
                    "strategy_version": row.get("strategy_version", self.versions.strategy_version),
                    "score_version": row.get("score_version", self.versions.score_version),
                    "parameter_profile": row.get("parameter_profile", self.versions.parameter_profile),
                    "source": "SKIPPED_FORWARD_PROXY",
                }
                if quote is None or not quote.is_valid() or stop <= 0:
                    outcome = {
                        **base,
                        "future_bid": "", "future_ask": "",
                        "mfe_points": "UNAVAILABLE", "mae_points": "UNAVAILABLE",
                        "would_have_hit_target": "UNAVAILABLE", "would_have_hit_stop": "UNAVAILABLE",
                        "forward_r_multiple": "UNAVAILABLE",
                        "status": "UNAVAILABLE", "reason": reason or ("Required stop unavailable" if stop <= 0 else "Future quote invalid"),
                        "evidence_profile": row.get("evidence_profile", "UNSPECIFIED"),
                    }
                else:
                    future_bid = float(quote.bid)
                    delta = future_bid - entry_mid
                    outcome = {
                        **base,
                        "future_bid": future_bid, "future_ask": float(quote.ask),
                        "mfe_points": max(0.0, delta), "mae_points": min(0.0, delta),
                        "would_have_hit_target": future_bid >= target, "would_have_hit_stop": future_bid <= stop_price,
                        "forward_r_multiple": delta / stop,
                        "status": "OBSERVED", "reason": "",
                        "evidence_profile": row.get("evidence_profile", "UNSPECIFIED"),
                    }
                self.skipped_forward_outcomes.append(outcome)
                emitted.append(outcome)
        return emitted

    def no_trade_alpha_snapshot(self, max_rows: int = 5000) -> dict[str, Any]:
        """Summarize observed skipped-forward outcomes for research only."""
        path = self.state_dir / "skipped_forward_outcomes.csv"
        if not path.exists():
            return {"status": "WARMUP", "observed_rows": 0, "unavailable_rows": 0, "updated_at": datetime.now().isoformat()}
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))[-max(1, int(max_rows)):]
        except OSError:
            return {"status": "UNAVAILABLE", "observed_rows": 0, "unavailable_rows": 0, "updated_at": datetime.now().isoformat()}
        observed = [r for r in rows if str(r.get("status", "")).upper() == "OBSERVED"]
        unavailable = [r for r in rows if str(r.get("status", "")).upper() != "OBSERVED"]
        def truth(v: Any) -> bool:
            return str(v).strip().lower() in {"1", "true", "yes", "y", "hit", "win"}
        forward = []
        for r in observed:
            try:
                value = float(r.get("forward_r_multiple", ""))
                if math.isfinite(value):
                    forward.append(value)
            except (TypeError, ValueError):
                pass
        target_hits = sum(1 for r in observed if truth(r.get("would_have_hit_target")))
        stop_hits = sum(1 for r in observed if truth(r.get("would_have_hit_stop")))
        veto: dict[str, dict[str, Any]] = {}
        for r in observed:
            reason = str(r.get("veto_reason") or r.get("why_not_traded") or "UNSPECIFIED").split(";", 1)[0].strip() or "UNSPECIFIED"
            item = veto.setdefault(reason, {"observed": 0, "target_hits": 0, "stop_hits": 0, "sum_forward_r": 0.0})
            item["observed"] += 1
            item["target_hits"] += int(truth(r.get("would_have_hit_target")))
            item["stop_hits"] += int(truth(r.get("would_have_hit_stop")))
            try:
                value = float(r.get("forward_r_multiple", ""))
                if math.isfinite(value):
                    item["sum_forward_r"] += value
            except (TypeError, ValueError):
                pass
        for item in veto.values():
            item["avg_forward_r"] = item["sum_forward_r"] / item["observed"] if item["observed"] else 0.0
            del item["sum_forward_r"]
        return {
            "status": "READY" if observed else "WARMUP",
            "total_rows": len(rows),
            "observed_rows": len(observed),
            "unavailable_rows": len(unavailable),
            "target_hits": target_hits,
            "stop_hits": stop_hits,
            "ambiguous_rows": max(0, len(observed) - target_hits - stop_hits),
            "saved_loss_rate": stop_hits / len(observed) if observed else None,
            "missed_winner_rate": target_hits / len(observed) if observed else None,
            "average_forward_r": sum(forward) / len(forward) if forward else None,
            "by_veto_reason": veto,
            "cost_model_valid": False,
            "research_only": True,
            "updated_at": datetime.now().isoformat(),
        }

    def record_monitor_snapshot(self, underlying: str, exchange: str,
                                chain, context, vix: Optional[float],
                                instrument_kind: str = "INDEX",
                                ts: Optional[datetime] = None,
                                lot_size: Optional[int] = None,
                                lifecycle_state: str = "MONITOR") -> None:
        """Record monitor-only liquidity observations without ranking or entry.

        This is deliberately separate from candidate evidence. A monitor-only
        index must earn promotion using observed quote quality and fillability,
        not merely because its chain endpoint responds.
        """
        now = ts or datetime.now()
        atm_strike = chain.nearest_strike()
        atm = next((s for s in chain.strikes if abs(s.strike - atm_strike) < 1e-9), None)
        ce = atm.ce if atm is not None else None
        pe = atm.pe if atm is not None else None
        legs = chain.legs()
        valid_legs = [leg for leg in legs if leg.quote.is_valid()]
        ce_spread_pct = (ce.quote.spread / ce.quote.mid * 100.0) if ce and ce.quote.mid > 0 else 99.0
        pe_spread_pct = (pe.quote.spread / pe.quote.mid * 100.0) if pe and pe.quote.mid > 0 else 99.0
        valid_lot_size = int(lot_size) if lot_size is not None and int(lot_size) > 0 else None

        def lots(quantity: Optional[float]) -> str | float:
            if quantity is None or valid_lot_size is None:
                return ""
            return quantity / valid_lot_size

        self.monitor_diagnostics.append({
            "ts": now.isoformat(),
            "date": now.date().isoformat(),
            "underlying": underlying,
            "exchange": exchange,
            "instrument_kind": instrument_kind,
            "instrument_class": class_for_metadata(exchange, instrument_kind),
            "lifecycle_state": lifecycle_state,
            "spot": round(chain.underlying_price, 4),
            "expiry": chain.expiry,
            "vix": "" if vix is None else round(vix, 4),
            "direction": round(context.direction_score, 2),
            "direction_model_score": "" if getattr(context, "direction_model_score", None) is None else round(getattr(context, "direction_model_score"), 2),
            "direction_model_name": getattr(context, "direction_model_name", ""),
            "direction_model_status": getattr(context, "direction_model_status", "UNAVAILABLE"),
            "direction_model_disagreement": "" if getattr(context, "direction_model_disagreement", None) is None else round(getattr(context, "direction_model_disagreement"), 2),
            "trade_quality": round(context.trade_quality_score, 2),
            "market_hostility": round(context.market_hostility_score, 2),
            "strike_count": len(chain.strikes),
            "option_leg_count": len(legs),
            "valid_quote_leg_count": len(valid_legs),
            "atm_strike": atm_strike,
            "atm_ce_mid": "" if ce is None else round(ce.quote.mid, 4),
            "atm_pe_mid": "" if pe is None else round(pe.quote.mid, 4),
            "atm_ce_spread_pct": round(ce_spread_pct, 4),
            "atm_pe_spread_pct": round(pe_spread_pct, 4),
            "atm_ce_bid_qty": "" if ce is None else ce.quote.bid_qty,
            "atm_ce_ask_qty": "" if ce is None else ce.quote.ask_qty,
            "atm_pe_bid_qty": "" if pe is None else pe.quote.bid_qty,
            "atm_pe_ask_qty": "" if pe is None else pe.quote.ask_qty,
            "atm_ce_top_book_lots": "" if ce is None else lots(min(ce.quote.bid_qty, ce.quote.ask_qty)),
            "atm_pe_top_book_lots": "" if pe is None else lots(min(pe.quote.bid_qty, pe.quote.ask_qty)),
            "atm_ce_depth_lots": "" if ce is None or ce.quote.cumulative_bid_qty_5depth is None else lots(min(ce.quote.cumulative_bid_qty_5depth, ce.quote.cumulative_ask_qty_5depth or 0)),
            "atm_pe_depth_lots": "" if pe is None or pe.quote.cumulative_bid_qty_5depth is None else lots(min(pe.quote.cumulative_bid_qty_5depth, pe.quote.cumulative_ask_qty_5depth or 0)),
            "strategy_version": self.versions.strategy_version,
            "score_version": self.versions.score_version,
            "universe_version": self.versions.universe_version,
            "parameter_profile": self.versions.parameter_profile,
        })

    def record_shadow_candidates(self, evaluations: Iterable,
                                 ts: Optional[datetime] = None) -> None:
        """Persist monitor-only evaluations without mixing them with trade evidence."""
        now = ts or datetime.now()
        for e in evaluations:
            row = self._candidate_row(e, now)
            row["research_only"] = True
            self.shadow_candidates.append(row)
            diagnostic = self._diagnostic_row(e, now)
            diagnostic["research_only"] = True
            self.shadow_diagnostics.append(diagnostic)

    def record_shadow_outcome(self, outcome: ShadowOutcome, costs: float = 0.0) -> None:
        net_pnl = float(outcome.net_pnl_rupees) - float(costs)
        risk = abs(outcome.r_multiple) if outcome.r_multiple else 0.0
        self.shadow_outcomes.append({
            "shadow_id": outcome.shadow_id, "underlying": outcome.underlying,
            "instrument_class": outcome.instrument_class, "lifecycle_state": outcome.lifecycle_state,
            "exposure_group": outcome.exposure_group, "side": outcome.side,
            "strike": outcome.strike, "expiry": outcome.expiry, "lot_size": outcome.lot_size,
            "entry_time": outcome.entry_time, "exit_time": outcome.exit_time,
            "entry_price": outcome.entry_price, "exit_price": outcome.exit_price,
            "exit_reason": outcome.exit_reason, "gross_points": outcome.gross_points,
            "net_points": outcome.net_points, "gross_pnl_rupees": outcome.net_pnl_rupees,
            "costs_rupees": costs, "net_pnl_rupees": net_pnl,
            "r_multiple": outcome.r_multiple, "hold_seconds": outcome.hold_seconds,
            "max_adverse_points": outcome.max_adverse_points,
            "max_favorable_points": outcome.max_favorable_points,
            "score": outcome.score, "threshold": outcome.threshold,
            "fillable_entry": outcome.fillable_entry, "fillable_exit": outcome.fillable_exit,
            "strategy_version": self.versions.strategy_version,
            "score_version": self.versions.score_version,
            "universe_version": self.versions.universe_version,
            "parameter_profile": self.versions.parameter_profile,
        })

    def record_candidates(self, evaluations: Iterable, ts: Optional[datetime] = None) -> None:

        """One row per evaluated candidate (every grade, not just selected) into
        candidates_log.csv, so a per-day top-N report can be built for threshold
        calibration. The runner calls this once per minute (same cadence as
        record_skipped) to bound file size; minute-level sampling is ample for
        judging where the excellent-gate threshold sits."""
        now = ts or datetime.now()
        for e in evaluations:
            self.candidates.append(self._candidate_row(e, now))
            self.diagnostics.append(self._diagnostic_row(e, now))

    def _diagnostic_row(self, e, now: datetime) -> dict[str, Any]:
        c = e.candidate
        reasons = tuple(e.reasons)
        notes = c.notes or {}
        return {
            "ts": now.isoformat(),
            "date": now.date().isoformat(),
            "underlying": c.instrument.underlying,
            "exchange": c.instrument.exchange,
            "instrument_kind": c.instrument.instrument_kind,
            "instrument_class": c.instrument.instrument_class,
            "lifecycle_state": c.lifecycle_state,
            "exposure_group": c.exposure_group,
            "strategy_version": self.versions.strategy_version,
            "score_version": self.versions.score_version,
            "universe_version": self.versions.universe_version,
            "parameter_profile": self.versions.parameter_profile,
            "side": c.side.value,
            "setup_type": c.setup_type,
            "strike": c.instrument.strike,
            "side_direction_score": round(max(0.0, c.instrument_direction_score), 1),
            "observed_elasticity_valid": notes.get("observed_elasticity_valid", ""),
            "observed_elasticity_raw": notes.get("observed_elasticity_raw", ""),
            "observed_elasticity_post_cost": notes.get("observed_elasticity_post_cost", ""),
            "observed_elasticity_delta_adjusted": notes.get("observed_elasticity_delta_adjusted", ""),
            "observed_elasticity_post_cost_delta_adjusted": notes.get("observed_elasticity_post_cost_delta_adjusted", ""),
            "observed_elasticity_status": notes.get("observed_elasticity_status", "UNAVAILABLE"),
            "observed_elasticity_confirmation_count": notes.get("observed_elasticity_confirmation_count", 0),
            "expected_value_r": c.expected_value_r,
            "expected_value_status": notes.get("expected_value_status", "UNVALIDATED_COST_MODEL"),
            "same_direction_recent_loss": notes.get("same_direction_recent_loss", False),
            "observed_elasticity_reason": notes.get("observed_elasticity_reason", ""),
            "surface_valid": notes.get("surface_valid", ""),
            "atm_iv": notes.get("atm_iv", ""),
            "call_put_iv_skew": notes.get("call_put_iv_skew", ""),
            "call_wing_iv": notes.get("call_wing_iv", ""),
            "put_wing_iv": notes.get("put_wing_iv", ""),
            "surface_reason": notes.get("surface_reason", ""),
            "direction_model_score": notes.get("direction_model_score", ""),
            "direction_model_name": notes.get("direction_model_name", ""),
            "direction_model_status": notes.get("direction_model_status", ""),
            "direction_model_disagreement": notes.get("direction_model_disagreement", ""),
            "gate_snapshot_id": notes.get("gate_snapshot_id", ""),
            "gate_learning_status": notes.get("gate_learning_status", ""),
            "gate_learning_observations": notes.get("gate_learning_observations", ""),
            "gate_learning_sessions": notes.get("gate_learning_sessions", ""),
            "gate_learning_outcomes": notes.get("gate_learning_outcomes", ""),
            "gate_contract_quality_min": notes.get("gate_contract_quality_min", ""),
            "gate_direction_min": notes.get("gate_direction_min", ""),
            "gate_premium_elasticity_min": notes.get("gate_premium_elasticity_min", ""),
            "gate_expected_required_ratio_min": notes.get("gate_expected_required_ratio_min", ""),
            "gate_trade_quality_min": notes.get("gate_trade_quality_min", ""),
            "gate_final_confidence_min": notes.get("gate_final_confidence_min", ""),
            "gate_market_hostility_max": notes.get("gate_market_hostility_max", ""),
            "gate_iv_crush_max": notes.get("gate_iv_crush_max", ""),
            "gate_spread_pct_max": notes.get("gate_spread_pct_max", ""),
            "gate_min_top_book_lots": notes.get("gate_min_top_book_lots", ""),
            "gate_min_5depth_lots_each_side": notes.get("gate_min_5depth_lots_each_side", ""),
            "gate_resolution_path": notes.get("gate_resolution_path", ""),
            "gate_optimization_method": notes.get("gate_optimization_method", ""),
            "gate_optimization_status": notes.get("gate_optimization_status", ""),
            "gate_optimization_quantile": notes.get("gate_optimization_quantile", ""),
            "gate_validation_observations": notes.get("gate_validation_observations", ""),
            "gate_validation_sessions": notes.get("gate_validation_sessions", ""),
            "gate_validation_expectancy_r": notes.get("gate_validation_expectancy_r", ""),
            "gate_validation_drawdown_r": notes.get("gate_validation_drawdown_r", ""),
            "gate_validation_retention": notes.get("gate_validation_retention", ""),
            "gate_last_validated_at": notes.get("gate_last_validated_at", ""),
            "evidence_profile": notes.get("evidence_profile", self.versions.parameter_profile),
            "mapping_status": notes.get("mapping_status", "UNSPECIFIED"),
            "cost_model_status": notes.get("cost_model_status", "UNSPECIFIED"),
            "cost_model_valid": notes.get("cost_model_valid", False),
            "canonical_promotion_allowed": notes.get("canonical_promotion_allowed", False),
            "iv_context_status": notes.get("iv_context_status", "UNAVAILABLE"),
            "iv_context_reason": notes.get("iv_context_reason", ""),
            "iv_context_source": notes.get("iv_context_source", ""),
            "data_health_valid": notes.get("data_health_valid", str(c.data_health.valid)),
            "source_timestamp_available": str(c.quote.source_timestamp_available),
            "liquidity_data_status": notes.get("liquidity_data_status", "LIQUIDITY_UNAVAILABLE" if c.quote.bid_qty <= 0 or c.quote.ask_qty <= 0 else "MEASURED"),
            "depth_evidence": notes.get("depth_evidence", "FIVE_LEVEL" if c.quote.cumulative_bid_qty_5depth is not None and c.quote.cumulative_ask_qty_5depth is not None else "TOP_BOOK_ONLY" if c.quote.bid_qty > 0 and c.quote.ask_qty > 0 else "UNAVAILABLE"),
            "depth_source": notes.get("depth_source", "FYERS_MARKET_DEPTH" if c.quote.source_timestamp_available else "UNAVAILABLE"),
            "depth_bid_levels": notes.get("depth_bid_levels", 5 if c.quote.cumulative_bid_qty_5depth is not None else 0),
            "depth_ask_levels": notes.get("depth_ask_levels", 5 if c.quote.cumulative_ask_qty_5depth is not None else 0),
            "bid_qty": c.quote.bid_qty,
            "ask_qty": c.quote.ask_qty,
            "cumulative_bid_qty_5depth": c.quote.cumulative_bid_qty_5depth if c.quote.cumulative_bid_qty_5depth is not None else "",
            "cumulative_ask_qty_5depth": c.quote.cumulative_ask_qty_5depth if c.quote.cumulative_ask_qty_5depth is not None else "",
            "quote_timestamp": c.quote.timestamp.isoformat(),
            "iv_data_status": notes.get("iv_data_status", "IV_UNAVAILABLE" if c.greeks.iv is None else "MEASURED"),
            "direction_gate_passed": not any("SideDirection hard reject" in r for r in reasons),
            "contract_quality_score": round(e.contract_quality.score, 1),
            "contract_quality_gate_passed": e.contract_quality.valid and not any("ContractQuality below minimum" in r for r in reasons),
            "eligible": e.eligible,
            "decision": e.decision.value,
            "rejection_count": len(reasons),
            "rejection_reasons": "; ".join(reasons),
            "calibrated_probability": c.calibrated_success_probability if c.calibrated_success_probability is not None else "",
            "calibrated_expectancy_r": c.calibrated_net_expectancy_r if c.calibrated_net_expectancy_r is not None else "",
        }

    def _candidate_row(self, e, now: datetime) -> dict[str, Any]:
        c = e.candidate
        try:
            dte = (c.instrument.expiry - now.date()).days
        except Exception:
            dte = ""
        mid = c.quote.mid
        return {
            "ts": now.isoformat(),
            "date": now.date().isoformat(),
            "underlying": c.instrument.underlying,
            "exchange": c.instrument.exchange,
            "instrument_kind": c.instrument.instrument_kind,
            "instrument_class": c.instrument.instrument_class,
            "lifecycle_state": c.lifecycle_state,
            "exposure_group": c.exposure_group,
            "strategy_version": self.versions.strategy_version,
            "score_version": self.versions.score_version,
            "universe_version": self.versions.universe_version,
            "parameter_profile": self.versions.parameter_profile,
            "side": c.side.value,
            "setup_type": c.setup_type,
            "strike": c.instrument.strike,
            "expiry": c.instrument.expiry.isoformat(),
            "dte": dte,
            "grade": e.grade.value,
            "comparable_score": round(e.comparable_opportunity_score, 2),
            "opportunity_score": round(e.opportunity_score, 2),
            "threshold": round(e.dynamic_excellent_threshold, 1),
            "eligible": e.eligible,
            "decision": e.decision.value,
            "direction": round(c.instrument_direction_score, 1),
            "direction_model_score": c.notes.get("direction_model_score", ""),
            "direction_model_name": c.notes.get("direction_model_name", ""),
            "direction_model_status": c.notes.get("direction_model_status", ""),
            "direction_model_disagreement": c.notes.get("direction_model_disagreement", ""),
            "gate_snapshot_id": c.notes.get("gate_snapshot_id", ""),
            "gate_learning_status": c.notes.get("gate_learning_status", ""),
            "gate_learning_observations": c.notes.get("gate_learning_observations", ""),
            "gate_learning_sessions": c.notes.get("gate_learning_sessions", ""),
            "gate_learning_outcomes": c.notes.get("gate_learning_outcomes", ""),
            "gate_contract_quality_min": c.notes.get("gate_contract_quality_min", ""),
            "gate_direction_min": c.notes.get("gate_direction_min", ""),
            "gate_premium_elasticity_min": c.notes.get("gate_premium_elasticity_min", ""),
            "gate_expected_required_ratio_min": c.notes.get("gate_expected_required_ratio_min", ""),
            "gate_trade_quality_min": c.notes.get("gate_trade_quality_min", ""),
            "gate_final_confidence_min": c.notes.get("gate_final_confidence_min", ""),
            "gate_market_hostility_max": c.notes.get("gate_market_hostility_max", ""),
            "gate_iv_crush_max": c.notes.get("gate_iv_crush_max", ""),
            "gate_min_top_book_lots": c.notes.get("gate_min_top_book_lots", ""),
            "gate_min_5depth_lots_each_side": c.notes.get("gate_min_5depth_lots_each_side", ""),
            "cost_model_status": c.notes.get("cost_model_status", "UNSPECIFIED"),
            "cost_model_valid": c.notes.get("cost_model_valid", False),
            "canonical_promotion_allowed": c.notes.get("canonical_promotion_allowed", False),
            "iv_context_status": c.notes.get("iv_context_status", "UNAVAILABLE"),
            "iv_context_reason": c.notes.get("iv_context_reason", ""),
            "iv_context_source": c.notes.get("iv_context_source", ""),
            "trade_quality": round(c.trade_quality_score, 1),
            "market_hostility": round(c.market_hostility_score, 1),
            "iv_crush": round(c.iv_crush_risk_score, 1),
            "convexity": round(c.convexity_edge_score, 1),
            "execution": round(c.execution_quality_score, 1),
            "confidence": round(c.opportunity_confidence_score, 1),
            "regime_fit": round(c.regime_fit_score, 1),
            "premium_elasticity": round(c.premium_elasticity, 3),
            "observed_elasticity_status": c.notes.get("observed_elasticity_status", "UNAVAILABLE"),
            "observed_elasticity_post_cost_delta_adjusted": c.notes.get("observed_elasticity_post_cost_delta_adjusted", ""),
            "expected_value_r": c.expected_value_r,
            "expected_value_status": c.notes.get("expected_value_status", "UNVALIDATED_COST_MODEL"),
            "same_direction_recent_loss": c.notes.get("same_direction_recent_loss", False),
            "expected_move": round(c.expected_move, 1),
            "required_move": round(c.required_move, 1),
            "exp_req_ratio": round(c.expected_required_ratio, 2),
            "bid": c.quote.bid,
            "ask": c.quote.ask,
            "mid": round(mid, 2),
            "spread_pct": round(c.quote.spread / mid * 100, 2) if mid > 0 else 99.0,
            "depth_evidence": c.notes.get("depth_evidence", "FIVE_LEVEL" if c.quote.cumulative_bid_qty_5depth is not None and c.quote.cumulative_ask_qty_5depth is not None else "TOP_BOOK_ONLY" if c.quote.bid_qty > 0 and c.quote.ask_qty > 0 else "UNAVAILABLE"),
            "depth_source": c.notes.get("depth_source", "FYERS_MARKET_DEPTH" if c.quote.source_timestamp_available else "UNAVAILABLE"),
            "depth_bid_levels": c.notes.get("depth_bid_levels", 5 if c.quote.cumulative_bid_qty_5depth is not None else 0),
            "depth_ask_levels": c.notes.get("depth_ask_levels", 5 if c.quote.cumulative_ask_qty_5depth is not None else 0),
            "bid_qty": c.quote.bid_qty,
            "ask_qty": c.quote.ask_qty,
            "cumulative_bid_qty_5depth": c.quote.cumulative_bid_qty_5depth if c.quote.cumulative_bid_qty_5depth is not None else "",
            "cumulative_ask_qty_5depth": c.quote.cumulative_ask_qty_5depth if c.quote.cumulative_ask_qty_5depth is not None else "",
            "quote_timestamp": c.quote.timestamp.isoformat(),
            "source_timestamp_available": str(c.quote.source_timestamp_available),
            "reasons": "; ".join(e.reasons),
            "calibrated_probability": c.calibrated_success_probability if c.calibrated_success_probability is not None else "",
            "calibrated_expectancy_r": c.calibrated_net_expectancy_r if c.calibrated_net_expectancy_r is not None else "",
        }


def build_evidence_report(state_dir: str | Path, config: Optional[SystemConfig] = None,
                          emergency_tests_passed: bool = False) -> str:
    """Run the phase-2 gate + evidence review over the accumulated paper data."""
    cfg = config or SystemConfig.from_file("uploads/PARAMETERS.json")
    state = Path(state_dir)
    mtil = CsvDataset.from_csv(state / "mtil.csv")
    skipped = CsvDataset.from_csv(state / "skipped.csv")

    acceptance = DryRunValidator(cfg).validate(
        mtil, skipped, emergency_tests_passed=emergency_tests_passed)
    review = EvidenceAnalyzer().analyze(mtil, skipped)

    lines: list[str] = []
    lines.append("=" * 74)
    lines.append("PAPER-EVIDENCE REPORT  (proxy scores vs trade outcomes)")
    lines.append(f"state dir: {state}")
    profile = cfg.raw.get("evidence_profiles", {})
    if isinstance(profile, Mapping):
        lines.append(
            "EVIDENCE PROFILE: "
            f"{profile.get('active_profile', 'UNSPECIFIED')} "
            f"| elasticity={profile.get('elasticity_status', 'UNSPECIFIED')} "
            f"| mapping={profile.get('mapping_status', 'UNSPECIFIED')} "
            f"| cost={profile.get('cost_status', 'UNSPECIFIED')} "
            f"| canonical_exclusion={profile.get('exclude_from_canonical_validation', 'UNKNOWN')}"
        )
    lines.append("=" * 74)
    lines.append("")
    manifest_path = state / "run_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            lines.append(f"RUN PROVENANCE: policy_signature={manifest.get('policy_signature', 'UNKNOWN')} universe_count={len(manifest.get('universe', {}).get('underlyings', []))} live_execution={manifest.get('live_execution', 'UNKNOWN')}")
        except (OSError, json.JSONDecodeError):
            lines.append("RUN PROVENANCE: INVALID_MANIFEST")
    else:
        lines.append("RUN PROVENANCE: LEGACY_OR_UNKNOWN_STATE — do not mix with revised policy evidence")
    lines.append("")
    lines.append(acceptance.summary_text())
    lines.append("")
    lines.append(review.summary_text())
    lines.append("")
    lines.append("CALIBRATION: does a higher proxy score predict better outcomes?")
    lines.append(_calibration_table("OpportunityScore", review.opportunity_score_buckets))
    lines.append(_calibration_table("ExpectedValue_R", review.ev_buckets))
    lines.append(_calibration_table("VolEdgeRatio", review.vol_edge_buckets))
    if review.skipped_analysis is not None:
        s = review.skipped_analysis
        lines.append("")
        lines.append(f"SKIPPED CANDIDATES: {s.total_skipped} logged, "
                     f"{s.skipped_winner_rate:.2%} would-have-hit-target, "
                     f"{s.no_trade_saved_loss_rate:.2%} would-have-hit-stop")
    forward_path = state / "skipped_forward_outcomes.csv"
    if forward_path.exists():
        try:
            with forward_path.open("r", encoding="utf-8-sig", newline="") as f:
                forward_rows = list(csv.DictReader(f))
            observed = [r for r in forward_rows if str(r.get("status", "")).upper() == "OBSERVED"]
            unavailable = len(forward_rows) - len(observed)
            lines.append("")
            lines.append(f"SKIPPED FORWARD OUTCOMES: {len(forward_rows)} windows, {len(observed)} observed, {unavailable} unavailable")
        except (OSError, csv.Error):
            lines.append("SKIPPED FORWARD OUTCOMES: INVALID_STREAM")
    else:
        lines.append("")
        lines.append("SKIPPED FORWARD OUTCOMES: NOT_STARTED")
    lines.append("")
    lines.append("NOTE: rows carry the PROXY scores from paper_signal.py. A flat or")
    lines.append("inverted calibration table is the signal that the proxies need work")
    lines.append("before any live-trading decision. Score buckets with <5 trades are")
    lines.append("not statistically meaningful.")
    return "\n".join(lines)


def build_top_candidates_report(state_dir: str | Path, top_n: int = 10,
                                day: Optional[str] = None) -> str:
    """Top-N candidates per day (by ComparableOpportunityScore) from the
    candidates log written by the paper runner, with per-candidate component
    detail. Purpose: threshold calibration - it shows the score ceiling and
    distribution each day, so the excellent-gate threshold can be judged
    against what the market actually offered instead of being tuned blind."""
    state = Path(state_dir)
    path = state / "candidates_log.csv"
    if not path.exists():
        return ("TOP-CANDIDATES REPORT\n"
                "no candidates_log.csv yet - run the paper runner during a market\n"
                "session first (the runner samples every candidate once per minute).\n")
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if day is not None and r.get("date") != day:
                continue
            rows.append(r)
    if not rows:
        return f"TOP-CANDIDATES REPORT\nno candidate rows for day={day} in {path}\n"

    def fnum(v: Any) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    by_day: dict[str, list] = {}
    for r in rows:
        by_day.setdefault(r.get("date") or "?", []).append(r)

    lines = [
        "=" * 74,
        f"TOP-{top_n} CANDIDATES BY DAY  (ComparableOpportunityScore, sampled 1/min)",
        f"state dir: {state}",
        "=" * 74,
    ]
    all_scores: list[float] = []
    for d in sorted(by_day):
        day_rows = sorted(by_day[d],
                          key=lambda r: fnum(r.get("comparable_score")), reverse=True)
        scores = [fnum(r.get("comparable_score")) for r in day_rows]
        all_scores.extend(scores)
        n = len(scores)
        mean = sum(scores) / n
        p90 = sorted(scores)[int(n * 0.90) - 1] if n else 0.0
        over80 = sum(1 for s in scores if s >= 80.0)
        lines.append("")
        lines.append(f"DAY {d}   rows={n}  max={max(scores):.1f}  mean={mean:.1f}  "
                     f"p90={p90:.1f}  candidates>=80: {over80}")
        lines.append("  #   score   thr   gr elig und      side strike   expiry    exp/req"
                     "   prem  spread%  decision")
        for rank, r in enumerate(day_rows[:top_n], start=1):
            exp = str(r.get("expiry") or "")[5:10]
            dte = str(r.get("dte") or "?")
            lines.append(
                f"  {rank:>2}  {fnum(r.get('comparable_score')):6.1f}  "
                f"{fnum(r.get('threshold')):5.1f}  {str(r.get('grade')):<2}  "
                f"{str(r.get('eligible')):<4} {str(r.get('underlying')):<9} "
                f"{str(r.get('side')):<2} {fnum(r.get('strike')):>7.0f}  "
                f"{exp}({dte}d)  {fnum(r.get('exp_req_ratio')):6.2f}  "
                f"{fnum(r.get('mid')):7.1f}  {fnum(r.get('spread_pct')):6.2f}  "
                f"{str(r.get('decision'))}")
            lines.append(
                f"      dir={fnum(r.get('direction')):5.1f} "
                f"tq={fnum(r.get('trade_quality')):5.1f} "
                f"host={fnum(r.get('market_hostility')):5.1f} "
                f"conv={fnum(r.get('convexity')):5.1f} "
                f"exec={fnum(r.get('execution')):5.1f} "
                f"conf={fnum(r.get('confidence')):5.1f} "
                f"reg={fnum(r.get('regime_fit')):5.1f}  "
                f"why: {(str(r.get('reasons')) or '-')[:70]}")
    if all_scores:
        amax = max(all_scores)
        ndays = len(by_day)
        days_over80 = sum(
            1 for d in by_day.values()
            if any(fnum(r.get("comparable_score")) >= 80.0 for r in d))
        lines.append("")
        lines.append("-" * 74)
        lines.append("SCORE DISTRIBUTION (all days, comparable score)")
        for lo in range(0, 100, 10):
            cnt = sum(1 for s in all_scores if lo <= s < lo + 10)
            lines.append(f"  {lo:>3}-{lo + 10:>3}: {cnt}")
        lines.append("")
        lines.append("THRESHOLD INSIGHT")
        lines.append(f"  all-time max score: {amax:.1f}")
        lines.append(f"  days with any candidate >= 80: {days_over80} / {ndays}")
        lines.append("  A day's max/p90 below the excellent gate means the threshold may be")
        lines.append("  unreachable in current conditions; a max well above it with no trade")
        lines.append("  suggests the gate or the score components need review.")
    return "\n".join(lines)


def _calibration_table(title: str, buckets: Iterable) -> str:
    rows = list(buckets)
    if not rows:
        return f"{title}: no data yet"
    header = f"{title:<16} {'n':>4} {'win%':>7} {'avgR':>7} {'predEV':>7} {'volEdge':>8}"
    body = [header]
    for b in rows:
        body.append(f"{b.bucket:<16} {b.count:>4} {b.win_rate:>7.1%} "
                    f"{b.avg_actual_r:>7.2f} {b.avg_predicted_ev_r:>7.2f} {b.avg_vol_edge_ratio:>8.2f}")
    return "\n".join(body)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Generate the paper-evidence phase-2 report")
    ap.add_argument("--state-dir", default="paper_state")
    ap.add_argument("--emergency-tests-passed", action="store_true",
                    help="Mark the emergency-tests check as passed (run the test suite first)")
    ap.add_argument("--top-candidates", action="store_true",
                    help="Also build the per-day top-N candidates report")
    ap.add_argument("--top", type=int, default=10,
                    help="Top-N candidates per day in the top report (default 10)")
    ap.add_argument("--date", default=None,
                    help="Restrict the top-candidates report to one YYYY-MM-DD")
    args = ap.parse_args()
    text = build_evidence_report(args.state_dir,
                                 emergency_tests_passed=args.emergency_tests_passed)
    out = Path(args.state_dir) / "evidence_report.txt"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n[wrote {out}]")
    if args.top_candidates:
        top_text = build_top_candidates_report(args.state_dir, top_n=args.top, day=args.date)
        top_out = Path(args.state_dir) / "top_candidates_report.txt"
        top_out.write_text(top_text, encoding="utf-8")
        print(f"\n[wrote {top_out}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
