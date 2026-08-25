from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Mapping, Optional

from .config import SystemConfig
from .models import PaperFill, PaperTrade, Quote
from .scoring import PaperFillSimulator


@dataclass(frozen=True)
class MarketBar:
    timestamp: datetime
    quote: Quote
    futures_price: float
    iv: Optional[float] = None
    # Remaining expected move of the underlying in premium points at this bar
    # (e.g. the regime-projected move for the rest of the session). Used by the
    # volatility-aware time stop to decide when a trade can no longer reach its
    # target. None disables that check for this bar.
    expected_move_remaining: Optional[float] = None


@dataclass(frozen=True)
class ExitPolicy:
    """Active exit management for a trade.

    All thresholds are expressed in R multiples, where 1R = the initial stop
    distance. The ratchet never loosens the stop, so the worst-case loss per
    trade is identical to a pure fixed stop; the policy only banks profits
    after the trade is meaningfully in the money.
    """

    enabled: bool = True
    breakeven_trigger_r: float = 1.0
    trail_trigger_r: float = 1.5
    trail_distance_r: float = 1.0
    # Fraction of the max-holding window after which a trade still below entry
    # is exited (asymmetric time stop: losers get cut early, winners keep the
    # full window). 0.0 disables.
    losing_time_stop_fraction: float = 0.0
    # Linear tightening of the stop toward entry as the deadline approaches:
    # stop distance shrinks from 1R to (1 - time_decay_tighten)*1R by the
    # deadline. 0.0 disables.
    time_decay_tighten: float = 0.0
    # Volatility-aware time stop: once this fraction of the max-holding window
    # has elapsed, exit if the remaining expected move (bar.expected_move_remaining)
    # is smaller than the distance still needed to reach the target. This is a
    # smarter version of the losing_time_stop: it exits "dead" trades based on
    # whether the remaining move can plausibly pay out. 0.0 disables.
    vol_time_stop_fraction: float = 0.0
    # Extra slippage applied to risk-reducing exits (stop/breakeven/trail/time/
    # losing-time/vol-time), expressed as a fraction of the initial stop distance
    # (1R). Models gap-through-stop: paper drawdown should be an honest upper
    # bound for live. 0.0 disables (current behaviour).
    stop_exit_slippage_frac: float = 0.0

    @classmethod
    def from_config(cls, config: Optional[SystemConfig]) -> "ExitPolicy":
        if config is None:
            return cls(enabled=False)
        raw = config.raw.get("exit_management")
        if not isinstance(raw, Mapping):
            return cls(enabled=False)
        return cls(
            enabled=bool(raw.get("enabled", True)),
            breakeven_trigger_r=float(raw.get("breakeven_trigger_r", 1.0)),
            trail_trigger_r=float(raw.get("trail_trigger_r", 1.5)),
            trail_distance_r=float(raw.get("trail_distance_r", 1.0)),
            losing_time_stop_fraction=float(raw.get("losing_time_stop_fraction", 0.0)),
            time_decay_tighten=float(raw.get("time_decay_tighten", 0.0)),
            vol_time_stop_fraction=float(raw.get("vol_time_stop_fraction", 0.0)),
            stop_exit_slippage_frac=float(raw.get("stop_exit_slippage_frac", 0.0)),
        )


# Exit reason strings used by SimulatedTradeLifecycle.
EXIT_TARGET = "TARGET_HIT"
EXIT_STOP = "STOP_HIT"
EXIT_BREAKEVEN = "BREAKEVEN_HIT"
EXIT_TRAIL = "TRAIL_HIT"
EXIT_TIME = "TIME_STOP"
EXIT_LOSING_TIME = "LOSING_TIME_STOP"
EXIT_VOL_TIME = "VOL_TIME_STOP"
EXIT_END_OF_DATA = "END_OF_DATA_EXIT"
EXIT_NO_DATA = "NO_EXIT_DATA"


@dataclass(frozen=True)
class SimulatedTradeResult:
    trade: PaperTrade
    exit_reason: str
    highest_premium: float
    lowest_premium: float
    mfe_points: float
    mae_points: float
    gross_pnl_points: float
    gross_pnl_rupees: float


class SimulatedTradeLifecycle:
    """Simulates a long-option paper trade bar by bar.

    Pass an `ExitPolicy` to enable active exit management (breakeven lock-in
    and a trailing stop ratchet). With no policy, behaviour is identical to the
    legacy fixed target/stop/time exit.
    """

    def __init__(self, fill_simulator: PaperFillSimulator):
        self.fill_simulator = fill_simulator

    def run(
        self,
        trade: PaperTrade,
        bars: Iterable[MarketBar],
        target_points: float,
        stop_points: float,
        max_duration_seconds: int,
        exit_policy: Optional[ExitPolicy] = None,
    ) -> SimulatedTradeResult:
        if not trade.entry_fill.filled or trade.entry_fill.fill_price is None:
            raise ValueError("Cannot simulate lifecycle for unfilled entry.")
        entry = trade.entry_fill.fill_price
        if exit_policy is not None and exit_policy.enabled and stop_points > 0:
            return self._run_managed(trade, bars, target_points, stop_points, max_duration_seconds, exit_policy, entry)
        return self._run_legacy(trade, bars, target_points, stop_points, max_duration_seconds, entry)

    def _run_legacy(
        self,
        trade: PaperTrade,
        bars: Iterable[MarketBar],
        target_points: float,
        stop_points: float,
        max_duration_seconds: int,
        entry: float,
    ) -> SimulatedTradeResult:
        high = entry
        low = entry
        exit_fill: Optional[PaperFill] = None
        exit_time: Optional[datetime] = None
        exit_reason = EXIT_NO_DATA
        deadline = trade.entry_time + timedelta(seconds=max_duration_seconds)
        last_quote: Optional[Quote] = None
        last_time: Optional[datetime] = None
        tick = trade.entry_evaluation.candidate.instrument.tick_size
        for bar in bars:
            last_quote = bar.quote
            last_time = bar.timestamp
            premium = bar.quote.mid
            high = max(high, premium)
            low = min(low, premium)
            if premium >= entry + target_points:
                exit_fill = self.fill_simulator.exit_sell(bar.quote, tick)
                exit_time = bar.timestamp
                exit_reason = EXIT_TARGET
                break
            if premium <= entry - stop_points:
                exit_fill = self.fill_simulator.exit_sell(bar.quote, tick)
                exit_time = bar.timestamp
                exit_reason = EXIT_STOP
                break
            if bar.timestamp >= deadline:
                exit_fill = self.fill_simulator.exit_sell(bar.quote, tick)
                exit_time = bar.timestamp
                exit_reason = EXIT_TIME
                break
        return self._finalize(trade, entry, high, low, exit_fill, exit_time, exit_reason, last_quote, last_time, tick)

    def _run_managed(
        self,
        trade: PaperTrade,
        bars: Iterable[MarketBar],
        target_points: float,
        stop_points: float,
        max_duration_seconds: int,
        policy: ExitPolicy,
        entry: float,
    ) -> SimulatedTradeResult:
        """Fixed stop plus breakeven lock-in and a trailing stop ratchet.

        The stop level is monotonically non-decreasing: it starts at the fixed
        stop, moves to entry after `breakeven_trigger_r` R of profit, and then
        trails `trail_distance_r` R below the running high after
        `trail_trigger_r` R of profit. It never loosens, so worst-case per-trade
        risk is identical to the legacy fixed stop.
        """

        r = stop_points
        initial_stop = entry - stop_points
        stop_level = initial_stop
        breakeven_trigger = entry + policy.breakeven_trigger_r * r
        trail_trigger = entry + policy.trail_trigger_r * r
        high = entry
        low = entry
        exit_fill: Optional[PaperFill] = None
        exit_time: Optional[datetime] = None
        exit_reason = EXIT_NO_DATA
        deadline = trade.entry_time + timedelta(seconds=max_duration_seconds)
        last_quote: Optional[Quote] = None
        last_time: Optional[datetime] = None
        tick = trade.entry_evaluation.candidate.instrument.tick_size
        # Gap/slippage buffer on risk-reducing exits (never on targets): models
        # that a real marketable exit during a fast move fills worse than the
        # observed quote. 0 by default -> legacy behaviour.
        exit_buffer = r * max(0.0, policy.stop_exit_slippage_frac)
        for bar in bars:
            last_quote = bar.quote
            last_time = bar.timestamp
            premium = bar.quote.mid
            high = max(high, premium)
            low = min(low, premium)
            # Ratchet: lock in breakeven, then trail behind the running high.
            # Never loosens the stop, so risk per trade never increases.
            if premium >= breakeven_trigger and stop_level < entry:
                stop_level = entry
            if premium >= trail_trigger:
                trail_level = high - policy.trail_distance_r * r
                if trail_level > stop_level:
                    stop_level = trail_level
            # Time-decay tightening: shrink the stop distance toward entry as
            # the deadline approaches (never loosens; 0 when disabled).
            if policy.time_decay_tighten > 0:
                elapsed_frac = min(1.0, max(0.0, (bar.timestamp - trade.entry_time).total_seconds() / max_duration_seconds)) if max_duration_seconds > 0 else 1.0
                decayed_stop = entry - stop_points * (1.0 - policy.time_decay_tighten * elapsed_frac)
                if decayed_stop > stop_level:
                    stop_level = decayed_stop
            if premium >= entry + target_points:
                exit_fill = self.fill_simulator.exit_sell(bar.quote, tick)
                exit_time = bar.timestamp
                exit_reason = EXIT_TARGET
                break
            if premium <= stop_level:
                exit_fill = self.fill_simulator.exit_sell(bar.quote, tick, slippage_baseline=exit_buffer)
                exit_time = bar.timestamp
                if entry - 1e-9 <= stop_level <= entry + 1e-9:
                    exit_reason = EXIT_BREAKEVEN
                elif stop_level > entry + 1e-9:
                    exit_reason = EXIT_TRAIL
                else:
                    # Initial stop or a time-decayed stop below entry.
                    exit_reason = EXIT_STOP
                break
            # Asymmetric time stop: exit a still-losing trade early so losers
            # do not consume the full holding window (0 when disabled).
            # Checked after the stop, so a crash straight through the initial
            # stop is still labelled STOP_HIT.
            if policy.losing_time_stop_fraction > 0:
                elapsed_frac = min(1.0, max(0.0, (bar.timestamp - trade.entry_time).total_seconds() / max_duration_seconds)) if max_duration_seconds > 0 else 1.0
                if elapsed_frac >= policy.losing_time_stop_fraction and premium < entry:
                    exit_fill = self.fill_simulator.exit_sell(bar.quote, tick, slippage_baseline=exit_buffer)
                    exit_time = bar.timestamp
                    exit_reason = EXIT_LOSING_TIME
                    break
            # Volatility-aware time stop: once past the fraction threshold, exit
            # if the remaining expected move can no longer reach the target.
            # Only fires when the runner supplies expected_move_remaining.
            if policy.vol_time_stop_fraction > 0 and bar.expected_move_remaining is not None and bar.expected_move_remaining >= 0:
                elapsed_frac = min(1.0, max(0.0, (bar.timestamp - trade.entry_time).total_seconds() / max_duration_seconds)) if max_duration_seconds > 0 else 1.0
                if elapsed_frac >= policy.vol_time_stop_fraction:
                    dist_to_target = (entry + target_points) - premium
                    if dist_to_target > bar.expected_move_remaining + 1e-9:
                        exit_fill = self.fill_simulator.exit_sell(bar.quote, tick, slippage_baseline=exit_buffer)
                        exit_time = bar.timestamp
                        exit_reason = EXIT_VOL_TIME
                        break
            if bar.timestamp >= deadline:
                exit_fill = self.fill_simulator.exit_sell(bar.quote, tick, slippage_baseline=exit_buffer)
                exit_time = bar.timestamp
                exit_reason = EXIT_TIME
                break
        return self._finalize(trade, entry, high, low, exit_fill, exit_time, exit_reason, last_quote, last_time, tick)

    def _finalize(
        self,
        trade: PaperTrade,
        entry: float,
        high: float,
        low: float,
        exit_fill: Optional[PaperFill],
        exit_time: Optional[datetime],
        exit_reason: str,
        last_quote: Optional[Quote],
        last_time: Optional[datetime],
        tick: float,
    ) -> SimulatedTradeResult:
        if exit_fill is None and last_quote is not None:
            exit_fill = self.fill_simulator.exit_sell(last_quote, tick)
            exit_time = last_time
            exit_reason = EXIT_END_OF_DATA
        if exit_fill is None or not exit_fill.filled or exit_fill.fill_price is None:
            exit_price = 0.0
        else:
            exit_price = exit_fill.fill_price
        lot = trade.entry_evaluation.candidate.instrument.lot_size
        gross_points = exit_price - entry
        return SimulatedTradeResult(
            PaperTrade(trade.trade_id, trade.entry_evaluation, trade.entry_fill, trade.entry_time, exit_fill, exit_time, exit_reason),
            exit_reason,
            high,
            low,
            high - entry,
            entry - low,
            gross_points,
            gross_points * lot,
        )
