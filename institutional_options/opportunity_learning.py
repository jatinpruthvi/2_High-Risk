from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .models import OptionType


class OpportunityLearningLedger:
    """Paper-only ledger for qualified opportunities and later executable outcomes."""

    BUCKETS = ((60, "1m"), (300, "5m"), (900, "15m"), (1800, "30m"))

    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir)
        self.state_path = self.state_dir / "opportunity_learning_state.json"
        self.outcome_path = self.state_dir / "forward_outcomes.csv"
        self.state: dict[str, Any] = self._load()
        self.state.setdefault("active", {})
        self.state.setdefault("coverage", {})
        self.state.setdefault("last_update", "")
        self._write_header()

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write_header(self) -> None:
        if self.outcome_path.exists() and self.outcome_path.stat().st_size:
            return
        fields = ["key", "underlying", "side", "strike", "lane", "bucket", "observed_at", "entry_ask", "exit_bid", "exit_ask", "executable_pnl_per_unit", "theoretical_pnl_per_unit", "quote_age_seconds", "paper_only"]
        with self.outcome_path.open("w", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=fields).writeheader()

    @staticmethod
    def session_phase(ts: datetime) -> str:
        minutes = ts.hour * 60 + ts.minute
        if minutes < 555:
            return "PREOPEN"
        if 555 <= minutes < 915:
            return "CONTINUOUS"
        if 915 <= minutes <= 930:
            return "CAS_WINDOW"
        if minutes > 930:
            return "POST_CAS"
        return "OUT_OF_SESSION"

    def process_qualified(self, rows: list[dict[str, Any]], ts: datetime) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for row in rows:
            key = "|".join(str(row.get(field, "")) for field in ("underlying", "side", "expiry", "strike", "lane"))
            previous = self.state["active"].get(key)
            if previous is None:
                arm_state = "QUALIFIED"
                first_seen = ts.isoformat()
                armed_at = ""
            else:
                arm_state = "ARMED" if previous.get("state") in {"QUALIFIED", "ARMED"} else "QUALIFIED"
                first_seen = previous.get("first_seen", ts.isoformat())
                armed_at = previous.get("armed_at", "")
                if arm_state == "ARMED" and not armed_at:
                    armed_at = ts.isoformat()
            bid = float(row.get("bid") or 0)
            ask = float(row.get("ask") or 0)
            break_even_points = max(0.0, ask - bid)
            break_even_pct = (100.0 * break_even_points / ask) if ask > 0 else None
            enriched = dict(row)
            enriched.update({
                "state": arm_state,
                "first_seen_at": first_seen,
                "armed_at": armed_at,
                "session_phase": self.session_phase(ts),
                "break_even_move_points": round(break_even_points, 4),
                "break_even_move_pct": round(break_even_pct, 4) if break_even_pct is not None else None,
                "paper_only": True,
            })
            self.state["active"][key] = {
                **(previous if isinstance(previous, Mapping) else {}),
                **enriched,
                "key": key,
                "entry_ask": ask,
                "outcomes": dict((previous or {}).get("outcomes", {})),
            }
            output.append(enriched)
        self.state["last_update"] = ts.isoformat()
        self._save()
        return output

    def update_forward_outcomes(self, chains: Mapping[str, Any], ts: datetime) -> None:
        fields = ["key", "underlying", "side", "strike", "lane", "bucket", "observed_at", "entry_ask", "exit_bid", "exit_ask", "executable_pnl_per_unit", "theoretical_pnl_per_unit", "quote_age_seconds", "paper_only"]
        new_rows: list[dict[str, Any]] = []
        for key, record in list(self.state["active"].items()):
            try:
                first = datetime.fromisoformat(str(record["first_seen_at"]))
                elapsed = max(0.0, (ts - first).total_seconds())
                chain = chains.get(str(record.get("underlying")))
                if chain is None:
                    continue
                option = OptionType.CE if str(record.get("side")) == "CE" else OptionType.PE
                leg = chain.leg_at(float(record.get("strike")), option)
                quote = leg.quote
                if quote.bid <= 0 or quote.ask <= 0:
                    continue
                for seconds, bucket in self.BUCKETS:
                    if elapsed < seconds or bucket in record.get("outcomes", {}):
                        continue
                    entry_ask = float(record.get("entry_ask") or 0)
                    exit_bid = float(quote.bid)
                    exit_ask = float(quote.ask)
                    exit_mid = float(quote.mid)
                    row = {
                        "key": key, "underlying": record.get("underlying", ""), "side": record.get("side", ""),
                        "strike": record.get("strike", ""), "lane": record.get("lane", ""), "bucket": bucket,
                        "observed_at": ts.isoformat(), "entry_ask": entry_ask, "exit_bid": exit_bid, "exit_ask": exit_ask,
                        "executable_pnl_per_unit": round(exit_bid - entry_ask, 4),
                        "theoretical_pnl_per_unit": round(exit_mid - entry_ask, 4),
                        "quote_age_seconds": getattr(quote, "age_seconds", lambda _ts: None)(ts), "paper_only": True,
                    }
                    new_rows.append(row)
                    record.setdefault("outcomes", {})[bucket] = row
            except (AttributeError, KeyError, TypeError, ValueError):
                continue
        if new_rows:
            with self.outcome_path.open("a", encoding="utf-8", newline="") as handle:
                csv.DictWriter(handle, fieldnames=fields).writerows(new_rows)
        self.state["last_update"] = ts.isoformat()
        self._save()

    def update_coverage(self, configured: list[str], observed: Mapping[str, Any], ts: datetime) -> None:
        for underlying in configured:
            item = self.state["coverage"].setdefault(underlying, {"cycles": 0, "observed_cycles": 0, "last_observed_at": ""})
            item["cycles"] += 1
            if underlying in observed:
                item["observed_cycles"] += 1
                item["last_observed_at"] = ts.isoformat()
        self.state["last_update"] = ts.isoformat()
        self._save()

    def snapshot(self) -> dict[str, Any]:
        active = list(self.state.get("active", {}).values())
        return {
            "status": "ACTIVE",
            "paper_only": True,
            "active_candidates": len(active),
            "armed_candidates": sum(1 for item in active if item.get("state") == "ARMED"),
            "forward_outcome_records": sum(len(item.get("outcomes", {})) for item in active),
            "coverage": self.state.get("coverage", {}),
            "last_update": self.state.get("last_update", ""),
            "sample_policy": {"minimum_comparable_trades": 30, "calibration_updates_allowed": False},
            "recent_candidates": active[-50:],
        }

    def _save(self) -> None:
        self.state_path.write_text(json.dumps(self.state, indent=2, default=str), encoding="utf-8")
