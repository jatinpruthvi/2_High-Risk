"""Tests for the new exit-policy behaviours: volatility-aware time stop and
gap/slippage on risk-reducing exits."""

import unittest
from datetime import datetime, timedelta

from institutional_options.config import SystemConfig
from institutional_options.lifecycle import (
    EXIT_STOP, EXIT_TIME, EXIT_VOL_TIME,
    ExitPolicy, MarketBar, SimulatedTradeLifecycle,
)
from institutional_options.models import Quote
from institutional_options.roi_lab import make_lab_trade
from institutional_options.scoring import PaperFillSimulator

CFG_PATH = "uploads/PARAMETERS.json"


def _quote(premium: float, spread: float = 0.6, ts=None) -> Quote:
    half = spread / 2.0
    bid = max(0.05, premium - half)
    ask = bid + spread
    return Quote(bid, ask, 5000, 5000, (bid + ask) / 2.0, ts or datetime.now())


class ExitPolicyTests(unittest.TestCase):
    def setUp(self):
        self.cfg = SystemConfig.from_file(CFG_PATH)
        self.sim = SimulatedTradeLifecycle(PaperFillSimulator(self.cfg))

    def _trade(self):
        return make_lab_trade(_quote(100.0), self.cfg)

    def _bars(self, trade, premiums, expected_move=None):
        bars = []
        for i, p in enumerate(premiums):
            ts = trade.entry_time + timedelta(seconds=5 * i)
            bars.append(MarketBar(ts, _quote(p), 25000.0,
                                  expected_move_remaining=expected_move))
        return bars

    def test_vol_time_stop_fires_when_move_exhausted(self):
        trade = self._trade()
        # 60 bars at 5s -> max window 300s. Flat premium at entry: no target
        # (140) and no stop (80). After 35% of the window the remaining expected
        # move (10 pts) is far below the 40 pts needed for the target -> exit.
        bars = self._bars(trade, [100.0] * 60, expected_move=10.0)
        result = self.sim.run(trade, bars, target_points=40.0, stop_points=20.0,
                              max_duration_seconds=300,
                              exit_policy=ExitPolicy(vol_time_stop_fraction=0.35))
        self.assertEqual(result.exit_reason, EXIT_VOL_TIME)
        # Fires on the first bar past 35%: bar 21 -> 105s.
        self.assertEqual((result.trade.exit_time - trade.entry_time).total_seconds(), 105.0)

    def test_vol_time_stop_holds_when_move_sufficient(self):
        trade = self._trade()
        # 61 bars -> last bar sits exactly on the 300s deadline.
        bars = self._bars(trade, [100.0] * 61, expected_move=50.0)
        result = self.sim.run(trade, bars, target_points=40.0, stop_points=20.0,
                              max_duration_seconds=300,
                              exit_policy=ExitPolicy(vol_time_stop_fraction=0.35))
        # 40 <= 50, so the vol-time stop never fires; the deadline exits.
        self.assertEqual(result.exit_reason, EXIT_TIME)

    def test_stop_exit_slippage_widens_loss(self):
        trade = self._trade()
        premiums = [100.0] * 10 + [90.0, 85.0, 80.0] + [79.0] * 5
        bars = self._bars(trade, premiums)
        plain = self.sim.run(trade, bars, 40.0, 20.0, 300,
                             ExitPolicy(stop_exit_slippage_frac=0.0))
        slip = self.sim.run(trade, bars, 40.0, 20.0, 300,
                            ExitPolicy(stop_exit_slippage_frac=0.1))
        self.assertEqual(plain.exit_reason, EXIT_STOP)
        self.assertEqual(slip.exit_reason, EXIT_STOP)
        # 10% of 1R (20 pts) = 2.0 pts of extra slippage on the exit fill.
        gap = plain.trade.exit_fill.fill_price - slip.trade.exit_fill.fill_price
        self.assertGreaterEqual(gap, 1.5)


if __name__ == "__main__":
    unittest.main()
