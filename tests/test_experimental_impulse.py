from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

from institutional_options.experimental_impulse import ImpulseBreakoutSelector
from institutional_options.models import CalibrationStatus, DataHealth, OptionType


class ExperimentalImpulseTests(unittest.TestCase):
    NOW = datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc)

    @staticmethod
    def history(last_close=104.0):
        rows = []
        for index in range(30):
            ts = ExperimentalImpulseTests.NOW - timedelta(minutes=30 - index)
            rows.append([int(ts.timestamp()), 100.0, 101.0, 99.0, 100.0, 100.0])
        rows.append([int((ExperimentalImpulseTests.NOW - timedelta(seconds=30)).timestamp()), 100.0, last_close, 99.0, last_close, 200.0])
        return rows

    @staticmethod
    def evaluation(eligible=True, data_valid=True, contract_valid=True, side=OptionType.CE):
        instrument = SimpleNamespace(underlying="NIFTY", strike=25000.0, expiry="2026-08-25")
        candidate = SimpleNamespace(
            instrument=instrument,
            side=side,
            data_health=DataHealth(data_valid, False, "" if data_valid else "invalid data"),
            lifecycle_state="PAPER_ELIGIBLE",
            execution_quality_score=90.0,
            convexity_edge_score=90.0,
            opportunity_confidence_score=90.0,
            market_hostility_score=10.0,
            iv_crush_risk_score=10.0,
        )
        return SimpleNamespace(
            candidate=candidate,
            contract_quality=SimpleNamespace(valid=contract_valid, score=90.0),
            eligible=eligible,
            comparable_opportunity_score=90.0,
        )

    @staticmethod
    def context(direction=60.0, efficiency=70.0):
        return SimpleNamespace(atr1=1.0, direction_score=direction, trend_efficiency=efficiency)

    def test_breakout_is_research_only_and_same_episode_is_suppressed(self):
        selector = ImpulseBreakoutSelector({
            "enabled": True,
            "research_only": True,
            "paper_entry_enabled": False,
            "min_breakout_displacement_atr": 0.75,
            "min_direction_score": 25,
            "min_trend_efficiency": 50,
        })
        first = selector.evaluate("NIFTY", self.history(), self.context(), (self.evaluation(),), self.NOW, cost_model_valid=True)
        self.assertEqual(first.status, "BREAKOUT_RESEARCH_ONLY")
        self.assertTrue(first.raw_signal)
        second = selector.evaluate(
            "NIFTY", self.history(), self.context(), (self.evaluation(),), self.NOW + timedelta(minutes=1),
            cost_model_valid=True, last_trigger_key=first.trigger_key,
            cooldown_until=self.NOW + timedelta(minutes=20),
        )
        self.assertEqual(second.status, "BREAKOUT_SUPPRESSED_ONE_SHOT")

    def test_cost_model_is_hard_block(self):
        selector = ImpulseBreakoutSelector({
            "enabled": True,
            "research_only": False,
            "paper_entry_enabled": True,
            "min_breakout_displacement_atr": 0.75,
        })
        result = selector.evaluate("NIFTY", self.history(), self.context(), (self.evaluation(),), self.NOW, cost_model_valid=False)
        self.assertEqual(result.status, "BREAKOUT_BLOCKED_COST_MODEL")

    def test_invalid_data_is_hard_block(self):
        selector = ImpulseBreakoutSelector({"enabled": True, "research_only": False, "paper_entry_enabled": True})
        result = selector.evaluate(
            "NIFTY", self.history(), self.context(), (self.evaluation(data_valid=False),), self.NOW,
            cost_model_valid=True,
        )
        self.assertEqual(result.status, "BREAKOUT_BLOCKED_DATA_HEALTH")

    def test_late_entry_is_blocked(self):
        selector = ImpulseBreakoutSelector({"enabled": True, "max_late_entry_atr": 1.5})
        result = selector.evaluate("NIFTY", self.history(last_close=110.0), self.context(), (self.evaluation(),), self.NOW, cost_model_valid=True)
        self.assertEqual(result.status, "BREAKOUT_BLOCKED_LATE_ENTRY")

    def test_no_breakout_is_not_a_signal(self):
        selector = ImpulseBreakoutSelector({"enabled": True})
        result = selector.evaluate("NIFTY", self.history(last_close=100.0), self.context(), (self.evaluation(),), self.NOW, cost_model_valid=True)
        self.assertEqual(result.status, "NO_BREAKOUT")
        self.assertFalse(result.raw_signal)


if __name__ == "__main__":
    unittest.main()
