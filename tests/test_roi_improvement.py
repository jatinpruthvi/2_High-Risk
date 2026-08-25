import unittest
from datetime import datetime, date, timedelta

from institutional_options.candidates import CandidateFactory, CandidateFactoryContext
from institutional_options.config import SystemConfig
from institutional_options.lifecycle import ExitPolicy, MarketBar, SimulatedTradeLifecycle, EXIT_BREAKEVEN, EXIT_LOSING_TIME, EXIT_TRAIL, EXIT_TARGET
from institutional_options.models import CalibrationStatus, Quote
from institutional_options.option_chain import DhanOptionChainParser
from institutional_options.risk import DynamicRiskCalculator, RequiredStopModel, RiskContext
from institutional_options.roi_lab import LabScenario, make_lab_trade, run_experiment, generate_paths, simulate_trades
from institutional_options.scoring import PaperFillSimulator


def bars_from_premiums(values, start=None):
    start = start or datetime(2026, 6, 1, 10, 0, 0)
    out = []
    for i, p in enumerate(values):
        ts = start + timedelta(seconds=5 * i)
        bid = p - 0.25
        ask = p + 0.25
        out.append(MarketBar(ts, Quote(bid, ask, 5000, 5000, p, ts, 25000, 25000), 25000.0))
    return out


class ExitPolicyTests(unittest.TestCase):
    def setUp(self):
        self.cfg = SystemConfig.from_file("uploads/PARAMETERS.json")
        self.entry_quote = Quote(99.75, 100.25, 5000, 5000, 100.0, datetime(2026, 6, 1, 10, 0, 0), 25000, 25000)
        self.trade = make_lab_trade(self.entry_quote, self.cfg)
        self.lifecycle = SimulatedTradeLifecycle(PaperFillSimulator(self.cfg))

    def run_trade(self, premiums, policy):
        return self.lifecycle.run(
            self.trade, bars_from_premiums(premiums),
            target_points=40.0, stop_points=20.0, max_duration_seconds=600, exit_policy=policy,
        )

    def test_breakeven_locks_in_profit_after_1r(self):
        premiums = [100, 106, 112, 118, 121, 118, 112, 106, 100, 94, 88]
        legacy = self.run_trade(premiums, None)
        managed = self.run_trade(premiums, ExitPolicy.from_config(self.cfg))
        self.assertEqual(managed.exit_reason, EXIT_BREAKEVEN)
        # Managed exits near breakeven; legacy rides the winner back to a loss.
        self.assertGreater(managed.gross_pnl_points, legacy.gross_pnl_points)
        self.assertGreater(managed.gross_pnl_points, -1.0)
        self.assertLess(legacy.gross_pnl_points, -5.0)

    def test_trailing_stop_banks_profit(self):
        premiums = [100, 110, 120, 130, 136, 130, 124, 118, 112, 106, 100]
        policy = ExitPolicy(enabled=True, breakeven_trigger_r=1.0, trail_trigger_r=1.5, trail_distance_r=1.0)
        legacy = self.run_trade(premiums, None)
        managed = self.run_trade(premiums, policy)
        self.assertEqual(managed.exit_reason, EXIT_TRAIL)
        self.assertGreater(managed.gross_pnl_points, 0.0)
        self.assertGreater(managed.gross_pnl_points, legacy.gross_pnl_points)

    def test_target_still_takes_priority(self):
        premiums = [100, 110, 120, 130, 141]
        for policy in (None, ExitPolicy.from_config(self.cfg)):
            result = self.run_trade(premiums, policy)
            self.assertEqual(result.exit_reason, EXIT_TARGET)

    def test_managed_never_worse_than_initial_stop(self):
        scenario = LabScenario(n_paths=300, seed=5)
        paths = generate_paths(scenario)
        policy = ExitPolicy.from_config(self.cfg)
        legacy = simulate_trades(paths, self.cfg, None, scenario)
        managed = simulate_trades(paths, self.cfg, policy, scenario)
        # Per-trade worst case is bounded by the 1R initial stop in both regimes
        # (small extra from exit spread), and managed never exceeds legacy's tail.
        self.assertGreater(legacy.max_drawdown_r, 0)
        self.assertLessEqual(managed.max_drawdown_r, legacy.max_drawdown_r + 1e-6)

    def test_losing_time_stop_cuts_losers_early(self):
        premiums = [100, 99, 98, 97, 96, 95, 94, 93, 92, 91]  # 60s spacing -> 35% of 600s at bar 4
        start = datetime(2026, 6, 1, 10, 0, 0)
        bars = []
        for i, p in enumerate(premiums):
            ts = start + timedelta(seconds=60 * i)
            bars.append(MarketBar(ts, Quote(p - 0.25, p + 0.25, 5000, 5000, p, ts, 25000, 25000), 25000.0))
        policy = ExitPolicy.from_config(self.cfg)
        legacy = self.lifecycle.run(self.trade, bars, target_points=40.0, stop_points=20.0, max_duration_seconds=600)
        managed = self.lifecycle.run(self.trade, bars, target_points=40.0, stop_points=20.0, max_duration_seconds=600, exit_policy=policy)
        self.assertEqual(managed.exit_reason, EXIT_LOSING_TIME)
        self.assertGreater(managed.gross_pnl_points, legacy.gross_pnl_points)
        self.assertLess(managed.gross_pnl_points, 0.0)  # cut at a small loss, not ridden to the time stop

    def test_exit_policy_from_config(self):
        policy = ExitPolicy.from_config(self.cfg)
        self.assertTrue(policy.enabled)
        self.assertEqual(policy.breakeven_trigger_r, 1.0)
        self.assertEqual(policy.trail_trigger_r, 2.0)
        self.assertEqual(policy.trail_distance_r, 1.0)
        self.assertEqual(policy.losing_time_stop_fraction, 0.35)
        self.assertEqual(policy.time_decay_tighten, 0.0)
        self.assertFalse(ExitPolicy.from_config(None).enabled)


class RequiredStopModelTests(unittest.TestCase):
    def setUp(self):
        self.cfg = SystemConfig.from_file("uploads/PARAMETERS.json")

    def test_required_stop_is_premium_based(self):
        model = RequiredStopModel(self.cfg)
        self.assertEqual(model.required_stop_points(100.0), 20.0)
        self.assertEqual(model.required_stop_points(250.0), 50.0)

    def test_candidate_factory_no_longer_conflates_required_move_with_stop(self):
        payload = {"data": {"last_price": 25000, "oc": {"25000.000000": {
            "ce": {"top_bid_price": 100, "top_ask_price": 100.5, "top_bid_quantity": 1000, "top_ask_quantity": 1000,
                   "last_price": 100.25, "security_id": 1, "oi": 1000, "previous_oi": 900, "volume": 10000,
                   "greeks": {"delta": 0.5}, "implied_volatility": 12, "source_timestamp": "2026-06-01T10:00:00+05:30"},
            "pe": {"top_bid_price": 100, "top_ask_price": 100.5, "top_bid_quantity": 1000, "top_ask_quantity": 1000,
                   "last_price": 100.25, "security_id": 2, "oi": 1000, "previous_oi": 900, "volume": 10000,
                   "greeks": {"delta": -0.5}, "implied_volatility": 12, "source_timestamp": "2026-06-01T10:00:00+05:30"}}}}}
        chain = DhanOptionChainParser.parse(payload, "NIFTY", "2026-06-30")
        ctx = CandidateFactoryContext(25000, 25000, 80, 80, 80, 10, 100, 100, 80, 10,
                                      CalibrationStatus.UNVALIDATED, CalibrationStatus.UNVALIDATED)
        cands = CandidateFactory(self.cfg).candidates_from_chain(chain, date(2026, 6, 30), 75, 0.05, ctx)
        c = cands[0]
        self.assertTrue(c.quote.source_timestamp_available)
        # Logical stop is a fraction of premium (~20.05), not the 80-point required move.
        self.assertAlmostEqual(c.required_stop_points, 100.25 * 0.2, places=6)
        self.assertNotAlmostEqual(c.required_stop_points, c.required_move)

    def test_risk_gate_accepts_stop_that_fits_cap(self):
        plan = DynamicRiskCalculator(self.cfg).plan(RiskContext(
            capital=100000, mode="NORMAL", setup_grade="A", lots=1,
            entry_premium=100.25, lot_size=30, spread_points=0.5, tick_size=0.05,
            required_stop_points=20.05, instrument="BANKNIFTY",
        ))
        self.assertTrue(plan.hard_stop_fit)
        self.assertAlmostEqual(plan.hard_stop_points, 20.05, places=4)


class RoiLabEvidenceTests(unittest.TestCase):
    def test_roi_improves_without_increasing_drawdown(self):
        legacy, managed = run_experiment(LabScenario(n_paths=2000, seed=42))
        self.assertGreater(managed.roi_pct, legacy.roi_pct)
        self.assertLessEqual(managed.max_drawdown_r, legacy.max_drawdown_r + 1e-9)
        self.assertGreaterEqual(managed.profit_factor, legacy.profit_factor)
        self.assertGreater(legacy.trades, 0)
        self.assertEqual(managed.trades, legacy.trades)


if __name__ == "__main__":
    unittest.main()
