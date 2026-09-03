import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from institutional_options.opportunity_learning import OpportunityLearningLedger
from institutional_options.paper_runner import PaperRunner


class QuoteStub:
    bid = 10.0
    ask = 10.5
    bid_qty = 75.0
    ask_qty = 80.0
    source_timestamp_available = True

    def is_valid(self):
        return True


class TwoSpeedFrameworkTests(unittest.TestCase):
    def test_data_quorum_reports_ready_only_when_all_hard_inputs_pass(self):
        runner = object.__new__(PaperRunner)
        runner._cost_model_valid = True
        candidate = SimpleNamespace(
            data_health=SimpleNamespace(valid=True),
            quote=QuoteStub(),
            instrument=SimpleNamespace(security_id="SEC", lot_size=25, tick_size=0.05),
        )
        evaluation = SimpleNamespace(candidate=candidate)
        now = datetime(2026, 8, 27, 10, 0, tzinfo=timezone.utc)
        snapshot = runner._data_quorum_snapshot([evaluation], now)
        self.assertEqual(snapshot["status"], "READY")
        self.assertEqual(snapshot["stages"]["total"], 1)
        self.assertTrue(snapshot["paper_only"])

    def test_data_quorum_exposes_missing_source_timestamp(self):
        runner = object.__new__(PaperRunner)
        runner._cost_model_valid = True
        quote = QuoteStub()
        quote.source_timestamp_available = False
        candidate = SimpleNamespace(
            data_health=SimpleNamespace(valid=True),
            quote=quote,
            instrument=SimpleNamespace(security_id="SEC", lot_size=25, tick_size=0.05),
        )
        snapshot = runner._data_quorum_snapshot([SimpleNamespace(candidate=candidate)], datetime.now(timezone.utc))
        self.assertEqual(snapshot["status"], "DEGRADED")
        self.assertEqual(snapshot["failures"]["source_timestamp"], 1)

    def test_session_classifier_identifies_cas_window(self):
        ts = datetime(2026, 8, 27, 15, 20, tzinfo=timezone.utc)
        self.assertEqual(OpportunityLearningLedger.session_phase(ts), "CAS_WINDOW")


if __name__ == "__main__":
    unittest.main()
