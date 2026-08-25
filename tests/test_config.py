import copy
import json
import unittest
from pathlib import Path

from institutional_options.config import SystemConfig


class ConfigTests(unittest.TestCase):
    def test_loads_project_parameters(self):
        cfg = SystemConfig.from_file("uploads/PARAMETERS.json")
        self.assertEqual(cfg.section("instrument_universe")["max_open_positions"], 1)
        self.assertFalse(cfg.section("capital")["auto_execution_mvp"])

    def test_gate_learning_policy_is_explicit_and_conservative(self):
        cfg = SystemConfig.from_file("uploads/PARAMETERS.json")
        learning = cfg.raw["instrument_gate_learning"]
        self.assertTrue(learning["enabled"])
        self.assertTrue(learning["do_not_loosen"])
        self.assertGreaterEqual(learning["minimum_learning_days"], learning["warmup_days"])
        self.assertLessEqual(learning["winning_quantile"], 0.5)
        self.assertGreaterEqual(learning["high_watermark_quantile"], 0.5)

    def test_invalid_gate_learning_quantile_is_rejected(self):
        raw = json.loads(Path("uploads/PARAMETERS.json").read_text(encoding="utf-8"))
        raw["instrument_gate_learning"] = copy.deepcopy(raw["instrument_gate_learning"])
        raw["instrument_gate_learning"]["winning_quantile"] = 0.8
        with self.assertRaises(ValueError):
            SystemConfig(raw=raw).validate()

    def test_missing_execution_section_is_rejected_as_required(self):
        raw = json.loads(Path("uploads/PARAMETERS.json").read_text(encoding="utf-8"))
        raw.pop("execution", None)
        with self.assertRaisesRegex(ValueError, "Required config section missing: execution"):
            SystemConfig(raw=raw).validate()

    def test_invalid_operator_control_path_is_rejected(self):
        raw = json.loads(Path("uploads/PARAMETERS.json").read_text(encoding="utf-8"))
        raw["operator_controls"] = copy.deepcopy(raw["operator_controls"])
        raw["operator_controls"]["daily_mode_path"] = ""
        with self.assertRaises(ValueError):
            SystemConfig(raw=raw).validate()

    def test_invalid_stale_alert_threshold_is_rejected(self):
        raw = json.loads(Path("uploads/PARAMETERS.json").read_text(encoding="utf-8"))
        raw["data_health"] = copy.deepcopy(raw["data_health"])
        raw["data_health"]["stale_alert_consecutive_cycles"] = 0
        with self.assertRaises(ValueError):
            SystemConfig(raw=raw).validate()

    def test_invalid_walk_forward_grid_is_rejected(self):
        raw = json.loads(Path("uploads/PARAMETERS.json").read_text(encoding="utf-8"))
        raw["instrument_gate_learning"] = copy.deepcopy(raw["instrument_gate_learning"])
        raw["instrument_gate_learning"]["candidate_quantiles"] = [0.4]
        with self.assertRaises(ValueError):
            SystemConfig(raw=raw).validate()

    def test_expanded_runner_preserves_trade_boundary(self):
        runner_cfg = json.loads(Path("uploads/PAPER_RUNNER.json").read_text(encoding="utf-8"))
        underlyings = runner_cfg["underlyings"]
        properties = list(underlyings.values())
        trade_enabled = [meta for meta in properties if meta.get("trade_enabled") is True]
        monitor_only = [meta for meta in properties if meta.get("monitor_only") is True]
        self.assertEqual(len(properties), 59)
        self.assertEqual(len(trade_enabled), 59)
        self.assertEqual(len(monitor_only), 0)
        self.assertEqual(
            {name for name, meta in underlyings.items() if meta.get("trade_enabled") is True},
            set(underlyings),
        )
        self.assertTrue(all(meta.get("monitor_only") is False for meta in properties))
        self.assertEqual(runner_cfg["monitoring"]["monitor_batch_size"], 8)
        self.assertEqual(runner_cfg["monitoring"]["monitor_poll_seconds"], 60)
        breakout = runner_cfg["gate_breakout"]
        self.assertTrue(breakout["enabled"])
        self.assertEqual(breakout["lookback_seconds"], 1800)
        self.assertEqual(breakout["minimum_improvement_points"], 0.25)
        self.assertEqual(breakout["metric"], "threshold_margin")
        self.assertTrue(breakout["require_current_eligible"])
        self.assertTrue(breakout["require_data_health_valid"])
        self.assertTrue(breakout["require_contract_valid"])
        self.assertTrue(breakout["require_cost_model_valid"])
        experiment = runner_cfg["experimental_impulse_breakout"]
        self.assertTrue(experiment["enabled"])
        self.assertTrue(experiment["research_only"])
        self.assertFalse(experiment["paper_entry_enabled"])
        self.assertEqual(runner_cfg["history_bars"], 40)
        self.assertEqual(experiment["range_lookback_minutes"], 30)
        self.assertEqual(experiment["minimum_history_bars"], 20)
        self.assertEqual(experiment["one_shot_cooldown_seconds"], 1800)
        self.assertTrue(experiment["require_cost_model_valid"])
        self.assertTrue(experiment["require_data_health_valid"])
        self.assertTrue(experiment["require_contract_valid"])
        self.assertTrue(experiment["require_canonical_eligibility_for_paper_entry"])


if __name__ == "__main__":
    unittest.main()
