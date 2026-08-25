import csv
import tempfile
import unittest
from pathlib import Path

from institutional_options.config import SystemConfig
from institutional_options.phase2 import CsvDataset, DryRunValidator, EvidenceAnalyzer, Phase2ReportWriter


def write_csv(path, rows):
    fields = sorted({k for r in rows for k in r})
    with open(path, 'w', newline='') as f:
        w=csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)


class Phase2Tests(unittest.TestCase):
    def setUp(self):
        self.cfg = SystemConfig.from_file('uploads/PARAMETERS.json')

    def test_acceptance_passes_with_sufficient_data(self):
        with tempfile.TemporaryDirectory() as d:
            mtil=[]; skipped=[]
            for i in range(100):
                day = 1 + (i % 20)
                mtil.append({
                    'trade_id': f'T{i}', 'date': f'2026-06-{day:02d}', 'ranking_cycle_id': f'R{i}',
                    'instrument':'NIFTY', 'option_type':'CE', 'OpportunityScore':'85', 'OpportunityGrade':'A',
                    'DirectionScore':'80','TradeQualityScore':'80','ContractQualityScore':'80','MarketHostilityScore':'10',
                    'planned_risk_rupees':'500','net_pnl_rupees': '100' if i%2==0 else '-50','r_multiple':'1' if i%2==0 else '-0.5',
                    'trade_archetype_code':'A01','signal_combination_id':'S','regime_combination_id':'G','opportunity_cluster_id':'C',
                    'entry_revalidation_passed':'true','paper_fill_model':'bid_ask','cost_model_valid':'true','canonical_promotion_allowed':'true','rule_violations':'','rule_violation_type':''
                })
                skipped.append({'skip_id':f'SK{i}','timestamp':f'2026-06-{day:02d}T10:00:00','ranking_cycle_id':f'R{i}','underlying':'NIFTY','option_type':'PE','rank':'2','OpportunityScore':'70','DirectionScore':'70','TradeQualityScore':'70','ContractQualityScore':'80','PremiumElasticity':'1','ExpectedMove':'100','RequiredMove':'80','ExpectedRequiredRatio':'1.25','IVCrushRiskScore':'20','MarketHostilityScore':'10','RegimeConfidence':'75','DataHealthStatus':'VALID','hard_stop_fit':'true','why_not_traded':'lower rank','calibration_status':'UNVALIDATED','would_have_hit_target':'false','would_have_hit_stop':'true'})
            mp=Path(d)/'mtil.csv'; sp=Path(d)/'skipped.csv'
            write_csv(mp,mtil); write_csv(sp,skipped)
            acc=DryRunValidator(self.cfg).validate(CsvDataset.from_csv(mp), CsvDataset.from_csv(sp), dashboard_latency_pass_rate_pct=99, emergency_tests_passed=True)
            self.assertTrue(acc.passed, acc.summary_text())

    def test_placeholder_cost_evidence_fails_acceptance(self):
        row = {
            'trade_id': 'T0', 'date': '2026-06-01', 'ranking_cycle_id': 'R0',
            'entry_revalidation_passed': 'true', 'paper_fill_model': 'bid_ask',
            'cost_model_valid': 'false', 'canonical_promotion_allowed': 'false',
        }
        result = DryRunValidator(self.cfg).validate(CsvDataset([row]), emergency_tests_passed=True)
        cost_check = next(check for check in result.checks if check.name == 'cost_model_validity')
        self.assertFalse(cost_check.passed)
        self.assertFalse(result.passed)

    def test_final_five_days_include_skipped_only_dates(self):
        mtil = []
        for i in range(100):
            day = 1 + (i % 20)
            mtil.append({
                'trade_id': f'T{i}', 'date': f'2026-06-{day:02d}', 'ranking_cycle_id': f'R{i}',
                'entry_revalidation_passed': 'true', 'paper_fill_model': 'bid_ask',
                'cost_model_valid': 'true', 'canonical_promotion_allowed': 'true',
            })
        skipped = CsvDataset([{
            'skip_id': 'SKIPPED_ONLY', 'timestamp': '2026-06-21T10:00:00',
            'ranking_cycle_id': 'R-SKIPPED', 'mapping_validation_passed': 'false',
        }])
        result = DryRunValidator(self.cfg).validate(CsvDataset(mtil), skipped, emergency_tests_passed=True)
        mapping_check = next(check for check in result.checks if check.name == 'critical_mapping_errors_final_5_days')
        self.assertFalse(mapping_check.passed)
        self.assertEqual(mapping_check.observed, 1)

    def test_evidence_analyzer_groups(self):
        rows=[
            {'instrument':'NIFTY','trade_archetype_code':'A01','primary_regime':'Trend','net_pnl_rupees':'100','r_multiple':'1','OpportunityScore':'90','ExpectedValue_R':'0.5','VolEdgeRatio':'1.8','premium_failure_flag':'false','entry_slippage_points':'1','exit_slippage_points':'1'},
            {'instrument':'BANKNIFTY','trade_archetype_code':'A02','primary_regime':'Gap','net_pnl_rupees':'-50','r_multiple':'-0.5','OpportunityScore':'80','ExpectedValue_R':'0.2','VolEdgeRatio':'1.2','premium_failure_flag':'true','entry_slippage_points':'2','exit_slippage_points':'3'}]
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'mtil.csv'; write_csv(p,rows)
            review=EvidenceAnalyzer().analyze(CsvDataset.from_csv(p))
            self.assertEqual(review.overall.trades,2)
            self.assertEqual(len(review.by_instrument),2)
            out=Phase2ReportWriter.write_text(Path(d)/'report.txt', DryRunValidator(self.cfg).validate(CsvDataset.from_csv(p), emergency_tests_passed=False), review)
            self.assertTrue(out.exists())


if __name__ == '__main__':
    unittest.main()
