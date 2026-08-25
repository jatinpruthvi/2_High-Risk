from __future__ import annotations

from dataclasses import dataclass

from .config import SystemConfig
from .models import RiskPlan


@dataclass(frozen=True)
class RiskContext:
    capital: float
    mode: str
    setup_grade: str
    lots: int
    entry_premium: float
    lot_size: int
    spread_points: float
    tick_size: float
    required_stop_points: float
    instrument: str
    realized_loss_today: float = 0.0


class RequiredStopModel:
    """Logical stop distance required by structure/premium/volatility.

    For a long-option day trade the invalidation level is driven primarily by
    the premium paid: if the option loses a large fraction of its value, the
    thesis is broken regardless of where the underlying sits. The model returns
    a premium-based logical stop in points, floored by a configurable minimum
    and capped by the hard-stop point cap so it can never exceed the risk-cap
    derived stop. The DynamicRiskCalculator still enforces the survivability
    rule: if this required stop does not fit inside the risk cap, the trade is
    skipped.
    """

    def __init__(self, config: SystemConfig):
        self.config = config

    def required_stop_points(self, entry_premium: float) -> float:
        raw = self.config.raw.get("required_stop_model")
        if not isinstance(raw, dict):
            return 0.0
        if not raw.get("enabled", True):
            return 0.0
        pct = float(raw.get("premium_stop_pct", 0.20))
        min_points = float(raw.get("min_points", 0.0))
        stop = entry_premium * pct
        return max(min_points, stop)


class DynamicRiskCalculator:
    def __init__(self, config: SystemConfig):
        self.config = config

    def _remaining_daily_budget(self, ctx: RiskContext) -> float:
        max_daily = float(self.config.section("risk").get("max_daily_loss_rupees", 0.0))
        if max_daily <= 0:
            return float("inf")
        return max(0.0, max_daily - max(0.0, float(ctx.realized_loss_today)))

    def max_allowed_risk(self, ctx: RiskContext) -> float:
        risk = self.config.section("risk")
        overrides = self.config.raw.get("instrument_risk_overrides", {})
        inst_override = overrides.get(ctx.instrument.upper(), {}) if isinstance(overrides, dict) else {}
        if ctx.mode.upper() in {"SURVIVAL", "NO_TRADE"}:
            return 0.0
        daily_cap = 0.80 * self._remaining_daily_budget(ctx)
        if ctx.mode.upper() == "DEFENSIVE":
            cap = float(inst_override.get("normal_risk_cap_rupees", risk["defensive_risk_max_rupees"]))
            return min(
                ctx.capital * float(risk["defensive_risk_max_pct_of_capital"]) / 100.0,
                float(risk["defensive_risk_max_rupees"]),
                cap,
                daily_cap,
            )
        normal_cap = min(
            ctx.capital * float(risk["normal_risk_pct_of_capital"]) / 100.0,
            float(inst_override.get("normal_risk_cap_rupees", risk["normal_risk_cap_rupees"])),
        )
        if ctx.setup_grade.upper() in {"A+", "A_PLUS"}:
            instrument_cap = min(
                ctx.capital * float(risk["a_plus_risk_pct_of_capital"]) / 100.0,
                float(inst_override.get("a_plus_risk_cap_rupees", risk["a_plus_risk_cap_rupees"])),
            )
            return min(normal_cap, instrument_cap, daily_cap)
        return min(normal_cap, daily_cap)

    def plan(self, ctx: RiskContext) -> RiskPlan:
        max_allowed = self.max_allowed_risk(ctx)
        if max_allowed <= 0:
            return RiskPlan(max_allowed, 0.0, 0.0, False, 0.0, "Mode does not allow risk.")
        hard = self.config.section("hard_stop")
        is_aplus = ctx.setup_grade.upper() in {"A+", "A_PLUS"}
        point_cap = float(hard["a_plus_max_points"] if is_aplus else hard["normal_max_points"])
        pct = float(hard["a_plus_max_premium_pct"] if is_aplus else hard["normal_max_premium_pct"]) / 100.0
        premium_stop = ctx.entry_premium * pct
        risk_cap_stop = max_allowed / (ctx.lot_size * ctx.lots)
        hard_stop_points = min(point_cap, premium_stop, risk_cap_stop)
        planned_risk = hard_stop_points * ctx.lot_size * ctx.lots
        minimum_viable = max(2.0 * ctx.spread_points + 2.0 * ctx.tick_size, 0.0)
        required_stop_risk = ctx.required_stop_points * ctx.lot_size * ctx.lots
        if required_stop_risk > max_allowed:
            return RiskPlan(max_allowed, hard_stop_points, planned_risk, False, minimum_viable, "Required stop exceeds max allowed risk.")
        if hard_stop_points < minimum_viable:
            return RiskPlan(max_allowed, hard_stop_points, planned_risk, False, minimum_viable, "Hard stop is below minimum viable stop.")
        if planned_risk > max_allowed + 1e-9:
            return RiskPlan(max_allowed, hard_stop_points, planned_risk, False, minimum_viable, "Planned risk exceeds max allowed risk.")
        return RiskPlan(max_allowed, hard_stop_points, planned_risk, True, minimum_viable, "")
