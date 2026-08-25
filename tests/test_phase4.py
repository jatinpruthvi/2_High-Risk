import unittest

from institutional_options.forecast_research import ForecastRecord, ForecastResearchEvaluator
from institutional_options.microstructure_research import MicrostructureSignalEvaluator, SignalOutcomeRecord
from institutional_options.research_governance import (
    BrokerAbstractionResearchGate, BrokerTCAMetrics, ResearchMetrics, ResearchPromotionGate,
    ResearchRegistry, ResearchStatus, ThresholdChangeProposal, ThresholdOptimizationGuard,
)


class Phase4ResearchTests(unittest.TestCase):
    def test_registry_contains_verified_models(self):
        reg = ResearchRegistry.default()
        self.assertTrue(reg.get('Moirai/Moirai-2').verified)
        self.assertEqual(reg.get('Kronos').allowed_stage, ResearchStatus.RESEARCH_ONLY)

    def test_promotion_gate_keeps_small_sample_research_only(self):
        reg = ResearchRegistry.default()
        review = ResearchPromotionGate().review(reg.get('TimeGPT'), ResearchMetrics(20, 0.2, 0, 0.1, 0.01, 0.1))
        self.assertEqual(review.decision.value, 'KEEP_RESEARCH_ONLY')

    def test_threshold_guard_rejects_loosening(self):
        proposal = ThresholdChangeProposal('premium_elasticity', 1.0, 0.8, 1000, 0.1, 0.0, True, 'loosen')
        review = ThresholdOptimizationGuard().review(proposal)
        self.assertFalse(review.approved)

    def test_broker_tca_requires_better_net_cost(self):
        inc = BrokerTCAMetrics('DHAN', 100, 1.0, 0.0, 100, 50, True)
        ch = BrokerTCAMetrics('X', 100, 0.8, 0.0, 90, 40, True)
        self.assertTrue(BrokerAbstractionResearchGate().review(ch, inc).eligible_for_shadow_next_stage)

    def test_forecast_evaluator(self):
        recs=[ForecastRecord('M', 't', 'x', 10, 8, 12, 11, 14), ForecastRecord('M', 't2', 'x', 20, 18, 22, 19, 25)]
        ev=ForecastResearchEvaluator.evaluate(recs)
        self.assertEqual(ev.sample_size, 2)
        self.assertGreater(ev.mae_improvement, 0)

    def test_microstructure_signal_evaluator(self):
        recs=[SignalOutcomeRecord('GEX', 80, 0.1, -0.05, 0.2) for _ in range(60)]
        s=MicrostructureSignalEvaluator.evaluate(recs)
        self.assertTrue(s.useful)


if __name__ == '__main__':
    unittest.main()
