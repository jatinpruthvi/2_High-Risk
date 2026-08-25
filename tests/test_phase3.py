import tempfile
import unittest
from pathlib import Path

from institutional_options.analytics import PerformanceSummary
from institutional_options.config import SystemConfig
from institutional_options.phase2 import DryRunAcceptanceResult, EvidenceReview
from institutional_options.phase3 import ChargesVerifier, LiveReadinessReviewer, Phase3Artifacts, Phase3ReportWriter, ReadinessCheck


class Phase3Tests(unittest.TestCase):
    def setUp(self):
        self.cfg = SystemConfig.from_file('uploads/PARAMETERS.json')

    def _acceptance(self, passed=True):
        return DryRunAcceptanceResult(passed, (ReadinessCheck('dummy', passed, 'CRITICAL', 'dummy'),))

    def _evidence(self, expectancy=10.0):
        overall = PerformanceSummary(10, 6, 4, 0.6, 100, -50, expectancy, 2.0, expectancy*10, 100)
        return EvidenceReview(overall, tuple(), tuple(), tuple(), tuple(), tuple(), tuple(), None, None)

    def test_placeholder_charges_fail(self):
        check = ChargesVerifier.verify('uploads/CHARGES_CONFIG.json')
        self.assertFalse(check.passed)

    def test_readiness_not_live_approved_with_demo_trade_true(self):
        charges = ReadinessCheck('cost_model_verified', True, 'CRITICAL', 'ok')
        decision = LiveReadinessReviewer(self.cfg).review(self._acceptance(True), self._evidence(), charges, True, True, committee_approved_live_orders=True)
        self.assertTrue(decision.approved_for_manual_live_review)
        self.assertFalse(decision.approved_for_live_orders)

    def test_artifacts_exist(self):
        self.assertGreater(len(Phase3Artifacts.manual_live_checklist().items), 5)
        self.assertEqual(Phase3Artifacts.live_micro_test_rules().max_open_positions, 1)
        self.assertIn('Any order rejection', Phase3Artifacts.live_stop_criteria().criteria)

    def test_report_writer(self):
        charges = ReadinessCheck('cost_model_verified', True, 'CRITICAL', 'ok')
        decision = LiveReadinessReviewer(self.cfg).review(self._acceptance(True), self._evidence(), charges, True, True)
        with tempfile.TemporaryDirectory() as d:
            out = Phase3ReportWriter.write(Path(d)/'phase3.txt', decision)
            self.assertTrue(out.exists())


if __name__ == '__main__':
    unittest.main()
