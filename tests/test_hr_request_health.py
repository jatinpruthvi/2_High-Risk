import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from institutional_options.fyers_client import FyersAPIError, FyersCredentials, FyersRestClient, TokenStore


class FyersRequestHealthTests(unittest.TestCase):
    def test_option_chain_retries_transient_429_and_publishes_stats(self):
        with tempfile.TemporaryDirectory() as td:
            client = FyersRestClient(
                FyersCredentials("APP-100", "secret"),
                TokenStore(Path(td) / "tokens.json"),
                timeout=5,
                request_min_interval_sec=0.0,
                max_transient_retries=1,
                transient_backoff_sec=(0.0,),
                max_backoff_sec=0.0,
            )
            responses = [
                FyersAPIError("rate limited", status_code=429),
                (200, {"s": "ok", "data": {}}),
            ]
            with patch("institutional_options.fyers_client._req", side_effect=responses) as req:
                result = client.option_chain("NSE:NIFTY50-INDEX")
            self.assertEqual(result["s"], "ok")
            self.assertEqual(req.call_count, 2)
            stats = client.request_stats()
            self.assertEqual(stats["requests"], 2)
            self.assertEqual(stats["successes"], 1)
            self.assertEqual(stats["errors"], 0)
            self.assertEqual(stats["rate_limit_hits"], 1)
            self.assertEqual(stats["retries"], 1)
            self.assertEqual(stats["last_status"], 200)

    def test_exhausted_429_is_recorded_without_token_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            token_path = Path(td) / "tokens.json"
            token_path.write_text(json.dumps({"access_token": "saved", "refresh_token": "refresh"}), encoding="utf-8")
            client = FyersRestClient(
                FyersCredentials("APP-100", "secret"),
                TokenStore(token_path),
                timeout=5,
                request_min_interval_sec=0.0,
                max_transient_retries=1,
                transient_backoff_sec=(0.0,),
                max_backoff_sec=0.0,
            )
            with patch("institutional_options.fyers_client._req", side_effect=FyersAPIError("rate limited", status_code=429)):
                with self.assertRaises(FyersAPIError):
                    client.option_chain("NSE:NIFTY50-INDEX")
            stats = client.request_stats()
            self.assertEqual(stats["requests"], 2)
            self.assertEqual(stats["successes"], 0)
            self.assertEqual(stats["errors"], 1)
            self.assertEqual(stats["rate_limit_hits"], 2)
            self.assertEqual(stats["retries"], 1)
            self.assertEqual(json.loads(token_path.read_text(encoding="utf-8"))["access_token"], "saved")


class HighRiskRequestConfigTests(unittest.TestCase):
    def test_active_config_has_bounded_request_health_settings(self):
        path = Path(__file__).parents[1] / "uploads" / "PAPER_RUNNER.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(cfg["fyers_request_min_interval_seconds"], 0.35)
        self.assertEqual(cfg["fyers_max_transient_retries"], 2)
        self.assertEqual(cfg["fyers_transient_backoff_seconds"], [1.0, 3.0])
        self.assertEqual(cfg["fyers_max_backoff_seconds"], 8.0)
        self.assertTrue(cfg["experimental_impulse_breakout"]["research_only"])
        self.assertFalse(cfg["experimental_impulse_breakout"]["paper_entry_enabled"])


if __name__ == "__main__":
    unittest.main()
