"""ROI vs drawdown lab for exit-management research.

Runs a deterministic Monte Carlo of long-option premium paths through the real
`SimulatedTradeLifecycle` and compares two exit regimes:

* legacy  — fixed target / fixed stop / time stop (no active management)
* managed — fixed stop plus breakeven lock-in and a trailing stop ratchet
            (`ExitPolicy` from the `exit_management` config section)

Metrics are expressed in R (1R = initial stop distance). ROI is net R per 100
units of risk capital; drawdown is the peak-to-trough of the cumulative R
equity curve. Because the managed ratchet never loosens the initial stop, the
worst-case loss per trade is identical; the lab verifies ROI improves and max
drawdown does not worsen.

Run directly:  python -m institutional_options.roi_lab
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Optional

from .config import SystemConfig
from .lifecycle import ExitPolicy, MarketBar, SimulatedTradeLifecycle
from .models import (
    CalibrationStatus,
    CandidateInputs,
    DataHealth,
    Greeks,
    InstrumentSpec,
    Moneyness,
    OptionType,
    PaperFill,
    PaperTrade,
    Quote,
)
from .scoring import OpportunityScorer, PaperFillSimulator


@dataclass(frozen=True)
class LabScenario:
    n_paths: int = 2000
    bars: int = 60
    drift: float = 0.004          # per-bar log drift for good trades
    vol: float = 0.045            # per-bar log volatility
    good_fraction: float = 0.55   # share of paths with positive drift
    reversal_fraction: float = 0.45  # share of good paths that rise then reverse
    reversal_strength: float = 1.8   # drift multiplier after reversal
    theta_per_bar: float = 0.0    # per-bar theta decay of option premium (e.g. 0.002 ~ 11% over 60 bars)
    seed: int = 42
    entry_premium: float = 100.0
    spread_frac: float = 0.005
    stop_points: float = 20.0     # 1R
    target_points: float = 40.0   # 2R
    # Per-bar expected move (premium points) supplied on bars so the
    # volatility-aware time stop (ExitPolicy.vol_time_stop_fraction) can fire.
    # 0.0 disables (bars carry no expected move).
    expected_move_per_bar: float = 0.0


@dataclass(frozen=True)
class LabMetrics:
    label: str
    trades: int
    roi_pct: float
    max_drawdown_r: float
    win_rate: float
    profit_factor: float
    avg_win_r: float
    avg_loss_r: float
    exits: dict[str, int]
    unfilled: int = 0

    @property
    def fill_rate(self) -> float:
        total = self.trades + self.unfilled
        return self.trades / total if total else 0.0

    def table_row(self) -> str:
        return (
            f"{self.label:8s} trades={self.trades:5d} fill={self.fill_rate*100:5.1f}% roi={self.roi_pct:7.2f}%  "
            f"maxDD={self.max_drawdown_r:6.2f}R  win={self.win_rate*100:5.1f}%  "
            f"PF={self.profit_factor:5.2f}  avgWin={self.avg_win_r:5.2f}R  avgLoss={self.avg_loss_r:5.2f}R  "
            f"exits={dict(sorted(self.exits.items()))}"
        )


def make_lab_trade(entry_quote: Quote, cfg: SystemConfig) -> PaperTrade:
    """Build a realistic paper trade at the entry quote (reused across paths)."""
    now = datetime(2026, 6, 1, 10, 0, 0)
    candidate = CandidateInputs(
        instrument=InstrumentSpec("BANKNIFTY", "1", "OPTIDX", date(2026, 6, 30), 30, 0.05, 25000, OptionType.CE),
        quote=entry_quote,
        moneyness=Moneyness.ATM,
        greeks=Greeks(delta=0.5, gamma=0.01, theta=-5, vega=2, iv=15),
        data_health=DataHealth(True),
        futures_price=25000,
        underlying_price=25000,
        instrument_direction_score=80,
        trade_quality_score=80,
        regime_confidence=80,
        market_hostility_score=10,
        iv_crush_risk_score=20,
        premium_elasticity=1.2,
        expected_move=200,
        required_move=100,
        candidate_created_at=now,
        calibration_status_direction=CalibrationStatus.VALIDATED,
        calibration_status_liquidity=CalibrationStatus.VALIDATED,
    )
    evaluation = OpportunityScorer(cfg).evaluate(candidate)
    fill = PaperFillSimulator(cfg).entry_buy(candidate.quote, candidate.instrument.tick_size)
    if not fill.filled or fill.fill_price is None:
        # Template trade only; simulate_trades builds real per-path fills and
        # counts unfilled entries as fill-probability cost.
        fill = PaperFill(False, None, None, 0.0, fill.reason)
    return PaperTrade("LAB", evaluation, fill, now)


def _quote_at(premium: float, spread: float, ts: datetime) -> Quote:
    half = spread / 2.0
    bid = max(0.05, premium - half)
    ask = bid + spread
    return Quote(bid, ask, 5000, 5000, (bid + ask) / 2.0, ts, 25000, 25000)


def generate_paths(scenario: LabScenario) -> list[list[float]]:
    rng = random.Random(scenario.seed)
    n_good = int(scenario.n_paths * scenario.good_fraction)
    paths: list[list[float]] = []
    for i in range(scenario.n_paths):
        good = i < n_good
        reversal = good and rng.random() < scenario.reversal_fraction
        flip_at = rng.randint(int(scenario.bars * 0.30), int(scenario.bars * 0.70)) if reversal else None
        path = [scenario.entry_premium]
        price = scenario.entry_premium
        for t in range(1, scenario.bars + 1):
            drift_here = scenario.drift if good else -scenario.drift
            if flip_at is not None and t > flip_at:
                drift_here = -drift_here * scenario.reversal_strength
            theta = scenario.theta_per_bar if scenario.theta_per_bar > 0 else 0.0
            price = max(0.5, price * math.exp(rng.gauss(drift_here, scenario.vol) - theta))
            path.append(price)
        paths.append(path)
    return paths


def simulate_trades(paths: list[list[float]], cfg: SystemConfig, policy: Optional[ExitPolicy], scenario: LabScenario) -> LabMetrics:
    """Simulate the lifecycle for every path; entries the conservative paper
    fill model refuses (wide spreads) are counted as unfilled, matching the
    real fill-probability cost of spread friction."""

    lifecycle = SimulatedTradeLifecycle(PaperFillSimulator(cfg))
    spread = scenario.entry_premium * scenario.spread_frac
    entry_quote = _quote_at(scenario.entry_premium, spread, datetime(2026, 6, 1, 10, 0, 0))
    template = make_lab_trade(entry_quote, cfg)
    tick = template.entry_evaluation.candidate.instrument.tick_size
    r = scenario.stop_points
    net_r: list[float] = []
    exits: dict[str, int] = {}
    unfilled = 0
    for path in paths:
        bars = []
        for i, premium in enumerate(path):
            ts = template.entry_time + timedelta(seconds=5 * i)
            remaining = (scenario.expected_move_per_bar * max(0.0, scenario.bars - i)
                         if scenario.expected_move_per_bar > 0 else None)
            bars.append(MarketBar(ts, _quote_at(premium, spread, ts), 25000.0,
                                  expected_move_remaining=remaining))
        fill = PaperFillSimulator(cfg).entry_buy(entry_quote, tick)
        if not fill.filled or fill.fill_price is None:
            unfilled += 1
            continue
        trade = PaperTrade(template.trade_id, template.entry_evaluation, fill, template.entry_time)
        result = lifecycle.run(trade, bars, target_points=scenario.target_points, stop_points=scenario.stop_points, max_duration_seconds=scenario.bars * 5, exit_policy=policy)
        exits[result.exit_reason] = exits.get(result.exit_reason, 0) + 1
        net_r.append(result.gross_pnl_points / r)
    metrics = _metrics("managed" if policy is not None else "legacy", net_r, exits)
    return LabMetrics(metrics.label, metrics.trades, metrics.roi_pct, metrics.max_drawdown_r, metrics.win_rate, metrics.profit_factor, metrics.avg_win_r, metrics.avg_loss_r, metrics.exits, unfilled)


def _metrics(label: str, net_r: list[float], exits: dict[str, int]) -> LabMetrics:
    wins = [x for x in net_r if x > 0]
    losses = [x for x in net_r if x <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for x in net_r:
        equity += x
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    capital_r = 100.0
    return LabMetrics(
        label=label,
        trades=len(net_r),
        roi_pct=(sum(net_r) / capital_r) * 100.0,
        max_drawdown_r=max_dd,
        win_rate=len(wins) / len(net_r) if net_r else 0.0,
        profit_factor=gross_win / gross_loss if gross_loss > 0 else float("inf"),
        avg_win_r=mean(wins) if wins else 0.0,
        avg_loss_r=mean(losses) if losses else 0.0,
        exits=exits,
    )


def run_experiment(scenario: Optional[LabScenario] = None, cfg_path: str = "uploads/PARAMETERS.json") -> tuple[LabMetrics, LabMetrics]:
    scenario = scenario or LabScenario()
    cfg = SystemConfig.from_file(cfg_path)
    paths = generate_paths(scenario)
    legacy = simulate_trades(paths, cfg, None, scenario)
    managed = simulate_trades(paths, cfg, ExitPolicy.from_config(cfg), scenario)
    return legacy, managed


def run_vol_time_experiment(scenario: Optional[LabScenario] = None,
                            cfg_path: str = "uploads/PARAMETERS.json",
                            vol_time_fraction: float = 0.35,
                            expected_move_per_bar: float = 2.0) -> tuple[LabMetrics, LabMetrics]:
    """Compare the configured exit policy against the same policy plus the
    volatility-aware time stop (bars carry a decaying expected move)."""
    scenario = scenario or LabScenario(expected_move_per_bar=expected_move_per_bar)
    cfg = SystemConfig.from_file(cfg_path)
    paths = generate_paths(scenario)
    managed = simulate_trades(paths, cfg, ExitPolicy.from_config(cfg), scenario)
    vts_policy = replace(ExitPolicy.from_config(cfg), vol_time_stop_fraction=vol_time_fraction)
    vts = simulate_trades(paths, cfg, vts_policy, scenario)
    return managed, vts


def main() -> int:
    legacy, managed = run_experiment()
    print(legacy.table_row())
    print(managed.table_row())
    delta_roi = managed.roi_pct - legacy.roi_pct
    delta_dd = managed.max_drawdown_r - legacy.max_drawdown_r
    print(f"\nDelta ROI      : {delta_roi:+.2f} pp")
    print(f"Delta maxDraw : {delta_dd:+.2f} R   (<= 0 means drawdown did not worsen)")
    ok = delta_roi > 0 and delta_dd <= 1e-9
    print("Verdict       : " + ("PASS — ROI improved without increasing drawdown" if ok else "FAIL"))
    if ok:
        managed2, vts = run_vol_time_experiment()
        print("\n-- volatility-aware time stop vs configured policy --")
        print(managed2.table_row())
        print(vts.table_row())
        delta_vts = vts.roi_pct - managed2.roi_pct
        delta_vts_dd = vts.max_drawdown_r - managed2.max_drawdown_r
        print(f"Delta ROI      : {delta_vts:+.2f} pp")
        print(f"Delta maxDraw  : {delta_vts_dd:+.2f} R")
        if vts.exits.get("VOL_TIME_STOP", 0) > 0:
            print("VTS fired      : yes — dead trades exited before the deadline")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
