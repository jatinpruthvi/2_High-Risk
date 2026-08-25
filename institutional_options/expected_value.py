from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Optional


@dataclass(frozen=True)
class ExpectedValueEstimate:
    """Cost-aware EV estimate with an explicit evidence status.

    The numeric value is intentionally absent until the inputs are measured and
    the transaction-cost model is validated. A zero value must never be treated
    as a measured zero-expectancy trade.
    """

    expected_value_r: Optional[float]
    status: str
    reason: str = ""
    win_probability: Optional[float] = None
    avg_win_r: Optional[float] = None
    avg_loss_r: Optional[float] = None
    cost_r: Optional[float] = None
    slippage_r: Optional[float] = None
    theta_r: Optional[float] = None
    iv_crush_r: Optional[float] = None


class ExpectedValueEngine:
    """Compute research-only EV in a single R-multiple unit system."""

    @staticmethod
    def compute(
        win_probability: Optional[float],
        avg_win_r: Optional[float],
        avg_loss_r: Optional[float],
        cost_r: Optional[float],
        slippage_r: Optional[float] = 0.0,
        theta_r: Optional[float] = 0.0,
        iv_crush_r: Optional[float] = 0.0,
        *,
        cost_model_valid: bool,
        max_probability: float = 0.62,
    ) -> ExpectedValueEstimate:
        if not cost_model_valid:
            return ExpectedValueEstimate(None, "UNVALIDATED_COST_MODEL", "Transaction-cost configuration is placeholder or unverified.")
        values = (win_probability, avg_win_r, avg_loss_r, cost_r, slippage_r, theta_r, iv_crush_r)
        if any(value is None or not math.isfinite(float(value)) for value in values):
            return ExpectedValueEstimate(None, "UNAVAILABLE_INPUTS", "Measured win/loss, cost, and risk components are incomplete.")
        p = min(float(max_probability), max(0.0, float(win_probability)))
        avg_win = max(0.0, float(avg_win_r))
        avg_loss = max(0.0, float(avg_loss_r))
        costs = max(0.0, float(cost_r))
        slippage = max(0.0, float(slippage_r))
        theta = max(0.0, float(theta_r))
        iv_crush = max(0.0, float(iv_crush_r))
        ev = p * avg_win - (1.0 - p) * avg_loss - costs - slippage - theta - iv_crush
        return ExpectedValueEstimate(
            ev,
            "MEASURED_COST_AWARE",
            "Computed from validated cost model and measured/calibrated inputs.",
            p,
            avg_win,
            avg_loss,
            costs,
            slippage,
            theta,
            iv_crush,
        )

    @staticmethod
    def from_calibrated_expectancy(
        calibrated_net_expectancy_r: Optional[float],
        *,
        cost_model_valid: bool,
    ) -> ExpectedValueEstimate:
        if not cost_model_valid:
            return ExpectedValueEstimate(None, "UNVALIDATED_COST_MODEL", "Net expectancy is not canonical while charges are unverified.")
        if calibrated_net_expectancy_r is None or not math.isfinite(float(calibrated_net_expectancy_r)):
            return ExpectedValueEstimate(None, "WARMUP_NO_CALIBRATION", "Instrument/setup outcome calibration is not yet available.")
        value = float(calibrated_net_expectancy_r)
        return ExpectedValueEstimate(value, "CALIBRATED_NET_EXPECTANCY", "Validated walk-forward net expectancy is available.")
