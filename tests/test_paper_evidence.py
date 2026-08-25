import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from institutional_options.config import SystemConfig
from institutional_options.engine import PaperPortfolioState
from institutional_options.models import (
    CalibrationStatus, CandidateInputs, DataHealth, Greeks, InstrumentSpec,
    Moneyness, OptionType, PaperFill, PaperTrade, Quote,
)
from institutional_options.paper_evidence import (
    AppendingCsv, PaperEvidenceCollector, build_evidence_report,
    build_top_candidates_report,
)
from institutional_options.paper_runner import now_ist
from institutional_options.paper_signal import PaperSignalCalculator
from institutional_options.scoring import OpportunityScorer
from institutional_options.records import MTILRecordBuilder
from institutional_options.mtil import MTILField, MTILSchema
from institutional_options.option_chain import OptionChainSnapshot, OptionLeg, OptionStrike

CFG_PATH = "uploads/PARAMETERS.json"


def make_quote(mid=100.0, spread=0.6):
    return Quote(bid=mid - spread / 2, ask=mid + spread / 2, bid_qty=50, ask_qty=50,
                 last=mid, timestamp=now_ist())


def make_candidate(score_components, underlying="NIFTY", side=OptionType.CE,
                   strike=25000.0, premium=100.0):
    spec = InstrumentSpec(underlying, "sec1", "OPTIDX", date(2026, 8, 25), 65, 0.05, strike, side)
    return CandidateInputs(
        instrument=spec,
        quote=make_quote(premium),
        moneyness=Moneyness.ATM,
        greeks=Greeks(),
        data_health=DataHealth(True),
        futures_price=25000.0,
        underlying_price=25000.0,
        instrument_direction_score=score_components["direction"],
        trade_quality_score=score_components["trade_quality"],
        regime_confidence=score_components["regime_confidence"],
        market_hostility_score=score_components["hostility"],
        iv_crush_risk_score=20.0,
        premium_elasticity=score_components["elasticity"],
        expected_move=score_components["expected_move"],
        required_move=score_components["required_move"],
        expected_value_r=score_components["ev_r"],
        vol_edge_ratio=score_components["vol_edge"],
        convexity_edge_score=score_components["convexity"],
        execution_quality_score=score_components["execution"],
        opportunity_confidence_score=score_components["confidence"],
        regime_fit_score=score_components["regime_fit"],
        candidate_created_at=now_ist(),
        calibration_status_direction=CalibrationStatus.VALIDATED,
        calibration_status_liquidity=CalibrationStatus.VALIDATED,
    )


class EvidenceCsvTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_appending_csv_creates_header_and_appends(self):
        p = self.dir / "t.csv"
        csv = AppendingCsv(p)
        csv.append({"a": 1, "b": "x"})
        csv.append({"a": 2, "b": "y"})
        text = p.read_text(encoding="utf-8")
        self.assertIn("a,b", text)
        self.assertEqual(text.count("a,"), 1)  # header only once

    def test_skipped_rows_written_and_ranked(self):
        cfg = SystemConfig.from_file(CFG_PATH)
        scorer = OpportunityScorer(cfg)
        strong = make_candidate({"direction": 90, "trade_quality": 90, "regime_confidence": 80,
                                 "hostility": 10, "elasticity": 0.8, "expected_move": 200,
                                 "required_move": 100, "ratio": 2.0, "ev_r": 1.0, "vol_edge": 2.0,
                                 "convexity": 90, "execution": 90, "confidence": 90, "regime_fit": 90})
        weak = make_candidate({"direction": 10, "trade_quality": 10, "regime_confidence": 40,
                               "hostility": 60, "elasticity": 0.2, "expected_move": 50,
                               "required_move": 200, "ratio": 0.25, "ev_r": -0.5, "vol_edge": 0.5,
                               "convexity": 10, "execution": 10, "confidence": 10, "regime_fit": 10},
                              underlying="BANKNIFTY", side=OptionType.PE, strike=57800.0)
        evals = tuple(scorer.evaluate(c) for c in (strong, weak))
        col = PaperEvidenceCollector(self.dir)
        col.record_skipped(evals, ranking_cycle_id="202608121500")
        rows = list(self._csv_rows(self.dir / "skipped.csv"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["rank"], "1")   # highest score first
        self.assertGreater(float(rows[0]["OpportunityScore"]), float(rows[1]["OpportunityScore"]))
        self.assertIn("skip_id", rows[0])
        queue_rows = list(self._csv_rows(self.dir / "skipped_forward_queue.csv"))
        self.assertEqual(len(queue_rows), 2)
        self.assertIn("gate_features_json", queue_rows[0])
        self.assertIn("gate_snapshot_id", queue_rows[0])
        self.assertEqual(queue_rows[0]["instrument_id"], queue_rows[0]["underlying"])

    def test_report_builds_from_empty_state(self):
        text = build_evidence_report(self.dir, SystemConfig.from_file(CFG_PATH))
        self.assertIn("PAPER-EVIDENCE REPORT", text)
        self.assertIn("no data yet", text)

    def test_existing_csv_header_migrates_for_new_fields(self):
        path = self.dir / "legacy.csv"
        path.write_text("old,\nvalue,\n", encoding="utf-8")
        writer = AppendingCsv(path)
        writer.append({"old": "new", "parameter_profile": "PAPER_OVERRIDE"})
        rows = list(self._csv_rows(path))
        self.assertEqual(rows[0]["old"], "value")
        self.assertEqual(rows[1]["old"], "new")
        self.assertEqual(rows[1]["parameter_profile"], "PAPER_OVERRIDE")

    def test_mtil_builder_applies_schema_defaults(self):
        cfg = SystemConfig.from_file(CFG_PATH)
        candidate = make_candidate({"direction": 90, "trade_quality": 90, "regime_confidence": 80,
                                    "hostility": 10, "elasticity": 0.8, "expected_move": 200,
                                    "required_move": 100, "ratio": 2.0, "ev_r": 1.0, "vol_edge": 2.0,
                                    "convexity": 90, "execution": 90, "confidence": 90, "regime_fit": 90})
        evaluation = OpportunityScorer(cfg).evaluate(candidate)
        fill = PaperFill(True, candidate.quote.mid, None, 0.0, "")
        trade = PaperTrade("schema-test", evaluation, fill, now_ist(), exit_fill=fill,
                           exit_time=now_ist(), exit_reason="TARGET")
        schema = MTILSchema([MTILField("test", "test_float", "float", False, "", "", "", "")])
        row = MTILRecordBuilder.from_paper_trade(trade, schema=schema)
        self.assertEqual(row["test_float"], 0)

    def test_mtil_trade_row_preserves_gross_costs_and_net(self):
        cfg = SystemConfig.from_file(CFG_PATH)
        candidate = make_candidate({"direction": 90, "trade_quality": 90, "regime_confidence": 80,
                                    "hostility": 10, "elasticity": 0.8, "expected_move": 200,
                                    "required_move": 100, "ratio": 2.0, "ev_r": 1.0, "vol_edge": 2.0,
                                    "convexity": 90, "execution": 90, "confidence": 90, "regime_fit": 90})
        evaluation = OpportunityScorer(cfg).evaluate(candidate)
        fill = PaperFill(True, candidate.quote.mid, None, 0.0, "")
        trade = PaperTrade("accounting-test", evaluation, fill, now_ist(), exit_fill=fill,
                           exit_time=now_ist(), exit_reason="TARGET")
        col = PaperEvidenceCollector(self.dir)
        col.record_trade(trade, net_pnl_rupees=95.0, r_multiple=1.0,
                         gross_pnl_rupees=100.0, total_costs_rupees=5.0)
        row = list(self._csv_rows(self.dir / "mtil.csv"))[0]
        self.assertEqual(float(row["gross_pnl_rupees"]), 100.0)
        self.assertEqual(float(row["total_costs_rupees"]), 5.0)
        self.assertEqual(float(row["net_pnl_rupees"]), 95.0)
        self.assertEqual(row["mapping_validation_passed"], "False")
        self.assertEqual(row["tick_size_validation_passed"], "True")
        self.assertIn(row["entry_revalidation_passed"], {"True", "False"})
        self.assertNotIn("revalidation_passed", row)
        self.assertEqual(row["cost_model_status"], "UNSPECIFIED")
        self.assertEqual(row["elasticity_status"], "PROXY_RESEARCH_NOT_OBSERVED")
        self.assertEqual(row["data_health_valid"], "True")

    def test_record_trade_and_skipped_rows_use_runtime_versions(self):
        cfg = SystemConfig.from_file(CFG_PATH)
        candidate = make_candidate({"direction": 90, "trade_quality": 90, "regime_confidence": 80,
                                    "hostility": 10, "elasticity": 0.8, "expected_move": 200,
                                    "required_move": 100, "ratio": 2.0, "ev_r": 1.0, "vol_edge": 2.0,
                                    "convexity": 90, "execution": 90, "confidence": 90, "regime_fit": 90})
        evaluation = OpportunityScorer(cfg).evaluate(candidate)
        col = PaperEvidenceCollector(self.dir)
        col.record_skipped([evaluation], ranking_cycle_id="v-test")
        skipped = list(self._csv_rows(self.dir / "skipped.csv"))[0]
        self.assertEqual(skipped["strategy_version"], col.versions.strategy_version)
        self.assertEqual(skipped["score_version"], col.versions.score_version)
        self.assertEqual(skipped["universe_version"], col.versions.universe_version)

    def test_record_monitor_snapshot_normalizes_lots_and_preserves_unknown_metadata_as_blank(self):
        ts = now_ist()
        quote = make_quote(mid=100.0, spread=0.6)
        leg = OptionLeg(25000.0, OptionType.CE, "ce", quote, Greeks(), None, 0, 0, 0, 0, 0)
        strike = OptionStrike(25000.0, leg, None)
        chain = OptionChainSnapshot("NIFTY", 25000.0, "2026-08-25", ts, (strike,))
        context = SimpleNamespace(direction_score=60.0, trade_quality_score=70.0, market_hostility_score=10.0)
        col = PaperEvidenceCollector(self.dir)
        col.record_monitor_snapshot("NIFTY", "NSE", chain, context, None, lot_size=65,
                                    lifecycle_state="SHADOW", ts=ts)
        row = list(self._csv_rows(self.dir / "monitor_diagnostics.csv"))[0]
        self.assertAlmostEqual(float(row["atm_ce_top_book_lots"]), 50.0 / 65.0)
        self.assertEqual(row["lifecycle_state"], "SHADOW")
        col.record_monitor_snapshot("NIFTY", "NSE", chain, context, None, lot_size=None, ts=ts)
        rows = list(self._csv_rows(self.dir / "monitor_diagnostics.csv"))
        self.assertEqual(rows[-1]["atm_ce_top_book_lots"], "")

    def test_record_candidates_writes_full_detail_rows(self):
        cfg = SystemConfig.from_file(CFG_PATH)
        scorer = OpportunityScorer(cfg)
        strong = make_candidate({"direction": 90, "trade_quality": 90, "regime_confidence": 80,
                                 "hostility": 10, "elasticity": 0.8, "expected_move": 200,
                                 "required_move": 100, "ratio": 2.0, "ev_r": 1.0, "vol_edge": 2.0,
                                 "convexity": 90, "execution": 90, "confidence": 90, "regime_fit": 90})
        weak = make_candidate({"direction": 10, "trade_quality": 10, "regime_confidence": 40,
                               "hostility": 60, "elasticity": 0.2, "expected_move": 50,
                               "required_move": 200, "ratio": 0.25, "ev_r": -0.5, "vol_edge": 0.5,
                               "convexity": 10, "execution": 10, "confidence": 10, "regime_fit": 10},
                              underlying="BANKNIFTY", side=OptionType.PE, strike=57800.0)
        evals = tuple(scorer.evaluate(c) for c in (strong, weak))
        col = PaperEvidenceCollector(self.dir)
        col.record_candidates(evals, ts=datetime(2026, 8, 12, 14, 30))
        rows = list(self._csv_rows(self.dir / "candidates_log.csv"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["date"], "2026-08-12")
        self.assertGreater(float(rows[0]["comparable_score"]), float(rows[1]["comparable_score"]))
        for key in ("grade", "eligible", "decision", "direction", "convexity", "execution",
                    "confidence", "exp_req_ratio", "bid", "ask", "mid", "spread_pct", "reasons",
                    "iv_context_status", "iv_context_reason", "iv_context_source",
                    "cost_model_valid", "canonical_promotion_allowed", "depth_evidence", "depth_source",
                    "depth_bid_levels", "depth_ask_levels", "bid_qty", "ask_qty",
                    "cumulative_bid_qty_5depth", "cumulative_ask_qty_5depth", "quote_timestamp",
                    "source_timestamp_available"):
            self.assertIn(key, rows[0])
        self.assertIsInstance(rows[0]["reasons"], str)
        diagnostics = list(self._csv_rows(self.dir / "candidate_diagnostics.csv"))
        self.assertEqual(len(diagnostics), 2)
        for key in ("side_direction_score", "direction_gate_passed",
                    "contract_quality_score", "contract_quality_gate_passed",
                    "gate_optimization_status", "gate_validation_observations",
                    "gate_validation_retention", "rejection_count", "rejection_reasons",
                    "iv_context_status", "iv_context_reason", "iv_context_source",
                    "cost_model_valid", "canonical_promotion_allowed", "depth_evidence", "depth_source",
                    "depth_bid_levels", "depth_ask_levels", "bid_qty", "ask_qty",
                    "cumulative_bid_qty_5depth", "cumulative_ask_qty_5depth", "quote_timestamp",
                    "source_timestamp_available"):

            self.assertIn(key, diagnostics[0])
        # The strong call is aligned and the weak PE is wrong-sided in this
        # fixture, so the diagnostics must make the distinction explicit.
        self.assertEqual(diagnostics[0]["direction_gate_passed"], "True")
        self.assertEqual(diagnostics[1]["direction_gate_passed"], "False")

    def _csv_rows(self, path):
        import csv
        with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
            yield from csv.DictReader(f)


class ReportWithTradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = SystemConfig.from_file(CFG_PATH)

    def tearDown(self):
        self.tmp.cleanup()

    def test_report_renders_calibration_buckets_after_a_trade(self):
        col = PaperEvidenceCollector(self.dir)
        # A winning, high-score trade (score ~90+) and a losing lower-score trade.
        strong = make_candidate({"direction": 90, "trade_quality": 90, "regime_confidence": 80,
                                 "hostility": 10, "elasticity": 0.8, "expected_move": 200,
                                 "required_move": 100, "ratio": 2.0, "ev_r": 1.0, "vol_edge": 2.0,
                                 "convexity": 90, "execution": 90, "confidence": 90, "regime_fit": 90})
        weak = make_candidate({"direction": 20, "trade_quality": 20, "regime_confidence": 40,
                               "hostility": 40, "elasticity": 0.4, "expected_move": 80,
                               "required_move": 160, "ratio": 0.5, "ev_r": 0.1, "vol_edge": 0.9,
                               "convexity": 30, "execution": 50, "confidence": 40, "regime_fit": 40},
                              underlying="BANKNIFTY", side=OptionType.PE, strike=57800.0)
        scorer = OpportunityScorer(self.cfg)
        for cand, pnl, r in ((strong, 3000.0, 2.0), (weak, -800.0, -1.5)):
            ev = scorer.evaluate(cand)
            fill = PaperFill(True, cand.quote.mid, None, 0.0, "")
            trade = PaperTrade(trade_id=f"t-{pnl}", entry_evaluation=ev, entry_fill=fill,
                               entry_time=now_ist(), exit_fill=fill,
                               exit_time=now_ist() + timedelta(minutes=5),
                               exit_reason="TARGET_HIT" if pnl > 0 else "STOP_HIT")
            col.record_trade(trade, net_pnl_rupees=pnl, r_multiple=r)
        text = build_evidence_report(self.dir, self.cfg)
        self.assertIn("EVIDENCE REVIEW", text)
        self.assertIn("trades=2", text)
        self.assertIn("CALIBRATION", text)
        self.assertIn("90+", text)         # current high-score bucket rendered
        self.assertIn("win%", text)


CANDIDATE_LOG_COLS = [
    "ts", "date", "underlying", "side", "strike", "expiry", "dte", "grade",
    "comparable_score", "opportunity_score", "threshold", "eligible", "decision",
    "direction", "trade_quality", "market_hostility", "iv_crush", "convexity",
    "execution", "confidence", "regime_fit", "premium_elasticity", "expected_move",
    "required_move", "exp_req_ratio", "bid", "ask", "mid", "spread_pct", "reasons",
]


def _candidate_row(day, score, underlying="NIFTY", side="CE", strike=24500.0,
                   decision="NO_EXCELLENT_CANDIDATE"):
    return {
        "ts": f"{day}T12:00:00", "date": day, "underlying": underlying, "side": side,
        "strike": strike, "expiry": "2026-08-18", "dte": 6, "grade": "B",
        "comparable_score": score, "opportunity_score": score, "threshold": 80.0,
        "eligible": "True", "decision": decision, "direction": 60.0, "trade_quality": 55.0,
        "market_hostility": 10.0, "iv_crush": 20.0, "convexity": 70.0, "execution": 80.0,
        "confidence": 75.0, "regime_fit": 65.0, "premium_elasticity": 0.5,
        "expected_move": 150.0, "required_move": 100.0, "exp_req_ratio": 1.5,
        "bid": 99.0, "ask": 101.0, "mid": 100.0, "spread_pct": 1.98,
        "reasons": "grade below threshold",
    }


class TopCandidatesReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_report_top10_per_day_with_summary(self):
        ac = AppendingCsv(self.dir / "candidates_log.csv")
        # Day 1: 12 candidates (scores 40..51) - only the top 10 may appear.
        for i in range(12):
            ac.append(_candidate_row("2026-08-11", 40.0 + i, strike=24500.0 + i))
        # Day 2: 3 candidates, one well above the 80 gate.
        for score in (85.0, 55.0, 45.0):
            ac.append(_candidate_row("2026-08-12", score, underlying="BANKNIFTY", side="PE"))

        text = build_top_candidates_report(self.dir)
        self.assertIn("DAY 2026-08-11", text)
        self.assertIn("DAY 2026-08-12", text)
        day1 = text.split("DAY 2026-08-11")[1].split("DAY 2026-08-12")[0]
        self.assertIn("51.0", day1)     # day-1 top score is shown
        self.assertNotIn("40.0", day1)  # 12th-ranked candidate is cut by top-10
        day2 = text.split("DAY 2026-08-12")[1].split("SCORE DISTRIBUTION")[0]
        self.assertIn("85.0", day2)
        self.assertIn("candidates>=80: 1", day2)
        self.assertIn("SCORE DISTRIBUTION", text)
        self.assertIn("THRESHOLD INSIGHT", text)
        self.assertIn("all-time max score: 85.0", text)
        self.assertIn("days with any candidate >= 80: 1 / 2", text)

    def test_report_day_filter_and_missing_log(self):
        self.assertIn("no candidates_log.csv yet", build_top_candidates_report(self.dir))
        ac = AppendingCsv(self.dir / "candidates_log.csv")
        ac.append(_candidate_row("2026-08-11", 70.0))
        ac.append(_candidate_row("2026-08-12", 90.0))
        text = build_top_candidates_report(self.dir, day="2026-08-12")
        self.assertIn("DAY 2026-08-12", text)
        self.assertNotIn("DAY 2026-08-11", text)

    def test_report_top_n_override(self):
        ac = AppendingCsv(self.dir / "candidates_log.csv")
        for i in range(5):
            ac.append(_candidate_row("2026-08-11", 60.0 + i))
        text = build_top_candidates_report(self.dir, top_n=2)
        day1 = text.split("DAY 2026-08-11")[1].split("SCORE DISTRIBUTION")[0]
        self.assertIn("64.0", day1)
        self.assertNotIn("\n   3 ", day1)  # only top 2 ranked rows shown


class DailyRunTests(unittest.TestCase):
    def test_daily_run_archives_and_flags_tests(self):
        from institutional_options.daily_evidence_run import (
            PROJECT_ROOT, archive_report, generate_report,
        )
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            # A tiny mtil row so the report has evidence to render.
            (state / "mtil.csv").write_text(
                "trade_id,date,instrument,option_type,OpportunityScore,net_pnl_rupees,r_multiple\n"
                "t1,2026-08-12,NIFTY,CE,85,1500,1.5\n", encoding="utf-8")
            out = generate_report(state, emergency_passed=True)
            self.assertTrue(out.exists())
            text = out.read_text(encoding="utf-8")
            self.assertIn("PAPER-EVIDENCE REPORT", text)
            self.assertIn("[PASS] emergency_tests_passed", text)
            # The daily run must also produce the top-candidates report.
            self.assertTrue((state / "top_candidates_report.txt").exists())
            archived = archive_report(state, out)
            self.assertTrue(archived.exists())
            self.assertIn("evidence_report_", archived.name)
            # project root must be the repo folder holding pyproject.toml
            self.assertTrue((PROJECT_ROOT / "pyproject.toml").exists())

    def test_daily_run_runs_test_suite(self):
        import subprocess, sys
        from institutional_options.daily_evidence_run import run_tests
        # Simulated: patch subprocess.run to avoid actually running the suite here.
        import institutional_options.daily_evidence_run as m
        real = m.subprocess.run
        try:
            m.subprocess.run = lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
            self.assertTrue(run_tests())
            m.subprocess.run = lambda *a, **k: type("R", (), {"returncode": 1, "stdout": "fail", "stderr": ""})()
            self.assertFalse(run_tests())
        finally:
            m.subprocess.run = real


if __name__ == "__main__":
    unittest.main()
