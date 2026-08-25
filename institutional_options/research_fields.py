from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ResearchOnlyFields:
    """Optional research fields that are logged if available but cannot approve MVP trades."""

    gex_scenario_estimate: Optional[float] = None
    cvd_proxy: Optional[float] = None
    stock_option_chain_confirmation: Optional[float] = None
    depth20_liquidity_score: Optional[float] = None
    ai_advisory_score: Optional[float] = None
