from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from .analytics import PerformanceSummary, summarize_pnl
from .config import SystemConfig


def _parse_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "hit", "win"}


def _parse_date(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    observed: float | str
    required: float | str
    severity: str
    message: str


@dataclass(frozen=True)
class DryRunAcceptanceResult:
    passed: bool
    checks: tuple[CheckResult, ...]

    def summary_text(self) -> str:
        lines = [f"DRY-RUN ACCEPTANCE: {'PASS' if self.passed else 'FAIL'}"]
        for c in self.checks:
            status = "PASS" if c.passed else "FAIL"
            lines.append(f"[{status}] {c.name}: observed={c.observed} required={c.required} severity={c.severity} - {c.message}")
        return "\n".join(lines)


@dataclass(frozen=True)
class GroupPerformance:
    group_key: str
    summary: PerformanceSummary
    avg_r: float
    avg_opportunity_score: float
    avg_expected_value_r: float
    avg_vol_edge_ratio: float
    premium_failure_rate: float
    avg_entry_slippage_points: float
    avg_exit_slippage_points: float


@dataclass(frozen=True)
class CalibrationBucket:
    bucket: str
    count: int
    win_rate: float
    avg_actual_r: float
    avg_predicted_ev_r: float
    avg_vol_edge_ratio: float


@dataclass(frozen=True)
class SkippedCandidateAnalysis:
    total_skipped: int
    skipped_winners: int
    skipped_losers: int
    skipped_winner_rate: float
    no_trade_saved_loss_rate: float


@dataclass(frozen=True)
class EvidenceReview:
    overall: PerformanceSummary
    by_instrument: tuple[GroupPerformance, ...]
    by_archetype: tuple[GroupPerformance, ...]
    by_regime: tuple[GroupPerformance, ...]
    opportunity_score_buckets: tuple[CalibrationBucket, ...]
    ev_buckets: tuple[CalibrationBucket, ...]
    vol_edge_buckets: tuple[CalibrationBucket, ...]
    skipped_analysis: Optional[SkippedCandidateAnalysis]
    midcap_summary: Optional[GroupPerformance]

    def summary_text(self) -> str:
        lines = ["EVIDENCE REVIEW", "Overall:", _summary_line("ALL", self.overall)]
        lines.append("By Instrument:")
        lines += [_group_line(g) for g in self.by_instrument]
        lines.append("By Archetype:")
        lines += [_group_line(g) for g in self.by_archetype]
        lines.append("By Regime:")
        lines += [_group_line(g) for g in self.by_regime]
        if self.skipped_analysis:
            s = self.skipped_analysis
            lines.append(f"Skipped: total={s.total_skipped} skipped_winner_rate={s.skipped_winner_rate:.2%} no_trade_saved_loss_rate={s.no_trade_saved_loss_rate:.2%}")
        if self.midcap_summary:
            lines.append("Midcap:")
            lines.append(_group_line(self.midcap_summary))
        return "\n".join(lines)


def _summary_line(key: str, s: PerformanceSummary) -> str:
    return f"{key}: trades={s.trades} win_rate={s.win_rate:.2%} expectancy={s.expectancy:.2f} profit_factor={s.profit_factor:.2f} net_pnl={s.net_pnl:.2f} max_dd={s.max_drawdown:.2f}"


def _group_line(g: GroupPerformance) -> str:
    return f"{g.group_key}: trades={g.summary.trades} win_rate={g.summary.win_rate:.2%} expectancy={g.summary.expectancy:.2f} avg_R={g.avg_r:.2f} avg_score={g.avg_opportunity_score:.2f} premium_fail={g.premium_failure_rate:.2%}"


class CsvDataset:
    def __init__(self, rows: Iterable[Mapping[str, Any]]):
        self.rows = tuple(dict(r) for r in rows)

    @classmethod
    def from_csv(cls, path: str | Path) -> "CsvDataset":
        p = Path(path)
        if not p.exists():
            return cls([])
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            return cls(csv.DictReader(f))

    def unique_dates(self) -> set[date]:
        dates: set[date] = set()
        for r in self.rows:
            d = _parse_date(r.get("date") or r.get("timestamp"))
            if d:
                dates.add(d)
        return dates

    def unique_values(self, field: str) -> set[str]:
        return {str(r.get(field, "")).strip() for r in self.rows if str(r.get(field, "")).strip()}

    def numeric(self, field: str) -> list[float]:
        return [_parse_float(r.get(field)) for r in self.rows]


class DryRunValidator:
    def __init__(self, config: SystemConfig):
        self.config = config
        self.criteria = config.section("phase1_dry_run_acceptance")

    def validate(self, mtil: CsvDataset, skipped: Optional[CsvDataset] = None, dashboard_latency_pass_rate_pct: Optional[float] = None, emergency_tests_passed: bool = False) -> DryRunAcceptanceResult:
        skipped = skipped or CsvDataset([])
        checks: list[CheckResult] = []
        min_days = int(self.criteria["minimum_trading_days"])
        days = len(mtil.unique_dates() | skipped.unique_dates())
        checks.append(CheckResult("minimum_trading_days", days >= min_days, days, min_days, "CRITICAL", "Minimum dry-run market days captured."))
        min_cycles = int(self.criteria["minimum_ranking_cycles"])
        cycles = len(mtil.unique_values("ranking_cycle_id") | skipped.unique_values("ranking_cycle_id"))
        checks.append(CheckResult("minimum_ranking_cycles", cycles >= min_cycles, cycles, min_cycles, "CRITICAL", "Ranking cycles recorded."))
        min_candidates = int(self.criteria["minimum_paper_trade_candidates"])
        candidates = len(mtil.rows) + len(skipped.rows)
        checks.append(CheckResult("minimum_paper_trade_candidates", candidates >= min_candidates, candidates, min_candidates, "CRITICAL", "Simulated/tracked candidates recorded."))
        final_dates = sorted(mtil.unique_dates() | skipped.unique_dates())[-5:]
        final_date_set = set(final_dates)
        final_rows = [
            row
            for rows in (mtil.rows, skipped.rows)
            for row in rows
            if _parse_date(row.get("date") or row.get("timestamp")) in final_date_set
        ] if final_dates else []
        mapping_flags = [r.get("mapping_validation_passed") for r in final_rows if r.get("mapping_validation_passed") not in (None, "")]
        mapping_errors = sum(1 for v in mapping_flags if not _parse_bool(v)) if mapping_flags else self._count_rule_text(final_rows, ["mapping", "security", "instrument"])
        checks.append(CheckResult("critical_mapping_errors_final_5_days", mapping_errors == 0, mapping_errors, 0, "CRITICAL", "No critical mapping errors in final five dry-run days."))
        lot_flags = [r.get("lot_size_validation_passed") for r in final_rows if r.get("lot_size_validation_passed") not in (None, "")]
        tick_flags = [r.get("tick_size_validation_passed") for r in final_rows if r.get("tick_size_validation_passed") not in (None, "")]
        if lot_flags or tick_flags:
            lot_tick_errors = sum(1 for v in lot_flags if not _parse_bool(v)) + sum(1 for v in tick_flags if not _parse_bool(v))
        else:
            lot_tick_errors = self._count_rule_text(final_rows, ["lot", "tick"])
        checks.append(CheckResult("wrong_lot_tick_calculations", lot_tick_errors == 0, lot_tick_errors, 0, "CRITICAL", "No wrong lot-size or tick-size calculations."))
        reval_values = []
        for row in mtil.rows:
            value = row.get("entry_revalidation_passed")
            if value in (None, ""):
                profile = f"{row.get('schema_version', '')} {row.get('parameter_profile', '')}".upper()
                if "LEGACY" in profile:
                    value = row.get("revalidation_passed")
            if value not in (None, ""):
                reval_values.append(value)
        reval_ok = bool(reval_values) and all(_parse_bool(v) for v in reval_values)
        checks.append(CheckResult("candidate_revalidation", reval_ok, f"{sum(_parse_bool(v) for v in reval_values)}/{len(reval_values)}", "all true", "CRITICAL", "Candidate revalidation recorded and passed."))
        paper_fill_active = any(str(r.get("paper_fill_model", "")).strip() for r in mtil.rows) or any(str(r.get("simulated_entry_fill", "")).strip() for r in mtil.rows) or any(str(r.get("entry_fill_price", "")).strip() for r in mtil.rows)
        checks.append(CheckResult("paper_fill_simulator_active", paper_fill_active, paper_fill_active, True, "CRITICAL", "Paper-fill simulator evidence present."))
        mtil_complete = self._mtil_core_completeness(mtil) >= 0.95 if mtil.rows else False
        checks.append(CheckResult("mtil_core_completeness", mtil_complete, f"{self._mtil_core_completeness(mtil):.2%}", ">=95%", "CRITICAL", "Core MTIL fields are populated."))
        cost_values = [r.get("cost_model_valid") for r in mtil.rows]
        cost_fields_present = bool(mtil.rows) and all(value not in (None, "") for value in cost_values)
        canonical_values = [r.get("canonical_promotion_allowed") for r in mtil.rows]
        canonical_fields_present = bool(mtil.rows) and all(value not in (None, "") for value in canonical_values)
        cost_boundary_ok = cost_fields_present and all(_parse_bool(value) for value in cost_values)
        canonical_boundary_ok = canonical_fields_present and all(_parse_bool(value) for value in canonical_values)
        checks.append(CheckResult(
            "cost_model_validity",
            cost_boundary_ok,
            f"{sum(_parse_bool(value) for value in cost_values)}/{len(cost_values)}; fields_present={cost_fields_present}",
            "all MTIL rows true with field present",
            "CRITICAL",
            "Canonical acceptance requires explicit validated transaction-cost evidence; placeholder or missing cost flags fail closed.",
        ))
        checks.append(CheckResult(
            "canonical_promotion_boundary",
            canonical_boundary_ok,
            f"{sum(_parse_bool(value) for value in canonical_values)}/{len(canonical_values)}; fields_present={canonical_fields_present}",
            "all MTIL rows true with field present",
            "CRITICAL",
            "Canonical promotion must be explicitly allowed on every accepted MTIL row.",
        ))
        skipped_complete = self._skipped_core_completeness(skipped) >= 0.90 if skipped.rows else False
        checks.append(CheckResult("skipped_candidate_logging", skipped_complete, f"{self._skipped_core_completeness(skipped):.2%}", ">=90%", "CRITICAL", "Skipped candidate log fields are populated."))
        if dashboard_latency_pass_rate_pct is not None:
            req = float(self.criteria["dashboard_ranking_latency_pass_rate_pct"])
            checks.append(CheckResult("dashboard_latency_pass_rate", dashboard_latency_pass_rate_pct >= req, dashboard_latency_pass_rate_pct, req, "HIGH", "Dashboard ranking latency pass rate."))
        checks.append(CheckResult("emergency_tests_passed", emergency_tests_passed is True, emergency_tests_passed, True, "CRITICAL", "Emergency tests must pass before live review."))
        passed = all(c.passed for c in checks if c.severity == "CRITICAL")
        return DryRunAcceptanceResult(passed, tuple(checks))

    @staticmethod
    def _count_rule_text(rows: Iterable[Mapping[str, Any]], keywords: list[str]) -> int:
        count = 0
        for r in rows:
            text = " ".join(str(r.get(k, "")) for k in ("rule_violations", "rule_violation_type", "exit_reason_primary", "signal_failure_cause", "execution_failure_cause")).lower()
            if any(k in text for k in keywords):
                count += 1
        return count

    @staticmethod
    def _mtil_core_completeness(dataset: CsvDataset) -> float:
        if not dataset.rows:
            return 0.0
        core = ["trade_id", "date", "instrument", "option_type", "OpportunityScore", "OpportunityGrade", "DirectionScore", "TradeQualityScore", "ContractQualityScore", "MarketHostilityScore", "planned_risk_rupees", "net_pnl_rupees", "r_multiple", "trade_archetype_code", "signal_combination_id", "regime_combination_id", "opportunity_cluster_id"]
        total = len(dataset.rows) * len(core)
        filled = sum(1 for r in dataset.rows for f in core if r.get(f) not in (None, ""))
        return filled / total if total else 0.0

    @staticmethod
    def _skipped_core_completeness(dataset: CsvDataset) -> float:
        if not dataset.rows:
            return 0.0
        core = ["skip_id", "timestamp", "ranking_cycle_id", "underlying", "option_type", "rank", "OpportunityScore", "why_not_traded", "calibration_status"]
        total = len(dataset.rows) * len(core)
        filled = sum(1 for r in dataset.rows for f in core if r.get(f) not in (None, ""))
        return filled / total if total else 0.0


class EvidenceAnalyzer:
    def analyze(self, mtil: CsvDataset, skipped: Optional[CsvDataset] = None) -> EvidenceReview:
        skipped = skipped or CsvDataset([])
        overall = summarize_pnl(mtil.numeric("net_pnl_rupees"))
        by_inst = self._group_performance(mtil, "instrument")
        by_arch = self._group_performance(mtil, "trade_archetype_code")
        by_regime = self._group_performance(mtil, "primary_regime")
        opp_buckets = self._bucket_calibration(mtil, "OpportunityScore", self._score_bucket)
        ev_buckets = self._bucket_calibration(mtil, "ExpectedValue_R", self._ev_bucket)
        vol_buckets = self._bucket_calibration(mtil, "VolEdgeRatio", self._vol_bucket)
        skipped_analysis = self._skipped(skipped) if skipped.rows else None
        mid = next((g for g in by_inst if g.group_key == "MIDCPNIFTY"), None)
        return EvidenceReview(overall, by_inst, by_arch, by_regime, opp_buckets, ev_buckets, vol_buckets, skipped_analysis, mid)

    def _group_performance(self, dataset: CsvDataset, field: str) -> tuple[GroupPerformance, ...]:
        groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for r in dataset.rows:
            key = str(r.get(field) or "UNKNOWN")
            groups[key].append(r)
        out: list[GroupPerformance] = []
        for key, rows in sorted(groups.items()):
            pnls = [_parse_float(r.get("net_pnl_rupees")) for r in rows]
            summary = summarize_pnl(pnls)
            out.append(GroupPerformance(
                key,
                summary,
                self._avg(rows, "r_multiple"),
                self._avg(rows, "OpportunityScore"),
                self._avg(rows, "ExpectedValue_R"),
                self._avg(rows, "VolEdgeRatio"),
                self._rate(rows, "premium_failure_flag"),
                self._avg(rows, "entry_slippage_points"),
                self._avg(rows, "exit_slippage_points"),
            ))
        return tuple(out)

    def _bucket_calibration(self, dataset: CsvDataset, field: str, bucket_fn) -> tuple[CalibrationBucket, ...]:
        groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for r in dataset.rows:
            groups[bucket_fn(_parse_float(r.get(field)))].append(r)
        out = []
        for bucket, rows in sorted(groups.items()):
            wins = sum(1 for r in rows if _parse_float(r.get("net_pnl_rupees")) > 0)
            count = len(rows)
            out.append(CalibrationBucket(
                bucket,
                count,
                wins / count if count else 0.0,
                self._avg(rows, "r_multiple"),
                self._avg(rows, "ExpectedValue_R"),
                self._avg(rows, "VolEdgeRatio"),
            ))
        return tuple(out)

    @staticmethod
    def _score_bucket(v: float) -> str:
        if v >= 90: return "90+"
        if v >= 80: return "80-89"
        if v >= 70: return "70-79"
        if v >= 60: return "60-69"
        return "<60"

    @staticmethod
    def _ev_bucket(v: float) -> str:
        if v >= 0.75: return "EV_0.75+"
        if v >= 0.30: return "EV_0.30_0.74"
        if v > 0: return "EV_0_0.29"
        return "EV_<=0"

    @staticmethod
    def _vol_bucket(v: float) -> str:
        if v >= 2.0: return "VOL_2.0+"
        if v >= 1.6: return "VOL_1.6_1.99"
        if v >= 1.3: return "VOL_1.3_1.59"
        return "VOL_<1.3"

    @staticmethod
    def _avg(rows: list[Mapping[str, Any]], field: str) -> float:
        vals = [_parse_float(r.get(field)) for r in rows if r.get(field) not in (None, "")]
        return sum(vals) / len(vals) if vals else 0.0

    @staticmethod
    def _rate(rows: list[Mapping[str, Any]], field: str) -> float:
        vals = [r.get(field) for r in rows if r.get(field) not in (None, "")]
        return sum(_parse_bool(v) for v in vals) / len(vals) if vals else 0.0

    @staticmethod
    def _skipped(skipped: CsvDataset) -> SkippedCandidateAnalysis:
        target = sum(_parse_bool(r.get("would_have_hit_target")) for r in skipped.rows)
        stop = sum(_parse_bool(r.get("would_have_hit_stop")) for r in skipped.rows)
        total = len(skipped.rows)
        return SkippedCandidateAnalysis(
            total,
            target,
            stop,
            target / total if total else 0.0,
            stop / total if total else 0.0,
        )


class Phase2ReportWriter:
    @staticmethod
    def write_text(path: str | Path, acceptance: DryRunAcceptanceResult, review: EvidenceReview) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(acceptance.summary_text() + "\n\n" + review.summary_text(), encoding="utf-8")
        return p
