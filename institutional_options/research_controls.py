"""Research controls for the paper-only options system.

This module deliberately keeps research promotion separate from the frozen trade
universe.  It provides:

* explicit instrument lifecycle states;
* stable strategy/score version fingerprints;
* measured, instrument-class-specific liquidity gates;
* post-cost counterfactual outcome calibration; and
* promotion recommendations that never mutate trade eligibility.

The store is append-safe and persists only aggregate research statistics.  It is
not a live-trading permission service.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Optional

from .models import CalibrationStatus


class InstrumentLifecycle(str, Enum):
    MONITOR = "MONITOR"
    SHADOW = "SHADOW"
    PAPER_ELIGIBLE = "PAPER_ELIGIBLE"
    TRADE_ELIGIBLE = "TRADE_ELIGIBLE"
    RETIRED = "RETIRED"


class InstrumentClass(str, Enum):
    NSE_INDEX = "NSE_INDEX"
    BSE_INDEX = "BSE_INDEX"
    NSE_STOCK_OPTION = "NSE_STOCK_OPTION"
    BSE_STOCK_OPTION = "BSE_STOCK_OPTION"

    @classmethod
    def from_metadata(cls, exchange: str, instrument_kind: str) -> "InstrumentClass":
        exchange = str(exchange or "NSE").upper()
        kind = str(instrument_kind or "INDEX").upper()
        if kind in {"STOCK", "STOCK_OPTION", "OPTSTK"}:
            return cls.BSE_STOCK_OPTION if exchange == "BSE" else cls.NSE_STOCK_OPTION
        return cls.BSE_INDEX if exchange == "BSE" else cls.NSE_INDEX


@dataclass(frozen=True)
class StrategyVersions:
    strategy_version: str
    score_version: str
    universe_version: str
    parameter_profile: str = "FROZEN_PARAMETERS"


def version_fingerprint(
    config: Any,
    universe: Optional[Mapping[str, Any]] = None,
    parameter_profile: str = "FROZEN_PARAMETERS",
) -> StrategyVersions:
    """Return reproducible fingerprints for evidence rows and event replay."""
    raw = getattr(config, "raw", config)
    payload = json.dumps(raw, sort_keys=True, default=str, separators=(",", ":"))
    cfg_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    universe_payload = json.dumps(universe or {}, sort_keys=True, default=str, separators=(",", ":"))
    uni_hash = hashlib.sha256(universe_payload.encode("utf-8")).hexdigest()[:12]
    return StrategyVersions(
        strategy_version=f"paper-strategy-{cfg_hash}",
        score_version=f"opportunity-score-{cfg_hash}",
        universe_version=f"universe-{uni_hash}",
        parameter_profile=str(parameter_profile),
    )


def exposure_group(underlying: str, instrument_kind: str = "INDEX") -> str:
    """Conservative factor grouping used for counterfactual independence labels."""
    name = str(underlying or "").upper()
    kind = str(instrument_kind or "INDEX").upper()
    if kind in {"STOCK", "STOCK_OPTION", "OPTSTK"}:
        return f"STOCK:{name}"
    if name in {"BANKNIFTY", "BANKEX"}:
        return "INDEX:BANKING"
    if name in {"NIFTY", "NIFTYNXT50", "NIFTYFPI"}:
        return "INDEX:BROAD_EQUITY"
    if name == "FINNIFTY":
        return "INDEX:FINANCIALS"
    if name == "MIDCPNIFTY":
        return "INDEX:MIDCAP"
    if name == "SENSEX":
        return "INDEX:BSE_BROAD"
    if name == "FOCIT":
        return "INDEX:BSE_OTHER"
    return f"INDEX:{name}"


@dataclass(frozen=True)
class ClassGateSet:
    instrument_class: str
    status: CalibrationStatus
    contract_quality_min: float
    atm_spread_ideal_pct: float
    atm_spread_acceptable_pct: float
    atm_spread_reject_pct: float
    itm_spread_ideal_pct: float
    itm_spread_acceptable_pct: float
    itm_spread_reject_pct: float
    otm_spread_ideal_pct: float
    otm_spread_acceptable_pct: float
    otm_spread_reject_pct: float
    absolute_spread_cap_points: float
    min_top_book_lots: float
    min_5depth_lots_each_side: float
    min_quote_freshness_sec: float
    min_valid_quote_rate: float
    min_paper_fill_rate: float
    excellent_score_min: float
    min_calibrated_probability: float
    min_net_expectancy_r: float
    minimum_observations: int
    minimum_days: int
    observations: int = 0
    sessions: int = 0
    valid_quote_rate: float = 0.0
    paper_fill_rate: float = 0.0
    median_spread_pct: float = 0.0
    p90_spread_pct: float = 0.0
    median_depth_lots: float = 0.0
    calibrated_probability: Optional[float] = None
    calibrated_net_expectancy_r: Optional[float] = None
    instrument_id: str = ""
    gate_learning_status: str = "CLASS_FLOOR_WARMUP"
    gate_snapshot_id: str = ""
    gate_learning_observations: int = 0
    gate_learning_sessions: int = 0
    gate_learning_outcomes: int = 0
    highest_observed_gate: Mapping[str, Any] = field(default_factory=dict)
    high_watermark_gate: Mapping[str, Any] = field(default_factory=dict)
    direction_min: float = 65.0
    premium_elasticity_min: float = 1.0
    expected_required_ratio_min: float = 1.6
    trade_quality_min: float = 70.0
    final_confidence_min: float = 65.0
    execution_quality_min: float = 0.0
    regime_confidence_min: float = 60.0
    market_hostility_max: float = 35.0
    iv_crush_max: float = 50.0
    spread_pct_max: float = float("inf")
    gate_resolution_path: str = "GLOBAL_POLICY_FLOOR>CLASS_FLOOR>INSTRUMENT_LEARNED_FLOOR"
    gate_optimization_method: str = "CONSTRAINED_WALK_FORWARD"
    gate_optimization_status: str = "NOT_READY"
    gate_optimization_quantile: Optional[float] = None
    gate_validation_observations: int = 0
    gate_validation_sessions: int = 0
    gate_validation_expectancy_r: Optional[float] = None
    gate_validation_drawdown_r: Optional[float] = None
    gate_validation_retention: float = 0.0
    gate_last_validated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["status"] = self.status.value
        return out


_DEFAULT_CLASS_PROFILES: dict[str, dict[str, Any]] = {
    # This is intentionally equal to the frozen MVP index liquidity policy.
    InstrumentClass.NSE_INDEX.value: {
        "contract_quality_min": 80, "atm_spread_ideal_pct": 1.0,
        "atm_spread_acceptable_pct": 1.5, "atm_spread_reject_pct": 2.0,
        "itm_spread_ideal_pct": 1.2, "itm_spread_acceptable_pct": 1.8,
        "itm_spread_reject_pct": 2.5, "otm_spread_ideal_pct": 2.0,
        "otm_spread_acceptable_pct": 3.0, "otm_spread_reject_pct": 4.0,
        "absolute_spread_cap_points": 8, "min_top_book_lots": 2,
        "min_5depth_lots_each_side": 10, "min_quote_freshness_sec": 8,
        "min_valid_quote_rate": 0.95, "min_paper_fill_rate": 0.80,
        "excellent_score_min": 80, "min_calibrated_probability": 0.50,
        "min_net_expectancy_r": 0.0, "minimum_observations": 100,
        "minimum_days": 20,
    },
    InstrumentClass.BSE_INDEX.value: {
        "contract_quality_min": 85, "atm_spread_ideal_pct": 1.0,
        "atm_spread_acceptable_pct": 1.8, "atm_spread_reject_pct": 3.0,
        "itm_spread_ideal_pct": 1.5, "itm_spread_acceptable_pct": 2.2,
        "itm_spread_reject_pct": 3.5, "otm_spread_ideal_pct": 2.5,
        "otm_spread_acceptable_pct": 3.5, "otm_spread_reject_pct": 5.0,
        "absolute_spread_cap_points": 10, "min_top_book_lots": 3,
        "min_5depth_lots_each_side": 15, "min_quote_freshness_sec": 8,
        "min_valid_quote_rate": 0.97, "min_paper_fill_rate": 0.85,
        "excellent_score_min": 85, "min_calibrated_probability": 0.52,
        "min_net_expectancy_r": 0.0, "minimum_observations": 150,
        "minimum_days": 20,
    },
    InstrumentClass.NSE_STOCK_OPTION.value: {
        "contract_quality_min": 90, "atm_spread_ideal_pct": 1.0,
        "atm_spread_acceptable_pct": 1.8, "atm_spread_reject_pct": 3.0,
        "itm_spread_ideal_pct": 1.5, "itm_spread_acceptable_pct": 2.5,
        "itm_spread_reject_pct": 4.0, "otm_spread_ideal_pct": 2.5,
        "otm_spread_acceptable_pct": 4.0, "otm_spread_reject_pct": 6.0,
        "absolute_spread_cap_points": 12, "min_top_book_lots": 3,
        "min_5depth_lots_each_side": 20, "min_quote_freshness_sec": 8,
        "min_valid_quote_rate": 0.98, "min_paper_fill_rate": 0.88,
        "excellent_score_min": 87, "min_calibrated_probability": 0.55,
        "min_net_expectancy_r": 0.0, "minimum_observations": 200,
        "minimum_days": 20,
    },
    InstrumentClass.BSE_STOCK_OPTION.value: {
        "contract_quality_min": 92, "atm_spread_ideal_pct": 1.5,
        "atm_spread_acceptable_pct": 2.5, "atm_spread_reject_pct": 4.0,
        "itm_spread_ideal_pct": 2.0, "itm_spread_acceptable_pct": 3.0,
        "itm_spread_reject_pct": 5.0, "otm_spread_ideal_pct": 3.0,
        "otm_spread_acceptable_pct": 5.0, "otm_spread_reject_pct": 7.0,
        "absolute_spread_cap_points": 15, "min_top_book_lots": 4,
        "min_5depth_lots_each_side": 25, "min_quote_freshness_sec": 8,
        "min_valid_quote_rate": 0.98, "min_paper_fill_rate": 0.90,
        "excellent_score_min": 90, "min_calibrated_probability": 0.57,
        "min_net_expectancy_r": 0.0, "minimum_observations": 250,
        "minimum_days": 20,
    },
}


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


LOWER_GATE_FEATURES = (
    "contract_quality_min", "direction_min", "premium_elasticity_min",
    "expected_required_ratio_min", "trade_quality_min", "final_confidence_min",
    "execution_quality_min", "regime_confidence_min", "min_top_book_lots",
    "min_5depth_lots_each_side", "excellent_score_min",
)
UPPER_GATE_FEATURES = ("spread_pct_max", "market_hostility_max", "iv_crush_max")


def _gate_passes(features: Mapping[str, Any], gate: Mapping[str, Any]) -> bool:
    for name in LOWER_GATE_FEATURES:
        if name in gate and features.get(name) is not None:
            try:
                if float(features[name]) < float(gate[name]):
                    return False
            except (TypeError, ValueError):
                return False
    for name in UPPER_GATE_FEATURES:
        if name in gate and features.get(name) is not None:
            try:
                if float(features[name]) > float(gate[name]):
                    return False
            except (TypeError, ValueError):
                return False
    return True


def _max_drawdown_r(values: list[float]) -> float:
    peak = 0.0
    cumulative = 0.0
    drawdown = 0.0
    for value in values:
        cumulative += float(value)
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    return drawdown


def gate_feature_snapshot(evaluation) -> dict[str, float]:
    """Return the exact gate features used by the per-instrument optimizer.

    This is intentionally duck-typed so the evidence and calibration layers do
    not depend on the scorer implementation. It must remain a research snapshot
    of observed candidate facts, never a fabricated approval flag.
    """
    c = evaluation.candidate
    lot = max(1, int(c.instrument.lot_size))
    mid = c.quote.mid
    spread_pct = c.quote.spread / mid * 100.0 if mid > 0 else 999.0
    features = {
        "contract_quality_min": float(evaluation.contract_quality.score),
        "direction_min": max(0.0, float(c.instrument_direction_score)),
        "premium_elasticity_min": float(c.premium_elasticity),
        "expected_required_ratio_min": float(c.expected_required_ratio),
        "trade_quality_min": float(c.trade_quality_score),
        "final_confidence_min": float(c.opportunity_confidence_score),
        "execution_quality_min": float(c.execution_quality_score),
        "regime_confidence_min": float(c.regime_confidence),
        "market_hostility_max": float(c.market_hostility_score),
        "iv_crush_max": float(c.iv_crush_risk_score),
        "spread_pct_max": float(spread_pct),
        "min_top_book_lots": float(min(c.quote.bid_qty, c.quote.ask_qty) / lot),
        "excellent_score_min": float(evaluation.comparable_opportunity_score),
    }
    if c.quote.cumulative_bid_qty_5depth is not None and c.quote.cumulative_ask_qty_5depth is not None:
        features["min_5depth_lots_each_side"] = float(
            min(c.quote.cumulative_bid_qty_5depth, c.quote.cumulative_ask_qty_5depth) / lot
        )
    return features


class InstrumentCalibrationStore:
    """Persist class-level observations and score-outcome calibration."""

    def __init__(self, state_dir: str | Path, config: Any):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.state_dir / "instrument_calibration.json"
        raw_config = getattr(config, "raw", {}) or {}
        self.raw_config = raw_config
        configured = raw_config.get("instrument_class_profiles", {})
        default_retirement = {
            "minimum_shadow_outcomes": 20,
            "minimum_paper_trades": 50,
            "negative_expectancy_retire_threshold_r": -0.25,
            "data_quality_degradation_factor": 0.80,
        }
        configured_retirement = raw_config.get("retirement_rules", {})
        self.retirement_rules = dict(default_retirement)
        if isinstance(configured_retirement, Mapping):
            self.retirement_rules.update(configured_retirement)
        configured_learning = raw_config.get("instrument_gate_learning", {})
        default_learning = {
            "enabled": True,
            "warmup_days": 5,
            "minimum_learning_observations": 100,
            "minimum_learning_days": 20,
            "minimum_learning_outcomes": 20,
            "winning_quantile": 0.25,
            "high_watermark_quantile": 0.90,
            "candidate_quantiles": [0.50, 0.60, 0.70, 0.75, 0.80, 0.90],
            "validation_fraction": 0.30,
            "minimum_validation_outcomes": 10,
            "minimum_validation_days": 5,
            "validation_min_expectancy_r": 0.10,
            "validation_max_drawdown_r": 10.0,
            "minimum_retention": 0.60,
            "maximum_gate_update_step_fraction": 0.10,
            "required_stable_validation_windows": 2,
            "do_not_loosen": True,
            "positive_expectancy_required": True,
        }
        self.learning_rules = dict(default_learning)
        if isinstance(configured_learning, Mapping):
            self.learning_rules.update(configured_learning)
        self.profiles: dict[str, dict[str, Any]] = {}
        for key, default in _DEFAULT_CLASS_PROFILES.items():
            override = configured.get(key, {}) if isinstance(configured, Mapping) else {}
            merged = dict(default)
            if isinstance(override, Mapping):
                merged.update(override)
            self.profiles[key] = merged
        self.state = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"classes": {}, "outcomes": {}, "instruments": {}, "gate_learning": {}, "lifecycle": {}, "updated_at": ""}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return {"classes": {}, "outcomes": {}, "instruments": {}, "gate_learning": {}, "lifecycle": {}, "updated_at": ""}
            raw.setdefault("classes", {})
            raw.setdefault("outcomes", {})
            raw.setdefault("instruments", {})
            raw.setdefault("gate_learning", {})
            raw.setdefault("lifecycle", {})
            return raw
        except (OSError, json.JSONDecodeError):
            return {"classes": {}, "outcomes": {}, "instruments": {}, "gate_learning": {}, "lifecycle": {}, "updated_at": ""}

    def _save(self) -> None:
        self.state["updated_at"] = datetime.now(timezone.utc).isoformat()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def lifecycle_state(self, instrument_id: str, default: InstrumentLifecycle = InstrumentLifecycle.MONITOR) -> InstrumentLifecycle:
        raw = self.state.setdefault("lifecycle", {}).get(str(instrument_id), default.value)
        try:
            return InstrumentLifecycle(str(raw))
        except ValueError:
            return default

    def set_lifecycle_state(self, instrument_id: str, state: InstrumentLifecycle) -> None:
        self.state.setdefault("lifecycle", {})[str(instrument_id)] = InstrumentLifecycle(state).value
        self._save()

    def record_observation(self, instrument_class: str, observed_at: datetime,
                           valid_quote: bool, paper_fillable: bool,
                           spread_pct: Optional[float], top_book_lots: Optional[float],
                           depth_lots: Optional[float], stale: bool = False,
                           instrument_id: Optional[str] = None) -> None:
        key = str(instrument_class)
        row = self.state.setdefault("classes", {}).setdefault(key, {
            "observations": 0, "valid_quotes": 0, "paper_fills": 0,
            "stale_quotes": 0, "sessions": [], "spread_samples": [],
            "top_book_samples": [], "depth_samples": [],
        })
        row["observations"] = int(row.get("observations", 0)) + 1
        row["valid_quotes"] = int(row.get("valid_quotes", 0)) + int(bool(valid_quote))
        row["paper_fills"] = int(row.get("paper_fills", 0)) + int(bool(paper_fillable))
        row["stale_quotes"] = int(row.get("stale_quotes", 0)) + int(bool(stale))
        sessions = set(row.get("sessions", []))
        sessions.add(observed_at.date().isoformat())
        row["sessions"] = sorted(sessions)[-1000:]
        for field_name, value in (("spread_samples", spread_pct), ("top_book_samples", top_book_lots), ("depth_samples", depth_lots)):
            if value is None:
                continue
            try:
                num = float(value)
            except (TypeError, ValueError):
                continue
            samples = list(row.get(field_name, []))
            samples.append(num)
            row[field_name] = samples[-2000:]
        if instrument_id:
            inst = self.state.setdefault("instruments", {}).setdefault(str(instrument_id), {
                "instrument_class": key, "observations": 0, "valid_quotes": 0,
                "paper_fills": 0, "sessions": [], "shadow_outcomes": 0,
                "shadow_wins": 0, "shadow_sum_r": 0.0, "paper_trades": 0,
                "paper_wins": 0, "paper_sum_r": 0.0, "max_drawdown_r": 0.0,
            })
            inst["instrument_class"] = key
            inst["observations"] = int(inst.get("observations", 0)) + 1
            inst["valid_quotes"] = int(inst.get("valid_quotes", 0)) + int(bool(valid_quote))
            inst["paper_fills"] = int(inst.get("paper_fills", 0)) + int(bool(paper_fillable))
            sessions = set(inst.get("sessions", [])); sessions.add(observed_at.date().isoformat())
            inst["sessions"] = sorted(sessions)[-1000:]
        self._save()

    def record_gate_observation(self, instrument_id: str, instrument_class: str,
                                observed_at: datetime, features: Mapping[str, Any],
                                eligible: bool, score: float) -> None:
        """Persist per-instrument observations for conservative gate learning."""
        key = str(instrument_id)
        row = self.state.setdefault("gate_learning", {}).setdefault(key, {
            "instrument_class": str(instrument_class), "observations": [], "outcomes": [],
            "sessions": [], "highest_observed_gate": {},
        })
        row["instrument_class"] = str(instrument_class)
        normalized = {}
        for name, value in dict(features).items():
            try:
                normalized[name] = value if value is None or isinstance(value, bool) else float(value)
            except (TypeError, ValueError):
                normalized[name] = str(value)
        row["observations"].append({
            "ts": observed_at.isoformat(), "date": observed_at.date().isoformat(),
            "eligible": bool(eligible), "score": float(score), "features": normalized,
        })
        row["observations"] = row["observations"][-5000:]
        sessions = set(row.get("sessions", [])); sessions.add(observed_at.date().isoformat())
        row["sessions"] = sorted(sessions)[-1000:]
        row["highest_observed_gate"] = self._highest_observed_gate(row["observations"])
        high_q = min(0.99, max(0.50, _safe_float(self.learning_rules.get("high_watermark_quantile"), 0.90)))
        row["high_watermark_gate"] = self._highest_observed_gate(row["observations"], quantile=high_q)
        self._save()

    @staticmethod
    def _highest_observed_gate(observations: list[Mapping[str, Any]], quantile: float = 1.0) -> dict[str, Any]:
        lower = LOWER_GATE_FEATURES
        upper = UPPER_GATE_FEATURES
        out: dict[str, Any] = {}
        eligible = [obs for obs in observations if bool(obs.get("eligible"))]
        q = min(1.0, max(0.5, float(quantile)))
        for name in lower:
            vals = []
            for obs in eligible:
                try:
                    value = obs.get("features", {}).get(name)
                    if value is not None: vals.append(float(value))
                except (TypeError, ValueError):
                    pass
            if vals: out[name] = InstrumentCalibrationStore._percentile(vals, q)
        for name in upper:
            vals = []
            for obs in eligible:
                try:
                    value = obs.get("features", {}).get(name)
                    if value is not None: vals.append(float(value))
                except (TypeError, ValueError):
                    pass
            if vals: out[name] = InstrumentCalibrationStore._percentile(vals, 1.0 - q)
        return out

    def record_outcome(self, instrument_class: str, score: float, r_multiple: float,
                       net_pnl: float, success: Optional[bool] = None,
                       instrument_id: Optional[str] = None, paper: bool = False,
                       features: Optional[Mapping[str, Any]] = None,
                       observed_at: Optional[datetime] = None,
                       cost_model_valid: bool = True) -> None:
        observed_at = observed_at or datetime.now(timezone.utc)
        key = str(instrument_class)
        row = self.state.setdefault("outcomes", {}).setdefault(key, {
            "count": 0, "wins": 0, "sum_r": 0.0, "sum_pnl": 0.0,
            "score_buckets": {},
        })
        if success is None:
            success = float(r_multiple) > 0.0
        if cost_model_valid:
            row["count"] = int(row.get("count", 0)) + 1
            row["wins"] = int(row.get("wins", 0)) + int(bool(success))
            row["sum_r"] = float(row.get("sum_r", 0.0)) + float(r_multiple)
            row["sum_pnl"] = float(row.get("sum_pnl", 0.0)) + float(net_pnl)
            bucket = self.score_bucket(score)
            bucket_row = row.setdefault("score_buckets", {}).setdefault(bucket, {"count": 0, "wins": 0, "sum_r": 0.0})
            bucket_row["count"] += 1
            bucket_row["wins"] += int(bool(success))
            bucket_row["sum_r"] += float(r_multiple)
        if instrument_id:
            gate_row = self.state.setdefault("gate_learning", {}).setdefault(str(instrument_id), {
                "instrument_class": key, "observations": [], "outcomes": [], "sessions": [],
                "highest_observed_gate": {},
            })
            normalized = {}
            for name, value in dict(features or {}).items():
                try:
                    normalized[name] = value if value is None or isinstance(value, bool) else float(value)
                except (TypeError, ValueError):
                    normalized[name] = str(value)
            gate_row["outcomes"].append({
                "ts": observed_at.isoformat(), "score": float(score), "r_multiple": float(r_multiple), "net_pnl": float(net_pnl),
                "success": bool(success), "paper": bool(paper), "proxy": False,
                "cost_model_valid": bool(cost_model_valid), "features": normalized,
            })
            gate_row["outcomes"] = gate_row["outcomes"][-1000:]
            inst = self.state.setdefault("instruments", {}).setdefault(str(instrument_id), {
                "instrument_class": key, "observations": 0, "valid_quotes": 0,
                "paper_fills": 0, "sessions": [], "shadow_outcomes": 0,
                "shadow_wins": 0, "shadow_sum_r": 0.0, "paper_trades": 0,
                "paper_wins": 0, "paper_sum_r": 0.0, "max_drawdown_r": 0.0,
            })
            if cost_model_valid:
                field = "paper" if paper else "shadow"
                inst[f"{field}_outcomes" if not paper else "paper_trades"] = int(inst.get(f"{field}_outcomes" if not paper else "paper_trades", 0)) + 1
                inst[f"{field}_wins"] = int(inst.get(f"{field}_wins", 0)) + int(bool(success))
                prior_sum_r = float(inst.get(f"{field}_sum_r", 0.0))
                new_sum_r = prior_sum_r + float(r_multiple)
                inst[f"{field}_sum_r"] = new_sum_r
                if paper:
                    peak_r = max(float(inst.get("paper_peak_r", 0.0)), new_sum_r)
                    inst["paper_peak_r"] = peak_r
                    inst["max_drawdown_r"] = max(
                        float(inst.get("max_drawdown_r", 0.0)), peak_r - new_sum_r
                    )
        if instrument_id:
            self._refresh_optimizer(str(instrument_id), key)
        self._save()

    def record_forward_outcomes(self, rows: list[Mapping[str, Any]], cost_model_valid: bool = False) -> int:
        """Persist observed skipped-forward rows as proxy research outcomes only.

        Proxy rows remain research-only and are excluded from canonical optimizer
        validation unless the current cost model is explicitly validated.
        """
        added = 0
        touched: set[tuple[str, str]] = set()
        for source in rows:
            if str(source.get("status", "")) != "OBSERVED":
                continue
            instrument_id = str(source.get("instrument_id") or source.get("underlying") or "")
            instrument_class = str(source.get("instrument_class") or "")
            if not instrument_id or not instrument_class:
                continue
            try:
                r_multiple = float(source.get("forward_r_multiple"))
                score = float(source.get("ComparableOpportunityScore"))
                features = json.loads(str(source.get("gate_features_json", "{}")))
                observed_at = datetime.fromisoformat(str(source.get("observed_at")))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(features, Mapping):
                continue
            key = instrument_id
            row = self.state.setdefault("gate_learning", {}).setdefault(key, {
                "instrument_class": instrument_class, "observations": [], "outcomes": [],
                "forward_outcomes": [], "sessions": [], "highest_observed_gate": {},
            })
            row["instrument_class"] = instrument_class
            existing = {(str(item.get("skip_id", "")), str(item.get("window_minutes", ""))) for item in row.get("forward_outcomes", [])}
            dedupe_key = (str(source.get("skip_id", "")), str(source.get("window_minutes", "")))
            if dedupe_key in existing:
                continue
            row.setdefault("forward_outcomes", []).append({
                "ts": observed_at.isoformat(), "skip_id": dedupe_key[0], "window_minutes": dedupe_key[1],
                "score": score, "r_multiple": r_multiple, "success": r_multiple > 0.0,
                "features": {str(k): v for k, v in features.items()}, "proxy": True,
                "cost_model_valid": bool(cost_model_valid),
            })
            row["forward_outcomes"] = row["forward_outcomes"][-2000:]
            touched.add((key, instrument_class))
            added += 1
        for instrument_id, instrument_class in touched:
            self._refresh_optimizer(instrument_id, instrument_class)
        if added:
            self._save()
        return added

    @staticmethod
    def score_bucket(score: float) -> str:
        value = max(0, min(100, int(float(score) // 10) * 10))
        return f"{value:02d}-{min(100, value + 10):02d}"

    def _metrics(self, instrument_class: str) -> dict[str, Any]:
        row = self.state.get("classes", {}).get(str(instrument_class), {})
        observations = int(row.get("observations", 0))
        spreads = [float(x) for x in row.get("spread_samples", [])]
        depths = [float(x) for x in row.get("depth_samples", [])]
        return {
            "observations": observations,
            "sessions": len(row.get("sessions", [])),
            "valid_quote_rate": (int(row.get("valid_quotes", 0)) / observations) if observations else 0.0,
            "paper_fill_rate": (int(row.get("paper_fills", 0)) / observations) if observations else 0.0,
            "median_spread_pct": median(spreads) if spreads else 0.0,
            "p90_spread_pct": self._percentile(spreads, 0.90),
            "median_depth_lots": median(depths) if depths else 0.0,
        }

    @staticmethod
    def _percentile(values: list[float], p: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, math.ceil(p * len(ordered)) - 1))
        return ordered[index]

    def outcome_calibration(self, instrument_class: str, score: float) -> tuple[Optional[float], Optional[float], CalibrationStatus]:
        profile = self.profiles.get(str(instrument_class), _DEFAULT_CLASS_PROFILES[InstrumentClass.NSE_INDEX.value])
        row = self.state.get("outcomes", {}).get(str(instrument_class), {})
        count = int(row.get("count", 0))
        minimum = max(20, _safe_int(profile.get("minimum_outcome_observations", 20), 20))
        bucket = row.get("score_buckets", {}).get(self.score_bucket(score), {})
        bcount = int(bucket.get("count", 0))
        if count < minimum or bcount < 5:
            return None, None, CalibrationStatus.OBSERVED if count else CalibrationStatus.UNVALIDATED
        probability = float(bucket.get("wins", 0)) / bcount
        ev = float(bucket.get("sum_r", 0.0)) / bcount
        return probability, ev, CalibrationStatus.VALIDATED

    def _class_floor_gate(self, instrument_class: str) -> dict[str, float]:
        profile = self.profiles.get(str(instrument_class), self.profiles[InstrumentClass.NSE_INDEX.value])
        raw = getattr(self, "raw_config", {})
        score_cfg = raw.get("scores", {}) if isinstance(raw, Mapping) else {}
        elasticity_cfg = raw.get("premium_elasticity", {}) if isinstance(raw, Mapping) else {}
        expected_cfg = raw.get("expected_move", {}) if isinstance(raw, Mapping) else {}
        defaults = {
            "contract_quality_min": _safe_float(profile.get("contract_quality_min"), 80.0),
            "direction_min": _safe_float(score_cfg.get("direction_min"), 65.0),
            "premium_elasticity_min": _safe_float(elasticity_cfg.get("reject_or_exit_threshold"), 0.5),
            "expected_required_ratio_min": _safe_float(expected_cfg.get("hard_reject_ratio"), 1.1),
            "trade_quality_min": _safe_float(score_cfg.get("trade_quality_min"), 70.0),
            "final_confidence_min": _safe_float(score_cfg.get("final_confidence_min"), 65.0),
            "execution_quality_min": 0.0,
            "regime_confidence_min": _safe_float(score_cfg.get("regime_confidence_min"), 60.0),
            "min_top_book_lots": _safe_float(profile.get("min_top_book_lots"), 2.0),
            "min_5depth_lots_each_side": _safe_float(profile.get("min_5depth_lots_each_side"), 10.0),
            "excellent_score_min": _safe_float(profile.get("excellent_score_min"), 80.0),
        }
        gate = {name: _safe_float(profile.get(name), defaults[name]) for name in LOWER_GATE_FEATURES}
        gate.update({
            "spread_pct_max": _safe_float(profile.get("spread_pct_max"), float("inf")),
            "market_hostility_max": _safe_float(profile.get("market_hostility_max"), 35.0),
            "iv_crush_max": _safe_float(profile.get("iv_crush_max"), 50.0),
        })
        return gate

    def _derive_candidate_gate(self, samples: list[Mapping[str, Any]], quantile: float) -> dict[str, float]:
        winners = [item.get("features", {}) for item in samples if bool(item.get("success")) and isinstance(item.get("features"), Mapping)]
        gate: dict[str, float] = {}
        q = min(0.95, max(0.50, float(quantile)))
        for name in LOWER_GATE_FEATURES:
            values = []
            for features in winners:
                try:
                    if features.get(name) is not None:
                        values.append(float(features[name]))
                except (TypeError, ValueError):
                    pass
            if values:
                gate[name] = self._percentile(values, q)
        for name in UPPER_GATE_FEATURES:
            values = []
            for features in winners:
                try:
                    if features.get(name) is not None:
                        values.append(float(features[name]))
                except (TypeError, ValueError):
                    pass
            if values:
                gate[name] = self._percentile(values, 1.0 - q)
        return gate

    @staticmethod
    def _gate_retention(gate: Mapping[str, Any], observations: list[Mapping[str, Any]]) -> float:
        usable = [item for item in observations if isinstance(item.get("features"), Mapping)]
        if not usable:
            return 0.0
        return sum(1 for item in usable if _gate_passes(item.get("features", {}), gate)) / len(usable)

    @staticmethod
    def _evaluate_gate(gate: Mapping[str, Any], samples: list[Mapping[str, Any]]) -> dict[str, Any]:
        usable = [item for item in samples if isinstance(item.get("features"), Mapping)]
        passed = [item for item in usable if _gate_passes(item.get("features", {}), gate)]
        values = [float(item.get("r_multiple", 0.0)) for item in passed]
        return {
            "observations": len(passed),
            "available": len(usable),
            "expectancy_r": (sum(values) / len(values)) if values else None,
            "drawdown_r": _max_drawdown_r(values) if values else None,
            "retention": (len(passed) / len(usable)) if usable else 0.0,
        }

    def _bounded_gate_update(self, candidate: Mapping[str, Any], previous: Mapping[str, Any]) -> dict[str, float]:
        step = min(0.50, max(0.01, _safe_float(self.learning_rules.get("maximum_gate_update_step_fraction"), 0.10)))
        bounded: dict[str, float] = {}
        for name, value in candidate.items():
            try:
                new_value = float(value)
            except (TypeError, ValueError):
                continue
            if name not in previous:
                bounded[name] = new_value
                continue
            try:
                old_value = float(previous[name])
            except (TypeError, ValueError):
                bounded[name] = new_value
                continue
            if name in LOWER_GATE_FEATURES and old_value > 0:
                bounded[name] = min(new_value, old_value * (1.0 + step))
            elif name in UPPER_GATE_FEATURES and math.isfinite(old_value) and old_value > 0:
                bounded[name] = max(new_value, old_value * (1.0 - step))
            else:
                bounded[name] = new_value
        return bounded

    def _refresh_optimizer(self, instrument_id: str, instrument_class: str) -> None:
        """Recompute research diagnostics and persist only validated gate changes."""
        row = self.state.setdefault("gate_learning", {}).setdefault(str(instrument_id), {})
        observations = list(row.get("observations", []))
        actual = [item for item in row.get("outcomes", []) if isinstance(item, Mapping) and item.get("cost_model_valid") is True]
        proxy = [item for item in row.get("forward_outcomes", []) if isinstance(item, Mapping) and item.get("cost_model_valid") is True]
        min_obs = _safe_int(self.learning_rules.get("minimum_learning_observations"), 100)
        min_days = max(_safe_int(self.learning_rules.get("minimum_learning_days"), 20), _safe_int(self.learning_rules.get("warmup_days"), 5))
        min_outcomes = _safe_int(self.learning_rules.get("minimum_learning_outcomes"), 20)
        min_validation = _safe_int(self.learning_rules.get("minimum_validation_outcomes"), 10)
        min_validation_days = _safe_int(self.learning_rules.get("minimum_validation_days"), 5)
        validation_fraction = min(0.50, max(0.10, _safe_float(self.learning_rules.get("validation_fraction"), 0.30)))
        required_windows = _safe_int(self.learning_rules.get("required_stable_validation_windows"), 2)
        highest = dict(row.get("highest_observed_gate", {}))
        meta = dict(row.get("optimizer", {}))
        meta.update({
            "method": "CONSTRAINED_WALK_FORWARD",
            "observations": len(observations), "sessions": len(set(row.get("sessions", []))),
            "outcomes": len(actual), "proxy_outcomes": len(proxy),
            "last_refresh": datetime.now(timezone.utc).isoformat(),
        })
        if len(observations) < min_obs or len(set(row.get("sessions", []))) < min_days:
            meta.update({"status": "WARMUP_OBSERVATIONS", "validation_observations": 0})
            row["optimizer"] = meta
            return
        if len(actual) < min_outcomes:
            meta.update({"status": "WARMUP_OUTCOMES", "validation_observations": 0})
            row["optimizer"] = meta
            return
        actual = sorted(actual, key=lambda item: str(item.get("ts", "")))
        validation_total = min_validation * required_windows
        if len(actual) < max(min_outcomes, validation_total + min_validation):
            meta.update({"status": "WARMUP_VALIDATION", "validation_observations": 0})
            row["optimizer"] = meta
            return
        split = max(min_validation, int(math.floor(len(actual) * (1.0 - validation_fraction))))
        if len(actual) - split < validation_total:
            split = len(actual) - validation_total
        train_actual = actual[:split]
        validation_actual = actual[split:]
        window_size = max(5, int(math.ceil(len(validation_actual) / max(1, required_windows))))
        validation_windows = [validation_actual[i:i + window_size] for i in range(0, len(validation_actual), window_size)]
        validation_windows = [window for window in validation_windows if len(window) >= 5]
        validation_dates = {str(item.get("ts", ""))[:10] for item in validation_actual if item.get("ts")}
        if len(validation_dates) < min_validation_days or len(validation_windows) < required_windows:
            meta.update({"status": "WARMUP_VALIDATION_SESSIONS", "validation_observations": len(validation_actual), "validation_sessions": len(validation_dates)})
            row["optimizer"] = meta
            return
        validation_start = str(validation_actual[0].get("ts", ""))
        train_proxy = [item for item in proxy if str(item.get("ts", "")) < validation_start]
        training = train_actual + train_proxy
        if len([item for item in training if bool(item.get("success"))]) < max(5, min_outcomes // 2):
            meta.update({"status": "WARMUP_WINNERS", "validation_observations": len(validation_actual), "validation_sessions": len(validation_dates)})
            row["optimizer"] = meta
            return
        base = self._class_floor_gate(instrument_class)
        baseline_windows = [self._evaluate_gate(base, window) for window in validation_windows]
        min_retention = min(1.0, max(0.50, _safe_float(self.learning_rules.get("minimum_retention"), 0.60)))
        min_expectancy = _safe_float(self.learning_rules.get("validation_min_expectancy_r"), 0.10)
        min_improvement = _safe_float(self.learning_rules.get("minimum_improvement_r"), 0.0)
        max_drawdown = _safe_float(self.learning_rules.get("validation_max_drawdown_r"), 10.0)
        candidate_quantiles = self.learning_rules.get("candidate_quantiles", [0.50, 0.60, 0.70, 0.75, 0.80, 0.90])
        candidates = [(None, base)]
        if isinstance(candidate_quantiles, (list, tuple)):
            for q in candidate_quantiles:
                try:
                    candidate = self._derive_candidate_gate(training, float(q))
                    if candidate:
                        candidates.append((float(q), candidate))
                except (TypeError, ValueError):
                    continue
        baseline_exp = sum(float(x["expectancy_r"]) for x in baseline_windows if x["expectancy_r"] is not None) / max(1, len(baseline_windows))
        best = None
        for quantile, candidate in candidates:
            metrics = [self._evaluate_gate(candidate, window) for window in validation_windows]
            total_passed = sum(int(m["observations"]) for m in metrics)
            candidate_retention = self._gate_retention(candidate, observations)
            if total_passed < min_validation or candidate_retention < min_retention or any(m["retention"] < min_retention or m["expectancy_r"] is None or m["expectancy_r"] < min_expectancy or (m["drawdown_r"] or 0.0) > max_drawdown for m in metrics):
                continue
            expectancy = sum(float(m["expectancy_r"]) for m in metrics) / len(metrics)
            retention = candidate_retention
            drawdown = max(float(m["drawdown_r"] or 0.0) for m in metrics)
            objective = expectancy - 0.10 * drawdown
            if expectancy < baseline_exp + min_improvement:
                continue
            record = (objective, retention, candidate, metrics, expectancy, drawdown, quantile)
            if best is None or record[0] > best[0] + 1e-9 or (abs(record[0] - best[0]) <= 1e-9 and retention > best[1]):
                best = record
        previous = dict(row.get("last_validated_gate", {}))
        if best is None:
            meta.update({"status": "INSTRUMENT_DEGRADED" if previous else "CANDIDATE_REJECTED", "validation_observations": len(validation_actual), "validation_sessions": len(validation_dates), "validation_expectancy_r": baseline_exp, "validation_windows": len(validation_windows)})
            row["optimizer"] = meta
            return
        bounded = self._bounded_gate_update(best[2], previous) if previous else dict(best[2])
        signature = hashlib.sha256(json.dumps(bounded, sort_keys=True).encode()).hexdigest()[:12]
        previous_signature = str(row.get("last_candidate_gate_signature", ""))
        stable = int(row.get("stable_validation_windows", 0))
        stable = stable + 1 if signature == previous_signature else 1
        row["last_candidate_gate_signature"] = signature
        if stable >= required_windows:
            row["last_validated_gate"] = bounded
            row["last_validated_gate_signature"] = signature
            row["last_validated_at"] = datetime.now(timezone.utc).isoformat()
        meta.update({
            "status": "INSTRUMENT_VALIDATED" if stable >= required_windows else "CANDIDATE_VALIDATION",
            "candidate_gate": bounded, "selected_quantile": best[6],
            "validation_observations": len(validation_actual), "validation_sessions": len(validation_dates),
            "validation_expectancy_r": best[4], "validation_drawdown_r": best[5],
            "validation_retention": best[1], "validation_windows": len(validation_windows),
            "stable_validation_windows": stable, "gate_signature": signature,
        })
        row["stable_validation_windows"] = stable
        row["optimizer"] = meta

    def _learned_gate(self, instrument_id: Optional[str], instrument_class: str) -> tuple[dict[str, Any], str, dict[str, Any], int, int, int, dict[str, Any]]:
        if not instrument_id or not bool(self.learning_rules.get("enabled", True)):
            return {}, "CLASS_FLOOR_WARMUP", {}, 0, 0, 0, {}
        row = self.state.get("gate_learning", {}).get(str(instrument_id), {})
        observations = list(row.get("observations", []))
        outcomes = [item for item in row.get("outcomes", []) if isinstance(item, Mapping)]
        sessions = len(set(row.get("sessions", [])))
        highest = dict(row.get("highest_observed_gate", {}))
        meta = dict(row.get("optimizer", {}))
        status = str(meta.get("status", "WARMUP_OBSERVATIONS"))
        learned = dict(row.get("last_validated_gate", {})) if row.get("last_validated_gate") and status in {"INSTRUMENT_VALIDATED", "INSTRUMENT_DEGRADED", "CANDIDATE_VALIDATION"} else {}
        learning_status = "LEARNED_IDEAL_GATE" if status == "INSTRUMENT_VALIDATED" else status
        return learned, learning_status, highest, len(observations), sessions, len(outcomes), meta

    def gates_for(self, instrument_class: str, instrument_id: Optional[str] = None) -> ClassGateSet:
        key = str(instrument_class)
        profile = self.profiles.get(key, self.profiles[InstrumentClass.NSE_INDEX.value])
        metrics = self._metrics(key)
        learned, learning_status, highest, learning_observations, learning_sessions, learning_outcomes, optimizer = self._learned_gate(instrument_id, key)
        enough = metrics["observations"] >= _safe_int(profile.get("minimum_observations"), 100)
        clean = metrics["valid_quote_rate"] >= _safe_float(profile.get("min_valid_quote_rate"), 0.95)
        fillable = metrics["paper_fill_rate"] >= _safe_float(profile.get("min_paper_fill_rate"), 0.80)
        status = CalibrationStatus.VALIDATED if enough and clean and fillable else (
            CalibrationStatus.OBSERVED if metrics["observations"] else CalibrationStatus.UNVALIDATED
        )
        # Calibration can tighten a gate from measured tails; it never loosens the
        # configured floor. This prevents early noisy observations from making the
        # strategy more permissive.
        reject_base = max(_safe_float(profile.get("atm_spread_reject_pct"), 2.0), _safe_float(learned.get("spread_pct_max"), 0.0))
        measured_reject = metrics["p90_spread_pct"] * 1.10 if metrics["p90_spread_pct"] else reject_base
        reject = max(reject_base, measured_reject)
        acceptable = max(_safe_float(profile.get("atm_spread_acceptable_pct"), 1.5), reject * 0.75)
        ideal = max(_safe_float(profile.get("atm_spread_ideal_pct"), 1.0), acceptable * 0.60)
        depth_floor = max(_safe_float(profile.get("min_5depth_lots_each_side"), 10), metrics["median_depth_lots"] * 0.50 if metrics["median_depth_lots"] else 0, _safe_float(learned.get("min_5depth_lots_each_side"), 0))
        outcome_class = CalibrationStatus.UNVALIDATED
        probability = expectancy = None
        outcome = self.state.get("outcomes", {}).get(key, {})
        if int(outcome.get("count", 0)):
            probability, expectancy, outcome_class = self.outcome_calibration(key, 80.0)
        if outcome_class == CalibrationStatus.VALIDATED:
            status = CalibrationStatus.VALIDATED if status == CalibrationStatus.VALIDATED else CalibrationStatus.OBSERVED
        return ClassGateSet(
            instrument_class=key,
            status=status,
            contract_quality_min=max(_safe_float(profile.get("contract_quality_min"), 80), _safe_float(learned.get("contract_quality_min"), 0)),
            atm_spread_ideal_pct=ideal,
            atm_spread_acceptable_pct=acceptable,
            atm_spread_reject_pct=reject,
            itm_spread_ideal_pct=_safe_float(profile.get("itm_spread_ideal_pct"), 1.2),
            itm_spread_acceptable_pct=_safe_float(profile.get("itm_spread_acceptable_pct"), 1.8),
            itm_spread_reject_pct=_safe_float(profile.get("itm_spread_reject_pct"), 2.5),
            otm_spread_ideal_pct=_safe_float(profile.get("otm_spread_ideal_pct"), 2.0),
            otm_spread_acceptable_pct=_safe_float(profile.get("otm_spread_acceptable_pct"), 3.0),
            otm_spread_reject_pct=_safe_float(profile.get("otm_spread_reject_pct"), 4.0),
            absolute_spread_cap_points=_safe_float(profile.get("absolute_spread_cap_points"), 8),
            min_top_book_lots=max(_safe_float(profile.get("min_top_book_lots"), 2), _safe_float(learned.get("min_top_book_lots"), 0)),
            min_5depth_lots_each_side=depth_floor,
            min_quote_freshness_sec=_safe_float(profile.get("min_quote_freshness_sec"), 8),
            min_valid_quote_rate=_safe_float(profile.get("min_valid_quote_rate"), 0.95),
            min_paper_fill_rate=_safe_float(profile.get("min_paper_fill_rate"), 0.80),
            excellent_score_min=max(_safe_float(profile.get("excellent_score_min"), 80), _safe_float(learned.get("excellent_score_min"), 0)),
            min_calibrated_probability=_safe_float(profile.get("min_calibrated_probability"), 0.50),
            min_net_expectancy_r=_safe_float(profile.get("min_net_expectancy_r"), 0.0),
            minimum_observations=_safe_int(profile.get("minimum_observations"), 100),
            minimum_days=_safe_int(profile.get("minimum_days"), 20),
            observations=metrics["observations"], sessions=metrics["sessions"],
            valid_quote_rate=metrics["valid_quote_rate"], paper_fill_rate=metrics["paper_fill_rate"],
            median_spread_pct=metrics["median_spread_pct"], p90_spread_pct=metrics["p90_spread_pct"],
            median_depth_lots=metrics["median_depth_lots"], calibrated_probability=probability,
            calibrated_net_expectancy_r=expectancy,
            instrument_id=str(instrument_id or ""), gate_learning_status=learning_status,
            gate_snapshot_id=hashlib.sha256(json.dumps({"class": key, "instrument": instrument_id or "", "learned": learned}, sort_keys=True).encode()).hexdigest()[:12],
            gate_learning_observations=learning_observations,
            gate_learning_sessions=learning_sessions,
            gate_learning_outcomes=learning_outcomes,
            highest_observed_gate=highest,
            high_watermark_gate=dict(self.state.get("gate_learning", {}).get(str(instrument_id), {}).get("high_watermark_gate", {})),
            direction_min=max(_safe_float(profile.get("direction_min"), 65.0), _safe_float(learned.get("direction_min"), 0)),
            premium_elasticity_min=max(_safe_float(profile.get("premium_elasticity_min"), 1.0), _safe_float(learned.get("premium_elasticity_min"), 0)),
            expected_required_ratio_min=max(_safe_float(profile.get("expected_required_ratio_min"), 1.6), _safe_float(learned.get("expected_required_ratio_min"), 0)),
            trade_quality_min=max(_safe_float(profile.get("trade_quality_min"), 70.0), _safe_float(learned.get("trade_quality_min"), 0)),
            final_confidence_min=max(_safe_float(profile.get("final_confidence_min"), 65.0), _safe_float(learned.get("final_confidence_min"), 0)),
            execution_quality_min=max(_safe_float(profile.get("execution_quality_min"), 0.0), _safe_float(learned.get("execution_quality_min"), 0)),
            regime_confidence_min=max(_safe_float(profile.get("regime_confidence_min"), 60.0), _safe_float(learned.get("regime_confidence_min"), 0)),
            market_hostility_max=min(_safe_float(profile.get("market_hostility_max"), 35.0), _safe_float(learned.get("market_hostility_max"), 100.0) or 100.0),
            iv_crush_max=min(_safe_float(profile.get("iv_crush_max"), 50.0), _safe_float(learned.get("iv_crush_max"), 100.0) or 100.0),
            spread_pct_max=min(_safe_float(profile.get("spread_pct_max"), float("inf")), _safe_float(learned.get("spread_pct_max"), float("inf"))),
            gate_resolution_path="GLOBAL_POLICY_FLOOR>CLASS_FLOOR>INSTRUMENT_LEARNED_FLOOR; LOWER=max; UPPER=min",
            gate_optimization_method=str(optimizer.get("method", "CONSTRAINED_WALK_FORWARD")),
            gate_optimization_status=str(optimizer.get("status", learning_status)),
            gate_optimization_quantile=optimizer.get("selected_quantile"),
            gate_validation_observations=_safe_int(optimizer.get("validation_observations"), 0),
            gate_validation_sessions=_safe_int(optimizer.get("validation_sessions"), 0),
            gate_validation_expectancy_r=optimizer.get("validation_expectancy_r"),
            gate_validation_drawdown_r=optimizer.get("validation_drawdown_r"),
            gate_validation_retention=_safe_float(optimizer.get("validation_retention"), 0.0),
            gate_last_validated_at=str(self.state.get("gate_learning", {}).get(str(instrument_id), {}).get("last_validated_at", "")),
        )

    def instrument_metrics(self, instrument_id: str) -> dict[str, Any]:
        row = self.state.get("instruments", {}).get(str(instrument_id), {})
        learning = self.state.get("gate_learning", {}).get(str(instrument_id), {})
        optimizer = learning.get("optimizer", {}) if isinstance(learning, Mapping) else {}
        observations = int(row.get("observations", 0))
        valid_outcomes = [
            item for item in learning.get("outcomes", [])
            if isinstance(item, Mapping) and item.get("cost_model_valid") is True
        ]
        valid_shadow = [item for item in valid_outcomes if not bool(item.get("paper"))]
        valid_paper = [item for item in valid_outcomes if bool(item.get("paper"))]
        shadow_values = [float(item.get("r_multiple", 0.0)) for item in valid_shadow]
        paper_values = [float(item.get("r_multiple", 0.0)) for item in valid_paper]
        paper_peak = 0.0
        paper_cumulative = 0.0
        paper_drawdown = 0.0
        for value in paper_values:
            paper_cumulative += value
            paper_peak = max(paper_peak, paper_cumulative)
            paper_drawdown = max(paper_drawdown, paper_peak - paper_cumulative)
        return {
            "observations": observations,
            "sessions": len(row.get("sessions", [])),
            "valid_quote_rate": float(row.get("valid_quotes", 0)) / observations if observations else 0.0,
            "paper_fill_rate": float(row.get("paper_fills", 0)) / observations if observations else 0.0,
            "shadow_outcomes": len(valid_shadow),
            "shadow_net_expectancy_r": (sum(shadow_values) / len(shadow_values)) if shadow_values else None,
            "paper_trades": len(valid_paper),
            "paper_net_expectancy_r": (sum(paper_values) / len(paper_values)) if paper_values else None,
            "max_drawdown_r": paper_drawdown,
            "cost_valid_outcomes": len(valid_outcomes),
            "cost_invalid_outcomes": max(0, len([item for item in learning.get("outcomes", []) if isinstance(item, Mapping)]) - len(valid_outcomes)),
            "gate_optimization_status": optimizer.get("status", "NOT_READY"),
            "gate_validation_observations": int(optimizer.get("validation_observations", 0) or 0),
            "gate_validation_sessions": int(optimizer.get("validation_sessions", 0) or 0),
            "gate_validation_expectancy_r": optimizer.get("validation_expectancy_r"),
            "gate_validation_drawdown_r": optimizer.get("validation_drawdown_r"),
            "gate_validation_retention": float(optimizer.get("validation_retention", 0.0) or 0.0),
            "last_validated_gate": dict(learning.get("last_validated_gate", {})) if isinstance(learning, Mapping) else {},
            "last_validated_at": learning.get("last_validated_at", "") if isinstance(learning, Mapping) else "",
        }

    def snapshot(self) -> dict[str, Any]:
        out = {key: self.gates_for(key).to_dict() for key in self.profiles}
        for instrument_id, row in self.state.get("gate_learning", {}).items():
            instrument_class = str(row.get("instrument_class", InstrumentClass.NSE_INDEX.value))
            out[f"instrument:{instrument_id}"] = self.gates_for(instrument_class, str(instrument_id)).to_dict()
        return out


@dataclass(frozen=True)
class PromotionMetrics:
    observations: int
    sessions: int
    valid_quote_rate: float
    paper_fill_rate: float
    shadow_outcomes: int = 0
    shadow_net_expectancy_r: Optional[float] = None
    paper_trades: int = 0
    paper_net_expectancy_r: Optional[float] = None
    max_drawdown_r: float = 0.0


@dataclass(frozen=True)
class PromotionDecision:
    current_state: InstrumentLifecycle
    recommended_state: InstrumentLifecycle
    allowed: bool
    trade_review_ready: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class OverlapDecision:
    allowed: bool
    reason: str
    exposure_group: str


class PortfolioOverlapGuard:
    """Conservative factor-overlap filter for future multi-position operation."""

    def __init__(self, enabled: bool = True, block_same_group: bool = True,
                 block_same_underlying: bool = True):
        self.enabled = enabled
        self.block_same_group = block_same_group
        self.block_same_underlying = block_same_underlying

    def assess(self, underlying: str, group: str, active_underlyings: set[str] | frozenset[str] = frozenset(),
               active_groups: set[str] | frozenset[str] = frozenset()) -> OverlapDecision:
        if not self.enabled:
            return OverlapDecision(True, "overlap guard disabled", group)
        if self.block_same_underlying and underlying in active_underlyings:
            return OverlapDecision(False, "same underlying exposure already active", group)
        if self.block_same_group and group in active_groups:
            return OverlapDecision(False, "same exposure group already active", group)
        return OverlapDecision(True, "no active overlap detected", group)


class PromotionEngine:
    """Recommend lifecycle movement; it never edits the trade universe."""

    def __init__(self, calibration: InstrumentCalibrationStore):
        self.calibration = calibration

    def evaluate(self, instrument_class: str, current_state: InstrumentLifecycle,
                 metrics: PromotionMetrics, monitor_only: bool = True) -> PromotionDecision:
        gate = self.calibration.gates_for(instrument_class)
        reasons: list[str] = []
        if current_state == InstrumentLifecycle.RETIRED:
            return PromotionDecision(current_state, current_state, False, False, ("Instrument is retired",))
        rules = self.calibration.retirement_rules
        data_quality_factor = _safe_float(rules.get("data_quality_degradation_factor"), 0.80)
        negative_expectancy = _safe_float(rules.get("negative_expectancy_retire_threshold_r"), -0.25)
        min_shadow_outcomes = _safe_int(rules.get("minimum_shadow_outcomes"), 20)
        min_paper_trades = _safe_int(rules.get("minimum_paper_trades"), 50)
        if metrics.observations >= gate.minimum_observations and metrics.valid_quote_rate < gate.min_valid_quote_rate * data_quality_factor:
            return PromotionDecision(current_state, InstrumentLifecycle.RETIRED, True, False, ("Persistent data-quality degradation",))
        if metrics.shadow_outcomes >= min_shadow_outcomes and metrics.shadow_net_expectancy_r is not None and metrics.shadow_net_expectancy_r < negative_expectancy:
            return PromotionDecision(current_state, InstrumentLifecycle.RETIRED, True, False, ("Shadow post-cost expectancy materially negative",))
        if metrics.paper_trades >= min_paper_trades and metrics.paper_net_expectancy_r is not None and metrics.paper_net_expectancy_r < negative_expectancy:
            return PromotionDecision(current_state, InstrumentLifecycle.RETIRED, True, False, ("Paper post-cost expectancy materially negative",))
        if metrics.valid_quote_rate < gate.min_valid_quote_rate:
            reasons.append("valid quote rate below class gate")
        if metrics.paper_fill_rate < gate.min_paper_fill_rate:
            reasons.append("paper-fill rate below class gate")
        if metrics.observations < gate.minimum_observations or metrics.sessions < gate.minimum_days:
            reasons.append("minimum class observations or sessions not reached")
        if reasons:
            next_state = InstrumentLifecycle.MONITOR if current_state == InstrumentLifecycle.MONITOR else current_state
            return PromotionDecision(current_state, next_state, False, False, tuple(reasons))
        if current_state == InstrumentLifecycle.MONITOR:
            return PromotionDecision(current_state, InstrumentLifecycle.SHADOW, True, False, ("Liquidity observation gate passed",))
        if current_state == InstrumentLifecycle.SHADOW:
            if metrics.shadow_outcomes < min_shadow_outcomes or metrics.shadow_net_expectancy_r is None or metrics.shadow_net_expectancy_r <= 0:
                return PromotionDecision(current_state, current_state, False, False, ("Shadow post-cost expectancy gate not passed",))
            return PromotionDecision(current_state, InstrumentLifecycle.PAPER_ELIGIBLE, True, False, ("Shadow expectancy gate passed",))
        if current_state == InstrumentLifecycle.PAPER_ELIGIBLE:
            if metrics.paper_trades < min_paper_trades or metrics.paper_net_expectancy_r is None or metrics.paper_net_expectancy_r <= 0:
                return PromotionDecision(current_state, current_state, False, False, ("Paper validation expectancy gate not passed",))
            if metrics.max_drawdown_r > 10:
                return PromotionDecision(current_state, current_state, False, False, ("Paper drawdown gate not passed",))
            # Monitor-only instruments stop at review-ready. A committee or a
            # separately approved config change is required before trade eligibility.
            return PromotionDecision(current_state, InstrumentLifecycle.PAPER_ELIGIBLE, True, True,
                                     ("Paper validation complete; trade review required",))
        if current_state == InstrumentLifecycle.TRADE_ELIGIBLE and monitor_only:
            return PromotionDecision(current_state, InstrumentLifecycle.TRADE_ELIGIBLE, False, False,
                                     ("Monitor-only flag conflicts with trade eligibility",))
        return PromotionDecision(current_state, current_state, False, False, ("No lifecycle transition required",))


def class_for_metadata(exchange: str, instrument_kind: str) -> str:
    return InstrumentClass.from_metadata(exchange, instrument_kind).value


__all__ = [
    "ClassGateSet", "InstrumentCalibrationStore", "InstrumentClass",
    "InstrumentLifecycle",     "OverlapDecision", "PortfolioOverlapGuard", "PromotionDecision", "PromotionEngine",
    "PromotionMetrics", "StrategyVersions", "class_for_metadata",
    "exposure_group", "gate_feature_snapshot", "version_fingerprint",
]
