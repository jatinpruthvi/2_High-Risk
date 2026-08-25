import tempfile
import unittest
from pathlib import Path

from institutional_options.phase4 import (
    AutoExecutionResearchGate, AutoExecutionResearchMetrics,
    MultiPositionResearchGate, MultiPositionResearchMetrics,
    Phase4ExperimentGate, ResearchExperimentResult, ResearchExperimentSpec,
    ResearchLedger, SectorExpansionGate, SectorIndexCandidate,
    StockOptionEnrichmentGate, StockOptionEnrichmentMetrics,
)


class Phase4ExtendedTests(unittest.TestCase):
    def test_experiment_gate_advances_good_research(self):
        spec=ResearchExperimentSpec('E1','GEX Test','MICRO','test',100,'expectancy',0.0)
        res=ResearchExperimentResult('E1',150,0.1,0.0,0.2,0.1,0.01)
        review=Phase4ExperimentGate().review(spec,res)
        self.assertEqual(review.decision.value,'ADVANCE_TO_SHADOW')

    def test_sector_expansion_never_phase1_universe(self):
        c=SectorIndexCandidate('NIFTYIT',90,90,90,80,0.1,20)
        r=SectorExpansionGate().review(c)
        self.assertTrue(r.approved_for_research_watchlist)
        self.assertFalse(r.approved_for_phase1_universe)

    def test_stock_option_enrichment_gate(self):
        m=StockOptionEnrichmentMetrics('HDFCBANK',60,0.05,0.1,0.01,90)
        r=StockOptionEnrichmentGate().review(m)
        self.assertTrue(r.eligible_for_future_wbci_enrichment)

    def test_multi_position_stays_rejected_phase1(self):
        m=MultiPositionResearchMetrics(300,0.2,0.0,True,0.0,20)
        r=MultiPositionResearchGate().review(m)
        self.assertTrue(r.keep_rejected_for_phase1)
        self.assertTrue(r.eligible_for_future_committee_review)

    def test_auto_execution_rejected_production(self):
        m=AutoExecutionResearchMetrics(300,1.0,0.0,0,10.0,True)
        r=AutoExecutionResearchGate().review(m)
        self.assertTrue(r.production_rejected)
        self.assertTrue(r.eligible_for_shadow_research)

    def test_research_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            spec=ResearchExperimentSpec('E1','Test','CAT','hyp',100,'ev',0.0)
            res=ResearchExperimentResult('E1',10,0,0,0,0,0)
            review=Phase4ExperimentGate().review(spec,res)
            ledger=ResearchLedger(Path(d)/'ledger.csv')
            ledger.append(review)
            self.assertTrue((Path(d)/'ledger.csv').exists())


if __name__ == '__main__':
    unittest.main()
