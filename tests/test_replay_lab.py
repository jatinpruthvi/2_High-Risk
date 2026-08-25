"""Tests for the session replay lab: cycle-accurate replay client and the
offline replay of a captured session through the real runner pipeline."""

import gzip
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
from pathlib import Path

from institutional_options.config import SystemConfig
from institutional_options.fyers_client import FyersInstrument, FyersSymbolMaster
from institutional_options.operator_controls import DEFAULT_IV_CONTEXT, DailyModeDecision, MarketContextDecision
from institutional_options.replay_lab import SessionReplayClient, replay_session

IST = timezone(timedelta(hours=5, minutes=30))
SYM = "NSE:NIFTY50-INDEX"


def make_chain_payload(spot=25000.0, prem=100.0):
    chain = [{
        "option_type": "", "strike_price": -1, "ltp": spot, "bid": 0, "ask": 0,
        "fyToken": "101000000026000", "symbol": SYM, "description": "NIFTY50-INDEX",
    }]
    for offset in (-300, -200, -100, 0, 100, 200, 300):
        strike = spot + offset
        k = 1.0 + abs(offset) / 400.0
        for opt in ("CE", "PE"):
            bid = max(0.5, prem / k - 0.3)
            ask = bid + 0.6
            chain.append({
                "option_type": opt, "strike_price": strike, "ltp": (bid + ask) / 2,
                "bid": bid, "ask": ask, "fyToken": f"tok-{strike}-{opt}",
                "symbol": f"NSE:NIFTY26AUG{int(strike)}{opt}", "description": "",
            })
    return {"s": "ok", "data": {
        "callOi": 1, "putOi": 1,
        "indiavixData": {"ltp": 13.5, "symbol": "NSE:INDIAVIX-INDEX"},
        "expiryData": [
            {"date": "25-08-2026", "expiry": "1787652600", "expiry_flag": "M"},
            {"date": "29-09-2026", "expiry": "1790676600", "expiry_flag": "M"},
        ],
        "optionsChain": chain,
    }}


def history_rising(spot=25000.0, bars=15):
    out = []
    t = 1786000000
    px = spot * 0.98
    for i in range(bars):
        px *= 1.0012
        out.append([t + i * 60, round(px, 2), round(px * 1.0005, 2),
                    round(px * 0.9995, 2), round(px, 2), 1000])
    return out


def make_master():
    insts = []
    for offset in (-300, -200, -100, 0, 100, 200, 300):
        strike = 25000.0 + offset
        for opt in ("CE", "PE"):
            insts.append(FyersInstrument(
                fyers_symbol=f"NSE:NIFTY26AUG{int(strike)}{opt}", token=f"t{strike}{opt}",
                underlying="NIFTY", expiry_date=__import__("datetime").date(2026, 8, 25),
                expiry_ts=1787652600, strike=strike, option_type=opt,
                lot_size=65, tick_size=0.05,
            ))
    return FyersSymbolMaster(insts)


def make_depth_payload(symbol: str, ltt: int = 1786509000) -> dict:
    return {"s": "ok", "d": {symbol: {
        "bids": [{"price": 99.0 - i * 0.05, "volume": 100 + i * 50, "ord": i + 1} for i in range(5)],
        "ask": [{"price": 100.0 + i * 0.05, "volume": 150 + i * 50, "ord": i + 1} for i in range(5)],
        "ltp": 99.5, "ltt": ltt,
    }}}


def make_record(i: int, include_depth: bool = False) -> dict:
    ts = (datetime(2026, 8, 12, 10, 0, tzinfo=IST) + timedelta(seconds=5 * i)).isoformat()
    record = {"ts": ts, "chains": {SYM: make_chain_payload()},
              "history": {SYM: history_rising()}}
    if include_depth:
        record["depth"] = {}
        for row in record["chains"][SYM]["data"]["optionsChain"]:
            if row.get("option_type") in {"CE", "PE"} and row.get("symbol"):
                record["depth"][row["symbol"]] = make_depth_payload(row["symbol"], int(datetime.fromisoformat(ts).timestamp()))
    return record


class ReplayClientTests(unittest.TestCase):
    def test_client_advances_per_cycle(self):
        records = [make_record(0), make_record(1), make_record(2)]
        client = SessionReplayClient(records, [SYM])
        p0 = client.option_chain(SYM)
        h0 = client.history(SYM)
        p1 = client.option_chain(SYM)   # symbol repeats -> next cycle
        h1 = client.history(SYM)
        self.assertIs(p0, records[0]["chains"][SYM])
        self.assertIs(h0, records[0]["history"][SYM])
        self.assertIs(p1, records[1]["chains"][SYM])
        self.assertIs(h1, records[1]["history"][SYM])
        self.assertEqual(client.cycles_run, 1)

    def test_depth_replays_when_captured_and_fails_closed_when_legacy(self):
        captured = make_record(0, include_depth=True)
        legacy = make_record(1, include_depth=False)
        client = SessionReplayClient([captured, legacy], [SYM])
        symbol = captured["chains"][SYM]["data"]["optionsChain"][1]["symbol"]
        self.assertEqual(client.market_depth(symbol)["s"], "ok")
        client.option_chain(SYM)  # mark the current cycle as served
        client.option_chain(SYM)  # repeat advances to legacy record
        response = client.market_depth(symbol)
        self.assertEqual(response["s"], "error")


class ReplaySessionTests(unittest.TestCase):
    def test_replay_uses_captured_depth_in_candidate_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            session = tmp / "depth_sess.jsonl.gz"
            with gzip.open(session, "wt", encoding="utf-8") as f:
                for i in range(3):
                    f.write(json.dumps(make_record(i, include_depth=True)) + "\n")
            out = tmp / "depth_out"
            cfg = SystemConfig.from_file("uploads/PARAMETERS.json")
            with mock.patch(
                "institutional_options.paper_runner.load_daily_mode",
                return_value=DailyModeDecision("NORMAL", "NORMAL", "APPLIED", "test", "test"),
            ), mock.patch(
                "institutional_options.paper_runner.load_market_context",
                return_value=MarketContextDecision(dict(DEFAULT_IV_CONTEXT), "APPLIED", "test", "test", "2026-08-12", "2026-08-12T15:30:00+05:30", "test"),
            ), mock.patch(
                "institutional_options.paper_runner.PaperRunner._risk_context_block_reason",
                return_value="",
            ):
                runner = replay_session(
                    session, runner_cfg={
                        "poll_seconds": 0.01, "strikecount": 12,
                        "underlyings": {"NIFTY": {"index_symbol": SYM, "prefer_monthly": False}},
                    }, state_dir=out, master=make_master(), config=cfg)
            snapshot = runner.snapshot()
            depth_health = snapshot["underlyings"]["NIFTY"]["depth_health"]
            self.assertEqual(depth_health["status"], "APPLIED")
            self.assertEqual(depth_health["successful_legs"], 6)
            self.assertEqual(depth_health["five_level_legs"], 6)

    def test_replay_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            session = tmp / "sess.jsonl.gz"
            n = 20
            with gzip.open(session, "wt", encoding="utf-8") as f:
                for i in range(n):
                    f.write(json.dumps(make_record(i)) + "\n")
            out = tmp / "out"
            cfg = SystemConfig.from_file("uploads/PARAMETERS.json")
            runner = replay_session(
                session, runner_cfg={
                    "poll_seconds": 0.01, "strikecount": 12,
                    "underlyings": {"NIFTY": {"index_symbol": SYM, "prefer_monthly": False}},
                }, state_dir=out, master=make_master(), config=cfg)
            snap = runner.snapshot()
            self.assertEqual(runner.client.cycles_run, n - 1)
            self.assertIn("NIFTY", snap["underlyings"])
            self.assertTrue(snap["last_cycle_ok"])
            self.assertTrue((out / "trades.csv").exists())
            self.assertTrue((out / "skipped.csv").exists())


if __name__ == "__main__":
    unittest.main()
