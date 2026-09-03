from __future__ import annotations

import csv
import gzip
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


def timestamp_quality(source_timestamp: Any, received_at: Any, max_delay_seconds: float = 5.0) -> dict[str, Any]:
    """Classify exchange/source timestamp versus local receipt timestamp."""
    result = {"status": "UNAVAILABLE", "source_timestamp": str(source_timestamp or ""), "received_at": str(received_at or ""), "delay_seconds": None}
    if not source_timestamp or not received_at:
        return result
    try:
        source = datetime.fromisoformat(str(source_timestamp).replace("Z", "+00:00"))
        received = datetime.fromisoformat(str(received_at).replace("Z", "+00:00"))
        if source.tzinfo is None:
            source = source.replace(tzinfo=timezone.utc)
        if received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
        delay = (received - source).total_seconds()
        result["delay_seconds"] = round(delay, 3)
        result["status"] = "VALID" if 0 <= delay <= max(0.0, float(max_delay_seconds)) else "DELAYED_OR_CLOCK_SKEW"
    except (TypeError, ValueError, OverflowError):
        result["status"] = "INVALID"
    return result


def scan_session_integrity(state_dir: str | Path) -> dict[str, Any]:
    root = Path(state_dir)
    files = sorted(root.glob("sessions/*.jsonl.gz"))
    errors: list[dict[str, str]] = []
    readable = 0
    records = 0
    for path in files:
        try:
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
                for _ in handle:
                    records += 1
            readable += 1
        except (OSError, EOFError, gzip.BadGzipFile) as exc:
            errors.append({"file": path.name, "error": type(exc).__name__})
    return {"status": "OK" if not errors else "DEGRADED", "files": len(files), "readable_files": readable, "records": records, "errors": errors[-20:]}


def _float(row: Mapping[str, Any], key: str) -> float:
    try:
        value = float(row.get(key, 0) or 0)
        return value if math.isfinite(value) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _trade_rows(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error):
        return []


def _stats(rows: list[dict[str, Any]], min_sample: int) -> dict[str, Any]:
    net = [_float(row, "net_pnl") for row in rows]
    wins = [value for value in net if value > 0]
    losses = [value for value in net if value < 0]
    return {
        "sample_size": len(rows),
        "sufficient_sample": len(rows) >= min_sample,
        "status": "READY" if len(rows) >= min_sample else "WARMUP_INSUFFICIENT_EVIDENCE",
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(100.0 * len(wins) / len(rows), 2) if rows else None,
        "net_pnl": round(sum(net), 2),
        "avg_net_pnl": round(sum(net) / len(net), 2) if net else None,
        "median_net_pnl": round(sorted(net)[len(net) // 2], 2) if net else None,
        "gross_pnl": round(sum(_float(row, "gross_pnl") for row in rows), 2),
        "costs": round(sum(_float(row, "costs") for row in rows), 2),
        "avg_hold_seconds": round(sum(_float(row, "hold_seconds") for row in rows) / len(rows), 2) if rows else None,
        "exit_reasons": dict(sorted(((key, sum(1 for row in rows if row.get("exit_reason") == key)) for key in {row.get("exit_reason", "") for row in rows} if key), key=lambda item: item[0])),
    }


def build_opportunity_heartbeat(state_dir: str | Path) -> dict[str, Any]:
    """Summarize persisted candidate flow; this is diagnostic only."""
    path = Path(state_dir) / "candidate_diagnostics.csv"
    rows = list(_trade_rows(path))
    counts: dict[str, Any] = {"evaluated": len(rows), "data_invalid": 0, "contract_invalid": 0, "no_trade": 0, "eligible": 0, "other": 0}
    reason_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        decision = str(row.get("decision", "") or "").upper()
        if decision == "DATA_INVALID":
            counts["data_invalid"] += 1
        elif decision == "CONTRACT_INVALID":
            counts["contract_invalid"] += 1
        elif decision == "NO_TRADE":
            counts["no_trade"] += 1
        elif decision in {"TRADE", "ELIGIBLE", "PAPER_ELIGIBLE"}:
            counts["eligible"] += 1
        else:
            counts["other"] += 1
        for token in str(row.get("reasons", "") or "").replace("|", ";").split(";"):
            token = token.strip()
            if token:
                reason_counts[token[:120]] += 1
    counts["top_rejection_reasons"] = [{"reason": key, "count": value} for key, value in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))[:8]]
    counts["status"] = "FEED_OR_GATE_BLOCKED" if counts["data_invalid"] > max(counts["no_trade"], counts["eligible"]) else ("OPPORTUNITIES_PRESENT" if counts["eligible"] else "NO_QUALIFYING_OPPORTUNITY")
    return counts


def build_evidence_snapshot(state_dir: str | Path, min_sample: int = 30) -> dict[str, Any]:
    root = Path(state_dir)
    rows = list(_trade_rows(root / "trades.csv"))
    calibration_rows = list(_trade_rows(root / "paper_calibration_trades.csv"))
    known_ids = {str(row.get("trade_id", "")) for row in rows}
    for row in calibration_rows:
        trade_id = str(row.get("trade_id", ""))
        if trade_id not in known_ids:
            row["entry_mode"] = "PAPER_CALIBRATION"
            rows.append(row)
            known_ids.add(trade_id)
        else:
            for existing in rows:
                if str(existing.get("trade_id", "")) == trade_id and not existing.get("entry_mode"):
                    existing["entry_mode"] = "PAPER_CALIBRATION"
    by_lane: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_underlying: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        lane = row.get("entry_mode") or "LEGACY_UNKNOWN"
        underlying = row.get("underlying") or "UNKNOWN"
        by_lane[lane].append(row)
        by_underlying[underlying].append(row)
    return {
        "status": "OK" if rows else "WARMUP_NO_TRADES",
        "min_sample_for_calibration": min_sample,
        "total": _stats(rows, min_sample),
        "by_lane": {key: _stats(value, min_sample) for key, value in sorted(by_lane.items())},
        "by_underlying": {key: _stats(value, min_sample) for key, value in sorted(by_underlying.items())},
        "session_integrity": scan_session_integrity(root),
        "calibration_gate_updates_allowed": all(len(value) >= min_sample for value in by_lane.values()) and bool(rows),
    }
