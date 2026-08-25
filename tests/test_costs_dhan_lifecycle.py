import tempfile
import unittest
from datetime import datetime, date, timedelta
from pathlib import Path

from institutional_options.costs import ChargesConfig, CostCalculator
from institutional_options.dhan import DhanCredentials, DhanRestClient
from institutional_options.execution import ExecutionRouter, OrderIntent
from institutional_options.lifecycle import MarketBar, SimulatedTradeLifecycle
from institutional_options.models import CalibrationStatus, CandidateInputs, DataHealth, Greeks, InstrumentSpec, Moneyness, OptionType, PaperTrade, Quote
from institutional_options.scoring import OpportunityScorer, PaperFillSimulator
from institutional_options.config import SystemConfig
from institutional_options.skipped import SkippedCandidateWriter
from institutional_options.reporting import DashboardHTML, DryRunReportGenerator


def make_eval_and_fill():
    cfg = SystemConfig.from_file("uploads/PARAMETERS.json")
    now = datetime(2026, 6, 1, 10)
    c = CandidateInputs(
        instrument=InstrumentSpec("NIFTY", "1", "OPTIDX", date(2026,6,30), 75, 0.05, 25000, OptionType.CE),
        quote=Quote(100, 100.5, 1000, 1000, 100.25, now, 5000, 5000),
        moneyness=Moneyness.ATM,
        greeks=Greeks(delta=0.5),
        data_health=DataHealth(True),
        futures_price=25000,
        underlying_price=25000,
        instrument_direction_score=95,
        trade_quality_score=95,
        regime_confidence=85,
        market_hostility_score=10,
        iv_crush_risk_score=20,
        premium_elasticity=1.2,
        expected_move=200,
        required_move=100,
        required_stop_points=10,
        convexity_edge_score=95,
        execution_quality_score=95,
        opportunity_confidence_score=95,
        regime_fit_score=95,
        calibration_status_direction=CalibrationStatus.VALIDATED,
        calibration_status_liquidity=CalibrationStatus.VALIDATED,
        candidate_created_at=now,
    )
    ev = OpportunityScorer(cfg).evaluate(c)
    fill = PaperFillSimulator(cfg).entry_buy(c.quote, c.instrument.tick_size)
    return cfg, ev, fill, now


class AddedModuleTests(unittest.TestCase):
    def test_cost_calculator(self):
        charges = ChargesConfig.from_file("uploads/CHARGES_CONFIG.json")
        costs = CostCalculator(charges).round_trip_cost(10000, 11000)
        self.assertGreater(costs.total, 0)

    def test_dhan_demo_order_not_sent(self):
        client = DhanRestClient(DhanCredentials("client", "token"), demo_trade=True)
        router = ExecutionRouter(client)
        res = router.place(OrderIntent("client", "BUY", "NSE_FNO", "INTRADAY", "LIMIT", "DAY", "1", 75, 100.0))
        self.assertTrue(res["demo"])
        self.assertEqual(res["orderStatus"], "DEMO_NOT_SENT")

    def test_execution_router_rejects_malformed_order_before_broker_call(self):
        class StubClient:
            demo_trade = False
            called = False

            def place_order(self, payload):
                self.called = True
                return {"orderStatus": "SHOULD_NOT_BE_CALLED"}

        client = StubClient()
        router = ExecutionRouter(client)
        result = router.place(OrderIntent("client", "BUY", "NSE_FNO", "INTRADAY", "LIMIT", "DAY", "", 0, 100.0))
        self.assertEqual(result["orderStatus"], "REJECTED_VALIDATION")
        self.assertFalse(client.called)
        self.assertIn("security_id is required", result["validationErrors"])
        self.assertIn("quantity must be a positive integer", result["validationErrors"])

    def test_lifecycle_exits_target(self):
        cfg, ev, fill, now = make_eval_and_fill()
        trade = PaperTrade("T1", ev, fill, now)
        bars = [MarketBar(now + timedelta(seconds=60), Quote(105, 105.5, 1000,1000,105.25, now + timedelta(seconds=60)), 25050)]
        result = SimulatedTradeLifecycle(PaperFillSimulator(cfg)).run(trade, bars, target_points=4, stop_points=5, max_duration_seconds=600)
        self.assertEqual(result.exit_reason, "TARGET_HIT")

    def test_skipped_writer_and_reports(self):
        with tempfile.TemporaryDirectory() as d:
            skipped = SkippedCandidateWriter("uploads/SKIPPED_CANDIDATE_SCHEMA.csv", Path(d)/"skipped.csv")
            skipped.append({"skip_id":"S1","timestamp":"t","ranking_cycle_id":"R1","underlying":"NIFTY","option_type":"CE","rank":1,"OpportunityScore":75,"DirectionScore":80,"TradeQualityScore":80,"ContractQualityScore":80,"PremiumElasticity":1.0,"ExpectedMove":100,"RequiredMove":80,"ExpectedRequiredRatio":1.25,"IVCrushRiskScore":20,"MarketHostilityScore":10,"RegimeConfidence":75,"DataHealthStatus":"VALID","hard_stop_fit":True,"why_not_traded":"B grade","calibration_status":"UNVALIDATED"})
            self.assertTrue((Path(d)/"skipped.csv").exists())
            DashboardHTML.write_ranking(Path(d)/"dash.html", [{"instrument":"NIFTY","score":90}])
            self.assertTrue((Path(d)/"dash.html").exists())
            report_path = Path(d)/"mtil.csv"
            report_path.write_text("net_pnl_rupees\n100\n-50\n")
            text = DryRunReportGenerator(report_path).summary_text()
            self.assertIn("Trades: 2", text)


if __name__ == "__main__":
    unittest.main()
