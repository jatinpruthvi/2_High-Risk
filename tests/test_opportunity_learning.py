import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from institutional_options.opportunity_learning import OpportunityLearningLedger


class QuoteStub:
    bid = 12.0
    ask = 12.5
    mid = 12.25

    @staticmethod
    def age_seconds(_ts):
        return 1.0


class ChainStub:
    def leg_at(self, _strike, _option):
        return SimpleNamespace(quote=QuoteStub())


class OpportunityLearningTests(unittest.TestCase):
    def test_candidate_becomes_armed_on_second_fresh_observation(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = OpportunityLearningLedger(td)
            row = {"underlying": "NIFTY", "side": "CE", "expiry": "2026-08-27", "strike": 25000, "lane": "PAPER_CALIBRATION", "bid": 10, "ask": 10.5}
            t0 = datetime(2026, 8, 27, 10, 0, tzinfo=timezone.utc)
            first = ledger.process_qualified([row], t0)
            second = ledger.process_qualified([row], t0 + timedelta(seconds=5))
            self.assertEqual(first[0]["state"], "QUALIFIED")
            self.assertEqual(second[0]["state"], "ARMED")
            self.assertGreater(second[0]["break_even_move_points"], 0)
            self.assertTrue(second[0]["paper_only"])

    def test_forward_outcome_uses_bid_for_executable_and_mid_for_theoretical(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = OpportunityLearningLedger(td)
            t0 = datetime(2026, 8, 27, 10, 0, tzinfo=timezone.utc)
            row = {"underlying": "NIFTY", "side": "CE", "expiry": "2026-08-27", "strike": 25000, "lane": "CANONICAL", "bid": 10, "ask": 10.5}
            ledger.process_qualified([row], t0)
            ledger.update_forward_outcomes({"NIFTY": ChainStub()}, t0 + timedelta(seconds=60))
            record = next(iter(ledger.state["active"].values()))
            outcome = record["outcomes"]["1m"]
            self.assertEqual(outcome["executable_pnl_per_unit"], 1.5)
            self.assertEqual(outcome["theoretical_pnl_per_unit"], 1.75)
            self.assertTrue(outcome["paper_only"])

    def test_coverage_tracks_observed_and_missing_underlyings(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = OpportunityLearningLedger(td)
            now = datetime(2026, 8, 27, 10, 0, tzinfo=timezone.utc)
            ledger.update_coverage(["NIFTY", "BANKNIFTY"], {"NIFTY": object()}, now)
            snapshot = ledger.snapshot()
            self.assertEqual(snapshot["coverage"]["NIFTY"]["observed_cycles"], 1)
            self.assertEqual(snapshot["coverage"]["BANKNIFTY"]["observed_cycles"], 0)


if __name__ == "__main__":
    unittest.main()
