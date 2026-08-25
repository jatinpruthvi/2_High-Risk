import unittest
from dataclasses import replace
from datetime import datetime, date

from institutional_options.config import SystemConfig
from institutional_options.engine import PaperOpportunityEngine, PaperPortfolioState
from institutional_options.models import CandidateInputs, CalibrationStatus, DataHealth, Greeks, InstrumentSpec, Moneyness, OptionType, Quote, TradeDecision
from institutional_options.scoring import CandidateRevalidator, ContractQualityCalculator, OpportunityScorer, PaperFillSimulator
from institutional_options.risk import DynamicRiskCalculator, RiskContext
from institutional_options.orchestrators import DataHealthOrchestrator
from institutional_options.edge_modules import ExpectedValueEngine, ExpectedValueInputs, ExecutionQualityCalculator


def candidate(underlying="NIFTY", score=90, opt=OptionType.CE):
    now = datetime(2026, 6, 1, 10, 0, 0)
    return CandidateInputs(
        instrument=InstrumentSpec(underlying, "1", "OPTIDX", date(2026, 6, 30), 75, 0.05, 25000, opt),
        quote=Quote(100, 100.5, 1000, 1000, 100.25, now, 5000, 5000),
        moneyness=Moneyness.ATM,
        greeks=Greeks(delta=0.5, gamma=0.01, theta=-5, vega=2, iv=15),
        data_health=DataHealth(True),
        futures_price=25000,
        underlying_price=25000,
        instrument_direction_score=score if opt == OptionType.CE else -score,
        trade_quality_score=score,
        regime_confidence=80,
        market_hostility_score=10,
        iv_crush_risk_score=20,
        premium_elasticity=1.2,
        expected_move=200,
        required_move=100,
        required_stop_points=10,
        expected_value_r=0.5,
        vol_edge_ratio=2.0,
        convexity_edge_score=score,
        execution_quality_score=score,
        opportunity_confidence_score=score,
        regime_fit_score=score,
        candidate_created_at=now,
        calibration_status_direction=CalibrationStatus.VALIDATED,
        calibration_status_liquidity=CalibrationStatus.VALIDATED,
    )


class ExpectedValueEngineTests(unittest.TestCase):
    def test_positive_expectancy_with_high_win_rate(self):
        inputs = ExpectedValueInputs(
            expected_value_r=0.6,
            win_rate=0.6,
            avg_win_r=2.0,
            avg_loss_r=1.0,
            premium_elasticity_score=70.0,
            gamma_usefulness_score=80.0,
        )
        ev = ExpectedValueEngine.calculate_ev(inputs)
        self.assertGreater(ev, 0.0)
        score = ExpectedValueEngine.score(ev)
        self.assertGreater(score, 50.0)

    def test_negative_expectancy_with_low_win_rate(self):
        inputs = ExpectedValueInputs(
            expected_value_r=-0.2,
            win_rate=0.3,
            avg_win_r=1.5,
            avg_loss_r=1.0,
            premium_elasticity_score=30.0,
            gamma_usefulness_score=40.0,
        )
        ev = ExpectedValueEngine.calculate_ev(inputs)
        self.assertLess(ev, 0.0)
        score = ExpectedValueEngine.score(ev)
        self.assertLess(score, 50.0)

    def test_calibrated_net_expectancy_is_used_when_available(self):
        inputs = ExpectedValueInputs(
            expected_value_r=0.5,
            win_rate=0.4,
            avg_win_r=1.5,
            avg_loss_r=1.0,
            calibrated_success_probability=0.5,
            calibrated_net_expectancy_r=0.8,
            calibration_status_direction=CalibrationStatus.VALIDATED,
            calibration_status_liquidity=CalibrationStatus.VALIDATED,
            premium_elasticity_score=50.0,
            gamma_usefulness_score=60.0,
        )
        ev = ExpectedValueEngine.calculate_ev(inputs)
        # Should return the calibrated value, not the proxy
        self.assertAlmostEqual(ev, 0.8, places=4)

    def test_calibrated_success_probability_is_used(self):
        inputs = ExpectedValueInputs(
            expected_value_r=0.0,
            win_rate=0.3,
            avg_win_r=1.8,
            avg_loss_r=1.0,
            calibrated_success_probability=0.65,
            calibrated_net_expectancy_r=None,
            calibration_status_direction=CalibrationStatus.VALIDATED,
            calibration_status_liquidity=CalibrationStatus.VALIDATED,
            premium_elasticity_score=50.0,
            gamma_usefulness_score=60.0,
        )
        ev = ExpectedValueEngine.calculate_ev(inputs)
        expected_ev = (0.65 * 1.8) - (0.35 * 1.0) - 0.08
        self.assertAlmostEqual(ev, expected_ev, places=4)

    def test_proxy_ev_uses_elasticity_and_gamma(self):
        inputs = ExpectedValueInputs(
            expected_value_r=0.0,
            win_rate=0.0,
            avg_win_r=0.0,
            avg_loss_r=0.0,
            calibrated_success_probability=None,
            calibrated_net_expectancy_r=None,
            calibration_status_direction=CalibrationStatus.UNVALIDATED,
            calibration_status_liquidity=CalibrationStatus.UNVALIDATED,
            premium_elasticity_score=70.0,  # 0.70 win rate
            gamma_usefulness_score=80.0,    # 2.6R avg win
        )
        ev = ExpectedValueEngine.calculate_ev(inputs)
        expected_ev = (0.70 * 2.6) - (0.30 * 1.0) - 0.08
        self.assertAlmostEqual(ev, expected_ev, places=4)

    def test_ev_score_mapping(self):
        # EV above ideal -> 100
        self.assertEqual(ExpectedValueEngine.score(1.0), 100.0)
        # EV between acceptable and ideal -> 70-100
        self.assertAlmostEqual(ExpectedValueEngine.score(0.3), 70.0 + 30.0 * (0.3 - 0.1) / (0.5 - 0.1), places=2)
        # EV below reject -> 0
        self.assertEqual(ExpectedValueEngine.score(-0.5), 0.0)

    def test_direct_ev_calculation(self):
        ev = ExpectedValueEngine.ev_r_from_inputs(win_rate=0.6, avg_win_r=2.0, avg_loss_r=1.0)
        expected = (0.6 * 2.0) - (0.4 * 1.0) - 0.08
        self.assertAlmostEqual(ev, expected, places=4)


class ExecutionQualityCalculatorTests(unittest.TestCase):
    def setUp(self):
        self.calc = ExecutionQualityCalculator()

    def test_no_returns_neutral_score(self):
        score = self.calc.score("NIFTY")
        self.assertEqual(score, 50.0)

    def test_perfect_execution_returns_high_score(self):
        # Record a fill with zero slippage
        self.calc.record_fill(
            instrument="NIFTY",
            fill_price=100.0,
            mid_price=100.0,
            spread_pct=1.0,
            side="CE",
            timestamp=1000.0
        )
        score = self.calc.score("NIFTY", current_spread_pct=1.0)
        self.assertGreater(score, 90.0)  # Should be close to 100

    def test_high_slippage_returns_low_score(self):
        # Record a fill with 50% slippage relative to spread
        self.calc.record_fill(
            instrument="NIFTY",
            fill_price=102.0,
            mid_price=100.0,
            spread_pct=2.0,
            side="CE",
            timestamp=1000.0
        )
        score = self.calc.score("NIFTY", current_spread_pct=2.0)
        self.assertLess(score, 50.0)  # Should be around 0 for 50% slippage

    def test_weighted_average_uses_recent_fills_more(self):
        # Old fill: bad execution
        self.calc.record_fill(
            instrument="NIFTY",
            fill_price=105.0,
            mid_price=100.0,
            spread_pct=2.0,
            side="CE",
            timestamp=1000.0
        )
        # Recent fill: good execution
        self.calc.record_fill(
            instrument="NIFTY",
            fill_price=100.5,
            mid_price=100.0,
            spread_pct=2.0,
            side="CE",
            timestamp=2000.0
        )
        score = self.calc.score("NIFTY", current_spread_pct=2.0)
        # Should be better than the average of the two (which would be ~50)
        self.assertGreater(score, 50.0)

    def test_time_of_day_adjustment(self):
        # Record a fill
        self.calc.record_fill(
            instrument="NIFTY",
            fill_price=102.0,
            mid_price=100.0,
            spread_pct=2.0,
            side="CE",
            timestamp=1000.0
        )
        # Score at hour 9 (open volatility) should be more forgiving
        score_open = self.calc.score("NIFTY", current_spread_pct=2.0, hour=9)
        # Score at hour 12 (mid-session) should be stricter
        score_mid = self.calc.score("NIFTY", current_spread_pct=2.0, hour=12)
        self.assertGreater(score_open, score_mid)

    def test_get_avg_slippage_pct(self):
        self.calc.record_fill(
            instrument="NIFTY",
            fill_price=102.0,
            mid_price=100.0,
            spread_pct=2.0,
            side="CE",
            timestamp=1000.0
        )
        self.calc.record_fill(
            instrument="NIFTY",
            fill_price=101.0,
            mid_price=100.0,
            spread_pct=2.0,
            side="CE",
            timestamp=2000.0
        )
        avg = self.calc.get_avg_slippage_pct("NIFTY")
        self.assertAlmostEqual(avg, 1.5, places=2)  # (2.0 + 1.0) / 2 = 1.5% avg slippage

    def test_get_fill_count(self):
        self.assertEqual(self.calc.get_fill_count("NIFTY"), 0)
        self.calc.record_fill(
            instrument="NIFTY",
            fill_price=100.0,
            mid_price=100.0,
            spread_pct=1.0,
            side="CE",
            timestamp=1000.0
        )
        self.assertEqual(self.calc.get_fill_count("NIFTY"), 1)


class ScoringEngineTests(unittest.TestCase):
    def setUp(self):
        self.cfg = SystemConfig.from_file("uploads/PARAMETERS.json")

    def test_contract_quality_good(self):
        cq = ContractQualityCalculator(self.cfg).calculate(candidate())
        self.assertTrue(cq.valid)
        self.assertGreaterEqual(cq.score, 80)

    def test_paper_fill_uses_bid_ask(self):
        sim = PaperFillSimulator(self.cfg)
        fill = sim.entry_buy(candidate().quote, 0.05)
        self.assertTrue(fill.filled)
        self.assertGreaterEqual(fill.fill_price, 100.5)

    def test_contract_quality_minimum_is_enforced(self):
        scorer = OpportunityScorer(self.cfg)
        low_depth_quote = Quote(100.0, 100.5, 10, 10, 100.25,
                                datetime(2026, 6, 1, 10, 0, 0), 100, 100)
        evaluation = scorer.evaluate(replace(candidate(), quote=low_depth_quote))
        self.assertFalse(evaluation.eligible)
        self.assertTrue(any("ContractQuality below minimum" in r for r in evaluation.reasons))

    def test_declared_core_strategy_gates_are_enforced(self):
        scorer = OpportunityScorer(self.cfg)
        weak = replace(
            candidate(),
            instrument_direction_score=50.0,
            premium_elasticity=0.9,
            expected_move=120.0,
            required_move=100.0,
            market_hostility_score=40.0,
            trade_quality_score=60.0,
            regime_confidence=50.0,
            opportunity_confidence_score=60.0,
        )
        evaluation = scorer.evaluate(weak)
        self.assertFalse(evaluation.eligible)
        reasons = " | ".join(evaluation.reasons)
        for text in ("SideDirection", "PremiumElasticity", "Expected/Required",
                     "MarketHostility", "TradeQuality", "RegimeConfidence", "FinalConfidence"):
            self.assertIn(text, reasons)

    def test_wrong_side_candidate_is_rejected(self):
        scorer = OpportunityScorer(self.cfg)
        bearish_put = candidate(opt=OptionType.PE)
        evaluation = scorer.evaluate(bearish_put)
        self.assertFalse(evaluation.eligible)
        self.assertTrue(any("SideDirection hard reject" in r for r in evaluation.reasons))

    def test_candidate_revalidation_rejects_spread_expansion(self):
        scorer = OpportunityScorer(self.cfg)
        evaluation = scorer.evaluate(candidate())
        revalidator = CandidateRevalidator(self.cfg)
        widened = Quote(95.0, 97.0, 1000, 1000, 96.0, datetime(2026, 6, 1, 10, 0, 1), 5000, 5000)
        ok, reasons = revalidator.revalidate(
            evaluation, widened, datetime(2026, 6, 1, 10, 0, 1),
            ranking_spread=evaluation.candidate.quote.spread,
        )
        self.assertFalse(ok)
        self.assertIn("Spread expanded", " | ".join(reasons))

    def test_engine_selects_best_excellent(self):
        engine = PaperOpportunityEngine(self.cfg)
        weak = candidate("BANKNIFTY", 75)
        strong = candidate("NIFTY", 95)
        result = engine.evaluate_and_select([weak, strong])
        self.assertEqual(result.decision, TradeDecision.BUY_CALL_CANDIDATE)
        self.assertEqual(result.selected.candidate.instrument.underlying, "NIFTY")

    def test_unresolved_tie_is_explicit_no_trade(self):
        engine = PaperOpportunityEngine(self.cfg)
        result = engine.evaluate_and_select([candidate("NIFTY", 90), candidate("BANKNIFTY", 90)])
        self.assertEqual(result.decision, TradeDecision.NO_TRADE)
        self.assertTrue(any("ambiguous" in reason.lower() for reason in result.reasons))

    def test_global_position_lock_blocks(self):
        engine = PaperOpportunityEngine(self.cfg)
        result = engine.evaluate_and_select([candidate()], PaperPortfolioState(open_positions_count=1))
        self.assertEqual(result.decision, TradeDecision.GLOBAL_POSITION_LOCK_ACTIVE)

    def test_source_timestamp_is_required_for_strict_health(self):
        health = DataHealthOrchestrator(self.cfg)
        now = datetime(2026, 6, 1, 10, 0, 1)
        self.assertFalse(health.evaluate_candidate(candidate(), now).valid)
        timestamped = replace(candidate(), quote=Quote(100, 100.5, 1000, 1000, 100.25, now, 5000, 5000, True))
        self.assertTrue(health.evaluate_candidate(timestamped, now).valid)

    def test_excellent_gate_boundaries_are_hard_rejects(self):
        scorer = OpportunityScorer(self.cfg)
        for field, reason in (("execution_quality_score", "ExecutionQuality"),
                              ("convexity_edge_score", "ConvexityEdge"),
                              ("opportunity_confidence_score", "OpportunityConfidence"),
                              ("regime_fit_score", "RegimeFit")):
            boundary = 69.0 if field in {"opportunity_confidence_score", "regime_fit_score"} else 79.0
            evaluation = scorer.evaluate(replace(candidate(), **{field: boundary}))
            self.assertFalse(evaluation.eligible, field)
            self.assertTrue(any(reason in item for item in evaluation.reasons), (field, evaluation.reasons))

    def test_zero_quote_depth_is_data_invalid(self):
        health = DataHealthOrchestrator(self.cfg)
        stale_depth = replace(candidate(), quote=Quote(100, 100.5, 0, 1000, 100.25, datetime(2026, 6, 1, 10, 0)))
        result = health.evaluate_candidate(stale_depth, datetime(2026, 6, 1, 10, 0, 1))
        self.assertFalse(result.valid)
        self.assertIn("depth", result.reason.lower())

    def test_survival_daily_mode_blocks_new_risk(self):
        scorer = OpportunityScorer(self.cfg)
        scorer.set_runtime_mode("SURVIVAL")
        evaluation = scorer.evaluate(candidate())
        self.assertFalse(evaluation.risk_plan.hard_stop_fit)
        self.assertEqual(evaluation.risk_plan.max_allowed_risk, 0.0)

    def test_explicit_playbook_grade_is_used_for_risk_provenance(self):
        evaluation = OpportunityScorer(self.cfg).evaluate(replace(candidate(), setup_grade="A"))
        self.assertEqual(evaluation.candidate.notes["setup_grade_source"], "PLAYBOOK_METADATA")
        self.assertEqual(evaluation.candidate.notes["setup_grade_used"], "A")

    def test_missing_required_stop_is_fail_closed(self):
        evaluation = OpportunityScorer(self.cfg).evaluate(replace(candidate(), required_stop_points=0.0))
        self.assertFalse(evaluation.eligible)
        self.assertTrue(any("RequiredStop" in item for item in evaluation.reasons))

    def test_aplus_new_trade_cap_respects_normal_instrument_and_daily_caps(self):
        calc = DynamicRiskCalculator(self.cfg)
        plan = calc.plan(RiskContext(
            capital=100000, mode="NORMAL", setup_grade="A+", lots=1,
            entry_premium=80, lot_size=30, spread_points=1, tick_size=0.05,
            required_stop_points=10, instrument="BANKNIFTY", realized_loss_today=0,
        ))
        self.assertEqual(plan.max_allowed_risk, 750.0)


if __name__ == "__main__":
    unittest.main()
