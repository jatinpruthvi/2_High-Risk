import unittest
from types import SimpleNamespace

from institutional_options.paper_runner import PaperRunner


class ConcurrentPositionTests(unittest.TestCase):
    def _runner(self):
        runner = object.__new__(PaperRunner)
        runner.cfg = {"max_concurrent_paper_positions": 2}
        runner.state = SimpleNamespace(open_positions=[], open_position=None)
        return runner

    @staticmethod
    def _position(trade_id, entry=10.0, last=10.0, stop=1.0):
        evaluation = SimpleNamespace(
            candidate=SimpleNamespace(instrument=SimpleNamespace(lot_size=25)),
        )
        trade = SimpleNamespace(trade_id=trade_id, entry_fill=SimpleNamespace(fill_price=entry), entry_evaluation=evaluation)
        return SimpleNamespace(trade=trade, last_premium=last, stop_points=stop)

    def test_two_positions_allowed_third_is_blocked(self):
        runner = self._runner()
        self.assertTrue(runner._add_open_position(self._position("one")))
        self.assertTrue(runner._add_open_position(self._position("two")))
        self.assertFalse(runner._capacity_available())
        self.assertFalse(runner._add_open_position(self._position("three")))
        self.assertEqual(len(runner.state.open_positions), 2)
        self.assertEqual(runner.state.open_position.trade.trade_id, "one")

    def test_risk_reservation_is_aggregated_across_positions(self):
        runner = self._runner()
        runner._add_open_position(self._position("one", entry=10, last=10, stop=1))
        runner._add_open_position(self._position("two", entry=20, last=21, stop=2))
        self.assertEqual(runner._open_position_risk_reservation(), 100.0)

    def test_remove_keeps_primary_alias_consistent(self):
        runner = self._runner()
        first = self._position("one")
        second = self._position("two")
        runner._add_open_position(first)
        runner._add_open_position(second)
        runner._remove_open_position(first)
        self.assertEqual(len(runner.state.open_positions), 1)
        self.assertEqual(runner.state.open_position.trade.trade_id, "two")


if __name__ == "__main__":
    unittest.main()
