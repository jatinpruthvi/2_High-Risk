from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from statistics import median
from typing import Optional

from .config import SystemConfig
from .mapping import round_to_tick
from .models import (
    CalibrationStatus,
    CandidateInputs,
    ContractQualityBreakdown,
    Moneyness,
    OpportunityEvaluation,
    OpportunityGrade,
    PaperFill,
    Quote,
    TradeDecision,
)
from .risk import DynamicRiskCalculator, RiskContext
from .research_controls import ClassGateSet
from .edge_modules import ExpectedValueEngine, ExpectedValueInputs


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def linear_score(value: float, ideal: float, acceptable: float, reject: float) -> float:
    if value <= ideal:
        return 100.0
    if value <= acceptable:
        return 70.0 + 30.0 * (acceptable - value) / (acceptable - ideal)
    if value <= reject:
        return 70.0 * (reject - value) / (reject - acceptable)
    return 0.0


class ContractQualityCalculator:
    def __init__(self, config: SystemConfig):
        self.config = config

    def calculate(self, candidate: CandidateInputs, quote_stale: bool = False, expiry_day: bool = False, aplus_context: bool = False, theta_ratio: Optional[float] = None, gates: Optional[ClassGateSet] = None) -> ContractQualityBreakdown:
        quote = candidate.quote
        if not quote.is_valid():
            return ContractQualityBreakdown(0, False, 0, 0, 0, 0, 0, 0, "Invalid bid/ask.")
        mid = quote.mid
        spread = quote.spread
        spread_pct = spread / mid * 100.0 if mid > 0 else 999.0
        liq_cfg = self.config.section("liquidity")
        source = gates if gates is not None else liq_cfg
        def value(name: str) -> float:
            return float(source[name] if isinstance(source, dict) else getattr(source, name))
        if candidate.moneyness == Moneyness.ATM:
            ideal = value("atm_spread_ideal_pct"); acceptable = value("atm_spread_acceptable_pct"); reject = value("atm_spread_reject_pct")
        elif candidate.moneyness == Moneyness.ITM:
            ideal = value("itm_spread_ideal_pct"); acceptable = value("itm_spread_acceptable_pct"); reject = value("itm_spread_reject_pct")
        else:
            ideal = value("otm_spread_ideal_pct"); acceptable = value("otm_spread_acceptable_pct"); reject = value("otm_spread_reject_pct")
        if quote_stale or spread_pct > reject or spread > value("absolute_spread_cap_points"):
            return ContractQualityBreakdown(0, False, 0, 0, 0, 0, 0, 0, "Quote stale or spread hard rejected.")
        spread_score = linear_score(spread_pct, ideal, acceptable, reject)
        lot = candidate.instrument.lot_size
        min_top = min(quote.bid_qty / lot, quote.ask_qty / lot)
        top_floor = value("min_top_book_lots") if gates is not None else 0.0
        if gates is not None and min_top < top_floor:
            return ContractQualityBreakdown(0, False, 0, 0, 0, 0, 0, 0, f"Top-book depth below {top_floor:.1f} lots.")
        if min_top >= 5:
            top_score = 100.0
        elif min_top >= 2:
            top_score = 70.0 + 30.0 * (min_top - 2.0) / 3.0
        elif min_top >= 1:
            top_score = 40.0 + 30.0 * (min_top - 1.0)
        else:
            top_score = 0.0
        if quote.cumulative_bid_qty_5depth is not None and quote.cumulative_ask_qty_5depth is not None:
            min_depth = min(quote.cumulative_bid_qty_5depth / lot, quote.cumulative_ask_qty_5depth / lot)
            depth_floor = value("min_5depth_lots_each_side") if gates is not None else 10.0
            if gates is not None and min_depth < depth_floor:
                return ContractQualityBreakdown(0, False, 0, 0, 0, 0, 0, 0, f"Five-level depth below {depth_floor:.1f} lots.")
            depth_preferred = max(depth_floor * 2.5, depth_floor + 1.0)
            if min_depth >= depth_preferred:
                depth_score = 100.0
            elif min_depth >= depth_floor:
                depth_score = 70.0 + 30.0 * (min_depth - depth_floor) / max(1.0, depth_preferred - depth_floor)
            elif min_depth >= depth_floor * 0.5:
                depth_score = 40.0 + 30.0 * (min_depth - depth_floor * 0.5) / max(1.0, depth_floor * 0.5)
            else:
                depth_score = 0.0
        else:
            depth_score = top_score * 0.8
        liquidity_score = 0.6 * top_score + 0.4 * depth_score
        abs_delta = abs(candidate.greeks.delta) if candidate.greeks.delta is not None else self._delta_proxy(candidate.moneyness)
        delta_score = self._delta_score(abs_delta)
        gamma_score = self._gamma_score(abs_delta, expiry_day, aplus_context)
        theta_score = self._theta_score(theta_ratio)
        iv_score = self._iv_score(candidate.iv_crush_risk_score)
        total = 0.25 * liquidity_score + 0.20 * spread_score + 0.20 * delta_score + 0.15 * gamma_score + 0.10 * theta_score + 0.10 * iv_score
        return ContractQualityBreakdown(clamp(total), total >= 60.0, clamp(liquidity_score), clamp(spread_score), clamp(delta_score), clamp(gamma_score), clamp(theta_score), clamp(iv_score), "")

    @staticmethod
    def _delta_proxy(m: Moneyness) -> float:
        return {Moneyness.ATM: 0.5, Moneyness.ITM: 0.7, Moneyness.OTM: 0.3}[m]

    @staticmethod
    def _delta_score(abs_delta: float) -> float:
        if 0.45 <= abs_delta <= 0.65:
            return 100.0
        if 0.35 <= abs_delta < 0.45 or 0.65 < abs_delta <= 0.75:
            return 80.0
        if 0.25 <= abs_delta < 0.35 or 0.75 < abs_delta <= 0.85:
            return 60.0
        if 0.15 <= abs_delta < 0.25:
            return 30.0
        if abs_delta < 0.15:
            return 0.0
        return 70.0

    @staticmethod
    def _gamma_score(abs_delta: float, expiry_day: bool, aplus_context: bool) -> float:
        if 0.40 <= abs_delta <= 0.60:
            base = 100.0
        elif 0.30 <= abs_delta <= 0.70:
            base = 80.0
        elif 0.20 <= abs_delta <= 0.80:
            base = 50.0
        else:
            base = 20.0
        if expiry_day and not aplus_context:
            return min(base, 40.0)
        return base

    @staticmethod
    def _theta_score(theta_ratio: Optional[float]) -> float:
        if theta_ratio is None:
            return 50.0
        if theta_ratio >= 3.0:
            return 100.0
        if theta_ratio >= 2.0:
            return 80.0
        if theta_ratio >= 1.5:
            return 50.0
        if theta_ratio >= 1.0:
            return 20.0
        return 0.0

    @staticmethod
    def _iv_score(iv_crush: float) -> float:
        if iv_crush <= 30:
            return 100.0
        if iv_crush <= 50:
            return 80.0
        if iv_crush <= 70:
            return 50.0
        if iv_crush <= 85:
            return 20.0
        return 0.0


class PaperFillSimulator:
    def __init__(self, config: SystemConfig):
        self.config = config

    def entry_buy(self, quote: Quote, tick_size: float, slippage_baseline: float = 0.0) -> PaperFill:
        if not quote.is_valid():
            return PaperFill(False, None, None, 0.0, "Invalid quote.")
        spread = quote.spread
        buffer = max(tick_size, 0.10 * spread, slippage_baseline)
        limit = min(quote.ask + tick_size, quote.mid + 0.60 * spread)
        limit = round_to_tick(limit, tick_size)
        fill = quote.ask + buffer
        fill = round_to_tick(fill, tick_size)
        if fill <= limit + 1e-9:
            return PaperFill(True, fill, limit, buffer, "")
        return PaperFill(False, None, limit, buffer, "No fill under conservative paper-fill model.")

    def exit_sell(self, quote: Quote, tick_size: float, slippage_baseline: float = 0.0) -> PaperFill:
        if not quote.is_valid():
            return PaperFill(False, None, None, 0.0, "Invalid quote.")
        spread = quote.spread
        buffer = max(tick_size, 0.10 * spread, slippage_baseline)
        fill = round_to_tick(quote.bid - buffer, tick_size)
        if fill > 0:
            return PaperFill(True, fill, None, buffer, "")
        return PaperFill(False, None, None, buffer, "Exit fill not positive after slippage buffer.")


class OpportunityScorer:
    def __init__(self, config: SystemConfig, gate_provider=None):
        self.config = config
        self.gate_provider = gate_provider
        self.contract_quality = ContractQualityCalculator(config)
        self.risk = DynamicRiskCalculator(config)
        self.runtime_mode = "NORMAL"

    def set_runtime_mode(self, mode: str) -> None:
        normalized = str(mode or "NORMAL").upper()
        self.runtime_mode = normalized if normalized in {"NORMAL", "DEFENSIVE", "SURVIVAL"} else "NORMAL"

    def evaluate(self, candidate: CandidateInputs, realized_loss_today: float = 0.0) -> OpportunityEvaluation:
        reasons: list[str] = []
        gates = self._gates(candidate)
        cq = self.contract_quality.calculate(candidate, quote_stale=not candidate.data_health.valid, gates=gates)
        raw_setup_grade = str(candidate.setup_grade or (candidate.notes or {}).get("setup_grade", "")).strip().upper()
        if raw_setup_grade in {"A+", "A_PLUS", "A"}:
            setup_grade_hint = "A+" if raw_setup_grade == "A_PLUS" else raw_setup_grade
            setup_grade_source = "PLAYBOOK_METADATA"
        else:
            setup_grade_hint = "A+" if candidate.opportunity_confidence_score >= 80 and candidate.convexity_edge_score >= 90 else "A"
            setup_grade_source = "SCORE_FALLBACK"
        risk_plan = self.risk.plan(RiskContext(
            capital=float(self.config.section("capital")["starting_capital"]),
            mode=self.runtime_mode,
            setup_grade=setup_grade_hint,
            lots=1,
            entry_premium=candidate.quote.mid,
            lot_size=candidate.instrument.lot_size,
            spread_points=candidate.quote.spread,
            tick_size=candidate.instrument.tick_size,
            required_stop_points=max(candidate.required_stop_points, 0.0),
            instrument=candidate.instrument.underlying,
            realized_loss_today=realized_loss_today,
        ))
        if not candidate.data_health.valid:
            reasons.append("DataHealth invalid")
        contract_min = float(gates.contract_quality_min) if gates is not None else float(self.config.section("opportunity_selection").get("require_contract_quality_min", 0.0))
        if gates is not None and gates.status == CalibrationStatus.RETIRED:
            reasons.append("Instrument lifecycle retired")
        if candidate.lifecycle_state == "RETIRED":
            reasons.append("Instrument lifecycle retired")
        if gates is not None and candidate.calibrated_success_probability is not None and candidate.calibrated_success_probability < gates.min_calibrated_probability:
            reasons.append(f"Class calibrated probability below minimum: {candidate.calibrated_success_probability:.2f} < {gates.min_calibrated_probability:.2f}")
        if gates is not None and candidate.calibrated_net_expectancy_r is not None and candidate.calibrated_net_expectancy_r < gates.min_net_expectancy_r:
            reasons.append(f"Class calibrated expectancy below minimum: {candidate.calibrated_net_expectancy_r:.2f}R < {gates.min_net_expectancy_r:.2f}R")
        if not cq.valid:
            reasons.append(f"Contract invalid: {cq.reason}")
        elif cq.score < contract_min:
            reasons.append(f"ContractQuality below minimum: {cq.score:.1f} < {contract_min:.1f}")
        if not risk_plan.hard_stop_fit:
            reasons.append(f"HardStopFit false: {risk_plan.reason}")
        direction_cfg = self.config.section("phase1_direction_models")
        score_cfg = self.config.section("scores")
        selection_cfg = self.config.section("opportunity_selection")
        excellent_cfg = selection_cfg.get("excellent_gate_requirements", {})
        if not isinstance(excellent_cfg, dict):
            excellent_cfg = {}
        elasticity_cfg = self.config.section("premium_elasticity")
        expected_cfg = self.config.section("expected_move")
        direction_permission = max(
            float(direction_cfg.get("direction_bullish_permission", 45.0)),
            float(score_cfg.get("direction_min", 0.0)),
            float(getattr(gates, "direction_min", 0.0)) if gates is not None else 0.0,
        )
        # CandidateFactory stores direction from the candidate's own perspective:
        # calls inherit bullish context and puts negate it.  A negative value is
        # therefore a wrong-side setup, not a source of positive conviction.
        if candidate.instrument_direction_score < direction_permission:
            reasons.append(
                f"SideDirection hard reject: {candidate.instrument_direction_score:.1f} < {direction_permission:.1f}"
            )
        iv_max = min(
            float(selection_cfg.get("require_iv_crush_max", float("inf"))),
            float(self.config.section("iv_crush").get("hard_veto_above", float("inf"))),
            float(getattr(gates, "iv_crush_max", float("inf"))) if gates is not None else float("inf"),
        )
        if candidate.iv_crush_risk_score > iv_max:
            reasons.append(f"IVCrush hard reject: {candidate.iv_crush_risk_score:.1f} > {iv_max:.1f}")
        elasticity_min = max(
            float(selection_cfg.get("require_premium_elasticity_min", 0.0)),
            float(elasticity_cfg.get("reject_or_exit_threshold", 0.0)),
            float(getattr(gates, "premium_elasticity_min", 0.0)) if gates is not None else 0.0,
        )
        if candidate.premium_elasticity < elasticity_min:
            reasons.append(f"PremiumElasticity hard reject: {candidate.premium_elasticity:.2f} < {elasticity_min:.2f}")
        ratio_min = max(
            float(selection_cfg.get("require_expected_required_ratio_min", 0.0)),
            float(expected_cfg.get("hard_reject_ratio", 0.0)),
            float(getattr(gates, "expected_required_ratio_min", 0.0)) if gates is not None else 0.0,
        )
        if candidate.expected_required_ratio < ratio_min:
            reasons.append(f"Expected/Required hard reject: {candidate.expected_required_ratio:.2f} < {ratio_min:.2f}")
        hostility_max = min(
            float(selection_cfg.get("require_market_hostility_max", 100.0)),
            float(score_cfg.get("market_hostility_survival_max", 100.0)),
            float(getattr(gates, "market_hostility_max", 100.0)) if gates is not None else 100.0,
        )
        if candidate.market_hostility_score > hostility_max:
            reasons.append(f"MarketHostility hard reject: {candidate.market_hostility_score:.1f} > {hostility_max:.1f}")
        spread_pct = candidate.quote.spread / candidate.quote.mid * 100.0 if candidate.quote.mid > 0 else float("inf")
        learned_spread_max = float(getattr(gates, "spread_pct_max", float("inf"))) if gates is not None else float("inf")
        if spread_pct > learned_spread_max:
            reasons.append(f"InstrumentSpread hard reject: {spread_pct:.2f} > {learned_spread_max:.2f}")
        if candidate.trade_quality_score < max(float(score_cfg.get("trade_quality_min", 0.0)), float(getattr(gates, "trade_quality_min", 0.0)) if gates is not None else 0.0):
            reasons.append("TradeQuality below configured minimum")
        if candidate.regime_confidence < max(float(score_cfg.get("regime_confidence_min", 0.0)), float(getattr(gates, "regime_confidence_min", 0.0)) if gates is not None else 0.0):
            reasons.append("RegimeConfidence below configured minimum")
        if candidate.opportunity_confidence_score < max(float(score_cfg.get("final_confidence_min", 0.0)), float(getattr(gates, "final_confidence_min", 0.0)) if gates is not None else 0.0):
            reasons.append("FinalConfidence below configured minimum")
        execution_min = max(
            float(excellent_cfg.get("execution_quality_min", 80.0)),
            float(getattr(gates, "execution_quality_min", 0.0)) if gates is not None else 0.0,
        )
        if candidate.execution_quality_score < execution_min:
            reasons.append(f"ExecutionQuality below excellent gate: {candidate.execution_quality_score:.1f} < {execution_min:.1f}")
        convexity_min = float(excellent_cfg.get("convexity_edge_min", 80.0))
        if candidate.convexity_edge_score < convexity_min:
            reasons.append(f"ConvexityEdge below excellent gate: {candidate.convexity_edge_score:.1f} < {convexity_min:.1f}")
        confidence_min = max(
            float(excellent_cfg.get("opportunity_confidence_min", 70.0)),
            float(score_cfg.get("final_confidence_min", 0.0)),
            float(getattr(gates, "final_confidence_min", 0.0)) if gates is not None else 0.0,
        )
        if candidate.opportunity_confidence_score < confidence_min:
            reasons.append(f"OpportunityConfidence below excellent gate: {candidate.opportunity_confidence_score:.1f} < {confidence_min:.1f}")
        regime_fit_min = float(excellent_cfg.get("regime_fit_min", 70.0))
        if candidate.regime_fit_score < regime_fit_min:
            reasons.append(f"RegimeFit below excellent gate: {candidate.regime_fit_score:.1f} < {regime_fit_min:.1f}")
        if bool(excellent_cfg.get("required_stop_must_be_configured", True)) and candidate.required_stop_points <= 0:
            reasons.append("RequiredStop unavailable or non-positive")
        raw = self._raw_opportunity_score(candidate, cq.score)
        comparable = raw - self._calibration_penalty(candidate)
        threshold = self._dynamic_threshold(candidate)
        grade = self._grade(comparable, threshold, reasons)
        eligible = not reasons and grade in {OpportunityGrade.A, OpportunityGrade.A_PLUS}
        decision = self._decision(candidate, eligible, reasons)
        candidate = replace(candidate, notes={**dict(candidate.notes or {}), "setup_grade_source": setup_grade_source, "setup_grade_used": setup_grade_hint})
        return OpportunityEvaluation(candidate, cq, risk_plan, raw, comparable, threshold, grade, eligible, decision, tuple(reasons))

    def _raw_opportunity_score(self, c: CandidateInputs, contract_quality_score: float) -> float:
        weights = self.config.section("opportunity_selection").get("final_opportunity_score_weights", {})
        score = (
            float(weights.get("trade_quality_score", 0.25)) * c.trade_quality_score +
            float(weights.get("convexity_quality_score", 0.20)) * c.convexity_edge_score +
            float(weights.get("direction_score", 0.15)) * max(0.0, c.instrument_direction_score) +
            float(weights.get("execution_quality_score", 0.15)) * c.execution_quality_score +
            float(weights.get("regime_fit_score", 0.10)) * c.regime_fit_score +
            float(weights.get("opportunity_confidence_score", 0.10)) * c.opportunity_confidence_score +
            float(weights.get("contract_quality_score", 0.05)) * contract_quality_score
        )
        # Expected Value Engine: compute EV from calibrated data or proxy estimation
        ev_inputs = ExpectedValueInputs(
            expected_value_r=c.expected_value_r,
            win_rate=float(c.calibrated_success_probability or 0.0),
            avg_win_r=1.8,
            avg_loss_r=1.0,
            calibrated_success_probability=c.calibrated_success_probability,
            calibrated_net_expectancy_r=c.calibrated_net_expectancy_r,
            calibration_status_direction=c.calibration_status_direction,
            calibration_status_liquidity=c.calibration_status_liquidity,
            premium_elasticity_score=clamp(c.premium_elasticity * 100.0),
            gamma_usefulness_score=80.0,
        )
        ev = ExpectedValueEngine.calculate_ev(ev_inputs)
        ev_score = ExpectedValueEngine.score(ev)
        score += float(weights.get("expected_value_score", 0.10)) * ev_score
        score -= max(0.0, c.market_hostility_score - 20.0) * 0.25
        if bool((c.notes or {}).get("same_direction_recent_loss", False)):
            penalty_cfg = self.config.section("opportunity_selection").get("penalties", {})
            score -= float(penalty_cfg.get("same_direction_recent_loss_penalty", 20.0))
        return clamp(score)

    def _calibration_penalty(self, c: CandidateInputs) -> float:
        penalty = 0.0
        if c.calibration_status_direction == CalibrationStatus.UNVALIDATED:
            penalty += 10.0
        if c.calibration_status_liquidity == CalibrationStatus.UNVALIDATED:
            penalty += 15.0 if c.instrument.underlying == "MIDCPNIFTY" else 10.0
        if c.calibration_status_direction == CalibrationStatus.RETIRED or c.calibration_status_liquidity == CalibrationStatus.RETIRED:
            penalty += 100.0
        return penalty

    def _dynamic_threshold(self, c: CandidateInputs) -> float:
        base = float(self.config.section("opportunity_selection")["excellent_opportunity_min_score"])
        gates = self._gates(c)
        if gates is not None:
            base = max(base, gates.excellent_score_min)
        if c.instrument.underlying == "MIDCPNIFTY" and c.calibration_status_liquidity != CalibrationStatus.VALIDATED:
            base += 10.0
        if c.iv_crush_risk_score >= 50.0:
            base += 5.0
        notes = c.notes or {}
        try:
            gap_pct = abs(float(notes.get("gap_pct")))
        except (TypeError, ValueError):
            gap_pct = 0.0
        gap_cfg = self.config.section("gap")
        if gap_pct > float(gap_cfg.get("small_gap_pct", 0.50)):
            base += float(self.config.raw.get("excellence_framework", {}).get("dynamic_threshold_additions", {}).get("gap_day_above_0_50_pct", 5.0))
        expiry_flag = notes.get("expiry_day", notes.get("expiry_week_flag", False))
        if expiry_flag is True or str(expiry_flag).strip().lower() in {"1", "true", "yes", "y"}:
            base += float(self.config.raw.get("excellence_framework", {}).get("dynamic_threshold_additions", {}).get("expiry_day", 5.0))
        if bool(notes.get("same_direction_recent_loss", False)):
            base += float(self.config.raw.get("excellence_framework", {}).get("dynamic_threshold_additions", {}).get("same_direction_recent_loss", 10.0))
        return base

    def _gates(self, candidate: CandidateInputs) -> Optional[ClassGateSet]:
        if self.gate_provider is None:
            return None
        try:
            return self.gate_provider(candidate.instrument.instrument_class, candidate.instrument.underlying)
        except TypeError:
            try:
                return self.gate_provider(candidate.instrument.instrument_class)
            except Exception:
                return None
        except Exception:
            return None

    @staticmethod
    def _grade(score: float, threshold: float, reasons: list[str]) -> OpportunityGrade:
        if reasons:
            return OpportunityGrade.REJECT
        if score >= max(90.0, threshold + 10.0):
            return OpportunityGrade.A_PLUS
        if score >= threshold:
            return OpportunityGrade.A
        if score >= 70.0:
            return OpportunityGrade.B
        if score >= 60.0:
            return OpportunityGrade.C
        return OpportunityGrade.REJECT

    @staticmethod
    def _decision(c: CandidateInputs, eligible: bool, reasons: list[str]) -> TradeDecision:
        if reasons:
            if any("DataHealth" in r for r in reasons):
                return TradeDecision.DATA_INVALID
            if any("Contract" in r for r in reasons):
                return TradeDecision.CONTRACT_INVALID
            return TradeDecision.NO_TRADE
        if not eligible:
            return TradeDecision.NO_EXCELLENT_CANDIDATE
        return TradeDecision.BUY_CALL_CANDIDATE if c.side.value == "CE" else TradeDecision.BUY_PUT_CANDIDATE


class CandidateRevalidator:
    def __init__(self, config: SystemConfig):
        self.config = config

    def revalidate(self, evaluation: OpportunityEvaluation, current_quote: Quote, now: datetime, ranking_spread: float, fast_market: bool = False) -> tuple[bool, tuple[str, ...]]:
        reasons: list[str] = []
        candidate = evaluation.candidate
        created = candidate.candidate_created_at or candidate.quote.timestamp
        max_age = float(self.config.section("candidate_revalidation")["fast_market_max_candidate_age_sec" if fast_market else "normal_market_max_candidate_age_sec"])
        age = (now - created).total_seconds()
        if age > max_age:
            reasons.append("Candidate age exceeds revalidation limit")
        if not current_quote.is_valid():
            reasons.append("Current quote invalid")
        max_spread_multiple = float(self.config.section("candidate_revalidation")["max_spread_expansion_from_ranking_multiple"])
        if ranking_spread > 0 and current_quote.spread > max_spread_multiple * ranking_spread:
            reasons.append("Spread expanded beyond revalidation limit")
        if evaluation.comparable_opportunity_score < evaluation.dynamic_excellent_threshold:
            reasons.append("Opportunity score below dynamic threshold")
        if not evaluation.risk_plan.hard_stop_fit:
            reasons.append("Hard stop no longer fits")
        return (not reasons, tuple(reasons))
