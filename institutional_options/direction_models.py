from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from .scoring import clamp


@dataclass(frozen=True)
class LeadershipInput:
    symbol: str
    weight: float
    last_price: float
    vwap: float
    vwap_slope: float
    stock_return_5m_pct: float
    index_return_5m_pct: float
    relative_volume: Optional[float] = None
    sector_score: float = 0.0


@dataclass(frozen=True)
class MidcapDirectionInput:
    futures_vwap_structure_score: float
    trend_efficiency_score: float
    premium_elasticity_directional_score: float
    broad_market_confirmation_score: float


class DirectionModelCalculator:
    @staticmethod
    def vwap_state_score(last_price: float, vwap: float, vwap_slope: float, near_band_pct: float = 0.05) -> float:
        if vwap <= 0:
            return 0.0
        diff_pct = (last_price - vwap) / vwap * 100.0
        if diff_pct > near_band_pct and vwap_slope > 0:
            return 100.0
        if diff_pct > near_band_pct and vwap_slope >= 0:
            return 60.0
        if -near_band_pct <= diff_pct <= near_band_pct:
            return 0.0
        if diff_pct < -near_band_pct and vwap_slope < 0:
            return -100.0
        if diff_pct < -near_band_pct and vwap_slope <= 0:
            return -60.0
        return 0.0

    @staticmethod
    def relative_strength_score(stock_ret_5m_pct: float, index_ret_5m_pct: float, mild: float = 0.05, strong: float = 0.15) -> float:
        rs = stock_ret_5m_pct - index_ret_5m_pct
        if rs >= strong:
            return 100.0
        if rs >= mild:
            return 60.0
        if -mild < rs < mild:
            return 0.0
        if rs > -strong:
            return -60.0
        return -100.0

    @staticmethod
    def volume_confirmation_score(stock_ret_5m_pct: float, relative_volume: Optional[float], mild_rvol: float = 1.0, strong_rvol: float = 1.5) -> float:
        if relative_volume is None:
            return 0.0
        if abs(stock_ret_5m_pct) < 1e-12:
            return 0.0
        sign = 1.0 if stock_ret_5m_pct > 0 else -1.0
        if relative_volume >= strong_rvol:
            return 100.0 * sign
        if relative_volume >= mild_rvol:
            return 60.0 * sign
        return 0.0

    def weighted_leadership_score(self, inputs: list[LeadershipInput], use_sector_component: bool = True) -> float:
        if not inputs:
            return 0.0
        total_weight = sum(max(0.0, i.weight) for i in inputs)
        if total_weight <= 0:
            total_weight = float(len(inputs))
            weights = {i.symbol: 1.0 / total_weight for i in inputs}
        else:
            weights = {i.symbol: max(0.0, i.weight) / total_weight for i in inputs}
        score = 0.0
        for i in inputs:
            vwap = self.vwap_state_score(i.last_price, i.vwap, i.vwap_slope)
            rs = self.relative_strength_score(i.stock_return_5m_pct, i.index_return_5m_pct)
            vol = self.volume_confirmation_score(i.stock_return_5m_pct, i.relative_volume)
            if use_sector_component:
                stock_score = 0.40 * vwap + 0.30 * rs + 0.20 * vol + 0.10 * clamp(i.sector_score, -100, 100)
            else:
                stock_score = 0.45 * vwap + 0.35 * rs + 0.20 * vol
            score += weights[i.symbol] * stock_score
        return clamp(score, -100.0, 100.0)

    def banknifty_fast_wbci(self, inputs: list[LeadershipInput]) -> float:
        return self.weighted_leadership_score(inputs, use_sector_component=False)

    def nifty_leadership_proxy(self, inputs: list[LeadershipInput]) -> float:
        return self.weighted_leadership_score(inputs, use_sector_component=True)

    def finnifty_leadership_proxy(self, inputs: list[LeadershipInput]) -> float:
        return self.weighted_leadership_score(inputs, use_sector_component=True)

    @staticmethod
    def midcap_direction_proxy(i: MidcapDirectionInput) -> float:
        return clamp(
            0.40 * i.futures_vwap_structure_score
            + 0.25 * i.trend_efficiency_score
            + 0.20 * i.premium_elasticity_directional_score
            + 0.15 * i.broad_market_confirmation_score,
            -100.0,
            100.0,
        )

    @staticmethod
    def instrument_direction_score(leadership_score: float, futures_auction_structure_score: float, momentum_trend_efficiency_score: float, options_premium_confirmation_score: float) -> float:
        return clamp(
            0.35 * leadership_score
            + 0.30 * futures_auction_structure_score
            + 0.20 * momentum_trend_efficiency_score
            + 0.15 * options_premium_confirmation_score,
            -100.0,
            100.0,
        )
