from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional

from .analytics import PerformanceSummary
from .config import SystemConfig
from .phase2 import DryRunAcceptanceResult, EvidenceReview


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    passed: bool
    severity: str
    message: str


@dataclass(frozen=True)
class LiveReadinessDecision:
    approved_for_manual_live_review: bool
    approved_for_live_orders: bool
    checks: tuple[ReadinessCheck, ...]

    def summary_text(self) -> str:
        lines = [
            f"MANUAL LIVE REVIEW READY: {'YES' if self.approved_for_manual_live_review else 'NO'}",
            f"LIVE ORDERS APPROVED: {'YES' if self.approved_for_live_orders else 'NO'}",
        ]
        for c in self.checks:
            lines.append(f"[{'PASS' if c.passed else 'FAIL'}] {c.name} ({c.severity}) - {c.message}")
        return "\n".join(lines)


@dataclass(frozen=True)
class ManualLiveChecklist:
    items: tuple[str, ...]


@dataclass(frozen=True)
class PaperVsLiveFillComparisonPlan:
    required_fields: tuple[str, ...]
    stop_thresholds: Mapping[str, float]


@dataclass(frozen=True)
class LiveMicroTestRules:
    max_open_positions: int
    max_pending_orders: int
    max_trades_per_day: int
    max_risk_per_trade_rupees: float
    allowed_order_type: str
    allowed_mode: str
    must_log_to_mtil: bool


@dataclass(frozen=True)
class LiveStopCriteria:
    criteria: tuple[str, ...]


class ChargesVerifier:
    """Verifies whether the cost model uses confirmed broker/statutory rates."""

    @staticmethod
    def verify(charges_path: str | Path) -> ReadinessCheck:
        p = Path(charges_path)
        if not p.exists():
            return ReadinessCheck("cost_model_verified", False, "CRITICAL", "Charges config file missing.")
        raw = json.loads(p.read_text())
        status = str(raw.get("status", "")).upper()
        if "PLACEHOLDER" in status or not status:
            return ReadinessCheck("cost_model_verified", False, "CRITICAL", "Charges config still marked placeholder; verify broker/statutory rates before live.")
        required = ["brokerage_per_order_rupees", "gst_rate_pct", "stt_sell_rate_pct", "exchange_transaction_charge_rate_pct", "sebi_turnover_fee_rate_pct", "stamp_duty_buy_rate_pct"]
        missing = [k for k in required if raw.get(k) is None]
        if missing:
            return ReadinessCheck("cost_model_verified", False, "CRITICAL", f"Charges config missing values: {missing}")
        return ReadinessCheck("cost_model_verified", True, "CRITICAL", "Charges config appears verified.")


class RuleViolationAnalyzer:
    @staticmethod
    def check_no_pattern(rule_violation_count: int, critical_rule_violation_count: int) -> ReadinessCheck:
        if critical_rule_violation_count > 0:
            return ReadinessCheck("rule_violation_pattern", False, "CRITICAL", f"Critical rule violations found: {critical_rule_violation_count}")
        if rule_violation_count > 0:
            return ReadinessCheck("rule_violation_pattern", False, "HIGH", f"Non-critical rule violations found: {rule_violation_count}; review before live.")
        return ReadinessCheck("rule_violation_pattern", True, "CRITICAL", "No rule violation pattern detected.")


class LiveReadinessReviewer:
    """Phase 3 investment-committee readiness evaluator.

    This does not enable live trading. It only determines whether evidence is strong enough
    to be reviewed for possible manual-live testing.
    """

    def __init__(self, config: SystemConfig):
        self.config = config

    def review(
        self,
        phase2_acceptance: DryRunAcceptanceResult,
        evidence: EvidenceReview,
        charges_check: ReadinessCheck,
        emergency_exit_plan_verified: bool,
        daily_loss_lock_designed: bool,
        rule_violation_count: int = 0,
        critical_rule_violation_count: int = 0,
        committee_approved_live_orders: bool = False,
    ) -> LiveReadinessDecision:
        checks: list[ReadinessCheck] = []
        checks.append(ReadinessCheck("phase2_acceptance", phase2_acceptance.passed, "CRITICAL", "Phase 2 dry-run acceptance must pass."))
        execution = self.config.section("execution")
        demo_trade = execution.get("demo_trade", True)
        checks.append(ReadinessCheck("live_orders_disabled_by_default", demo_trade is True, "CRITICAL", "demo_trade must remain true by default before any live approval."))
        checks.append(charges_check)
        checks.append(ReadinessCheck("emergency_exit_plan_verified", emergency_exit_plan_verified, "CRITICAL", "Emergency exit plan must be verified."))
        checks.append(ReadinessCheck("daily_loss_lock_designed", daily_loss_lock_designed, "CRITICAL", "Daily loss lock must be designed before live."))
        checks.append(RuleViolationAnalyzer.check_no_pattern(rule_violation_count, critical_rule_violation_count))
        checks.append(self._evidence_quality_check(evidence.overall))
        # Phase 3 is a readiness-review phase, not a live-order enablement phase.
        # Even if the committee parameter is passed, this module must not approve live orders.
        # A separate future deployment-control module must perform the explicit demo_trade=False switch.
        critical_pass = all(c.passed for c in checks if c.severity == "CRITICAL")
        manual_review_ready = critical_pass
        live_orders_approved = False
        checks.append(ReadinessCheck(
            "phase3_live_order_block",
            True,
            "CRITICAL",
            "Phase 3 cannot approve live orders; it can only approve readiness for manual-live review.",
        ))
        return LiveReadinessDecision(manual_review_ready, live_orders_approved, tuple(checks))

    @staticmethod
    def _evidence_quality_check(summary: PerformanceSummary) -> ReadinessCheck:
        if summary.trades <= 0:
            return ReadinessCheck("paper_evidence_quality", False, "CRITICAL", "No simulated trades/candidates in evidence review.")
        if summary.expectancy < 0:
            return ReadinessCheck("paper_evidence_quality", False, "HIGH", f"Paper expectancy is negative: {summary.expectancy:.2f}")
        return ReadinessCheck("paper_evidence_quality", True, "HIGH", f"Paper expectancy non-negative: {summary.expectancy:.2f}")


class Phase3Artifacts:
    @staticmethod
    def manual_live_checklist() -> ManualLiveChecklist:
        return ManualLiveChecklist((
            "Investment committee approval recorded",
            "Phase 2 dry-run acceptance passed",
            "Cost model verified with broker/statutory rates",
            "Emergency exit plan verified",
            "Daily loss lock designed",
            "demo_trade default remains true until explicit manual-live approval",
            "Max open positions remains 1",
            "Max pending orders remains 1",
            "No auto-execution",
            "No option selling",
            "No leverage or pledge",
            "MTIL logging active",
            "Paper-vs-live fill comparison plan active",
            "Stop criteria accepted before first live test",
        ))

    @staticmethod
    def paper_vs_live_fill_plan() -> PaperVsLiveFillComparisonPlan:
        return PaperVsLiveFillComparisonPlan(
            required_fields=(
                "paper_entry_fill", "live_entry_fill", "paper_exit_fill", "live_exit_fill",
                "entry_slippage_difference_points", "exit_slippage_difference_points",
                "fill_latency_seconds", "spread_at_order", "spread_at_fill", "order_rejection_flag",
            ),
            stop_thresholds={
                "avg_extra_slippage_points": 2.0,
                "single_trade_extra_slippage_points": 5.0,
                "order_rejection_count": 1.0,
                "missing_mtil_log_count": 1.0,
            },
        )

    @staticmethod
    def live_micro_test_rules() -> LiveMicroTestRules:
        return LiveMicroTestRules(
            max_open_positions=1,
            max_pending_orders=1,
            max_trades_per_day=1,
            max_risk_per_trade_rupees=500.0,
            allowed_order_type="manual_marketable_limit_only",
            allowed_mode="MANUAL_MICRO_LIVE_ONLY_AFTER_APPROVAL",
            must_log_to_mtil=True,
        )

    @staticmethod
    def live_stop_criteria() -> LiveStopCriteria:
        return LiveStopCriteria((
            "Any rule violation",
            "Any order rejection",
            "Any missing MTIL record",
            "Any data-health invalid event during open position",
            "Any live fill worse than paper fill by more than allowed threshold",
            "Any broker/API instability",
            "Any emotional/manual override",
            "Daily loss limit touched or threatened",
            "Emergency exit process fails in drill or live test",
        ))


class Phase3ReportWriter:
    @staticmethod
    def write(path: str | Path, decision: LiveReadinessDecision) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(decision.summary_text(), encoding="utf-8")
        return p
