from pathlib import Path
import json

root = Path(r"E:\Jatin-Project\DHAN\2_High-Risk")
runner = root / "institutional_options" / "paper_runner.py"
text = runner.read_text(encoding="utf-8")

def replace_once(old: str, new: str, label: str) -> None:
    global text
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"missing marker: {label}")
    text = text.replace(old, new, 1)

replace_once(
'''        self.data_health = DataHealthOrchestrator(self.config)
        self.portfolio_no_trade = PortfolioNoTradeCalculator()''',
'''        self.data_health = DataHealthOrchestrator(self.config)
        self.paper_calibration_data_health = (
            DataHealthOrchestrator(self.paper_calibration_engine.config)
            if self.paper_calibration_engine is not None else None
        )
        self.paper_calibration_revalidator = (
            CandidateRevalidator(self.paper_calibration_engine.config)
            if self.paper_calibration_engine is not None else None
        )
        self.portfolio_no_trade = PortfolioNoTradeCalculator()''',
"health initializer",
)
replace_once(
'''            chain_health = self.data_health.evaluate_option_chain(chain, now_ist())''',
'''            health_orchestrator = self.paper_calibration_data_health if calibration_scope and self.paper_calibration_data_health is not None else self.data_health
            chain_health = health_orchestrator.evaluate_option_chain(chain, now_ist())''',
"chain health",
)
replace_once(
'''                candidate_health = self.data_health.evaluate_candidate(c, now_ist())''',
'''                candidate_health = health_orchestrator.evaluate_candidate(c, now_ist())''',
"candidate health",
)
replace_once(
'''        revalidated, revalidation_reasons = self.revalidator.revalidate(
''',
'''        revalidator = self.paper_calibration_revalidator if entry_mode == "PAPER_CALIBRATION" and self.paper_calibration_revalidator is not None else self.revalidator
        revalidated, revalidation_reasons = revalidator.revalidate(
''',
"entry revalidator",
)
replace_once(
'''        refreshed_health = self.data_health.evaluate_candidate(refreshed_candidate, now_ist())''',
'''        health_orchestrator = self.paper_calibration_data_health if entry_mode == "PAPER_CALIBRATION" and self.paper_calibration_data_health is not None else self.data_health
        refreshed_health = health_orchestrator.evaluate_candidate(refreshed_candidate, now_ist())''',
"fresh health",
)
old = '''        expected = dict(raw.get("expected_move", {}))
        expected["hard_reject_ratio"] = float(cfg.get("expected_required_ratio_min", 1.10))
        raw["expected_move"] = expected'''
new = '''        expected = dict(raw.get("expected_move", {}))
        expected["hard_reject_ratio"] = float(cfg.get("expected_required_ratio_min", 1.10))
        raw["expected_move"] = expected
        data_health = dict(raw.get("data_health", {}))
        max_quote_age = float(cfg.get("max_quote_age_seconds", 45.0))
        max_chain_age = float(cfg.get("max_chain_age_seconds", 45.0))
        data_health["option_quote_stale_invalid_sec"] = max(float(data_health.get("option_quote_stale_invalid_sec", 8.0)), max_quote_age)
        data_health["option_quote_stale_warning_sec"] = min(float(data_health.get("option_quote_stale_warning_sec", 5.0)), max_quote_age * 0.5)
        data_health["option_chain_invalid_sec"] = max(float(data_health.get("option_chain_invalid_sec", 30.0)), max_chain_age)
        data_health["option_chain_stale_entry_sec"] = max(float(data_health.get("option_chain_stale_entry_sec", 15.0)), max_chain_age * 0.5)
        raw["data_health"] = data_health
        revalidation = dict(raw.get("candidate_revalidation", {}))
        max_candidate_age = float(cfg.get("max_candidate_age_seconds", max_quote_age))
        revalidation["normal_market_max_candidate_age_sec"] = max(float(revalidation.get("normal_market_max_candidate_age_sec", 15.0)), max_candidate_age)
        revalidation["fast_market_max_candidate_age_sec"] = max(float(revalidation.get("fast_market_max_candidate_age_sec", 5.0)), max_candidate_age)
        raw["candidate_revalidation"] = revalidation'''
replace_once(old, new, "calibration config freshness")
runner.write_text(text, encoding="utf-8", newline="")

config_path = root / "uploads" / "PAPER_RUNNER.json"
cfg = json.loads(config_path.read_text(encoding="utf-8"))
cal = dict(cfg.get("paper_calibration", {}))
cal.update({
    "max_quote_age_seconds": 45.0,
    "max_chain_age_seconds": 45.0,
    "max_candidate_age_seconds": 45.0,
})
cfg["paper_calibration"] = cal
config_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
print("direct_calibration_freshness=applied")
