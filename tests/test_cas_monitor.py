import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from institutional_options.cas_monitor import CasAnomalyMonitor
from institutional_options.cas_replay import replay_cas_events


class CasMonitorTests(unittest.TestCase):
    NOW = datetime(2026, 8, 27, 15, 20, tzinfo=timezone(timedelta(hours=5, minutes=30)))

    @staticmethod
    def chain(mid, bid=9.5, ask=10.5, bid_qty=10, ask_qty=10):
        quote = SimpleNamespace(
            mid=mid, bid=bid, ask=ask, last=mid, bid_qty=bid_qty, ask_qty=ask_qty,
            cumulative_bid_qty_5depth=None, cumulative_ask_qty_5depth=None,
            timestamp=CasMonitorTests.NOW - timedelta(seconds=1),
        )
        leg = SimpleNamespace(quote=quote)
        return SimpleNamespace(expiry=date(2026, 8, 27).isoformat(), strikes=(SimpleNamespace(strike=65000, ce=None, pe=leg),))

    def test_large_cas_move_with_fresh_size_is_executable_research_event(self):
        with tempfile.TemporaryDirectory() as td:
            monitor = CasAnomalyMonitor(td, {"min_jump_pct": 100.0})
            monitor.observe({"BANKEX": self.chain(5.0)}, self.NOW - timedelta(minutes=1), {"BANKEX": {"exchange": "BSE"}})
            snap = monitor.observe({"BANKEX": self.chain(100.0, 99.5, 100.5)}, self.NOW, {"BANKEX": {"exchange": "BSE"}}, "s1")
            self.assertEqual(snap["status"], "ACTIVE")
            self.assertEqual(snap["last_event"]["execution_status"], "EXECUTABLE")
            self.assertTrue(snap["last_event"]["paper_only"])

    def test_replay_separates_executable_and_theoretical_events(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "cas_anomalies.csv"
            path.write_text("underlying,execution_status\nBANKEX,EXECUTABLE\nBANKEX,UNVERIFIABLE\n", encoding="utf-8")
            report = replay_cas_events(path)
            self.assertEqual(report["event_count"], 2)
            self.assertEqual(report["executable_event_count"], 1)
            self.assertEqual(report["unverifiable_event_count"], 1)
            self.assertEqual(report["orders_placed"], 0)

    def test_large_cas_move_without_size_is_unverifiable(self):
        with tempfile.TemporaryDirectory() as td:
            monitor = CasAnomalyMonitor(td, {"min_jump_pct": 100.0})
            monitor.observe({"BANKEX": self.chain(5.0)}, self.NOW - timedelta(minutes=1), {"BANKEX": {"exchange": "BSE"}})
            snap = monitor.observe({"BANKEX": self.chain(100.0, 99.5, 100.5, 0, 0)}, self.NOW, {"BANKEX": {"exchange": "BSE"}})
            self.assertEqual(snap["last_event"]["execution_status"], "UNVERIFIABLE")
            self.assertIn("without fresh", snap["last_event"]["reason"])


if __name__ == "__main__":
    unittest.main()
