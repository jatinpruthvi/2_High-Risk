import unittest
from datetime import datetime, date, UTC
from pathlib import Path
import tempfile
from dataclasses import replace

from institutional_options.config import SystemConfig
from institutional_options.costs import validate_charges_config
from institutional_options.dashboard import DryRunDashboard
from institutional_options.direction_models import DirectionModelCalculator, LeadershipInput, MidcapDirectionInput
from institutional_options.models import CalibrationStatus, DataHealth, Greeks, InstrumentSpec, Moneyness, OptionType, Quote
from institutional_options.option_chain import DhanOptionChainParser, OptionChainSemanticValidator
from institutional_options.orchestrators import DataHealthOrchestrator
from institutional_options.engine import PaperOpportunityEngine
from tests.test_scoring_and_engine import candidate


class RemainingDebtTests(unittest.TestCase):
    def test_direction_models(self):
        calc = DirectionModelCalculator()
        inputs=[LeadershipInput('A',0.6,101,100,1,0.2,0.0,1.6), LeadershipInput('B',0.4,99,100,-1,-0.2,0.0,1.6)]
        score=calc.nifty_leadership_proxy(inputs)
        self.assertGreater(score, 0)
        mid=calc.midcap_direction_proxy(MidcapDirectionInput(80,80,80,80))
        self.assertEqual(mid,80)

    def test_option_chain_semantic_validation(self):
        payload={"data":{"last_price":25000,"oc":{"25000.000000":{"ce":{"top_bid_price":100,"top_ask_price":100.5,"top_bid_quantity":1000,"top_ask_quantity":1000,"last_price":100.25,"security_id":1,"oi":1000,"previous_oi":900,"volume":10000,"greeks":{"delta":0.5},"implied_volatility":12}}}}}
        snap=DhanOptionChainParser.parse(payload,'NIFTY','2026-06-30', datetime.now(UTC))
        report=OptionChainSemanticValidator.validate(snap)
        self.assertTrue(report.valid)
        self.assertTrue(any('Missing PE' in w for w in report.warnings))

    def test_datahealth_candidate_quote(self):
        cfg=SystemConfig.from_file('uploads/PARAMETERS.json')
        orch=DataHealthOrchestrator(cfg)
        c=replace(candidate(), quote=replace(candidate().quote, source_timestamp_available=True))
        health=orch.evaluate_candidate(c, c.quote.timestamp)
        self.assertTrue(health.valid)

    def test_dashboard_render_selection(self):
        cfg=SystemConfig.from_file('uploads/PARAMETERS.json')
        result=PaperOpportunityEngine(cfg).evaluate_and_select([candidate('NIFTY',95)])
        with tempfile.TemporaryDirectory() as d:
            p=DryRunDashboard.write_selection(Path(d)/'dash.html', result)
            text=p.read_text()
            self.assertIn('Dry Run Opportunity Ranking', text)
            self.assertIn('NIFTY', text)

    def test_charges_placeholder_validation(self):
        res=validate_charges_config('uploads/CHARGES_CONFIG.json')
        self.assertFalse(res.valid)


if __name__ == '__main__':
    unittest.main()
