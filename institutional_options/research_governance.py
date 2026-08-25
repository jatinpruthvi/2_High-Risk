from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from statistics import mean
from typing import Iterable, Mapping, Optional


class ResearchStatus(str, Enum):
    RESEARCH_ONLY = "RESEARCH_ONLY"
    OFFLINE_EVALUATED = "OFFLINE_EVALUATED"
    SHADOW_MODE = "SHADOW_MODE"
    ADVISORY_ONLY = "ADVISORY_ONLY"
    RISK_FILTER_ELIGIBLE = "RISK_FILTER_ELIGIBLE"
    REJECTED = "REJECTED"


class ResearchDecision(str, Enum):
    APPROVE_NEXT_STAGE = "APPROVE_NEXT_STAGE"
    KEEP_RESEARCH_ONLY = "KEEP_RESEARCH_ONLY"
    REJECT = "REJECT"


@dataclass(frozen=True)
class ResearchCandidate:
    name: str
    category: str
    verified: bool
    allowed_stage: ResearchStatus
    description: str
    production_authority: str = "NONE"


@dataclass(frozen=True)
class ResearchMetrics:
    sample_size: int
    net_expectancy_delta_r: float
    max_drawdown_delta_r: float
    false_trade_reduction_rate: float
    missed_winner_increase_rate: float
    no_trade_quality_delta: float
    regime_accuracy_delta: float = 0.0
    notes: str = ""


@dataclass(frozen=True)
class ResearchReview:
    candidate: ResearchCandidate
    metrics: ResearchMetrics
    decision: ResearchDecision
    reasons: tuple[str, ...]


class ResearchRegistry:
    def __init__(self, candidates: Iterable[ResearchCandidate]):
        self.candidates = {c.name: c for c in candidates}

    @classmethod
    def default(cls) -> "ResearchRegistry":
        return cls([
            ResearchCandidate("Moirai/Moirai-2", "AI_FORECASTING", True, ResearchStatus.RESEARCH_ONLY, "Multivariate time-series regime/volatility research"),
            ResearchCandidate("Kronos", "AI_FORECASTING", True, ResearchStatus.RESEARCH_ONLY, "Financial OHLCV/K-line model research"),
            ResearchCandidate("TimeGPT", "AI_FORECASTING", True, ResearchStatus.RESEARCH_ONLY, "Probabilistic forecast and interval research"),
            ResearchCandidate("Chronos", "AI_FORECASTING", True, ResearchStatus.RESEARCH_ONLY, "General time-series forecasting benchmark"),
            ResearchCandidate("TimesFM", "AI_FORECASTING", True, ResearchStatus.RESEARCH_ONLY, "General time-series forecasting benchmark"),
            ResearchCandidate("GEXScenario", "MICROSTRUCTURE", True, ResearchStatus.RESEARCH_ONLY, "Gamma/OI scenario research only"),
            ResearchCandidate("CVDProxy", "MICROSTRUCTURE", True, ResearchStatus.RESEARCH_ONLY, "Inferred order-flow proxy research only"),
            ResearchCandidate("StockOptionChainEnrichment", "ENRICHMENT", True, ResearchStatus.RESEARCH_ONLY, "Constituent option-chain confirmation research"),
            ResearchCandidate("TwentyDepthLiquidity", "MICROSTRUCTURE", True, ResearchStatus.RESEARCH_ONLY, "20-depth liquidity value research"),
            ResearchCandidate("SectorIndexExpansion", "UNIVERSE", True, ResearchStatus.RESEARCH_ONLY, "Future index universe expansion research"),
        ])

    def get(self, name: str) -> ResearchCandidate:
        return self.candidates[name]

    def to_json(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps([asdict(c) for c in self.candidates.values()], indent=2), encoding="utf-8")
        return p


class ResearchPromotionGate:
    """Deterministic research governance gate.

    This gate never grants production trading authority. At most, it can approve a module
    for the next research stage if evidence improves net trading quality without worsening
    drawdown or missed-winner behavior beyond allowed limits.
    """

    def __init__(self, min_sample_size: int = 100, min_expectancy_delta_r: float = 0.05, max_drawdown_worsening_r: float = 0.0, max_missed_winner_increase_rate: float = 0.05):
        self.min_sample_size = min_sample_size
        self.min_expectancy_delta_r = min_expectancy_delta_r
        self.max_drawdown_worsening_r = max_drawdown_worsening_r
        self.max_missed_winner_increase_rate = max_missed_winner_increase_rate

    def review(self, candidate: ResearchCandidate, metrics: ResearchMetrics) -> ResearchReview:
        reasons: list[str] = []
        if not candidate.verified:
            reasons.append("Candidate is not verified.")
        if metrics.sample_size < self.min_sample_size:
            reasons.append(f"Sample size {metrics.sample_size} below required {self.min_sample_size}.")
        if metrics.net_expectancy_delta_r < self.min_expectancy_delta_r:
            reasons.append("Net expectancy improvement below threshold.")
        if metrics.max_drawdown_delta_r < -abs(self.max_drawdown_worsening_r):
            reasons.append("Max drawdown worsened beyond allowed tolerance.")
        if metrics.missed_winner_increase_rate > self.max_missed_winner_increase_rate:
            reasons.append("Missed winner rate increased too much.")
        if candidate.production_authority != "NONE":
            reasons.append("Candidate requests production authority, which is forbidden by roadmap.")
        decision = ResearchDecision.APPROVE_NEXT_STAGE if not reasons else ResearchDecision.KEEP_RESEARCH_ONLY
        if not candidate.verified or candidate.production_authority != "NONE":
            decision = ResearchDecision.REJECT
        return ResearchReview(candidate, metrics, decision, tuple(reasons))


@dataclass(frozen=True)
class ThresholdChangeProposal:
    parameter_name: str
    old_value: float
    new_value: float
    sample_size: int
    net_expectancy_delta_r: float
    max_drawdown_delta_r: float
    loosens_threshold: bool
    rationale: str


@dataclass(frozen=True)
class ThresholdChangeReview:
    proposal: ThresholdChangeProposal
    approved: bool
    reasons: tuple[str, ...]


class ThresholdOptimizationGuard:
    def __init__(self, min_sample_size: int = 500):
        self.min_sample_size = min_sample_size

    def review(self, proposal: ThresholdChangeProposal) -> ThresholdChangeReview:
        reasons: list[str] = []
        if proposal.sample_size < self.min_sample_size:
            reasons.append(f"Sample size {proposal.sample_size} below required {self.min_sample_size}.")
        if proposal.loosens_threshold:
            reasons.append("Loosening thresholds is not allowed before large-sample validation.")
        if proposal.net_expectancy_delta_r <= 0:
            reasons.append("No positive net expectancy improvement.")
        if proposal.max_drawdown_delta_r < 0:
            reasons.append("Drawdown worsened.")
        return ThresholdChangeReview(proposal, not reasons, tuple(reasons))


@dataclass(frozen=True)
class BrokerTCAMetrics:
    broker_name: str
    sample_size: int
    avg_slippage_points: float
    rejection_rate: float
    avg_ack_latency_ms: float
    avg_net_cost_rupees: float
    emergency_exit_verified: bool


@dataclass(frozen=True)
class BrokerTCAReview:
    challenger: BrokerTCAMetrics
    incumbent: BrokerTCAMetrics
    eligible_for_shadow_next_stage: bool
    reasons: tuple[str, ...]


class BrokerAbstractionResearchGate:
    def review(self, challenger: BrokerTCAMetrics, incumbent: BrokerTCAMetrics) -> BrokerTCAReview:
        reasons: list[str] = []
        if challenger.sample_size < 50:
            reasons.append("Challenger broker sample size below 50.")
        if challenger.avg_net_cost_rupees > incumbent.avg_net_cost_rupees:
            reasons.append("Challenger net cost is not lower than incumbent.")
        if challenger.rejection_rate > incumbent.rejection_rate:
            reasons.append("Challenger rejection rate worse than incumbent.")
        if not challenger.emergency_exit_verified:
            reasons.append("Challenger emergency exit path not verified.")
        return BrokerTCAReview(challenger, incumbent, not reasons, tuple(reasons))
