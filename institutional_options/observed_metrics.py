from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Hashable, Optional

from .models import OptionType, Quote


@dataclass(frozen=True)
class ElasticityObservation:
    """One rolling, bid/ask-aware observation of option response."""

    valid: bool
    raw_elasticity: Optional[float]
    post_cost_elasticity: Optional[float]
    underlying_move_points: float
    option_mid_move_points: float
    post_cost_option_move_points: float
    elapsed_seconds: float
    reason: str = ""
    delta_adjusted_elasticity: Optional[float] = None
    post_cost_delta_adjusted_elasticity: Optional[float] = None
    confirmed: bool = False
    confirmation_count: int = 0


class RollingPremiumElasticity:
    """Compute observed option-premium response over a bounded rolling window.

    A valid observation is diagnostic. A confirmed observation additionally needs
    the configured number of consecutive valid windows and a post-cost,
    delta-adjusted response at or above the configured minimum. Missing delta,
    stale/invalid quotes, adverse movement, or insufficient movement never
    becomes a synthetic elasticity value.
    """

    def __init__(
        self,
        window_seconds: float = 60.0,
        min_underlying_move_points: float = 30.0,
        confirmation_windows: int = 2,
        min_confirmed_elasticity: float = 1.0,
    ):
        self.window_seconds = max(1.0, float(window_seconds))
        self.min_underlying_move_points = max(0.0, float(min_underlying_move_points))
        self.confirmation_windows = max(1, int(confirmation_windows))
        self.min_confirmed_elasticity = max(0.0, float(min_confirmed_elasticity))
        self._last: dict[Hashable, tuple[datetime, float, Quote, Optional[float]]] = {}
        self._streak: dict[Hashable, int] = {}

    def update(
        self,
        key: Hashable,
        timestamp: datetime,
        underlying_price: float,
        quote: Quote,
        side: OptionType,
        delta: Optional[float] = None,
    ) -> ElasticityObservation:
        previous = self._last.get(key)
        self._last[key] = (timestamp, float(underlying_price), quote, delta)
        if previous is None:
            self._streak[key] = 0
            return ElasticityObservation(
                False, None, None, 0.0, 0.0, 0.0, 0.0,
                "No prior observation for contract.",
            )

        previous_ts, previous_underlying, previous_quote, previous_delta = previous
        elapsed = (timestamp - previous_ts).total_seconds()
        if elapsed <= 0:
            self._streak[key] = 0
            return ElasticityObservation(
                False, None, None, 0.0, 0.0, 0.0, elapsed,
                "Non-positive observation interval.",
            )
        if elapsed > self.window_seconds:
            self._streak[key] = 0
            return ElasticityObservation(
                False, None, None, 0.0, 0.0, 0.0, elapsed,
                "Observation interval exceeds rolling window.",
            )
        if not quote.is_valid() or not previous_quote.is_valid():
            self._streak[key] = 0
            return ElasticityObservation(
                False, None, None, 0.0, 0.0, 0.0, elapsed,
                "Current or previous quote invalid.",
            )

        underlying_move = float(underlying_price) - previous_underlying
        if abs(underlying_move) < self.min_underlying_move_points:
            self._streak[key] = 0
            return ElasticityObservation(
                False, None, None, underlying_move, 0.0, 0.0, elapsed,
                "Underlying move below identification minimum.",
            )

        option_mid_move = quote.mid - previous_quote.mid
        # A tradable long-option round trip starts at the previous ask and ends
        # at the current bid. This removes the optimistic mid-to-mid effect.
        post_cost_option_move = quote.bid - previous_quote.ask
        side_sign = 1.0 if side is OptionType.CE else -1.0
        favorable_underlying_move = underlying_move * side_sign
        if favorable_underlying_move <= 0:
            self._streak[key] = 0
            return ElasticityObservation(
                False, None, None, underlying_move, option_mid_move,
                post_cost_option_move, elapsed,
                "Underlying move adverse to option side.",
            )

        raw = option_mid_move / favorable_underlying_move
        post_cost = post_cost_option_move / favorable_underlying_move
        current_delta = delta if delta is not None else previous_delta
        if current_delta is None or not math.isfinite(float(current_delta)) or abs(float(current_delta)) < 0.05:
            self._streak[key] = 0
            return ElasticityObservation(
                False, raw, post_cost, underlying_move, option_mid_move,
                post_cost_option_move, elapsed,
                "Delta unavailable or too small for delta-adjusted elasticity.",
            )

        abs_delta = abs(float(current_delta))
        delta_adjusted = raw / abs_delta
        post_cost_delta_adjusted = post_cost / abs_delta
        if not math.isfinite(delta_adjusted) or not math.isfinite(post_cost_delta_adjusted):
            self._streak[key] = 0
            return ElasticityObservation(
                False, raw, post_cost, underlying_move, option_mid_move,
                post_cost_option_move, elapsed,
                "Non-finite delta-adjusted elasticity.",
            )

        if post_cost_delta_adjusted >= self.min_confirmed_elasticity:
            self._streak[key] = self._streak.get(key, 0) + 1
        else:
            self._streak[key] = 0
        count = self._streak[key]
        confirmed = count >= self.confirmation_windows
        return ElasticityObservation(
            True,
            raw,
            post_cost,
            underlying_move,
            option_mid_move,
            post_cost_option_move,
            elapsed,
            "" if confirmed else "Confirmation windows incomplete.",
            delta_adjusted,
            post_cost_delta_adjusted,
            confirmed,
            count,
        )
