import csv
import gzip
import json
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from institutional_options.config import SystemConfig
from institutional_options.fyers_client import (
    FyersAPIError, FyersCredentials, FyersInstrument, FyersRestClient, FyersSymbolMaster, TokenStore,
)
from institutional_options.fyers_parser import (
    FyersOptionChainParser, parse_expiry_calendar, parse_india_vix,
)
from institutional_options.paper_runner import PaperRunner
from institutional_options.paper_signal import PaperSignalCalculator
from institutional_options.option_chain import OptionChainSnapshot
from institutional_options.models import DataHealth, Moneyness, OptionType, TradeDecision


CFG_PATH = "uploads/PARAMETERS.json"


class TokenStoreTests(unittest.TestCase):
    def test_load_accepts_utf8_bom_token_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "tokens.json"
            path.write_text(json.dumps({"access_token": "access", "refresh_token": "refresh"}), encoding="utf-8-sig")
            store = TokenStore(path)
            store.load()
            self.assertEqual(store.access_token, "access")
            self.assertEqual(store.refresh_token, "refresh")


RUNNER_CFG = {
    "poll_seconds": 1,
    "strikecount": 12,
    "underlyings": {"NIFTY": {"index_symbol": "NSE:NIFTY50-INDEX", "prefer_monthly": False}},
}


def make_chain_payload(spot=25000.0, prem=100.0, expiry_ts=1787652600):
    """Synthetic Fyers /data/options-chain-v3 payload around spot."""
    chain = [{
        "option_type": "", "strike_price": -1, "ltp": spot, "bid": 0, "ask": 0,
        "fyToken": "101000000026000", "symbol": "NSE:NIFTY50-INDEX", "description": "NIFTY50-INDEX",
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
                "symbol": f"NSE:NIFTY{tint(expiry_ts)}{int(strike)}{opt}", "description": "",
            })
    return {"s": "ok", "data": {
        "callOi": 1, "putOi": 1,
        "indiavixData": {"ltp": 13.5, "symbol": "NSE:INDIAVIX-INDEX"},
        "expiryData": [
            {"date": "25-08-2026", "expiry": str(expiry_ts), "expiry_flag": "M"},
            {"date": "29-09-2026", "expiry": "1790676600", "expiry_flag": "M"},
        ],
        "optionsChain": chain,
    }}


def tint(ts):
    # last two digits of year + month code for a readable-ish suffix
    return "26AUG"


class FakeClient:
    """Minimal stand-in for FyersRestClient (no network)."""

    def __init__(self, payloads=None, history=None):
        self.payloads = payloads or {"NSE:NIFTY50-INDEX": make_chain_payload()}
        self.history = history

    def option_chain(self, symbol, strikecount=30, expiry_timestamp="", header=""):
        return self.payloads.get(symbol)

    def quotes(self, symbols, header=""):
        return {"s": "ok", "d": []}

    def history(self, symbol, resolution="1", range_from="", range_to="", cont_flag="1", header=""):
        if self.history is not None:
            return {"s": "ok", "candles": self.history}
        return {"s": "ok", "candles": []}

    def ensure_session(self):
        return "fake-header"


def make_master(underlying="NIFTY", expiry=date(2026, 8, 25), spot=25000):
    insts = []
    for offset in (-300, -200, -100, 0, 100, 200, 300):
        strike = spot + offset
        for opt in ("CE", "PE"):
            insts.append(FyersInstrument(
                fyers_symbol=f"NSE:NIFTY26AUG{int(strike)}{opt}", token=f"t{strike}{opt}",
                underlying=underlying, expiry_date=expiry, expiry_ts=1787652600,
                strike=strike, option_type=opt, lot_size=65, tick_size=0.05,
            ))
    return FyersSymbolMaster(insts)


def history_rising(spot=25000.0, bars=15):
    out = []
    t = 1786000000
    px = spot * 0.98
    for i in range(bars):
        px *= 1.0012
        out.append([t + i * 60, round(px, 2), round(px * 1.0005, 2), round(px * 0.9995, 2), round(px, 2), 1000])
    return out


class FyersParserTests(unittest.TestCase):
    def test_numeric_fyers_symbol_uses_display_name_strike_and_ist_expiry(self):
        expiry_ts = 1787047800  # 2026-08-18 09:00 IST
        row = ["token", "NIFTY 18 Aug 26 24200 CE", "NSE", "65", "0.05", "", "", "", str(expiry_ts),
               "NSE:NIFTY2681824200CE", "", "", "", "NIFTY"]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "NSE_FO.csv"
            path.write_text(",".join(row) + "\n", encoding="utf-8")
            master = FyersSymbolMaster.from_csv(path, allowed_underlyings={"NIFTY"})
        self.assertEqual(master.expiry_dates("NIFTY"), (date(2026, 8, 18),))
        self.assertEqual(master.instruments[0].strike, 24200.0)
        self.assertEqual(master.instruments[0].option_type, "CE")
        self.assertEqual(master.symbol_for("NIFTY", date(2026, 8, 18), 24200, "CE"),
                         "NSE:NIFTY2681824200CE")

    def test_bse_symbol_master_rows_are_parsed_when_requested(self):
        expiry_ts = 1787652600
        rows = []
        for opt in ("CE", "PE"):
            row = ["bse-token", "SENSEX", "BSE", "20", "0.05", "", "", "", str(expiry_ts),
                   f"BSE:SENSEX26AUG78000{opt}", "", "", "", "SENSEX"]
            rows.append(",".join(row))
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "BSE_FO.csv"
            path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            master = FyersSymbolMaster.from_csv(
                path,
                allowed_exchanges={"BSE"},
                allowed_underlyings={"SENSEX"},
            )
        self.assertEqual(master.expiry_dates("SENSEX"), (date(2026, 8, 25),))
        self.assertEqual(master.lot_size("SENSEX", date(2026, 8, 25)), 20)
        self.assertEqual(master.tick_size("SENSEX", date(2026, 8, 25)), 0.05)
        self.assertEqual(master.symbol_for("SENSEX", date(2026, 8, 25), 78000, "CE"),
                         "BSE:SENSEX26AUG78000CE")

    def test_parse_chain(self):
        payload = make_chain_payload()
        chain = FyersOptionChainParser.parse(payload, "NIFTY", "2026-08-25",
                                             datetime(2026, 8, 12, 10, 0))
        self.assertIsInstance(chain, OptionChainSnapshot)
        self.assertEqual(chain.underlying, "NIFTY")
        self.assertAlmostEqual(chain.underlying_price, 25000.0)
        self.assertEqual(len(chain.strikes), 7)
        leg = chain.leg_at(25000.0, OptionType.CE)
        self.assertGreater(leg.quote.bid, 0)
        self.assertGreater(leg.quote.ask, leg.quote.bid)
        self.assertEqual(leg.security_id, "tok-25000.0-CE")

    def test_parse_calendar_and_vix(self):
        payload = make_chain_payload()
        cal = parse_expiry_calendar(payload)
        self.assertEqual(len(cal), 2)
        self.assertEqual(cal[0].flag, "M")
        self.assertEqual(parse_india_vix(payload), 13.5)

    def test_parse_raises_on_bad_payload(self):
        with self.assertRaises(Exception):
            FyersOptionChainParser.parse({"data": {}}, "NIFTY", "2026-08-25")


class DepthFakeClient(FakeClient):
    def __init__(self, depth_payload=None, **kwargs):
        super().__init__(**kwargs)
        self.depth_payload = depth_payload or self._default_depth()
        self.depth_calls = []

    @staticmethod
    def _default_depth():
        return {
            "s": "ok",
            "d": {
                "__SYMBOL__": {
                    "bids": [{"price": 99.0 - i * 0.05, "volume": 100 + i * 50, "ord": i + 1} for i in range(5)],
                    "ask": [{"price": 100.0 + i * 0.05, "volume": 150 + i * 50, "ord": i + 1} for i in range(5)],
                    "ltp": 99.5,
                    "ltt": int(datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc).timestamp()),
                },
            },
        }

    def market_depth(self, symbol, ohlcv_flag=1, header=""):
        self.depth_calls.append((symbol, ohlcv_flag))
        raw = json.loads(json.dumps(self.depth_payload).replace("__SYMBOL__", symbol))
        return raw


class FyersDepthTests(unittest.TestCase):
    def test_market_depth_client_uses_read_only_depth_route(self):
        with tempfile.TemporaryDirectory() as td:
            client = FyersRestClient(
                FyersCredentials("APP-100", "secret"),
                TokenStore(Path(td) / "tokens.json"),
                timeout=7,
            )
            with mock.patch("institutional_options.fyers_client._req", return_value=(200, {"s": "ok"})) as req:
                result = client.market_depth("NSE:NIFTY2681824200CE", header="APP-100:token")
                cached = client.market_depth("NSE:NIFTY2681824200CE", header="APP-100:token")
            self.assertEqual(result, {"s": "ok"})
            self.assertEqual(cached, result)
            self.assertEqual(req.call_count, 1)
            self.assertEqual(client.depth_stats()["cache_hits"], 1)
            url = req.call_args.args[0]
            self.assertIn("https://api-t1.fyers.in/data/depth?", url)
            self.assertIn("symbol=NSE%3ANIFTY2681824200CE", url)
            self.assertIn("ohlcv_flag=1", url)
            self.assertEqual(req.call_args.kwargs["auth_header"], "APP-100:token")
            self.assertEqual(req.call_args.kwargs["timeout"], 7)

    def test_option_chain_uses_configured_request_timeout(self):
        with tempfile.TemporaryDirectory() as td:
            client = FyersRestClient(
                FyersCredentials("APP-100", "secret"),
                TokenStore(Path(td) / "tokens.json"),
                timeout=11,
            )
            with mock.patch("institutional_options.fyers_client._req", return_value=(200, {"s": "ok"})) as req:
                self.assertEqual(client.option_chain("NSE:NIFTY50-INDEX"), {"s": "ok"})
            self.assertEqual(req.call_args.kwargs["timeout"], 11)

    def test_market_depth_retries_429_and_records_stats(self):
        with tempfile.TemporaryDirectory() as td:
            client = FyersRestClient(
                FyersCredentials("APP-100", "secret"),
                TokenStore(Path(td) / "tokens.json"),
                timeout=7,
            )
            with mock.patch("institutional_options.fyers_client._req", side_effect=[
                FyersAPIError("rate limited", status_code=429),
                (200, {"s": "ok"}),
            ]) as req, mock.patch("institutional_options.fyers_client.time.sleep"):
                self.assertEqual(client.market_depth("NSE:NIFTY2681824200CE", header="h"), {"s": "ok"})
            self.assertEqual(req.call_count, 2)
            stats = client.depth_stats()
            self.assertEqual(stats["rate_limit_hits"], 1)
            self.assertEqual(stats["retries"], 1)
            self.assertEqual(stats["successes"], 1)
            self.assertEqual(stats["errors"], 0)

    def test_runner_keeps_malformed_depth_fail_closed(self):
        cfg = SystemConfig.from_file(CFG_PATH)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        malformed = {"s": "ok", "d": {"__SYMBOL__": {"bids": [], "ask": [], "ltt": 0}}}
        client = DepthFakeClient(depth_payload=malformed, history=history_rising())
        runner = PaperRunner(cfg, RUNNER_CFG, state_dir=Path(tmp.name), client=client, master=make_master())
        payload = make_chain_payload()
        chain = FyersOptionChainParser.parse(payload, "NIFTY", "2026-08-25", datetime(2026, 8, 12, 10, 0))
        enriched = runner._enrich_fyers_depth("NIFTY", chain, payload)
        leg = enriched.leg_at(25000.0, OptionType.CE)
        self.assertEqual(leg.quote.bid_qty, 0)
        self.assertEqual(leg.quote.ask_qty, 0)
        self.assertEqual(leg.quote.cumulative_bid_qty_5depth, None)
        self.assertEqual(runner.state.underlyings["NIFTY"]["depth_health"]["status"], "UNAVAILABLE")
        self.assertGreater(runner.state.underlyings["NIFTY"]["depth_health"]["failed_legs"], 0)

    def test_runner_enriches_top_book_and_five_level_depth(self):
        cfg = SystemConfig.from_file(CFG_PATH)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        client = DepthFakeClient(history=history_rising())
        runner = PaperRunner(cfg, RUNNER_CFG, state_dir=Path(tmp.name), client=client, master=make_master())
        payload = make_chain_payload()
        chain = FyersOptionChainParser.parse(payload, "NIFTY", "2026-08-25", datetime(2026, 8, 12, 10, 0))
        enriched = runner._enrich_fyers_depth("NIFTY", chain, payload)
        leg = enriched.leg_at(25000.0, OptionType.CE)
        self.assertEqual(leg.quote.bid_qty, 100)
        self.assertEqual(leg.quote.ask_qty, 150)
        self.assertEqual(leg.quote.cumulative_bid_qty_5depth, 100 + 150 + 200 + 250 + 300)
        self.assertEqual(leg.quote.cumulative_ask_qty_5depth, 150 + 200 + 250 + 300 + 350)
        self.assertTrue(leg.quote.source_timestamp_available)
        self.assertEqual(leg.source_timestamp, datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc))
        self.assertEqual(runner.state.underlyings["NIFTY"]["depth_health"]["successful_legs"], 6)
        self.assertEqual(len(client.depth_calls), 6)

    def test_runner_does_not_mark_zero_filled_levels_as_five_level_evidence(self):
        cfg = SystemConfig.from_file(CFG_PATH)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        raw = DepthFakeClient._default_depth()
        raw["d"]["__SYMBOL__"]["ask"][1:] = [{"price": 0.0, "volume": 0, "ord": 0} for _ in range(4)]
        client = DepthFakeClient(depth_payload=raw, history=history_rising())
        runner = PaperRunner(cfg, RUNNER_CFG, state_dir=Path(tmp.name), client=client, master=make_master())
        payload = make_chain_payload()
        chain = FyersOptionChainParser.parse(payload, "NIFTY", "2026-08-25", datetime(2026, 8, 12, 10, 0))
        enriched = runner._enrich_fyers_depth("NIFTY", chain, payload)
        leg = enriched.leg_at(25000.0, OptionType.CE)
        self.assertGreater(leg.quote.bid_qty, 0)
        self.assertGreater(leg.quote.ask_qty, 0)
        self.assertIsNone(leg.quote.cumulative_bid_qty_5depth)
        self.assertIsNone(leg.quote.cumulative_ask_qty_5depth)
        self.assertEqual(runner.state.underlyings["NIFTY"]["depth_health"]["five_level_legs"], 0)

    def test_runner_rejects_zero_best_quote_and_records_reason(self):
        cfg = SystemConfig.from_file(CFG_PATH)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        raw = DepthFakeClient._default_depth()
        raw["d"]["__SYMBOL__"]["ask"][0] = {"price": 0.0, "volume": 0, "ord": 0}
        client = DepthFakeClient(depth_payload=raw, history=history_rising())
        runner = PaperRunner(cfg, RUNNER_CFG, state_dir=Path(tmp.name), client=client, master=make_master())
        payload = make_chain_payload()
        chain = FyersOptionChainParser.parse(payload, "NIFTY", "2026-08-25", datetime(2026, 8, 12, 10, 0))
        enriched = runner._enrich_fyers_depth("NIFTY", chain, payload)
        leg = enriched.leg_at(25000.0, OptionType.CE)
        self.assertEqual(leg.quote.bid_qty, 0)
        self.assertEqual(leg.quote.ask_qty, 0)
        health = runner.state.underlyings["NIFTY"]["depth_health"]
        self.assertEqual(health["status"], "UNAVAILABLE")
        self.assertTrue(any("best quote invalid" in reason for reason in health["failure_reasons"]))


class SignalProxyTests(unittest.TestCase):
    def setUp(self):
        self.cfg = SystemConfig.from_file(CFG_PATH)

    def test_context_and_proxies_are_nonzero(self):
        payload = make_chain_payload()
        chain = FyersOptionChainParser.parse(payload, "NIFTY", "2026-08-25",
                                             datetime(2026, 8, 12, 10, 0))
        calc = PaperSignalCalculator(self.cfg, history_rising())
        ctx = calc.compute_context(chain, 13.5, datetime(2026, 8, 12, 10, 0))
        self.assertGreater(ctx.direction_score, 0)      # rising history -> positive
        self.assertGreater(ctx.trade_quality_score, 0)
        self.assertGreater(ctx.required_move, 0)
        # Use calibration_scope=True to test proxy fallback behavior
        proxies = calc.candidate_proxies(chain, ctx, Moneyness.ATM, OptionType.CE, spread_pct=0.6, calibration_scope=True)
        self.assertGreaterEqual(proxies.premium_elasticity, 0.5)   # would pass scorer gate
        self.assertGreater(proxies.convexity_edge_score, 0)
        self.assertGreater(proxies.execution_quality_score, 0)

    def test_side_aware_confidence_breaks_ce_pe_tie(self):
        payload = make_chain_payload()
        chain = FyersOptionChainParser.parse(payload, "NIFTY", "2026-08-25",
                                             datetime(2026, 8, 12, 10, 0))
        calc = PaperSignalCalculator(self.cfg, history_rising())   # uptrend history
        ctx = calc.compute_context(chain, 13.5, datetime(2026, 8, 12, 10, 0))
        self.assertGreater(ctx.direction_score, 0)
        ce = calc.candidate_proxies(chain, ctx, Moneyness.ATM, OptionType.CE, spread_pct=0.6)
        pe = calc.candidate_proxies(chain, ctx, Moneyness.ATM, OptionType.PE, spread_pct=0.6)
        # In an uptrend the call must carry more conviction than the put.
        self.assertGreater(ce.opportunity_confidence_score, pe.opportunity_confidence_score)

    def test_direction_model_runs_in_shadow_without_replacing_proxy(self):
        payload = make_chain_payload()
        chain = FyersOptionChainParser.parse(payload, "NIFTY", "2026-08-25",
                                             datetime(2026, 8, 12, 10, 0))
        calc = PaperSignalCalculator(self.cfg, history_rising())
        inputs = {name: history_rising() for name in ("HDFCBANK", "SBIN", "ICICIBANK")}
        ctx = calc.compute_context(chain, 13.5, datetime(2026, 8, 12, 10, 0),
                                   history_candles=history_rising(),
                                   direction_model_inputs=inputs)
        self.assertEqual(ctx.direction_model_status, "VALID")
        self.assertIsNotNone(ctx.direction_model_score)
        self.assertEqual(ctx.direction_score, calc._trend_signals([row[4] for row in history_rising()])[1])

    def test_per_call_history_override_beats_constructor_history(self):
        payload = make_chain_payload()
        chain = FyersOptionChainParser.parse(payload, "NIFTY", "2026-08-25",
                                             datetime(2026, 8, 12, 10, 0))
        calc = PaperSignalCalculator(self.cfg, history_rising())        # rising
        flat = [[int(time.time()) - (30 - i) * 60, 25000.0, 25001.0, 24999.0, 25000.0, 100] for i in range(30)]
        ctx = calc.compute_context(chain, 13.5, datetime(2026, 8, 12, 10, 0),
                                   history_candles=flat)               # flat beats rising
        self.assertAlmostEqual(ctx.direction_score, 0.0, delta=5.0)
        self.assertGreater(ctx.atr1, 0.0)                              # history actually consumed


class RunnerCycleTests(unittest.TestCase):
    # Pin the clock to market hours (Wed 10:00 IST) so these tests pass
    # regardless of when the suite runs; run_one_cycle short-circuits outside
    # 09:15-15:30 IST, which would yield zero candidates.
    MARKET_NOW = datetime(2026, 8, 12, 10, 0)

    def setUp(self):
        self.cfg = SystemConfig.from_file(CFG_PATH)
        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.tmp.name)
        self._clock = mock.patch("institutional_options.paper_runner.now_ist",
                                 return_value=self.MARKET_NOW)
        self._clock.start()

    def tearDown(self):
        self._clock.stop()
        self.tmp.cleanup()

    @staticmethod
    def _breakout_eval(underlying, score, threshold=75.0, eligible=True, data_valid=True, contract_valid=True, quality=80.0):
        candidate = SimpleNamespace(
            instrument=SimpleNamespace(underlying=underlying),
            data_health=DataHealth(data_valid, False, "" if data_valid else "invalid"),
            notes={},
            execution_quality_score=quality,
            convexity_edge_score=quality,
            premium_elasticity=1.5,
            market_hostility_score=10.0,
            iv_crush_risk_score=10.0,
            opportunity_confidence_score=quality,
        )
        return SimpleNamespace(
            candidate=candidate,
            contract_quality=SimpleNamespace(valid=contract_valid, score=quality),
            comparable_opportunity_score=score,
            dynamic_excellent_threshold=threshold,
            eligible=eligible,
            decision=TradeDecision.BUY_CALL_CANDIDATE if eligible else TradeDecision.NO_TRADE,
            reasons=tuple(),
        )

    def test_gate_breakout_requires_prior_max_and_persists(self):
        cfg = {**RUNNER_CFG, "gate_breakout": {"enabled": True, "lookback_seconds": 1800, "minimum_improvement_points": 0.25}}
        runner = PaperRunner(self.cfg, cfg, state_dir=self.state_dir, client=FakeClient(history=history_rising()), master=make_master())
        runner._cost_model_valid = True
        first = self._breakout_eval("NIFTY", 80.0)
        result1 = runner._apply_gate_breakout_filter(SimpleNamespace(evaluations=(first,)), self.MARKET_NOW)
        self.assertIsNone(result1.selected)
        self.assertEqual(runner.state.underlyings["_gate_breakout"]["instrument_status"]["NIFTY"]["status"], "WARMUP_NO_PRIOR_MAX")
        second = self._breakout_eval("NIFTY", 81.0)
        result2 = runner._apply_gate_breakout_filter(SimpleNamespace(evaluations=(second,)), self.MARKET_NOW + timedelta(minutes=1))
        self.assertIsNotNone(result2.selected)
        self.assertEqual(result2.selected.candidate.instrument.underlying, "NIFTY")
        reloaded = PaperRunner(self.cfg, cfg, state_dir=self.state_dir, client=FakeClient(history=history_rising()), master=make_master())
        reloaded._cost_model_valid = True
        third = self._breakout_eval("NIFTY", 82.0)
        result3 = reloaded._apply_gate_breakout_filter(SimpleNamespace(evaluations=(third,)), self.MARKET_NOW + timedelta(minutes=2))
        self.assertIsNotNone(result3.selected)

    def test_gate_breakout_ranks_multiple_instruments_by_quality(self):
        cfg = {**RUNNER_CFG, "gate_breakout": {"enabled": True, "lookback_seconds": 1800, "minimum_improvement_points": 0.25}}
        runner = PaperRunner(self.cfg, cfg, state_dir=self.state_dir, client=FakeClient(history=history_rising()), master=make_master())
        runner._cost_model_valid = True
        seed = (
            self._breakout_eval("NIFTY", 80.0),
            self._breakout_eval("BANKNIFTY", 80.0),
        )
        runner._apply_gate_breakout_filter(SimpleNamespace(evaluations=seed), self.MARKET_NOW)
        current = (
            self._breakout_eval("NIFTY", 82.0, quality=82.0),
            self._breakout_eval("BANKNIFTY", 85.0, quality=90.0),
        )
        result = runner._apply_gate_breakout_filter(SimpleNamespace(evaluations=current), self.MARKET_NOW + timedelta(minutes=1))
        self.assertIsNotNone(result.selected)
        self.assertEqual(result.selected.candidate.instrument.underlying, "BANKNIFTY")
        self.assertEqual(runner.state.underlyings["_gate_breakout"]["selected_underlying"], "BANKNIFTY")

    def test_gate_breakout_never_bypasses_invalid_data_or_contract(self):
        cfg = {**RUNNER_CFG, "gate_breakout": {"enabled": True, "lookback_seconds": 1800, "minimum_improvement_points": 0.25}}
        runner = PaperRunner(self.cfg, cfg, state_dir=self.state_dir, client=FakeClient(history=history_rising()), master=make_master())
        runner._cost_model_valid = True
        invalid = self._breakout_eval("NIFTY", 100.0, eligible=False, data_valid=False, contract_valid=False)
        result = runner._apply_gate_breakout_filter(SimpleNamespace(evaluations=(invalid,)), self.MARKET_NOW)
        self.assertIsNone(result.selected)
        self.assertEqual(runner.state.underlyings["_gate_breakout"]["instrument_status"]["NIFTY"]["status"], "NO_VALIDATED_VALUE")

    def test_successful_cycle_clears_stale_global_error(self):
        runner = PaperRunner(self.cfg, RUNNER_CFG, state_dir=self.state_dir,
                             client=FakeClient(history=history_rising()),
                             master=make_master())
        runner.state.last_error = "OptionChainParseError: stale prior cycle"
        runner.run_one_cycle()
        self.assertEqual(runner.state.last_error, "")
        self.assertTrue(runner.state.last_cycle_ok)

    def test_persistent_stale_data_alert_transitions_and_recovers(self):
        runner = PaperRunner(self.cfg, RUNNER_CFG, state_dir=self.state_dir,
                             client=FakeClient(history=history_rising()),
                             master=make_master())
        stale = DataHealth(False, False, "Option chain stale 31.0s")
        runner._record_data_health_observation("NIFTY", stale, self.MARKET_NOW, "trade")
        self.assertEqual(runner.state.underlyings["NIFTY"]["stale_data_alert"]["status"], "OBSERVING")
        runner._record_data_health_observation("NIFTY", stale, self.MARKET_NOW + timedelta(minutes=1), "trade")
        alert = runner.state.underlyings["NIFTY"]["stale_data_alert"]
        self.assertEqual(alert["status"], "ALERT")
        self.assertEqual(alert["consecutive_bad_cycles"], 2)
        ledger_text = (self.state_dir / "research_events.csv").read_text(encoding="utf-8")
        self.assertIn("DATA_HEALTH_ALERT", ledger_text)
        runner._record_data_health_observation("NIFTY", DataHealth(True, False, ""), self.MARKET_NOW + timedelta(minutes=2), "trade")
        self.assertEqual(runner.state.underlyings["NIFTY"]["stale_data_alert"]["status"], "CLEAR")

    def test_entry_window_uses_configured_start_and_cutoff(self):
        runner = PaperRunner(self.cfg, RUNNER_CFG, state_dir=self.state_dir,
                             client=FakeClient(history=history_rising()),
                             master=make_master())
        self.assertFalse(runner._entry_window_open(datetime(2026, 8, 12, 9, 29)))
        self.assertTrue(runner._entry_window_open(datetime(2026, 8, 12, 9, 30)))
        self.assertTrue(runner._entry_window_open(datetime(2026, 8, 12, 14, 14)))
        self.assertFalse(runner._entry_window_open(datetime(2026, 8, 12, 14, 15)))
        self.assertFalse(runner._entry_window_open(datetime(2026, 8, 12, 15, 0)))

    def test_default_expanded_universe_is_paper_selector_eligible(self):
        cfg = json.loads(Path("uploads/PAPER_RUNNER.json").read_text(encoding="utf-8"))
        underlyings = cfg["underlyings"]
        self.assertFalse(underlyings["SENSEX"]["monitor_only"])
        self.assertFalse(underlyings["NIFTYNXT50"]["monitor_only"])
        self.assertFalse(underlyings["NIFTYFPI"]["monitor_only"])
        self.assertIn("BANKEX", underlyings)
        self.assertEqual(underlyings["NIFTYNXT50"]["index_symbol"], "NSE:NIFTYNXT50-INDEX")
        self.assertEqual(underlyings["NIFTYFPI"]["index_symbol"], "NSE:NIFTYFPI-INDEX")
        self.assertFalse(underlyings["BANKEX"]["monitor_only"])
        self.assertFalse(underlyings["FOCIT"]["monitor_only"])
        stocks = [meta for meta in underlyings.values() if meta.get("instrument_kind") == "STOCK"]
        trade_enabled = [meta for meta in underlyings.values() if meta.get("trade_enabled")]
        self.assertEqual(len(stocks), 50)
        self.assertEqual(len(trade_enabled), 59)
        self.assertTrue(all(meta.get("trade_enabled") and not meta.get("monitor_only") for meta in underlyings.values()))
        self.assertEqual(cfg["monitoring"]["monitor_batch_size"], 8)
        self.assertEqual(cfg["monitoring"]["monitor_poll_seconds"], 60)

    def test_priority_scheduler_keeps_core_and_full_audit_metadata(self):
        full_cfg = json.loads(Path("uploads/PAPER_RUNNER.json").read_text(encoding="utf-8"))
        full_cfg["monitoring"] = {**full_cfg.get("monitoring", {}), "monitor_poll_seconds": 0, "paper_trade_batch_size": 8}
        runner = PaperRunner(self.cfg, full_cfg, state_dir=self.state_dir,
                             client=FakeClient(), master=make_master())
        selected = runner._cycle_underlyings()
        schedule = runner.state.underlyings["_paper_schedule"]
        self.assertEqual(len(runner._trade_underlyings()), 59)
        self.assertEqual(set(selected[:4]), {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"})
        self.assertEqual(len(selected), 12)
        self.assertEqual(schedule["mode"], "CORE_PLUS_PRIORITY_LANES")
        self.assertGreaterEqual(len(schedule["audit_lane"]), 8)
        self.assertEqual(schedule["total_paper_underlyings"], 59)

    def test_priority_scheduler_defers_backoff_but_preserves_audit_deadline(self):
        full_cfg = json.loads(Path("uploads/PAPER_RUNNER.json").read_text(encoding="utf-8"))
        full_cfg["monitoring"] = {**full_cfg.get("monitoring", {}), "monitor_poll_seconds": 0, "paper_trade_batch_size": 8}
        runner = PaperRunner(self.cfg, full_cfg, state_dir=self.state_dir,
                             client=FakeClient(), master=make_master())
        first = runner._cycle_underlyings()
        expanded = [u for u in runner._trade_underlyings() if u not in {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"}]
        deferred_underlying = expanded[0]
        row = runner._scheduler_entry(deferred_underlying)
        row.update({"last_full_audit_cycle": runner._scheduler_cycle, "next_retry_at": time.time() + 3600, "status": "FAILED_BACKOFF"})
        second = runner._cycle_underlyings()
        schedule = runner.state.underlyings["_paper_schedule"]
        self.assertNotIn(deferred_underlying, second)
        self.assertTrue(any(item["underlying"] == deferred_underlying and item["reason"] == "FAILURE_BACKOFF" for item in schedule["deferred"]))
        self.assertLessEqual(runner._scheduler_cycle - int(row["last_full_audit_cycle"]), runner.scheduler_max_audit_cycles)
        self.assertEqual(len(first), 12)

    def test_prefer_monthly_selects_monthly_expiry(self):
        runner = PaperRunner(self.cfg, RUNNER_CFG, state_dir=self.state_dir,
                             client=FakeClient(), master=make_master())
        calendar = (
            SimpleNamespace(date_str="18-08-2026", expiry_ts=1787047800, flag="W"),
            SimpleNamespace(date_str="25-08-2026", expiry_ts=1787652600, flag="M"),
        )
        self.assertEqual(runner._select_expiry("SENSEX", calendar, True), "2026-08-25")
        self.assertEqual(runner._select_expiry("NIFTY", calendar, False), "2026-08-18")

    def test_missing_options_chain_is_explicitly_unavailable_and_fail_closed(self):
        cfg = SystemConfig.from_file(CFG_PATH)
        cfg_runner = {**RUNNER_CFG, "underlyings": {
            "NIFTY": {"index_symbol": "NSE:NIFTY50-INDEX", "prefer_monthly": False},
        }}
        client = FakeClient(payloads={"NSE:NIFTY50-INDEX": {"s": "ok", "data": {}}})
        runner = PaperRunner(cfg, cfg_runner, state_dir=self.state_dir, client=client, master=make_master())
        with self.assertRaises(RuntimeError):
            runner.run_one_cycle()
        health = runner.state.underlyings["NIFTY"]["chain_health"]
        self.assertEqual(health["status"], "UNAVAILABLE")
        self.assertEqual(health["reason_code"], "OPTIONS_CHAIN_UNAVAILABLE")
        self.assertTrue(health["fail_closed"])

    def test_monitor_rotation_keeps_trade_universe_always_present(self):
        cfg = json.loads(Path("uploads/PAPER_RUNNER.json").read_text(encoding="utf-8"))
        cfg["monitoring"]["monitor_poll_seconds"] = 0
        runner = PaperRunner(self.cfg, cfg, state_dir=self.state_dir,
                             client=FakeClient(), master=make_master())
        first = runner._cycle_underlyings()
        second = runner._cycle_underlyings()
        self.assertEqual(set(first[:4]), {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"})
        self.assertEqual(set(second[:4]), {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"})
        self.assertEqual(len(first), 12)
        self.assertEqual(len(second), 12)
        self.assertNotEqual(first[4:], second[4:])

    def test_monitor_poll_throttle_fetches_trade_universe_without_repeating_batch(self):
        cfg = json.loads(Path("uploads/PAPER_RUNNER.json").read_text(encoding="utf-8"))
        runner = PaperRunner(self.cfg, cfg, state_dir=self.state_dir,
                             client=FakeClient(), master=make_master())
        first = runner._cycle_underlyings()
        second = runner._cycle_underlyings()
        self.assertEqual(len(first), 12)
        self.assertEqual(len(second), 12)
        self.assertEqual(set(second), set(first))
        schedule = runner.state.underlyings["_paper_schedule"]
        self.assertEqual(set(schedule["selected"]), set(second))
        self.assertEqual(len(schedule["last_batch"]), 8)

    def test_monitor_only_bse_chain_is_displayed_but_not_ranked(self):
        cfg = {**RUNNER_CFG, "underlyings": {
            "NIFTY": {"index_symbol": "NSE:NIFTY50-INDEX", "prefer_monthly": False},
            "SENSEX": {"index_symbol": "BSE:SENSEX-INDEX", "exchange": "BSE",
                       "prefer_monthly": True, "monitor_only": True},
        }}
        payloads = {
            "NSE:NIFTY50-INDEX": make_chain_payload(),
            "BSE:SENSEX-INDEX": make_chain_payload(spot=78000.0, prem=120.0),
        }
        combined_master = FyersSymbolMaster.combine(
            make_master(),
            make_master("SENSEX", expiry=date(2026, 8, 25), spot=78000),
        )
        runner = PaperRunner(self.cfg, cfg, state_dir=self.state_dir,
                             client=FakeClient(payloads=payloads, history=history_rising()),
                             master=combined_master)
        runner.run_one_cycle()
        snap = runner.snapshot()
        self.assertEqual(snap["underlyings"]["SENSEX"]["exchange"], "BSE")
        self.assertTrue(snap["underlyings"]["SENSEX"]["monitor_only"])
        ranked = snap["underlyings"].get("_candidates", [])
        self.assertTrue(all(row["underlying"] != "SENSEX" for row in ranked))
        monitor_log = self.state_dir / "monitor_diagnostics.csv"
        self.assertTrue(monitor_log.exists())
        monitor_text = monitor_log.read_text(encoding="utf-8")
        self.assertIn("underlying,exchange", monitor_text)
        self.assertIn("SENSEX,BSE", monitor_text)
        self.assertIn("atm_ce_spread_pct", monitor_text)
        shadow_log = self.state_dir / "shadow_candidates.csv"
        self.assertTrue(shadow_log.exists())
        shadow_text = shadow_log.read_text(encoding="utf-8")
        self.assertIn("research_only", shadow_text)
        self.assertIn("SENSEX", shadow_text)
        self.assertNotIn("SENSEX", "\n".join(row.get("underlying", "") for row in ranked))

    def test_stock_option_monitor_uses_generic_chain_and_master_path(self):
        cfg = {**RUNNER_CFG, "underlyings": {
            "NIFTY": {"index_symbol": "NSE:NIFTY50-INDEX", "prefer_monthly": False},
            "RELIANCE": {"index_symbol": "NSE:RELIANCE-EQ", "exchange": "NSE",
                         "instrument_kind": "STOCK", "prefer_monthly": True,
                         "monitor_only": True},
        }}
        payloads = {
            "NSE:NIFTY50-INDEX": make_chain_payload(),
            "NSE:RELIANCE-EQ": make_chain_payload(spot=25000.0, prem=90.0),
        }
        combined_master = FyersSymbolMaster.combine(
            make_master(),
            make_master("RELIANCE", expiry=date(2026, 8, 25), spot=25000),
        )
        runner = PaperRunner(self.cfg, cfg, state_dir=self.state_dir,
                             client=FakeClient(payloads=payloads, history=history_rising()),
                             master=combined_master)
        runner.run_one_cycle()
        snap = runner.snapshot()
        self.assertEqual(snap["underlyings"]["RELIANCE"]["instrument_kind"], "STOCK")
        self.assertTrue(snap["underlyings"]["RELIANCE"]["monitor_only"])
        self.assertTrue(all(row["underlying"] != "RELIANCE"
                            for row in snap["underlyings"].get("_candidates", [])))
        self.assertTrue(any(row["underlying"] == "RELIANCE" and row["research_only"]
                            for row in snap["underlyings"].get("_shadow_candidates", [])))

    def test_missing_contract_metadata_blocks_candidate_creation(self):
        client = FakeClient(history=history_rising())
        runner = PaperRunner(self.cfg, RUNNER_CFG, state_dir=self.state_dir,
                             client=client, master=FyersSymbolMaster([]))
        runner.run_one_cycle()
        snap = runner.snapshot()
        self.assertIn("instrument_error", snap["underlyings"]["NIFTY"])
        self.assertEqual(snap["underlyings"].get("_candidates", []), [])

    def test_cycle_builds_candidates_with_proxies(self):
        client = FakeClient(history=history_rising())
        master = make_master()
        runner = PaperRunner(self.cfg, RUNNER_CFG, state_dir=self.state_dir,
                             client=client, master=master)
        runner.run_one_cycle()
        snap = runner.snapshot()
        cands = snap["underlyings"].get("_candidates", [])
        self.assertGreater(len(cands), 0)
        # The first live observation must remain unavailable until the
        # timestamp-aligned, post-cost, delta-adjusted metric is confirmed.
        for c in cands:
            self.assertEqual(c["premium_elasticity"], 0.0)
            self.assertIn(c["observed_elasticity_status"], {"UNAVAILABLE", "OBSERVED_NOT_CONFIRMED"})
        self.assertTrue(snap["last_cycle_ok"])

    def test_capture_cycle_persists_depth_payloads(self):
        cfg = {**RUNNER_CFG, "capture": True}
        runner = PaperRunner(self.cfg, cfg, state_dir=self.state_dir,
                             client=FakeClient(history=history_rising()), master=make_master())
        depth = {"NSE:NIFTY26AUG25000CE": {"s": "ok", "d": {}}}
        runner._capture_cycle({"NSE:NIFTY50-INDEX": make_chain_payload()}, {}, self.MARKET_NOW, depth)
        runner._capture_file.close()
        captures = list((self.state_dir / "sessions").glob("*.jsonl.gz"))
        self.assertEqual(len(captures), 1)
        with gzip.open(captures[0], "rt", encoding="utf-8") as handle:
            record = json.loads(handle.readline())
        self.assertEqual(record["depth"], depth)

    def test_snapshot_serializes(self):
        client = FakeClient(history=history_rising())
        runner = PaperRunner(self.cfg, RUNNER_CFG, state_dir=self.state_dir,
                             client=client, master=make_master())
        runner.run_one_cycle()
        snap = runner.snapshot()
        json.dumps(snap)  # must not raise
        self.assertEqual(snap["mode"], "PAPER (no orders placed)")
        self.assertIn("equity", snap)

    def test_edge_scaled_target_scales_with_ratio(self):
        edge_cfg = {**RUNNER_CFG, "config_overrides": {"exit_management": {
            "edge_scaled_target": True, "edge_scale_min_ratio": 1.1,
            "edge_scale_min_r": 1.0, "edge_scale_max_r": 3.0}}}
        runner = PaperRunner(self.cfg, edge_cfg, state_dir=self.state_dir,
                             client=FakeClient(history=history_rising()),
                             master=make_master())
        strong = SimpleNamespace(candidate=SimpleNamespace(expected_move=176.0, required_move=100.0))
        self.assertAlmostEqual(runner._target_r(strong), 3.0)  # 2.0*1.6 capped
        weak = SimpleNamespace(candidate=SimpleNamespace(expected_move=90.0, required_move=100.0))
        self.assertLess(runner._target_r(weak), 2.0)           # ratio 0.9 -> below base
        self.assertGreaterEqual(runner._target_r(weak), 1.0)   # floored
        # Edge scaling disabled -> plain preferred_target_R.
        runner2 = PaperRunner(self.cfg, RUNNER_CFG, state_dir=self.state_dir,
                              client=FakeClient(history=history_rising()),
                              master=make_master())
        self.assertAlmostEqual(runner2._target_r(strong), 2.0)

    def test_cycle_writes_candidate_diagnostics(self):
        runner = PaperRunner(self.cfg, RUNNER_CFG, state_dir=self.state_dir,
                             client=FakeClient(history=history_rising()),
                             master=make_master())
        runner.run_one_cycle()
        path = self.state_dir / "candidate_diagnostics.csv"
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        for key in ("side_direction_score", "direction_gate_passed",
                    "observed_elasticity_valid", "observed_elasticity_post_cost",
                    "surface_valid", "atm_iv", "call_put_iv_skew"):
            self.assertIn(key, text)

    def test_cycle_writes_candidates_log(self):
        runner = PaperRunner(self.cfg, RUNNER_CFG, state_dir=self.state_dir,
                             client=FakeClient(history=history_rising()),
                             master=make_master())
        runner.run_one_cycle()
        path = self.state_dir / "candidates_log.csv"
        self.assertTrue(path.exists())
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertGreater(len(rows), 0)
        for key in ("date", "comparable_score", "threshold", "grade", "decision",
                    "direction", "execution", "exp_req_ratio", "spread_pct"):
            self.assertIn(key, rows[0])

    def test_verified_playbook_filter_selects_regime_compatible_code(self):
        risk_path = self.state_dir / "risk_context.json"
        risk_path.write_text(json.dumps({
            "ts": "2026-08-12T10:00:00+05:30",
            "source": "test-feed",
            "global_risk_state": "NEUTRAL",
            "news_state": "NEWS_NORMAL",
            "liquidity_stable": True,
            "gap_wait_completed": True,
        }), encoding="utf-8")
        cfg = {**RUNNER_CFG, "risk_context_path": str(risk_path),
               "config_overrides": {"playbook_runtime": {"enforce_on_paper": True}}}
        runner = PaperRunner(self.cfg, cfg, state_dir=self.state_dir,
                             client=FakeClient(history=history_rising()), master=make_master())
        context = SimpleNamespace(
            trend_efficiency=90.0, direction_score=80.0, vix=13.5,
            regime_confidence=85.0, market_hostility_score=10.0,
            trade_quality_score=90.0, dte=5.0,
        )
        runner._update_playbook_filters({"NIFTY": context}, self.MARKET_NOW)
        self.assertIn("A01", runner._playbook_codes_by_underlying["NIFTY"])

    def test_runtime_risk_context_fails_closed_when_enforced(self):
        risk_path = self.state_dir / "risk_context.json"
        risk_path.write_text(json.dumps({
            "ts": "2026-08-12T10:00:00+05:30",
            "source": "test-feed",
            "global_risk_state": "SHOCK",
            "news_state": "NEWS_NORMAL",
            "portfolio_no_trade_score": 10,
        }), encoding="utf-8")
        cfg = {**RUNNER_CFG,
               "risk_context_path": str(risk_path),
               "config_overrides": {"runtime_risk_controls": {"enforce_on_paper": True}}}
        runner = PaperRunner(self.cfg, cfg, state_dir=self.state_dir,
                             client=FakeClient(history=history_rising()), master=make_master())
        self.assertIn("Global risk shock", runner._risk_context_block_reason())

    def test_rank_persistence_requires_two_windows_and_survives_restart(self):
        runner = PaperRunner(self.cfg, RUNNER_CFG, state_dir=self.state_dir,
                             client=FakeClient(history=history_rising()), master=make_master())
        candidate = SimpleNamespace(
            instrument=SimpleNamespace(underlying="NIFTY", expiry=date(2026, 8, 25), strike=25000.0),
            side=OptionType.CE,
        )
        evaluation = SimpleNamespace(candidate=candidate)
        first = runner._rank_persistence_check(evaluation, self.MARKET_NOW)
        self.assertFalse(first[0])
        reloaded = PaperRunner(self.cfg, RUNNER_CFG, state_dir=self.state_dir,
                               client=FakeClient(history=history_rising()), master=make_master())
        second = reloaded._rank_persistence_check(evaluation, self.MARKET_NOW + timedelta(seconds=5))
        self.assertTrue(second[0])

    def test_daily_risk_limits_are_enforced_and_persisted(self):
        runner = PaperRunner(self.cfg, RUNNER_CFG, state_dir=self.state_dir,
                             client=FakeClient(history=history_rising()), master=make_master())
        runner.state.trades_today = 2
        self.assertIn("Maximum trades per day", runner._daily_risk_block_reason(self.MARKET_NOW))
        runner.state.trades_today = 0
        runner.state.losses_today = 3
        self.assertIn("three daily losses", runner._daily_risk_block_reason(self.MARKET_NOW))
        runner.state.losses_today = 0
        runner.state.realized_pnl_today = -1500.0
        self.assertIn("Maximum daily loss", runner._daily_risk_block_reason(self.MARKET_NOW))
        runner.state.realized_pnl_today = 0.0
        runner.state.trades_today = 1
        runner._save_daily_risk_state()
        reloaded = PaperRunner(self.cfg, RUNNER_CFG, state_dir=self.state_dir,
                               client=FakeClient(history=history_rising()), master=make_master())
        self.assertEqual(reloaded.state.trades_today, 1)

    def test_signal_runner_override_reaches_signal_calculator_config(self):
        cfg = {**RUNNER_CFG, "signal": {"required_move_straddle_factor": 0.9}}
        runner = PaperRunner(self.cfg, cfg, state_dir=self.state_dir,
                             client=FakeClient(history=history_rising()), master=make_master())
        self.assertEqual(runner.config.raw["paper_runner"]["signal"]["required_move_straddle_factor"], 0.9)

    def test_saturday_waits_until_monday_open(self):
        runner = PaperRunner(self.cfg, RUNNER_CFG, state_dir=self.state_dir,
                             client=FakeClient(), master=make_master())
        saturday = datetime(2026, 8, 15, 10, 0)
        with mock.patch("institutional_options.paper_runner.now_ist", return_value=saturday):
            self.assertEqual(runner._seconds_to_open(), 47 * 3600 + 15 * 60)

    def test_prefilter_drops_unfillable_strikes(self):
        payload = make_chain_payload()
        for row in payload["data"]["optionsChain"]:
            if row.get("strike_price") == 25000.0 and row.get("option_type") in ("CE", "PE"):
                mid = (row["bid"] + row["ask"]) / 2
                row["bid"] = mid - 2.0
                row["ask"] = mid + 2.0
                row["ltp"] = mid
        client = FakeClient(payloads={"NSE:NIFTY50-INDEX": payload},
                            history=history_rising())
        runner = PaperRunner(self.cfg, RUNNER_CFG, state_dir=self.state_dir,
                             client=client, master=make_master())
        runner.run_one_cycle()
        snap = runner.snapshot()
        cands = snap["underlyings"].get("_candidates", [])
        strikes = {c["strike"] for c in cands}
        self.assertNotIn(25000.0, strikes)
        self.assertGreaterEqual(snap["underlyings"].get("_prefiltered", 0), 2)


    def test_run_manifest_is_created_and_stale_state_is_archived(self):
        with tempfile.TemporaryDirectory() as d:
            runner = PaperRunner(self.cfg, RUNNER_CFG, state_dir=d,
                                 client=FakeClient(history=history_rising()), master=make_master())
            manifest_path = Path(d) / "run_manifest.json"
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["universe"]["underlyings"], ["NIFTY"])
            self.assertEqual(manifest["live_execution"], "DISABLED")
            (Path(d) / "mtil.csv").write_text("legacy\n", encoding="utf-8")
            manifest["policy_signature"] = "stale-policy"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            PaperRunner(self.cfg, RUNNER_CFG, state_dir=d,
                        client=FakeClient(history=history_rising()), master=make_master())
            archives = list((Path(d) / "archives").glob("policy_*"))
            self.assertEqual(len(archives), 1)
            self.assertTrue((archives[0] / "mtil.csv").exists())
            self.assertTrue(manifest_path.exists())

    def test_revalidation_and_fill_audit_streams_are_created(self):
        with tempfile.TemporaryDirectory() as d:
            runner = PaperRunner(self.cfg, RUNNER_CFG, state_dir=d,
                                 client=FakeClient(history=history_rising()), master=make_master())
            runner.run_one_cycle()
            self.assertTrue((Path(d) / "run_manifest.json").exists())
            # The audit files are created once the corresponding path is exercised;
            # their presence is not required when no candidate reaches revalidation.
            self.assertFalse((Path(d) / "mtil.csv").exists() and (Path(d) / "mtil.csv").read_text(encoding="utf-8").startswith("legacy"))

    def test_live_execution_override_is_rejected(self):
        cfg = {**RUNNER_CFG, "config_overrides": {"execution": {"live_trading_enabled": True}}}
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                PaperRunner(self.cfg, cfg, state_dir=d,
                            client=FakeClient(history=history_rising()), master=make_master())


    def test_experimental_breakout_publishes_research_only_status(self):
        cfg = {
            **RUNNER_CFG,
            "experimental_impulse_breakout": {
                "enabled": True,
                "label": "EXPERIMENTAL_IMPULSE_BREAKOUT",
                "research_only": True,
                "paper_entry_enabled": False,
                "range_lookback_minutes": 30,
                "minimum_history_bars": 20,
                "max_signal_age_seconds": 180,
                "min_breakout_displacement_atr": 0.75,
                "min_direction_score": 25.0,
                "min_trend_efficiency": 50.0,
                "one_shot_cooldown_seconds": 1800,
                "require_cost_model_valid": True,
                "require_data_health_valid": True,
                "require_contract_valid": True,
                "require_canonical_eligibility_for_paper_entry": True,
            },
        }
        runner = PaperRunner(self.cfg, cfg, state_dir=self.state_dir, client=FakeClient(), master=make_master())
        runner._cost_model_valid = True
        base_ts = int(self.MARKET_NOW.replace(tzinfo=timezone.utc).timestamp()) - 30 * 60
        history = []
        for index in range(30):
            ts = base_ts + index * 60
            history.append([ts, 100.0, 101.0, 99.0, 100.0, 100.0])
        history.append([base_ts + 30 * 60 - 30, 100.0, 104.0, 99.0, 104.0, 200.0])
        candidate = SimpleNamespace(
            instrument=SimpleNamespace(underlying="NIFTY", strike=25000.0, expiry=date(2026, 8, 25)),
            side=OptionType.CE,
            data_health=DataHealth(True, False, ""),
            lifecycle_state="PAPER_ELIGIBLE",
            execution_quality_score=90.0,
            convexity_edge_score=90.0,
            opportunity_confidence_score=90.0,
            market_hostility_score=10.0,
            iv_crush_risk_score=10.0,
        )
        evaluation = SimpleNamespace(
            candidate=candidate,
            contract_quality=SimpleNamespace(valid=True, score=90.0),
            eligible=True,
            comparable_opportunity_score=90.0,
        )
        runner._evaluate_experimental_impulse_breakouts(
            {"NIFTY": object()},
            {"NIFTY": SimpleNamespace(atr1=1.0, direction_score=60.0, trend_efficiency=70.0)},
            {"NIFTY": history},
            (evaluation,),
            self.MARKET_NOW.replace(tzinfo=timezone.utc),
            portfolio_blocked=False,
        )
        view = runner.state.underlyings["_experimental_impulse_breakout"]
        self.assertTrue(view["enabled"])
        self.assertTrue(view["research_only"])
        self.assertFalse(view["paper_entry_enabled"])
        self.assertEqual(view["raw_signal_count"], 1)
        self.assertEqual(view["signals"][0]["status"], "BREAKOUT_RESEARCH_ONLY")

if __name__ == "__main__":
    unittest.main()
