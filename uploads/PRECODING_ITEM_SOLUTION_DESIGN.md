# Pre-Coding Item Solution Design

**Perspective:** Billion-dollar hedge-fund investment committee, institutional options portfolio manager, quantitative trading architect, risk committee, and survivability-focused systems reviewer.

**Purpose:** Convert all remaining pre-coding items into clear institutional solution designs so implementation can begin without ambiguity.

**Scope:** This is not a coding document. It defines the trading, risk, validation, and roadmap treatment for each item.

---

## 0. Final Implementation Boundary

The approved first build is:

```text
Phase 1 Paper-Mode / Dry-Run / MTIL-Functional Opportunity Ranking System
```

Allowed:

```text
Data capture
Paper ranking
Simulated entries/exits
MTIL logging
Skipped-candidate logging
Paper-fill simulation
Performance analytics
Dry-run dashboard
```

Not allowed in MVP:

```text
Live execution
Auto trading
Real broker order placement
Multi-position mode
Leverage
Option selling
B-grade trades
Rank #2 auto-switch
```

---

# 1. Instrument Mapping, Lot-Size/Tick-Size Validation, MTIL Logging, Paper-Fill Simulator

## Institutional Problem

Wrong instrument mapping, wrong lot size, wrong tick size, unrealistic paper fills, or incomplete logging can invalidate all downstream performance analysis.

## Solution Design

### 1.1 Instrument Mapping

For every candidate instrument:

```text
BANKNIFTY
NIFTY
FINNIFTY
MIDCPNIFTY
```

The system must map from DHAN instrument master:

```text
underlying_symbol
instrument_type
expiry
strike
option_type
security_id
lot_size
tick_size
freeze_qty
buy_sell_indicator
```

### 1.2 Hard Veto

```text
If mapping missing, stale, duplicated, inconsistent, or lot/tick invalid:
    candidate cannot enter ranking.
```

### 1.3 Lot-Size Risk Formula

```text
lot_size_i = instrument_master_lot_size
RiskCapStopPoints_i = MaxAllowedRisk_i / (lot_size_i × lots)
PlannedRisk_i = HardStopPoints_i × lot_size_i × lots
```

### 1.4 Tick-Size Rule

```text
All simulated limit prices must be rounded to valid tick increments.
```

### 1.5 MTIL Logging Rule

Every ranking cycle must log:

```text
all candidates
all rejected candidates
best candidate
reason traded / reason no-trade
simulated entry
simulated exit
P&L / R / ROI
all scores
all vetoes
```

### 1.6 Paper-Fill Simulator

No LTP fills.

Entry:

```text
mid = (bid + ask) / 2
spread = ask - bid
slippage_buffer = max(1 tick, 0.10 × spread, instrument_slippage_baseline)
limit_price = min(ask + 1 tick, mid + 0.60 × spread)

if ask + slippage_buffer <= limit_price:
    simulated_entry = ask + slippage_buffer
else:
    simulated_entry = NO_FILL
```

Exit:

```text
simulated_exit = bid - max(1 tick, 0.10 × spread, instrument_slippage_baseline)
```

## Status

```text
MVP CRITICAL — must be built first.
```

---

# 2. Cost Model

## Institutional Problem

Gross P&L overstates edge. Option systems die through spread, slippage, brokerage, taxes, and fees.

## Solution Design

```text
GrossPnL = (exit_fill - entry_fill) × lot_size × lots
```

```text
TotalCosts =
  brokerage
+ STT
+ exchange_transaction_charges
+ SEBI_charges
+ stamp_duty
+ GST
+ other_broker_charges
+ slippage_cost
```

```text
NetPnL = GrossPnL - TotalCosts
```

## Institutional Rule

```text
Only net P&L is valid for expectancy, ROI, drawdown, profit factor, and strategy review.
```

## Status

```text
MVP CRITICAL — formula ready; actual rates must be configurable and verified weekly.
```

---

# 3. Nifty Direction Model

## Institutional Problem

Bank Nifty FastWBCI cannot be reused for Nifty. Nifty requires broad-market leadership.

## Solution Design

```text
NiftyStockScore_i =
  0.40 × VWAPStateScore_i
+ 0.30 × RelativeStrength5m_vs_Nifty_i
+ 0.20 × VolumeConfirmation_i
+ 0.10 × SectorContributionScore_i
```

```text
NiftyLeadershipScore = Σ(weight_i × NiftyStockScore_i)
```

If versioned weights unavailable:

```text
Use top-liquid proxy
Apply InstrumentUncertaintyPenalty = 10
No A+ grade until validated
```

## Initial Leadership Universe

Use current top-weight / high-liquidity Nifty constituents when weight config is created, including financials, IT, energy, FMCG/consumption, telecom, and capital goods.

## Status

```text
PARTIALLY READY — proxy allowed for paper mode; live authority requires validation.
```

---

# 4. FinNifty Direction Model

## Institutional Problem

FinNifty overlaps with financials but is not identical to Bank Nifty. It needs its own financial-sector leadership model.

## Solution Design

```text
FinStockScore_i =
  0.40 × VWAPStateScore_i
+ 0.30 × RelativeStrength5m_vs_FinNifty_i
+ 0.20 × VolumeConfirmation_i
+ 0.10 × FinancialSubsectorConfirmation_i
```

```text
FinNiftyLeadershipScore = Σ(weight_i × FinStockScore_i)
```

Conflict penalty:

```text
If FinNifty signal conflicts with Bank Nifty financial leadership:
    ConflictPenalty = 10 to 20
```

## Status

```text
PARTIALLY READY — proxy allowed in paper; live authority requires validation.
```

---

# 5. Midcap Nifty

## Institutional Problem

Midcap Nifty may offer convexity but has higher liquidity and execution uncertainty.

## Solution Design

Default status:

```text
MIDCPNIFTY = MONITOR_ONLY
```

Live eligibility requires:

```text
20 trading days baseline
100 ranking cycles
20 excellent candidate observations
ContractQualityScore >= 85
PremiumElasticity >= 1.10
ExpectedMove/RequiredMove >= 1.75
MarketHostilityScore <= 30
ExecutionQualityScore >= 85
stable quote freshness
no repeated no-bid events
```

## Status

```text
MONITOR-ONLY until baseline passes.
```

---

# 6. AI Layer / AI Forecasting Research Layer

## Institutional Problem

AI can create false confidence if given trading authority before validation.

## Solution Design

AI may research:

```text
regime probability
forecast realized volatility
uncertainty bands
anomaly detection
no-trade probability
EV input improvement
VolEdge improvement
edge decay detection
```

AI may not:

```text
trigger trades
place orders
size positions
select strikes as sole authority
override risk gates
replace OpportunityScore
```

Verified-model candidates only:

```text
Moirai / Moirai-2
Kronos
TimeGPT
Chronos
TimesFM
```

## Status

```text
POST-MVP RESEARCH ONLY.
```

---

# 7. GEX Research

## Institutional Problem

GEX can help identify pin/release zones, but public OI cannot reveal actual dealer books.

## Solution Design

Use as scenario estimate only:

```text
GEX_SCENARIO_ESTIMATE = OI × Gamma × ContractMultiplier × Spot² × 0.01
```

Allowed use:

```text
research
context
pin/release awareness
post-trade attribution
```

Forbidden use:

```text
trade trigger
position sizing
hard gate
claim of dealer certainty
```

## Status

```text
RESEARCH ONLY UNTIL VALIDATED.
```

---

# 8. CVD / Order-Flow Research

## Institutional Problem

Retail/broker feed CVD may be inferred and unreliable.

## Solution Design

Use only after validation:

```text
ApproxAggressorFlow = trade_price_vs_bid_ask_mid
```

Allowed:

```text
research
secondary confirmation
post-trade analysis
```

Forbidden in MVP:

```text
production gate
entry trigger
override of premium/contract/risk gates
```

## Status

```text
RESEARCH ONLY.
```

---

# 9. Stock Option-Chain Enrichment

## Institutional Problem

Stock option chains may improve WBCI/leadership confirmation, but they add complexity and noise.

## Solution Design

Future enrichment only:

```text
Tier 1: HDFCBANK, ICICIBANK, SBIN
Tier 2 later: AXISBANK, KOTAKBANK
```

Use for:

```text
confirmation
divergence
WBCI enrichment
```

Cannot:

```text
trigger index option trades alone
override Bank/Nifty/FinNifty premium failure
override contract quality
```

## Status

```text
POST-MVP RESEARCH / ENRICHMENT.
```

---

# 10. Sector Index Expansion

## Institutional Problem

Sector indices can add opportunities but also add complexity, liquidity issues, and overtrading risk.

## Solution Design

No sector expansion in MVP.

Future inclusion requires:

```text
instrument liquidity baseline
spread stability
option volume and OI quality
direction model
expected move model
contract quality baseline
positive paper expectancy
```

## Status

```text
DEFER UNTIL PHASE 1 VALIDATED.
```

---

# 11. Dynamic Threshold Optimization

## Institutional Problem

Dynamic threshold optimization can overfit if done too early.

## Solution Design

Allowed only after:

```text
100+ simulated candidates
50+ paper trades
regime segmentation
net cost-adjusted results
no small-sample changes
```

Rule:

```text
Thresholds may only be tightened before validation.
Do not loosen thresholds during dry-run.
```

## Status

```text
POST-DATA CALIBRATION ONLY.
```

---

# 12. OpportunityScore

## Institutional Problem

OpportunityScore can create false precision if used alone.

## Solution Design

Use final formula:

```text
OpportunityScore =
  0.25 × TradeQualityScore
+ 0.20 × ConvexityQualityScore
+ 0.15 × DirectionScore
+ 0.15 × ExecutionQualityScore
+ 0.10 × RegimeFitScore
+ 0.10 × OpportunityConfidenceScore
+ 0.05 × ContractQualityScore
- penalties
```

Hard rule:

```text
OpportunityScore cannot override failed hard gates.
```

## Status

```text
READY FOR PAPER MODE.
```

---

# 13. ExpectedValue_R

## Institutional Problem

Score quality is not expectancy.

## Solution Design

```text
ExpectedValue_R =
  (WinProbability × AvgWin_R)
- (LossProbability × AvgLoss_R)
- Cost_R
- Slippage_R
- ThetaRisk_R
- IVCrushRisk_R
```

Thresholds:

```text
>= 0.30R live-quality candidate
>= 0.75R A+
<= 0 reject
```

## Status

```text
READY FOR PAPER MODE WITH CONSERVATIVE PROBABILITIES.
```

---

# 14. VolEdgeRatio

## Institutional Problem

Option buying requires realized movement to exceed required movement.

## Solution Design

```text
VolEdgeRatio = ForecastRealizedMove / RequiredMove
```

Thresholds:

```text
>= 1.60 live-quality
>= 2.00 A+
< 1.30 reject/paper-only
```

## Status

```text
READY FOR PAPER MODE; CALIBRATE BY INSTRUMENT.
```

---

# 15. ConvexityEdgeScore

## Institutional Problem

Direction can be right while convexity is poor.

## Solution Design

```text
ConvexityEdgeScore =
  0.30 × PremiumElasticityScore
+ 0.25 × GammaUsefulnessScore
+ 0.20 × ExpectedAccelerationScore
+ 0.15 × IVSupportScore
+ 0.10 × TimeToProfitQualityScore
```

Thresholds:

```text
>= 80 required
>= 90 A+
< 70 reject
```

## Status

```text
READY FOR PAPER MODE.
```

---

# 16. ExecutionQualityScore

## Institutional Problem

Theoretical edge fails if execution quality is poor.

## Solution Design

```text
ExecutionQualityScore =
  0.25 × SpreadStabilityScore
+ 0.20 × DepthPersistenceScore
+ 0.20 × QuoteFreshnessScore
+ 0.15 × PaperFillProbabilityScore
+ 0.10 × SlippageBaselineScore
+ 0.10 × RequoteRiskScore
```

Thresholds:

```text
>= 80 required
MIDCPNIFTY >= 85
```

## Status

```text
READY FOR PAPER MODE.
```

---

# 17. PremiumElasticity

## Institutional Problem

Option premium must respond to underlying movement.

## Solution Design

```text
DeltaAdjustedElasticity = ΔOptionMid / (abs(ΔFutures) × abs(delta))
```

Thresholds:

```text
>= 0.80 minimum
>= 1.00 excellent
< 0.50 reject/exit warning
```

## Status

```text
READY.
```

---

# 18. MarketHostilityScore

## Institutional Problem

Market conditions can be hostile even if one candidate looks attractive.

## Solution Design

Use existing weighted risk score with additions from global/news/liquidity/drawdown.

Thresholds:

```text
<=35 live-quality
35-55 defensive/watch only in Phase 1
>55 survival/no trade
>75 hard no-trade
```

## Status

```text
READY.
```

---

# 19. PortfolioNoTradeScore

## Institutional Problem

The best of weak candidates should still be no-trade.

## Solution Design

```text
PortfolioNoTradeScore =
  0.25 × BestCandidateWeaknessRisk
+ 0.20 × CrossInstrumentMarketHostility
+ 0.15 × DataBreadthRisk
+ 0.15 × LiquidityBreadthRisk
+ 0.10 × EventGapSystemRisk
+ 0.10 × RecentLossPsychologyRisk
+ 0.05 × CalibrationUncertaintyRisk
```

Thresholds:

```text
>70 hard no-trade
50-70 no live trade unless A+ and no systemic risk
```

## Status

```text
READY.
```

---

# 20. IVCrushRiskScore

## Institutional Problem

IV crush can destroy long option trades.

## Solution Design

Use existing IVCrushRisk model.

Thresholds:

```text
<=50 excellent candidate
50-70 penalty / stricter threshold
70-85 no new long unless realized move dominates
>85 hard no-trade
```

## Status

```text
READY.
```

---

# 21. Midcap Liquidity Thresholds

## Institutional Problem

Midcap Nifty may be less liquid and more fragile.

## Solution Design

Midcap remains monitor-only until baseline passes.

Live criteria:

```text
ContractQualityScore >= 85
ExecutionQualityScore >= 85
PremiumElasticity >= 1.10
ExpectedMove/RequiredMove >= 1.75
MarketHostilityScore <= 30
stable quote freshness
no repeated no-bid events
```

## Status

```text
MONITOR-ONLY UNTIL VALIDATED.
```

---

# 22. Nifty Weighted Leadership Model

## Institutional Problem

Nifty needs its own leadership model.

## Solution Design

```text
NiftyLeadershipScore = Σ(weight_i × NiftyStockScore_i)
```

```text
NiftyStockScore_i =
0.40 × VWAPState
+ 0.30 × RS5m_vs_Nifty
+ 0.20 × VolumeConfirmation
+ 0.10 × SectorContribution
```

## Status

```text
PROXY READY FOR PAPER; WEIGHT FILE NEEDED FOR VALIDATION.
```

---

# 23. FinNifty Weighted Leadership Model

## Institutional Problem

FinNifty requires financial-sector leadership beyond Bank Nifty.

## Solution Design

```text
FinNiftyLeadershipScore = Σ(weight_i × FinStockScore_i)
```

```text
FinStockScore_i =
0.40 × VWAPState
+ 0.30 × RS5m_vs_FinNifty
+ 0.20 × VolumeConfirmation
+ 0.10 × FinancialSubsectorConfirmation
```

## Status

```text
PROXY READY FOR PAPER; WEIGHT FILE NEEDED FOR VALIDATION.
```

---

# 24. Midcap Nifty Direction Model

## Institutional Problem

Midcap direction is harder without reliable constituent leadership and liquidity.

## Solution Design

```text
MidcapDirectionScore =
0.40 × FuturesVWAP_OR_StructureScore
+ 0.25 × TrendEfficiencyScore
+ 0.20 × PremiumElasticityScoreDirectional
+ 0.15 × BroadMarketConfirmationScore
```

## Status

```text
MONITOR/PAPER ONLY UNTIL VALIDATED.
```

---

# 25. Exact Probability Inputs for EV

## Institutional Problem

EV requires win probability estimates, but false precision is dangerous.

## Solution Design

Initial conservative mapping:

```text
A+ = 0.55 base win probability
A  = 0.48 base win probability
B  = 0.42 paper only
C/Reject = no trade
```

Adjustments:

```text
+0.03 ForcedFlow >=85
+0.03 ConvexityEdge >=90
+0.02 LiquidityVacuum >=80
-0.05 unvalidated instrument
-0.05 same-direction recent loss
-0.05 global risk-off without Indian acceptance
```

Cap:

```text
WinProbability cannot exceed 0.62 in paper/MVP phase.
```

## Status

```text
READY FOR PAPER, PROVISIONAL.
```

---

# 26. Instrument-Specific Spread Baselines

## Institutional Problem

Spread norms differ by instrument.

## Solution Design

Track per instrument/time window:

```text
median spread %
median absolute spread
95th percentile spread
spread stability
spread shock frequency
```

Initial thresholds:

```text
BANKNIFTY excellent <=1.5%, reject >2.0%
NIFTY excellent <=1.0%, reject >1.5%
FINNIFTY excellent <=1.5%, reject >2.5%
MIDCPNIFTY excellent <=1.25%, reject >2.0%
```

## Status

```text
READY FOR BASELINE COLLECTION.
```

---

# 27. Instrument-Specific Slippage Baselines

## Institutional Problem

Expected slippage must be instrument-specific.

## Solution Design

Track:

```text
simulated entry slippage
simulated exit slippage
spread fraction paid
no-fill frequency
requote frequency
emergency exit slippage
```

Use in:

```text
ExecutionQualityScore
ExpectedValue_R
Paper-fill simulator
```

## Status

```text
READY FOR PAPER COLLECTION.
```

---

# 28. Ambiguous Logic

## Institutional Problem

Ambiguity creates inconsistent implementation.

## Final Resolution

```text
If a metric is unavailable:
    mark UNAVAILABLE / UNVALIDATED
    apply penalty or cap
    do not fake value
    do not allow it to approve trade
```

```text
Hard gates dominate all scores.
No score can rescue a failed gate.
```

## Status

```text
RESOLVED.
```

---

# 29. Items To Freeze Before Coding

Freeze:

```text
Universe = BANKNIFTY, NIFTY, FINNIFTY, MIDCPNIFTY
Max open positions = 1
Max pending orders = 1
No live orders
No auto-execution
No leverage
No pledge
No overnight
No option selling
No B-grade live trades
No rank #2 auto-switch
No new instruments during MVP
No threshold lowering during dry-run
```

## Status

```text
FROZEN.
```

---

# 30. Recommended MVP Scope

## Institutional Solution

Build only:

```text
Instrument master loader
Per-instrument mapping
Lot/tick validation
Data capture
Candidate generator
Paper-fill simulator
Opportunity ranking
Candidate grading
Portfolio no-trade engine
Candidate revalidation
Simulated entry/exit
MTIL logging
Skipped-candidate logging
Dry-run dashboard
Performance analytics
```

## Status

```text
MVP SCOPE FROZEN.
```

---

# 31. Deferred / Rejected For MVP Items

## AI

```text
Research roadmap only; no MVP authority.
```

## GEX

```text
Research/context only; no gate.
```

## CVD

```text
Research only until validated.
```

## Stock Option Chains

```text
Future enrichment; not MVP gate.
```

## 20-depth

```text
Later liquidity research; not MVP.
```

## Dynamic Threshold Optimization

```text
Post-data calibration only.
```

## Live Execution

```text
NO-GO until dry-run passes.
```

## Broker Switching

```text
Post-DHAN MVP stability only.
```

## Multi-Position Mode

```text
Rejected for Phase 1.
```

---

# Final Investment Committee Verdict

The specification is complete enough to code the paper-mode system.

The first implementation must be:

```text
non-live
paper-mode
MTIL-functional
dry-run validated
strictly one-position architecture
```

Final rule:

```text
Build evidence first.
Trade capital later.
```
