from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .models import Moneyness, OptionType
from .option_chain import OptionChainSnapshot


@dataclass(frozen=True)
class SurfaceDiagnostics:
    valid: bool
    atm_iv: Optional[float]
    call_put_iv_skew: Optional[float]
    call_wing_iv: Optional[float]
    put_wing_iv: Optional[float]
    reason: str = ""


class OptionSurfaceDiagnostics:
    """Cross-sectional IV diagnostics for one option-chain snapshot.

    These values are observational only.  IV percentile, IV-versus-realized
    spread, and term-structure comparisons require historical or multi-expiry
    data and are intentionally not inferred here.
    """

    @staticmethod
    def calculate(chain: OptionChainSnapshot) -> SurfaceDiagnostics:
        if not chain.strikes:
            return SurfaceDiagnostics(False, None, None, None, None, "No strikes.")
        atm_strike = chain.nearest_strike()
        try:
            atm = chain.strikes[min(range(len(chain.strikes)), key=lambda i: abs(chain.strikes[i].strike - atm_strike))]
        except (ValueError, IndexError):
            return SurfaceDiagnostics(False, None, None, None, None, "ATM strike unavailable.")

        atm_ce = atm.ce.implied_volatility if atm.ce is not None else None
        atm_pe = atm.pe.implied_volatility if atm.pe is not None else None
        atm_values = [v for v in (atm_ce, atm_pe) if v is not None and v > 0]
        if not atm_values:
            return SurfaceDiagnostics(False, None, None, None, None, "ATM IV unavailable.")
        atm_iv = sum(atm_values) / len(atm_values)
        skew = (atm_ce - atm_pe) if atm_ce is not None and atm_pe is not None else None

        call_wings = []
        put_wings = []
        for strike in chain.strikes:
            if strike.strike == atm_strike:
                continue
            if strike.strike > atm_strike and strike.ce is not None and strike.ce.implied_volatility:
                call_wings.append(strike.ce.implied_volatility)
            if strike.strike < atm_strike and strike.pe is not None and strike.pe.implied_volatility:
                put_wings.append(strike.pe.implied_volatility)
        call_wing = sum(call_wings) / len(call_wings) if call_wings else None
        put_wing = sum(put_wings) / len(put_wings) if put_wings else None
        return SurfaceDiagnostics(True, atm_iv, skew, call_wing, put_wing, "")
