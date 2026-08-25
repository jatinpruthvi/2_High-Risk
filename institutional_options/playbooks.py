from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional


class RegimeLabel(str, Enum):
    TREND_EXPANSION = "TREND_EXPANSION"
    TREND_PULLBACK = "TREND_PULLBACK"
    RANGE_BALANCE = "RANGE_BALANCE"
    COMPRESSION = "COMPRESSION"
    COMPRESSION_TO_EXPANSION = "COMPRESSION_TO_EXPANSION"
    GAP_ACCEPTANCE = "GAP_ACCEPTANCE"
    GAP_REJECTION = "GAP_REJECTION"
    EXPIRY_PIN = "EXPIRY_PIN"
    GAMMA_PIN_FAILURE = "GAMMA_PIN_FAILURE"
    OI_WALL_BREAK = "OI_WALL_BREAK"
    LIQUIDITY_SWEEP_REVERSAL = "LIQUIDITY_SWEEP_REVERSAL"
    VOL_EXPANSION = "VOL_EXPANSION"
    POST_EVENT_STABILIZATION = "POST_EVENT_STABILIZATION"
    POST_EVENT_IV_CRUSH = "POST_EVENT_IV_CRUSH"
    RISK_OFF = "RISK_OFF"
    RISK_ON = "RISK_ON"
    PANIC = "PANIC"
    PANIC_STABILIZATION = "PANIC_STABILIZATION"
    POWER_HOUR = "POWER_HOUR"
    NEWS_CHAOS = "NEWS_CHAOS"
    UNKNOWN = "UNKNOWN"


class PlaybookGrade(str, Enum):
    A_PLUS = "A+"
    A = "A"
    B = "B"
    C = "C"
    REJECT = "Reject"


@dataclass(frozen=True)
class RegimeContext:
    primary: RegimeLabel
    confidence: float
    secondary: tuple[RegimeLabel, ...] = ()
    market_hostility_score: float = 0.0
    iv_crush_risk_score: float = 0.0
    liquidity_stable: bool = True
    event_resolved: bool = True
    gap_wait_completed: bool = True
    trend_strength_score: float = 0.0
    range_expansion_quality: float = 0.0
    compression_expansion_score: float = 0.0
    forced_flow_score: float = 0.0
    liquidity_vacuum_score: float = 0.0
    gamma_pin_failure_score: float = 0.0
    global_risk_shock: bool = False
    time_bucket: str = "UNKNOWN"

    def regimes(self) -> set[RegimeLabel]:
        return {self.primary, *self.secondary}


@dataclass(frozen=True)
class PlaybookDefinition:
    code: str
    name: str
    allowed_regimes: tuple[RegimeLabel, ...]
    blocked_regimes: tuple[RegimeLabel, ...]
    min_regime_confidence: float = 70.0
    max_market_hostility: float = 35.0
    max_iv_crush_risk: float = 70.0
    requires_liquidity_stable: bool = True
    requires_event_resolved: bool = True
    requires_gap_wait_completed: bool = False
    min_trend_strength: float = 0.0
    min_range_expansion_quality: float = 0.0
    min_forced_flow_score: float = 0.0
    min_liquidity_vacuum_score: float = 0.0
    min_gamma_pin_failure_score: float = 0.0
    min_compression_expansion_score: float = 0.0


@dataclass(frozen=True)
class PlaybookEvaluation:
    playbook: PlaybookDefinition
    score: float
    grade: PlaybookGrade
    allowed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PlaybookSelectionResult:
    selected: Optional[PlaybookEvaluation]
    evaluations: tuple[PlaybookEvaluation, ...]
    allowed_codes: frozenset[str]
    no_trade: bool
    reasons: tuple[str, ...]


class RegimePlaybookSelectionEngine:
    """Selects the best playbook for the current regime.

    This is a filter/selector, not a trade trigger. It prevents using the wrong
    archetype for the day and blocks best-of-weak playbook selection.
    """

    def __init__(self, playbooks: Optional[Iterable[PlaybookDefinition]] = None, excellent_threshold: float = 80.0):
        self.playbooks = tuple(playbooks) if playbooks is not None else self.default_playbooks()
        self.excellent_threshold = excellent_threshold

    @staticmethod
    def default_playbooks() -> tuple[PlaybookDefinition, ...]:
        return (
            PlaybookDefinition("A01", "Trend Day Breakout", (RegimeLabel.TREND_EXPANSION,), (RegimeLabel.RANGE_BALANCE, RegimeLabel.EXPIRY_PIN, RegimeLabel.NEWS_CHAOS), 75, 35, 60, min_trend_strength=70, min_range_expansion_quality=75),
            PlaybookDefinition("A02", "Gap Continuation", (RegimeLabel.GAP_ACCEPTANCE,), (RegimeLabel.NEWS_CHAOS,), 75, 35, 60, requires_gap_wait_completed=True, min_range_expansion_quality=75),
            PlaybookDefinition("A03", "Gap Fill Reversal", (RegimeLabel.GAP_REJECTION,), (RegimeLabel.NEWS_CHAOS,), 75, 35, 60, requires_gap_wait_completed=True, min_forced_flow_score=60),
            PlaybookDefinition("A04", "Short Covering Rally", (RegimeLabel.RISK_ON, RegimeLabel.TREND_EXPANSION), (RegimeLabel.RANGE_BALANCE, RegimeLabel.EXPIRY_PIN), 70, 35, 60, min_forced_flow_score=60),
            PlaybookDefinition("A05", "Long Build Up Expansion", (RegimeLabel.TREND_EXPANSION,), (RegimeLabel.RANGE_BALANCE, RegimeLabel.NEWS_CHAOS), 70, 35, 60, min_trend_strength=65),
            PlaybookDefinition("A06", "IV Expansion Momentum", (RegimeLabel.VOL_EXPANSION,), (RegimeLabel.POST_EVENT_IV_CRUSH,), 70, 35, 70, min_forced_flow_score=60),
            PlaybookDefinition("A07", "OI Wall Breakout", (RegimeLabel.OI_WALL_BREAK,), (RegimeLabel.EXPIRY_PIN,), 75, 35, 60, min_forced_flow_score=70, min_liquidity_vacuum_score=70),
            PlaybookDefinition("A08", "Power Hour Momentum", (RegimeLabel.POWER_HOUR, RegimeLabel.TREND_EXPANSION), (RegimeLabel.NEWS_CHAOS,), 75, 30, 60, min_trend_strength=75),
            PlaybookDefinition("A09", "Compression Breakout", (RegimeLabel.COMPRESSION_TO_EXPANSION,), (RegimeLabel.RANGE_BALANCE,), 75, 35, 60, min_compression_expansion_score=75, min_range_expansion_quality=75),
            PlaybookDefinition("A10", "Gamma Pin Failure", (RegimeLabel.GAMMA_PIN_FAILURE,), (RegimeLabel.NEWS_CHAOS,), 75, 35, 70, min_gamma_pin_failure_score=75),
            PlaybookDefinition("A11", "Liquidity Sweep Reversal", (RegimeLabel.LIQUIDITY_SWEEP_REVERSAL,), (RegimeLabel.NEWS_CHAOS,), 75, 35, 60, min_forced_flow_score=60),
            PlaybookDefinition("A14", "Pullback Continuation", (RegimeLabel.TREND_PULLBACK, RegimeLabel.TREND_EXPANSION), (RegimeLabel.RANGE_BALANCE,), 70, 35, 60, min_trend_strength=65),
            PlaybookDefinition("A15", "Post-Event Continuation", (RegimeLabel.POST_EVENT_STABILIZATION,), (RegimeLabel.POST_EVENT_IV_CRUSH, RegimeLabel.NEWS_CHAOS), 75, 30, 50, requires_event_resolved=True),
            PlaybookDefinition("A16", "Risk-Off Put Acceleration", (RegimeLabel.RISK_OFF,), (RegimeLabel.RANGE_BALANCE,), 75, 40, 70, min_forced_flow_score=70),
            PlaybookDefinition("A17", "Capitulation Reversal", (RegimeLabel.PANIC_STABILIZATION,), (RegimeLabel.PANIC, RegimeLabel.NEWS_CHAOS), 80, 35, 60, min_forced_flow_score=70),
            PlaybookDefinition("A18", "Range Failure Continuation", (RegimeLabel.TREND_EXPANSION, RegimeLabel.OI_WALL_BREAK), (RegimeLabel.RANGE_BALANCE,), 75, 35, 60, min_range_expansion_quality=75),
            PlaybookDefinition("A19", "Midcap Risk-On Thrust", (RegimeLabel.RISK_ON,), (RegimeLabel.RISK_OFF, RegimeLabel.NEWS_CHAOS), 85, 30, 50, min_trend_strength=80, min_liquidity_vacuum_score=75),
        )

    def evaluate(self, context: RegimeContext) -> PlaybookSelectionResult:
        evaluations = tuple(self._evaluate_one(p, context) for p in self.playbooks)
        allowed = [e for e in evaluations if e.allowed and e.score >= self.excellent_threshold]
        if not allowed:
            return PlaybookSelectionResult(None, evaluations, frozenset(), True, ("No excellent playbook for current regime",))
        ranked = sorted(allowed, key=lambda e: e.score, reverse=True)
        top = ranked[0]
        return PlaybookSelectionResult(top, evaluations, frozenset(e.playbook.code for e in allowed), False, ("Selected best regime-compatible playbook",))

    def _evaluate_one(self, p: PlaybookDefinition, c: RegimeContext) -> PlaybookEvaluation:
        reasons: list[str] = []
        regimes = c.regimes()
        if not regimes.intersection(p.allowed_regimes):
            reasons.append("Regime not allowed for playbook")
        if regimes.intersection(p.blocked_regimes):
            reasons.append("Blocked regime active for playbook")
        if c.confidence < p.min_regime_confidence:
            reasons.append("Regime confidence below playbook requirement")
        if c.market_hostility_score > p.max_market_hostility:
            reasons.append("Market hostility too high for playbook")
        if c.iv_crush_risk_score > p.max_iv_crush_risk:
            reasons.append("IV crush risk too high for playbook")
        if p.requires_liquidity_stable and not c.liquidity_stable:
            reasons.append("Liquidity not stable")
        if p.requires_event_resolved and not c.event_resolved:
            reasons.append("Event risk not resolved")
        if p.requires_gap_wait_completed and not c.gap_wait_completed:
            reasons.append("Gap wait not completed")
        if c.global_risk_shock:
            reasons.append("Global shock active")
        checks = [
            (c.trend_strength_score, p.min_trend_strength, "Trend strength"),
            (c.range_expansion_quality, p.min_range_expansion_quality, "Range expansion quality"),
            (c.forced_flow_score, p.min_forced_flow_score, "Forced flow"),
            (c.liquidity_vacuum_score, p.min_liquidity_vacuum_score, "Liquidity vacuum"),
            (c.gamma_pin_failure_score, p.min_gamma_pin_failure_score, "Gamma pin failure"),
            (c.compression_expansion_score, p.min_compression_expansion_score, "Compression expansion"),
        ]
        for observed, required, label in checks:
            if required and observed < required:
                reasons.append(f"{label} below requirement")
        base = 100.0
        base -= max(0.0, p.min_regime_confidence - c.confidence)
        base -= max(0.0, c.market_hostility_score - 20.0) * 0.5
        base -= max(0.0, c.iv_crush_risk_score - 30.0) * 0.25
        for observed, required, _label in checks:
            if required:
                base -= max(0.0, required - observed) * 0.5
        if reasons:
            base = min(base, 69.0)
        score = max(0.0, min(100.0, base))
        grade = self._grade(score, reasons)
        return PlaybookEvaluation(p, score, grade, not reasons and grade in {PlaybookGrade.A, PlaybookGrade.A_PLUS}, tuple(reasons))

    @staticmethod
    def _grade(score: float, reasons: list[str]) -> PlaybookGrade:
        if reasons:
            return PlaybookGrade.REJECT if score < 60 else PlaybookGrade.C
        if score >= 90:
            return PlaybookGrade.A_PLUS
        if score >= 80:
            return PlaybookGrade.A
        if score >= 70:
            return PlaybookGrade.B
        if score >= 60:
            return PlaybookGrade.C
        return PlaybookGrade.REJECT
