from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from .config import SystemConfig
from .models import OptionType
from .option_chain import OptionChainParseError, OptionChainSnapshot
from .snapshot import InstrumentMarketSnapshot


@dataclass(frozen=True)
class ExpectedMoveResult:
    expected_move: float
    required_move: float
    ratio: float
    raw_expected_move: float


class ExpectedMoveCalculator:
    def __init__(self, config: SystemConfig):
        self.config = config

    def calculate(self, underlying: str, required_move: float, atr_remaining: float, regime_projected: float, straddle_implied_remaining: float, gap_remaining_adjustment: float = 1.0, liquidity_adjustment: float = 1.0) -> ExpectedMoveResult:
        haircuts = self.config.section("expected_move_model_phase1")["confidence_haircuts"]
        haircut = float(haircuts.get(underlying.upper(), 0.70))
        raw = median([atr_remaining, regime_projected, straddle_implied_remaining])
        expected = raw * haircut * liquidity_adjustment * gap_remaining_adjustment
        ratio = expected / required_move if required_move > 0 else 0.0
        return ExpectedMoveResult(expected, required_move, ratio, raw)


class IVCrushRiskCalculator:
    def __init__(self, config: SystemConfig):
        self.config = config

    @staticmethod
    def bucket(value: float, points: tuple[tuple[float, float], ...]) -> float:
        for threshold, score in points:
            if value <= threshold:
                return score
        return points[-1][1]

    def calculate(self, iv_rank: float | None, event_risk: float, recent_iv_expansion_pct: float, iv_realized_spread_pct: float, term_structure_risk: float, dte: float, skew_risk: float) -> float:
        w = self.config.section("iv_crush")["weights"]
        iv_rank_risk = 50.0 if iv_rank is None else self.bucket(iv_rank, ((30,10),(50,25),(70,50),(85,75),(101,90)))
        recent = self.bucket(recent_iv_expansion_pct, ((0,15),(10,40),(20,65),(999,85)))
        iv_spread = self.bucket(iv_realized_spread_pct, ((0,10),(20,25),(40,55),(999,80)))
        dte_risk = 90 if dte <= 0 else 80 if dte <= 1 else 60 if dte <= 3 else 35 if dte <= 7 else 20
        score = (
            float(w["iv_rank_risk"])*iv_rank_risk + float(w["event_risk"])*event_risk +
            float(w["recent_iv_expansion_risk"])*recent + float(w["iv_realized_spread_risk"])*iv_spread +
            float(w["term_structure_risk"])*term_structure_risk + float(w["time_to_expiry_risk"])*dte_risk +
            float(w["skew_risk"])*skew_risk
        )
        return max(0.0, min(100.0, score))


class SimpleMarketHostilityCalculator:
    def calculate(self, data_risk: float, liquidity_risk: float, regime_risk: float, premium_risk: float, event_gap_risk: float, direction_conflict_risk: float, psychology_risk: float) -> float:
        return max(0.0, min(100.0, 0.20*data_risk + 0.20*liquidity_risk + 0.15*regime_risk + 0.15*premium_risk + 0.10*event_gap_risk + 0.10*direction_conflict_risk + 0.10*psychology_risk))


class PortfolioNoTradeCalculator:
    def calculate(self, best_candidate_weakness_risk: float, cross_instrument_market_hostility: float, data_breadth_risk: float, liquidity_breadth_risk: float, event_gap_system_risk: float, recent_loss_psychology_risk: float, calibration_uncertainty_risk: float) -> float:
        return max(0.0, min(100.0, 0.25*best_candidate_weakness_risk + 0.20*cross_instrument_market_hostility + 0.15*data_breadth_risk + 0.15*liquidity_breadth_risk + 0.10*event_gap_system_risk + 0.10*recent_loss_psychology_risk + 0.05*calibration_uncertainty_risk))


def atm_straddle_implied_move(chain: OptionChainSnapshot) -> float:
    """Return the ATM straddle only when both live legs are present.

    Fyers can return a one-sided strike. Missing-leg data is not inferred and
    remains a zero/unknown expected-move component; candidate construction
    still evaluates the available leg and the data-health gate decides whether
    it can be entered.
    """
    try:
        k = chain.nearest_strike()
        ce = chain.leg_at(k, OptionType.CE)
        pe = chain.leg_at(k, OptionType.PE)
    except OptionChainParseError:
        return 0.0
    return ce.quote.mid + pe.quote.mid
