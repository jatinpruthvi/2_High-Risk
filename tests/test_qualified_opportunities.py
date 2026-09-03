import csv
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from institutional_options.paper_runner import PaperRunner
from institutional_options.opportunity_learning import OpportunityLearningLedger


class QuoteStub:
    bid = 10.0
    ask = 10.2
    mid = 10.1

    @staticmethod
    def age_seconds(_ts):
        return 1.0


class QualifiedOpportunityTests(unittest.TestCase):
    def _runner(self, root):
        runner = object.__new__(PaperRunner)
        runner.state = SimpleNamespace(open_position=None, underlyings={})
        runner._qualified_opportunity_path = Path(root) / "qualified_opportunities.csv"
        runner._missed_opportunity_path = Path(root) / "best_missed_opportunities.csv"
        runner.opportunity_learning = OpportunityLearningLedger(root)
        runner._write_qualified_opportunity_header()
        return runner

    def _evaluation(self):
        candidate = SimpleNamespace(
            instrument=SimpleNamespace(underlying="NIFTY", expiry=date(2026, 8, 27), strike=25000.0),
            side=SimpleNamespace(value="CE"), quote=QuoteStub(),
        )
        return SimpleNamespace(eligible=True, candidate=candidate, comparable_opportunity_score=91.5, dynamic_excellent_threshold=80.0)

    def test_qualified_candidate_is_persisted_and_capacity_reason_is_visible(self):
        with tempfile.TemporaryDirectory() as td:
            runner = self._runner(td)
            now = datetime(2026, 8, 27, 10, 0, tzinfo=timezone.utc)
            evaluation = self._evaluation()
            runner._record_qualified_opportunities([evaluation], now, lane="PAPER_CALIBRATION", selected=evaluation)
            runner.state.open_position = object()
            runner._record_qualified_opportunities([evaluation], now, lane="PAPER_CALIBRATION", selected=evaluation)
            with runner._qualified_opportunity_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["status"], "SELECTED_FOR_REVALIDATION")
            self.assertEqual(rows[1]["status"], "BLOCKED_OPEN_POSITION")
            self.assertEqual(len(runner.state.underlyings["_qualified_opportunities"]), 2)
            self.assertEqual(rows[0]["paper_only"], "True")


if __name__ == "__main__":
    unittest.main()
