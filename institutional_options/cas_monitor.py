"""Paper-only Closing Auction Session anomaly monitoring.

This module observes quotes and never places orders. It deliberately separates
price-print anomalies from executable quotes so hindsight marks cannot become
paper fills or canonical strategy evidence.
"""
from __future__ import annotations

import csv
import json
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Mapping


class CasAnomalyMonitor:
    def __init__(self, state_dir: str | Path, config: Mapping[str, Any] | None = None) -> None:
        self.state_dir = Path(state_dir)
        self.config = dict(config or {})
        self.enabled = bool(self.config.get("enabled", True))
        self.start_time = self._parse_time(self.config.get("start_time", "15:05"), time(15, 5))
        self.end_time = self._parse_time(self.config.get("end_time", "15:30"), time(15, 30))
        self.min_jump_pct = float(self.config.get("min_jump_pct", 100.0))
        self.max_quote_age_seconds = float(self.config.get("max_quote_age_seconds", 5.0))
        self.state_path = self.state_dir / "cas_monitor_state.json"
        self.events_path = self.state_dir / "cas_anomalies.csv"
        self._previous: dict[str, dict[str, Any]] = self._load_state()
        self._snapshot: dict[str, Any] = {
            "enabled": self.enabled,
            "status": "INITIALIZED" if self.enabled else "DISABLED",
            "window_active": False,
            "last_observed_at": "",
            "observed_legs": 0,
            "anomaly_events": 0,
            "new_event": False,
            "last_event": {},
            "paper_only": True,
        }
        self._ensure_header()

    @staticmethod
    def _parse_time(value: Any, fallback: time) -> time:
        try:
            hour, minute = str(value).split(":", 1)
            return time(int(hour), int(minute))
        except (TypeError, ValueError):
            return fallback

    def _load_state(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            return dict(raw) if isinstance(raw, Mapping) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_state(self) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._previous, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.state_path)

    def _ensure_header(self) -> None:
        if self.events_path.exists() and self.events_path.stat().st_size:
            return
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("w", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=self._fieldnames()).writeheader()

    @staticmethod
    def _fieldnames() -> list[str]:
        return [
            "ts", "session_id", "underlying", "exchange", "expiry", "strike", "side",
            "phase", "previous_mid", "mid", "last", "bid", "ask", "jump_pct",
            "quote_age_seconds", "bid_qty", "ask_qty", "depth_evidence",
            "execution_status", "theoretical_price", "executable_buy_price",
            "executable_sell_price", "anomaly", "paper_only", "reason",
        ]

    @staticmethod
    def _quote_value(quote: Any, name: str, default: Any = None) -> Any:
        value = getattr(quote, name, default)
        return default if value is None else value

    def _window_active(self, now: datetime) -> bool:
        current = now.timetz().replace(tzinfo=None)
        return self.start_time <= current <= self.end_time

    def _is_expiry_day(self, chain: Any, now: datetime) -> bool:
        try:
            return date.fromisoformat(str(chain.expiry)[:10]) == now.date()
        except (TypeError, ValueError):
            return False

    def observe(self, chains: Mapping[str, Any], now: datetime, universe: Mapping[str, Mapping[str, Any]], session_id: str = "") -> dict[str, Any]:
        if not self.enabled:
            self._snapshot.update({"status": "DISABLED", "window_active": False, "last_observed_at": now.isoformat()})
            return self.snapshot()
        window_active = self._window_active(now)
        observed = 0
        events = 0
        last_event: dict[str, Any] = {}
        for underlying, chain in chains.items():
            meta = universe.get(underlying, {})
            if str(meta.get("exchange", "NSE")).upper() != "BSE" or not self._is_expiry_day(chain, now):
                continue
            for strike_obj in getattr(chain, "strikes", ()):
                for side in ("CE", "PE"):
                    leg = getattr(strike_obj, side.lower(), None)
                    quote = getattr(leg, "quote", None) if leg is not None else None
                    if quote is None:
                        continue
                    observed += 1
                    key = f"{underlying}|{chain.expiry}|{strike_obj.strike}|{side}"
                    mid = float(self._quote_value(quote, "mid", 0.0) or 0.0)
                    bid = float(self._quote_value(quote, "bid", 0.0) or 0.0)
                    ask = float(self._quote_value(quote, "ask", 0.0) or 0.0)
                    last_raw = self._quote_value(quote, "last")
                    last = None if last_raw is None else float(last_raw)
                    previous = self._previous.get(key, {})
                    previous_mid = float(previous.get("mid", 0.0) or 0.0)
                    jump_pct = ((mid - previous_mid) / previous_mid * 100.0) if previous_mid > 0 and mid > 0 else 0.0
                    timestamp = self._quote_value(quote, "timestamp")
                    try:
                        age = max(0.0, (now - timestamp).total_seconds()) if timestamp else None
                    except (TypeError, ValueError):
                        age = None
                    bid_qty = int(self._quote_value(quote, "bid_qty", 0) or 0)
                    ask_qty = int(self._quote_value(quote, "ask_qty", 0) or 0)
                    five_depth = self._quote_value(quote, "cumulative_bid_qty_5depth") is not None and self._quote_value(quote, "cumulative_ask_qty_5depth") is not None
                    depth_evidence = "FIVE_LEVEL" if five_depth else "TOP_BOOK_ONLY" if bid_qty > 0 and ask_qty > 0 else "UNAVAILABLE"
                    fresh = age is not None and age <= self.max_quote_age_seconds
                    executable = fresh and bid > 0 and ask >= bid and bid_qty > 0 and ask_qty > 0
                    execution_status = "EXECUTABLE" if executable else "UNVERIFIABLE"
                    anomaly = window_active and abs(jump_pct) >= self.min_jump_pct
                    reason = ""
                    if anomaly and not executable:
                        reason = "Large expiry-window repricing without fresh two-sided executable size"
                    elif anomaly:
                        reason = "Large expiry-window repricing with executable top book"
                    if anomaly:
                        row = {
                            "ts": now.isoformat(), "session_id": session_id, "underlying": underlying,
                            "exchange": meta.get("exchange", "BSE"), "expiry": str(chain.expiry),
                            "strike": strike_obj.strike, "side": side, "phase": "CAS_WINDOW",
                            "previous_mid": previous_mid, "mid": mid, "last": last, "bid": bid, "ask": ask,
                            "jump_pct": round(jump_pct, 4), "quote_age_seconds": age,
                            "bid_qty": bid_qty, "ask_qty": ask_qty, "depth_evidence": depth_evidence,
                            "execution_status": execution_status, "theoretical_price": last if last is not None else mid,
                            "executable_buy_price": ask if executable else "", "executable_sell_price": bid if executable else "",
                            "anomaly": True, "paper_only": True, "reason": reason,
                        }
                        with self.events_path.open("a", newline="", encoding="utf-8") as handle:
                            csv.DictWriter(handle, fieldnames=self._fieldnames()).writerow(row)
                        events += 1
                        last_event = row
                    self._previous[key] = {"mid": mid, "last": last, "ts": now.isoformat()}
        self._save_state()
        self._snapshot.update({
            "status": "ACTIVE" if window_active else "STANDBY",
            "window_active": window_active,
            "last_observed_at": now.isoformat(),
            "observed_legs": observed,
            "anomaly_events": int(self._snapshot.get("anomaly_events", 0)) + events,
            "new_event": bool(events),
            "last_event": last_event or self._snapshot.get("last_event", {}),
            "phase": "CAS_WINDOW" if window_active else "OUTSIDE_CAS_WINDOW",
            "paper_only": True,
        })
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        return dict(self._snapshot)
