# MVP Formula Specification

## Purpose
Exact code-ready formula definitions for the first MVP implementation.

---

# 0. Dynamic Risk and Stop-Fit Model

## Purpose

Risk per trade is dynamic. The rupee values in `PARAMETERS.json` are maximum caps, not fixed target losses.

```text
₹750 normal risk = ceiling, not target.
Actual planned risk may be lower.
```

## 0.1 Max Allowed Risk

Normal mode:

```text
MaxAllowedRisk = min(Capital * 0.0075, normal_risk_cap_rupees)
```

A+ setup:

```text
MaxAllowedRisk = min(Capital * 0.0100, a_plus_risk_cap_rupees)
```

Defensive mode:

```text
MaxAllowedRisk = min(Capital * defensive_risk_pct, defensive_risk_max_rupees)
```

For survival and no-trade modes:

```text
MaxAllowedRisk = 0
```

## 0.2 Premium-Based Stop Points

Normal trade:

```text
PremiumStopPoints = entry_premium * 0.20
PointCap = 25
RiskCapStopPoints = MaxAllowedRisk / (lot_size * lots)
HardStopPoints = min(PointCap, PremiumStopPoints, RiskCapStopPoints)
PlannedRiskRupees = HardStopPoints * lot_size * lots
```

A+ trade:

```text
PremiumStopPoints = entry_premium * 0.25
PointCap = 33
RiskCapStopPoints = MaxAllowedRisk / (lot_size * lots)
HardStopPoints = min(PointCap, PremiumStopPoints, RiskCapStopPoints)
PlannedRiskRupees = HardStopPoints * lot_size * lots
```

## 0.3 Required Logical Stop Fit

The setup may require a logical stop based on structure, volatility, spread, or invalidation.

```text
RequiredStopRisk = RequiredStopPoints * lot_size * lots
```

Stop-fit rule:

```text
if RequiredStopRisk > MaxAllowedRisk:
    hard_stop_fit = false
    trade_allowed = false
else:
    hard_stop_fit = true
```

Do not force a trade by widening the risk cap. If the required stop does not fit, skip the trade.

## 0.4 Actual Planned Risk

Actual planned risk is the risk implied by the selected hard stop. It is not automatically equal to the cap.

```text
ActualPlannedRisk = PlannedRiskRupees
ActualPlannedRisk <= MaxAllowedRisk
```

Examples for 1 Bank Nifty lot with lot size 30:

| Entry Premium | 20% Premium Stop | Hard Stop Points | Planned Risk |
|---:|---:|---:|---:|
| ₹80 | 16 pts | 16 pts | ₹480 |
| ₹100 | 20 pts | 20 pts | ₹600 |
| ₹400 | 80 pts | 25 pts due risk cap | ₹750 |

## 0.5 Setup Risk Bands

| Setup Quality / Mode | Planned Risk |
|---|---:|
| C-grade / unclear | No trade |
| B-grade | ₹250–₹400 |
| A-grade | usually ₹500–₹750 cap; may be lower if premium stop is smaller |
| A+ grade | up to ₹1,000 max; may be lower if dynamic stop is smaller |
| Defensive mode | ₹250–₹500 |
| Survival mode | ₹0 |
| No-trade mode | ₹0 |

# 1. ContractQualityScore

Hard invalid if any:

```text
bid <= 0
ask <= 0
ask <= bid
quote_stale = true
spread_pct > hard_reject_spread_pct
absolute_spread_points > absolute_spread_cap_points
```

If hard invalid:

```text
ContractQualityScore = 0
contract_valid = false
```

Otherwise:

```text
ContractQualityScore =
  0.25 * LiquidityScore
+ 0.20 * SpreadScore
+ 0.20 * DeltaResponsivenessScore
+ 0.15 * GammaSuitabilityScore
+ 0.10 * ThetaSafetyScore
+ 0.10 * IVFairnessScore
```

All sub-scores are 0–100.

## 1.1 SpreadScore

```text
mid = (bid + ask) / 2
spread = ask - bid
spread_pct = spread / mid * 100
```

Use moneyness bucket:

- ATM: hard reject >2.0%
- ITM: hard reject >2.5%
- OTM: hard reject >4.0%

Scoring:

```text
if spread_pct <= ideal: 100
elif spread_pct <= acceptable: 70 + 30 * (acceptable - spread_pct) / (acceptable - ideal)
elif spread_pct <= reject: 70 * (reject - spread_pct) / (reject - acceptable)
else: 0
```

## 1.2 LiquidityScore

Convert quantity to lots:

```text
top_bid_lots = bid_qty / lot_size
top_ask_lots = ask_qty / lot_size
min_top_lots = min(top_bid_lots, top_ask_lots)
```

Top score:

```text
if min_top_lots >= 5: 100
elif min_top_lots >= 2: 70 + 30 * (min_top_lots - 2) / 3
elif min_top_lots >= 1: 40 + 30 * (min_top_lots - 1)
else: 0
```

Depth score if 5-depth available:

```text
cum_bid_lots = cumulative_bid_qty_5depth / lot_size
cum_ask_lots = cumulative_ask_qty_5depth / lot_size
min_depth_lots = min(cum_bid_lots, cum_ask_lots)

if min_depth_lots >= 25: 100
elif min_depth_lots >= 10: 70 + 30 * (min_depth_lots - 10) / 15
elif min_depth_lots >= 5: 40 + 30 * (min_depth_lots - 5) / 5
else: 0
```

If depth unavailable:

```text
DepthScore = TopScore * 0.8
```

Final:

```text
LiquidityScore = 0.60 * TopScore + 0.40 * DepthScore
```

## 1.3 DeltaResponsivenessScore

Use absolute delta. If Greeks unavailable, approximate by moneyness bucket.

```text
abs_delta = abs(delta)
```

Scoring:

```text
0.45 <= abs_delta <= 0.65: 100
0.35 <= abs_delta < 0.45 or 0.65 < abs_delta <= 0.75: 80
0.25 <= abs_delta < 0.35 or 0.75 < abs_delta <= 0.85: 60
0.15 <= abs_delta < 0.25: 30
abs_delta < 0.15: 0
abs_delta > 0.85: 70
```

## 1.4 GammaSuitabilityScore

MVP approximation using delta and DTE:

```text
base from abs_delta:
0.40–0.60: 100
0.30–0.70: 80
0.20–0.80: 50
else: 20
```

DTE adjustment:

```text
if expiry_day and not A+ trend/gamma-break context: cap score at 40
if DTE 1: cap score at 70
if DTE 2-7: no cap
if DTE >7: cap score at 85 for intraday momentum
```

## 1.5 ThetaSafetyScore

```text
ThetaRatio = ExpectedPremiumGainPerMinute / max(ThetaRiskPerMinute, tiny_value)
```

Scoring:

```text
ThetaRatio >= 3.0: 100
2.0 <= ThetaRatio < 3.0: 80
1.5 <= ThetaRatio < 2.0: 50
1.0 <= ThetaRatio < 1.5: 20
ThetaRatio < 1.0: 0
```

## 1.6 IVFairnessScore

Use IVCrushRiskScore:

```text
IVCrushRisk <= 30: 100
30 < IVCrushRisk <= 50: 80
50 < IVCrushRisk <= 70: 50
70 < IVCrushRisk <= 85: 20
>85: 0
```

---

# 2. FastWBCI

FastWBCI uses HDFCBANK, ICICIBANK, SBIN only.

Normalized weights:

```text
HDFCBANK: 0.393
SBIN: 0.305
ICICIBANK: 0.302
```

For each stock:

```text
FastStockScore =
0.45 * VWAPStateScore
+ 0.35 * RelativeStrength5mScore
+ 0.20 * VolumeFuturesConfirmationScore
```

FastWBCI:

```text
FastWBCI = sum(normalized_weight_i * FastStockScore_i)
```

## 2.1 VWAPStateScore

```text
vwap_diff_pct = (last_price - vwap) / vwap * 100
```

Scoring:

```text
vwap_diff_pct > 0.05 and vwap_slope_positive: +100
vwap_diff_pct > 0.05 and not vwap_slope_negative: +60
-0.05 <= vwap_diff_pct <= 0.05: 0
vwap_diff_pct < -0.05 and not vwap_slope_positive: -60
vwap_diff_pct < -0.05 and vwap_slope_negative: -100
```

## 2.2 RelativeStrength5mScore

```text
stock_ret_5m_pct = (stock_now - stock_5m_ago) / stock_5m_ago * 100
bn_ret_5m_pct = (bn_fut_now - bn_fut_5m_ago) / bn_fut_5m_ago * 100
rs = stock_ret_5m_pct - bn_ret_5m_pct
```

Scoring:

```text
rs >= +0.15: +100
+0.05 <= rs < +0.15: +60
-0.05 < rs < +0.05: 0
-0.15 < rs <= -0.05: -60
rs <= -0.15: -100
```

## 2.3 VolumeFuturesConfirmationScore

For MVP, use equity relative volume. Futures OI enhancement can be added later.

```text
stock_ret_5m_pct > 0 and rvol >= 1.5: +100
stock_ret_5m_pct > 0 and 1.0 <= rvol < 1.5: +60
abs(stock_ret_5m_pct) small or rvol unavailable: 0
stock_ret_5m_pct < 0 and 1.0 <= rvol < 1.5: -60
stock_ret_5m_pct < 0 and rvol >= 1.5: -100
```

If rvol baseline unavailable:

```text
VolumeFuturesConfirmationScore = 0
```

---

# 3. MarketHostilityScore

MarketHostilityScore is the live MVP simplification of NoTradeScore + ConflictScore.

Hard veto first. If any hard veto exists:

```text
MarketHostilityScore = 100
mode = NO_TRADE
```

Hard veto examples:

- DataHealth invalid
- Contract invalid
- daily loss hit
- no clear hard stop or required logical stop exceeds MaxAllowedRisk
- PlannedRiskRupees > MaxAllowedRisk
- IVCrushRiskScore > 85
- ExpectedMove/RequiredMove < 1.10
- PremiumElasticity < 0.50
- spread hard reject
- order rejection unresolved

If no hard veto:

```text
MarketHostilityScore =
0.20 * DataRisk
+ 0.20 * LiquidityRisk
+ 0.15 * RegimeRisk
+ 0.15 * PremiumRisk
+ 0.10 * EventGapRisk
+ 0.10 * WBCIConflictRisk
+ 0.10 * PsychologyRisk
```

All sub-scores 0–100.

## 3.1 DataRisk

```text
0 if all data fresh
40 if warning stale state
70 if multiple warnings
100 if any invalid state
```

## 3.2 LiquidityRisk

```text
0 if ContractQuality >= 85
20 if 70 <= ContractQuality < 85
50 if 60 <= ContractQuality < 70
100 if ContractQuality < 60
```

## 3.3 RegimeRisk

```text
0 if regime confidence >= 75 and tradable regime
30 if 60 <= regime confidence < 75
60 if 50 <= regime confidence < 60
100 if regime confidence < 50 or regime is hard no-trade
```

## 3.4 PremiumRisk

Use worst of elasticity/IV/required move:

```text
ElasticityRisk:
  elasticity >= 1.00: 0
  0.80 <= elasticity < 1.00: 20
  0.60 <= elasticity < 0.80: 50
  0.50 <= elasticity < 0.60: 75
  <0.50: 100

RequiredMoveRisk:
  ratio >=1.60: 0
  1.30–1.60: 20
  1.10–1.30: 70
  <1.10: 100

IVRisk:
  IVCrushRiskScore directly capped 0–100

PremiumRisk = max(ElasticityRisk, RequiredMoveRisk, IVRisk)
```

## 3.5 EventGapRisk

```text
0 normal day
20 small gap or mild event context
40 moderate gap / event within 24h
70 large gap / event same day / news shock
100 shock gap / unresolved major news
```

## 3.6 WBCIConflictRisk

```text
0 if instrument direction/leadership score supports candidate direction
25 if instrument direction/leadership score is neutral
60 if instrument direction/leadership score mildly opposes
100 if instrument direction/leadership score strongly opposes or instrument-specific heavyweight veto triggers
```

## 3.7 PsychologyRisk

```text
0 normal
30 after one loss
60 after two losses but cooldown completed
100 if cooldown active, daily loss hit, revenge/FOMO flag, or rule violation
```

## 3.8 MarketHostility Interpretation

```text
0–35: normal
35–55: defensive
55–75: survival / no new speculative risk
>75: no-trade
```

---

# 4. Per-Instrument Trade Candidate Generator

Inputs:

- DataHealth
- ContractQualityScore
- RegimeState
- RegimeConfidence
- InstrumentDirectionScore or FastWBCI for Bank Nifty
- BN futures VWAP/OR state
- PremiumElasticity
- ExpectedMove/RequiredMove
- IVCrushRiskScore
- MarketHostilityScore
- MaxAllowedRisk
- PlannedRiskRupees
- HardStopPoints
- HardStopFit

## 4.1 Algorithm

```text
if DataHealth invalid:
    output DATA_INVALID

elif risk limit breached or cooldown active:
    output NO_TRADE

elif ContractQualityScore < 60 or contract hard invalid:
    output CONTRACT_INVALID

elif MarketHostilityScore > 75:
    output NO_TRADE

elif MarketHostilityScore > 55:
    output SURVIVAL

elif RegimeConfidence < 60:
    output WAIT

elif hard_stop_fit == false:
    output AVOID

else:
    evaluate call and put candidates
```

## 4.2 Call Candidate

```text
call_ok =
InstrumentDirectionScore > +45
AND BN_futures_above_vwap_or_OR_acceptance
AND call_delta_adjusted_elasticity >= 0.80
AND ExpectedMoveRequiredRatio >= 1.30
AND IVCrushRiskScore <= 70
AND ContractQualityScore >= 70
AND MarketHostilityScore <= 55
AND hard_stop_fit == true
```

If `call_ok` and MarketHostility <=35:

```text
BUY_CALL_CANDIDATE
```

If `call_ok` and 35 < MarketHostility <=55:

```text
BUY_CALL_CANDIDATE_DEFENSIVE
```

## 4.3 Put Candidate

```text
put_ok =
InstrumentDirectionScore < -45
AND BN_futures_below_vwap_or_OR_acceptance
AND put_delta_adjusted_elasticity >= 0.80
AND ExpectedMoveRequiredRatio >= 1.30
AND IVCrushRiskScore <= 70
AND ContractQualityScore >= 70
AND MarketHostilityScore <= 55
AND hard_stop_fit == true
```

If `put_ok` and MarketHostility <=35:

```text
BUY_PUT_CANDIDATE
```

If `put_ok` and 35 < MarketHostility <=55:

```text
BUY_PUT_CANDIDATE_DEFENSIVE
```

## 4.4 If Neither Candidate Passes

```text
if direction present but premium/contract fails:
    output WAIT_OR_BAD_OPTION
elif premium good but direction absent:
    output WAIT_FOR_DIRECTION
elif regime hostile:
    output AVOID
else:
    output WAIT
```

## 4.5 A+ Candidate

A+ requires:

```text
ContractQualityScore >= 80
PremiumElasticity >= 1.00
ExpectedMoveRequiredRatio >= 1.60
abs(InstrumentDirectionScore) >= 70 in trade direction
MarketHostilityScore < 25
IVCrushRiskScore < 50
RegimeConfidence >= 75
```

A+ does not bypass hard stops or risk caps.

---

# 5. Phase 1 Multi-Instrument Opportunity Selection Engine

## Purpose

Phase 1 expands the evaluated opportunity universe but does **not** increase simultaneous exposure.

```text
Eligible instruments = BANKNIFTY, NIFTY, FINNIFTY, MIDCPNIFTY
Evaluate all.
Rank all.
Trade only the single best excellent candidate.
Maximum open positions = 1.
Maximum pending orders = 1.
No trade if none are excellent.
```

This is an opportunity-selection upgrade, not a trade-frequency upgrade.

## 5.1 Global Position Lock

Before evaluating new entries:

```text
if open_positions_count >= 1:
    block_all_new_entries = true

if pending_orders_count >= 1:
    block_all_new_entries = true
```

This rule is global across all instruments. If a Bank Nifty position exists, no Nifty, FinNifty, or Midcap Nifty entry is allowed.

## 5.2 Per-Instrument Candidate Generation

For each eligible instrument and each side, calculate:

```text
CALL_candidate_i
PUT_candidate_i
```

using the same five-gate framework:

```text
Gate 1: Data OK?
Gate 2: Contract OK?
Gate 3: Regime OK?
Gate 4: Direction + Premium OK?
Gate 5: Market Hostility OK?
```

Each candidate must calculate:

```text
DirectionScore_i
TradeQualityScore_i
ContractQualityScore_i
PremiumElasticity_i
ExpectedMoveRequiredRatio_i
IVCrushRiskScore_i
MarketHostilityScore_i
RegimeConfidence_i
HardStopFit_i
InstrumentUncertaintyPenalty_i
```

## 5.3 Excellent Candidate Gate

Phase 1 does not trade merely acceptable candidates. A candidate is eligible only if:

```text
ContractQualityScore >= 80
PremiumElasticity >= 1.00
ExpectedMoveRequiredRatio >= 1.60
MarketHostilityScore <= 35
IVCrushRiskScore <= 50
RegimeConfidence >= 75
HardStopFit == true
DataHealth == valid
```

If no candidate passes the excellent gate:

```text
NO_TRADE
```

## 5.4 OpportunityScore Formula

For candidates that pass hard gates:

```text
OpportunityScore =
  0.30 * TradeQualityScore
+ 0.20 * DirectionScore
+ 0.15 * PremiumElasticityScore
+ 0.15 * ContractQualityScore
+ 0.10 * RegimeFitScore
+ 0.10 * ExpectedMoveRequiredScore
- MarketHostilityPenalty
- InstrumentUncertaintyPenalty
- SameDirectionRecentLossPenalty
- LiquidityNotBaselinedPenalty
```

Important:

```text
OpportunityScore cannot rescue a failed hard gate.
```

## 5.5 Score Component Mappings

```text
PremiumElasticityScore:
  elasticity >= 1.20: 100
  1.00 <= elasticity < 1.20: 85
  0.80 <= elasticity < 1.00: 70
  else: failed for Phase 1 excellent gate

ExpectedMoveRequiredScore:
  ratio >= 2.00: 100
  1.60 <= ratio < 2.00: 85
  1.30 <= ratio < 1.60: 70
  else: failed for Phase 1 excellent gate

RegimeFitScore:
  tradable regime and confidence >= 80: 100
  tradable regime and confidence 75-80: 85
  tradable regime and confidence 60-75: 70
  else: failed for Phase 1 excellent gate

MarketHostilityPenalty:
  MarketHostilityScore directly subtracted at 1.0x multiplier
```

## 5.6 Instrument Uncertainty Penalty

Apply penalty when instrument-specific directional model or liquidity baseline is not fully validated.

```text
BANKNIFTY: 0 penalty after current engine validated
NIFTY: 5-10 penalty until Nifty leadership engine is validated
FINNIFTY: 5-10 penalty until FinNifty leadership engine is validated
MIDCPNIFTY: 10-15 penalty until liquidity/spread baseline is validated
```

Midcap Nifty must pass stricter liquidity validation before live eligibility.

## 5.7 Ranking Rule

After scoring all eligible candidates:

```text
Rank candidates by OpportunityScore descending.
```

Trade only the highest-ranked candidate if:

```text
OpportunityScore >= 80
AND all excellent candidate gates pass
AND global position lock is clear
AND daily/weekly/monthly risk limits allow trade
```

If the top candidate fails final validation immediately before entry:

```text
Do not automatically trade rank #2.
Recalculate all candidates first.
```

## 5.8 Tie-Break Rules

If two candidates have similar scores within 3 points:

Priority order:

```text
1. Higher ContractQualityScore
2. Higher PremiumElasticity
3. Lower MarketHostilityScore
4. Lower IVCrushRiskScore
5. Better spread/depth
6. More validated instrument
```

## 5.9 Same-Direction Recent Loss Cooldown

Even with one open position maximum, the system can still overtrade correlated instruments sequentially.

If a trade loses in one index, then another same-direction index trade appears within 30 minutes:

```text
Apply SameDirectionRecentLossPenalty = 20
```

If the new trade is not still excellent after penalty:

```text
NO_TRADE
```

## 5.10 Output States

The selection engine outputs:

```text
BEST_CANDIDATE: instrument + side + score
NO_EXCELLENT_CANDIDATE
GLOBAL_POSITION_LOCK_ACTIVE
DATA_INVALID
CONTRACT_INVALID
MARKET_HOSTILE
```


---

# 6. Phase 1 Completion Formulas

## 6.1 Generic InstrumentDirectionScore

For non-Bank-Nifty instruments, do not reuse Bank Nifty FastWBCI blindly.

```text
InstrumentDirectionScore =
  0.35 * InstrumentLeadershipScore
+ 0.30 * FuturesAuctionStructureScore
+ 0.20 * MomentumTrendEfficiencyScore
+ 0.15 * OptionsPremiumConfirmationScore
```

Use FastWBCI as `InstrumentLeadershipScore` only for Bank Nifty.

For Nifty, FinNifty, and Midcap Nifty, use instrument-specific proxies until dedicated weighted leadership engines are validated.

## 6.2 Nifty Direction Proxy

```text
NiftyStockScore_i =
  0.40 * VWAPStateScore_i
+ 0.30 * RelativeStrength5m_vs_Nifty_i
+ 0.20 * VolumeConfirmation_i
+ 0.10 * SectorContributionScore_i

NiftyLeadershipScore = sum(weight_i * NiftyStockScore_i)
```

If versioned Nifty weights are unavailable:

```text
use equal-weighted top-liquid proxy
apply InstrumentUncertaintyPenalty = 10
```

## 6.3 FinNifty Direction Proxy

```text
FinStockScore_i =
  0.40 * VWAPStateScore_i
+ 0.30 * RelativeStrength5m_vs_FinNifty_i
+ 0.20 * VolumeConfirmation_i
+ 0.10 * FinancialSubsectorConfirmation_i

FinNiftyLeadershipScore = sum(weight_i * FinStockScore_i)
```

If versioned FinNifty weights are unavailable:

```text
apply InstrumentUncertaintyPenalty = 10
```

## 6.4 Midcap Nifty Direction Proxy

```text
MidcapDirectionScore =
  0.40 * FuturesVWAP_OR_StructureScore
+ 0.25 * TrendEfficiencyScore
+ 0.20 * PremiumElasticityScoreDirectional
+ 0.15 * BroadMarketConfirmationScore
```

Until Midcap liquidity and direction are validated:

```text
InstrumentUncertaintyPenalty = 15
LiquidityNotBaselinedPenalty = 15
```

## 6.5 Per-Instrument Lot-Size Risk Formula

```text
lot_size_i = DHAN instrument master lot size for selected contract
MaxAllowedRisk_i = risk cap based on mode and instrument override
RiskCapStopPoints_i = MaxAllowedRisk_i / (lot_size_i * lots)
PremiumStopPoints_i = entry_premium_i * premium_stop_pct
HardStopPoints_i = min(point_cap_i, PremiumStopPoints_i, RiskCapStopPoints_i)
PlannedRisk_i = HardStopPoints_i * lot_size_i * lots
```

Hard rule:

```text
PlannedRisk_i <= MaxAllowedRisk_i
```

Minimum viable stop:

```text
MinimumViableStopPoints_i = max(
  2 * spread_points_i + 2 ticks,
  instrument_noise_floor_i
)
```

If:

```text
HardStopPoints_i < MinimumViableStopPoints_i
```

then:

```text
TRADE_INVALID_STOP_TOO_TIGHT
```

## 6.6 Paper-Fill Simulator

Do not use LTP fills.

Entry buy simulation:

```text
mid = (bid + ask) / 2
spread = ask - bid
slippage_buffer = max(1 tick, 0.10 * spread, instrument_slippage_baseline)
limit_price = min(ask + 1 tick, mid + 0.60 * spread)

if ask + slippage_buffer <= limit_price:
    simulated_entry = ask + slippage_buffer
else:
    simulated_entry = NO_FILL
```

Exit sell simulation:

```text
simulated_exit = bid - max(1 tick, 0.10 * spread, instrument_slippage_baseline)
```

Emergency exit simulation:

```text
emergency_slippage_buffer = max(2 ticks, 0.25 * spread, instrument_emergency_slippage_baseline)
```

## 6.7 Per-Instrument ExpectedMove

```text
RawExpectedMove_i = median(
  ATRRemainingMove_i,
  ATMStraddleImpliedMove_i,
  RegimeProjectedMove_i
)

ExpectedMove_i = RawExpectedMove_i
* InstrumentConfidenceHaircut_i
* LiquidityAdjustment_i
* GapRemainingAdjustment_i
```

Provisional confidence haircuts:

```text
BANKNIFTY: 0.85
NIFTY: 0.80
FINNIFTY: 0.75
MIDCPNIFTY: 0.65
```

Phase 1 excellent requirement:

```text
ExpectedMove_i / RequiredMove_i >= 1.60
```

Midcap provisional requirement:

```text
ExpectedMove_i / RequiredMove_i >= 1.75
```

## 6.8 Candidate Revalidation Before Order

Immediately before order entry:

```text
DataHealth still valid
selected option quote fresh
spread not expanded > 1.25 * ranking_time_spread
ContractQualityScore still >= required threshold
PremiumElasticity still valid
ExpectedMove/RequiredMove still valid
IVCrushRiskScore still below threshold
MarketHostilityScore still acceptable
global position lock clear
no pending order exists
OpportunityScore still >= 80
hard stop still fits risk cap
```

Candidate age rule:

```text
fast market: candidate age <= 5 seconds
normal market: candidate age <= 15 seconds
```

If top candidate fails:

```text
recalculate all candidates
never auto-trade rank #2
```

## 6.9 Cost / Tax Model

```text
GrossPnL = (exit_fill - entry_fill) * lot_size * lots

TotalCosts =
  brokerage
+ STT
+ exchange_transaction_charges
+ SEBI_charges
+ stamp_duty
+ GST
+ other_broker_charges
+ slippage_cost

NetPnL = GrossPnL - TotalCosts
```

All statutory and broker rates must come from configurable values and be verified weekly.

---

# 7. Final Institutional Hardening Formulas

## 7.1 Excellence Grade

```text
A+ = OpportunityScore >= 90 and all strong gates pass
A  = OpportunityScore >= 80 and all excellent gates pass
B  = 70 <= OpportunityScore < 80; watch/paper only
C  = 60 <= OpportunityScore < 70; no trade
Reject = OpportunityScore < 60 or any hard gate fail
```

Live Phase 1 trades only A or A+.

## 7.2 Dynamic Excellent Threshold

```text
DynamicExcellentThreshold = 80
+ GapPenalty
+ ExpiryPenalty
+ IVCrushPenalty
+ InstrumentValidationPenalty
+ SameDirectionRecentLossPenalty
```

Penalty values:

```text
Gap day >0.50%: +5
Expiry day: +5
IVCrushRisk 50-70: +5
Midcap unvalidated: +10
Same-direction recent loss: +10
```

The dynamic threshold can only increase strictness in Phase 1.

## 7.3 OpportunityConfidenceScore

```text
OpportunityConfidenceScore =
  0.30 * DataConfidence
+ 0.25 * CalibrationConfidence
+ 0.20 * RankStability
+ 0.15 * SignalAgreement
+ 0.10 * ExecutionConfidence
```

Rules:

```text
>=80 = high confidence
70-79 = acceptable
60-69 = watch only
<60 = reject
```

Caps:

```text
If liquidity calibration is UNVALIDATED: cap at 70
If direction calibration is UNVALIDATED: cap at 75
If both direction and liquidity are UNVALIDATED: no live trade
```

## 7.4 ConvexityQualityScore

```text
ConvexityQualityScore =
  0.30 * PremiumElasticityScore
+ 0.25 * ExpectedMoveRequiredScore
+ 0.20 * GammaSuitabilityScore
+ 0.15 * IVExpansionOrStabilityScore
+ 0.10 * TimeToProfitScore
```

Gate:

```text
ConvexityQualityScore >= 80 required for live Phase 1 trade.
```

## 7.5 ExecutionQualityScore

```text
ExecutionQualityScore =
  0.25 * SpreadStabilityScore
+ 0.20 * DepthPersistenceScore
+ 0.20 * QuoteFreshnessScore
+ 0.15 * PaperFillProbabilityScore
+ 0.10 * SlippageBaselineScore
+ 0.10 * RequoteRiskScore
```

Gate:

```text
ExecutionQualityScore >= 80
MIDCPNIFTY ExecutionQualityScore >= 85
```

## 7.6 PortfolioNoTradeScore

```text
PortfolioNoTradeScore =
  0.25 * BestCandidateWeaknessRisk
+ 0.20 * CrossInstrumentMarketHostility
+ 0.15 * DataBreadthRisk
+ 0.15 * LiquidityBreadthRisk
+ 0.10 * EventGapSystemRisk
+ 0.10 * RecentLossPsychologyRisk
+ 0.05 * CalibrationUncertaintyRisk
```

Hard no-trade if:

```text
No candidate grade >= A
Best OpportunityScore < DynamicExcellentThreshold
PortfolioNoTradeScore > 70
Broad event/tail-risk veto active
Daily risk budget insufficient
Global position lock active
Global execution reliability invalid
3 or more instruments have invalid DataHealth
Top candidate fails revalidation
Top two candidates ambiguous after tie-break
```

## 7.7 Final OpportunityScore

```text
OpportunityScore =
  0.25 * TradeQualityScore
+ 0.20 * ConvexityQualityScore
+ 0.15 * DirectionScore
+ 0.15 * ExecutionQualityScore
+ 0.10 * RegimeFitScore
+ 0.10 * OpportunityConfidenceScore
+ 0.05 * ContractQualityScore
- MarketHostilityPenalty
- InstrumentUncertaintyPenalty
- SameDirectionRecentLossPenalty
- LiquidityNotBaselinedPenalty
```

Hard rule:

```text
OpportunityScore cannot override failed gates.
```

## 7.8 Tie-Break Rule

If candidates are within 3 points:

```text
1. Higher ExecutionQualityScore
2. Higher ConvexityQualityScore
3. Higher ContractQualityScore
4. Higher PremiumElasticity
5. Lower MarketHostilityScore
6. Lower IVCrushRiskScore
7. Higher OpportunityConfidenceScore
8. More validated instrument
```

If still ambiguous:

```text
NO_TRADE
```

## 7.9 Remaining Daily Risk Budget

```text
RemainingDailyLossBudget = MaxDailyLoss - RealizedLossToday

MaxAllowedRiskForNewTrade = min(
  NormalRiskCap,
  InstrumentRiskCap,
  0.80 * RemainingDailyLossBudget
)
```

If:

```text
PlannedRisk > MaxAllowedRiskForNewTrade
```

then:

```text
TRADE_INVALID_DAILY_RISK_BUDGET
```

## 7.10 Rank Persistence

```text
A candidate must remain A or A+ for 2 consecutive ranking windows
OR be A+ with strong breakout/gap acceptance and all gates excellent.
```

If not persistent:

```text
WAIT_FOR_CONFIRMATION
```
