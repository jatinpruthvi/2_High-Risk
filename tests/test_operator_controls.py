import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from institutional_options.operator_controls import IST, load_daily_mode, load_market_context
from institutional_options.paper_runner import PaperRunner


class _StubScorer:
    def __init__(self):
        self.modes = []

    def set_runtime_mode(self, mode):
        self.modes.append(mode)


class _StubLedger:
    def __init__(self):
        self.events = []

    def append(self, *args, **kwargs):
        self.events.append((args, kwargs))


class OperatorControlTests(unittest.TestCase):
    NOW = datetime(2026, 8, 17, 9, 0, tzinfo=IST)

    def test_manual_mode_cannot_loosen_computed_mode(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "DAILY_MODE.txt"
            path.write_text(
                "mode=NORMAL\nas_of=2026-08-17\nexpires_at=2026-08-17T15:30:00+05:30\n",
                encoding="utf-8",
            )
            decision = load_daily_mode(path, "SURVIVAL", self.NOW)
        self.assertEqual(decision.status, "APPLIED")
        self.assertEqual(decision.effective_mode, "SURVIVAL")

    def test_stale_daily_mode_retains_computed_mode(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "DAILY_MODE.txt"
            path.write_text(
                "mode=DEFENSIVE\nas_of=2026-08-16\nexpires_at=2026-08-16T15:30:00+05:30\n",
                encoding="utf-8",
            )
            decision = load_daily_mode(path, "NORMAL", self.NOW)
        self.assertEqual(decision.status, "STALE")
        self.assertEqual(decision.effective_mode, "NORMAL")

    def test_utc_input_is_normalized_to_ist_session_date(self):
        utc_before_midnight = datetime(2026, 8, 16, 23, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "DAILY_MODE.txt"
            path.write_text(
                "mode=DEFENSIVE\nas_of=2026-08-17\nexpires_at=2026-08-17T15:30:00+05:30\n",
                encoding="utf-8",
            )
            decision = load_daily_mode(path, "NORMAL", utc_before_midnight)
        self.assertEqual(decision.status, "APPLIED")
        self.assertEqual(decision.effective_mode, "DEFENSIVE")

    def test_market_context_requires_expiry_and_bounds(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "DAILY_MARKET_CONTEXT.json"
            path.write_text(json.dumps({
                "enabled": True,
                "as_of": "2026-08-17",
                "expires_at": "2026-08-17T15:30:00+05:30",
                "source": "MANUAL_PROXY_RESEARCH",
                "event_risk": 80,
                "recent_iv_expansion_pct": 70,
                "iv_realized_spread_pct": 60,
                "term_structure_risk": 50,
                "skew_risk": 40,
            }), encoding="utf-8")
            decision = load_market_context(path, self.NOW)
        self.assertEqual(decision.status, "APPLIED")
        self.assertEqual(decision.values["event_risk"], 80.0)

    def test_expiry_boundary_is_evaluated_in_ist(self):
        exact_expiry_utc = datetime(2026, 8, 17, 10, 0, tzinfo=timezone.utc)
        after_expiry_utc = datetime(2026, 8, 17, 10, 0, 1, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "DAILY_MODE.txt"
            path.write_text(
                "mode=DEFENSIVE\nas_of=2026-08-17\nexpires_at=2026-08-17T15:30:00+05:30\n",
                encoding="utf-8",
            )
            exact = load_daily_mode(path, "NORMAL", exact_expiry_utc)
            after = load_daily_mode(path, "NORMAL", after_expiry_utc)
        self.assertEqual(exact.status, "APPLIED")
        self.assertEqual(after.status, "INVALID")

    def test_disabled_market_context_does_not_claim_live_truth(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "DAILY_MARKET_CONTEXT.json"
            path.write_text(json.dumps({"enabled": False}), encoding="utf-8")
            decision = load_market_context(path, self.NOW)
        self.assertEqual(decision.status, "DISABLED")
        self.assertEqual(decision.values["event_risk"], 10.0)

    def test_runner_refreshes_mode_and_market_context_each_cycle(self):
        with tempfile.TemporaryDirectory() as td:
            mode_path = Path(td) / "DAILY_MODE.txt"
            context_path = Path(td) / "DAILY_MARKET_CONTEXT.json"
            mode_path.write_text(
                "mode=NORMAL\nas_of=2026-08-17\nexpires_at=2026-08-17T15:30:00+05:30\n",
                encoding="utf-8",
            )
            context_path.write_text(json.dumps({"enabled": False}), encoding="utf-8")
            runner = PaperRunner.__new__(PaperRunner)
            runner._daily_mode_path = str(mode_path)
            runner._market_context_path = str(context_path)
            runner._risk_context = {"global_risk_state": "NEUTRAL", "news_state": "NEWS_NORMAL"}
            runner.scorer_engine = _StubScorer()
            runner.factory = SimpleNamespace(market_context=None)
            runner.signal = SimpleNamespace(market_context=None)
            runner.state = SimpleNamespace(underlyings={}, session_id="TEST_SESSION")
            runner.event_ledger = _StubLedger()

            runner._refresh_daily_controls(self.NOW)
            self.assertEqual(runner.daily_mode.effective_mode, "NORMAL")
            self.assertEqual(runner.factory.market_context.status, "DISABLED")

            mode_path.write_text(
                "mode=DEFENSIVE\nas_of=2026-08-17\nexpires_at=2026-08-17T15:30:00+05:30\n",
                encoding="utf-8",
            )
            context_path.write_text(json.dumps({
                "enabled": True,
                "as_of": "2026-08-17",
                "expires_at": "2026-08-17T15:30:00+05:30",
                "source": "MANUAL_PROXY_RESEARCH",
                "event_risk": 60,
                "recent_iv_expansion_pct": 20,
                "iv_realized_spread_pct": 10,
                "term_structure_risk": 15,
                "skew_risk": 10,
            }), encoding="utf-8")
            runner._refresh_daily_controls(self.NOW)

            self.assertEqual(runner.daily_mode.effective_mode, "DEFENSIVE")
            self.assertEqual(runner.factory.market_context.status, "APPLIED")
            self.assertIs(runner.factory.market_context, runner.signal.market_context)
            self.assertEqual(runner.scorer_engine.modes, ["NORMAL", "DEFENSIVE"])
            self.assertEqual(len(runner.event_ledger.events), 4)


if __name__ == "__main__":
    unittest.main()

