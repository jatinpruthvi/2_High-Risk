"""Live paper trading runner.

Polls the Fyers market-data API (validated, read-only, no orders) and drives
the *real* strategy pipeline each cycle:

    chain -> OptionChainSnapshot -> CandidateFactory (live proxies added)
          -> OpportunityScorer -> PaperOpportunityEngine selection
          -> PaperFillSimulator entry fill
          -> SimulatedTradeLifecycle with ExitPolicy on live bars
          -> journal + shared state for the dashboard

Paper-only by construction: this module never places an order. It only reads
market data and simulates fills through the same conservative paper-fill
model the rest of the repo uses.

Run:  python -m institutional_options.paper_runner
"""
from __future__ import annotations

import csv
import gzip
import hashlib
from copy import deepcopy
import json
import math
import os
import shutil
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from types import SimpleNamespace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from .config import ConfigError, SystemConfig
from .costs import ChargesConfig, CostCalculator, validate_charges_config
from .candidates import CandidateFactory, CandidateFactoryContext
from .engine import PaperOpportunityEngine, PaperPortfolioState
from .fyers_client import FyersCredentials, FyersRestClient, FyersSymbolMaster, TokenStore
from .fyers_parser import FyersOptionChainParser, parse_expiry_calendar, parse_india_vix
from .feed_quality import assess_fyers_payload
from .derived_iv import implied_volatility
from .lifecycle import (
    EXIT_BREAKEVEN, EXIT_END_OF_DATA, EXIT_LOSING_TIME, EXIT_NO_DATA,
    EXIT_STOP, EXIT_TARGET, EXIT_TIME, EXIT_TRAIL, EXIT_VOL_TIME,
    ExitPolicy, MarketBar, SimulatedTradeLifecycle,
)
from .models import DataHealth, OptionType, PaperFill, PaperTrade, Quote, TradeDecision, SelectionResult
from .market_metrics import PortfolioNoTradeCalculator
from .observed_metrics import RollingPremiumElasticity
from .option_chain import OptionChainSnapshot, OptionLeg, OptionStrike
from .playbooks import RegimeContext, RegimeLabel, RegimePlaybookSelectionEngine
from .surface_diagnostics import OptionSurfaceDiagnostics
from .paper_evidence import PaperEvidenceCollector
from .evidence_analytics import build_evidence_snapshot, build_opportunity_heartbeat, timestamp_quality
from .opportunity_learning import OpportunityLearningLedger
from .paper_signal import PaperSignalCalculator
from .cas_monitor import CasAnomalyMonitor
from .edge_modules import ExecutionQualityCalculator
from .experimental_impulse import ImpulseBreakoutResult, ImpulseBreakoutSelector
from .orchestrators import DataHealthOrchestrator
from .operator_controls import load_daily_mode, load_market_context
from .research_controls import (
    InstrumentCalibrationStore, InstrumentLifecycle, PortfolioOverlapGuard,
    PromotionEngine, PromotionMetrics, class_for_metadata, exposure_group, gate_feature_snapshot,
    version_fingerprint,
)
from .research_ledger import ResearchEventLedger, ShadowTradeTracker
from .scoring import CandidateRevalidator, PaperFillSimulator

IST = timezone(timedelta(hours=5, minutes=30))
ACTIVE_EXIT_REASONS = {EXIT_TARGET, EXIT_STOP, EXIT_BREAKEVEN, EXIT_TRAIL, EXIT_TIME, EXIT_LOSING_TIME, EXIT_VOL_TIME}


def now_ist() -> datetime:
    return datetime.now(IST)


@dataclass
class OpenPosition:
    trade: PaperTrade
    symbol: str                 # Fyers symbol of the held option
    underlying: str
    expiry: str
    stop_points: float
    target_points: float
    max_duration_seconds: int
    bars: list[MarketBar] = field(default_factory=list)
    opened_at: datetime = field(default_factory=now_ist)
    last_premium: float = 0.0
    highest_premium: float = 0.0
    lowest_premium: float = 0.0
    last_quote: Optional[Quote] = None
    entry_mode: str = "CANONICAL"


@dataclass
class ClosedTradeRecord:
    trade_id: str
    underlying: str
    side: str
    expiry: str
    strike: float
    entry_time: str
    exit_time: str
    entry_fill: float
    exit_fill: float
    exit_reason: str
    gross_points: float
    gross_pnl: float
    costs: float
    net_pnl: float
    hold_seconds: int
    max_adverse_points: float
    max_favorable_points: float
    entry_mode: str = "CANONICAL"


@dataclass
class RunnerState:
    started_at: str = field(default_factory=lambda: now_ist().isoformat())
    last_cycle: str = ""
    last_cycle_ok: bool = False
    last_error: str = ""
    cycle_in_progress: bool = False
    cycle_started_at: str = ""
    market_open: bool = False
    open_position: Optional[OpenPosition] = None
    open_positions: list[OpenPosition] = field(default_factory=list)
    closed_trades: list[ClosedTradeRecord] = field(default_factory=list)
    underlyings: dict[str, Any] = field(default_factory=dict)   # per-underlying display data
    equity: list[float] = field(default_factory=list)
    realized_pnl: float = 0.0
    realized_pnl_today: float = 0.0
    realized_pnl_week: float = 0.0
    trades_today: int = 0
    losses_today: int = 0
    loss_streak_today: int = 0
    last_loss_at: str = ""
    recent_direction_losses: dict[str, str] = field(default_factory=dict)
    session_id: str = ""


class PaperRunner:
    """Owns the poll loop and shared state; no order placement."""

    def __init__(self, config: SystemConfig, runner_cfg: Mapping[str, Any],
                 state_dir: str | Path = "paper_state",
                 client: Optional[FyersRestClient] = None,
                 master: Optional[FyersSymbolMaster] = None,
                 replay: bool = False):
        self.base_config = config
        self.cfg = runner_cfg
        self.universe = self._universe()
        self.state_dir = Path(state_dir)
        self._prepare_state_directory()
        self._daily_risk_path = self.state_dir / "daily_risk.json"
        self._account_state_path = self.state_dir / "paper_account.json"
        self._open_position_path = self.state_dir / "paper_open_position.json"
        self._open_positions_path = self.state_dir / "paper_open_positions.json"
        self._entry_audit_path = self.state_dir / "entry_audit.csv"
        self._qualified_opportunity_path = self.state_dir / "qualified_opportunities.csv"
        self._missed_opportunity_path = self.state_dir / "best_missed_opportunities.csv"
        self.opportunity_learning = OpportunityLearningLedger(self.state_dir)
        self._write_entry_audit_header()
        self._write_qualified_opportunity_header()
        self._write_missed_opportunity_header()
        self._evidence_analytics_cache: dict[str, Any] = {}
        self._evidence_analytics_cache_at = 0.0
        self._rank_persistence_path = self.state_dir / "rank_persistence.json"
        self._rank_persistence: dict[str, dict[str, Any]] = self._load_rank_persistence()
        self._gate_breakout_path = self.state_dir / "gate_breakout_history.json"
        self._gate_breakout_history: dict[str, list[dict[str, Any]]] = self._load_gate_breakout_history()
        self._experimental_impulse_path = self.state_dir / "experimental_impulse_state.json"
        self._experimental_impulse_csv_path = self.state_dir / "experimental_impulse_signals.csv"
        self._experimental_impulse_state = self._load_experimental_impulse_state()
        self._write_experimental_impulse_header()
        self._daily_risk_date = now_ist().date().isoformat()
        self._risk_week_key = (now_ist().date() - timedelta(days=now_ist().weekday())).isoformat()
        self.state = RunnerState(session_id=now_ist().strftime("%Y%m%d_%H%M%S"))
        self.cas_monitor = CasAnomalyMonitor(self.state_dir, self.cfg.get("cas_monitor", {}))
        self._cas_paper_entry_enabled = bool(self.cfg.get("cas_monitor", {}).get("paper_position_enabled", True))
        self._restore_account_state()
        self._restore_daily_risk_state(now_ist())
        self._replay = bool(replay)

        # Paper-only config overrides (PARAMETERS.json is never modified).
        # With the frozen risk caps, a real NIFTY/BANKNIFTY ATM premium
        # (required stop = 20% of premium x lot) always exceeds the Rs 750 cap,
        # so no trade can fire. To *watch* the strategy trade in paper mode,
        # set uploads/PAPER_RUNNER.json -> config_overrides. The dashboard shows
        # a PAPER-ONLY OVERRIDE banner whenever these are active.
        self._active_overrides: dict[str, Any] = {}
        self.config = self._overlay_config(config)

        if client is not None:
            self.client = client
        elif self._replay:
            raise ValueError("replay mode requires an injected replay client")
        else:
            creds = FyersCredentials.from_env()
            timeout_cfg = self.cfg.get("fyers_request_timeout_seconds", 15)
            try:
                request_timeout = max(5, min(30, int(timeout_cfg)))
            except (TypeError, ValueError):
                request_timeout = 15
            min_interval_cfg = self.cfg.get("fyers_request_min_interval_seconds", 0.35)
            try:
                request_min_interval = max(0.0, min(5.0, float(min_interval_cfg)))
            except (TypeError, ValueError):
                request_min_interval = 0.35
            retries_cfg = self.cfg.get("fyers_max_transient_retries", 2)
            try:
                max_transient_retries = max(0, min(4, int(retries_cfg)))
            except (TypeError, ValueError):
                max_transient_retries = 2
            backoff_cfg = self.cfg.get("fyers_transient_backoff_seconds", [1.0, 3.0])
            if isinstance(backoff_cfg, (list, tuple)):
                try:
                    transient_backoff = tuple(max(0.0, float(x)) for x in backoff_cfg) or (1.0, 3.0)
                except (TypeError, ValueError):
                    transient_backoff = (1.0, 3.0)
            else:
                transient_backoff = (1.0, 3.0)
            max_backoff_cfg = self.cfg.get("fyers_max_backoff_seconds", 8.0)
            try:
                max_backoff = max(0.0, min(60.0, float(max_backoff_cfg)))
            except (TypeError, ValueError):
                max_backoff = 8.0
            self.client = FyersRestClient(
                creds,
                TokenStore(self.state_dir / "tokens.json"),
                timeout=request_timeout,
                request_min_interval_sec=request_min_interval,
                max_transient_retries=max_transient_retries,
                transient_backoff_sec=transient_backoff,
                max_backoff_sec=max_backoff,
            )
            self.client.ensure_session()

        self.signal = PaperSignalCalculator(self.config)
        elasticity_cfg = self.config.section("premium_elasticity")
        self.observed_elasticity = RollingPremiumElasticity(
            window_seconds=float(elasticity_cfg.get("smoothing_window_sec", 60.0)),
            min_underlying_move_points=float(elasticity_cfg.get("min_futures_move_points", 30.0)),
            confirmation_windows=max(1, int(elasticity_cfg.get("confirmation_windows", 2))),
            min_confirmed_elasticity=float(elasticity_cfg.get("delta_adjusted_entry_min", 1.0)),
        )
        self.execution_quality = ExecutionQualityCalculator()
        self.factory = CandidateFactory(self.config)
        self.scorer_engine = None
        self.fill_sim = PaperFillSimulator(self.config)
        self.lifecycle = SimulatedTradeLifecycle(self.fill_sim)
        self.exit_policy = ExitPolicy.from_config(self.config)
        # Phase-2 evidence collection: mtil.csv (closed trades) + skipped.csv.
        self.evidence = None
        self._last_skipped_cycle = 0.0
        self._last_shadow_cycle = 0.0
        self._incident_block_until = 0.0
        self._incident_reason = ""
        self.history_bars = int(self.cfg.get("history_bars", 30))
        self.history_cache: dict[str, list] = {}

        charges_path = Path("uploads/CHARGES_CONFIG.json")
        charges = ChargesConfig.from_file(charges_path)
        self.costs = CostCalculator(charges)
        charges_validation = validate_charges_config(charges_path)
        self._cost_model_valid = bool(charges_validation.valid)
        self._cost_model_status = "COST_MODEL_VALIDATED" if self._cost_model_valid else "COST_MODEL_UNVALIDATED"
        self.state.underlyings["_cost_model"] = {
            "status": self._cost_model_status,
            "canonical_promotion_allowed": self._canonical_promotion_allowed(),
            "reasons": list(charges_validation.reasons),
        }

        self.poll_seconds = float(self.cfg.get("poll_seconds", 5.0))
        self.strikecount = int(self.cfg.get("strikecount", 30))
        self.entry_hold_seconds = int(self.config.section("holding_time")["normal_max_hold_minutes"]) * 60
        monitoring_cfg = self.cfg.get("monitoring", {})
        self.monitor_batch_size = max(1, int(monitoring_cfg.get("monitor_batch_size", 8))) if isinstance(monitoring_cfg, Mapping) else 8
        self.monitor_poll_seconds = max(0.0, float(monitoring_cfg.get("monitor_poll_seconds", 60.0))) if isinstance(monitoring_cfg, Mapping) else 60.0
        self._monitor_cursor = 0
        self._last_monitor_refresh = float("-inf")
        self._last_monitor_batch: list[str] = []
        # Staged paper-selector scheduler. This controls request priority and
        # retry timing only; it never changes the frozen 59-instrument universe
        # or bypasses any candidate, liquidity, risk, or execution gate.
        self.staged_scheduler_enabled = bool(monitoring_cfg.get("staged_evaluation_enabled", True)) if isinstance(monitoring_cfg, Mapping) else True
        self.scheduler_max_audit_cycles = max(1, int(monitoring_cfg.get("max_full_audit_cycles", 7))) if isinstance(monitoring_cfg, Mapping) else 7
        self.scheduler_backoff_base_seconds = max(5.0, float(monitoring_cfg.get("failure_backoff_base_seconds", 30.0))) if isinstance(monitoring_cfg, Mapping) else 30.0
        self.scheduler_backoff_max_seconds = max(self.scheduler_backoff_base_seconds, float(monitoring_cfg.get("failure_backoff_max_seconds", 180.0))) if isinstance(monitoring_cfg, Mapping) else 180.0
        self._scheduler_cycle = 0
        self._scheduler_meta: dict[str, dict[str, Any]] = {}
        self._risk_context = self._load_risk_context()
        self._playbook_codes_by_underlying: dict[str, frozenset[str]] = {}
        self._playbook_grades_by_underlying: dict[str, str] = {}
        self.playbook_engine = RegimePlaybookSelectionEngine(
            excellent_threshold=float(self.config.section("opportunity_selection").get("excellent_opportunity_min_score", 80.0))
        )
        if self._active_overrides:
            parameter_profile = "PAPER_OVERRIDE"
        elif isinstance(self.cfg.get("signal"), Mapping):
            parameter_profile = "RUNNER_SIGNAL_CONFIG"
        else:
            parameter_profile = "FROZEN_PARAMETERS"
        evidence_profile = self.config.raw.get("evidence_profiles", {}).get("active_profile")
        if evidence_profile:
            parameter_profile = f"{parameter_profile}::{evidence_profile}"
        self.versions = version_fingerprint(self.config, self.universe, parameter_profile=parameter_profile)
        self.calibration = InstrumentCalibrationStore(self.state_dir, self.config)
        self.promotion = PromotionEngine(self.calibration)
        self.overlap_guard = PortfolioOverlapGuard(enabled=True, block_same_group=True, block_same_underlying=True)
        self.event_ledger = ResearchEventLedger(self.state_dir, self.versions)
        self.evidence = PaperEvidenceCollector(self.state_dir, self.versions)
        self.scorer_engine = PaperOpportunityEngine(self.config, gate_provider=self.calibration.gates_for)
        self.paper_calibration_engine = self._build_paper_calibration_engine()
        operator_controls = self.config.raw.get("operator_controls", {})
        if not isinstance(operator_controls, Mapping):
            operator_controls = {}
        self._daily_mode_path = str(operator_controls.get("daily_mode_path", "uploads/DAILY_MODE.txt"))
        self._market_context_path = str(operator_controls.get("market_context_path", "uploads/DAILY_MARKET_CONTEXT.json"))
        computed_mode = self._computed_daily_mode()
        self.daily_mode = load_daily_mode(self._daily_mode_path, computed_mode, now=now_ist())
        self.scorer_engine.set_runtime_mode(self.daily_mode.effective_mode)
        self.state.underlyings["_daily_mode"] = {
            "computed_mode": self.daily_mode.computed_mode,
            "effective_mode": self.daily_mode.effective_mode,
            "status": self.daily_mode.status,
            "reason": self.daily_mode.reason,
            "path": self.daily_mode.path,
        }
        self.event_ledger.append(
            "DAILY_MODE_CONTEXT", session_id=self.state.session_id,
            decision_source="daily_mode_operator_control", ts=now_ist(),
            payload=self.state.underlyings["_daily_mode"],
        )
        self.revalidator = CandidateRevalidator(self.config)
        self.data_health = DataHealthOrchestrator(self.config)
        self.paper_calibration_data_health = (
            DataHealthOrchestrator(self.paper_calibration_engine.config)
            if self.paper_calibration_engine is not None else None
        )
        self.paper_calibration_revalidator = (
            CandidateRevalidator(self.paper_calibration_engine.config)
            if self.paper_calibration_engine is not None else None
        )
        self.portfolio_no_trade = PortfolioNoTradeCalculator()
        self.shadow_tracker = ShadowTradeTracker(self.fill_sim, max_hold_seconds=self.entry_hold_seconds)
        self.lifecycle_states = {}
        for und, meta in self.universe.items():
            default_state = InstrumentLifecycle.MONITOR if meta.get("monitor_only", False) else InstrumentLifecycle.PAPER_ELIGIBLE
            state = self.calibration.lifecycle_state(und, default_state)
            if not meta.get("monitor_only", False) and state in {InstrumentLifecycle.MONITOR, InstrumentLifecycle.SHADOW}:
                state = InstrumentLifecycle.PAPER_ELIGIBLE
                self.calibration.set_lifecycle_state(und, state)
            self.lifecycle_states[und] = state.value
        if master is None and self._replay:
            # Replay is offline: load every cached exchange master (no auth needed).
            cached_masters = []
            for exchange in self._configured_exchanges():
                cached = self.state_dir / f"{exchange}_FO.csv"
                if cached.exists():
                    cached_masters.append(
                        FyersSymbolMaster.from_csv(
                            cached,
                            allowed_exchanges={exchange},
                            allowed_underlyings=set(self.universe),
                        )
                    )
            if cached_masters:
                master = FyersSymbolMaster.combine(*cached_masters)
        self.master = master if master is not None else self._load_master()
        self._restore_open_position()
        self._journal_path = self.state_dir / "trades.csv"
        self._write_journal_header()
        # Session capture: every cycle's raw chain/history payloads, gzipped
        # JSONL, for offline replay + parameter sweeps (paper_state/sessions/).
        self._capture = bool(self.cfg.get("capture", False))
        self._capture_file = None
        if self._capture:
            sess_dir = self.state_dir / "sessions"
            sess_dir.mkdir(parents=True, exist_ok=True)
            self._capture_file = gzip.open(sess_dir / f"{self.state.session_id}.jsonl.gz",
                                           "wt", encoding="utf-8")
        trade_universe = [und for und, meta in self.universe.items() if meta.get("trade_enabled", False)]
        monitor_universe = [und for und, meta in self.universe.items() if meta.get("monitor_only", False)]
        self._log(f"Paper selector universe: {', '.join(trade_universe)}; "
                  f"monitor-only: {', '.join(monitor_universe) or '-'}")

    # -- setup -----------------------------------------------------------------

    def _prepare_state_directory(self) -> None:
        """Prevent stale evidence from being mixed with a changed paper policy."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        management = self.cfg.get("state_management", {})
        if not isinstance(management, Mapping):
            management = {}
        fresh_on_change = bool(management.get("fresh_state_on_policy_change", True))
        fresh_on_legacy = bool(management.get("fresh_state_on_missing_manifest", True))
        universe_payload = {
            "underlyings": sorted(self.universe),
            "trade_enabled": sorted(und for und, meta in self.universe.items() if meta.get("trade_enabled", True)),
            "monitor_only": sorted(und for und, meta in self.universe.items() if meta.get("monitor_only", False)),
            "live_trading_enabled": bool(getattr(self.base_config, "raw", {}).get("execution", {}).get("live_trading_enabled", False)),
        }
        cfg_payload = json.dumps({
            "universe": universe_payload,
            "parameters": getattr(self.base_config, "raw", {}),
            "runner_overrides": self.cfg.get("config_overrides", {}),
            "runner_signal": self.cfg.get("signal", {}),
            "runner_experimental_impulse": self.cfg.get("experimental_impulse_breakout", {}),
            "runner_history_bars": self.cfg.get("history_bars", 30),
        }, sort_keys=True, default=str, separators=(",", ":"))
        signature = hashlib.sha256(cfg_payload.encode("utf-8")).hexdigest()[:16]
        manifest_path = self.state_dir / "run_manifest.json"
        previous = None
        if manifest_path.exists():
            try:
                previous = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                previous = None
        evidence_names = {
            "mtil.csv", "skipped.csv", "candidates_log.csv", "candidate_diagnostics.csv",
            "shadow_candidates.csv", "shadow_candidate_diagnostics.csv", "monitor_diagnostics.csv",
            "shadow_outcomes.csv", "skipped_forward_queue.csv", "skipped_forward_outcomes.csv", "revalidation_audit.csv", "paper_fill_audit.csv", "experimental_impulse_state.json", "experimental_impulse_signals.csv",
            "instrument_calibration.json", "research_events.csv", "run_manifest.json", "master_provenance.json",
            "daily_risk.json", "rank_persistence.json", "runner.log", "runner.err.log",
        }
        has_legacy_evidence = any((self.state_dir / name).exists() for name in evidence_names)
        should_archive = (fresh_on_change and previous is not None and previous.get("policy_signature") != signature) or (fresh_on_legacy and previous is None and has_legacy_evidence)
        if should_archive:
            archive_root = self.state_dir / str(management.get("archive_dir", "archives"))
            archive_root.mkdir(parents=True, exist_ok=True)
            stamp = now_ist().strftime("%Y%m%d_%H%M%S")
            archive_dir = archive_root / f"policy_{stamp}"
            suffix = 1
            while archive_dir.exists():
                archive_dir = archive_root / f"policy_{stamp}_{suffix}"
                suffix += 1
            archive_dir.mkdir(parents=True, exist_ok=False)
            preserved = {archive_root.name, "tokens.json", "creds.env"}
            for child in list(self.state_dir.iterdir()):
                if child.name in preserved:
                    continue
                shutil.move(str(child), str(archive_dir / child.name))
            self._log(f"Archived stale paper evidence to {archive_dir}")
        manifest = {
            "created_at": now_ist().isoformat(),
            "policy_signature": signature,
            "universe": universe_payload,
            "parameter_profile": "PAPER_RUNNER_CONFIG",
            "live_execution": "DISABLED",
            "state_policy": "fresh_state_on_policy_change",
        }
        tmp = manifest_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(manifest_path)
        self.run_manifest = manifest

    def _universe(self) -> dict[str, dict[str, str]]:
        cfg_universe = self.cfg.get("underlyings")
        if isinstance(cfg_universe, Mapping):
            out: dict[str, dict[str, str]] = {}
            for und, meta in cfg_universe.items():
                if isinstance(meta, Mapping):
                    exchange = str(meta.get("exchange", "NSE")).upper()
                    if exchange not in {"NSE", "BSE"}:
                        raise ValueError(f"Unsupported Fyers exchange for {und}: {exchange}")
                    out[str(und).upper()] = {
                        "index_symbol": str(meta.get("index_symbol", "")),
                        "exchange": exchange,
                        "prefer_monthly": str(meta.get("prefer_monthly", "false")).lower() == "true",
                        "instrument_kind": str(meta.get("instrument_kind", "INDEX")).upper(),
                        "monitor_only": bool(meta.get("monitor_only", False)),
                        "trade_enabled": bool(meta.get("trade_enabled", not bool(meta.get("monitor_only", False)))),
                    }
            if out:
                return out
        # Defaults (NSE index symbols on Fyers; note BANKNIFTY is NIFTYBANK).
        return {
            "NIFTY": {"index_symbol": "NSE:NIFTY50-INDEX", "exchange": "NSE", "prefer_monthly": "false", "monitor_only": False},
            "BANKNIFTY": {"index_symbol": "NSE:NIFTYBANK-INDEX", "exchange": "NSE", "prefer_monthly": "false", "monitor_only": False},
            "FINNIFTY": {"index_symbol": "NSE:FINNIFTY-INDEX", "exchange": "NSE", "prefer_monthly": "false", "monitor_only": False},
            "MIDCPNIFTY": {"index_symbol": "NSE:MIDCPNIFTY-INDEX", "exchange": "NSE", "prefer_monthly": "false", "monitor_only": False},
        }

    def _configured_exchanges(self) -> tuple[str, ...]:
        return tuple(sorted({meta.get("exchange", "NSE") for meta in self.universe.values()}))

    def _trade_underlyings(self) -> list[str]:
        """Return every configured paper-trade-eligible underlying.

        Live eligibility remains separately frozen in PARAMETERS.json. This
        method represents the revised paper-only policy and therefore does not
        exclude instruments merely because they belong to the expanded research
        universe.
        """
        return [und for und, meta in self.universe.items()
                if bool(meta.get("trade_enabled", not meta.get("monitor_only", False)))]

    def _scheduler_entry(self, underlying: str) -> dict[str, Any]:
        return self._scheduler_meta.setdefault(str(underlying), {
            "status": "UNSEEN",
            "failures": 0,
            "last_attempt_cycle": -1,
            "last_full_audit_cycle": -1,
            "last_success_cycle": -1,
            "next_retry_at": 0.0,
            "last_error": "",
            "last_deferred_reason": "",
            "last_deferred_event_cycle": -1,
        })

    def _scheduler_public_state(self, underlying: str) -> dict[str, Any]:
        row = self._scheduler_entry(underlying)
        return {
            "lane": str(row.get("lane", "AUDIT")),
            "status": str(row.get("status", "UNSEEN")),
            "failures": int(row.get("failures", 0)),
            "last_attempt_cycle": int(row.get("last_attempt_cycle", -1)),
            "last_full_audit_cycle": int(row.get("last_full_audit_cycle", -1)),
            "last_success_cycle": int(row.get("last_success_cycle", -1)),
            "next_retry_at": float(row.get("next_retry_at", 0.0) or 0.0),
            "last_error": str(row.get("last_error", "")),
            "last_deferred_reason": str(row.get("last_deferred_reason", "")),
        }

    def _scheduler_mark_success(self, underlying: str) -> None:
        row = self._scheduler_entry(underlying)
        row.update({
            "status": "SUCCESS",
            "failures": 0,
            "last_success_cycle": self._scheduler_cycle,
            "last_full_audit_cycle": self._scheduler_cycle,
            "next_retry_at": 0.0,
            "last_error": "",
        })
        self.state.underlyings.setdefault(underlying, {})["scheduler"] = self._scheduler_public_state(underlying)

    def _scheduler_mark_deferred(self, underlying: str, reason: str, details: Optional[Mapping[str, Any]] = None) -> None:
        row = self._scheduler_entry(underlying)
        row.update({
            "status": "DEFERRED_STRUCTURAL",
            "last_attempt_cycle": self._scheduler_cycle,
            "last_deferred_reason": str(reason),
            "last_error": "",
            "next_retry_at": time.time() + self.monitor_poll_seconds,
        })
        self.state.underlyings.setdefault(underlying, {})["scheduler"] = self._scheduler_public_state(underlying)
        self.state.underlyings.setdefault(underlying, {})["prefilter"] = {
            "status": "DEFERRED",
            "reason": str(reason),
            "details": dict(details or {}),
            "lane": str(row.get("lane", "OPPORTUNITY")),
            "audit_due_by_cycle": self._scheduler_cycle + self.scheduler_max_audit_cycles,
            "timestamp": now_ist().isoformat(),
        }
        self.event_ledger.append(
            "PAPER_INSTRUMENT_DEFERRED", session_id=self.state.session_id,
            underlying=underlying, exchange=self.universe.get(underlying, {}).get("exchange", "NSE"),
            instrument_kind=self.universe.get(underlying, {}).get("instrument_kind", "INDEX"),
            instrument_class=class_for_metadata(self.universe.get(underlying, {}).get("exchange", "NSE"), self.universe.get(underlying, {}).get("instrument_kind", "INDEX")),
            decision_source="structural_prefilter", ts=now_ist(),
            payload={"reason": str(reason), "details": dict(details or {}), "scheduler_cycle": self._scheduler_cycle},
        )

    def _scheduler_mark_failure(self, underlying: str, detail: str) -> None:
        row = self._scheduler_entry(underlying)
        failures = int(row.get("failures", 0)) + 1
        delay = min(self.scheduler_backoff_max_seconds,
                    self.scheduler_backoff_base_seconds * (2 ** min(failures - 1, 3)))
        row.update({
            "status": "FAILED_BACKOFF",
            "failures": failures,
            "last_full_audit_cycle": self._scheduler_cycle,
            "next_retry_at": time.time() + delay,
            "last_error": str(detail)[:240],
        })
        self.state.underlyings.setdefault(underlying, {})["scheduler"] = self._scheduler_public_state(underlying)

    def _structural_prefilter(self, underlying: str, chain: OptionChainSnapshot, now: datetime) -> tuple[bool, str, dict[str, Any]]:
        """Cheap quote admissibility check used only to budget depth requests.

        This is not a trading gate. Core and audit-lane instruments always
        receive depth. Opportunity-lane instruments may defer depth when every
        nearest strike is clearly unusable, while the full candidate path still
        records the defer reason and the next audit is guaranteed.
        """
        cfg = self.cfg.get("monitoring", {})
        max_spread = float(cfg.get("structural_prefilter_max_spread_pct", 8.0)) if isinstance(cfg, Mapping) else 8.0
        legs = []
        nearest = chain.nearest_strike()
        for strike in sorted(chain.strikes, key=lambda item: abs(item.strike - nearest))[:3]:
            for leg in (strike.ce, strike.pe):
                if leg is not None:
                    legs.append(leg)
        if not legs:
            return False, "STRUCTURAL_NO_NEAREST_OPTION_LEGS", {"legs": 0}
        fresh_valid = 0
        acceptable = 0
        for leg in legs:
            quote = leg.quote
            if quote.bid <= 0 or quote.ask <= quote.bid or quote.mid <= 0:
                continue
            try:
                age = max(0.0, (now - quote.timestamp).total_seconds())
            except Exception:
                age = 999.0
            if age > 8.0:
                continue
            fresh_valid += 1
            spread_pct = quote.spread / quote.mid * 100.0
            if spread_pct <= max_spread:
                acceptable += 1
        details = {"legs": len(legs), "fresh_valid": fresh_valid, "acceptable_spread": acceptable, "max_spread_pct": max_spread}
        if fresh_valid == 0:
            return False, "STRUCTURAL_NO_FRESH_VALID_QUOTES", details
        if acceptable == 0:
            return False, "STRUCTURAL_ALL_SPREADS_TOO_WIDE", details
        return True, "STRUCTURAL_QUOTES_ADMISSIBLE", details

    def _scheduler_priority(self, underlying: str, now: float) -> tuple[float, str]:
        row = self._scheduler_entry(underlying)
        score = 0.0
        if int(row.get("last_full_audit_cycle", -1)) < 0:
            score += 100.0
        if int(row.get("last_success_cycle", -1)) >= 0:
            age = max(0, self._scheduler_cycle - int(row.get("last_success_cycle", -1)))
            score += min(50.0, float(age) * 5.0)
        if str(row.get("status")) == "SUCCESS":
            score += 10.0
        if int(row.get("failures", 0)):
            score -= min(25.0, float(row.get("failures", 0)) * 5.0)
        if now >= float(row.get("next_retry_at", 0.0) or 0.0):
            score += 15.0
        return score, underlying

    def _cycle_underlyings(self) -> list[str]:
        """Return core names plus a priority-ordered expanded paper batch.

        Every configured trade-enabled instrument remains in the 59-instrument
        paper universe. This scheduler only controls request order and bounded
        retry timing. Core indices are always refreshed. Expanded instruments
        with repeated structural failures enter a bounded backoff, but each is
        forced through a full audit before ``max_full_audit_cycles`` expires.
        """
        all_trade = self._trade_underlyings()
        rotation_cfg = self.cfg.get("monitoring", {})
        rotation_enabled = bool(rotation_cfg.get("paper_trade_rotation_enabled", True)) if isinstance(rotation_cfg, Mapping) else True
        self._scheduler_cycle += 1
        if not rotation_enabled or not self.staged_scheduler_enabled:
            self.state.underlyings["_paper_schedule"] = {
                "mode": "ALL_CONFIGURED_UNDERLYINGS" if not rotation_enabled else "CORE_PLUS_ROTATING_EXPANDED",
                "selected": all_trade,
                "deferred": [],
                "total_paper_underlyings": len(all_trade),
                "scheduler_cycle": self._scheduler_cycle,
            }
            return all_trade
        core = [und for und in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY") if und in all_trade]
        monitor_only = [und for und, meta in self.universe.items()
                        if bool(meta.get("monitor_only", False)) and und not in core]
        expanded = [und for und in all_trade if und not in core] + monitor_only
        if not expanded:
            return all_trade
        batch_size = max(1, int(rotation_cfg.get("paper_trade_batch_size", self.monitor_batch_size))) if isinstance(rotation_cfg, Mapping) else self.monitor_batch_size
        now_mono = time.monotonic()
        if self._last_monitor_batch and now_mono - self._last_monitor_refresh < self.monitor_poll_seconds:
            selected = core + self._last_monitor_batch
            self.state.underlyings["_paper_schedule"] = {
                "mode": "CORE_PLUS_PRIORITY_LANES",
                "batch_size": batch_size,
                "total_paper_underlyings": len(all_trade),
                "selected": selected,
                "core": core,
                "last_batch": list(self._last_monitor_batch),
                "deferred": [],
                "scheduler_cycle": self._scheduler_cycle,
                "next_refresh_in_sec": round(max(0.0, self.monitor_poll_seconds - (now_mono - self._last_monitor_refresh)), 1),
                "max_full_audit_cycles": self.scheduler_max_audit_cycles,
            }
            return selected
        now = time.time()
        due: list[tuple[float, str, str]] = []
        deferred: list[dict[str, Any]] = []
        for und in expanded:
            row = self._scheduler_entry(und)
            retry_ready = now >= float(row.get("next_retry_at", 0.0) or 0.0)
            audit_due = int(row.get("last_full_audit_cycle", -1)) < 0 or (
                self._scheduler_cycle - int(row.get("last_full_audit_cycle", -1)) >= self.scheduler_max_audit_cycles
            )
            if retry_ready or audit_due:
                priority, _ = self._scheduler_priority(und, now)
                lane = "AUDIT" if audit_due else "OPPORTUNITY"
                due.append((priority, und, lane))
            else:
                reason = "FAILURE_BACKOFF"
                row["last_deferred_reason"] = reason
                deferred.append({"underlying": und, "lane": "AUDIT", "reason": reason,
                                 "retry_at": datetime.fromtimestamp(float(row.get("next_retry_at", 0.0)), timezone.utc).isoformat()})
                if self._scheduler_cycle - int(row.get("last_deferred_event_cycle", -1)) >= self.scheduler_max_audit_cycles:
                    row["last_deferred_event_cycle"] = self._scheduler_cycle
                    self.event_ledger.append(
                        "PAPER_INSTRUMENT_DEFERRED", session_id=self.state.session_id,
                        underlying=und, exchange=self.universe.get(und, {}).get("exchange", "NSE"),
                        instrument_kind=self.universe.get(und, {}).get("instrument_kind", "INDEX"),
                        instrument_class=class_for_metadata(self.universe.get(und, {}).get("exchange", "NSE"), self.universe.get(und, {}).get("instrument_kind", "INDEX")),
                        decision_source="staged_scheduler", ts=now_ist(),
                        payload={"lane": "AUDIT", "reason": reason, "scheduler_cycle": self._scheduler_cycle},
                    )
        order = {und: index for index, und in enumerate(expanded)}
        rotation_start = self._monitor_cursor % len(expanded)
        due.sort(key=lambda item: (
            -item[0],
            (order[item[1]] - rotation_start) % len(expanded),
            item[1],
        ))
        selected = [und for _, und, _ in due[:min(batch_size, len(due))]]
        self._monitor_cursor = (rotation_start + min(batch_size, len(due))) % len(expanded)
        for und in core:
            self._scheduler_entry(und)["lane"] = "CORE"
        for _, und, lane in due[:min(batch_size, len(due))]:
            row = self._scheduler_entry(und)
            row["lane"] = lane
            row["last_attempt_cycle"] = self._scheduler_cycle
            row["last_deferred_reason"] = ""
        for _, und, lane in due[min(batch_size, len(due)):]:
            self._scheduler_entry(und)["lane"] = lane
        deferred.extend({"underlying": und, "lane": lane, "reason": "BATCH_LIMIT"}
                        for _, und, lane in due[min(batch_size, len(due)):])
        self._last_monitor_batch = selected
        self._last_monitor_refresh = now_mono
        self.state.underlyings["_paper_schedule"] = {
            "mode": "CORE_PLUS_PRIORITY_LANES",
            "batch_size": batch_size,
            "total_paper_underlyings": len(all_trade),
            "selected": core + selected,
            "core": core,
            "opportunity_lane": [und for _, und, lane in due if lane == "OPPORTUNITY"],
            "audit_lane": [und for _, und, lane in due if lane == "AUDIT"],
            "deferred": deferred,
            "scheduler_cycle": self._scheduler_cycle,
            "max_full_audit_cycles": self.scheduler_max_audit_cycles,
            "failure_backoff_seconds": [self.scheduler_backoff_base_seconds, self.scheduler_backoff_max_seconds],
        }
        return core + selected

    def _load_master(self) -> FyersSymbolMaster:
        masters = []
        for exchange in self._configured_exchanges():
            master_path = self.state_dir / f"{exchange}_FO.csv"
            path = self.client.fetch_symbol_master(master_path, exchange=exchange)
            masters.append(FyersSymbolMaster.from_csv(
                path,
                allowed_exchanges={exchange},
                allowed_underlyings=set(self.universe),
            ))
        master = FyersSymbolMaster.combine(*masters)
        self._record_master_provenance(master)
        for und, meta in self.universe.items():
            exps = master.expiry_dates(und)
            mode = "MONITOR_ONLY" if meta.get("monitor_only") else ("TRADE_ELIGIBLE" if meta.get("trade_enabled", True) else "DISABLED")
            self._log(f"  {und} [{meta.get('exchange', 'NSE')}, {mode}]: {len(exps)} expiries, nearest {exps[0] if exps else '-'}")
        return master

    def _record_master_provenance(self, master: FyersSymbolMaster) -> None:
        """Persist exact master-file hashes and per-instrument metadata coverage."""
        files = []
        for exchange in self._configured_exchanges():
            path = self.state_dir / f"{exchange}_FO.csv"
            if not path.exists():
                continue
            stat = path.stat()
            files.append({
                "exchange": exchange,
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, IST).isoformat(),
            })
        coverage = {}
        for underlying in sorted(self.universe):
            instruments = [item for item in master.instruments if item.underlying.upper() == underlying.upper()]
            coverage[underlying] = {
                "contract_rows": len(instruments),
                "expiry_count": len(master.expiry_dates(underlying)),
                "has_ce": any(item.option_type == "CE" for item in instruments),
                "has_pe": any(item.option_type == "PE" for item in instruments),
                "lot_sizes": sorted({int(item.lot_size) for item in instruments}),
                "tick_sizes": sorted({float(item.tick_size) for item in instruments}),
            }
        payload = {"captured_at": now_ist().isoformat(), "files": files, "coverage": coverage}
        out = self.state_dir / "master_provenance.json"
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(out)
        self.run_manifest["master_provenance"] = payload
        manifest_path = self.state_dir / "run_manifest.json"
        manifest_tmp = manifest_path.with_suffix(".tmp")
        manifest_tmp.write_text(json.dumps(self.run_manifest, indent=2, sort_keys=True), encoding="utf-8")
        manifest_tmp.replace(manifest_path)

    # -- main loop ---------------------------------------------------------------

    def run_forever(self, stop_event: Optional[threading.Event] = None) -> None:
        self._log("Loop started.")
        try:
            while stop_event is None or not stop_event.is_set():
                try:
                    self.run_one_cycle()
                except Exception as e:  # keep the loop alive, but block new entries during stabilization
                    self.state.last_cycle_ok = False
                    self.state.cycle_in_progress = False
                    self.state.last_error = f"{type(e).__name__}: {e}"
                    self._incident_reason = f"Cycle failure: {self.state.last_error}"
                    stable_wait = float(self.config.section("data_health").get("reconnect_stable_wait_sec", 30.0))
                    self._incident_block_until = time.time() + max(0.0, stable_wait)
                    self._log(f"Cycle error; new entries blocked for {stable_wait:.1f}s: {self.state.last_error}")
                wait = self.poll_seconds if self.state.market_open else self._seconds_to_open()
                if wait > 0:
                    time.sleep(min(wait, self.poll_seconds if self.state.market_open else 60.0))
        finally:
            if self._capture_file is not None:
                try:
                    self._capture_file.close()
                except Exception:
                    pass

    def _positions(self) -> list[OpenPosition]:
        positions = list(getattr(self.state, "open_positions", []) or [])
        if not positions and self.state.open_position is not None:
            positions = [self.state.open_position]
        return positions

    def _has_open_positions(self) -> bool:
        return bool(self._positions())

    def _primary_open_position(self) -> Optional[OpenPosition]:
        positions = self._positions()
        return positions[0] if positions else None

    def _max_concurrent_paper_positions(self) -> int:
        try:
            return max(1, min(5, int(self.cfg.get("max_concurrent_paper_positions", 2))))
        except (TypeError, ValueError):
            return 2

    def _capacity_available(self) -> bool:
        return len(self._positions()) < self._max_concurrent_paper_positions()

    def _sync_position_alias(self) -> None:
        self.state.open_positions = list(self._positions())
        self.state.open_position = self.state.open_positions[0] if self.state.open_positions else None

    def _add_open_position(self, position: OpenPosition) -> bool:
        positions = self._positions()
        if len(positions) >= self._max_concurrent_paper_positions():
            return False
        if any(item.trade.trade_id == position.trade.trade_id for item in positions):
            return False
        positions.append(position)
        self.state.open_positions = positions
        self._sync_position_alias()
        return True

    def _remove_open_position(self, position: OpenPosition) -> None:
        positions = [item for item in self._positions() if item.trade.trade_id != position.trade.trade_id]
        self.state.open_positions = positions
        self._sync_position_alias()

    def run_one_cycle(self) -> None:
        now = now_ist()
        # Clear only the global cycle-failure field. Instrument-level warnings
        # remain in each underlying's chain/depth health and evidence records.
        self.state.last_error = ""
        self.state.cycle_in_progress = True
        self.state.cycle_started_at = now.isoformat()
        self._roll_daily_risk_state(now)
        self._risk_context = self._load_risk_context()
        self._refresh_daily_controls(now)
        self.state.market_open = self._market_open(now)
        if not self.state.market_open:
            if self._has_open_positions() and now.weekday() < 5 and now.hour * 60 + now.minute > 15 * 60 + 30:
                self._force_close_end_of_day(now)
            self.state.last_cycle = now.isoformat()
            self.state.cycle_in_progress = False
            return
        chains: dict[str, OptionChainSnapshot] = {}
        vix_map: dict[str, Optional[float]] = {}
        context_map = {}
        payloads: dict[str, Any] = {}
        histories: dict[str, Any] = {}
        depth_payloads: dict[str, Any] = {}
        self._depth_payloads = depth_payloads
        cas_snapshot: dict[str, Any] = {}
        for und in self._cycle_underlyings():
            meta = self.universe[und]
            try:
                payload = self.client.option_chain(meta["index_symbol"], self.strikecount)
                payloads[und] = payload
                # The cycle start can be tens of seconds old after serial
                # collection across the universe. Timestamp the chain at its
                # own HTTP receipt time so freshness is measured honestly per
                # instrument; depth and entry revalidation remain independent.
                chain_received_at = now_ist()
                cal = parse_expiry_calendar(payload)
                expiry = self._select_expiry(und, cal, bool(meta.get("prefer_monthly", False)))
                chain = FyersOptionChainParser.parse(payload, und, expiry, chain_received_at)
                scheduler_lane = str(self._scheduler_entry(und).get("lane", "AUDIT"))
                if self.staged_scheduler_enabled and scheduler_lane == "OPPORTUNITY":
                    prefilter_ok, prefilter_reason, prefilter_details = self._structural_prefilter(und, chain, now)
                    self.state.underlyings.setdefault(und, {})["prefilter"] = {
                        "status": "ADMISSIBLE" if prefilter_ok else "DEFERRED",
                        "reason": prefilter_reason,
                        "details": prefilter_details,
                        "lane": scheduler_lane,
                        "timestamp": now.isoformat(),
                    }
                    if not prefilter_ok:
                        self._scheduler_mark_deferred(und, prefilter_reason, prefilter_details)
                        self._log(f"  {und} structural prefilter deferred: {prefilter_reason}")
                        continue
                chain = self._enrich_fyers_depth(und, chain, payload)
                depth_health = self.state.underlyings.get(und, {}).get("depth_health", {})
                feed_report = assess_fyers_payload(
                    payload, chain=chain,
                    depth_status=str(depth_health.get("status", "UNKNOWN")),
                    market_open=True,
                )
                self.state.underlyings.setdefault(und, {})["feed_health"] = feed_report.to_dict()
                if self._derived_iv_research_enabled():
                    self.state.underlyings[und]["derived_iv_research"] = self._derived_iv_research_snapshot(chain)
                vix = parse_india_vix(payload)
                chains[und] = chain
                vix_map[und] = vix
                history = self._fetch_history(und, meta["index_symbol"])
                histories[und] = history
                direction_inputs = self._direction_model_histories(und)
                context_map[und] = self.signal.compute_context(
                    chain, vix, now, history_candles=history,
                    direction_model_inputs=direction_inputs,
                )
                self._scheduler_mark_success(und)
            except Exception as e:
                detail = f"{type(e).__name__}: {e}"
                reason_code = "OPTIONS_CHAIN_UNAVAILABLE" if "optionsChain" in str(e) else "OPTIONS_CHAIN_ERROR"
                self._scheduler_mark_failure(und, detail)
                self.state.underlyings[und] = {
                    "error": detail,
                    "chain_health": {
                        "source": "FYERS_OPTIONS_CHAIN",
                        "status": "UNAVAILABLE",
                        "reason_code": reason_code,
                        "detail": detail,
                        "fail_closed": True,
                    },
                }
                self._log(f"  {und} chain unavailable [{reason_code}]: {detail}")
        if not chains:
            raise RuntimeError("No underlying chains fetched this cycle.")
        if self._capture_file is not None:
            self._capture_cycle(payloads, histories, now, depth_payloads)
        try:
            cas_snapshot = self.cas_monitor.observe(chains, now_ist(), self.universe, self.state.session_id)
            self.state.underlyings["_cas_monitor"] = cas_snapshot
            if not self._has_open_positions() and cas_snapshot.get("new_event"):
                self._enter_cas_paper_position(chains, context_map, cas_snapshot, now_ist())
        except Exception as exc:
            self.state.underlyings["_cas_monitor"] = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}", "paper_only": True}
            self._log(f"  CAS monitor failed: {type(exc).__name__}: {exc}")
        self._update_playbook_filters(context_map, now)
        self.state.underlyings["_risk_context"] = dict(self._risk_context)
        for und, chain in chains.items():
            meta = self.universe.get(und, {})
            if meta.get("monitor_only", False):
                try:
                    instrument_kind = meta.get("instrument_kind", "INDEX")
                    exchange = meta.get("exchange", "NSE")
                    monitor_lot = None
                    try:
                        monitor_expiry = date.fromisoformat(chain.expiry[:10])
                        monitor_lot = self.master.lot_size(und, monitor_expiry)
                    except Exception:
                        pass
                    self.evidence.record_monitor_snapshot(
                        underlying=und,
                        exchange=exchange,
                        chain=chain,
                        context=context_map[und],
                        vix=vix_map.get(und),
                        instrument_kind=instrument_kind,
                        lot_size=monitor_lot,
                        lifecycle_state=self.lifecycle_states.get(und, InstrumentLifecycle.MONITOR.value),
                        ts=now,
                    )
                    self._observe_monitor_calibration(und, chain, meta, now)
                    self.event_ledger.append(
                        "MONITOR_SNAPSHOT", session_id=self.state.session_id,
                        underlying=und, exchange=exchange, instrument_kind=instrument_kind,
                        instrument_class=class_for_metadata(exchange, instrument_kind),
                        lifecycle_state=self.lifecycle_states.get(und, InstrumentLifecycle.MONITOR.value),
                        decision_source="monitor_diagnostics", ts=now,
                        payload={"expiry": chain.expiry, "strike_count": len(chain.strikes)},
                    )
                except Exception as e:
                    self._log(f"  monitor diagnostics failed for {und}: {e}")
            else:
                try:
                    self._observe_monitor_calibration(und, chain, meta, now)
                except Exception as e:
                    self._log(f"  trade-universe calibration observation failed for {und}: {e}")

        self._refresh_lifecycle_states()
        self._update_chain_display(chains, vix_map, context_map)
        self._record_shadow_cycle(chains, context_map, now)

        # Manage the open position with fresh bars before considering new entries.
        # Existing positions remain managed after the entry window closes.
        self._manage_open_position(chains, context_map)

        # Build candidates from all fresh chains and select only inside the
        # configured entry window.  Outside the window we still fetch data and
        # manage an open position, but do not create new exposure.
        if self._capacity_available() and self._entry_window_open(now):
            self.state.underlyings.pop("_entry_window", None)
            self._select_and_enter(chains, context_map, histories)
        elif not self._has_open_positions():
            self.state.underlyings["_entry_window"] = {
                "status": "CLOSED",
                "reason": "New entries disabled outside configured entry window",
                "timestamp": now.isoformat(),
            }
            # The experimental lane is research-only by configuration. It must
            # continue collecting breakout evidence outside the canonical entry
            # window, but it must never route an entry from this branch.
            try:
                experimental_candidates = self._build_candidates(chains, context_map)
                experimental_evaluations = tuple()
                if experimental_candidates:
                    experimental_state = PaperPortfolioState(
                        open_positions_count=0,
                        pending_orders_count=0,
                        realized_loss_today=0.0,
                    )
                    experimental_evaluations = self.scorer_engine.evaluate_and_select(
                        experimental_candidates, state=experimental_state,
                    ).evaluations
                self._evaluate_experimental_impulse_breakouts(
                    chains, context_map, histories, experimental_evaluations, now,
                    portfolio_blocked=False,
                )
            except Exception as exc:
                self._log(f"  experimental impulse collection outside entry window failed: {exc}")
        try:
            forward_rows = self.evidence.observe_skipped_forward(chains, now)
            self.calibration.record_forward_outcomes(forward_rows, cost_model_valid=self._cost_model_valid)
            self.state.underlyings["_no_trade_alpha"] = self.evidence.no_trade_alpha_snapshot()
        except Exception as e:
            self._log(f"  skipped forward observation failed: {e}")

        self.state.last_cycle = now_ist().isoformat()
        self.state.last_cycle_ok = True
        self.state.cycle_in_progress = False
        self._update_equity()

    # -- candidate building + selection -----------------------------------------

    def _record_data_health_observation(self, underlying: str, health: DataHealth, now: datetime, scope: str) -> None:
        """Persist stale/invalid transitions so repeated feed failures are visible."""
        target = self.state.underlyings.setdefault(underlying, {})
        prior = dict(target.get("stale_data_alert", {}))
        threshold = max(1, int(self.config.section("data_health").get("stale_alert_consecutive_cycles", 2)))
        was_alert = str(prior.get("status", "CLEAR")) == "ALERT"
        if health.valid and not health.warning:
            alert = {
                "status": "CLEAR",
                "consecutive_bad_cycles": 0,
                "last_valid_at": now.isoformat(),
                "last_bad_at": prior.get("last_bad_at", ""),
                "last_reason": health.reason or "",
                "scope": scope,
            }
        else:
            consecutive = int(prior.get("consecutive_bad_cycles", 0) or 0) + 1
            status = "ALERT" if consecutive >= threshold else "OBSERVING"
            alert = {
                "status": status,
                "consecutive_bad_cycles": consecutive,
                "alert_threshold_cycles": threshold,
                "last_valid_at": prior.get("last_valid_at", ""),
                "last_bad_at": now.isoformat(),
                "last_reason": health.reason or "Data health warning",
                "scope": scope,
            }
            if status == "ALERT" and not was_alert:
                self._log(f"  DATA HEALTH ALERT {underlying}: {alert['last_reason']}")
                self.event_ledger.append(
                    "DATA_HEALTH_ALERT", session_id=self.state.session_id,
                    underlying=underlying,
                    exchange=self.universe.get(underlying, {}).get("exchange", "NSE"),
                    instrument_kind=self.universe.get(underlying, {}).get("instrument_kind", "INDEX"),
                    instrument_class=class_for_metadata(
                        self.universe.get(underlying, {}).get("exchange", "NSE"),
                        self.universe.get(underlying, {}).get("instrument_kind", "INDEX"),
                    ),
                    decision_source="data_health_orchestrator", ts=now,
                    payload=alert,
                )
        target["stale_data_alert"] = alert

    def _enrich_fyers_depth(self, underlying: str, chain: OptionChainSnapshot, payload: Mapping[str, Any]) -> OptionChainSnapshot:
        """Merge read-only Fyers depth into the bounded candidate strikes.

        The option-chain endpoint supplies broad strike coverage but omits
        quantities.  Fyers' separate `/data/depth` endpoint supplies the exact
        symbol's level-one and five-level book.  We request depth only for the
        nearest three strikes (the same bounded set used by CandidateFactory),
        preserving all-59 chain collection while avoiding an unbounded request
        fan-out.  Any missing or malformed depth remains invalid rather than
        being inferred.
        """
        depth_method = getattr(self.client, "market_depth", None)
        if not callable(depth_method):
            self.state.underlyings.setdefault(underlying, {})["depth_health"] = {
                "source": "FYERS_MARKET_DEPTH",
                "status": "UNAVAILABLE",
                "reason": "Depth client method unavailable",
                "requested_legs": 0,
                "successful_legs": 0,
                "failed_legs": 0,
                "five_level_legs": 0,
            }
            return chain
        raw_data = payload.get("data", {}) if isinstance(payload, Mapping) else {}
        raw_rows = raw_data.get("optionsChain", []) if isinstance(raw_data, Mapping) else []
        symbols: dict[tuple[float, str], str] = {}
        for raw in raw_rows:
            if not isinstance(raw, Mapping):
                continue
            option_type = str(raw.get("option_type", "")).upper()
            raw_symbol = str(raw.get("symbol", "")).strip()
            try:
                strike = float(raw.get("strike_price"))
            except (TypeError, ValueError):
                continue
            if option_type in {"CE", "PE"} and strike > 0 and raw_symbol:
                symbols[(strike, option_type)] = raw_symbol
        target_strikes = set(sorted((s.strike for s in chain.strikes), key=lambda strike: abs(strike - chain.nearest_strike()))[:3])
        requested = successful = five_level = failed = 0
        rate_limit_errors = api_errors = 0
        last_error = ""
        failure_reasons: list[str] = []

        def _levels(raw: Any, side: str) -> list[dict[str, float]]:
            if not isinstance(raw, list) or not raw:
                raise ValueError(f"Fyers depth {side} levels missing")
            out: list[dict[str, float]] = []
            for index, item in enumerate(raw):
                if not isinstance(item, Mapping):
                    raise ValueError(f"Fyers depth {side}[{index}] malformed")
                try:
                    price = float(item.get("price", 0.0))
                    volume = float(item.get("volume", 0.0))
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"Fyers depth {side}[{index}] numeric fields invalid") from exc
                if not math.isfinite(price) or not math.isfinite(volume) or volume < 0:
                    raise ValueError(f"Fyers depth {side}[{index}] numeric fields invalid")
                out.append({"price": price, "volume": volume})
            return out

        def _optional_int(raw: Any, fallback: int) -> int:
            if raw in (None, ""):
                return fallback
            try:
                value = float(raw)
                return int(value) if math.isfinite(value) and value >= 0 else fallback
            except (TypeError, ValueError):
                return fallback

        def _optional_float(raw: Any, fallback: Optional[float]) -> Optional[float]:
            if raw in (None, ""):
                return fallback
            try:
                value = float(raw)
                return value if math.isfinite(value) else fallback
            except (TypeError, ValueError):
                return fallback

        enriched_strikes: list[OptionStrike] = []
        for strike in chain.strikes:
            if strike.strike not in target_strikes:
                enriched_strikes.append(strike)
                continue
            legs: list[tuple[str, Optional[OptionLeg]]] = [("CE", strike.ce), ("PE", strike.pe)]
            new_legs: dict[str, Optional[OptionLeg]] = {}
            for side, leg in legs:
                if leg is None:
                    new_legs[side] = None
                    continue
                symbol = symbols.get((strike.strike, side), "")
                if not symbol:
                    new_legs[side] = leg
                    failed += 1
                    failure_reasons.append(f"{side}@{strike.strike}: depth symbol missing")
                    continue
                requested += 1
                try:
                    depth_payload = depth_method(symbol, ohlcv_flag=1)
                    if hasattr(self, "_depth_payloads"):
                        self._depth_payloads[symbol] = depth_payload
                    depth_data = depth_payload.get("d", {}) if isinstance(depth_payload, Mapping) else {}
                    depth = depth_data.get(symbol, {}) if isinstance(depth_data, Mapping) else {}
                    if not isinstance(depth, Mapping):
                        raise ValueError("Fyers depth symbol payload missing")
                    bids = _levels(depth.get("bids", []), "bid")
                    asks = _levels(depth.get("ask", depth.get("asks", [])), "ask")
                    best_bid = bids[0]
                    best_ask = asks[0]
                    bid = best_bid["price"]
                    ask = best_ask["price"]
                    bid_qty = int(best_bid["volume"])
                    ask_qty = int(best_ask["volume"])
                    if bid <= 0 or ask <= 0 or ask <= bid or bid_qty <= 0 or ask_qty <= 0:
                        raise ValueError("Fyers depth best quote invalid")
                    ltt = depth.get("ltt")
                    if ltt in (None, ""):
                        raise ValueError("Fyers depth source timestamp missing")
                    ltt_seconds = float(ltt)
                    if not math.isfinite(ltt_seconds) or ltt_seconds <= 0:
                        raise ValueError("Fyers depth source timestamp invalid")
                    depth_timestamp = datetime.fromtimestamp(ltt_seconds, timezone.utc)
                    valid_five_bid = len(bids) >= 5 and all(level["price"] > 0 and level["volume"] > 0 for level in bids[:5])
                    valid_five_ask = len(asks) >= 5 and all(level["price"] > 0 and level["volume"] > 0 for level in asks[:5])
                    if valid_five_bid and valid_five_ask:
                        cumulative_bid = int(sum(level["volume"] for level in bids[:5]))
                        cumulative_ask = int(sum(level["volume"] for level in asks[:5]))
                        five_level += 1
                    else:
                        cumulative_bid = cumulative_ask = None
                    last = _optional_float(depth.get("ltp"), leg.quote.last)
                    quote = replace(
                        leg.quote,
                        bid=bid,
                        ask=ask,
                        bid_qty=bid_qty,
                        ask_qty=ask_qty,
                        last=last,
                        timestamp=depth_timestamp,
                        cumulative_bid_qty_5depth=cumulative_bid,
                        cumulative_ask_qty_5depth=cumulative_ask,
                        source_timestamp_available=True,
                    )
                    depth_oi = _optional_int(depth.get("oi"), leg.oi)
                    depth_volume = _optional_int(depth.get("v"), leg.volume)
                    new_legs[side] = replace(
                        leg,
                        quote=quote,
                        source_timestamp=depth_timestamp,
                        oi=depth_oi,
                        volume=depth_volume,
                    )
                    successful += 1
                except Exception as exc:
                    failed += 1
                    if getattr(exc, "status_code", None) == 429:
                        rate_limit_errors += 1
                    else:
                        api_errors += 1
                    last_error = f"{type(exc).__name__}: {str(exc)[:180]}"
                    failure_reasons.append(f"{symbol}: {last_error}")
                    new_legs[side] = leg
                    self._log(f"  {underlying} {symbol} depth unavailable: {last_error}")
            enriched_strikes.append(OptionStrike(strike.strike, new_legs["CE"], new_legs["PE"]))
        client_stats = {}
        stats_method = getattr(self.client, "depth_stats", None)
        if callable(stats_method):
            try:
                client_stats = stats_method()
            except Exception:
                client_stats = {}
        status = "APPLIED" if successful and not failed else "PARTIAL" if successful else "UNAVAILABLE"
        self.state.underlyings.setdefault(underlying, {})["depth_health"] = {
            "source": "FYERS_MARKET_DEPTH",
            "status": status,
            "requested_legs": requested,
            "successful_legs": successful,
            "failed_legs": failed,
            "five_level_legs": five_level,
            "rate_limit_errors": rate_limit_errors,
            "api_errors": api_errors,
            "last_error": last_error,
            "failure_reasons": failure_reasons[-20:],
            "client_stats": client_stats,
            "candidate_strikes": sorted(target_strikes),
        }
        return replace(chain, strikes=tuple(enriched_strikes))

    def _derived_iv_research_enabled(self) -> bool:
        cfg = self.config.raw.get("derived_iv_research", {}) if isinstance(self.config.raw, Mapping) else {}
        return bool(cfg.get("enabled", False)) if isinstance(cfg, Mapping) else False

    def _derived_iv_research_snapshot(self, chain: OptionChainSnapshot) -> dict[str, Any]:
        """Compute labelled theoretical IV for research only; never mutates candidates."""
        atm = chain.nearest_strike()
        row: dict[str, Any] = {"status": "DERIVED_RESEARCH_ONLY", "source": "DERIVED_BLACK_SCHOLES_RESEARCH", "strike": atm, "legs": {}}
        for side, leg in (("CE", chain.leg_at(atm, OptionType.CE)), ("PE", chain.leg_at(atm, OptionType.PE))):
            result = implied_volatility(leg.quote.mid, chain.underlying_price, atm, chain.expiry, side, valuation_time=chain.timestamp)
            row["legs"][side] = {"value": result.value, "status": result.status, "reason": result.reason}
        return row

    def _evaluate_chain_health(self, chain, scope: str = "trade", now: Optional[datetime] = None) -> DataHealth:
        """Evaluate chain health, scoping the Fyers timestamp exception safely.

        Calibration may turn only the chain-level CE/PE observation-time
        mismatch into a warning. Leg-level quote validity, positive depth,
        source timestamp, freshness, and revalidation remain hard gates.
        """
        observed_at = now or now_ist()
        calibration_scope = scope == "calibration"
        health_orchestrator = (
            self.paper_calibration_data_health
            if calibration_scope and self.paper_calibration_data_health is not None
            else self.data_health
        )
        chain_health = health_orchestrator.evaluate_option_chain(chain, observed_at)
        if (
            calibration_scope
            and bool(self._paper_calibration_cfg().get("allow_chain_timestamp_mismatch_warnings", False))
            and not chain_health.valid
            and "CE/PE timestamp delta" in chain_health.reason
        ):
            return DataHealth(True, True, "Calibration warning: " + chain_health.reason)
        return chain_health

    def _build_candidates(self, chains, context_map, scope: str = "trade") -> list:
        if scope not in {"trade", "monitor", "calibration"}:
            raise ValueError(f"Unsupported candidate build scope: {scope}")
        calibration_scope = scope == "calibration"
        trade_scope = scope in {"trade", "calibration"}
        out = []
        if scope == "trade":
            self.state.underlyings["_prefiltered"] = 0
        for und, chain in chains.items():
            meta = self.universe.get(und, {})
            is_monitor = bool(meta.get("monitor_only", False))
            is_trade_enabled = bool(meta.get("trade_enabled", not is_monitor))
            lifecycle_state = self.lifecycle_states.get(
                und, InstrumentLifecycle.MONITOR.value if is_monitor else InstrumentLifecycle.TRADE_ELIGIBLE.value
            )
            if trade_scope and (not is_trade_enabled or lifecycle_state in {InstrumentLifecycle.MONITOR.value, InstrumentLifecycle.SHADOW.value, InstrumentLifecycle.RETIRED.value}):
                continue
            if scope == "monitor" and (not is_monitor or lifecycle_state == InstrumentLifecycle.RETIRED.value):
                continue
            ctx = context_map[und]
            health_orchestrator = (
                self.paper_calibration_data_health
                if calibration_scope and self.paper_calibration_data_health is not None
                else self.data_health
            )
            chain_health = self._evaluate_chain_health(chain, scope=scope, now=now_ist())
            try:
                expiry = date.fromisoformat(chain.expiry[:10])
            except (ValueError, TypeError):
                self.state.underlyings.setdefault(und, {})["instrument_error"] = "Invalid chain expiry; candidate blocked"
                continue
            try:
                lot = self.master.lot_size(und, expiry)
                tick = self.master.tick_size(und, expiry)
            except Exception as e:
                self.state.underlyings.setdefault(und, {})["instrument_error"] = f"Missing master metadata: {e}"
                continue
            instrument_class = class_for_metadata(meta.get("exchange", "NSE"), meta.get("instrument_kind", "INDEX"))
            lifecycle_state = self.lifecycle_states.get(
                und, InstrumentLifecycle.MONITOR.value if is_monitor else InstrumentLifecycle.TRADE_ELIGIBLE.value
            )
            cctx = CandidateFactoryContext(
                futures_price=chain.underlying_price,
                spot_price=chain.underlying_price,
                instrument_direction_score=ctx.direction_score,
                trade_quality_score=ctx.trade_quality_score,
                regime_confidence=ctx.regime_confidence,
                market_hostility_score=ctx.market_hostility_score,
                atr_remaining_move=ctx.atr_remaining_move,
                regime_projected_move=ctx.regime_projected_move,
                required_move=ctx.required_move,
                dte=ctx.dte,
                calibration_direction=ctx.calibration_direction,
                calibration_liquidity=ctx.calibration_liquidity,
                exchange=meta.get("exchange", "NSE"),
                instrument_kind=meta.get("instrument_kind", "INDEX"),
                instrument_class=instrument_class,
                lifecycle_state=lifecycle_state,
                data_health=chain_health,
            )
            cands = self.factory.candidates_from_chain(chain, expiry, lot, tick, cctx)
            candidate_health_failures = 0
            candidate_health_reasons: list[str] = []
            setup_codes = self._playbook_codes_by_underlying.get(und)
            setup_grade = self._playbook_grades_by_underlying.get(und, "")
            if scope == "trade" and self.config.section("playbook_runtime").get("enforce_on_paper", False) and not setup_codes:
                continue
            setup_type = next(iter(setup_codes), "UNKNOWN") if setup_codes else "UNKNOWN"
            surface = OptionSurfaceDiagnostics.calculate(chain)
            for c in cands:
                c = replace(c, setup_type=setup_type, setup_grade=setup_grade)
                candidate_health = health_orchestrator.evaluate_candidate(c, now_ist())
                if not candidate_health.valid or candidate_health.warning:
                    candidate_health_failures += 1
                    if candidate_health.reason:
                        candidate_health_reasons.append(candidate_health.reason)
                combined_health = DataHealth(
                    valid=chain_health.valid and candidate_health.valid,
                    warning=chain_health.warning or candidate_health.warning,
                    reason="; ".join(reason for reason in (chain_health.reason, candidate_health.reason) if reason),
                )
                c = replace(c, data_health=combined_health)
                spread_pct = c.quote.spread / c.quote.mid * 100.0 if c.quote.mid > 0 else 99.0
                elasticity = self.observed_elasticity.update(
                    key=(und, c.instrument.expiry, c.instrument.strike, c.side.value),
                    timestamp=c.quote.timestamp,
                    underlying_price=chain.underlying_price,
                    quote=c.quote,
                    side=c.side,
                    delta=c.greeks.delta,
                )
                observed_premium_elasticity = (
                    float(elasticity.post_cost_delta_adjusted_elasticity)
                    if elasticity.confirmed and elasticity.post_cost_delta_adjusted_elasticity is not None
                    else 0.0
                )
                # Canonical candidates require confirmed observed elasticity.
                # The separate calibration lane may use the moneyness proxy only
                # for bounded paper collection, and labels it explicitly.
                entry_elasticity = observed_premium_elasticity
                proxies = self.signal.candidate_proxies(
                    chain, ctx, c.moneyness, c.side, spread_pct,
                    observed_elasticity=entry_elasticity,
                    real_gamma=c.greeks.gamma,
                    calibration_scope=calibration_scope,
                    execution_calculator=self.execution_quality,
                    underlying=c.instrument.underlying
                )
                notes = dict(c.notes)
                active_gates = self.calibration.gates_for(instrument_class, und)
                notes.update({
                    "gate_snapshot_id": active_gates.gate_snapshot_id,
                    "gate_learning_status": active_gates.gate_learning_status,
                    "gate_learning_observations": active_gates.gate_learning_observations,
                    "gate_learning_sessions": active_gates.gate_learning_sessions,
                    "gate_learning_outcomes": active_gates.gate_learning_outcomes,
                    "gate_contract_quality_min": active_gates.contract_quality_min,
                    "gate_direction_min": active_gates.direction_min,
                    "gate_premium_elasticity_min": active_gates.premium_elasticity_min,
                    "gate_expected_required_ratio_min": active_gates.expected_required_ratio_min,
                    "gate_trade_quality_min": active_gates.trade_quality_min,
                    "gate_final_confidence_min": active_gates.final_confidence_min,
                    "gate_market_hostility_max": active_gates.market_hostility_max,
                    "gate_iv_crush_max": active_gates.iv_crush_max,
                    "gate_spread_pct_max": active_gates.spread_pct_max,
                    "gate_min_top_book_lots": active_gates.min_top_book_lots,
                    "gate_min_5depth_lots_each_side": active_gates.min_5depth_lots_each_side,
                    "depth_evidence": (
                        "FIVE_LEVEL" if c.quote.cumulative_bid_qty_5depth is not None and c.quote.cumulative_ask_qty_5depth is not None
                        else "TOP_BOOK_ONLY" if c.quote.bid_qty > 0 and c.quote.ask_qty > 0
                        else "UNAVAILABLE"
                    ),
                    "depth_source": "FYERS_MARKET_DEPTH" if c.quote.source_timestamp_available else "UNAVAILABLE",
                    "depth_bid_levels": 5 if c.quote.cumulative_bid_qty_5depth is not None else 0,
                    "depth_ask_levels": 5 if c.quote.cumulative_ask_qty_5depth is not None else 0,
                    "gate_resolution_path": active_gates.gate_resolution_path,
                    "gate_optimization_method": active_gates.gate_optimization_method,
                    "gate_optimization_status": active_gates.gate_optimization_status,
                    "gate_optimization_quantile": active_gates.gate_optimization_quantile,
                    "gate_validation_observations": active_gates.gate_validation_observations,
                    "gate_validation_sessions": active_gates.gate_validation_sessions,
                    "gate_validation_expectancy_r": active_gates.gate_validation_expectancy_r,
                    "gate_validation_drawdown_r": active_gates.gate_validation_drawdown_r,
                    "gate_validation_retention": active_gates.gate_validation_retention,
                    "gate_last_validated_at": active_gates.gate_last_validated_at,
                    "setup_grade": setup_grade or "UNAVAILABLE",
                    "setup_grade_source": "PLAYBOOK_METADATA" if setup_grade else "SCORE_FALLBACK",
                })
                notes.update({
                    "observed_elasticity_valid": str(elasticity.valid),
                    "observed_elasticity_raw": "" if elasticity.raw_elasticity is None else f"{elasticity.raw_elasticity:.8f}",
                    "observed_elasticity_post_cost": "" if elasticity.post_cost_elasticity is None else f"{elasticity.post_cost_elasticity:.8f}",
                    "observed_elasticity_delta_adjusted": "" if elasticity.delta_adjusted_elasticity is None else f"{elasticity.delta_adjusted_elasticity:.8f}",
                    "observed_elasticity_post_cost_delta_adjusted": "" if elasticity.post_cost_delta_adjusted_elasticity is None else f"{elasticity.post_cost_delta_adjusted_elasticity:.8f}",
                    "observed_elasticity_confirmed": str(elasticity.confirmed),
                    "observed_elasticity_confirmation_count": elasticity.confirmation_count,
                    "observed_elasticity_status": "CONFIRMED" if elasticity.confirmed else "OBSERVED_NOT_CONFIRMED" if elasticity.valid else "UNAVAILABLE",
                    "observed_elasticity_reason": elasticity.reason,
                    "expiry_day": c.instrument.expiry == now_ist().date(),
                    "same_direction_recent_loss": self._same_direction_loss_active(und, c.side.value, now_ist()),
                    "entry_mode": "PAPER_CALIBRATION" if calibration_scope else "CANONICAL",
                    "research_only": bool(calibration_scope),
                    "calibration_premium_elasticity_proxy": f"{proxies.premium_elasticity:.8f}" if calibration_scope else "",
                    "surface_valid": str(surface.valid),
                    "atm_iv": "" if surface.atm_iv is None else f"{surface.atm_iv:.6f}",
                    "call_put_iv_skew": "" if surface.call_put_iv_skew is None else f"{surface.call_put_iv_skew:.6f}",
                    "call_wing_iv": "" if surface.call_wing_iv is None else f"{surface.call_wing_iv:.6f}",
                    "put_wing_iv": "" if surface.put_wing_iv is None else f"{surface.put_wing_iv:.6f}",
                    "surface_reason": surface.reason,
                    "direction_model_score": "" if ctx.direction_model_score is None else f"{ctx.direction_model_score:.4f}",
                    "direction_model_name": ctx.direction_model_name,
                    "direction_model_status": ctx.direction_model_status,
                    "direction_model_disagreement": "" if ctx.direction_model_disagreement is None else f"{ctx.direction_model_disagreement:.4f}",
                    "data_health_valid": str(c.data_health.valid),
                    "data_health_warning": str(c.data_health.warning),
                    "data_health_reason": c.data_health.reason,
                    "evidence_profile": str(self.config.raw.get("evidence_profiles", {}).get("active_profile", "UNSPECIFIED")),
                    "elasticity_status": str(self.config.raw.get("evidence_profiles", {}).get("elasticity_status", "UNSPECIFIED")),
                    "mapping_status": str(self.config.raw.get("evidence_profiles", {}).get("mapping_status", "UNSPECIFIED")),
                    "cost_model_status": self._cost_model_status,
                    "cost_model_valid": self._cost_model_valid,
                    "canonical_promotion_allowed": self._canonical_promotion_allowed(),
                    "liquidity_data_status": "MEASURED" if c.quote.bid_qty > 0 and c.quote.ask_qty > 0 and (c.quote.cumulative_bid_qty_5depth or 0) > 0 and (c.quote.cumulative_ask_qty_5depth or 0) > 0 else "LIQUIDITY_UNAVAILABLE",
                    "iv_data_status": "MEASURED" if c.greeks.iv is not None else "IV_UNAVAILABLE",
                    "iv_context_status": self.factory.market_context.status,
                    "iv_context_reason": self.factory.market_context.reason,
                    "iv_context_source": self.factory.market_context.source,
                    "iv_context_as_of": self.factory.market_context.as_of,
                    "iv_context_expires_at": self.factory.market_context.expires_at,
                })
                proxy_score = 0.5 * c.trade_quality_score + 0.5 * proxies.opportunity_confidence_score
                calibrated_probability, calibrated_expectancy, _ = self.calibration.outcome_calibration(
                    instrument_class, proxy_score
                )
                from .expected_value import ExpectedValueEngine
                ev_estimate = ExpectedValueEngine.from_calibrated_expectancy(
                    calibrated_expectancy, cost_model_valid=self._cost_model_valid,
                )
                notes.update({
                    "expected_value_status": ev_estimate.status,
                    "expected_value_reason": ev_estimate.reason,
                    "expected_value_r": "" if ev_estimate.expected_value_r is None else f"{ev_estimate.expected_value_r:.8f}",
                    "expected_value_cost_model_valid": self._cost_model_valid,
                })
                c = replace(c,
                    premium_elasticity=proxies.premium_elasticity,
                    expected_value_r=0.0 if ev_estimate.expected_value_r is None else float(ev_estimate.expected_value_r),
                    convexity_edge_score=proxies.convexity_edge_score,
                    execution_quality_score=proxies.execution_quality_score,
                    opportunity_confidence_score=proxies.opportunity_confidence_score,
                    regime_fit_score=proxies.regime_fit_score,
                    calibrated_success_probability=calibrated_probability,
                    calibrated_net_expectancy_r=calibrated_expectancy,
                    notes=notes,
                )

                # Spread-cost pre-filter: skip strikes the conservative paper
                # fill model would refuse at entry (wide OR pathologically tight
                # spreads), so un-fillable candidates never waste an evaluation
                # or selection cycle. Uses the real simulator -> exact match.
                probe = self.fill_sim.entry_buy(c.quote, c.instrument.tick_size)
                if not probe.filled:
                    if scope == "trade":
                        self.state.underlyings["_prefiltered"] = \
                            int(self.state.underlyings.get("_prefiltered", 0)) + 1
                    continue
                out.append(c)
            if candidate_health_failures or not chain_health.valid or chain_health.warning:
                health_for_alert = DataHealth(
                    valid=chain_health.valid and candidate_health_failures == 0,
                    warning=chain_health.warning or candidate_health_failures > 0,
                    reason="; ".join(reason for reason in (chain_health.reason, *candidate_health_reasons) if reason),
                )
            else:
                health_for_alert = chain_health
            self._record_data_health_observation(und, health_for_alert, now_ist(), scope)
        return out

    def _refresh_lifecycle_states(self) -> None:
        """Apply measured promotion rules without mutating the frozen trade universe."""
        for underlying, meta in self.universe.items():
            if not bool(meta.get("trade_enabled", not meta.get("monitor_only", False))):
                continue
            current = InstrumentLifecycle(self.lifecycle_states.get(underlying, InstrumentLifecycle.MONITOR.value))
            instrument_class = class_for_metadata(meta.get("exchange", "NSE"), meta.get("instrument_kind", "INDEX"))
            raw = self.calibration.instrument_metrics(underlying)
            metrics = PromotionMetrics(
                observations=raw["observations"], sessions=raw["sessions"],
                valid_quote_rate=raw["valid_quote_rate"], paper_fill_rate=raw["paper_fill_rate"],
                shadow_outcomes=raw["shadow_outcomes"], shadow_net_expectancy_r=raw["shadow_net_expectancy_r"],
                paper_trades=raw["paper_trades"], paper_net_expectancy_r=raw["paper_net_expectancy_r"],
                max_drawdown_r=raw["max_drawdown_r"],
            )
            decision = self.promotion.evaluate(instrument_class, current, metrics, monitor_only=bool(meta.get("monitor_only", False)))
            self.state.underlyings.setdefault(underlying, {})["promotion"] = {
                "current_state": decision.current_state.value,
                "recommended_state": decision.recommended_state.value,
                "allowed": decision.allowed,
                "trade_review_ready": decision.trade_review_ready,
                "reasons": list(decision.reasons),
                "metrics": raw,
            }
            if decision.recommended_state != current and decision.allowed:
                self.lifecycle_states[underlying] = decision.recommended_state.value
                self.calibration.set_lifecycle_state(underlying, decision.recommended_state)
                self.event_ledger.append(
                    "LIFECYCLE_TRANSITION", session_id=self.state.session_id,
                    underlying=underlying, exchange=meta.get("exchange", "NSE"),
                    instrument_kind=meta.get("instrument_kind", "INDEX"),
                    instrument_class=instrument_class,
                    lifecycle_state=decision.recommended_state.value,
                    decision_source="measured_promotion_engine", payload={
                        "from": current.value, "to": decision.recommended_state.value,
                        "reasons": decision.reasons,
                    },
                )

    def _observe_monitor_calibration(self, underlying: str, chain: OptionChainSnapshot,
                                     meta: Mapping[str, Any], now: datetime) -> None:
        """Measure class-level quote validity, spread, depth, freshness, and fills."""
        instrument_class = class_for_metadata(meta.get("exchange", "NSE"), meta.get("instrument_kind", "INDEX"))
        try:
            expiry = date.fromisoformat(chain.expiry[:10])
            lot = self.master.lot_size(underlying, expiry)
        except Exception:
            self.calibration.record_observation(instrument_class, now, False, False, None, None, None, stale=True, instrument_id=underlying)
            return
        atm = chain.nearest_strike()
        legs = []
        for side in (OptionType.CE, OptionType.PE):
            try:
                legs.append(chain.leg_at(atm, side))
            except Exception:
                pass
        if not legs:
            self.calibration.record_observation(instrument_class, now, False, False, None, None, None, stale=True, instrument_id=underlying)
            return
        for leg in legs:
            quote = leg.quote
            valid = quote.is_valid()
            try:
                age = max(0.0, (now - quote.timestamp).total_seconds())
            except Exception:
                age = 999.0
            stale = age > 8.0
            spread_pct = quote.spread / quote.mid * 100.0 if valid and quote.mid > 0 else None
            top_book_lots = min(quote.bid_qty, quote.ask_qty) / max(1, lot) if valid else None
            depth_lots = None
            if quote.cumulative_bid_qty_5depth is not None and quote.cumulative_ask_qty_5depth is not None:
                depth_lots = min(quote.cumulative_bid_qty_5depth, quote.cumulative_ask_qty_5depth) / max(1, lot)
            fill = self.fill_sim.entry_buy(quote, self.master.tick_size(underlying, expiry)) if valid else None
            self.calibration.record_observation(
                instrument_class, now, valid and not stale,
                bool(fill and fill.filled), spread_pct, top_book_lots, depth_lots, stale=stale,
                instrument_id=underlying,
            )

    def _record_shadow_cycle(self, chains, context_map, now: datetime) -> None:
        shadow_candidates = self._build_candidates(chains, context_map, scope="monitor")
        if not shadow_candidates:
            self.state.underlyings["_shadow_candidates"] = []
            return
        shadow_state = PaperPortfolioState(open_positions_count=0, pending_orders_count=0,
                                           realized_loss_today=max(0.0, -self.state.realized_pnl))
        result = self.scorer_engine.evaluate_and_select(shadow_candidates, state=shadow_state)
        self._update_candidate_display(result, key="_shadow_candidates")
        best_by_underlying = {}
        for evaluation in sorted(result.evaluations, key=lambda e: e.comparable_opportunity_score, reverse=True):
            best_by_underlying.setdefault(evaluation.candidate.instrument.underlying, evaluation)
        for evaluation in best_by_underlying.values():
            outcome = self.shadow_tracker.observe(evaluation, now)
            self.event_ledger.append(
                "SHADOW_CANDIDATE", session_id=self.state.session_id,
                underlying=evaluation.candidate.instrument.underlying,
                exchange=evaluation.candidate.instrument.exchange,
                instrument_kind=evaluation.candidate.instrument.instrument_kind,
                instrument_class=evaluation.candidate.instrument.instrument_class,
                lifecycle_state=evaluation.candidate.lifecycle_state,
                exposure_group=evaluation.candidate.exposure_group,
                decision_source="shadow_ranker", ts=now,
                payload={"score": evaluation.comparable_opportunity_score, "eligible": evaluation.eligible,
                         "reasons": evaluation.reasons},
            )
            if outcome is not None:
                costs = self.costs.round_trip_cost(
                    outcome.entry_price * outcome.lot_size,
                    outcome.exit_price * outcome.lot_size,
                ).total
                net = outcome.net_pnl_rupees - costs
                net_r = outcome.r_multiple
                if outcome.net_pnl_rupees:
                    net_r = outcome.r_multiple * (net / outcome.net_pnl_rupees)
                self.evidence.record_shadow_outcome(outcome, costs=costs)
                self.calibration.record_outcome(
                    outcome.instrument_class, outcome.score, net_r, net,
                    instrument_id=outcome.underlying, paper=False,
                    observed_at=now,
                    cost_model_valid=self._cost_model_valid,
                )
                self.event_ledger.append(
                    "SHADOW_OUTCOME", session_id=self.state.session_id,
                    underlying=outcome.underlying, instrument_class=outcome.instrument_class,
                    lifecycle_state=outcome.lifecycle_state, exposure_group=outcome.exposure_group,
                    decision_source="counterfactual_paper_fill", ts=now,
                    payload={"exit_reason": outcome.exit_reason, "net_pnl": net, "net_r": net_r},
                )
        if time.time() - self._last_shadow_cycle >= 60.0:
            self._last_shadow_cycle = time.time()
            try:
                self.evidence.record_shadow_candidates(result.evaluations, ts=now)
            except Exception as e:
                self._log(f"  shadow candidate evidence failed: {e}")

    @staticmethod
    def _gate_feature_snapshot(evaluation) -> dict[str, float]:
        return gate_feature_snapshot(evaluation)

    def _record_gate_observations(self, evaluations, now: datetime) -> None:
        for evaluation in evaluations:
            c = evaluation.candidate
            try:
                self.calibration.record_gate_observation(
                    c.instrument.underlying, c.instrument.instrument_class, now,
                    self._gate_feature_snapshot(evaluation), evaluation.eligible,
                    evaluation.comparable_opportunity_score,
                )
            except Exception as e:
                self._log(f"  gate observation failed for {c.instrument.underlying}: {e}")

    def _portfolio_no_trade_snapshot(self, evaluations, now: datetime) -> dict[str, Any]:
        cfg = self.config.section("portfolio_no_trade_engine")
        if not bool(cfg.get("enabled", True)):
            return {"enabled": False, "score": 0.0, "status": "DISABLED", "timestamp": now.isoformat()}
        if not evaluations:
            components = {
                "best_candidate_weakness_risk": 100.0,
                "cross_instrument_market_hostility": 100.0,
                "data_breadth_risk": 100.0,
                "liquidity_breadth_risk": 100.0,
                "event_gap_system_risk": 100.0,
                "recent_loss_psychology_risk": 0.0,
                "calibration_uncertainty_risk": 100.0,
            }
        else:
            contract_scores = [float(e.contract_quality.score) for e in evaluations]
            invalid_health = sum(1 for e in evaluations if not e.candidate.data_health.valid)
            invalid_liquidity = sum(1 for e in evaluations if not e.contract_quality.valid)
            unvalidated = sum(
                1 for e in evaluations
                if e.candidate.calibration_status_direction.value == "UNVALIDATED"
                or e.candidate.calibration_status_liquidity.value == "UNVALIDATED"
            )
            best_score = max(float(e.comparable_opportunity_score) for e in evaluations)
            hostility = sum(float(e.candidate.market_hostility_score) for e in evaluations) / len(evaluations)
            runtime_cfg = self.config.section("runtime_risk_controls")
            event_risk = 0.0
            if bool(runtime_cfg.get("enforce_on_paper", False)) and self._risk_context.get("status") != "VALID":
                event_risk = 100.0
            components = {
                "best_candidate_weakness_risk": max(0.0, min(100.0, 100.0 - best_score)),
                "cross_instrument_market_hostility": max(0.0, min(100.0, hostility)),
                "data_breadth_risk": 100.0 * invalid_health / len(evaluations),
                "liquidity_breadth_risk": 100.0 * invalid_liquidity / len(evaluations),
                "event_gap_system_risk": event_risk,
                "recent_loss_psychology_risk": max(0.0, min(100.0, self.state.loss_streak_today * 35.0 + self.state.losses_today * 15.0)),
                "calibration_uncertainty_risk": 100.0 * unvalidated / len(evaluations),
            }
        score = self.portfolio_no_trade.calculate(**components)
        shutdown = float(cfg.get("portfolio_no_trade_score_shutdown_above", 70.0))
        hard_vetoes = []
        if evaluations and bool(cfg.get("hard_vetoes", {}).get("three_or_more_instruments_data_invalid", False)):
            invalid_underlyings = {e.candidate.instrument.underlying for e in evaluations if not e.candidate.data_health.valid}
            invalid_count = len(invalid_underlyings)
            if invalid_count >= 3:
                hard_vetoes.append(f"{invalid_count}_instruments_data_invalid")
        return {
            "enabled": True,
            "score": score,
            "shutdown_above": shutdown,
            "status": "BLOCKED" if score >= shutdown or hard_vetoes else "CLEAR",
            "hard_vetoes": hard_vetoes,
            "components": components,
            "timestamp": now.isoformat(),
        }

    def _paper_calibration_cfg(self) -> Mapping[str, Any]:
        raw = self.cfg.get("paper_calibration", {})
        return raw if isinstance(raw, Mapping) else {}

    def _build_paper_calibration_engine(self) -> Optional[PaperOpportunityEngine]:
        """Build the bounded research-only selector on a cloned configuration.

        This lane may use proxy signal inputs and a wider research freshness
        window, but it keeps the real quote/depth/source-timestamp, contract,
        paper-fill, stop, and revalidation controls hard.
        """
        cfg = self._paper_calibration_cfg()
        if not bool(cfg.get("enabled", False)) or not bool(cfg.get("research_only", True)):
            return None
        raw = deepcopy(dict(self.config.raw))
        selection = dict(raw.get("opportunity_selection", {}))
        selection["excellent_opportunity_min_score"] = float(cfg.get("min_score", 40.0))
        selection["minimum_core_gate_score"] = float(cfg.get("min_core_gate_score", 50.0))
        selection["require_contract_quality_min"] = float(cfg.get("contract_quality_min", 70.0))
        selection["require_premium_elasticity_min"] = float(cfg.get("premium_elasticity_min", 0.30))
        selection["require_expected_required_ratio_min"] = float(cfg.get("expected_required_ratio_min", 1.10))
        selection["require_market_hostility_max"] = float(cfg.get("market_hostility_max", 55.0))
        selection["require_iv_crush_max"] = float(cfg.get("iv_crush_max", 70.0))
        excellent = dict(selection.get("excellent_gate_requirements", {}))
        excellent.update({
            "execution_quality_min": float(cfg.get("execution_quality_min", 60.0)),
            "convexity_edge_min": float(cfg.get("convexity_edge_min", 60.0)),
            "opportunity_confidence_min": float(cfg.get("opportunity_confidence_min", 60.0)),
            "regime_fit_min": float(cfg.get("regime_fit_min", 55.0)),
            "required_stop_must_be_configured": True,
        })
        selection["excellent_gate_requirements"] = excellent
        raw["opportunity_selection"] = selection

        scores = dict(raw.get("scores", {}))
        scores["direction_min"] = float(cfg.get("direction_min", 0.0))
        scores["trade_quality_min"] = float(cfg.get("trade_quality_min", 50.0))
        scores["final_confidence_min"] = float(cfg.get("final_confidence_min", 60.0))
        scores["regime_confidence_min"] = float(cfg.get("regime_confidence_min", 50.0))
        raw["scores"] = scores

        direction_models = dict(raw.get("phase1_direction_models", {}))
        direction_models["direction_bullish_permission"] = float(cfg.get("direction_min", 0.0))
        raw["phase1_direction_models"] = direction_models

        elasticity = dict(raw.get("premium_elasticity", {}))
        elasticity["reject_or_exit_threshold"] = float(cfg.get("premium_elasticity_min", 0.30))
        raw["premium_elasticity"] = elasticity
        expected = dict(raw.get("expected_move", {}))
        expected["hard_reject_ratio"] = float(cfg.get("expected_required_ratio_min", 1.10))
        raw["expected_move"] = expected

        # Calibration-only freshness policy. It is capped at 45 seconds by
        # construction and never changes canonical PARAMETERS.json.
        data_health = dict(raw.get("data_health", {}))
        max_quote_age = max(0.0, min(45.0, float(cfg.get("max_quote_age_seconds", 45.0))))
        max_chain_age = max(0.0, min(45.0, float(cfg.get("max_chain_age_seconds", 45.0))))
        data_health["option_quote_stale_invalid_sec"] = max_quote_age
        data_health["option_quote_stale_warning_sec"] = min(
            float(data_health.get("option_quote_stale_warning_sec", 5.0)),
            max_quote_age * 0.5,
        )
        data_health["option_chain_invalid_sec"] = max_chain_age
        data_health["option_chain_stale_entry_sec"] = min(
            float(data_health.get("option_chain_stale_entry_sec", 15.0)),
            max_chain_age * 0.5,
        )
        # Missing IV/delta and zero-volume/other chain semantic issues are
        # visible warnings in this research lane only. Quote validity,
        # positive bid/ask depth, source timestamp, per-leg freshness, and
        # revalidation remain hard gates.
        data_health["require_chain_semantics_for_approval"] = not bool(
            cfg.get("allow_chain_semantic_warnings", True)
        )
        raw["data_health"] = data_health

        revalidation = dict(raw.get("candidate_revalidation", {}))
        max_candidate_age = max(0.0, min(45.0, float(cfg.get("max_candidate_age_seconds", max_quote_age))))
        revalidation["normal_market_max_candidate_age_sec"] = max_candidate_age
        revalidation["fast_market_max_candidate_age_sec"] = max_candidate_age
        raw["candidate_revalidation"] = revalidation

        calibration_config = SystemConfig(raw)
        calibration_config.validate()
        return PaperOpportunityEngine(calibration_config, gate_provider=None)

    def _select_paper_calibration_candidate(self, chains, context_map, histories, now: datetime):
        cfg = self._paper_calibration_cfg()
        meta = {
            "enabled": bool(cfg.get("enabled", False)),
            "research_only": bool(cfg.get("research_only", True)),
            "entry_mode": "PAPER_CALIBRATION",
            "cost_model_valid": self._cost_model_valid,
            "status": "DISABLED",
            "timestamp": now.isoformat(),
        }
        if self.paper_calibration_engine is None:
            self.state.underlyings["_paper_calibration"] = meta
            return None
        if not self._cost_model_valid:
            meta.update({"status": "BLOCKED", "reason": "Calibration paper entry blocked: cost model is not validated"})
            self.state.underlyings["_paper_calibration"] = meta
            return None
        if not self._capacity_available():
            meta.update({"status": "BLOCKED", "reason": f"Concurrent paper-position capacity reached: {len(self._positions())}/{self._max_concurrent_paper_positions()}"})
            self.state.underlyings["_paper_calibration"] = meta
            return None
        max_entries = max(0, int(cfg.get("max_entries_per_day", 1)))
        if max_entries and self.state.trades_today >= max_entries:
            meta.update({
                "status": "BLOCKED",
                "reason": f"Calibration daily entry cap reached: {self.state.trades_today}/{max_entries}",
            })
            self.state.underlyings["_paper_calibration"] = meta
            return None
        candidates = self._build_candidates(chains, context_map, scope="calibration")
        # This is the calibration lane's only relaxed boundary: proxy scoring
        # may rank candidates, but a paper entry still requires valid quote,
        # positive top-book depth, source timestamp, and valid data health.
        safe = [
            c for c in candidates
            if c.data_health.valid
            and c.quote.is_valid()
            and c.quote.bid_qty > 0
            and c.quote.ask_qty > 0
            and c.quote.source_timestamp_available
        ]
        meta["evaluated_candidates"] = len(candidates)
        meta["safe_candidates"] = len(safe)
        if not safe:
            meta.update({
                "status": "NO_SAFE_CANDIDATE",
                "reason": "No candidate passed quote, depth, freshness, and source-timestamp checks",
            })
            self.state.underlyings["_paper_calibration"] = meta
            self.state.underlyings["_paper_calibration_candidates"] = []
            return None
        result = self.paper_calibration_engine.evaluate_and_select(
            safe,
            state=PaperPortfolioState(
                open_positions_count=len(self._positions()),
                pending_orders_count=0,
                realized_loss_today=0.0,
            ),
        )
        selected = result.selected
        self._record_qualified_opportunities(
            result.evaluations, now, lane="PAPER_CALIBRATION", selected=selected,
            portfolio_blocked=False,
        )
        if selected is not None and not self._candidate_is_armed(selected):
            meta.update({"status": "ARMING", "reason": "Candidate must pass two consecutive fresh qualified observations before paper entry"})
            selected = None
        self._update_candidate_display(result, key="_paper_calibration_candidates")
        meta.update({
            "status": "SELECTED" if selected is not None else meta.get("status", "NO_CALIBRATION_CANDIDATE"),
            "selected_underlying": selected.candidate.instrument.underlying if selected else "",
            "selected_side": selected.candidate.side.value if selected else "",
            "reason": "Selected bounded proxy candidate" if selected else "; ".join(result.reasons),
            "thresholds": {
                "score": float(cfg.get("min_score", 40.0)),
                "direction": float(cfg.get("direction_min", 0.0)),
                "premium_elasticity_proxy": float(cfg.get("premium_elasticity_min", 0.30)),
                "expected_required_ratio": float(cfg.get("expected_required_ratio_min", 1.10)),
                "contract_quality": float(cfg.get("contract_quality_min", 70.0)),
            },
        })
        self.state.underlyings["_paper_calibration"] = meta
        return selected

    def _select_and_enter(self, chains, context_map, histories: Optional[Mapping[str, list]] = None) -> None:
        now = now_ist()
        self.opportunity_learning.update_coverage(list(self.universe.keys()), chains, now)
        self.opportunity_learning.update_forward_outcomes(chains, now)
        if time.time() < self._incident_block_until:
            reason = f"{self._incident_reason}; reconnect stabilization in progress"
            self.state.underlyings["_incident"] = {"status": "BLOCKED", "reason": reason, "until": self._incident_block_until}
            self.event_ledger.append("INCIDENT_ENTRY_BLOCK", session_id=self.state.session_id, decision_source="incident_guard", ts=now, payload={"reason": reason})
            return
        if self._incident_block_until:
            self.state.underlyings.pop("_incident", None)
            self._incident_block_until = 0.0
            self._incident_reason = ""
        runtime_block = self._risk_context_block_reason()
        if runtime_block:
            self.state.underlyings["_runtime_risk"] = {"status": "BLOCKED", "reason": runtime_block, "context": dict(self._risk_context)}
            self.event_ledger.append(
                "RUNTIME_RISK_BLOCK", session_id=self.state.session_id,
                decision_source="runtime_risk_filter", ts=now,
                payload={"reason": runtime_block, "context": self._risk_context},
            )
            return
        self.state.underlyings.pop("_runtime_risk", None)
        risk_block = self._daily_risk_block_reason(now)
        if risk_block:
            self.state.underlyings["_daily_risk"] = {
                "status": "BLOCKED",
                "reason": risk_block,
                "trades_today": self.state.trades_today,
                "losses_today": self.state.losses_today,
                "realized_pnl_today": self.state.realized_pnl_today,
            }
            return
        self.state.underlyings.pop("_daily_risk", None)
        candidates = self._build_candidates(chains, context_map)
        if not candidates:
            self.state.underlyings["_candidates"] = []
            self._evaluate_experimental_impulse_breakouts(chains, context_map, histories or {}, tuple(), now, portfolio_blocked=False)
            return
        state = PaperPortfolioState(
            open_positions_count=0,
            pending_orders_count=0,
            # Shadow ranking is counterfactual and must not be suppressed by
            # the live paper portfolio's daily risk budget.
            realized_loss_today=0.0,
        )
        allowed_playbooks = None
        if self.config.section("playbook_runtime").get("enforce_on_paper", False):
            allowed_playbooks = set().union(*self._playbook_codes_by_underlying.values()) if self._playbook_codes_by_underlying else set()
        result = self.scorer_engine.evaluate_and_select(candidates, state=state, allowed_playbooks=allowed_playbooks)
        result = self._apply_gate_breakout_filter(result, now)
        self.state.underlyings["_data_quorum"] = self._data_quorum_snapshot(result.evaluations, now)
        self._record_gate_observations(result.evaluations, now)
        if result.decision == TradeDecision.NO_TRADE and any("ambiguous" in str(reason).lower() for reason in result.reasons):
            tie_payload = {
                "status": "UNRESOLVED",
                "reason": "Top candidates remained numerically identical after deterministic tie-break criteria",
                "candidate_count": len(result.evaluations),
                "timestamp": now.isoformat(),
            }
            self.state.underlyings["_rank_tie"] = tie_payload
            self.event_ledger.append(
                "RANK_TIE_UNRESOLVED", session_id=self.state.session_id,
                decision_source="ranking_tie_breaker", ts=now, payload=tie_payload,
            )
        else:
            self.state.underlyings.pop("_rank_tie", None)
        portfolio_snapshot = self._portfolio_no_trade_snapshot(result.evaluations, now)
        no_a_grade_required = bool(self.config.section("portfolio_no_trade_engine").get("no_trade_if_no_candidate_grade_at_least_A", True))
        has_a_grade = any(evaluation.eligible and evaluation.grade.value in {"A", "A+"} for evaluation in result.evaluations)
        if no_a_grade_required and not has_a_grade:
            portfolio_snapshot["status"] = "BLOCKED"
            portfolio_snapshot.setdefault("hard_vetoes", []).append("no_candidate_grade_A_or_better")
        self.state.underlyings["_portfolio_no_trade"] = portfolio_snapshot
        self._record_qualified_opportunities(
            result.evaluations, now, lane="CANONICAL", selected=result.selected,
            portfolio_blocked=portfolio_snapshot.get("status") == "BLOCKED",
        )
        self._update_candidate_display(result)
        self._evaluate_experimental_impulse_breakouts(
            chains, context_map, histories or {}, result.evaluations, now,
            portfolio_blocked=portfolio_snapshot.get("status") == "BLOCKED",
        )
        # Broad research evidence must be recorded even when a portfolio veto blocks entry.
        now_ts = time.time()
        if now_ts - self._last_skipped_cycle >= 60.0:
            self._last_skipped_cycle = now_ts
            cycle_id = now_ist().strftime("%Y%m%d%H%M")
            try:
                self.evidence.record_skipped(result.evaluations, ranking_cycle_id=cycle_id)
            except Exception as e:
                self._log(f"  evidence record_skipped failed: {e}")
            try:
                self.evidence.record_candidates(result.evaluations, ts=now_ist())
            except Exception as e:
                self._log(f"  evidence record_candidates failed: {e}")
        if portfolio_snapshot.get("status") == "BLOCKED":
            reason = f"Portfolio no-trade score {portfolio_snapshot['score']:.1f} >= {portfolio_snapshot['shutdown_above']:.1f}"
            hard_vetoes = portfolio_snapshot.get("hard_vetoes", [])
            if hard_vetoes:
                reason = f"Portfolio no-trade hard veto: {', '.join(str(v) for v in hard_vetoes)}"
            self.event_ledger.append(
                "PORTFOLIO_NO_TRADE_BLOCK", session_id=self.state.session_id,
                decision_source="portfolio_no_trade_engine", ts=now,
                payload={"reason": reason, "snapshot": portfolio_snapshot},
            )
            selected = self._select_paper_calibration_candidate(chains, context_map, histories or {}, now)
            entry_mode = "PAPER_CALIBRATION" if selected is not None else "CANONICAL"
            if selected is None:
                return
        else:
            selected = result.selected
            entry_mode = "CANONICAL"
            if selected is not None and not self._candidate_is_armed(selected):
                self.state.underlyings["_arm_gate"] = {"status": "ARMING", "underlying": selected.candidate.instrument.underlying, "reason": "Candidate must pass two consecutive fresh qualified observations before paper entry", "timestamp": now.isoformat()}
                return
            if selected is None:
                selected = self._select_paper_calibration_candidate(chains, context_map, histories or {}, now)
                entry_mode = "PAPER_CALIBRATION" if selected is not None else "CANONICAL"
                if selected is None:
                    self._rank_persistence = {}
                    self._save_rank_persistence()
                    return
        if entry_mode == "CANONICAL":
            persistent, persistence_reason, persistence_count, persistence_required = self._rank_persistence_check(selected, now)
            self.state.underlyings["_rank_persistence"] = {
                "key": self._rank_key(selected),
                "count": persistence_count,
                "required": persistence_required,
                "status": "PASS" if persistent else "BLOCKED",
                "reason": persistence_reason,
            }
            if not persistent:
                self.event_ledger.append(
                    "RANK_PERSISTENCE_BLOCK", session_id=self.state.session_id,
                    underlying=selected.candidate.instrument.underlying,
                    exchange=selected.candidate.instrument.exchange,
                    instrument_kind=selected.candidate.instrument.instrument_kind,
                    instrument_class=selected.candidate.instrument.instrument_class,
                    lifecycle_state=selected.candidate.lifecycle_state,
                    exposure_group=selected.candidate.exposure_group,
                    decision_source="rank_persistence_gate", ts=now,
                    payload={"count": persistence_count, "required": persistence_required, "reason": persistence_reason},
                )
                return
        friday_block = self._short_dated_friday_block_reason(selected.candidate, now)
        if friday_block:
            self.state.underlyings["_entry_window"] = {
                "status": "CLOSED",
                "reason": friday_block,
                "timestamp": now_ist().isoformat(),
            }
            return
        if selected.candidate.lifecycle_state in {InstrumentLifecycle.MONITOR.value, InstrumentLifecycle.SHADOW.value, InstrumentLifecycle.RETIRED.value}:
            self._log(f"Selector blocked non-paper lifecycle candidate: {selected.candidate.lifecycle_state}")
            return
        active_underlyings = {self.state.open_position.underlying} if self.state.open_position else set()
        active_groups = set()
        if self.state.open_position:
            active_candidate = self.state.open_position.trade.entry_evaluation.candidate
            active_groups.add(active_candidate.exposure_group)
        overlap = self.overlap_guard.assess(
            selected.candidate.instrument.underlying, selected.candidate.exposure_group,
            active_underlyings, active_groups,
        )
        if not overlap.allowed:
            self.event_ledger.append(
                "OVERLAP_BLOCK", session_id=self.state.session_id,
                underlying=selected.candidate.instrument.underlying,
                exchange=selected.candidate.instrument.exchange,
                instrument_kind=selected.candidate.instrument.instrument_kind,
                instrument_class=selected.candidate.instrument.instrument_class,
                lifecycle_state=selected.candidate.lifecycle_state,
                exposure_group=selected.candidate.exposure_group,
                decision_source="portfolio_overlap_guard", payload={"reason": overlap.reason},
            )
            return
        chain = chains[selected.candidate.instrument.underlying]
        leg = chain.leg_at(selected.candidate.instrument.strike, selected.candidate.side)
        revalidator = self.paper_calibration_revalidator if entry_mode == "PAPER_CALIBRATION" and self.paper_calibration_revalidator is not None else self.revalidator
        revalidated, revalidation_reasons = revalidator.revalidate(
            selected,
            leg.quote,
            now_ist(),
            ranking_spread=selected.candidate.quote.spread,
            fast_market=selected.candidate.market_hostility_score >= 50.0,
        )
        try:
            self.evidence.record_revalidation(selected, revalidated, revalidation_reasons, stage=f"{entry_mode}_PRE_ENTRY", ts=now_ist())
        except Exception as e:
            self._log(f"  revalidation evidence failed: {e}")
        if not revalidated:
            self.state.underlyings["_revalidation"] = {
                "status": "BLOCKED",
                "reasons": list(revalidation_reasons),
                "underlying": selected.candidate.instrument.underlying,
            }
            self.event_ledger.append(
                "REVALIDATION_BLOCK", session_id=self.state.session_id,
                underlying=selected.candidate.instrument.underlying,
                exchange=selected.candidate.instrument.exchange,
                instrument_kind=selected.candidate.instrument.instrument_kind,
                instrument_class=selected.candidate.instrument.instrument_class,
                lifecycle_state=selected.candidate.lifecycle_state,
                exposure_group=selected.candidate.exposure_group,
                decision_source="candidate_revalidator", payload={"reasons": revalidation_reasons},
            )
            return
        refreshed_candidate = replace(selected.candidate, quote=leg.quote)
        health_orchestrator = self.paper_calibration_data_health if entry_mode == "PAPER_CALIBRATION" and self.paper_calibration_data_health is not None else self.data_health
        refreshed_health = health_orchestrator.evaluate_candidate(refreshed_candidate, now_ist())
        refreshed_candidate = replace(
            refreshed_candidate,
            data_health=DataHealth(
                valid=refreshed_candidate.data_health.valid and refreshed_health.valid,
                warning=refreshed_candidate.data_health.warning or refreshed_health.warning,
                reason="; ".join(reason for reason in (refreshed_candidate.data_health.reason, refreshed_health.reason) if reason),
            ),
        )
        scoring_engine = self.paper_calibration_engine if entry_mode == "PAPER_CALIBRATION" else self.scorer_engine
        refreshed = scoring_engine.scorer.evaluate(
            refreshed_candidate,
            realized_loss_today=max(0.0, -self.state.realized_pnl_today),
        )
        try:
            self.evidence.record_revalidation(refreshed, refreshed.eligible, refreshed.reasons, stage=f"{entry_mode}_FRESH_SCORE", ts=now_ist())
        except Exception as e:
            self._log(f"  fresh-score evidence failed: {e}")
        if not refreshed.eligible:
            self.state.underlyings["_revalidation"] = {
                "status": "BLOCKED",
                "reasons": list(refreshed.reasons) or ["Fresh quote no longer passes all entry gates"],
                "underlying": selected.candidate.instrument.underlying,
            }
            return
        selected = refreshed
        self.state.underlyings.pop("_revalidation", None)
        if entry_mode == "PAPER_CALIBRATION":
            calibration_hard_failures = []
            if not self._cost_model_valid:
                calibration_hard_failures.append("cost model is not validated")
            if not selected.candidate.data_health.valid:
                calibration_hard_failures.append("final candidate data health is invalid")
            if not selected.candidate.quote.is_valid():
                calibration_hard_failures.append("final quote is invalid")
            if selected.candidate.quote.bid_qty <= 0 or selected.candidate.quote.ask_qty <= 0:
                calibration_hard_failures.append("final executable quote has non-positive size")
            if not selected.candidate.quote.source_timestamp_available:
                calibration_hard_failures.append("final source timestamp is unavailable")
            if calibration_hard_failures:
                reason = "; ".join(calibration_hard_failures)
                self.state.underlyings["_revalidation"] = {"status": "BLOCKED", "reasons": [reason], "underlying": selected.candidate.instrument.underlying}
                self._log(f"Calibration paper entry hard-blocked: {reason}")
                return
        mapping_ok, mapping_reason = self._validate_entry_mapping(selected.candidate)
        try:
            self.evidence.record_revalidation(selected, mapping_ok, (mapping_reason,) if not mapping_ok else tuple(), stage="MAPPING_VALIDATION", ts=now_ist())
        except Exception as e:
            self._log(f"  mapping-validation evidence failed: {e}")
        if not mapping_ok:
            self.state.underlyings["_revalidation"] = {
                "status": "BLOCKED",
                "reasons": [mapping_reason],
                "underlying": selected.candidate.instrument.underlying,
            }
            return
        entry_notes = dict(selected.candidate.notes or {})
        entry_notes.update({
            "entry_mode": entry_mode,
            "research_only": entry_mode == "PAPER_CALIBRATION",
            "entry_revalidation_passed": True,
            "mapping_validation_passed": True,
            "lot_size_validation_passed": selected.candidate.instrument.lot_size > 0,
            "tick_size_validation_passed": selected.candidate.instrument.tick_size > 0,
        })
        audit_payload = {
            "underlying": selected.candidate.instrument.underlying,
            "side": selected.candidate.side.value,
            "expiry": str(selected.candidate.instrument.expiry),
            "strike": selected.candidate.instrument.strike,
            "entry_mode": entry_mode,
            "quote_timestamp": str(selected.candidate.quote.timestamp),
            "bid": selected.candidate.quote.bid,
            "ask": selected.candidate.quote.ask,
            "mid": selected.candidate.quote.mid,
            "score": selected.comparable_opportunity_score,
            "threshold": selected.threshold,
            "data_health_valid": selected.candidate.data_health.valid,
            "source_timestamp_available": selected.candidate.quote.source_timestamp_available,
            "cost_model_valid": self._cost_model_valid,
        }
        audit_id = hashlib.sha256(json.dumps(audit_payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:20]
        entry_notes["entry_audit_id"] = audit_id
        entry_notes["entry_audit_payload"] = audit_payload
        selected = replace(selected, candidate=replace(selected.candidate, notes=entry_notes))
        self._append_entry_audit(audit_id, "ENTRY_APPROVED", selected, now_ist(), {"paper_only": True})
        symbol = self.master.symbol_for(
            selected.candidate.instrument.underlying,
            selected.candidate.instrument.expiry,
            selected.candidate.instrument.strike,
            selected.candidate.side.value,
        )
        fill = self.fill_sim.entry_buy(selected.candidate.quote, selected.candidate.instrument.tick_size)
        spread_pct = (selected.candidate.quote.spread / selected.candidate.quote.mid * 100.0) if selected.candidate.quote.mid > 0 else 99.0
        # Record execution quality for entry fill
        if fill.filled and fill.fill_price is not None:
            self.execution_quality.record_fill(
                instrument=selected.candidate.instrument.underlying,
                fill_price=fill.fill_price,
                mid_price=selected.candidate.quote.mid,
                spread_pct=spread_pct,
                side=selected.candidate.side.value,
                timestamp=now_ist().timestamp()
            )
        try:
            self.evidence.record_fill_attempt(selected, f"{entry_mode}_ENTRY", fill.filled and fill.fill_price is not None, fill.fill_price, fill.reason, ts=now_ist())
        except Exception as e:
            self._log(f"  entry-fill evidence failed: {e}")
        if not fill.filled or fill.fill_price is None:
            self._append_entry_audit(audit_id, "FILL_REJECTED", selected, now_ist(), {"reason": fill.reason, "paper_only": True})
            self._log(f"Entry not filled for {symbol}: {fill.reason}")
            return
        self._append_entry_audit(audit_id, "FILL_CONFIRMED", selected, now_ist(), {"fill_price": fill.fill_price, "paper_only": True})
        trade = PaperTrade(
            trade_id=f"{now_ist().strftime('%H%M%S')}-{symbol.split(':')[-1]}",
            entry_evaluation=selected,
            entry_fill=fill,
            entry_time=now_ist(),
        )
        stop = max(selected.risk_plan.hard_stop_points, 1.0)
        target_r = self._target_r(selected)
        pos = OpenPosition(
            trade=trade,
            symbol=symbol,
            underlying=selected.candidate.instrument.underlying,
            expiry=chain.expiry,
            stop_points=stop,
            target_points=stop * target_r,
            max_duration_seconds=self.entry_hold_seconds,
            last_premium=fill.fill_price,
            highest_premium=fill.fill_price,
            lowest_premium=fill.fill_price,
            last_quote=selected.candidate.quote,
            entry_mode=entry_mode,
        )
        if not self._add_open_position(pos):
            self._log("Paper entry blocked: concurrent position capacity reached")
            return
        self.state.trades_today += 1
        self._save_daily_risk_state()
        self._save_open_position_checkpoint(pos)
        self.event_ledger.append(
            "PAPER_ENTRY", session_id=self.state.session_id,
            underlying=selected.candidate.instrument.underlying,
            exchange=selected.candidate.instrument.exchange,
            instrument_kind=selected.candidate.instrument.instrument_kind,
            instrument_class=selected.candidate.instrument.instrument_class,
            lifecycle_state=selected.candidate.lifecycle_state,
            exposure_group=selected.candidate.exposure_group,
            decision_source="trade_selector", ts=trade.entry_time,
            payload={"symbol": symbol, "score": selected.comparable_opportunity_score,
                     "fill": fill.fill_price, "stop": stop, "target_r": target_r},
        )
        self._log(f"OPEN {symbol} @ {fill.fill_price:.2f} stop={stop:.2f} target={stop*target_r:.2f}")

    def _enter_cas_paper_position(self, chains, context_map, cas_snapshot: Mapping[str, Any], now: datetime) -> None:
        """Create one research-only paper position from a verified CAS anomaly.

        This path is intentionally separate from canonical selection. It requires
        a fresh two-sided quote with positive top-book quantities, valid mapping,
        one lot, and no open position; it never calls a broker order endpoint.
        """
        if not self._cas_paper_entry_enabled or not self._capacity_available():
            return
        risk_block = self._daily_risk_block_reason(now)
        if risk_block:
            self._log(f"CAS paper entry blocked by daily risk control: {risk_block}")
            return
        event = cas_snapshot.get("last_event") or {}
        if event.get("execution_status") != "EXECUTABLE" or event.get("phase") != "CAS_WINDOW":
            return
        underlying = str(event.get("underlying", ""))
        side = str(event.get("side", ""))
        try:
            strike = float(event.get("strike"))
        except (TypeError, ValueError):
            return
        if underlying not in chains or side not in {"CE", "PE"}:
            return
        # Build the same instrument/risk objects as the normal pipeline, but do
        # not require the canonical score threshold for this research-only lane.
        try:
            candidates = self._build_candidates(chains, context_map, scope="calibration")
            matches = [c for c in candidates if c.instrument.underlying == underlying and c.side.value == side and abs(float(c.instrument.strike) - strike) < 1e-6]
            if not matches:
                self._log(f"CAS paper entry unavailable: candidate not built for {underlying} {strike} {side}")
                return
            candidate = matches[0]
            quote = chains[underlying].leg_at(candidate.instrument.strike, candidate.side).quote
            fresh = quote.timestamp is not None and (now - quote.timestamp).total_seconds() <= float(self.cfg.get("cas_monitor", {}).get("max_quote_age_seconds", 5.0))
            if not fresh or quote.bid <= 0 or quote.ask < quote.bid or quote.bid_qty <= 0 or quote.ask_qty <= 0:
                self._log(f"CAS paper entry blocked: fresh executable quote check failed for {underlying} {strike} {side}")
                return
            candidate = replace(candidate, quote=quote, data_health=DataHealth(True, False, "CAS executable quote verified"))
            selected = self.paper_calibration_engine.scorer.evaluate(candidate, realized_loss_today=0.0)
            if not bool(getattr(selected.risk_plan, "hard_stop_fit", False)) or int(getattr(selected.risk_plan, "lots", 1)) != 1:
                self._log(f"CAS paper entry blocked: risk plan is not valid one-lot bounded risk for {underlying} {strike} {side}")
                return
            mapping_ok, mapping_reason = self._validate_entry_mapping(selected.candidate)
            if not mapping_ok:
                self._log(f"CAS paper entry blocked: {mapping_reason}")
                return
            symbol = self.master.symbol_for(underlying, selected.candidate.instrument.expiry, selected.candidate.instrument.strike, side)
            fill = self.fill_sim.entry_buy(quote, selected.candidate.instrument.tick_size)
            if not fill.filled or fill.fill_price is None:
                self._log(f"CAS paper entry not filled for {symbol}: {fill.reason}")
                return
            notes = dict(selected.candidate.notes or {})
            notes.update({"entry_mode": "CAS_ANOMALY_RESEARCH", "research_only": True, "cas_phase": "CAS_WINDOW", "cas_anomaly": True, "executable_quote_verified": True})
            selected = replace(selected, candidate=replace(selected.candidate, quote=quote, notes=notes))
            trade = PaperTrade(trade_id=f"{now.strftime('%H%M%S')}-{symbol.split(':')[-1]}", entry_evaluation=selected, entry_fill=fill, entry_time=now)
            stop = max(selected.risk_plan.hard_stop_points, 1.0)
            target_r = self._target_r(selected)
            pos = OpenPosition(trade=trade, symbol=symbol, underlying=underlying, expiry=chains[underlying].expiry, stop_points=stop, target_points=stop * target_r, max_duration_seconds=self.entry_hold_seconds, last_premium=fill.fill_price, highest_premium=fill.fill_price, lowest_premium=fill.fill_price, last_quote=quote, entry_mode="CAS_ANOMALY_RESEARCH")
            if not self._add_open_position(pos):
                self._log("CAS paper entry blocked: concurrent position capacity reached")
                return
            self.state.trades_today += 1
            self._save_daily_risk_state()
            self._save_open_position_checkpoint(pos)
            self.event_ledger.append("PAPER_ENTRY", session_id=self.state.session_id, underlying=underlying, exchange=selected.candidate.instrument.exchange, instrument_kind=selected.candidate.instrument.instrument_kind, instrument_class=selected.candidate.instrument.instrument_class, lifecycle_state=selected.candidate.lifecycle_state, exposure_group=selected.candidate.exposure_group, decision_source="cas_anomaly_monitor", ts=now, payload={"symbol": symbol, "entry_mode": "CAS_ANOMALY_RESEARCH", "research_only": True, "cas_event": event, "fill": fill.fill_price, "stop": stop, "target_r": target_r, "paper_only": True})
            self._log(f"OPEN CAS RESEARCH {symbol} @ {fill.fill_price:.2f} stop={stop:.2f} target={stop*target_r:.2f}")
        except Exception as exc:
            self._log(f"CAS paper entry failed safely: {type(exc).__name__}: {exc}")
    def _validate_entry_mapping(self, candidate) -> tuple[bool, str]:
        spec = candidate.instrument
        if not spec.security_id or spec.security_id == "":
            return False, "Mapping validation unavailable: security_id missing"
        if spec.lot_size <= 0:
            return False, "Lot-size validation failed: non-positive lot size"
        if spec.tick_size <= 0:
            return False, "Tick-size validation failed: non-positive tick size"
        if not spec.buy_sell_allowed:
            return False, "Mapping validation failed: buy side not permitted"
        try:
            symbol = self.master.symbol_for(spec.underlying, spec.expiry, spec.strike, candidate.side.value)
        except Exception as exc:
            return False, f"Mapping validation failed: {type(exc).__name__}"
        if not symbol:
            return False, "Mapping validation failed: empty broker symbol"
        return True, ""

    def _target_r(self, selected) -> float:
        """Target in R multiples. Base is preferred_target_R; when edge-scaled
        targets are enabled (exit_management.edge_scaled_target), the target is
        scaled by the candidate's expected/required ratio so high-edge setups
        are given room to run and marginal ones are banked earlier. The stop is
        never changed, so worst-case per-trade risk is identical."""
        base = float(self.config.section("expected_move").get("preferred_target_R", 2.0))
        raw = self.config.raw.get("exit_management")
        if not (isinstance(raw, Mapping) and raw.get("edge_scaled_target")):
            return base
        try:
            ratio = selected.candidate.expected_move / max(selected.candidate.required_move, 1e-9)
            min_ratio = float(raw.get("edge_scale_min_ratio", 1.1))
            min_r = float(raw.get("edge_scale_min_r", 1.0))
            max_r = float(raw.get("edge_scale_max_r", 3.0))
            return min(max(base * (ratio / min_ratio), min_r), max_r)
        except (TypeError, ValueError):
            return base

    # -- open position management -----------------------------------------------

    def _manage_open_position(self, chains, context_map=None) -> None:
        for pos in list(self._positions()):
            self._manage_single_position(pos, chains, context_map)

    def _manage_single_position(self, pos, chains, context_map=None) -> None:
        chain = chains.get(pos.underlying)
        if chain is None:
            return
        try:
            leg = chain.leg_at(pos.trade.entry_evaluation.candidate.instrument.strike,
                               pos.trade.entry_evaluation.candidate.side)
        except Exception:
            return
        ctx = (context_map or {}).get(pos.underlying)
        bar = MarketBar(
            timestamp=now_ist(),
            quote=leg.quote,
            futures_price=chain.underlying_price,
            iv=leg.implied_volatility,
            expected_move_remaining=ctx.regime_projected_move if ctx is not None else None,
        )
        pos.bars.append(bar)
        pos.last_quote = leg.quote
        pos.last_premium = leg.quote.mid
        pos.highest_premium = max(pos.highest_premium, leg.quote.mid)
        pos.lowest_premium = min(pos.lowest_premium, leg.quote.mid) if pos.lowest_premium > 0 else leg.quote.mid

        result = self.lifecycle.run(
            pos.trade, pos.bars,
            target_points=pos.target_points,
            stop_points=pos.stop_points,
            max_duration_seconds=pos.max_duration_seconds,
            exit_policy=self.exit_policy,
        )
        if result.exit_reason in ACTIVE_EXIT_REASONS:
            self._close_position(pos, result.exit_reason, result)
        else:
            self._save_open_position_checkpoint(pos)
        # EXIT_END_OF_DATA / NO_DATA means no exit triggered yet on the bars so far.

    def _force_close_end_of_day(self, now: datetime) -> None:
        for pos in list(self._positions()):
            self._force_close_single_position(pos, now)

    def _force_close_single_position(self, pos, now: datetime) -> None:
        quote = pos.last_quote
        if quote is None or not quote.is_valid():
            self.state.underlyings["_eod_guard"] = {
                "status": "BLOCKED",
                "reason": "Open paper position has no valid final quote; manual evidence reconciliation required",
            }
            return
        tick = pos.trade.entry_evaluation.candidate.instrument.tick_size
        exit_fill = self.fill_sim.exit_sell(quote, tick)
        exit_price = exit_fill.fill_price if exit_fill.filled and exit_fill.fill_price is not None else quote.bid
        trade = replace(
            pos.trade,
            exit_fill=exit_fill,
            exit_time=now,
            exit_reason="END_OF_DAY_EXIT",
        )
        entry_price = pos.trade.entry_fill.fill_price or pos.last_premium
        result = SimpleNamespace(
            trade=trade,
            exit_reason="END_OF_DAY_EXIT",
            gross_pnl_points=exit_price - entry_price,
            mae_points=entry_price - pos.lowest_premium,
            mfe_points=pos.highest_premium - entry_price,
        )
        self._close_position(pos, "END_OF_DAY_EXIT", result)

    def _close_position(self, pos: OpenPosition, reason: str, result) -> None:
        exit_fill = result.trade.exit_fill
        # Record execution quality for exit fill
        if exit_fill and exit_fill.filled and exit_fill.fill_price is not None:
            self.execution_quality.record_fill(
                instrument=pos.trade.entry_evaluation.candidate.instrument.underlying,
                fill_price=exit_fill.fill_price,
                mid_price=pos.last_quote.mid if pos.last_quote else 0.0,
                spread_pct=0.0,  # Use current spread if available, but exit uses bid/ask
                side=pos.trade.entry_evaluation.candidate.side.value,
                timestamp=(result.trade.exit_time or now_ist()).timestamp()
            )
        try:
            self.evidence.record_fill_attempt(
                pos.trade.entry_evaluation, f"{getattr(pos, "entry_mode", "CANONICAL")}_EXIT",
                bool(exit_fill and exit_fill.filled and exit_fill.fill_price is not None),
                exit_fill.fill_price if exit_fill else None,
                exit_fill.reason if exit_fill else "No exit fill object",
                ts=result.trade.exit_time or now_ist(),
            )
        except Exception as e:
            self._log(f"  exit-fill evidence failed: {e}")
        exit_price = exit_fill.fill_price if exit_fill and exit_fill.filled else pos.last_premium
        lot = pos.trade.entry_evaluation.candidate.instrument.lot_size
        gross_pnl = (exit_price - pos.trade.entry_fill.fill_price) * lot
        costs = self.costs.round_trip_cost(
            pos.trade.entry_fill.fill_price * lot, exit_price * lot).total
        net = gross_pnl - costs
        hold = int((result.trade.exit_time - pos.trade.entry_time).total_seconds()) if result.trade.exit_time else 0
        rec = ClosedTradeRecord(
            trade_id=pos.trade.trade_id,
            underlying=pos.underlying,
            side=pos.trade.entry_evaluation.candidate.side.value,
            expiry=pos.expiry,
            strike=pos.trade.entry_evaluation.candidate.instrument.strike,
            entry_time=pos.trade.entry_time.isoformat(),
            exit_time=(result.trade.exit_time or now_ist()).isoformat(),
            entry_fill=pos.trade.entry_fill.fill_price,
            exit_fill=exit_price,
            exit_reason=reason,
            gross_points=result.gross_pnl_points,
            gross_pnl=gross_pnl,
            costs=costs,
            net_pnl=net,
            hold_seconds=hold,
            max_adverse_points=result.mae_points,
            max_favorable_points=result.mfe_points,
            entry_mode=getattr(pos, "entry_mode", "CANONICAL"),
        )
        self.state.closed_trades.append(rec)
        self.state.realized_pnl += net
        self.state.realized_pnl_today += net
        self.state.realized_pnl_week += net
        self._save_account_state()
        if net < 0:
            self.state.losses_today += 1
            self.state.loss_streak_today += 1
            loss_ts = (result.trade.exit_time or now_ist()).isoformat()
            self.state.last_loss_at = loss_ts
            loss_key = f"{pos.underlying}|{pos.trade.entry_evaluation.candidate.side.value}"
            self.state.recent_direction_losses[loss_key] = loss_ts
        else:
            self.state.loss_streak_today = 0
        self._save_daily_risk_state()
        self._remove_open_position(pos)
        entry_notes = dict(pos.trade.entry_evaluation.candidate.notes or {})
        audit_id = str(entry_notes.get("entry_audit_id", ""))
        if audit_id:
            self._append_entry_audit(audit_id, "TRADE_CLOSED", pos.trade.entry_evaluation, result.trade.exit_time or now_ist(), {"exit_reason": reason, "net_pnl": net, "r_multiple": r_multiple, "paper_only": True})
        self._append_journal(rec)
        # Phase-2 evidence: one MTIL row per closed trade with entry proxy scores.
        planned = pos.trade.entry_evaluation.risk_plan.planned_risk
        r_multiple = net / planned if planned and planned > 0 else 0.0
        try:
            c = pos.trade.entry_evaluation.candidate
            if getattr(pos, "entry_mode", "CANONICAL") == "PAPER_CALIBRATION":
                self.evidence.record_calibration_trade(rec, cost_model_valid=self._cost_model_valid)
                self.event_ledger.append(
                    "PAPER_CALIBRATION_OUTCOME", session_id=self.state.session_id,
                    underlying=c.instrument.underlying, exchange=c.instrument.exchange,
                    instrument_kind=c.instrument.instrument_kind, instrument_class=c.instrument.instrument_class,
                    lifecycle_state=c.lifecycle_state, exposure_group=c.exposure_group,
                    decision_source="paper_calibration_lifecycle", ts=result.trade.exit_time or now_ist(),
                    payload={"exit_reason": reason, "net_pnl": net, "r_multiple": r_multiple, "cost_model_valid": self._cost_model_valid},
                )
            else:
                self.evidence.record_trade(
                    result.trade,
                    net_pnl_rupees=net,
                    r_multiple=r_multiple,
                    gross_pnl_rupees=gross_pnl,
                    total_costs_rupees=costs,
                )
                self.calibration.record_outcome(
                c.instrument.instrument_class, pos.trade.entry_evaluation.comparable_opportunity_score,
                r_multiple, net, instrument_id=c.instrument.underlying, paper=True,
                features=self._gate_feature_snapshot(pos.trade.entry_evaluation),
                observed_at=result.trade.exit_time or now_ist(),
                    cost_model_valid=self._cost_model_valid,
                )
                self.event_ledger.append(
                    "PAPER_OUTCOME", session_id=self.state.session_id,
                underlying=c.instrument.underlying, exchange=c.instrument.exchange,
                instrument_kind=c.instrument.instrument_kind, instrument_class=c.instrument.instrument_class,
                lifecycle_state=c.lifecycle_state, exposure_group=c.exposure_group,
                decision_source="paper_lifecycle", ts=result.trade.exit_time or now_ist(),
                    payload={"exit_reason": reason, "net_pnl": net, "r_multiple": r_multiple},
                )
        except Exception as e:
            self._log(f"  evidence/calibration record_trade failed: {e}")
        self._clear_open_position_checkpoint()
        self._log(f"CLOSE {rec.side} {rec.strike} {rec.exit_reason} net={net:+.0f} "
                  f"({result.gross_pnl_points:+.1f}pts) hold={hold}s")

    # -- display / state ----------------------------------------------------------

    def _update_chain_display(self, chains, vix_map, context_map) -> None:
        received_at = now_ist()
        for und, chain in chains.items():
            ctx = context_map[und]
            meta = self.universe.get(und, {})
            self.state.underlyings.setdefault(und, {})["evidence_clocks"] = {
                "local_received_at": received_at.isoformat(),
                "source_timestamp": str(getattr(chain, "source_timestamp", "") or ""),
                "timestamp_quality": timestamp_quality(getattr(chain, "source_timestamp", None), received_at.isoformat(), max_delay_seconds=5.0),
            }
            legs = []
            atm = chain.nearest_strike()
            for s in chain.strikes:
                if abs(s.strike - atm) > 600:
                    continue
                row = {"strike": s.strike, "atm": abs(s.strike - atm) < 1e-6}
                for name, leg in (("ce", s.ce), ("pe", s.pe)):
                    if leg is not None:
                        row[name] = {"bid": leg.quote.bid, "ask": leg.quote.ask,
                                     "ltp": leg.quote.last, "mid": leg.quote.mid}
                legs.append(row)
            instrument_kind = meta.get("instrument_kind", "INDEX")
            exchange = meta.get("exchange", "NSE")
            instrument_class = class_for_metadata(exchange, instrument_kind)
            class_gates = self.calibration.gates_for(instrument_class)
            prior_state = dict(self.state.underlyings.get(und, {}) or {})
            display_state = {
                "exchange": exchange,
                "instrument_kind": instrument_kind,
                "instrument_class": instrument_class,
                "lifecycle_state": self.lifecycle_states.get(und, InstrumentLifecycle.MONITOR.value),
                "exposure_group": exposure_group(und, instrument_kind),
                "class_gates": class_gates.to_dict(),
                "monitor_only": bool(meta.get("monitor_only", False)),
                "trade_enabled": bool(meta.get("trade_enabled", not meta.get("monitor_only", False))),
                "spot": chain.underlying_price,
                "vix": vix_map[und],
                "expiry": chain.expiry,
                "dte": ctx.dte,
                "direction": round(ctx.direction_score, 1),
                "direction_model_score": "" if ctx.direction_model_score is None else round(ctx.direction_model_score, 1),
                "direction_model_name": ctx.direction_model_name,
                "direction_model_status": ctx.direction_model_status,
                "direction_model_disagreement": "" if ctx.direction_model_disagreement is None else round(ctx.direction_model_disagreement, 1),
                "trade_quality": round(ctx.trade_quality_score, 1),
                "hostility": round(ctx.market_hostility_score, 1),
                "required_move": round(ctx.required_move, 1),
                "atr1": round(ctx.atr1, 2),
                "trend_eff": round(ctx.trend_efficiency, 1),
                "strikes": legs,
            }
            for preserved_key in ("depth_health", "stale_data_alert", "instrument_error", "promotion", "scheduler", "prefilter"):
                if preserved_key in prior_state:
                    display_state[preserved_key] = prior_state[preserved_key]
            self.state.underlyings[und] = display_state

    def _update_candidate_display(self, result, key: str = "_candidates") -> None:
        rows = []
        eligible_scores = sorted(float(e.comparable_opportunity_score) for e in result.evaluations if e.eligible)
        for e in result.evaluations:
            c = e.candidate
            score = float(e.comparable_opportunity_score)
            percentile = (100.0 * sum(1 for value in eligible_scores if value <= score) / len(eligible_scores)) if eligible_scores else 0.0
            rows.append({
                "underlying": c.instrument.underlying,
                "research_only": key == "_shadow_candidates" or bool((c.notes or {}).get("research_only", False)),
                "entry_mode": (c.notes or {}).get("entry_mode", "CANONICAL"),
                "side": c.side.value,
                "strike": c.instrument.strike,
                "expiry": str(c.instrument.expiry),
                "grade": e.grade.value,
                "score": round(score, 1),
                "relative_percentile": round(percentile, 1),
                "threshold": round(e.dynamic_excellent_threshold, 1),
                "eligible": e.eligible,
                "decision": e.decision.value,
                "contract_quality": round(e.contract_quality.score, 1),
                "premium_elasticity": round(c.premium_elasticity, 2),
                "observed_elasticity_status": (c.notes or {}).get("observed_elasticity_status", "UNAVAILABLE"),
                "observed_elasticity_post_cost_delta_adjusted": (c.notes or {}).get("observed_elasticity_post_cost_delta_adjusted", ""),
                "expected_value_r": c.expected_value_r,
                "expected_value_status": (c.notes or {}).get("expected_value_status", "UNAVAILABLE"),
                "convexity": round(c.convexity_edge_score, 1),
                "execution": round(c.execution_quality_score, 1),
                "confidence": round(c.opportunity_confidence_score, 1),
                "regime_fit": round(c.regime_fit_score, 1),
                "direction": round(c.instrument_direction_score, 1),
                "bid": c.quote.bid, "ask": c.quote.ask, "mid": round(c.quote.mid, 2),
                "reasons": "; ".join(e.reasons),
                "instrument_class": c.instrument.instrument_class,
                "lifecycle_state": c.lifecycle_state,
                "exposure_group": c.exposure_group,
                "calibrated_probability": c.calibrated_success_probability,
                "calibrated_expectancy_r": c.calibrated_net_expectancy_r,
            })
        self.state.underlyings[key] = rows

    def _update_equity(self) -> None:
        self.state.equity.append(round(self.state.realized_pnl, 2))
        self._save_account_state()
        if len(self.state.equity) > 5000:
            self.state.equity = self.state.equity[-5000:]

    def _capture_cycle(self, payloads: dict, histories: dict, now: datetime,
                       depth_payloads: Optional[dict] = None) -> None:
        """Append one cycle of raw chain/history/depth payloads to the session
        capture file for deterministic offline replay and parameter sweeps."""
        try:
            rec = {
                "ts": now.isoformat(),
                "chains": payloads,
                "history": histories,
                "depth": depth_payloads or {},
            }
            self._capture_file.write(json.dumps(rec, default=str) + "\n")
            self._capture_file.flush()
        except Exception as e:
            self._log(f"  capture failed: {e}")

    def _publish_default_paper_calibration_state(self) -> None:
        """Keep the research-only calibration panel truthful on every snapshot.

        Entry selection can be skipped before the calibration selector runs,
        especially while a restored paper position holds the global lock. The
        dashboard must not report the lane as unpublished in that case. This
        method publishes metadata only; it never makes a candidate eligible.
        """
        cfg = self._paper_calibration_cfg()
        if not bool(cfg.get("enabled", False)):
            return
        current = self.state.underlyings.get("_paper_calibration")
        if isinstance(current, Mapping) and current.get("enabled") is not None:
            return
        if self._has_open_positions():
            status = "BLOCKED"
            reason = "Global open position lock active"
        else:
            status = "NOT_EVALUATED"
            reason = "Awaiting calibration evaluation in the current cycle"
        self.state.underlyings["_paper_calibration"] = {
            "enabled": True,
            "research_only": bool(cfg.get("research_only", True)),
            "entry_mode": "PAPER_CALIBRATION",
            "cost_model_valid": bool(getattr(self, "_cost_model_valid", False)),
            "status": status,
            "reason": reason,
            "timestamp": now_ist().isoformat(),
        }

    def _position_view(self, pos: OpenPosition) -> dict[str, Any]:
        entry = pos.trade.entry_fill.fill_price
        return {
            "symbol": pos.symbol, "entry_mode": getattr(pos, "entry_mode", "CANONICAL"),
            "underlying": pos.underlying, "side": pos.trade.entry_evaluation.candidate.side.value,
            "strike": pos.trade.entry_evaluation.candidate.instrument.strike, "entry": entry,
            "last": pos.last_premium, "unrealized_points": pos.last_premium - entry,
            "unrealized_pnl": (pos.last_premium - entry) * pos.trade.entry_evaluation.candidate.instrument.lot_size,
            "stop_points": pos.stop_points, "target_points": pos.target_points,
            "max_duration_sec": pos.max_duration_seconds,
            "elapsed_sec": int((now_ist() - pos.trade.entry_time).total_seconds()),
            "highest": pos.highest_premium, "lowest": pos.lowest_premium, "bars": len(pos.bars),
            "mfe_points": pos.highest_premium - entry,
            "mae_points": entry - (pos.lowest_premium if pos.lowest_premium > 0 else entry),
            "opened_at": pos.trade.entry_time.isoformat(), "exit_policy": self._exit_policy_view(),
        }

    def snapshot(self) -> dict[str, Any]:
        self._publish_default_paper_calibration_state()
        pos = self._primary_open_position()
        pos_view = None
        if pos is not None:
            entry = pos.trade.entry_fill.fill_price
            pos_view = {
                "symbol": pos.symbol,
                "entry_mode": getattr(pos, "entry_mode", "CANONICAL"),
                "underlying": pos.underlying,
                "side": pos.trade.entry_evaluation.candidate.side.value,
                "strike": pos.trade.entry_evaluation.candidate.instrument.strike,
                "entry": entry,
                "last": pos.last_premium,
                "unrealized_points": pos.last_premium - entry,
                "unrealized_pnl": (pos.last_premium - entry) * pos.trade.entry_evaluation.candidate.instrument.lot_size,
                "stop_points": pos.stop_points,
                "target_points": pos.target_points,
                "max_duration_sec": pos.max_duration_seconds,
                "elapsed_sec": int((now_ist() - pos.trade.entry_time).total_seconds()),
                "highest": pos.highest_premium,
                "lowest": pos.lowest_premium,
                "bars": len(pos.bars),
                "mfe_points": pos.highest_premium - entry,
                "mae_points": entry - (pos.lowest_premium if pos.lowest_premium > 0 else entry),
                "opened_at": pos.trade.entry_time.isoformat(),
                "exit_policy": self._exit_policy_view(),
            }
        closed = [asdict(r) for r in self.state.closed_trades]
        return {
            "started_at": self.state.started_at,
            "session_id": self.state.session_id,
            "last_cycle": self.state.last_cycle,
            "last_cycle_ok": self.state.last_cycle_ok,
            "last_error": self.state.last_error,
            "cycle_in_progress": self.state.cycle_in_progress,
            "cycle_started_at": self.state.cycle_started_at,
            "market_open": self.state.market_open,
            "mode": "PAPER (no orders placed)",
            "open_position": pos_view,
            "open_positions": [self._position_view(item) for item in self._positions()],
            "open_positions_count": len(self._positions()),
            "max_concurrent_paper_positions": self._max_concurrent_paper_positions(),
            "closed_trades": closed,
            "trades_today": self.state.trades_today,
            "losses_today": self.state.losses_today,
            "underlyings": self.state.underlyings,
            "equity": self.state.equity[-2000:],
            "realized_pnl": self.state.realized_pnl,
            "starting_capital": self.base_config.section("capital")["starting_capital"],
            "current_equity": round(float(self.base_config.section("capital")["starting_capital"]) + float(self.state.realized_pnl), 2),
            "capital": round(float(self.base_config.section("capital")["starting_capital"]) + float(self.state.realized_pnl), 2),
            "paper_overrides_active": bool(self._active_overrides),
            "active_overrides": self._active_overrides,
            "daily_mode": dict(self.state.underlyings.get("_daily_mode", {})),
            "strategy_version": self.versions.strategy_version,
            "score_version": self.versions.score_version,
            "universe_version": self.versions.universe_version,
            "calibration": self.calibration.snapshot(),
            "evidence_analytics": self._evidence_analytics_view(),
            "opportunity_heartbeat": build_opportunity_heartbeat(self.state_dir),
            "qualified_opportunities": list(self.state.underlyings.get("_qualified_opportunities", []))[-200:],
            "opportunity_learning": self.opportunity_learning.snapshot(),
            "data_quorum": self.state.underlyings.get("_data_quorum", {}),
            "best_missed_opportunities": list(self.state.underlyings.get("_qualified_opportunities", []))[-50:],
            "cas_monitor": self.cas_monitor.snapshot(),
            "lifecycle_states": dict(self.lifecycle_states),
            "fyers_request_health": (self.client.request_stats() if hasattr(self.client, "request_stats") else {}),
            "note": "Live Fyers data. All scores marked PROXY are research-grade approximations; see paper_signal.py. Shadow outcomes are counterfactual paper fills only.",
        }

    def _exit_policy_view(self) -> dict[str, Any]:
        p = self.exit_policy
        return {
            "enabled": p.enabled,
            "breakeven_trigger_r": p.breakeven_trigger_r,
            "trail_trigger_r": p.trail_trigger_r,
            "trail_distance_r": p.trail_distance_r,
            "losing_time_stop_fraction": p.losing_time_stop_fraction,
            "time_decay_tighten": p.time_decay_tighten,
            "vol_time_stop_fraction": p.vol_time_stop_fraction,
            "stop_exit_slippage_frac": p.stop_exit_slippage_frac,
        }

    def _evidence_analytics_view(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._evidence_analytics_cache and now - self._evidence_analytics_cache_at < 10.0:
            return self._evidence_analytics_cache
        self._evidence_analytics_cache = build_evidence_snapshot(
            self.state_dir,
            min_sample=int(self.cfg.get("evidence_min_sample_for_calibration", 30)),
        )
        self._evidence_analytics_cache_at = now
        return self._evidence_analytics_cache

    # -- journal -------------------------------------------------------------------

    def _write_qualified_opportunity_header(self) -> None:
        if self._qualified_opportunity_path.exists() and self._qualified_opportunity_path.stat().st_size:
            return
        fields = ["ts", "underlying", "side", "expiry", "strike", "lane", "status", "score", "threshold", "bid", "ask", "mid", "quote_age_seconds", "reason", "paper_only"]
        with self._qualified_opportunity_path.open("w", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=fields).writeheader()

    def _candidate_is_armed(self, evaluation) -> bool:
        c = evaluation.candidate
        key = "|".join(str(value) for value in (c.instrument.underlying, c.side.value, c.instrument.expiry, c.instrument.strike, (c.notes or {}).get("entry_mode", "CANONICAL")))
        record = self.opportunity_learning.state.get("active", {}).get(key, {})
        return record.get("state") == "ARMED"

    def _record_qualified_opportunities(self, evaluations, ts: datetime, lane: str, selected=None, portfolio_blocked: bool = False) -> None:
        rows = []
        selected_key = ""
        if selected is not None:
            c = selected.candidate
            selected_key = f"{c.instrument.underlying}|{c.instrument.expiry}|{c.instrument.strike}|{c.side.value}"
        for evaluation in evaluations:
            if not evaluation.eligible:
                continue
            c = evaluation.candidate
            key = f"{c.instrument.underlying}|{c.instrument.expiry}|{c.instrument.strike}|{c.side.value}"
            if portfolio_blocked:
                status, reason = "BLOCKED_PORTFOLIO", "portfolio or daily risk veto"
            elif self._has_open_positions():
                status, reason = "BLOCKED_OPEN_POSITION", "one-open-position limit"
            elif key == selected_key:
                status, reason = "SELECTED_FOR_REVALIDATION", "top qualified candidate"
            else:
                status, reason = "QUALIFIED_NOT_SELECTED", "qualified but ranked below selected candidate"
            row = {
                "ts": ts.isoformat(), "underlying": c.instrument.underlying, "side": c.side.value,
                "expiry": str(c.instrument.expiry), "strike": c.instrument.strike, "lane": lane,
                "status": status, "score": round(float(evaluation.comparable_opportunity_score), 3),
                "threshold": round(float(evaluation.dynamic_excellent_threshold), 3),
                "bid": c.quote.bid, "ask": c.quote.ask, "mid": c.quote.mid,
                "quote_age_seconds": c.quote.age_seconds(ts), "reason": reason, "paper_only": True,
            }
            rows.append(row)
        if not rows:
            return
        fields = list(rows[0])
        with self._qualified_opportunity_path.open("a", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=fields).writerows(rows)
        learned = self.opportunity_learning.process_qualified(rows, ts)
        self._write_best_missed_opportunities(learned)
        recent = list(self.state.underlyings.get("_qualified_opportunities", []))
        recent.extend(learned)
        self.state.underlyings["_qualified_opportunities"] = recent[-200:]
        self.state.underlyings["_opportunity_learning"] = self.opportunity_learning.snapshot()

    def _write_missed_opportunity_header(self) -> None:
        if self._missed_opportunity_path.exists() and self._missed_opportunity_path.stat().st_size:
            return
        fields = ["ts", "underlying", "side", "expiry", "strike", "lane", "status", "score", "threshold", "bid", "ask", "mid", "quote_age_seconds", "reason", "paper_only"]
        with self._missed_opportunity_path.open("w", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=fields).writeheader()

    def _write_best_missed_opportunities(self, rows) -> None:
        missed = [row for row in rows if row.get("status") != "SELECTED_FOR_REVALIDATION"]
        if not missed:
            return
        fields = ["ts", "underlying", "side", "expiry", "strike", "lane", "status", "score", "threshold", "bid", "ask", "mid", "quote_age_seconds", "reason", "paper_only"]
        selected = sorted(missed, key=lambda row: float(row.get("score") or 0), reverse=True)[:20]
        projected = [{field: row.get(field, "") for field in fields} for row in selected]
        with self._missed_opportunity_path.open("a", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=fields).writerows(projected)

    def _data_quorum_snapshot(self, evaluations, now: datetime) -> dict:
        stages = {"total": len(evaluations), "data_health": 0, "quote": 0, "top_book": 0, "source_timestamp": 0, "contract_mapping": 0, "cost_model": 0}
        failures = {}
        for evaluation in evaluations:
            c = evaluation.candidate
            checks = {
                "data_health": bool(getattr(c.data_health, "valid", False)),
                "quote": bool(c.quote.is_valid()),
                "top_book": float(getattr(c.quote, "bid_qty", 0) or 0) > 0 and float(getattr(c.quote, "ask_qty", 0) or 0) > 0,
                "source_timestamp": bool(getattr(c.quote, "source_timestamp_available", False)),
                "contract_mapping": bool(getattr(c.instrument, "security_id", "")) and float(getattr(c.instrument, "lot_size", 0) or 0) > 0 and float(getattr(c.instrument, "tick_size", 0) or 0) > 0,
                "cost_model": bool(self._cost_model_valid),
            }
            for name, passed in checks.items():
                if passed:
                    stages[name] = stages.get(name, 0) + 1
                else:
                    failures[name] = failures.get(name, 0) + 1
        return {"timestamp": now.isoformat(), "session_phase": OpportunityLearningLedger.session_phase(now), "stages": stages, "failures": failures, "status": "READY" if all(stages.get(name, 0) == stages["total"] for name in ("data_health", "quote", "top_book", "source_timestamp", "contract_mapping", "cost_model")) else "DEGRADED", "paper_only": True}

    def _write_entry_audit_header(self) -> None:
        if self._entry_audit_path.exists() and self._entry_audit_path.stat().st_size:
            return
        with self._entry_audit_path.open("w", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=["ts", "audit_id", "stage", "underlying", "side", "expiry", "strike", "entry_mode", "score", "threshold", "data_health_valid", "source_timestamp_available", "cost_model_valid", "payload", "paper_only"]).writeheader()

    def _append_entry_audit(self, audit_id: str, stage: str, evaluation, ts: datetime, payload: Mapping[str, Any] | None = None) -> None:
        candidate = evaluation.candidate
        notes = dict(candidate.notes or {})
        row = {
            "ts": ts.isoformat(),
            "audit_id": audit_id,
            "stage": stage,
            "underlying": candidate.instrument.underlying,
            "side": candidate.side.value,
            "expiry": str(candidate.instrument.expiry),
            "strike": candidate.instrument.strike,
            "entry_mode": notes.get("entry_mode", "CANONICAL"),
            "score": getattr(evaluation, "comparable_opportunity_score", ""),
            "threshold": getattr(evaluation, "threshold", ""),
            "data_health_valid": candidate.data_health.valid,
            "source_timestamp_available": candidate.quote.source_timestamp_available,
            "cost_model_valid": self._cost_model_valid,
            "payload": json.dumps(dict(payload or {}), sort_keys=True, default=str),
            "paper_only": True,
        }
        with self._entry_audit_path.open("a", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=list(row)).writerow(row)

    def _write_journal_header(self) -> None:
        cols = ["trade_id", "underlying", "side", "expiry", "strike", "entry_time", "exit_time",
                "entry_fill", "exit_fill", "exit_reason", "gross_points", "gross_pnl",
                "costs", "net_pnl", "hold_seconds", "max_adverse_points", "max_favorable_points"]
        if not self._journal_path.exists():
            with self._journal_path.open("w", encoding="utf-8", newline="") as f:
                csv.writer(f).writerow(cols)

    def _append_journal(self, rec: ClosedTradeRecord) -> None:
        with self._journal_path.open("a", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow([
                rec.trade_id, rec.underlying, rec.side, rec.expiry, rec.strike,
                rec.entry_time, rec.exit_time, f"{rec.entry_fill:.2f}", f"{rec.exit_fill:.2f}",
                rec.exit_reason, f"{rec.gross_points:.2f}", f"{rec.gross_pnl:.2f}",
                f"{rec.costs:.2f}", f"{rec.net_pnl:.2f}", rec.hold_seconds,
                f"{rec.max_adverse_points:.2f}", f"{rec.max_favorable_points:.2f}",
            ])

    # -- helpers ---------------------------------------------------------------------

    def _canonical_promotion_allowed(self) -> bool:
        if not self._cost_model_valid:
            return False
        controls = self.config.raw.get("operator_controls", {})
        require_context = bool(controls.get("require_valid_market_context_for_canonical", False)) if isinstance(controls, Mapping) else False
        return not require_context or getattr(self.factory.market_context, "status", "") == "APPLIED"

    def _computed_daily_mode(self) -> str:
        global_state = str(self._risk_context.get("global_risk_state", "NEUTRAL")).upper()
        news_state = str(self._risk_context.get("news_state", "NEWS_NORMAL")).upper()
        if global_state == "SHOCK" or news_state == "NEWS_NO_TRADE":
            return "SURVIVAL"
        if global_state == "RISK_OFF" or news_state == "NEWS_CAUTION":
            return "DEFENSIVE"
        return "NORMAL"

    def _refresh_daily_controls(self, now: datetime) -> None:
        """Reload operator controls before every cycle and propagate them to all consumers."""
        computed_mode = self._computed_daily_mode()
        daily_mode = load_daily_mode(self._daily_mode_path, computed_mode, now=now)
        market_context = load_market_context(self._market_context_path, now=now)
        previous_mode = getattr(self, "daily_mode", None)
        previous_context = getattr(self.factory, "market_context", None)
        self.daily_mode = daily_mode
        self.scorer_engine.set_runtime_mode(daily_mode.effective_mode)
        self.factory.market_context = market_context
        self.signal.market_context = market_context
        self.state.underlyings["_daily_mode"] = {
            "computed_mode": daily_mode.computed_mode,
            "effective_mode": daily_mode.effective_mode,
            "status": daily_mode.status,
            "reason": daily_mode.reason,
            "path": daily_mode.path,
        }
        self.state.underlyings["_market_context"] = {
            "status": market_context.status,
            "reason": market_context.reason,
            "path": market_context.path,
            "as_of": market_context.as_of,
            "expires_at": market_context.expires_at,
            "source": market_context.source,
        }
        if previous_mode != daily_mode:
            self.event_ledger.append(
                "DAILY_MODE_CONTEXT", session_id=self.state.session_id,
                decision_source="daily_mode_operator_control", ts=now,
                payload=self.state.underlyings["_daily_mode"],
            )
        if previous_context != market_context:
            self.event_ledger.append(
                "MARKET_CONTEXT", session_id=self.state.session_id,
                decision_source="daily_market_context_operator_control", ts=now,
                payload=self.state.underlyings["_market_context"],
            )

    def _load_risk_context(self) -> dict[str, Any]:
        controls = self.config.raw.get("runtime_risk_controls", {}) if hasattr(self, "config") else self.base_config.raw.get("runtime_risk_controls", {})
        if not isinstance(controls, Mapping):
            return {"status": "UNAVAILABLE", "reason": "Risk controls not configured"}
        configured = self.cfg.get("risk_context_path") or controls.get("risk_context_path")
        path = Path(str(configured)) if configured else self.state_dir / "risk_context.json"
        if not path.is_absolute():
            if path.parts and path.parts[0] == self.state_dir.name:
                path = self.state_dir / Path(*path.parts[1:])
            else:
                path = self.state_dir / path
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"status": "UNAVAILABLE", "reason": "Verified risk/news context file missing or invalid", "path": str(path)}
        if not isinstance(payload, Mapping):
            return {"status": "UNAVAILABLE", "reason": "Risk/news context is not an object", "path": str(path)}
        source = str(payload.get("source", "")).strip()
        raw_ts = payload.get("ts") or payload.get("timestamp")
        try:
            parsed = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=IST)
            current = now_ist()
            if current.tzinfo is None:
                current = current.replace(tzinfo=IST)
            age = max(0.0, (current.astimezone(IST) - parsed.astimezone(IST)).total_seconds())
        except (TypeError, ValueError):
            return {"status": "UNAVAILABLE", "reason": "Risk/news context timestamp invalid", "path": str(path)}
        stale_after = float(controls.get("stale_after_sec", 30.0))
        if bool(controls.get("source_required", True)) and not source:
            return {"status": "UNAVAILABLE", "reason": "Risk/news context source is missing", "age_sec": age, "path": str(path)}
        if age > stale_after:
            return {"status": "STALE", "reason": f"Risk/news context is {age:.1f}s old", "age_sec": age, "path": str(path)}
        out = dict(payload)
        out.update({"status": "VALID", "age_sec": age, "path": str(path)})
        return out

    def _load_rank_persistence(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self._rank_persistence_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, Mapping):
            return {}
        return {str(key): dict(value) for key, value in raw.items() if isinstance(value, Mapping)}

    def _save_rank_persistence(self) -> None:
        tmp = self._rank_persistence_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._rank_persistence, indent=2, sort_keys=True, default=str), encoding="utf-8")
        tmp.replace(self._rank_persistence_path)

    def _load_gate_breakout_history(self) -> dict[str, list[dict[str, Any]]]:
        try:
            raw = json.loads(self._gate_breakout_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, Mapping):
            return {}
        out: dict[str, list[dict[str, Any]]] = {}
        for key, rows in raw.items():
            if isinstance(rows, list):
                out[str(key)] = [dict(row) for row in rows if isinstance(row, Mapping)]
        return out

    def _save_gate_breakout_history(self) -> None:
        tmp = self._gate_breakout_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._gate_breakout_history, indent=2, sort_keys=True, default=str), encoding="utf-8")
        tmp.replace(self._gate_breakout_path)

    # -- isolated experimental impulse-breakout lane ------------------------------

    def _experimental_impulse_config(self) -> Mapping[str, Any]:
        cfg = self.cfg.get("experimental_impulse_breakout", {})
        return cfg if isinstance(cfg, Mapping) else {}

    def _load_experimental_impulse_state(self) -> dict[str, Any]:
        if not self._experimental_impulse_path.exists():
            return {"last_trigger_key_by_underlying": {}, "cooldown_until_by_underlying": {}}
        try:
            raw = json.loads(self._experimental_impulse_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("state must be an object")
            raw.setdefault("last_trigger_key_by_underlying", {})
            raw.setdefault("cooldown_until_by_underlying", {})
            return raw
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {"last_trigger_key_by_underlying": {}, "cooldown_until_by_underlying": {}}

    def _save_experimental_impulse_state(self) -> None:
        tmp = self._experimental_impulse_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._experimental_impulse_state, indent=2, sort_keys=True, default=str), encoding="utf-8")
        tmp.replace(self._experimental_impulse_path)

    def _write_experimental_impulse_header(self) -> None:
        if self._experimental_impulse_csv_path.exists():
            return
        fields = [
            "timestamp", "label", "underlying", "status", "direction", "option_side", "raw_signal",
            "range_high", "range_low", "last_close", "atr_points", "displacement_points", "late_entry_atr",
            "direction_score", "trend_efficiency", "relative_volume", "history_bars", "quote_age_seconds",
            "trigger_key", "candidate_key", "reason", "cost_model_valid", "portfolio_blocked",
            "research_only", "paper_entry_enabled",
        ]
        with self._experimental_impulse_csv_path.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerow(fields)

    def _experimental_result_row(self, result: ImpulseBreakoutResult, now: datetime, portfolio_blocked: bool) -> dict[str, Any]:
        cfg = self._experimental_impulse_config()
        return {
            "timestamp": now.isoformat(),
            "label": str(cfg.get("label", "EXPERIMENTAL_IMPULSE_BREAKOUT")),
            "underlying": result.underlying,
            "status": result.status,
            "direction": result.direction,
            "option_side": result.option_side,
            "raw_signal": result.raw_signal,
            "range_high": result.range_high,
            "range_low": result.range_low,
            "last_close": result.last_close,
            "atr_points": result.atr_points,
            "displacement_points": result.displacement_points,
            "late_entry_atr": result.late_entry_atr,
            "direction_score": result.direction_score,
            "trend_efficiency": result.trend_efficiency,
            "relative_volume": result.relative_volume,
            "history_bars": result.history_bars,
            "quote_age_seconds": result.quote_age_seconds,
            "trigger_key": result.trigger_key,
            "candidate_key": result.candidate_key,
            "reason": result.reason,
            "cost_model_valid": self._cost_model_valid,
            "portfolio_blocked": portfolio_blocked,
            "research_only": bool(cfg.get("research_only", True)),
            "paper_entry_enabled": bool(cfg.get("paper_entry_enabled", False)),
        }

    def _evaluate_experimental_impulse_breakouts(
        self,
        chains: Mapping[str, Any],
        context_map: Mapping[str, Any],
        histories: Mapping[str, list],
        evaluations: Iterable[Any],
        now: datetime,
        *,
        portfolio_blocked: bool,
    ) -> None:
        cfg = self._experimental_impulse_config()
        if not bool(cfg.get("enabled", False)):
            self.state.underlyings.pop("_experimental_impulse_breakout", None)
            return
        selector = ImpulseBreakoutSelector(cfg)
        all_evaluations = tuple(evaluations)
        last_keys = self._experimental_impulse_state.setdefault("last_trigger_key_by_underlying", {})
        cooldowns = self._experimental_impulse_state.setdefault("cooldown_until_by_underlying", {})
        rows: list[dict[str, Any]] = []
        status_counts: dict[str, int] = {}
        ready: list[tuple[ImpulseBreakoutResult, Any]] = []
        for underlying in chains:
            context = context_map.get(underlying)
            if context is None:
                continue
            previous_key = str(last_keys.get(underlying, ""))
            cooldown_until = None
            raw_cooldown = cooldowns.get(underlying)
            if raw_cooldown:
                try:
                    cooldown_until = datetime.fromisoformat(str(raw_cooldown))
                except (TypeError, ValueError):
                    cooldown_until = None
            scoped = tuple(
                evaluation for evaluation in all_evaluations
                if str(evaluation.candidate.instrument.underlying).upper() == str(underlying).upper()
            )
            result = selector.evaluate(
                underlying,
                histories.get(underlying, []),
                context,
                scoped,
                now,
                cost_model_valid=self._cost_model_valid,
                portfolio_blocked=portfolio_blocked,
                open_position=self._has_open_positions(),
                cooldown_until=cooldown_until,
                last_trigger_key=previous_key,
            )
            row = self._experimental_result_row(result, now, portfolio_blocked)
            rows.append(row)
            status_counts[result.status] = status_counts.get(result.status, 0) + 1
            if result.raw_signal and result.trigger_key:
                last_keys[underlying] = result.trigger_key
                cooldown_seconds = max(60.0, float(cfg.get("one_shot_cooldown_seconds", 1800.0)))
                cooldowns[underlying] = (now + timedelta(seconds=cooldown_seconds)).isoformat()
            if result.status == "BREAKOUT_CANDIDATE_READY" and result.candidate is not None:
                ready.append((result, result.candidate))
            self.event_ledger.append(
                "EXPERIMENTAL_IMPULSE_BREAKOUT",
                session_id=self.state.session_id,
                underlying=underlying,
                instrument_class=class_for_metadata(self.universe.get(underlying, {}).get("exchange", "NSE"), self.universe.get(underlying, {}).get("instrument_kind", "INDEX")),
                lifecycle_state=self.lifecycle_states.get(underlying, InstrumentLifecycle.PAPER_ELIGIBLE.value),
                exposure_group=exposure_group(underlying, self.universe.get(underlying, {}).get("instrument_kind", "INDEX")),
                decision_source="experimental_impulse_breakout",
                ts=now,
                payload=row,
            )
        self._experimental_impulse_state["last_updated_at"] = now.isoformat()
        self._experimental_impulse_state["status_counts"] = status_counts
        self._save_experimental_impulse_state()
        if rows:
            with self._experimental_impulse_csv_path.open("a", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(self._experimental_result_row(ImpulseBreakoutResult("", ""), now, portfolio_blocked).keys()))
                writer.writerows(rows)
        selected = max(ready, key=lambda item: item[1].comparable_opportunity_score) if ready else None
        self.state.underlyings["_experimental_impulse_breakout"] = {
            "enabled": True,
            "label": str(cfg.get("label", "EXPERIMENTAL_IMPULSE_BREAKOUT")),
            "research_only": bool(cfg.get("research_only", True)),
            "paper_entry_enabled": bool(cfg.get("paper_entry_enabled", False)),
            "lookback_minutes": int(cfg.get("range_lookback_minutes", 30)),
            "one_shot_cooldown_seconds": float(cfg.get("one_shot_cooldown_seconds", 1800.0)),
            "status": "RESEARCH_ONLY" if bool(cfg.get("research_only", True)) else "PAPER_ENTRY_DISABLED",
            "cost_model_valid": self._cost_model_valid,
            "portfolio_blocked": portfolio_blocked,
            "raw_signal_count": sum(1 for row in rows if row.get("raw_signal")),
            "selected_underlying": selected[0].underlying if selected else None,
            "selected_candidate_key": selected[0].candidate_key if selected else None,
            "status_counts": status_counts,
            "signals": rows[-50:],
            "timestamp": now.isoformat(),
        }
    def _gate_breakout_config(self) -> Mapping[str, Any]:
        cfg = self.cfg.get("gate_breakout", {})
        return cfg if isinstance(cfg, Mapping) else {}

    def _gate_breakout_metric(self, evaluation) -> tuple[float, str]:
        cfg = self._gate_breakout_config()
        metric = str(cfg.get("metric", "threshold_margin")).strip().lower()
        score = float(evaluation.comparable_opportunity_score)
        threshold = float(evaluation.dynamic_excellent_threshold)
        if metric in {"comparable_opportunity_score", "score"}:
            return score, "comparable_opportunity_score"
        return score - threshold, "threshold_margin"

    @staticmethod
    def _gate_breakout_quality_key(evaluation) -> tuple:
        c = evaluation.candidate
        return (
            float(evaluation.comparable_opportunity_score),
            float(c.execution_quality_score),
            float(c.convexity_edge_score),
            float(evaluation.contract_quality.score),
            float(c.premium_elasticity),
            -float(c.market_hostility_score),
            -float(c.iv_crush_risk_score),
            float(c.opportunity_confidence_score),
            str(c.instrument.underlying),
        )

    def _apply_gate_breakout_filter(self, result: SelectionResult, now: datetime) -> SelectionResult:
        cfg = self._gate_breakout_config()
        if not bool(cfg.get("enabled", False)):
            self.state.underlyings.pop("_gate_breakout", None)
            return result
        try:
            lookback = max(60.0, min(7200.0, float(cfg.get("lookback_seconds", 1800.0))))
            min_improvement = max(0.0, float(cfg.get("minimum_improvement_points", 0.25)))
            max_samples = max(20, min(2000, int(cfg.get("max_samples_per_instrument", 720))))
        except (TypeError, ValueError):
            lookback, min_improvement, max_samples = 1800.0, 0.25, 720
        metric_name = str(cfg.get("metric", "threshold_margin"))
        require_eligible = bool(cfg.get("require_current_eligible", True))
        require_data_valid = bool(cfg.get("require_data_health_valid", True))
        require_contract_valid = bool(cfg.get("require_contract_valid", True))
        require_cost_valid = bool(cfg.get("require_cost_model_valid", True))
        cutoff = now - timedelta(seconds=lookback)
        grouped: dict[str, list[Any]] = {}
        for evaluation in result.evaluations:
            underlying = str(evaluation.candidate.instrument.underlying)
            grouped.setdefault(underlying, []).append(evaluation)
        status: dict[str, dict[str, Any]] = {}
        eligible_by_underlying: dict[str, Any] = {}
        breakout_by_underlying: dict[str, Any] = {}
        for underlying, evaluations in grouped.items():
            valid = []
            for evaluation in evaluations:
                if require_eligible and not bool(evaluation.eligible):
                    continue
                if require_data_valid and not bool(evaluation.candidate.data_health.valid):
                    continue
                if require_contract_valid and not bool(evaluation.contract_quality.valid):
                    continue
                if require_cost_valid and not self._cost_model_valid:
                    continue
                valid.append(evaluation)
            if not valid:
                status[underlying] = {"status": "NO_VALIDATED_VALUE", "candidate_count": len(evaluations)}
                continue
            current = max(valid, key=self._gate_breakout_quality_key)
            metric_value, actual_metric_name = self._gate_breakout_metric(current)
            eligible_by_underlying[underlying] = current
            rows = []
            for row in self._gate_breakout_history.get(underlying, []):
                try:
                    ts = datetime.fromisoformat(str(row.get("timestamp", "")))
                    value = float(row.get("value"))
                except (TypeError, ValueError):
                    continue
                if ts >= cutoff:
                    rows.append({"timestamp": ts.isoformat(), "value": value, "metric": str(row.get("metric", actual_metric_name))})
            prior_max = max((float(row["value"]) for row in rows), default=None)
            improved = prior_max is not None and metric_value > prior_max + min_improvement
            notes = dict(current.candidate.notes or {})
            notes.update({
                "gate_breakout_metric": actual_metric_name,
                "gate_breakout_current_value": metric_value,
                "gate_breakout_prior_max": prior_max,
                "gate_breakout_lookback_seconds": lookback,
                "gate_breakout_improvement_points": None if prior_max is None else metric_value - prior_max,
                "gate_breakout_status": "BREAKOUT" if improved else ("WARMUP_NO_PRIOR_MAX" if prior_max is None else "NO_NEW_MAX"),
            })
            try:
                current = replace(current, candidate=replace(current.candidate, notes=notes))
            except TypeError:
                # Lightweight test doubles may not be dataclasses; live candidates are immutable dataclasses.
                try:
                    current.candidate.notes = notes
                except Exception:
                    pass
            eligible_by_underlying[underlying] = current
            rows.append({"timestamp": now.isoformat(), "value": metric_value, "metric": actual_metric_name})
            rows = rows[-max_samples:]
            self._gate_breakout_history[underlying] = rows
            status[underlying] = {
                "status": "BREAKOUT" if improved else ("WARMUP_NO_PRIOR_MAX" if prior_max is None else "NO_NEW_MAX"),
                "metric": actual_metric_name,
                "current_value": metric_value,
                "prior_max": prior_max,
                "improvement_points": None if prior_max is None else metric_value - prior_max,
                "candidate_count": len(evaluations),
            }
            if improved:
                breakout_by_underlying[underlying] = current
        self._save_gate_breakout_history()
        qualified = list(breakout_by_underlying.values())
        selected = max(qualified, key=self._gate_breakout_quality_key) if qualified else None
        self.state.underlyings["_gate_breakout"] = {
            "enabled": True,
            "metric": metric_name,
            "lookback_seconds": lookback,
            "minimum_improvement_points": min_improvement,
            "require_current_eligible": require_eligible,
            "require_data_health_valid": require_data_valid,
            "require_contract_valid": require_contract_valid,
            "require_cost_model_valid": require_cost_valid,
            "instrument_status": status,
            "breakout_underlyings": sorted(breakout_by_underlying),
            "selected_underlying": selected.candidate.instrument.underlying if selected else None,
            "timestamp": now.isoformat(),
        }
        if selected is None:
            return SelectionResult(TradeDecision.NO_TRADE, None, result.evaluations, ("No validated 30-minute gate breakout",))
        return SelectionResult(selected.decision, selected, result.evaluations, ("Selected highest-quality validated gate breakout",))

    def _risk_context_block_reason(self) -> str:
        self._risk_context = self._load_risk_context()
        controls = self.config.section("runtime_risk_controls")
        if not bool(controls.get("enforce_on_paper", False)):
            return ""
        if self._risk_context.get("status") != "VALID":
            return "Risk/news context unavailable or stale; fail-closed entry block"
        global_state = str(self._risk_context.get("global_risk_state", "NEUTRAL")).upper()
        news_state = str(self._risk_context.get("news_state", "NEWS_NORMAL")).upper()
        if global_state == "SHOCK":
            return "Global risk shock active"
        if news_state == "NEWS_NO_TRADE":
            return "News no-trade state active"
        try:
            score = float(self._risk_context.get("portfolio_no_trade_score", 0.0))
            shutdown = float(self.config.section("portfolio_no_trade_engine").get("portfolio_no_trade_score_shutdown_above", 70.0))
            if score >= shutdown:
                return f"Portfolio no-trade score above shutdown: {score:.1f}"
        except (TypeError, ValueError):
            return "Portfolio no-trade score invalid"
        return ""

    def _regime_context(self, underlying: str, ctx) -> RegimeContext:
        global_state = str(self._risk_context.get("global_risk_state", "NEUTRAL")).upper()
        news_state = str(self._risk_context.get("news_state", "NEWS_UNKNOWN")).upper()
        if global_state == "SHOCK":
            primary = RegimeLabel.PANIC
        elif global_state == "RISK_OFF":
            primary = RegimeLabel.RISK_OFF
        elif global_state == "RISK_ON":
            primary = RegimeLabel.RISK_ON
        elif ctx.trend_efficiency >= 70.0 and abs(ctx.direction_score) >= 45.0:
            primary = RegimeLabel.TREND_EXPANSION
        elif ctx.vix is not None and ctx.vix < 11.0:
            primary = RegimeLabel.COMPRESSION
        else:
            primary = RegimeLabel.RANGE_BALANCE
        return RegimeContext(
            primary=primary,
            confidence=ctx.regime_confidence,
            market_hostility_score=ctx.market_hostility_score,
            iv_crush_risk_score=50.0,
            liquidity_stable=bool(self._risk_context.get("liquidity_stable", False)) if self._risk_context.get("status") == "VALID" else False,
            event_resolved=news_state in {"NEWS_NORMAL", "NEWS_CAUTION"},
            gap_wait_completed=bool(self._risk_context.get("gap_wait_completed", False)),
            trend_strength_score=ctx.trend_efficiency,
            range_expansion_quality=ctx.trade_quality_score,
            global_risk_shock=global_state == "SHOCK",
            time_bucket="OPENING" if ctx.dte >= 0 else "UNKNOWN",
        )

    def _update_playbook_filters(self, context_map: Mapping[str, Any], now: datetime) -> None:
        runtime = self.config.section("playbook_runtime")
        if not bool(runtime.get("enforce_on_paper", False)):
            self._playbook_codes_by_underlying = {}
            self._playbook_grades_by_underlying = {}
            return
        self._playbook_codes_by_underlying = {}
        self._playbook_grades_by_underlying = {}
        for underlying, ctx in context_map.items():
            selection = self.playbook_engine.evaluate(self._regime_context(underlying, ctx))
            self._playbook_codes_by_underlying[underlying] = selection.allowed_codes
            self._playbook_grades_by_underlying[underlying] = selection.selected.grade.value if selection.selected is not None else ""
            self.event_ledger.append(
                "PLAYBOOK_CONTEXT", session_id=self.state.session_id,
                underlying=underlying, exchange=self.universe.get(underlying, {}).get("exchange", "NSE"),
                instrument_kind=self.universe.get(underlying, {}).get("instrument_kind", "INDEX"),
                instrument_class=class_for_metadata(
                    self.universe.get(underlying, {}).get("exchange", "NSE"),
                    self.universe.get(underlying, {}).get("instrument_kind", "INDEX"),
                ),
                decision_source="regime_playbook_engine", ts=now,
                payload={"allowed_codes": sorted(selection.allowed_codes), "no_trade": selection.no_trade, "reasons": selection.reasons},
            )

    def _rank_key(self, evaluation) -> str:
        c = evaluation.candidate
        return f"{c.instrument.underlying}:{c.side.value}:{c.instrument.expiry.isoformat()}:{c.instrument.strike:g}"

    def _rank_persistence_check(self, selected, now: datetime) -> tuple[bool, str, int, int]:
        runtime = self.config.section("playbook_runtime")
        if not bool(runtime.get("require_rank_persistence", True)):
            return True, "disabled", 1, 1
        required = max(1, int(self.config.section("opportunity_selection").get("rank_persistence_required_windows", 2)))
        key = self._rank_key(selected)
        previous = self._rank_persistence.get(key, {})
        try:
            last = datetime.fromisoformat(str(previous.get("last_ts", "")))
            same_session = last.date() == now.date()
            gap = (now - last).total_seconds()
        except (TypeError, ValueError):
            same_session, gap = False, float("inf")
        max_gap = max(30.0, self.poll_seconds * 3.0)
        count = int(previous.get("count", 0)) + 1 if same_session and gap <= max_gap else 1
        self._rank_persistence = {key: {"count": count, "last_ts": now.isoformat(), "underlying": selected.candidate.instrument.underlying, "side": selected.candidate.side.value}}
        self._save_rank_persistence()
        if count < required:
            return False, f"Rank persistence {count}/{required} windows", count, required
        return True, "rank persistence satisfied", count, required

    @staticmethod
    def _checkpoint_datetime(value: Any) -> datetime:
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=IST)

    @staticmethod
    def _checkpoint_quote(raw: Mapping[str, Any]) -> Quote:
        return Quote(
            bid=float(raw["bid"]),
            ask=float(raw["ask"]),
            bid_qty=int(raw["bid_qty"]),
            ask_qty=int(raw["ask_qty"]),
            last=None if raw.get("last") is None else float(raw["last"]),
            timestamp=PaperRunner._checkpoint_datetime(raw["timestamp"]),
            cumulative_bid_qty_5depth=(None if raw.get("cumulative_bid_qty_5depth") is None else int(raw["cumulative_bid_qty_5depth"])),
            cumulative_ask_qty_5depth=(None if raw.get("cumulative_ask_qty_5depth") is None else int(raw["cumulative_ask_qty_5depth"])),
            source_timestamp_available=bool(raw.get("source_timestamp_available", False)),
        )

    @staticmethod
    def _checkpoint_quote_payload(quote: Quote) -> dict[str, Any]:
        return {
            "bid": quote.bid,
            "ask": quote.ask,
            "bid_qty": quote.bid_qty,
            "ask_qty": quote.ask_qty,
            "last": quote.last,
            "timestamp": quote.timestamp.isoformat(),
            "cumulative_bid_qty_5depth": quote.cumulative_bid_qty_5depth,
            "cumulative_ask_qty_5depth": quote.cumulative_ask_qty_5depth,
            "source_timestamp_available": quote.source_timestamp_available,
        }

    def _save_open_position_checkpoint(self, pos: Optional[OpenPosition] = None) -> None:
        positions = [pos] if pos is not None else self._positions()
        if not positions:
            self._clear_open_position_checkpoint()
            return
        if len(positions) == 1:
            PaperRunner._save_single_open_position_checkpoint(self, positions[0])
            extra_path = getattr(self, "_open_positions_path", None)
            if extra_path is not None:
                try: extra_path.unlink()
                except FileNotFoundError: pass
            return
        original = self._open_position_path
        payloads = []
        try:
            for index, position in enumerate(positions):
                temp = self.state_dir / f".paper_position_{index}.json"
                self._open_position_path = temp
                PaperRunner._save_single_open_position_checkpoint(self, position)
                payloads.append(json.loads(temp.read_text(encoding="utf-8")))
                temp.unlink(missing_ok=True)
        finally:
            self._open_position_path = original
        tmp = self._open_positions_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, "saved_at": now_ist().isoformat(), "positions": payloads, "paper_only": True}, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._open_positions_path)
        try: self._open_position_path.unlink()
        except FileNotFoundError: pass

    def _save_single_open_position_checkpoint(self, pos: Optional[OpenPosition] = None) -> None:
        """Persist the in-memory paper position for restart-safe lifecycle evidence.

        This file represents paper state only; it is never read by any broker
        execution path. The checkpoint stores the minimum immutable entry
        metadata plus fresh lifecycle bars needed to resume simulation.
        """
        position = pos or self.state.open_position
        if position is None:
            self._clear_open_position_checkpoint()
            return
        evaluation = position.trade.entry_evaluation
        candidate = evaluation.candidate
        instrument = candidate.instrument
        entry_fill = position.trade.entry_fill
        payload = {
            "version": 1,
            "saved_at": now_ist().isoformat(),
            "entry_mode": getattr(position, "entry_mode", "CANONICAL"),
            "symbol": position.symbol,
            "underlying": position.underlying,
            "expiry": position.expiry,
            "strike": instrument.strike,
            "side": candidate.side.value,
            "security_id": instrument.security_id,
            "lot_size": instrument.lot_size,
            "tick_size": instrument.tick_size,
            "freeze_qty": instrument.freeze_qty,
            "buy_sell_allowed": instrument.buy_sell_allowed,
            "exchange": instrument.exchange,
            "instrument_kind": instrument.instrument_kind,
            "instrument_class": instrument.instrument_class,
            "lifecycle_state": getattr(candidate, "lifecycle_state", "PAPER_ELIGIBLE"),
            "exposure_group": getattr(candidate, "exposure_group", position.underlying),
            "notes": dict(getattr(candidate, "notes", {}) or {}),
            "trade_id": position.trade.trade_id,
            "entry_time": position.trade.entry_time.isoformat(),
            "entry_fill": asdict(entry_fill),
            "comparable_opportunity_score": float(getattr(evaluation, "comparable_opportunity_score", 0.0)),
            "planned_risk": float(getattr(evaluation.risk_plan, "planned_risk", 0.0)),
            "stop_points": position.stop_points,
            "target_points": position.target_points,
            "max_duration_seconds": position.max_duration_seconds,
            "opened_at": position.opened_at.isoformat(),
            "last_premium": position.last_premium,
            "highest_premium": position.highest_premium,
            "lowest_premium": position.lowest_premium,
            "last_quote": self._checkpoint_quote_payload(position.last_quote) if position.last_quote is not None else None,
            "bars": [
                {
                    "timestamp": bar.timestamp.isoformat(),
                    "quote": self._checkpoint_quote_payload(bar.quote),
                    "futures_price": bar.futures_price,
                    "iv": bar.iv,
                    "expected_move_remaining": bar.expected_move_remaining,
                }
                for bar in position.bars[-200:]
            ],
        }
        tmp = self._open_position_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._open_position_path)

    def _clear_open_position_checkpoint(self) -> None:
        for path in (self._open_position_path, self._open_positions_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                self._log(f"  paper position checkpoint cleanup failed: {exc}")

    def _clear_single_open_position_checkpoint_legacy(self) -> None:
        try:
            self._open_position_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            self._log(f"  paper position checkpoint cleanup failed: {exc}")

    def _restore_open_position(self) -> None:
        self.state.open_positions = []
        multi_path = getattr(self, "_open_positions_path", None)
        if multi_path is not None and multi_path.exists():
            try:
                wrapper = json.loads(multi_path.read_text(encoding="utf-8"))
                payloads = wrapper.get("positions", []) if isinstance(wrapper, Mapping) else []
                for index, payload in enumerate(payloads):
                    temp = self.state_dir / f".restore_position_{index}.json"
                    temp.write_text(json.dumps(payload), encoding="utf-8")
                    original = self._open_position_path
                    self._open_position_path = temp
                    try: self._restore_single_open_position()
                    finally: self._open_position_path = original
                    if self.state.open_position is not None:
                        self.state.open_positions.append(self.state.open_position)
                        self.state.open_position = None
                    temp.unlink(missing_ok=True)
                self._sync_position_alias()
                return
            except Exception as exc:
                self.state.underlyings["_position_recovery"] = {"status": "BLOCKED", "reason": f"Invalid multi-position checkpoint: {type(exc).__name__}"}
                self._clear_open_position_checkpoint()
                return
        self._restore_single_open_position()
        if self.state.open_position is not None:
            self.state.open_positions = [self.state.open_position]
            self._sync_position_alias()

    def _restore_single_open_position(self) -> None:
        """Restore a same-day paper position, or fail closed on bad state."""
        if not self._open_position_path.exists():
            return
        try:
            raw = json.loads(self._open_position_path.read_text(encoding="utf-8"))
            if not isinstance(raw, Mapping) or int(raw.get("version", 0)) != 1:
                raise ValueError("Unsupported paper position checkpoint version")
            entry_time = self._checkpoint_datetime(raw["entry_time"])
            if entry_time.date() != now_ist().date():
                self.state.underlyings["_position_recovery"] = {
                    "status": "EXPIRED",
                    "reason": "Paper position checkpoint belongs to a prior trading date",
                    "entry_time": entry_time.isoformat(),
                }
                self._clear_open_position_checkpoint()
                return
            underlying = str(raw["underlying"]).upper()
            side = OptionType(str(raw["side"]).upper())
            expiry = str(raw["expiry"])
            strike = float(raw["strike"])
            lot_size = int(raw["lot_size"])
            tick_size = float(raw["tick_size"])
            if underlying not in self.universe or not bool(self.universe[underlying].get("trade_enabled", True)):
                raise ValueError("Checkpoint underlying is not paper-trade enabled")
            if lot_size <= 0 or tick_size <= 0 or not str(raw.get("symbol", "")):
                raise ValueError("Checkpoint has invalid mapping metadata")
            instrument = SimpleNamespace(
                underlying=underlying,
                security_id=str(raw.get("security_id", "")),
                instrument=str(raw.get("symbol", "")),
                expiry=date.fromisoformat(expiry[:10]),
                lot_size=lot_size,
                tick_size=tick_size,
                strike=strike,
                option_type=side,
                freeze_qty=(None if raw.get("freeze_qty") is None else int(raw["freeze_qty"])),
                buy_sell_allowed=bool(raw.get("buy_sell_allowed", True)),
                exchange=str(raw.get("exchange", "NSE")),
                instrument_kind=str(raw.get("instrument_kind", "INDEX")),
                instrument_class=str(raw.get("instrument_class", "NSE_INDEX")),
            )
            candidate = SimpleNamespace(
                instrument=instrument,
                side=side,
                notes=dict(raw.get("notes", {})) if isinstance(raw.get("notes", {}), Mapping) else {},
                lifecycle_state=str(raw.get("lifecycle_state", "PAPER_ELIGIBLE")),
                exposure_group=str(raw.get("exposure_group", underlying)),
            )
            risk_plan = SimpleNamespace(
                planned_risk=float(raw.get("planned_risk", 0.0)),
                hard_stop_points=float(raw.get("stop_points", 0.0)),
            )
            evaluation = SimpleNamespace(
                candidate=candidate,
                risk_plan=risk_plan,
                comparable_opportunity_score=float(raw.get("comparable_opportunity_score", 0.0)),
            )
            fill_raw = raw["entry_fill"]
            entry_fill = PaperFill(
                filled=bool(fill_raw["filled"]),
                fill_price=None if fill_raw.get("fill_price") is None else float(fill_raw["fill_price"]),
                limit_price=None if fill_raw.get("limit_price") is None else float(fill_raw["limit_price"]),
                slippage_buffer=float(fill_raw.get("slippage_buffer", 0.0)),
                reason=str(fill_raw.get("reason", "")),
            )
            trade = PaperTrade(
                trade_id=str(raw["trade_id"]),
                entry_evaluation=evaluation,
                entry_fill=entry_fill,
                entry_time=entry_time,
            )
            bars = []
            for bar_raw in raw.get("bars", []):
                if not isinstance(bar_raw, Mapping):
                    continue
                bars.append(MarketBar(
                    timestamp=self._checkpoint_datetime(bar_raw["timestamp"]),
                    quote=self._checkpoint_quote(bar_raw["quote"]),
                    futures_price=float(bar_raw["futures_price"]),
                    iv=None if bar_raw.get("iv") is None else float(bar_raw["iv"]),
                    expected_move_remaining=(None if bar_raw.get("expected_move_remaining") is None else float(bar_raw["expected_move_remaining"])),
                ))
            last_quote = self._checkpoint_quote(raw["last_quote"]) if isinstance(raw.get("last_quote"), Mapping) else None
            self.state.open_position = OpenPosition(
                trade=trade,
                symbol=str(raw["symbol"]),
                underlying=underlying,
                expiry=expiry,
                stop_points=float(raw["stop_points"]),
                target_points=float(raw["target_points"]),
                max_duration_seconds=int(raw["max_duration_seconds"]),
                bars=bars,
                opened_at=self._checkpoint_datetime(raw.get("opened_at", raw["entry_time"])),
                last_premium=float(raw.get("last_premium", entry_fill.fill_price or 0.0)),
                highest_premium=float(raw.get("highest_premium", entry_fill.fill_price or 0.0)),
                lowest_premium=float(raw.get("lowest_premium", entry_fill.fill_price or 0.0)),
                last_quote=last_quote,
                entry_mode=str(raw.get("entry_mode", "CANONICAL")),
            )
            self.state.underlyings["_position_recovery"] = {
                "status": "RESTORED",
                "entry_mode": self.state.open_position.entry_mode,
                "trade_id": self.state.open_position.trade.trade_id,
                "entry_time": entry_time.isoformat(),
            }
            self._log(f"RESTORED paper position {self.state.open_position.symbol} from checkpoint")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError) as exc:
            self.state.underlyings["_position_recovery"] = {
                "status": "BLOCKED",
                "reason": f"Invalid paper position checkpoint: {type(exc).__name__}",
            }
            self._log(f"Paper position checkpoint blocked: {type(exc).__name__}: {exc}")

    def _restore_account_state(self) -> None:
        """Restore lifetime paper equity; daily risk counters reset by date."""
        raw: Mapping[str, Any] = {}
        try:
            loaded = json.loads(self._account_state_path.read_text(encoding="utf-8"))
            if isinstance(loaded, Mapping):
                raw = loaded
        except (OSError, json.JSONDecodeError):
            raw = {}
        if "realized_pnl" in raw:
            try:
                self.state.realized_pnl = float(raw["realized_pnl"])
            except (TypeError, ValueError):
                self.state.realized_pnl = 0.0
        else:
            # One-time bootstrap from canonical trades only; calibration evidence is excluded.
            total = 0.0
            ledger = self.state_dir / "trades.csv"
            try:
                with ledger.open("r", encoding="utf-8", newline="") as handle:
                    for row in csv.DictReader(handle):
                        try:
                            total += float(row.get("net_pnl", 0.0) or 0.0)
                        except (TypeError, ValueError):
                            continue
            except OSError:
                pass
            self.state.realized_pnl = total
        values = raw.get("equity")
        if isinstance(values, list):
            try:
                self.state.equity = [float(value) for value in values][-5000:]
            except (TypeError, ValueError):
                self.state.equity = []
        if not self.state.equity:
            self.state.equity = [round(self.state.realized_pnl, 2)]
        self._save_account_state()

    def _save_account_state(self) -> None:
        payload = {
            "version": 1,
            "updated_at": now_ist().isoformat(),
            "starting_capital": float(self.base_config.section("capital").get("starting_capital", 0.0)),
            "realized_pnl": round(float(self.state.realized_pnl), 2),
            "equity": self.state.equity[-5000:],
            "live_execution": "DISABLED",
        }
        tmp = self._account_state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._account_state_path)
    def _restore_daily_risk_state(self, now: datetime) -> None:
        """Restore same-day risk counters; never carry them into a new date."""
        try:
            raw = json.loads(self._daily_risk_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        stored_date = str(raw.get("date", "")) if isinstance(raw, Mapping) else ""
        stored_week = str(raw.get("week_key", "")) if isinstance(raw, Mapping) else ""
        current_week = (now.date() - timedelta(days=now.weekday())).isoformat()
        self._risk_week_key = current_week
        try:
            self.state.realized_pnl_week = float(raw.get("realized_pnl_week", 0.0)) if stored_week == current_week else 0.0
            if stored_date != now.date().isoformat():
                self._reset_daily_risk_state(now, persist=True)
                return
            self._daily_risk_date = stored_date
            self.state.realized_pnl_today = float(raw.get("realized_pnl_today", 0.0))
            self.state.trades_today = max(0, int(raw.get("trades_today", 0)))
            self.state.losses_today = max(0, int(raw.get("losses_today", 0)))
            self.state.loss_streak_today = max(0, int(raw.get("loss_streak_today", 0)))
            self.state.last_loss_at = str(raw.get("last_loss_at", ""))
            recent = raw.get("recent_direction_losses", {})
            self.state.recent_direction_losses = {
                str(k): str(v) for k, v in recent.items()
            } if isinstance(recent, Mapping) else {}
        except (TypeError, ValueError):
            self._reset_daily_risk_state(now, persist=True)

    def _reset_daily_risk_state(self, now: datetime, persist: bool = False) -> None:
        self._daily_risk_date = now.date().isoformat()
        self.state.realized_pnl_today = 0.0
        self.state.trades_today = 0
        self.state.losses_today = 0
        self.state.loss_streak_today = 0
        self.state.last_loss_at = ""
        self.state.recent_direction_losses = {}
        if persist:
            self._save_daily_risk_state()

    def _roll_daily_risk_state(self, now: datetime) -> None:
        current_week = (now.date() - timedelta(days=now.weekday())).isoformat()
        if current_week != self._risk_week_key:
            self._risk_week_key = current_week
            self.state.realized_pnl_week = 0.0
        if now.date().isoformat() != self._daily_risk_date:
            self._reset_daily_risk_state(now, persist=True)
        else:
            self._save_daily_risk_state()

    def _save_daily_risk_state(self) -> None:
        payload = {
            "date": self._daily_risk_date,
            "week_key": self._risk_week_key,
            "realized_pnl_today": self.state.realized_pnl_today,
            "realized_pnl_week": self.state.realized_pnl_week,
            "trades_today": self.state.trades_today,
            "losses_today": self.state.losses_today,
            "loss_streak_today": self.state.loss_streak_today,
            "last_loss_at": self.state.last_loss_at,
            "recent_direction_losses": dict(self.state.recent_direction_losses),
        }
        tmp = self._daily_risk_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._daily_risk_path)

    def _open_position_risk_reservation(self) -> float:
        total = 0.0
        for pos in self._positions():
            entry = float(pos.trade.entry_fill.fill_price or 0.0)
            last = float(pos.last_premium or entry)
            lot = max(1, int(pos.trade.entry_evaluation.candidate.instrument.lot_size))
            stop_price = max(0.0, entry - float(pos.stop_points))
            total += max(0.0, last - stop_price) * lot
        return total

    def _same_direction_loss_active(self, underlying: str, side: str, now: datetime) -> bool:
        """Return whether the same underlying/option side recently lost.

        Invalid persisted timestamps fail closed for that direction. State is
        cleared at the daily-risk rollover, so the rule cannot leak across days.
        """
        cooldown = float(self.config.section("opportunity_selection").get("same_direction_after_loss_cooldown_min", 30.0))
        if cooldown <= 0:
            return False
        key = f"{underlying}|{side}"
        raw = self.state.recent_direction_losses.get(key, "")
        if not raw:
            return False
        try:
            elapsed = (now - datetime.fromisoformat(raw)).total_seconds() / 60.0
        except (TypeError, ValueError):
            return True
        return elapsed < cooldown

    def _daily_risk_block_reason(self, now: datetime) -> str:
        risk = self.config.section("risk")
        open_risk = self._open_position_risk_reservation()
        self.state.underlyings["_risk_exposure"] = {
            "open_position_risk_reservation": open_risk,
            "realized_loss_today": max(0.0, -self.state.realized_pnl_today),
            "realized_loss_week": max(0.0, -self.state.realized_pnl_week),
            "timestamp": now.isoformat(),
        }
        max_trades = max(0, int(risk.get("max_trades_per_day", 0)))
        if max_trades and self.state.trades_today >= max_trades:
            return f"Maximum trades per day reached: {self.state.trades_today}/{max_trades}"
        if bool(risk.get("stop_trading_after_three_losses", False)) and self.state.losses_today >= 3:
            return "Stop-trading rule active after three daily losses"
        max_daily_loss = float(risk.get("max_daily_loss_rupees", 0.0))
        daily_exposure = max(0.0, -self.state.realized_pnl_today) + open_risk
        if max_daily_loss > 0 and daily_exposure >= max_daily_loss:
            return f"Maximum daily loss/risk exposure reached: {daily_exposure:.2f}/{max_daily_loss:.2f}"
        max_weekly_loss = float(risk.get("max_weekly_loss_rupees", 0.0))
        weekly_exposure = max(0.0, -self.state.realized_pnl_week) + open_risk
        if max_weekly_loss > 0 and weekly_exposure >= max_weekly_loss:
            return f"Maximum weekly loss/risk exposure reached: {weekly_exposure:.2f}/{max_weekly_loss:.2f}"
        if self.state.last_loss_at and self.state.loss_streak_today > 0:
            try:
                last_loss = datetime.fromisoformat(self.state.last_loss_at)
                elapsed_min = (now - last_loss).total_seconds() / 60.0
                cooldown = float(risk.get(
                    "cooldown_after_two_losses_minutes" if self.state.loss_streak_today >= 2
                    else "cooldown_after_one_loss_minutes", 0.0
                ))
                if elapsed_min < cooldown:
                    return f"Loss cooldown active: {cooldown - elapsed_min:.1f} minutes remaining"
            except (TypeError, ValueError):
                return "Invalid last-loss timestamp; new entries blocked"
        return ""

    @staticmethod
    def _hhmm_to_minutes(value: Any, default: int) -> int:
        try:
            hour, minute = str(value).strip().split(":", 1)
            parsed = int(hour) * 60 + int(minute)
            if 0 <= parsed <= 24 * 60:
                return parsed
        except (TypeError, ValueError):
            pass
        return default

    def _market_open(self, now: datetime) -> bool:
        if now.weekday() >= 5:
            return False
        minutes = now.hour * 60 + now.minute
        return 9 * 60 + 15 <= minutes <= 15 * 60 + 30

    def _short_dated_friday_block_reason(self, candidate, now: datetime) -> str:
        if now.weekday() != 4:
            return ""
        theta = self.config.section("theta")
        cutoff = self._hhmm_to_minutes(theta.get("no_new_short_dated_friday_after", "13:30"), 13 * 60 + 30)
        if now.hour * 60 + now.minute < cutoff:
            return ""
        try:
            dte = (candidate.instrument.expiry - now.date()).days
        except (AttributeError, TypeError):
            return "Short-dated Friday entry blocked: invalid expiry"
        if dte <= 1:
            return f"Short-dated Friday entry blocked after {theta.get('no_new_short_dated_friday_after', '13:30')}"
        return ""

    def _entry_window_open(self, now: datetime) -> bool:
        if not self._market_open(now):
            return False
        holding = self.config.section("holding_time")
        start = self._hhmm_to_minutes(holding.get("no_trade_before", "09:30"), 9 * 60 + 30)
        end = self._hhmm_to_minutes(holding.get("no_new_entries_after", "14:15"), 14 * 60 + 15)
        minutes = now.hour * 60 + now.minute
        return start <= minutes < end

    def _seconds_to_open(self) -> float:
        now = now_ist()
        target = now.replace(hour=9, minute=15, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        while target.weekday() >= 5:
            target += timedelta(days=1)
        return max(0.0, (target - now).total_seconds())

    def _direction_model_histories(self, underlying: str) -> dict[str, list]:
        runtime = self.config.raw.get("direction_model_runtime", {})
        if not isinstance(runtime, Mapping) or not bool(runtime.get("shadow_enabled", False)):
            return {}
        symbols = runtime.get("component_symbols", {}).get(str(underlying).upper(), [])
        if not isinstance(symbols, list):
            return {}
        out: dict[str, list] = {}
        for symbol in symbols:
            name = str(symbol).upper()
            out[name] = self._fetch_history(
                f"_direction_component_{name}",
                f"NSE:{name}-EQ",
            )
        return out

    def _fetch_history(self, underlying: str, index_symbol: str) -> list:
        # Replay mode is offline and per-cycle: never cache across cycles.
        if self._replay:
            try:
                resp = self.client.history(index_symbol, resolution="1")
                candles = resp.get("candles", []) if isinstance(resp, dict) else (resp or [])
                return [c for c in candles if isinstance(c, (list, tuple)) and len(c) >= 5][-self.history_bars:]
            except Exception:
                return []
        cached = self.history_cache.get(underlying)
        if cached is not None and (time.time() - cached[0]) < 60.0:
            return cached[1]
        try:
            now = datetime.now(IST)
            start = now - timedelta(days=5)
            resp = self.client.history(index_symbol, resolution="1",
                                        range_from=start.strftime("%Y-%m-%d"),
                                        range_to=now.strftime("%Y-%m-%d"))
            candles = resp.get("candles", []) if isinstance(resp, dict) else []
            candles = [c for c in candles if isinstance(c, (list, tuple)) and len(c) >= 5][-self.history_bars:]
            self.history_cache[underlying] = (time.time(), candles)
            return candles
        except Exception:
            return self.history_cache.get(underlying, (0, []))[1]

    def _select_expiry(self, underlying: str, cal, prefer_monthly: bool) -> str:
        if not cal:
            exps = self.master.expiry_dates(underlying)
            return str(exps[0]) if exps else date.today().isoformat()
        today = now_ist().date()
        future = [e for e in cal if date.fromtimestamp(e.expiry_ts) >= today]
        if prefer_monthly:
            future = [e for e in future if e.flag.upper() == "M"]
        if not future:
            future = list(cal)
        chosen = future[0]
        return date.fromtimestamp(chosen.expiry_ts).isoformat()

    def _overlay_config(self, config: SystemConfig) -> SystemConfig:
        overrides = self.cfg.get("config_overrides")
        signal_cfg = self.cfg.get("signal")
        if (not isinstance(overrides, dict) or not overrides) and not isinstance(signal_cfg, Mapping):
            return config
        import copy
        raw = copy.deepcopy(dict(config.raw))
        if isinstance(signal_cfg, Mapping):
            raw.setdefault("paper_runner", {})["signal"] = dict(signal_cfg)
        signal_applied = isinstance(signal_cfg, Mapping)
        changed: dict[str, dict[str, Any]] = {}
        if isinstance(overrides, dict):
            for section, values in overrides.items():
                if section == "_comment" or not isinstance(values, dict):
                    continue
                if section not in raw:
                    continue
                if not isinstance(raw[section], dict):
                    raw[section] = dict(values)
                    changed[section] = dict(values)
                    continue
                merged = {**raw[section], **values}
                for key, val in values.items():
                    if key == "_comment":
                        continue
                    if key not in raw[section] or raw[section][key] != val:
                        changed.setdefault(section, {})[key] = val
                raw[section] = merged
        self._active_overrides = changed
        execution = raw.get("execution", {})
        if isinstance(execution, Mapping) and execution.get("live_trading_enabled") is not False:
            raise ConfigError("PaperRunner rejects any override that enables live execution.")
        if not changed and not signal_applied:
            return config
        if changed:
            self._log(f"PAPER-ONLY config overrides active: {changed}")
        return SystemConfig(raw=raw)

    def _log(self, msg: str) -> None:
        print(f"[{now_ist().strftime('%H:%M:%S')}] {msg}", flush=True)

