"""Live-data proxies for the score fields the CandidateFactory leaves zeroed.

The candidate factory intentionally leaves these at 0.0:
    premium_elasticity, convexity_edge_score, execution_quality_score,
    opportunity_confidence_score, regime_fit_score
With zeros the OpportunityScorer hard-rejects every candidate
(premium_elasticity < 0.5) and the final opportunity score cannot reach the
A/A+ threshold, so the paper program would never trade.

This module computes honest, clearly-documented proxies from live Fyers data
(spot, VIX, ATM straddle, recent 1-min history). They are PROXIES — they are
research-grade approximations of the real institutional scores, and the
dashboard marks every proxied field so nobody mistakes them for validated
signals. Config keys under ``paper_runner.signal`` tune the mapping.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from typing import Mapping, Optional

from .config import SystemConfig
from .direction_models import DirectionModelCalculator, LeadershipInput, MidcapDirectionInput
from .edge_modules import AdvancedEdgeCalculator, EdgeInputs, ExecutionQualityCalculator
from .models import CalibrationStatus, Moneyness, OptionType
from .operator_controls import load_market_context
from .option_chain import OptionChainSnapshot
from .scoring import clamp, linear_score

NSE_SESSION_MINUTES = 375.0  # 09:15 - 15:30


@dataclass(frozen=True)
class LiveSignalContext:
    """Everything the runner computes once per underlying per poll."""

    underlying: str
    spot_price: float
    vix: Optional[float]
    dte: float
    direction_score: float          # -100..100
    trade_quality_score: float      # 0..100
    regime_confidence: float        # 0..100
    market_hostility_score: float   # 0..100
    atr_remaining_move: float       # points
    regime_projected_move: float    # points
    required_move: float            # points
    calibration_direction: CalibrationStatus
    calibration_liquidity: CalibrationStatus
    trend_efficiency: float         # 0..100 (diagnostic)
    atr1: float                     # 1-min ATR in points (diagnostic)
    direction_model_score: Optional[float] = None
    direction_model_name: str = ""
    direction_model_status: str = "UNAVAILABLE"
    direction_model_disagreement: Optional[float] = None


@dataclass(frozen=True)
class CandidateProxies:
    premium_elasticity: float
    convexity_edge_score: float
    execution_quality_score: float
    opportunity_confidence_score: float
    regime_fit_score: float


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n % 2:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


class PaperSignalCalculator:
    """Builds LiveSignalContext and per-candidate proxies from live data."""

    def __init__(self, config: SystemConfig, history_candles: Optional[list[list]] = None):
        self.config = config
        self.history_candles = history_candles or []  # Fyers history: [ts, o, h, l, c, vol]
        context_path = config.raw.get("operator_controls", {}).get("market_context_path", "uploads/DAILY_MARKET_CONTEXT.json") if isinstance(config.raw.get("operator_controls", {}), Mapping) else "uploads/DAILY_MARKET_CONTEXT.json"
        self.market_context = load_market_context(context_path)

    # -- underlying-level signals --------------------------------------------

    def compute_context(self, chain: OptionChainSnapshot, vix: Optional[float],
                        now: datetime | None = None,
                        history_candles: Optional[list] = None,
                        direction_model_inputs: Optional[Mapping[str, list]] = None) -> LiveSignalContext:
        now = now or datetime.now(timezone.utc)
        spot = chain.underlying_price
        dte = max(0.0, self._dte(chain.expiry, now))
        history = history_candles if history_candles is not None else self.history_candles
        closes = [c[4] for c in history if isinstance(c, (list, tuple)) and len(c) >= 5]
        atr1 = self._atr_1min(history)
        trend_eff, direction = self._trend_signals(closes)
        vix = vix if vix and vix > 0 else None
        trade_quality = self._trade_quality(trend_eff, vix)
        regime_conf = self._regime_confidence(vix)
        hostility = self._hostility(vix, atr1, spot)
        remaining_min = self._remaining_minutes(now)
        atr_remaining = atr1 * remaining_min if remaining_min > 0 else atr1 * 30.0
        regime_projected = self._regime_projected_move(spot, vix, remaining_min)
        straddle = self._atm_straddle(chain)
        required = max(straddle * self._cfg_float("signal", "required_move_straddle_factor", 0.6), 1.0)
        cal_dir, cal_liq = self._calibration_status(chain.underlying)
        model_score, model_name, model_status = self.shadow_direction_score(
            chain.underlying, history, direction_model_inputs or {},
        )
        disagreement = abs(direction - model_score) if model_score is not None else None
        active_direction = direction
        if self._cfg_bool("direction_model_runtime", "use_model_for_trade", False) and model_score is not None:
            active_direction = model_score
        return LiveSignalContext(
            underlying=chain.underlying,
            spot_price=spot,
            vix=vix,
            dte=dte,
            direction_score=active_direction,
            trade_quality_score=trade_quality,
            regime_confidence=regime_conf,
            market_hostility_score=hostility,
            atr_remaining_move=atr_remaining,
            regime_projected_move=regime_projected,
            required_move=required,
            calibration_direction=cal_dir,
            calibration_liquidity=cal_liq,
            trend_efficiency=trend_eff,
            atr1=atr1,
            direction_model_score=model_score,
            direction_model_name=model_name,
            direction_model_status=model_status,
            direction_model_disagreement=disagreement,
        )

    # -- per-candidate proxies -------------------------------------------------

    def candidate_proxies(self, chain: OptionChainSnapshot, ctx: LiveSignalContext,
                          moneyness: Moneyness, option_type: OptionType,
                          spread_pct: float,
                          observed_elasticity: float = 0.0,
                          real_gamma: Optional[float] = None,
                          calibration_scope: bool = False,
                          execution_calculator: Optional[ExecutionQualityCalculator] = None,
                          underlying: str = "") -> CandidateProxies:
        # Premium elasticity: use observed elasticity if available.
        # For canonical (non-calibration) candidates, only use confirmed observed elasticity.
        # For calibration scope, fall back to moneyness proxy.
        if observed_elasticity > 0 or calibration_scope:
            premium_elasticity = observed_elasticity if observed_elasticity > 0 else \
                {Moneyness.ATM: 0.5, Moneyness.ITM: 0.7, Moneyness.OTM: 0.3}[moneyness]
        else:
            premium_elasticity = 0.0  # Canonical: hard reject until confirmed

        expected = self._expected_move(ctx, chain)
        ratio = expected / ctx.required_move if ctx.required_move > 0 else 0.0
        acceleration = linear_score(ratio, ideal=1.6, acceptable=1.1, reject=0.8)
        gamma_usefulness = self._gamma_usefulness(moneyness, ctx.dte, real_gamma)
        iv_support = clamp(100.0 - 0.6 * self._iv_crush_estimate(ctx, chain))
        time_to_profit = self._time_to_profit(ctx.dte, ratio)
        convexity = AdvancedEdgeCalculator.convexity_edge_score(EdgeInputs(
            premium_elasticity_score=clamp(premium_elasticity * 100.0, 0.0, 100.0),
            gamma_usefulness_score=gamma_usefulness,
            expected_acceleration_score=acceleration,
            iv_support_score=iv_support,
            time_to_profit_quality_score=time_to_profit,
        ))

        if execution_calculator is not None and underlying:
            from datetime import timezone
            from .paper_runner import now_ist
            hour = now_ist().hour if now_ist() else 12
            execution = execution_calculator.score(underlying, spread_pct, hour)
        else:
            execution = self._execution_score(spread_pct)
        confidence = self._confidence_score(ctx, spread_pct)
        # Side-aware directional conviction: a call in an uptrend (or a put in a
        # downtrend) is a higher-conviction trade than the opposite side. This is
        # what breaks the CE/PE tie in the engine's rank tie-break on real data.
        side_ok = (option_type is OptionType.CE and ctx.direction_score >= 0) or \
                  (option_type is OptionType.PE and ctx.direction_score <= 0)
        if side_ok:
            confidence = clamp(confidence + min(12.0, abs(ctx.direction_score) * 0.15))
        else:
            confidence = clamp(confidence - min(12.0, abs(ctx.direction_score) * 0.15))
        regime_fit = self._regime_fit(chain.underlying, ctx.vix)
        return CandidateProxies(premium_elasticity, convexity, execution, confidence, regime_fit)

    # -- internals ---------------------------------------------------------------

    def _dte(self, expiry_str: str, now: datetime) -> float:
        try:
            exp = date.fromisoformat(expiry_str[:10])
        except (ValueError, TypeError):
            return 0.0
        return (exp - now.date()).days

    def _cfg_bool(self, section: str, key: str, default: bool) -> bool:
        raw = self.config.raw.get(section)
        if isinstance(raw, Mapping):
            value = raw.get(key, default)
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in {"1", "true", "yes", "y"}
        return default

    def shadow_direction_score(
        self,
        underlying: str,
        primary_history: list,
        component_histories: Mapping[str, list],
    ) -> tuple[Optional[float], str, str]:
        """Calculate the richer direction model for shadow comparison only.

        Missing component histories fail closed to ``None``. The current proxy
        remains the trade signal unless the explicit, disabled-by-default
        ``use_model_for_trade`` switch is enabled after validation.
        """
        name = str(underlying or "").upper()
        features = self._history_features(primary_history)
        if features is None:
            return None, name, "PRIMARY_HISTORY_INSUFFICIENT"
        if name == "MIDCPNIFTY":
            score = DirectionModelCalculator.midcap_direction_proxy(MidcapDirectionInput(
                futures_vwap_structure_score=DirectionModelCalculator.vwap_state_score(
                    features["last_price"], features["vwap"], features["vwap_slope"],
                ),
                trend_efficiency_score=features["trend_efficiency"],
                premium_elasticity_directional_score=0.0,
                broad_market_confirmation_score=0.0,
            ))
            return score, "midcap_direction_proxy", "PARTIAL_MIDCAP"
        if name not in {"BANKNIFTY", "NIFTY", "FINNIFTY"}:
            return None, name, "NOT_CONFIGURED"
        cfg = self.config.raw.get("direction_model_runtime", {})
        symbols = cfg.get("component_symbols", {}).get(name, []) if isinstance(cfg, Mapping) else []
        if not symbols:
            return None, name, "COMPONENTS_NOT_CONFIGURED"
        weights = cfg.get("component_weights", {}).get(name, {}) if isinstance(cfg, Mapping) else {}
        inputs: list[LeadershipInput] = []
        for symbol in symbols:
            history = component_histories.get(symbol)
            item = self._history_features(history)
            if item is None:
                return None, name, f"MISSING_COMPONENT_HISTORY:{symbol}"
            inputs.append(LeadershipInput(
                symbol=symbol,
                weight=float(weights.get(symbol, 1.0)) if isinstance(weights, Mapping) else 1.0,
                last_price=item["last_price"],
                vwap=item["vwap"],
                vwap_slope=item["vwap_slope"],
                stock_return_5m_pct=item["return_5m_pct"],
                index_return_5m_pct=features["return_5m_pct"],
                relative_volume=item["relative_volume"],
            ))
        calc = DirectionModelCalculator()
        if name == "BANKNIFTY":
            return calc.banknifty_fast_wbci(inputs), "banknifty_fast_wbci", "VALID"
        if name == "FINNIFTY":
            return calc.finnifty_leadership_proxy(inputs), "finnifty_leadership_proxy", "VALID"
        return calc.nifty_leadership_proxy(inputs), "nifty_leadership_proxy", "VALID"

    def _history_features(self, history: Optional[list]) -> Optional[dict[str, float | None]]:
        if not isinstance(history, list) or len(history) < 10:
            return None
        rows = [row for row in history if isinstance(row, (list, tuple)) and len(row) >= 6]
        if len(rows) < 10:
            return None
        closes = [float(row[4]) for row in rows[-20:]]
        volumes = [float(row[5]) for row in rows[-20:]]
        if not closes or closes[-1] <= 0:
            return None
        recent = rows[-5:]
        prior = rows[-10:-5]
        def vwap(items):
            total_volume = sum(max(0.0, float(row[5])) for row in items)
            return (sum(float(row[4]) * max(0.0, float(row[5])) for row in items) / total_volume
                    if total_volume > 0 else sum(float(row[4]) for row in items) / len(items))
        recent_vwap = vwap(recent)
        prior_vwap = vwap(prior)
        base = closes[-6] if closes[-6] else 0.0
        return {
            "last_price": closes[-1],
            "vwap": recent_vwap,
            "vwap_slope": recent_vwap - prior_vwap,
            "return_5m_pct": ((closes[-1] - base) / base * 100.0) if base > 0 else 0.0,
            "relative_volume": (sum(volumes[-5:]) / 5.0) / (sum(volumes[:-5]) / max(1, len(volumes[:-5]))) if sum(volumes[:-5]) > 0 else None,
            "trend_efficiency": self._trend_signals(closes)[0],
        }

    def _cfg_float(self, section: str, key: str, default: float) -> float:
        raw = self.config.raw.get("paper_runner")
        if not isinstance(raw, Mapping):
            return default
        sec = raw.get(section)
        if not isinstance(sec, Mapping):
            return default
        try:
            return float(sec.get(key, default))
        except (TypeError, ValueError):
            return default

    def _atr_1min(self, history: Optional[list] = None) -> float:
        candles = history if history is not None else self.history_candles
        if len(candles) < 3:
            return 0.0
        diffs = []
        for c in candles[-15:]:
            if not isinstance(c, (list, tuple)) or len(c) < 4:
                continue
            try:
                h, l = float(c[2]), float(c[3])
            except (TypeError, ValueError):
                continue
            diffs.append(h - l)
        return mean(diffs) if diffs else 0.0

    def _trend_signals(self, closes: list[float]) -> tuple[float, float]:
        """Efficiency ratio (0..100) and signed direction (-100..100).

        Efficiency ratio = |net move over window| / sum(|per-bar moves|).
        High efficiency -> clean trending move -> good option-buying regime.
        """
        if len(closes) < 10:
            return 50.0, 0.0
        window = closes[-10:]
        net = abs(window[-1] - window[0])
        path = sum(abs(b - a) for a, b in zip(window, window[1:]))
        eff = (net / path * 100.0) if path > 0 else 0.0
        ret = (window[-1] - window[0]) / window[0] if window[0] else 0.0
        # Scale direction: 1% move -> |80|, capped at 100.
        direction = clamp(ret * 8000.0, -100.0, 100.0)
        return eff, direction

    def _trade_quality(self, trend_eff: float, vix: Optional[float]) -> float:
        base = trend_eff
        if vix is not None:
            # Very low VIX -> compression chop; very high -> event risk.
            if vix < 10 or vix > 22:
                base *= 0.6
            elif vix < 12 or vix > 19:
                base *= 0.8
        return clamp(base)

    def _regime_confidence(self, vix: Optional[float]) -> float:
        if vix is None:
            return 50.0
        # Moderate VIX = orderly regime; extremes reduce confidence.
        if 12 <= vix <= 18:
            return 80.0
        if 10 <= vix <= 22:
            return 60.0
        return 35.0

    def _hostility(self, vix: Optional[float], atr1: float, spot: float) -> float:
        score = 15.0
        if vix is not None:
            score += max(0.0, (vix - 16.0)) * 3.0      # high VIX -> hostile
            score += max(0.0, (11.0 - vix)) * 4.0      # ultra-low VIX -> chop
        if spot > 0:
            score += min(20.0, (atr1 / spot) * 100.0 * 200.0)  # erratic bars
        return clamp(score, 0.0, 100.0)

    def _remaining_minutes(self, now: datetime) -> float:
        # Approximate NSE session; weekend/after-hours handled by the runner gate.
        ist = now.astimezone(timezone(timedelta(hours=5, minutes=30)))
        minutes = ist.hour * 60 + ist.minute
        if minutes < 9 * 60 + 15:
            return NSE_SESSION_MINUTES
        if minutes > 15 * 60 + 30:
            return 0.0
        return 15 * 60 + 30 - minutes

    def _regime_projected_move(self, spot: float, vix: Optional[float], remaining_min: float) -> float:
        if spot <= 0:
            return 0.0
        if vix is None:
            vix = 13.0
        # Annualized VIX -> daily implied move, scaled by remaining session.
        daily = spot * (vix / 100.0) / 252.0 ** 0.5
        return daily * (remaining_min / NSE_SESSION_MINUTES)

    def _atm_straddle(self, chain: OptionChainSnapshot) -> float:
        try:
            k = chain.nearest_strike()
            ce = chain.leg_at(k, OptionType.CE)
            pe = chain.leg_at(k, OptionType.PE)
            return ce.quote.mid + pe.quote.mid
        except Exception:
            return 0.0

    def _expected_move(self, ctx: LiveSignalContext, chain: OptionChainSnapshot) -> float:
        from .market_metrics import ExpectedMoveCalculator
        straddle = self._atm_straddle(chain)
        haircut = self.config.section("expected_move_model_phase1")["confidence_haircuts"]
        h = float(haircut.get(ctx.underlying.upper(), 0.70))
        raw = _median([ctx.atr_remaining_move, ctx.regime_projected_move, straddle])
        return raw * h

    def _iv_crush_estimate(self, ctx: LiveSignalContext, chain: OptionChainSnapshot) -> float:
        from .market_metrics import IVCrushRiskCalculator
        calc = IVCrushRiskCalculator(self.config)
        values = self.market_context.values
        return calc.calculate(
            None,
            event_risk=values["event_risk"],
            recent_iv_expansion_pct=values["recent_iv_expansion_pct"],
            iv_realized_spread_pct=values["iv_realized_spread_pct"],
            term_structure_risk=values["term_structure_risk"],
            dte=ctx.dte,
            skew_risk=values["skew_risk"],
        )

    @staticmethod
    def _gamma_usefulness(moneyness: Moneyness, dte: float, real_gamma: Optional[float] = None) -> float:
        if real_gamma is not None and real_gamma > 0:
            # Real gamma from option chain: normalize to 0-100 scale
            # Typical gamma for ATM options: 0.001 - 0.01 per point
            # Scale: 0.005 = 100, 0.001 = 20, 0.01 = 100 (cap)
            gamma_score = min(100.0, max(20.0, real_gamma * 20000.0))
            base = gamma_score
        else:
            base = {Moneyness.ATM: 90.0, Moneyness.ITM: 60.0, Moneyness.OTM: 50.0}[moneyness]
        if dte <= 1:
            base *= 0.8  # expiry-day pin risk
        return clamp(base)

    @staticmethod
    def _time_to_profit(dte: float, ratio: float) -> float:
        score = 50.0
        if 2 <= dte <= 8:
            score += 20.0
        elif dte > 8:
            score += 10.0
        if ratio >= 1.6:
            score += 20.0
        elif ratio >= 1.1:
            score += 10.0
        return clamp(score)

    def _execution_score(self, spread_pct: float) -> float:
        return linear_score(spread_pct, ideal=0.8, acceptable=1.5, reject=2.5)

    def _confidence_score(self, ctx: LiveSignalContext, spread_pct: float) -> float:
        data_conf = linear_score(spread_pct, ideal=1.0, acceptable=2.0, reject=4.0)
        cal_conf = 45.0
        if ctx.calibration_direction != CalibrationStatus.UNVALIDATED:
            cal_conf += 10.0
        if ctx.calibration_liquidity != CalibrationStatus.UNVALIDATED:
            cal_conf += 10.0
        agreement = 100.0 - min(60.0, abs(ctx.trade_quality_score - ctx.regime_confidence))
        return clamp(0.4 * data_conf + 0.3 * cal_conf + 0.3 * agreement)

    def _regime_fit(self, underlying: str, vix: Optional[float]) -> float:
        matrix = self.config.section("instrument_regime_fit_matrix")
        if vix is None:
            regime = "broad_market_trend"
        elif vix < 11:
            regime = "low_vol_compression"
        elif vix <= 18:
            regime = "broad_market_trend"
        else:
            regime = "risk_off_panic"
        row = matrix.get(regime, {})
        try:
            return clamp(float(row.get(underlying.upper(), 60.0)))
        except (TypeError, ValueError):
            return 60.0

    def _calibration_status(self, underlying: str) -> tuple[CalibrationStatus, CalibrationStatus]:
        raw = self.config.raw.get("instrument_calibration_status", {})
        entry = raw.get(underlying.upper(), {}) if isinstance(raw, Mapping) else {}
        def to_status(value, default=CalibrationStatus.UNVALIDATED):
            try:
                return CalibrationStatus(str(value).upper())
            except ValueError:
                return default
        return (to_status(entry.get("direction")), to_status(entry.get("liquidity")))
