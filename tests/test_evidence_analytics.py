import gzip
import csv
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from institutional_options.evidence_analytics import (
    build_evidence_snapshot,
    scan_session_integrity,
    timestamp_quality,
)


class EvidenceAnalyticsTests(unittest.TestCase):
    def test_timestamp_quality_separates_source_and_receipt_delay(self):
        source = "2026-08-27T10:00:00+00:00"
        received = "2026-08-27T10:00:02+00:00"
        result = timestamp_quality(source, received, max_delay_seconds=5)
        self.assertEqual(result["status"], "VALID")
        self.assertEqual(result["delay_seconds"], 2.0)

    def test_session_integrity_flags_truncated_gzip(self):
        with tempfile.TemporaryDirectory() as td:
            sessions = Path(td) / "sessions"
            sessions.mkdir()
            valid = sessions / "valid.jsonl.gz"
            with gzip.open(valid, "wt", encoding="utf-8") as handle:
                handle.write('{"event":"ok"}\n')
            (sessions / "truncated.jsonl.gz").write_bytes(b"\\x1f\\x8b\\x08broken")
            result = scan_session_integrity(td)
            self.assertEqual(result["status"], "DEGRADED")
            self.assertEqual(result["files"], 2)
            self.assertGreaterEqual(len(result["errors"]), 1)

    def test_lane_and_sample_readiness_are_separate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows = [
                {"trade_id": "a", "underlying": "CIPLA", "net_pnl": "-10", "gross_pnl": "-8", "costs": "2", "hold_seconds": "60", "exit_reason": "STOP"},
                {"trade_id": "b", "underlying": "ONGC", "net_pnl": "20", "gross_pnl": "22", "costs": "2", "hold_seconds": "90", "exit_reason": "TARGET"},
            ]
            with (root / "trades.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            with (root / "paper_calibration_trades.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            result = build_evidence_snapshot(root, min_sample=30)
            self.assertEqual(result["total"]["sample_size"], 2)
            self.assertEqual(result["by_lane"]["PAPER_CALIBRATION"]["sample_size"], 2)
            self.assertFalse(result["by_lane"]["PAPER_CALIBRATION"]["sufficient_sample"])
            self.assertEqual(result["by_underlying"]["CIPLA"]["losses"], 1)


if __name__ == "__main__":
    unittest.main()
