from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Any, Mapping, Optional


class OptionType(str, Enum):
    CE = "CE"
    PE = "PE"


class Mode(str, Enum):
    DRY_RUN = "DRY_RUN"
    PAPER = "PAPER"
    LIVE_DISABLED = "LIVE_DISABLED"


class TradeDecision(str, Enum):
    BUY_CALL_CANDIDATE = "BUY_CALL_CANDIDATE"
    BUY_PUT_CANDIDATE = "BUY_PUT_CANDIDATE"
    NO_TRADE = "NO_TRADE"
    DATA_INVALID = "DATA_INVALID"
    CONTRACT_INVALID = "CONTRACT_INVALID"
    GLOBAL_POSITION_LOCK_ACTIVE = "GLOBAL_POSITION_LOCK_ACTIVE"
    MARKET_HOSTILE = "MARKET_HOSTILE"
    NO_EXCELLENT_CANDIDATE = "NO_EXCELLENT_CANDIDATE"
    REVALIDATE_REQUIRED = "REVALIDATE_REQUIRED"


class OpportunityGrade(str, Enum):
    A_PLUS = "A+"
    A = "A"
    B = "B"
    C = "C"
    REJECT = "Reject"


class CalibrationStatus(str, Enum):
    UNVALIDATED = "UNVALIDATED"
    OBSERVED = "OBSERVED"
    VALIDATED = "VALIDATED"
    DEGRADED = "DEGRADED"
    RETIRED = "RETIRED"


class Moneyness(str, Enum):
    ATM = "ATM"
    ITM = "ITM"
    OTM = "OTM"


@dataclass(frozen=True)
class InstrumentSpec:
    underlying: str
    security_id: str
    instrument: str
    expiry: date
    lot_size: int
    tick_size: float
    strike: Optional[float] = None
    option_type: Optional[OptionType] = None
    freeze_qty: Optional[int] = None
    buy_sell_allowed: bool = True
    exchange: str = "NSE"
    instrument_kind: str = "INDEX"
    instrument_class: str = "NSE_INDEX"


@dataclass(frozen=True)
class Quote:
    bid: float
    ask: float
    bid_qty: int
    ask_qty: int
    last: Optional[float]
    timestamp: datetime
    cumulative_bid_qty_5depth: Optional[int] = None
    cumulative_ask_qty_5depth: Optional[int] = None
    source_timestamp_available: bool = False

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    def is_valid(self) -> bool:
        return self.bid > 0 and self.ask > 0 and self.ask > self.bid


@dataclass(frozen=True)
class Greeks:
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    iv: Optional[float] = None


@dataclass(frozen=True)
class DataHealth:
    valid: bool
    warning: bool = False
    reason: str = ""


@dataclass(frozen=True)
class CandidateInputs:
    instrument: InstrumentSpec
    quote: Quote
    moneyness: Moneyness
    greeks: Greeks
    data_health: DataHealth
    futures_price: float
    underlying_price: float
    instrument_direction_score: float
    trade_quality_score: float
    regime_confidence: float
    market_hostility_score: float
    iv_crush_risk_score: float
    premium_elasticity: float
    expected_move: float
    required_move: float
    required_stop_points: float = 0.0
    expected_value_r: float = 0.0
    vol_edge_ratio: float = 0.0
    convexity_edge_score: float = 0.0
    execution_quality_score: float = 0.0
    opportunity_confidence_score: float = 0.0
    regime_fit_score: float = 0.0
    forced_flow_score: float = 0.0
    liquidity_vacuum_score: float = 0.0
    range_expansion_quality: float = 0.0
    directional_option_breadth_score: float = 0.0
    trend_exhaustion_risk: float = 0.0
    late_entry_risk: float = 0.0
    trade_location_efficiency: float = 0.0
    reward_path_score: float = 0.0
    time_to_profit_probability: float = 0.0
    opportunity_half_life_seconds: Optional[float] = None
    candidate_created_at: Optional[datetime] = None
    setup_type: str = "UNKNOWN"
    calibration_status_direction: CalibrationStatus = CalibrationStatus.UNVALIDATED
    calibration_status_liquidity: CalibrationStatus = CalibrationStatus.UNVALIDATED
    notes: Mapping[str, Any] = field(default_factory=dict)
    calibrated_success_probability: Optional[float] = None
    calibrated_net_expectancy_r: Optional[float] = None
    lifecycle_state: str = "SHADOW"
    exposure_group: str = ""
    setup_grade: str = ""

    @property
    def side(self) -> OptionType:
        if self.instrument.option_type is None:
            raise ValueError("Candidate instrument must be an option with option_type.")
        return self.instrument.option_type

    @property
    def expected_required_ratio(self) -> float:
        if self.required_move <= 0:
            return 0.0
        return self.expected_move / self.required_move


@dataclass(frozen=True)
class RiskPlan:
    max_allowed_risk: float
    hard_stop_points: float
    planned_risk: float
    hard_stop_fit: bool
    minimum_viable_stop_points: float
    reason: str = ""


@dataclass(frozen=True)
class ContractQualityBreakdown:
    score: float
    valid: bool
    liquidity_score: float
    spread_score: float
    delta_responsiveness_score: float
    gamma_suitability_score: float
    theta_safety_score: float
    iv_fairness_score: float
    reason: str = ""


@dataclass(frozen=True)
class OpportunityEvaluation:
    candidate: CandidateInputs
    contract_quality: ContractQualityBreakdown
    risk_plan: RiskPlan
    opportunity_score: float
    comparable_opportunity_score: float
    dynamic_excellent_threshold: float
    grade: OpportunityGrade
    eligible: bool
    decision: TradeDecision
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PaperFill:
    filled: bool
    fill_price: Optional[float]
    limit_price: Optional[float]
    slippage_buffer: float
    reason: str


@dataclass(frozen=True)
class PaperTrade:
    trade_id: str
    entry_evaluation: OpportunityEvaluation
    entry_fill: PaperFill
    entry_time: datetime
    exit_fill: Optional[PaperFill] = None
    exit_time: Optional[datetime] = None
    exit_reason: Optional[str] = None


@dataclass(frozen=True)
class SelectionResult:
    decision: TradeDecision
    selected: Optional[OpportunityEvaluation]
    evaluations: tuple[OpportunityEvaluation, ...]
    reasons: tuple[str, ...]
