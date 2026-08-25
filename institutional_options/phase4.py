from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from statistics import mean
from typing import Iterable, Mapping, Optional


class Phase4Decision(str, Enum):
    KEEP_RESEARCH = "KEEP_RESEARCH"
    ADVANCE_TO_SHADOW = "ADVANCE_TO_SHADOW"
    ADVANCE_TO_ADVISORY = "ADVANCE_TO_ADVISORY"
    REJECT = "REJECT"


@dataclass(frozen=True)
class ResearchExperimentSpec:
    experiment_id: str
    name: str
    category: str
    hypothesis: str
    required_sample_size: int
    success_metric: str
    max_allowed_drawdown_worsening_r: float
    production_authority_allowed: bool = False


@dataclass(frozen=True)
class ResearchExperimentResult:
    experiment_id: str
    sample_size: int
    expectancy_delta_r: float
    drawdown_delta_r: float
    profit_factor_delta: float
    false_trade_reduction_rate: float
    missed_winner_increase_rate: float
    notes: str = ""


@dataclass(frozen=True)
class ResearchExperimentReview:
    spec: ResearchExperimentSpec
    result: ResearchExperimentResult
    decision: Phase4Decision
    reasons: tuple[str, ...]


class Phase4ExperimentGate:
    """Research-only promotion gate for Phase 4 experiments.

    This gate can approve only research-stage advancement. It cannot grant live trading authority.
    """

    def review(self, spec: ResearchExperimentSpec, result: ResearchExperimentResult) -> ResearchExperimentReview:
        reasons: list[str] = []
        if spec.production_authority_allowed:
            reasons.append("Spec incorrectly requests production authority.")
        if result.sample_size < spec.required_sample_size:
            reasons.append(f"Sample size {result.sample_size} below required {spec.required_sample_size}.")
        if result.expectancy_delta_r <= 0:
            reasons.append("No positive expectancy improvement.")
        if result.drawdown_delta_r < -abs(spec.max_allowed_drawdown_worsening_r):
            reasons.append("Drawdown worsened beyond allowed tolerance.")
        if result.missed_winner_increase_rate > 0.05:
            reasons.append("Missed-winner rate increased above 5% tolerance.")
        if reasons:
            decision = Phase4Decision.REJECT if spec.production_authority_allowed else Phase4Decision.KEEP_RESEARCH
        else:
            decision = Phase4Decision.ADVANCE_TO_SHADOW
        return ResearchExperimentReview(spec, result, decision, tuple(reasons))


@dataclass(frozen=True)
class SectorIndexCandidate:
    symbol: str
    option_liquidity_score: float
    spread_quality_score: float
    volume_oi_quality_score: float
    regime_distinctiveness_score: float
    historical_paper_expectancy_r: float
    implementation_complexity_score: float


@dataclass(frozen=True)
class SectorExpansionReview:
    candidate: SectorIndexCandidate
    approved_for_research_watchlist: bool
    approved_for_phase1_universe: bool
    reasons: tuple[str, ...]


class SectorExpansionGate:
    def review(self, candidate: SectorIndexCandidate) -> SectorExpansionReview:
        reasons: list[str] = []
        if candidate.option_liquidity_score < 80:
            reasons.append("Option liquidity below 80.")
        if candidate.spread_quality_score < 80:
            reasons.append("Spread quality below 80.")
        if candidate.volume_oi_quality_score < 75:
            reasons.append("Volume/OI quality below 75.")
        if candidate.regime_distinctiveness_score < 60:
            reasons.append("Regime distinctiveness too low; likely redundant exposure.")
        if candidate.historical_paper_expectancy_r <= 0:
            reasons.append("No positive paper expectancy.")
        if candidate.implementation_complexity_score > 60:
            reasons.append("Implementation complexity too high for current phase.")
        watch = candidate.option_liquidity_score >= 70 and candidate.spread_quality_score >= 70
        return SectorExpansionReview(candidate, watch, False, tuple(reasons) + ("Phase 1 universe expansion remains frozen; no approval for production universe.",))


@dataclass(frozen=True)
class StockOptionEnrichmentMetrics:
    symbol: str
    sample_size: int
    incremental_direction_accuracy: float
    incremental_expectancy_r: float
    added_false_positive_rate: float
    liquidity_reliability_score: float


@dataclass(frozen=True)
class StockOptionEnrichmentReview:
    metrics: StockOptionEnrichmentMetrics
    useful_for_research: bool
    eligible_for_future_wbci_enrichment: bool
    reasons: tuple[str, ...]


class StockOptionEnrichmentGate:
    def review(self, metrics: StockOptionEnrichmentMetrics) -> StockOptionEnrichmentReview:
        reasons: list[str] = []
        if metrics.sample_size < 50:
            reasons.append("Sample size below 50.")
        if metrics.incremental_expectancy_r <= 0:
            reasons.append("No positive incremental expectancy.")
        if metrics.added_false_positive_rate > 0.05:
            reasons.append("Added false-positive rate above 5%.")
        if metrics.liquidity_reliability_score < 75:
            reasons.append("Stock option liquidity reliability below 75.")
        useful = metrics.sample_size >= 20 and metrics.incremental_direction_accuracy > 0
        eligible = not reasons
        return StockOptionEnrichmentReview(metrics, useful, eligible, tuple(reasons))


@dataclass(frozen=True)
class MultiPositionResearchMetrics:
    sample_size: int
    incremental_expectancy_r: float
    max_drawdown_delta_r: float
    correlation_adjusted_risk_ok: bool
    rule_violation_rate: float
    complexity_burden_score: float


@dataclass(frozen=True)
class MultiPositionResearchReview:
    metrics: MultiPositionResearchMetrics
    keep_rejected_for_phase1: bool
    eligible_for_future_committee_review: bool
    reasons: tuple[str, ...]


class MultiPositionResearchGate:
    def review(self, metrics: MultiPositionResearchMetrics) -> MultiPositionResearchReview:
        reasons = ["Phase 1 max open positions remains frozen at 1."]
        if metrics.sample_size < 200:
            reasons.append("Sample size below 200 for multi-position research.")
        if metrics.incremental_expectancy_r <= 0:
            reasons.append("No positive incremental expectancy.")
        if metrics.max_drawdown_delta_r < 0:
            reasons.append("Drawdown worsened.")
        if not metrics.correlation_adjusted_risk_ok:
            reasons.append("Correlation-adjusted risk not acceptable.")
        if metrics.rule_violation_rate > 0:
            reasons.append("Rule violations observed.")
        if metrics.complexity_burden_score > 50:
            reasons.append("Complexity burden too high.")
        eligible_future = len(reasons) == 1
        return MultiPositionResearchReview(metrics, True, eligible_future, tuple(reasons))


@dataclass(frozen=True)
class AutoExecutionResearchMetrics:
    sample_size: int
    fill_quality_improvement_points: float
    rejection_rate: float
    incident_count: int
    manual_vs_auto_net_cost_delta: float
    kill_switch_verified: bool


@dataclass(frozen=True)
class AutoExecutionResearchReview:
    metrics: AutoExecutionResearchMetrics
    production_rejected: bool
    eligible_for_shadow_research: bool
    reasons: tuple[str, ...]


class AutoExecutionResearchGate:
    def review(self, metrics: AutoExecutionResearchMetrics) -> AutoExecutionResearchReview:
        reasons = ["Auto-execution remains rejected for MVP and Phase 1."]
        if metrics.sample_size < 200:
            reasons.append("Sample size below 200.")
        if metrics.rejection_rate > 0:
            reasons.append("Order rejection rate must be zero in research sample.")
        if metrics.incident_count > 0:
            reasons.append("Execution incidents observed.")
        if metrics.manual_vs_auto_net_cost_delta <= 0:
            reasons.append("Auto execution did not improve net cost.")
        if not metrics.kill_switch_verified:
            reasons.append("Kill switch not verified.")
        eligible_shadow = len(reasons) == 1
        return AutoExecutionResearchReview(metrics, True, eligible_shadow, tuple(reasons))


class ResearchLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            with self.path.open("w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=["experiment_id", "name", "category", "decision", "reasons", "metrics_json"]).writeheader()

    def append(self, review: ResearchExperimentReview) -> None:
        with self.path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["experiment_id", "name", "category", "decision", "reasons", "metrics_json"])
            writer.writerow({
                "experiment_id": review.spec.experiment_id,
                "name": review.spec.name,
                "category": review.spec.category,
                "decision": review.decision.value,
                "reasons": "; ".join(review.reasons),
                "metrics_json": json.dumps(asdict(review.result)),
            })
