import unittest

from institutional_options.config import SystemConfig
from institutional_options.risk import DynamicRiskCalculator, RiskContext


class RiskTests(unittest.TestCase):
    def setUp(self):
        self.cfg = SystemConfig.from_file("uploads/PARAMETERS.json")
        self.calc = DynamicRiskCalculator(self.cfg)

    def test_dynamic_risk_low_premium_below_cap(self):
        plan = self.calc.plan(RiskContext(
            capital=100000, mode="NORMAL", setup_grade="A", lots=1,
            entry_premium=80, lot_size=30, spread_points=1, tick_size=0.05,
            required_stop_points=10, instrument="BANKNIFTY"
        ))
        self.assertTrue(plan.hard_stop_fit)
        self.assertEqual(plan.hard_stop_points, 16)
        self.assertEqual(plan.planned_risk, 480)

    def test_daily_loss_budget_caps_non_aplus_and_defensive_risk(self):
        normal = RiskContext(
            capital=100000, mode="NORMAL", setup_grade="A", lots=1,
            entry_premium=80, lot_size=30, spread_points=1, tick_size=0.05,
            required_stop_points=10, instrument="BANKNIFTY", realized_loss_today=600,
        )
        defensive = RiskContext(**{**normal.__dict__, "mode": "DEFENSIVE"})
        self.assertAlmostEqual(self.calc.max_allowed_risk(normal), 720.0)
        self.assertAlmostEqual(self.calc.max_allowed_risk(defensive), 500.0)

    def test_exhausted_daily_loss_budget_rejects_new_risk_for_all_grades(self):
        for grade in ("A", "A+"):
            plan = self.calc.plan(RiskContext(
                capital=100000, mode="NORMAL", setup_grade=grade, lots=1,
                entry_premium=80, lot_size=30, spread_points=1, tick_size=0.05,
                required_stop_points=10, instrument="BANKNIFTY", realized_loss_today=1500,
            ))
            self.assertFalse(plan.hard_stop_fit)
            self.assertIn("Mode does not allow risk", plan.reason)

    def test_required_stop_above_cap_rejects(self):
        plan = self.calc.plan(RiskContext(
            capital=100000, mode="NORMAL", setup_grade="A", lots=1,
            entry_premium=400, lot_size=30, spread_points=1, tick_size=0.05,
            required_stop_points=40, instrument="BANKNIFTY"
        ))
        self.assertFalse(plan.hard_stop_fit)


if __name__ == "__main__":
    unittest.main()
