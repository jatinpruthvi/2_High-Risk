from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .models import CalibrationStatus


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class EdgeInputs:
    premium_elasticity_score: float = 0.0
    gamma_usefulness_score: float = 0.0
    expected_acceleration_score: float = 0.0
    iv_support_score: float = 0.0
    time_to_profit_quality_score: float = 0.0
    expected_value_r: float = 0.0
    vol_edge_ratio: float = 0.0
    forced_flow_score: float = 0.0
    liquidity_vacuum_score: float = 0.0
    range_expansion_quality: float = 0.0
    directional_option_breadth_score: float = 0.0
    trend_exhaustion_risk: float = 0.0
    late_entry_risk: float = 0.0
    trade_location_efficiency: float = 0.0
    reward_path_score: float = 0.0
    time_to_profit_probability: float = 0.0


@dataclass(frozen=True)
class ExpectedValueInputs:
    """Inputs for the Expected Value Engine.

    All values are normalized to a 0-100 scale except:
    - expected_value_r: expected return in R multiples (1R = initial stop distance)
    - win_rate: probability of a winning trade (0..1)
    - avg_win_r: average win in R multiples
    - avg_loss_r: average loss in R multiples (positive value, e.g. 1.0 = -1R)
    """
    expected_value_r: float = 0.0
    win_rate: float = 0.0
    avg_win_r: float = 0.0
    avg_loss_r: float = 0.0
    calibrated_success_probability: Optional[float] = None
    calibrated_net_expectancy_r: Optional[float] = None
    calibration_status_direction: CalibrationStatus = CalibrationStatus.UNVALIDATED
    calibration_status_liquidity: CalibrationStatus = CalibrationStatus.UNVALIDATED
    premium_elasticity_score: float = 0.0
    gamma_usefulness_score: float = 0.0


class ExpectedValueEngine:
    """Calculates expected value (EV) for a candidate trade.

    EV = (Win Rate × Avg Win) - (Loss Rate × Avg Loss) - Costs

    Uses per-instrument historical outcomes from gate learning when available.
    Falls back to proxy estimation from direction score, convexity, and elasticity
    when insufficient calibration data exists.
    """

    # Cost estimate in R (round-trip slippage + brokerage as fraction of 1R)
    # Paper mode uses simplified cost; will be replaced by real CostModel.
    COST_R = 0.08

    @staticmethod
    def calculate_ev(i: ExpectedValueInputs) -> float:
        """Calculate expected value in R multiples."""
        # If calibrated net expectancy is available, use it directly (post-cost).
        if i.calibrated_net_expectancy_r is not None:
            cal_status_dir = i.calibration_status_direction
            cal_status_liq = i.calibration_status_liquidity
            if cal_status_dir in (CalibrationStatus.VALIDATED, CalibrationStatus.OBSERVED) or \
               cal_status_liq in (CalibrationStatus.VALIDATED, CalibrationStatus.OBSERVED):
                return float(i.calibrated_net_expectancy_r)

        # Check if calibrated success probability is available.
        if i.calibrated_success_probability is not None and 0.0 <= i.calibrated_success_probability <= 1.0:
            win_rate = i.calibrated_success_probability
            avg_win_r = max(i.avg_win_r, 1.5)  # Default assumption if not provided
            avg_loss_r = max(i.avg_loss_r, 1.0)
            ev = (win_rate * avg_win_r) - ((1.0 - win_rate) * avg_loss_r) - ExpectedValueEngine.COST_R
            return ev

        # Proxy EV from component scores.
        # premium_elasticity_score correlates with probability of reaching target
        # gamma_usefulness_score correlates with avg_win (higher gamma -> faster move)
        proxy_win_rate = i.premium_elasticity_score / 100.0
        proxy_avg_win = 1.0 + (i.gamma_usefulness_score / 100.0) * 2.0  # 1R to 3R
        proxy_avg_loss = 1.0
        ev = (proxy_win_rate * proxy_avg_win) - ((1.0 - proxy_win_rate) * proxy_avg_loss) - ExpectedValueEngine.COST_R
        return ev

    @staticmethod
    def score(ev: float, ideal: float = 0.5, acceptable: float = 0.1, reject: float = -0.3) -> float:
        """Convert EV (in R) to a 0-100 score for ranking/filtering."""
        if ev >= ideal:
            return 100.0
        if ev >= acceptable:
            return 70.0 + 30.0 * (ev - acceptable) / (ideal - acceptable)
        if ev >= reject:
            return 40.0 + 30.0 * (ev - reject) / (acceptable - reject)
        return 0.0

    @staticmethod
    def ev_r_from_inputs(win_rate: float, avg_win_r: float, avg_loss_r: float) -> float:
        """Direct EV calculation from win rate and R multiples."""
        return (win_rate * avg_win_r) - ((1.0 - win_rate) * avg_loss_r) - ExpectedValueEngine.COST_R


class ExecutionQualityCalculator:
    """Tracks and scores execution quality from paper fill data.

    Score = 100 × (1 - avg_slippage_pct / spread_pct) per instrument.
    Factors in time-of-day (wider spreads at open/close) and liquidity.
    """

    def __init__(self):
        self._fills: dict[str, list[dict]] = {}  # instrument -> list of fill records

    def record_fill(self, instrument: str, fill_price: float, mid_price: float,
                    spread_pct: float, side: str, timestamp: float) -> None:
        """Record a fill for execution quality tracking."""
        if instrument not in self._fills:
            self._fills[instrument] = []
        slippage = abs(fill_price - mid_price)
        slippage_pct = (slippage / mid_price * 100.0) if mid_price > 0 else 0.0
        self._fills[instrument].append({
            "fill_price": fill_price,
            "mid_price": mid_price,
            "spread_pct": spread_pct,
            "slippage_pct": slippage_pct,
            "side": side,
            "timestamp": timestamp,
        })
        # Keep only last 100 fills per instrument
        if len(self._fills[instrument]) > 100:
            self._fills[instrument] = self._fills[instrument][-100:]

    def score(self, instrument: str, current_spread_pct: float = 0.0,
              hour: int = 10) -> float:
        """Calculate execution quality score for an instrument.

        Returns 0-100 score. Higher = better execution quality.
        """
        fills = self._fills.get(instrument, [])
        if not fills:
            # No data: return neutral score based on current spread
            if current_spread_pct > 0:
                return max(0.0, 100.0 - current_spread_pct * 10.0)
            return 50.0

        # Weight recent fills more heavily (exponential decay)
        total_weight = 0.0
        weighted_slippage_ratio = 0.0
        now = fills[-1]["timestamp"] if fills else 0.0

        for i, fill in enumerate(fills):
            age = now - fill["timestamp"]
            # Half-life of 20 fills
            weight = 0.5 ** (age / 20.0) if age > 0 else 1.0
            spread = fill["spread_pct"] if fill["spread_pct"] > 0 else 0.001
            slippage_ratio = fill["slippage_pct"] / spread
            weighted_slippage_ratio += weight * slippage_ratio
            total_weight += weight

        avg_slippage_ratio = weighted_slippage_ratio / total_weight if total_weight > 0 else 1.0

        # Time-of-day adjustment: wider spreads at open (9:15-10:30) and close (15:00-15:30)
        time_factor = 1.0
        if hour < 10 or hour >= 15:
            time_factor = 0.8  # More forgiving during volatile periods
        elif 10 <= hour < 11:
            time_factor = 0.9  # Slightly wider at open

        # Score: 100 * (1 - adjusted_slippage_ratio)
        # Slippage ratio of 0 = 100, 0.5 = 50, 1.0 = 0
        score = max(0.0, 100.0 * (1.0 - avg_slippage_ratio * time_factor))
        return clamp(score)

    def get_avg_slippage_pct(self, instrument: str) -> float:
        """Get average slippage percentage for an instrument."""
        fills = self._fills.get(instrument, [])
        if not fills:
            return 0.0
        return sum(f["slippage_pct"] for f in fills) / len(fills)

    def get_fill_count(self, instrument: str) -> int:
        """Get number of recorded fills for an instrument."""
        return len(self._fills.get(instrument, []))


class AdvancedEdgeCalculator:
    """Institutional edge calculators used as filters/ranking quality layers.

    Inputs are precomputed primitive scores. Missing values should be provided as 0
    or handled upstream as UNAVAILABLE/UNVALIDATED with penalties.
    """

    @staticmethod
    def convexity_edge_score(i: EdgeInputs) -> float:
        return clamp(0.30*i.premium_elasticity_score + 0.25*i.gamma_usefulness_score + 0.20*i.expected_acceleration_score + 0.15*i.iv_support_score + 0.10*i.time_to_profit_quality_score)

    @staticmethod
    def final_edge_approval(i: EdgeInputs, breakout_trade: bool = False, opportunity_half_life_expired: bool = False) -> tuple[bool, tuple[str, ...]]:
        reasons: list[str] = []
        if i.expected_value_r < 0.30:
            reasons.append("ExpectedValue_R below 0.30R")
        if i.vol_edge_ratio < 1.60:
            reasons.append("VolEdgeRatio below 1.60")
        if AdvancedEdgeCalculator.convexity_edge_score(i) < 80:
            reasons.append("ConvexityEdgeScore below 80")
        if i.time_to_profit_probability < 70:
            reasons.append("TimeToProfitProbability below 70")
        if i.trade_location_efficiency < 75:
            reasons.append("TradeLocationEfficiency below 75")
        if i.reward_path_score < 75:
            reasons.append("RewardPathScore below 75")
        if i.trend_exhaustion_risk > 70:
            reasons.append("TrendExhaustionRisk above 70")
        if i.late_entry_risk > 70:
            reasons.append("LateEntryRisk above 70")
        if opportunity_half_life_expired:
            reasons.append("Opportunity half-life expired")
        if breakout_trade:
            if i.forced_flow_score < 70:
                reasons.append("ForcedFlowScore below 70 for breakout")
            if i.range_expansion_quality < 75:
                reasons.append("RangeExpansionQuality below 75 for breakout")
            if i.liquidity_vacuum_score < 70:
                reasons.append("LiquidityVacuumScore below 70 for breakout")
            if i.directional_option_breadth_score < 70:
                reasons.append("DirectionalOptionBreadthScore below 70 for breakout")
        return (not reasons, tuple(reasons))
