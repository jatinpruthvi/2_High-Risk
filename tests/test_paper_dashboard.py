from __future__ import annotations

import json
import socket
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from institutional_options.paper_dashboard import PAGE, PaperDashboard


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def get_url(url: str):
    try:
        with urlopen(url, timeout=3) as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()


class PaperDashboardTests(unittest.TestCase):
    def test_routes_and_strict_json(self):
        snapshot = {
            "mode": "PAPER (no orders placed)",
            "live_trading_enabled": False,
            "last_cycle_ok": True,
            "realized_pnl": float("inf"),
            "underlyings": {"NIFTY": {"depth_health": {"status": "PARTIAL"}}},
        }
        dashboard = PaperDashboard(lambda: snapshot, port=free_port())
        dashboard.start()
        try:
            base = f"http://{dashboard.host}:{dashboard.port}"
            status, body = get_url(base + "/")
            self.assertEqual(status, 200)
            self.assertIn(b"Paper Trading Dashboard", body)
            status, body = get_url(base + "/state.json")
            self.assertEqual(status, 200)
            payload = json.loads(body)
            self.assertIsNone(payload["realized_pnl"])
            status, body = get_url(base + "/unknown")
            self.assertEqual(status, 404)
            self.assertEqual(json.loads(body)["error"], "not_found")
        finally:
            dashboard.stop()

    def test_snapshot_failure_is_503_and_truthful(self):
        dashboard = PaperDashboard(lambda: (_ for _ in ()).throw(RuntimeError("runner unavailable")), port=free_port())
        dashboard.start()
        try:
            status, body = get_url(f"http://{dashboard.host}:{dashboard.port}/state.json")
            self.assertEqual(status, 503)
            payload = json.loads(body)
            self.assertEqual(payload["error"], "snapshot_unavailable")
            self.assertIn("runner unavailable", payload["detail"])
            self.assertFalse(payload["preview_only"] is False)
        finally:
            dashboard.stop()

    def test_page_contains_latest_safety_and_observability_guards(self):
        self.assertIn("No live paper cycle is available yet", PAGE)
        self.assertIn("Live Fyers cycle in progress", PAGE)
        self.assertIn("cycle_started_at", PAGE)
        self.assertIn("elapsed", PAGE)
        self.assertIn("const grade = String(r.grade ?? '—')", PAGE)
        self.assertIn("failure_reasons", PAGE)
        self.assertIn("cache:'no-store'", PAGE)


if __name__ == "__main__":
    unittest.main()
