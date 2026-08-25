from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from institutional_options.config import SystemConfig
from institutional_options.models import (
    CandidateInputs, DataHealth, Greeks, InstrumentSpec, Moneyness, OptionType,
    OpportunityEvaluation, OpportunityGrade, Quote, RiskPlan, TradeDecision,
)
from institutional_options.research_controls import (
    InstrumentCalibrationStore, InstrumentClass, InstrumentLifecycle,
    PromotionEngine, PromotionMetrics, exposure_group, version_fingerprint,
)
from institutional_options.research_ledger import ResearchEventLedger, ShadowTradeTracker
from institutional_options.scoring import PaperFillSimulator


ROOT = Path(__file__).resolve().parents[1]
CONFIG = SystemConfig.from_file(ROOT / "uploads" / "PARAMETERS.json")


class ResearchControlTests(unittest.TestCase):
    def test_class_profiles_are_conservative_and_distinct(self):
        with tempfile.TemporaryDirectory() as d:
            store = InstrumentCalibrationStore(d, CONFIG)
            nse = store.gates_for(InstrumentClass.NSE_INDEX.value)
            bse = store.gates_for(InstrumentClass.BSE_INDEX.value)
            stock = store.gates_for(InstrumentClass.NSE_STOCK_OPTION.value)
            self.assertGreaterEqual(bse.contract_quality_min, nse.contract_quality_min)
            self.assertGreaterEqual(stock.contract_quality_min, bse.contract_quality_min)
            self.assertGreaterEqual(stock.min_5depth_lots_each_side, nse.min_5depth_lots_each_side)

    def test_measured_gate_never_loose_than_configured_floor(self):
        with tempfile.TemporaryDirectory() as d:
            store = InstrumentCalibrationStore(d, CONFIG)
            now = datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc)
            for i in range(5):
                store.record_observation(
                    InstrumentClass.NSE_INDEX.value, now + timedelta(days=i),
                    True, True, 0.2, 100.0, 100.0,
                )
            gates = store.gates_for(InstrumentClass.NSE_INDEX.value)
            self.assertGreaterEqual(gates.atm_spread_reject_pct, 2.0)
            self.assertEqual(gates.status.value, "OBSERVED")

    def test_outcome_calibration_requires_sufficient_class_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            store = InstrumentCalibrationStore(d, CONFIG)
            cls = InstrumentClass.NSE_INDEX.value
            self.assertIsNone(store.outcome_calibration(cls, 85.0)[0])
            for i in range(20):
                store.record_outcome(cls, 85.0, 1.0 if i < 15 else -0.5, 100.0 if i < 15 else -50.0)
            probability, expectancy, status = store.outcome_calibration(cls, 85.0)
            self.assertAlmostEqual(probability, 0.75)
            self.assertAlmostEqual(expectancy, 0.625)
            self.assertEqual(status.value, "VALIDATED")

    def test_instrument_gate_learning_stays_at_class_floor_during_warmup(self):
        with tempfile.TemporaryDirectory() as d:
            store = InstrumentCalibrationStore(d, CONFIG)
            gates = store.gates_for(InstrumentClass.NSE_INDEX.value, "NIFTY")
            self.assertEqual(gates.gate_learning_status, "WARMUP_OBSERVATIONS")
            self.assertEqual(gates.gate_learning_observations, 0)
            self.assertGreaterEqual(gates.direction_min, 65.0)
            self.assertGreaterEqual(gates.expected_required_ratio_min, 1.6)

    def test_gate_resolution_path_is_explicit_and_conservative(self):
        with tempfile.TemporaryDirectory() as d:
            store = InstrumentCalibrationStore(d, CONFIG)
            gates = store.gates_for(InstrumentClass.NSE_INDEX.value, "NIFTY")
            self.assertIn("GLOBAL_POLICY_FLOOR>CLASS_FLOOR>INSTRUMENT_LEARNED_FLOOR", gates.gate_resolution_path)
            self.assertIn("LOWER=max", gates.gate_resolution_path)
            self.assertIn("UPPER=min", gates.gate_resolution_path)
            self.assertGreaterEqual(gates.direction_min, 65.0)
            self.assertLessEqual(gates.market_hostility_max, 35.0)

    def test_instrument_gate_learning_requires_multi_day_positive_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            store = InstrumentCalibrationStore(d, CONFIG)
            cls = InstrumentClass.NSE_INDEX.value
            base = {
                "contract_quality_min": 92, "direction_min": 78,
                "premium_elasticity_min": 1.8, "expected_required_ratio_min": 2.2,
                "trade_quality_min": 88, "final_confidence_min": 82,
                "execution_quality_min": 85, "regime_confidence_min": 80,
                "market_hostility_max": 18, "iv_crush_max": 25,
                "spread_pct_max": 0.8, "min_top_book_lots": 8,
                "min_5depth_lots_each_side": 35, "excellent_score_min": 91,
            }
            now = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
            for day in range(20):
                for _ in range(5):
                    store.record_gate_observation("NIFTY", cls, now + timedelta(days=day), base, True, 91.0)
            for day in range(20):
                for _ in range(4):
                    store.record_outcome(
                        cls, 91.0, 0.5, 100.0, instrument_id="NIFTY", paper=True,
                        features=base, observed_at=now + timedelta(days=day),
                    )
            for _ in range(2):
                store.record_outcome(
                    cls, 91.0, 0.5, 100.0, instrument_id="NIFTY", paper=True,
                    features=base, observed_at=now + timedelta(days=20),
                )
            gates = store.gates_for(cls, "NIFTY")
            self.assertEqual(gates.gate_learning_status, "LEARNED_IDEAL_GATE")
            self.assertEqual(gates.gate_learning_observations, 100)
            self.assertEqual(gates.gate_learning_sessions, 20)
            self.assertEqual(gates.gate_learning_outcomes, 82)
            self.assertEqual(gates.gate_optimization_status, "INSTRUMENT_VALIDATED")
            self.assertGreaterEqual(gates.gate_validation_observations, 20)
            self.assertGreaterEqual(gates.gate_validation_retention, 0.60)
            self.assertGreaterEqual(gates.direction_min, 65.0)
            self.assertGreaterEqual(gates.trade_quality_min, 70.0)
            self.assertLessEqual(gates.market_hostility_max, 35.0)
            self.assertLessEqual(gates.iv_crush_max, 50.0)
            self.assertGreaterEqual(gates.spread_pct_max, 0.8)
            self.assertEqual(gates.gate_optimization_method, "CONSTRAINED_WALK_FORWARD")
            self.assertEqual(gates.highest_observed_gate["direction_min"], 78.0)
            self.assertEqual(gates.high_watermark_gate["direction_min"], 78.0)
            self.assertGreaterEqual(CONFIG.raw["instrument_gate_learning"]["warmup_days"], 5)

    def test_walk_forward_optimizer_promotes_and_rolls_back_instrument_gate(self):
        with tempfile.TemporaryDirectory() as d:
            store = InstrumentCalibrationStore(d, CONFIG)
            cls = InstrumentClass.NSE_INDEX.value
            low = {
                "contract_quality_min": 80, "direction_min": 65,
                "premium_elasticity_min": 0.6, "expected_required_ratio_min": 1.2,
                "trade_quality_min": 70, "final_confidence_min": 65,
                "execution_quality_min": 80, "regime_confidence_min": 70,
                "market_hostility_max": 25, "iv_crush_max": 30,
                "spread_pct_max": 1.0, "min_top_book_lots": 3,
                "min_5depth_lots_each_side": 12, "excellent_score_min": 82,
            }
            high = {**low, "direction_min": 85}
            now = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
            for day in range(20):
                for _ in range(5):
                    store.record_gate_observation("NIFTY", cls, now + timedelta(days=day), high, True, 90.0)
            # Training window: positive outcomes satisfy the stricter feature; negative
            # outcomes satisfy only the class floor, creating a measurable improvement.
            for i in range(35):
                day = 20 + (i % 7)
                store.record_outcome(cls, 90.0, 0.5, 100.0, instrument_id="NIFTY", paper=True, features=high, observed_at=now + timedelta(days=day))
            for i in range(21):
                day = 20 + (i % 7)
                store.record_outcome(cls, 75.0, -0.2, -40.0, instrument_id="NIFTY", paper=True, features=low, observed_at=now + timedelta(days=day))
            # Validation window: 15 strict winners and 9 floor-only losers.
            for i in range(15):
                store.record_outcome(cls, 90.0, 0.5, 100.0, instrument_id="NIFTY", paper=True, features=high, observed_at=now + timedelta(days=27 + (i % 8)))
            for i in range(9):
                store.record_outcome(cls, 75.0, -0.2, -40.0, instrument_id="NIFTY", paper=True, features=low, observed_at=now + timedelta(days=27 + (i % 8)))
            # A second complete validation window is required before promotion.
            for i in range(13):
                store.record_outcome(cls, 90.0, 0.5, 100.0, instrument_id="NIFTY", paper=True, features=high, observed_at=now + timedelta(days=35 + (i % 8)))
            gates = store.gates_for(cls, "NIFTY")
            self.assertEqual(gates.gate_learning_status, "LEARNED_IDEAL_GATE")
            self.assertEqual(gates.gate_optimization_status, "INSTRUMENT_VALIDATED")
            self.assertGreaterEqual(gates.direction_min, 85.0)
            self.assertGreaterEqual(gates.gate_validation_retention, 0.60)
            validated_direction = gates.direction_min
            # New negative evidence invalidates the candidate; the last validated
            # gate remains active rather than loosening to the class floor.
            for i in range(20):
                store.record_outcome(cls, 75.0, -0.3, -60.0, instrument_id="NIFTY", paper=True, features=high, observed_at=now + timedelta(days=36 + i))
            degraded = store.gates_for(cls, "NIFTY")
            self.assertEqual(degraded.gate_optimization_status, "INSTRUMENT_DEGRADED")
            self.assertGreaterEqual(degraded.direction_min, validated_direction)

    def test_forward_proxy_outcome_links_features_without_counting_paper_trade(self):
        with tempfile.TemporaryDirectory() as d:
            store = InstrumentCalibrationStore(d, CONFIG)
            added = store.record_forward_outcomes([{
                "status": "OBSERVED", "skip_id": "s1", "window_minutes": 30,
                "observed_at": "2026-08-20T10:00:00+00:00", "underlying": "NIFTY",
                "instrument_id": "NIFTY", "instrument_class": InstrumentClass.NSE_INDEX.value,
                "ComparableOpportunityScore": 88.0, "forward_r_multiple": 0.75,
                "gate_features_json": '{"direction_min": 82, "spread_pct_max": 0.8}',
            }])
            self.assertEqual(added, 1)
            row = store.state["gate_learning"]["NIFTY"]
            self.assertEqual(len(row["forward_outcomes"]), 1)
            self.assertTrue(row["forward_outcomes"][0]["proxy"])
            self.assertEqual(store.instrument_metrics("NIFTY")["paper_trades"], 0)

    def test_promotion_stops_at_review_for_monitor_only_instruments(self):
        with tempfile.TemporaryDirectory() as d:
            store = InstrumentCalibrationStore(d, CONFIG)
            engine = PromotionEngine(store)
            cls = InstrumentClass.NSE_STOCK_OPTION.value
            base = dict(observations=250, sessions=20, valid_quote_rate=0.99, paper_fill_rate=0.95)
            first = engine.evaluate(cls, InstrumentLifecycle.MONITOR, PromotionMetrics(**base), monitor_only=True)
            self.assertEqual(first.recommended_state, InstrumentLifecycle.SHADOW)
            shadow = engine.evaluate(cls, InstrumentLifecycle.SHADOW, PromotionMetrics(**base, shadow_outcomes=20, shadow_net_expectancy_r=0.2), monitor_only=True)
            self.assertEqual(shadow.recommended_state, InstrumentLifecycle.PAPER_ELIGIBLE)
            paper = engine.evaluate(cls, InstrumentLifecycle.PAPER_ELIGIBLE, PromotionMetrics(**base, shadow_outcomes=20, shadow_net_expectancy_r=0.2, paper_trades=50, paper_net_expectancy_r=0.15), monitor_only=True)
            self.assertTrue(paper.trade_review_ready)
            self.assertEqual(paper.recommended_state, InstrumentLifecycle.PAPER_ELIGIBLE)

    def test_versioned_event_ledger_and_exposure_group(self):
        with tempfile.TemporaryDirectory() as d:
            versions = version_fingerprint(CONFIG, {"NIFTY": {"exchange": "NSE"}})
            ledger = ResearchEventLedger(d, versions)
            ledger.append("TEST", session_id="s1", underlying="BANKNIFTY", exchange="NSE", instrument_kind="INDEX", instrument_class="NSE_INDEX", lifecycle_state="SHADOW", decision_source="unit_test", payload={"score": 81})
            with (Path(d) / "research_events.csv").open(newline="", encoding="utf-8") as f:
                row = next(csv.DictReader(f))
            self.assertEqual(row["strategy_version"], versions.strategy_version)
            self.assertEqual(row["exposure_group"], "INDEX:BANKING")
            self.assertEqual(row["decision_source"], "unit_test")

    def test_overlap_guard_blocks_same_factor_group(self):
        from institutional_options.research_controls import PortfolioOverlapGuard
        guard = PortfolioOverlapGuard()
        decision = guard.assess("BANKEX", "INDEX:BANKING", {"BANKNIFTY"}, {"INDEX:BANKING"})
        self.assertFalse(decision.allowed)
        self.assertIn("exposure group", decision.reason)

    def test_lifecycle_state_persists_across_store_reload(self):
        with tempfile.TemporaryDirectory() as d:
            store = InstrumentCalibrationStore(d, CONFIG)
            store.set_lifecycle_state("SENSEX", InstrumentLifecycle.RETIRED)
            reloaded = InstrumentCalibrationStore(d, CONFIG)
            self.assertEqual(reloaded.lifecycle_state("SENSEX"), InstrumentLifecycle.RETIRED)
            self.assertEqual(reloaded.lifecycle_state("NIFTY"), InstrumentLifecycle.MONITOR)

    def test_configured_retirement_thresholds_are_used(self):
        class ConfigWithRetirement:
            raw = {
                "retirement_rules": {
                    "minimum_shadow_outcomes": 3,
                    "minimum_paper_trades": 4,
                    "negative_expectancy_retire_threshold_r": -0.10,
                    "data_quality_degradation_factor": 0.90,
                }
            }
        with tempfile.TemporaryDirectory() as d:
            store = InstrumentCalibrationStore(d, ConfigWithRetirement())
            engine = PromotionEngine(store)
            metrics = PromotionMetrics(100, 20, 0.99, 0.90, shadow_outcomes=3, shadow_net_expectancy_r=-0.11)
            decision = engine.evaluate(InstrumentClass.NSE_INDEX.value, InstrumentLifecycle.SHADOW, metrics, monitor_only=True)
            self.assertEqual(decision.recommended_state, InstrumentLifecycle.RETIRED)

    def test_paper_drawdown_is_updated_from_realized_r_sequence(self):
        with tempfile.TemporaryDirectory() as d:
            store = InstrumentCalibrationStore(d, CONFIG)
            cls = InstrumentClass.NSE_INDEX.value
            store.record_outcome(cls, 80.0, 2.0, 100.0, instrument_id="NIFTY", paper=True)
            store.record_outcome(cls, 80.0, -1.0, -50.0, instrument_id="NIFTY", paper=True)
            store.record_outcome(cls, 80.0, -0.5, -25.0, instrument_id="NIFTY", paper=True)
            metrics = store.instrument_metrics("NIFTY")
            self.assertEqual(metrics["paper_trades"], 3)
            self.assertAlmostEqual(metrics["paper_net_expectancy_r"], 1.0 / 6.0)
            self.assertAlmostEqual(metrics["max_drawdown_r"], 1.5)

    def test_unvalidated_cost_outcome_cannot_enter_canonical_calibration(self):
        with tempfile.TemporaryDirectory() as d:
            store = InstrumentCalibrationStore(d, CONFIG)
            cls = InstrumentClass.NSE_INDEX.value
            store.record_outcome(cls, 80.0, 2.0, 100.0, instrument_id="NIFTY", paper=False, cost_model_valid=False)
            self.assertEqual(store.state["outcomes"][cls]["count"], 0)
            self.assertFalse(store.state["gate_learning"]["NIFTY"]["outcomes"][0]["cost_model_valid"])
            self.assertEqual(store.instrument_metrics("NIFTY")["shadow_outcomes"], 0)

    def test_promotion_retires_materially_negative_shadow_state(self):
        with tempfile.TemporaryDirectory() as d:
            store = InstrumentCalibrationStore(d, CONFIG)
            engine = PromotionEngine(store)
            cls = InstrumentClass.NSE_INDEX.value
            metrics = PromotionMetrics(100, 20, 0.99, 0.90, shadow_outcomes=20, shadow_net_expectancy_r=-0.30)
            decision = engine.evaluate(cls, InstrumentLifecycle.SHADOW, metrics, monitor_only=True)
            self.assertEqual(decision.recommended_state, InstrumentLifecycle.RETIRED)
            self.assertTrue(decision.allowed)

    def test_shadow_tracker_rank_change_closes_using_previous_contract_quote(self):
        with tempfile.TemporaryDirectory() as d:
            now = datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc)
            spec = InstrumentSpec("SENSEX", "1", "OPTIDX", date(2026, 8, 20), 10, 0.05, 80000, OptionType.CE, instrument_class="BSE_INDEX", exchange="BSE")
            old_quote = Quote(100, 100.5, 100, 100, 100.25, now, 300, 300)
            candidate = CandidateInputs(
                instrument=spec, quote=old_quote, moneyness=Moneyness.ATM, greeks=Greeks(delta=0.5),
                data_health=DataHealth(True), futures_price=80000, underlying_price=80000,
                instrument_direction_score=70, trade_quality_score=90, regime_confidence=90,
                market_hostility_score=10, iv_crush_risk_score=10, premium_elasticity=0.6,
                expected_move=100, required_move=50, required_stop_points=5,
                convexity_edge_score=90, execution_quality_score=90,
                opportunity_confidence_score=90, regime_fit_score=90,
                lifecycle_state="SHADOW", exposure_group=exposure_group("SENSEX", "INDEX"),
            )
            evaluation = OpportunityEvaluation(candidate, type("CQ", (), {"score": 90})(), RiskPlan(100, 5, 100, True, 5), 90, 90, 80, OpportunityGrade.A, True, TradeDecision.BUY_CALL_CANDIDATE, ())
            tracker = ShadowTradeTracker(PaperFillSimulator(CONFIG), max_hold_seconds=1800)
            self.assertIsNone(tracker.observe(evaluation, now))
            new_spec = InstrumentSpec("SENSEX", "1", "OPTIDX", date(2026, 8, 20), 10, 0.05, 80100, OptionType.CE, instrument_class="BSE_INDEX", exchange="BSE")
            new_quote = Quote(50, 50.5, 100, 100, 50.25, now + timedelta(minutes=1), 300, 300)
            new_candidate = CandidateInputs(**{**candidate.__dict__, "instrument": new_spec, "quote": new_quote})
            new_evaluation = OpportunityEvaluation(new_candidate, evaluation.contract_quality, evaluation.risk_plan, 95, 95, 80, OpportunityGrade.A, True, TradeDecision.BUY_CALL_CANDIDATE, ())
            outcome = tracker.observe(new_evaluation, now + timedelta(minutes=1))
            self.assertIsNotNone(outcome)
            self.assertEqual(outcome.exit_reason, "RANK_CHANGE")
            self.assertGreater(outcome.exit_price, 90.0)

    def test_shadow_tracker_records_conservative_target_outcome(self):
        with tempfile.TemporaryDirectory() as d:
            now = datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc)
            spec = InstrumentSpec("SENSEX", "1", "OPTIDX", date(2026, 8, 20), 10, 0.05, 80000, OptionType.CE, instrument_class="BSE_INDEX", exchange="BSE")
            q1 = Quote(100, 100.5, 100, 100, 100.25, now, 300, 300)
            c = CandidateInputs(
                instrument=spec, quote=q1, moneyness=Moneyness.ATM, greeks=Greeks(delta=0.5),
                data_health=DataHealth(True), futures_price=80000, underlying_price=80000,
                instrument_direction_score=70, trade_quality_score=90, regime_confidence=90,
                market_hostility_score=10, iv_crush_risk_score=10, premium_elasticity=0.6,
                expected_move=100, required_move=50, required_stop_points=5,
                convexity_edge_score=90, execution_quality_score=90,
                opportunity_confidence_score=90, regime_fit_score=90,
                lifecycle_state="SHADOW", exposure_group=exposure_group("SENSEX", "INDEX"),
            )
            evaluation = OpportunityEvaluation(c, type("CQ", (), {"score": 90})(), RiskPlan(100, 5, 100, True, 5), 90, 90, 80, OpportunityGrade.A, True, TradeDecision.BUY_CALL_CANDIDATE, ())
            tracker = ShadowTradeTracker(PaperFillSimulator(CONFIG), max_hold_seconds=1800)
            self.assertIsNone(tracker.observe(evaluation, now))
            q2 = Quote(112, 112.5, 100, 100, 112.25, now + timedelta(minutes=1), 300, 300)
            c2 = CandidateInputs(**{**c.__dict__, "quote": q2})
            evaluation2 = OpportunityEvaluation(c2, evaluation.contract_quality, evaluation.risk_plan, 90, 90, 80, OpportunityGrade.A, True, TradeDecision.BUY_CALL_CANDIDATE, ())
            outcome = tracker.observe(evaluation2, now + timedelta(minutes=1))
            self.assertIsNotNone(outcome)
            self.assertEqual(outcome.exit_reason, "TARGET")
            self.assertTrue(outcome.fillable_entry)


if __name__ == "__main__":
    unittest.main()
