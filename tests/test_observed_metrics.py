import unittest
from datetime import datetime, timedelta

from institutional_options.models import OptionType, Quote
from institutional_options.observed_metrics import RollingPremiumElasticity


class ObservedElasticityTests(unittest.TestCase):
    def quote(self, bid, ask, ts):
        return Quote(bid, ask, 1000, 1000, (bid + ask) / 2.0, ts, 5000, 5000)

    def test_first_observation_is_not_valid(self):
        calc = RollingPremiumElasticity(window_seconds=60, min_underlying_move_points=30)
        ts = datetime(2026, 8, 13, 10, 0)
        obs = calc.update("NIFTY-CE", ts, 25000, self.quote(100, 101, ts), OptionType.CE)
        self.assertFalse(obs.valid)
        self.assertIn("No prior", obs.reason)

    def test_call_elasticity_is_side_aligned_and_post_cost_is_lower(self):
        calc = RollingPremiumElasticity(window_seconds=60, min_underlying_move_points=30)
        t0 = datetime(2026, 8, 13, 10, 0)
        t1 = t0 + timedelta(seconds=5)
        calc.update("NIFTY-CE", t0, 25000, self.quote(100, 101, t0), OptionType.CE, delta=0.5)
        obs = calc.update("NIFTY-CE", t1, 25050, self.quote(105, 106, t1), OptionType.CE, delta=0.5)
        self.assertTrue(obs.valid)
        self.assertAlmostEqual(obs.raw_elasticity, 5.0 / 50.0)
        self.assertAlmostEqual(obs.post_cost_elasticity, 4.0 / 50.0)

    def test_put_elasticity_is_positive_when_underlying_falls(self):
        calc = RollingPremiumElasticity(window_seconds=60, min_underlying_move_points=30)
        t0 = datetime(2026, 8, 13, 10, 0)
        t1 = t0 + timedelta(seconds=5)
        calc.update("NIFTY-PE", t0, 25000, self.quote(100, 101, t0), OptionType.PE, delta=-0.5)
        obs = calc.update("NIFTY-PE", t1, 24950, self.quote(105, 106, t1), OptionType.PE, delta=-0.5)
        self.assertTrue(obs.valid)
        self.assertGreater(obs.raw_elasticity, 0)
        self.assertGreater(obs.post_cost_elasticity, 0)

    def test_adverse_move_is_not_treated_as_favorable(self):
        calc = RollingPremiumElasticity(window_seconds=60, min_underlying_move_points=30)
        t0 = datetime(2026, 8, 13, 10, 0)
        t1 = t0 + timedelta(seconds=5)
        calc.update("NIFTY-CE", t0, 25000, self.quote(100, 101, t0), OptionType.CE)
        obs = calc.update("NIFTY-CE", t1, 24950, self.quote(95, 96, t1), OptionType.CE)
        self.assertFalse(obs.valid)
        self.assertIn("adverse", obs.reason)

    def test_stale_interval_is_not_used(self):
        calc = RollingPremiumElasticity(window_seconds=60, min_underlying_move_points=30)
        t0 = datetime(2026, 8, 13, 10, 0)
        t1 = t0 + timedelta(seconds=61)
        calc.update("NIFTY-CE", t0, 25000, self.quote(100, 101, t0), OptionType.CE)
        obs = calc.update("NIFTY-CE", t1, 25050, self.quote(105, 106, t1), OptionType.CE)
        self.assertFalse(obs.valid)
        self.assertIn("exceeds", obs.reason)


if __name__ == "__main__":
    unittest.main()
