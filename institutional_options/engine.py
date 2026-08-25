from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, AbstractSet

from .config import SystemConfig
from .models import OpportunityEvaluation, SelectionResult, TradeDecision
from .scoring import OpportunityScorer


@dataclass
class PaperPortfolioState:
    open_positions_count: int = 0
    pending_orders_count: int = 0
    realized_loss_today: float = 0.0


class PaperOpportunityEngine:
    def __init__(self, config: SystemConfig, gate_provider=None):
        self.config = config
        self.scorer = OpportunityScorer(config, gate_provider=gate_provider)

    def set_runtime_mode(self, mode: str) -> None:
        self.scorer.set_runtime_mode(mode)

    def evaluate_and_select(self, candidates: Iterable, state: Optional[PaperPortfolioState] = None, allowed_playbooks: Optional[AbstractSet[str]] = None) -> SelectionResult:
        state = state or PaperPortfolioState()
        if state.open_positions_count >= 1:
            return SelectionResult(TradeDecision.GLOBAL_POSITION_LOCK_ACTIVE, None, tuple(), ("Global open position lock active",))
        if state.pending_orders_count >= 1:
            return SelectionResult(TradeDecision.GLOBAL_POSITION_LOCK_ACTIVE, None, tuple(), ("Global pending order lock active",))
        evaluations = tuple(self.scorer.evaluate(c, realized_loss_today=state.realized_loss_today) for c in candidates)
        if allowed_playbooks is not None:
            eligible = [e for e in evaluations if e.eligible and e.candidate.setup_type in allowed_playbooks]
        else:
            eligible = [e for e in evaluations if e.eligible]
        if not eligible:
            return SelectionResult(TradeDecision.NO_EXCELLENT_CANDIDATE, None, evaluations, ("No A/A+ eligible candidate",))
        ranked = sorted(eligible, key=lambda e: e.comparable_opportunity_score, reverse=True)
        top = ranked[0]
        if len(ranked) > 1 and abs(top.comparable_opportunity_score - ranked[1].comparable_opportunity_score) <= float(self.config.section("opportunity_selection").get("rank_tie_threshold_points", 3)):
            top = self._tie_break(ranked[:2])
            if top is None:
                return SelectionResult(TradeDecision.NO_TRADE, None, evaluations, ("Top candidates ambiguous after tie-break",))
        return SelectionResult(top.decision, top, evaluations, ("Selected best excellent candidate",))

    @staticmethod
    def _tie_break(two: list[OpportunityEvaluation]) -> Optional[OpportunityEvaluation]:
        a, b = two
        keys = [
            lambda e: e.candidate.execution_quality_score,
            lambda e: e.candidate.convexity_edge_score,
            lambda e: e.contract_quality.score,
            lambda e: e.candidate.premium_elasticity,
            lambda e: -e.candidate.market_hostility_score,
            lambda e: -e.candidate.iv_crush_risk_score,
            lambda e: e.candidate.opportunity_confidence_score,
        ]
        for key in keys:
            av, bv = key(a), key(b)
            if abs(av - bv) > 1e-9:
                return a if av > bv else b
        return None
