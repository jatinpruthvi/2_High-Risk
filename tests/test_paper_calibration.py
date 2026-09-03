from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from institutional_options.config import SystemConfig
from institutional_options.engine import PaperOpportunityEngine, PaperPortfolioState
from institutional_options.models import CandidateInputs, DataHealth, Greeks, InstrumentSpec, Moneyness, OptionType, PaperFill, PaperTrade, Quote
from institutional_options.option_chain import OptionChainSnapshot, OptionLeg, OptionStrike
from institutional_options.orchestrators import DataHealthOrchestrator
from institutional_options.paper_evidence import PaperEvidenceCollector
from institutional_options.paper_runner import ClosedTradeRecord, OpenPosition, PaperRunner, RunnerState


class PaperCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.root = root
        cls.base = SystemConfig.from_file(root / "uploads" / "PARAMETERS.json")
        cls.runner_cfg = json.loads((root / "uploads" / "PAPER_RUNNER.json").read_text(encoding="utf-8"))

    def _candidate(self, source_timestamp_available=True, valid=True):
        now = datetime.now(timezone.utc)
        quote = Quote(
            bid=100.0, ask=100.5, bid_qty=200, ask_qty=200, last=100.25,
            timestamp=now, cumulative_bid_qty_5depth=1000,
            cumulative_ask_qty_5depth=1000,
            source_timestamp_available=source_timestamp_available,
        )
        instrument = InstrumentSpec(
            underlying="SENSEX", security_id="TEST", instrument="TESTCE",
            expiry=date.today(), lot_size=20, tick_size=0.05, strike=78000,
            option_type=OptionType.CE, exchange="BSE", instrument_kind="INDEX",
            instrument_class="BSE_INDEX",
        )
        return CandidateInputs(
            instrument=instrument, quote=quote, moneyness=Moneyness.ATM,
            greeks=Greeks(), data_health=DataHealth(valid), futures_price=78000,
            underlying_price=78000, instrument_direction_score=10.0,
            trade_quality_score=75.0, regime_confidence=60.0,
            market_hostility_score=20.0, iv_crush_risk_score=30.0,
            premium_elasticity=0.50, expected_move=120.0, required_move=100.0,
            required_stop_points=5.0, convexity_edge_score=70.0,
            execution_quality_score=75.0, opportunity_confidence_score=70.0,
            regime_fit_score=60.0, candidate_created_at=now,
            lifecycle_state="TRADE_ELIGIBLE", exposure_group="SENSEX",
            setup_grade="",
        )

    def test_calibration_engine_is_explicit_and_can_select_a_safe_proxy_candidate(self):
        runner = SimpleNamespace(cfg=self.runner_cfg, config=self.base, _paper_calibration_cfg=lambda: self.runner_cfg["paper_calibration"])
        engine = PaperRunner._build_paper_calibration_engine(runner)
        self.assertIsNotNone(engine)
        result = engine.evaluate_and_select(
            [self._candidate()],
            state=PaperPortfolioState(open_positions_count=0, pending_orders_count=0, realized_loss_today=0.0),
        )
        detail = result.evaluations[0] if result.evaluations else None
        self.assertTrue(result.selected is not None, (detail.reasons, detail.comparable_opportunity_score, detail.dynamic_excellent_threshold, detail.grade) if detail else result.reasons)
        self.assertTrue(result.selected.eligible)
        self.assertEqual(result.selected.candidate.instrument.underlying, "SENSEX")

    def _timestamp_mismatch_chain(self, now):
        ce_quote = Quote(100.0, 100.5, 200, 200, 100.25, now, 1000, 1000, True)
        pe_quote = Quote(101.0, 101.5, 200, 200, 101.25, now, 1000, 1000, True)
        ce = OptionLeg(78000.0, OptionType.CE, "CE", ce_quote, Greeks(), None, 100, 90, 10, 8, source_timestamp=now)
        pe = OptionLeg(78000.0, OptionType.PE, "PE", pe_quote, Greeks(), None, 100, 90, 10, 8, source_timestamp=now - timedelta(seconds=5))
        return OptionChainSnapshot("SENSEX", 78000.0, date.today().isoformat(), now, (OptionStrike(78000.0, ce, pe),))

    def _calibration_runner(self):
        runner = SimpleNamespace(
            cfg=self.runner_cfg,
            config=self.base,
            _paper_calibration_cfg=lambda: self.runner_cfg["paper_calibration"],
            data_health=DataHealthOrchestrator(self.base),
        )
        runner.paper_calibration_engine = PaperRunner._build_paper_calibration_engine(runner)
        runner.paper_calibration_data_health = DataHealthOrchestrator(runner.paper_calibration_engine.config)
        return runner

    def test_chain_timestamp_mismatch_is_calibration_warning_but_canonical_block(self):
        runner = self._calibration_runner()
        now = datetime.now(timezone.utc)
        chain = self._timestamp_mismatch_chain(now)
        calibration_health = PaperRunner._evaluate_chain_health(runner, chain, scope="calibration", now=now)
        canonical_health = PaperRunner._evaluate_chain_health(runner, chain, scope="trade", now=now)
        self.assertTrue(calibration_health.valid)
        self.assertTrue(calibration_health.warning)
        self.assertIn("Calibration warning", calibration_health.reason)
        self.assertFalse(canonical_health.valid)
        self.assertIn("CE/PE timestamp delta", canonical_health.reason)

    def test_calibration_clone_uses_45_second_freshness_without_mutating_canonical(self):
        runner = self._calibration_runner()
        data_health = runner.paper_calibration_engine.config.section("data_health")
        revalidation = runner.paper_calibration_engine.config.section("candidate_revalidation")
        self.assertEqual(data_health["option_quote_stale_invalid_sec"], 45.0)
        self.assertEqual(data_health["option_chain_invalid_sec"], 45.0)
        self.assertEqual(revalidation["normal_market_max_candidate_age_sec"], 45.0)
        self.assertEqual(revalidation["fast_market_max_candidate_age_sec"], 45.0)
        self.assertEqual(self.base.section("data_health")["option_quote_stale_invalid_sec"], 8.0)
        self.assertEqual(self.base.section("data_health")["option_chain_invalid_sec"], 30.0)

    def test_calibration_health_keeps_stale_quote_and_zero_depth_as_hard_failures(self):
        runner = self._calibration_runner()
        now = datetime.now(timezone.utc)
        health = DataHealthOrchestrator(runner.paper_calibration_engine.config)
        stale = self._candidate()
        stale_quote = Quote(100.0, 100.5, 200, 200, 100.25, now - timedelta(seconds=46), 1000, 1000, True)
        stale = stale.__class__(**{**stale.__dict__, "quote": stale_quote})
        stale_health = health.evaluate_candidate(stale, now)
        self.assertFalse(stale_health.valid)
        zero_depth_quote = Quote(100.0, 100.5, 0, 200, 100.25, now, 1000, 1000, True)
        zero_depth = self._candidate()
        zero_depth = zero_depth.__class__(**{**zero_depth.__dict__, "quote": zero_depth_quote})
        zero_depth_health = health.evaluate_candidate(zero_depth, now)
        self.assertFalse(zero_depth_health.valid)
        self.assertIn("depth unavailable", zero_depth_health.reason)

    def test_calibration_lane_rejects_missing_source_timestamp(self):
        runner = SimpleNamespace(cfg=self.runner_cfg, config=self.base, _paper_calibration_cfg=lambda: self.runner_cfg["paper_calibration"])
        engine = PaperRunner._build_paper_calibration_engine(runner)
        candidate = self._candidate(source_timestamp_available=False)
        # The runner's safe-candidate filter is intentionally stricter than the
        # relaxed signal scorer and must remain fail-closed.
        safe = candidate.data_health.valid and candidate.quote.is_valid() and candidate.quote.bid_qty > 0 and candidate.quote.ask_qty > 0 and candidate.quote.source_timestamp_available
        self.assertFalse(safe)

    def test_canonical_thresholds_and_paper_limits_are_unchanged(self):
        self.assertEqual(self.base.section("opportunity_selection")["require_premium_elasticity_min"], 1.0)
        self.assertEqual(self.base.section("opportunity_selection")["require_expected_required_ratio_min"], 1.6)
        self.assertFalse(self.base.section("execution")["live_trading_enabled"])
        universe = self.base.section("instrument_universe")
        self.assertEqual(universe["max_open_positions"], 1)
        self.assertEqual(universe["max_pending_orders"], 1)
        cal = self.runner_cfg["paper_calibration"]
        self.assertTrue(cal["enabled"])
        self.assertTrue(cal["research_only"])
        self.assertEqual(cal["max_entries_per_day"], 4)
        self.assertEqual(cal["max_quote_age_seconds"], 45.0)
        self.assertEqual(cal["max_chain_age_seconds"], 45.0)
        self.assertEqual(cal["max_candidate_age_seconds"], 45.0)
        self.assertTrue(cal["allow_chain_semantic_warnings"])

    def test_paper_position_checkpoint_round_trips_for_restart_safe_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime.now(timezone.utc)
            quote = Quote(100.0, 100.5, 200, 200, 100.25, now, 1000, 1000, True)
            instrument = SimpleNamespace(
                underlying="SENSEX", security_id="TEST", instrument="BSE:SENSEX26AUG77200CE",
                expiry=date.today(), lot_size=20, tick_size=0.05, strike=77200.0,
                option_type=OptionType.CE, freeze_qty=None, buy_sell_allowed=True,
                exchange="BSE", instrument_kind="INDEX", instrument_class="BSE_INDEX",
            )
            candidate = SimpleNamespace(
                instrument=instrument, side=OptionType.CE, notes={"entry_mode": "PAPER_CALIBRATION"},
                lifecycle_state="PAPER_ELIGIBLE", exposure_group="INDEX:BROAD_EQUITY",
            )
            evaluation = SimpleNamespace(
                candidate=candidate,
                risk_plan=SimpleNamespace(planned_risk=100.0),
                comparable_opportunity_score=58.0,
            )
            fill = PaperFill(filled=True, fill_price=100.5, limit_price=100.5, slippage_buffer=0.0, reason="")
            trade = PaperTrade(
                trade_id="checkpoint-test", entry_evaluation=evaluation,
                entry_fill=fill, entry_time=now,
            )
            position = OpenPosition(
                trade=trade, symbol=instrument.instrument, underlying="SENSEX",
                expiry=date.today().isoformat(), stop_points=10.0, target_points=20.0,
                max_duration_seconds=900, opened_at=now, last_premium=100.5,
                highest_premium=101.0, lowest_premium=100.0, last_quote=quote,
                entry_mode="PAPER_CALIBRATION",
            )
            path = Path(tmp) / "paper_open_position.json"
            writer = SimpleNamespace(_open_position_path=path, state=SimpleNamespace(open_position=position), _log=lambda *_args, **_kwargs: None)
            PaperRunner._save_open_position_checkpoint(writer, position)
            self.assertTrue(path.exists())
            reader = PaperRunner.__new__(PaperRunner)
            reader._open_position_path = path
            reader.state = RunnerState()
            reader.universe = {"SENSEX": {"trade_enabled": True}}
            reader._log = lambda *_args, **_kwargs: None
            PaperRunner._restore_open_position(reader)
            restored = reader.state.open_position
            self.assertIsNotNone(restored)
            self.assertEqual(restored.trade.trade_id, "checkpoint-test")
            self.assertEqual(restored.entry_mode, "PAPER_CALIBRATION")
            self.assertEqual(restored.trade.entry_fill.fill_price, 100.5)
            self.assertEqual(restored.trade.entry_evaluation.candidate.instrument.strike, 77200.0)
            self.assertEqual(restored.highest_premium, 101.0)

    def test_paper_position_checkpoint_round_trips_for_restart_safe_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime.now(timezone.utc)
            quote = Quote(100.0, 100.5, 200, 200, 100.25, now, 1000, 1000, True)
            instrument = SimpleNamespace(
                underlying="SENSEX", security_id="TEST", instrument="BSE:SENSEX26AUG77200CE",
                expiry=date.today(), lot_size=20, tick_size=0.05, strike=77200.0,
                option_type=OptionType.CE, freeze_qty=None, buy_sell_allowed=True,
                exchange="BSE", instrument_kind="INDEX", instrument_class="BSE_INDEX",
            )
            candidate = SimpleNamespace(
                instrument=instrument, side=OptionType.CE, notes={"entry_mode": "PAPER_CALIBRATION"},
                lifecycle_state="PAPER_ELIGIBLE", exposure_group="INDEX:BROAD_EQUITY",
            )
            evaluation = SimpleNamespace(
                candidate=candidate,
                risk_plan=SimpleNamespace(planned_risk=100.0),
                comparable_opportunity_score=58.0,
            )
            fill = PaperFill(filled=True, fill_price=100.5, limit_price=100.5, slippage_buffer=0.0, reason="")
            trade = PaperTrade(
                trade_id="checkpoint-test", entry_evaluation=evaluation,
                entry_fill=fill, entry_time=now,
            )
            position = OpenPosition(
                trade=trade, symbol=instrument.instrument, underlying="SENSEX",
                expiry=date.today().isoformat(), stop_points=10.0, target_points=20.0,
                max_duration_seconds=900, opened_at=now, last_premium=100.5,
                highest_premium=101.0, lowest_premium=100.0, last_quote=quote,
                entry_mode="PAPER_CALIBRATION",
            )
            path = Path(tmp) / "paper_open_position.json"
            writer = SimpleNamespace(
                _open_position_path=path,
                state=SimpleNamespace(open_position=position),
                _log=lambda *_args, **_kwargs: None,
                _checkpoint_quote_payload=PaperRunner._checkpoint_quote_payload,
            )
            PaperRunner._save_open_position_checkpoint(writer, position)
            self.assertTrue(path.exists())
            reader = PaperRunner.__new__(PaperRunner)
            reader._open_position_path = path
            reader.state = RunnerState()
            reader.universe = {"SENSEX": {"trade_enabled": True}}
            reader._log = lambda *_args, **_kwargs: None
            PaperRunner._restore_open_position(reader)
            restored = reader.state.open_position
            self.assertIsNotNone(restored)
            self.assertEqual(restored.trade.trade_id, "checkpoint-test")
            self.assertEqual(restored.entry_mode, "PAPER_CALIBRATION")
            self.assertEqual(restored.trade.entry_fill.fill_price, 100.5)
            self.assertEqual(restored.trade.entry_evaluation.candidate.instrument.strike, 77200.0)
            self.assertEqual(restored.highest_premium, 101.0)

    def test_calibration_trade_is_separate_from_canonical_mtil(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = PaperEvidenceCollector(tmp)
            rec = ClosedTradeRecord(
                trade_id="cal-test", underlying="SENSEX", side="CE", expiry=str(date.today()), strike=78000,
                entry_time="t1", exit_time="t2", entry_fill=100.5, exit_fill=102.0,
                exit_reason="TARGET", gross_points=1.5, gross_pnl=30.0, costs=0.0,
                net_pnl=30.0, hold_seconds=60, max_adverse_points=0.5,
                max_favorable_points=1.5, entry_mode="PAPER_CALIBRATION",
            )
            collector.record_calibration_trade(rec, cost_model_valid=False)
            self.assertTrue((Path(tmp) / "paper_calibration_trades.csv").exists())
            self.assertFalse((Path(tmp) / "mtil.csv").exists())
            text = (Path(tmp) / "paper_calibration_trades.csv").read_text(encoding="utf-8")
            self.assertIn("PAPER_CALIBRATION", text)
            self.assertIn("False", text)


if __name__ == "__main__":
    unittest.main()
