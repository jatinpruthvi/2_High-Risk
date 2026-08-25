import csv
import tempfile
import unittest
from pathlib import Path

from institutional_options.config import SystemConfig
from institutional_options.mtil import MTILSchema, MTILWriter
from institutional_options.records import MTILRecordBuilder
from institutional_options.phase2 import CsvDataset, DryRunValidator
from institutional_options.models import PaperTrade
from tests.test_costs_dhan_lifecycle import make_eval_and_fill
from institutional_options.candidates import CandidateFactory, CandidateFactoryContext
from institutional_options.option_chain import DhanOptionChainParser
from institutional_options.models import CalibrationStatus


class DevelopmentDebtFixTests(unittest.TestCase):
    def test_mtil_builder_schema_and_phase2_alignment(self):
        cfg, ev, fill, now = make_eval_and_fill()
        schema = MTILSchema.from_csv('uploads/MTIL_SCHEMA.csv')
        rec = MTILRecordBuilder.from_paper_trade(PaperTrade('T1', ev, fill, now), 100, 1, schema=schema)
        schema.validate_record(rec)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'mtil.csv'
            writer=MTILWriter(schema,path)
            # create enough rows for minimal validator parts not all acceptance
            writer.append(rec)
            ds=CsvDataset.from_csv(path)
            # candidate revalidation and paper fill should be seen using canonical MTIL fields
            result=DryRunValidator(SystemConfig.from_file('uploads/PARAMETERS.json')).validate(ds, emergency_tests_passed=False)
            names={c.name:c for c in result.checks}
            self.assertIn('candidate_revalidation', names)
            self.assertTrue(names['candidate_revalidation'].passed)
            self.assertIn('paper_fill_simulator_active', names)
            self.assertTrue(names['paper_fill_simulator_active'].passed)

    def test_candidate_factory_defaults_do_not_create_tradeable_candidate(self):
        payload={"data":{"last_price":25000,"oc":{"25000.000000":{"ce":{"top_bid_price":100,"top_ask_price":100.5,"top_bid_quantity":1000,"top_ask_quantity":1000,"last_price":100.25,"security_id":1,"oi":1000,"previous_oi":900,"volume":10000,"greeks":{"delta":0.5,"gamma":0.01,"theta":-5,"vega":2},"implied_volatility":12},"pe":{"top_bid_price":100,"top_ask_price":100.5,"top_bid_quantity":1000,"top_ask_quantity":1000,"last_price":100.25,"security_id":2,"oi":1000,"previous_oi":900,"volume":10000,"greeks":{"delta":-0.5,"gamma":0.01,"theta":-5,"vega":2},"implied_volatility":12}}}}}
        chain=DhanOptionChainParser.parse(payload,'NIFTY','2026-06-30')
        ctx=CandidateFactoryContext(25000,25000,80,80,80,10,100,100,80,10,CalibrationStatus.UNVALIDATED,CalibrationStatus.UNVALIDATED)
        cands=CandidateFactory(SystemConfig.from_file('uploads/PARAMETERS.json')).candidates_from_chain(chain, __import__('datetime').date(2026,6,30), 75, 0.05, ctx)
        self.assertTrue(cands)
        self.assertTrue(all(c.premium_elasticity == 0.0 for c in cands))
        self.assertTrue(all(c.expected_value_r == 0.0 for c in cands))
        self.assertTrue(all(c.convexity_edge_score == 0.0 for c in cands))


if __name__ == '__main__':
    unittest.main()
