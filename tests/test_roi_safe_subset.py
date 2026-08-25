from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from institutional_options.config import SystemConfig
from institutional_options.expected_value import ExpectedValueEngine
from institutional_options.models import CalibrationStatus, OptionType, Quote
from institutional_options.observed_metrics import RollingPremiumElasticity
from institutional_options.paper_evidence import PaperEvidenceCollector
from institutional_options.paper_runner import PaperRunner
from institutional_options.scoring import OpportunityScorer


ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "uploads" / "PARAMETERS.json"


def quote(bid: float, ask: float, ts: datetime) -> Quote:
    return Quote(bid, ask, 1000, 1000, ask, ts, 5000, 5000, True)


class RoiSafeSubsetTests(unittest.TestCase):
    def test_observed_elasticity_requires_two_confirmed_windows(self):
        tracker = RollingPremiumElasticity(
            window_seconds=60,
            min_underlying_move_points=30,
            confirmation_windows=2,
            min_confirmed_elasticity=1.0,
        )
        t0 = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
        first = tracker.update("NIFTY|25000|CE", t0, 25000.0, quote(100, 101, t0), OptionType.CE, delta=0.5)
        self.assertFalse(first.valid)
        second_ts = t0.replace(second=30)
        second = tracker.update("NIFTY|25000|CE", second_ts, 25040.0, quote(125, 126, second_ts), OptionType.CE, delta=0.5)
        self.assertTrue(second.valid)
        self.assertFalse(second.confirmed)
        self.assertAlmostEqual(second.post_cost_delta_adjusted_elasticity, 1.2, places=6)
        third_ts = t0.replace(second=59)
        third = tracker.update("NIFTY|25000|CE", third_ts, 25080.0, quote(150, 151, third_ts), OptionType.CE, delta=0.5)
        self.assertTrue(third.confirmed)
        self.assertEqual(third.confirmation_count, 2)

    def test_missing_delta_is_unavailable_not_a_proxy(self):
        tracker = RollingPremiumElasticity(window_seconds=60, min_underlying_move_points=30)
        t0 = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
        tracker.update("x", t0, 1000, quote(10, 11, t0), OptionType.CE)
        result = tracker.update("x", t0.replace(second=30), 1040, quote(14, 15, t0.replace(second=30)), OptionType.CE)
        self.assertFalse(result.valid)
        self.assertIn("Delta unavailable", result.reason)

    def test_shadow_ev_requires_validated_cost_model(self):
        blocked = ExpectedValueEngine.compute(0.55, 2.0, 1.0, 0.1, cost_model_valid=False)
        self.assertIsNone(blocked.expected_value_r)
        self.assertEqual(blocked.status, "UNVALIDATED_COST_MODEL")
        measured = ExpectedValueEngine.compute(0.70, 2.0, 1.0, 0.1, cost_model_valid=True)
        self.assertEqual(measured.status, "MEASURED_COST_AWARE")
        self.assertAlmostEqual(measured.win_probability, 0.62)
        self.assertAlmostEqual(measured.expected_value_r, 0.76, places=6)

    def test_dynamic_threshold_only_tightens_from_real_metadata(self):
        cfg = SystemConfig.from_file(CFG)
        scorer = OpportunityScorer(cfg)
        candidate = SimpleNamespace(
            instrument=SimpleNamespace(underlying="NIFTY"),
            calibration_status_liquidity=CalibrationStatus.VALIDATED,
            iv_crush_risk_score=10.0,
            notes={"gap_pct": 0.60, "expiry_day": True, "same_direction_recent_loss": True},
        )
        self.assertEqual(scorer._dynamic_threshold(candidate), 100.0)
        no_metadata = SimpleNamespace(
            instrument=SimpleNamespace(underlying="NIFTY"),
            calibration_status_liquidity=CalibrationStatus.VALIDATED,
            iv_crush_risk_score=10.0,
            notes={},
        )
        self.assertEqual(scorer._dynamic_threshold(no_metadata), 80.0)

    def test_same_direction_loss_cooldown_is_side_aware(self):
        cfg = SystemConfig.from_file(CFG)
        runner = object.__new__(PaperRunner)
        runner.config = cfg
        runner.state = SimpleNamespace(recent_direction_losses={
            "NIFTY|CE": "2026-08-12T09:50:00+05:30",
        })
        ist = timezone(timedelta(hours=5, minutes=30))
        now = datetime(2026, 8, 12, 10, 10, tzinfo=ist)
        self.assertTrue(runner._same_direction_loss_active("NIFTY", "CE", now))
        self.assertFalse(runner._same_direction_loss_active("NIFTY", "PE", now))
        later = datetime(2026, 8, 12, 10, 25, tzinfo=ist)
        self.assertFalse(runner._same_direction_loss_active("NIFTY", "CE", later))

    def test_no_trade_alpha_snapshot_is_research_only_and_grouped(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = PaperEvidenceCollector(tmp)
            collector.skipped_forward_outcomes.append({
                "skip_id": "a", "status": "OBSERVED", "forward_r_multiple": -1.0,
                "would_have_hit_target": False, "would_have_hit_stop": True,
                "veto_reason": "PremiumElasticity hard reject",
            })
            collector.skipped_forward_outcomes.append({
                "skip_id": "b", "status": "OBSERVED", "forward_r_multiple": 2.0,
                "would_have_hit_target": True, "would_have_hit_stop": False,
                "veto_reason": "PremiumElasticity hard reject",
            })
            collector.skipped_forward_outcomes.append({
                "skip_id": "c", "status": "UNAVAILABLE", "forward_r_multiple": "UNAVAILABLE",
                "would_have_hit_target": "UNAVAILABLE", "would_have_hit_stop": "UNAVAILABLE",
                "veto_reason": "DataHealth invalid",
            })
            snapshot = collector.no_trade_alpha_snapshot()
            self.assertEqual(snapshot["status"], "READY")
            self.assertEqual(snapshot["observed_rows"], 2)
            self.assertEqual(snapshot["unavailable_rows"], 1)
            self.assertEqual(snapshot["stop_hits"], 1)
            self.assertEqual(snapshot["target_hits"], 1)
            self.assertTrue(snapshot["research_only"])
            self.assertFalse(snapshot["cost_model_valid"])
            self.assertEqual(snapshot["by_veto_reason"]["PremiumElasticity hard reject"]["observed"], 2)

    def test_policy_boundaries_remain_locked(self):
        runner_cfg = json.loads((ROOT / "uploads" / "PAPER_RUNNER.json").read_text(encoding="utf-8"))
        exp = runner_cfg.get("experimental_impulse_breakout", {})
        self.assertTrue(exp.get("research_only"))
        self.assertFalse(exp.get("paper_entry_enabled"))
        params = json.loads(CFG.read_text(encoding="utf-8"))
        self.assertFalse(params["capital"]["pledge_or_leverage_allowed"])
        self.assertFalse(params["capital"]["overnight_holding_allowed"])
        self.assertFalse(params["capital"]["auto_execution_mvp"])
        self.assertEqual(params["instrument_universe"]["max_open_positions"], 1)
        self.assertTrue(params["premium_elasticity"]["require_observed_confirmation_for_selection"])
        self.assertTrue(params["expected_value"]["shadow_only_until_cost_model_valid"])


if __name__ == "__main__":
    unittest.main()
