from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class SystemConfig:
    raw: Mapping[str, Any]

    @classmethod
    def from_file(cls, path: str | Path) -> "SystemConfig":
        p = Path(path)
        with p.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        cfg = cls(raw=raw)
        cfg.validate()
        return cfg

    def section(self, name: str) -> Mapping[str, Any]:
        value = self.raw.get(name)
        if not isinstance(value, Mapping):
            raise ConfigError(f"Missing or invalid config section: {name}")
        return value

    def validate(self) -> None:
        required = [
            "capital",
            "risk",
            "execution",
            "data_health",
            "liquidity",
            "premium_elasticity",
            "expected_move",
            "iv_crush",
            "hard_stop",
            "instrument_universe",
            "opportunity_selection",
            "paper_fill_simulator",
            "portfolio_no_trade_engine",
            "excellence_framework",
        ]
        for name in required:
            if name not in self.raw:
                raise ConfigError(f"Required config section missing: {name}")
        capital = self.section("capital")
        if capital.get("pledge_or_leverage_allowed") is not False:
            raise ConfigError("Pledge/leverage must be disabled for MVP.")
        if capital.get("overnight_holding_allowed") is not False:
            raise ConfigError("Overnight holding must be disabled for MVP.")
        if capital.get("auto_execution_mvp") is not False:
            raise ConfigError("Auto execution must be disabled for MVP.")
        data_health = self.section("data_health")
        stale_alert_cycles = data_health.get("stale_alert_consecutive_cycles", 2)
        if isinstance(stale_alert_cycles, bool) or not isinstance(stale_alert_cycles, int) or stale_alert_cycles <= 0:
            raise ConfigError("data_health.stale_alert_consecutive_cycles must be a positive integer.")
        execution = self.section("execution")
        if execution.get("live_trading_enabled") is not False:
            raise ConfigError("live_trading_enabled must be false for current MVP/Phase 1-3 implementation.")
        universe = self.section("instrument_universe")
        eligible = [str(name).upper() for name in universe.get("eligible_underlyings", [])]
        core = {"BANKNIFTY", "NIFTY", "FINNIFTY", "MIDCPNIFTY"}
        if not eligible or len(eligible) != len(set(eligible)) or not core.issubset(set(eligible)):
            raise ConfigError("Instrument universe must be non-empty, duplicate-free, and contain all four core indices.")
        learning = self.raw.get("instrument_gate_learning", {})
        if learning and not isinstance(learning, Mapping):
            raise ConfigError("instrument_gate_learning must be an object when provided.")
        if isinstance(learning, Mapping):
            if learning.get("do_not_loosen") is not True:
                raise ConfigError("Per-instrument gate learning must not loosen class floors.")
            if "enabled" in learning and not isinstance(learning.get("enabled"), bool):
                raise ConfigError("instrument_gate_learning.enabled must be boolean.")
            warmup_days = learning.get("warmup_days", 5)
            minimum_days = learning.get("minimum_learning_days", 20)
            minimum_observations = learning.get("minimum_learning_observations", 100)
            minimum_outcomes = learning.get("minimum_learning_outcomes", 20)
            winning_quantile = learning.get("winning_quantile", 0.25)
            high_watermark_quantile = learning.get("high_watermark_quantile", 0.90)
            numeric_ints = (("warmup_days", warmup_days), ("minimum_learning_days", minimum_days),
                            ("minimum_learning_observations", minimum_observations),
                            ("minimum_learning_outcomes", minimum_outcomes))
            if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for _, v in numeric_ints):
                raise ConfigError("Gate-learning day, observation, and outcome thresholds must be positive integers.")
            if minimum_days < warmup_days:
                raise ConfigError("minimum_learning_days cannot be below warmup_days.")
            if not isinstance(winning_quantile, (int, float)) or not 0 < float(winning_quantile) <= 0.5:
                raise ConfigError("winning_quantile must be greater than 0 and no greater than 0.5.")
            if not isinstance(high_watermark_quantile, (int, float)) or not 0.5 <= float(high_watermark_quantile) <= 1.0:
                raise ConfigError("high_watermark_quantile must be between 0.5 and 1.0.")
            candidate_quantiles = learning.get("candidate_quantiles", [0.50, 0.60, 0.70, 0.75, 0.80, 0.90])
            if not isinstance(candidate_quantiles, (list, tuple)) or not candidate_quantiles:
                raise ConfigError("candidate_quantiles must be a non-empty list.")
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not 0.5 <= float(v) <= 0.95 for v in candidate_quantiles):
                raise ConfigError("candidate_quantiles must contain values between 0.5 and 0.95.")
            validation_fraction = learning.get("validation_fraction", 0.30)
            if not isinstance(validation_fraction, (int, float)) or not 0.10 <= float(validation_fraction) <= 0.50:
                raise ConfigError("validation_fraction must be between 0.10 and 0.50.")
            validation_ints = (("minimum_validation_outcomes", learning.get("minimum_validation_outcomes", 10)),
                               ("minimum_validation_days", learning.get("minimum_validation_days", 5)),
                               ("required_stable_validation_windows", learning.get("required_stable_validation_windows", 2)))
            if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for _, v in validation_ints):
                raise ConfigError("Validation outcome, day, and stability thresholds must be positive integers.")
            for key, minimum in (("validation_min_expectancy_r", 0.0), ("validation_max_drawdown_r", 0.0), ("minimum_retention", 0.5), ("maximum_gate_update_step_fraction", 0.01)):
                value = learning.get(key, minimum)
                if not isinstance(value, (int, float)) or float(value) < minimum:
                    raise ConfigError(f"{key} must be numeric and at least {minimum}.")
            if float(learning.get("minimum_retention", 0.60)) > 1.0:
                raise ConfigError("minimum_retention cannot exceed 1.0.")
            if float(learning.get("maximum_gate_update_step_fraction", 0.10)) > 0.50:
                raise ConfigError("maximum_gate_update_step_fraction cannot exceed 0.50.")
        evidence_profiles = self.raw.get("evidence_profiles", {})
        runtime_risk = self.raw.get("runtime_risk_controls", {})
        if isinstance(evidence_profiles, Mapping) and str(evidence_profiles.get("active_profile", "")).upper().startswith("STRICT"):
            if not isinstance(runtime_risk, Mapping) or runtime_risk.get("enforce_on_paper") is not True:
                raise ConfigError("Strict evidence profiles require runtime risk/news enforcement.")
            if evidence_profiles.get("exclude_from_canonical_validation") is not False:
                raise ConfigError("Strict evidence profiles cannot be excluded from canonical validation.")
        excellent = self.section("opportunity_selection").get("excellent_gate_requirements", {})
        if isinstance(excellent, Mapping) and excellent.get("required_stop_must_be_configured", True):
            stop_model = self.raw.get("required_stop_model")
            if not isinstance(stop_model, Mapping) or stop_model.get("enabled") is not True:
                raise ConfigError("Required-stop model must be configured and enabled for excellent-candidate selection.")
            try:
                if float(stop_model.get("premium_stop_pct", 0.0)) <= 0:
                    raise ConfigError("Required-stop premium_stop_pct must be positive.")
            except (TypeError, ValueError):
                raise ConfigError("Required-stop premium_stop_pct must be numeric.")
        operator_controls = self.raw.get("operator_controls", {})
        if operator_controls and not isinstance(operator_controls, Mapping):
            raise ConfigError("operator_controls must be an object when provided.")
        if isinstance(operator_controls, Mapping):
            for key in ("daily_mode_path", "market_context_path"):
                if key in operator_controls and not str(operator_controls.get(key, "")).strip():
                    raise ConfigError(f"operator_controls.{key} must be a non-empty path.")
            if "manual_mode_can_loosen" in operator_controls and operator_controls.get("manual_mode_can_loosen") is not False:
                raise ConfigError("operator_controls.manual_mode_can_loosen must remain false.")
        if universe.get("max_open_positions") != 1 or universe.get("max_pending_orders") != 1:
            raise ConfigError("Global position and pending order limits must be 1.")
        if universe.get("trade_only_best_ranked_candidate") is not True:
            raise ConfigError("MVP must trade only the best ranked candidate in paper mode.")

    def get_float(self, section: str, key: str) -> float:
        value = self.section(section).get(key)
        if not isinstance(value, (int, float)):
            raise ConfigError(f"Expected numeric config {section}.{key}")
        return float(value)

    def get_int(self, section: str, key: str) -> int:
        value = self.section(section).get(key)
        if not isinstance(value, int):
            raise ConfigError(f"Expected integer config {section}.{key}")
        return value
