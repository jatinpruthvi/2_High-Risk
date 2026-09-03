from __future__ import annotations
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

@dataclass(frozen=True)
class DerivedIVResult:
    value: Optional[float]
    status: str
    reason: str = ""
    source: str = "DERIVED_BLACK_SCHOLES_RESEARCH"

def _cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def _price(spot: float, strike: float, time_years: float, rate: float, vol: float, call: bool) -> float:
    if time_years <= 0 or vol <= 0: return max(spot-strike,0.0) if call else max(strike-spot,0.0)
    srt=vol*math.sqrt(time_years); d1=(math.log(spot/strike)+(rate+0.5*vol*vol)*time_years)/srt; d2=d1-srt; disc=math.exp(-rate*time_years)
    return spot*_cdf(d1)-strike*disc*_cdf(d2) if call else strike*disc*_cdf(-d2)-spot*_cdf(-d1)

def implied_volatility(price: float, spot: float, strike: float, expiry: date | datetime | str, option_type: str, valuation_time: Optional[datetime] = None, risk_free_rate: float = 0.0) -> DerivedIVResult:
    try:
        p,s,k=float(price),float(spot),float(strike); r=float(risk_free_rate)
        if isinstance(expiry,str): expiry=date.fromisoformat(expiry[:10])
        expiry_dt=datetime.combine(expiry, datetime.min.time()) if isinstance(expiry,date) and not isinstance(expiry,datetime) else expiry
        if isinstance(expiry_dt, datetime) and expiry_dt.tzinfo is None:
            expiry_dt=expiry_dt.replace(tzinfo=valuation_time.tzinfo if valuation_time and valuation_time.tzinfo else timezone.utc)
        now=valuation_time or datetime.now(expiry_dt.tzinfo)
        t=max((expiry_dt-now).total_seconds(),0.0)/(365.0*24*3600)
        call=str(option_type).upper()=='CE'
        intrinsic=max(s-k,0.0) if call else max(k-s,0.0); upper=s if call else k
        if not (p>0 and s>0 and k>0 and t>0): return DerivedIVResult(None,'INVALID_INPUT','Non-positive price/spot/strike or expired contract')
        if p < intrinsic or p >= upper: return DerivedIVResult(None,'OUT_OF_BOUNDS','Option price outside no-arbitrage bounds')
        lo,hi=1e-5,5.0
        for _ in range(80):
            mid=(lo+hi)/2.0
            if _price(s,k,t,r,mid,call)>p: hi=mid
            else: lo=mid
        v=(lo+hi)/2.0
        return DerivedIVResult(v,'DERIVED', 'Derived from midpoint and Black-Scholes bisection')
    except (TypeError,ValueError,OverflowError): return DerivedIVResult(None,'INVALID_INPUT','Unable to parse derived-IV inputs')
