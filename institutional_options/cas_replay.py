"""Offline replay/reporting for CAS anomaly evidence.

This utility never generates orders. It reports only what the captured evidence
supports: executable top-book scenarios versus theoretical or unverifiable
prints.
"""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any


def replay_cas_events(path: str | Path) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    with Path(path).open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    executable = [row for row in rows if row.get("execution_status") == "EXECUTABLE"]
    unverifiable = [row for row in rows if row.get("execution_status") != "EXECUTABLE"]
    return {
        "event_count": len(rows),
        "executable_event_count": len(executable),
        "unverifiable_event_count": len(unverifiable),
        "by_underlying": dict(Counter(row.get("underlying", "") for row in rows)),
        "by_execution_status": dict(Counter(row.get("execution_status", "UNVERIFIABLE") for row in rows)),
        "executable_events": executable,
        "theoretical_only_events": unverifiable,
        "paper_only": True,
        "orders_placed": 0,
    }


def write_replay_report(input_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    report = replay_cas_events(input_path)
    Path(output_path).write_text(__import__("json").dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report
