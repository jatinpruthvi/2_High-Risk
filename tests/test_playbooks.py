import unittest

from institutional_options.playbooks import RegimeContext, RegimeLabel, RegimePlaybookSelectionEngine
from institutional_options.engine import PaperOpportunityEngine
from institutional_options.config import SystemConfig
from tests.test_scoring_and_engine import candidate


class PlaybookTests(unittest.TestCase):
    def test_selects_trend_breakout_playbook(self):
        ctx=RegimeContext(RegimeLabel.TREND_EXPANSION, confidence=85, market_hostility_score=10, iv_crush_risk_score=20, trend_strength_score=85, range_expansion_quality=80)
        result=RegimePlaybookSelectionEngine().evaluate(ctx)
        self.assertFalse(result.no_trade)
        self.assertIn('A01', result.allowed_codes)

    def test_no_trade_in_range(self):
        ctx=RegimeContext(RegimeLabel.RANGE_BALANCE, confidence=90, market_hostility_score=10)
        result=RegimePlaybookSelectionEngine().evaluate(ctx)
        self.assertTrue(result.no_trade)

    def test_engine_filters_by_allowed_playbook(self):
        cfg=SystemConfig.from_file('uploads/PARAMETERS.json')
        c1=candidate('NIFTY',95); c1 = __import__('dataclasses').replace(c1, setup_type='A01')
        c2=candidate('BANKNIFTY',96); c2 = __import__('dataclasses').replace(c2, setup_type='A03')
        res=PaperOpportunityEngine(cfg).evaluate_and_select([c1,c2], allowed_playbooks={'A01'})
        self.assertEqual(res.selected.candidate.instrument.underlying,'NIFTY')


if __name__ == '__main__':
    unittest.main()
