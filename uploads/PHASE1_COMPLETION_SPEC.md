# Phase 1 Completion Specification — Multi-Instrument Opportunity Selection

**Purpose:** Complete the remaining Phase 1 design gaps for the multi-instrument index option-buying MVP.

**Final Phase 1 universe:**

```text
BANKNIFTY
NIFTY
FINNIFTY
MIDCPNIFTY
```

**Final Phase 1 execution rule:**

```text
Evaluate all.
Rank all.
Trade only the single best excellent candidate.
Maximum open positions = 1.
Maximum pending orders = 1.
No trade if none are excellent.
```

This file is a production-specification supplement to:

- `MVP_PRODUCTION_RUNBOOK.md`
- `MVP_FORMULAS_SPEC.md`
- `PARAMETERS.json`
- `DASHBOARD_MVP_SPEC.md`
- `INSTRUMENT_MAPPING_SPEC.md`
- `JOURNAL_SCHEMA.csv`

---

## 1. Can the Bank Nifty Strategy Be Applied to Other Instruments?

### 1.1 Core Answer

Yes, the **core decision architecture** can be applied to Nifty, FinNifty, and Midcap Nifty.

The following gates are universal:

```text
DataHealth
ContractQuality
PremiumElasticity
ExpectedMove_vs_RequiredMove
IVCrushRisk
MarketHostility
HardStopFit
Gap/Open Auction rules
NoTrade rules
Manual execution rules
Dynamic risk cap
```

However, the following are **not identical** across instruments and must be instrument-specific:

```text
Direction model
Constituent leadership model
Lot size
Tick size
Expiry calendar
Normal spread/depth baseline
Premium elasticity baseline
Expected move model
Liquidity shock threshold
IV/volatility behavior
Gap behavior
Expiry pin behavior
```

### 1.2 Institutional Rule

```text
Same operating system.
Different instrument calibration.
```

Do not blindly copy Bank Nifty thresholds to other instruments without instrument-specific validation.

---

## 2. Instrument-Specific Direction Models

DirectionScore must not rely on Bank Nifty FastWBCI for every instrument.

### 2.1 Common DirectionScore Structure

For every instrument:

```text
InstrumentDirectionScore =
  0.35 × InstrumentLeadershipScore
+ 0.30 × FuturesAuctionStructureScore
+ 0.20 × MomentumTrendEfficiencyScore
+ 0.15 × OptionsPremiumConfirmationScore
```

All sub-scores range from -100 to +100.

Interpretation:

| Score | Meaning |
|---:|---|
| > +70 | Strong bullish direction |
| +45 to +70 | Bullish permission |
| -20 to +20 | Mixed / no-trade |
| -45 to -70 | Bearish permission |
| < -70 | Strong bearish direction |

A direction score can allow consideration, but it cannot override TradeQuality, ContractQuality, PremiumElasticity, IVCrushRisk, DataHealth, or MarketHostility.

---

## 3. Bank Nifty Direction Model

Bank Nifty continues to use existing FastWBCI.

```text
FastWBCI =
0.45 × Top3 VWAP State
+ 0.35 × Top3 5-minute Relative Strength
+ 0.20 × Top3 Volume/Futures Confirmation
```

Top-3:

```text
HDFCBANK
ICICIBANK
SBIN
```

Production status:

```text
ACTIVE BUT STILL PROVISIONAL UNTIL FORWARD VALIDATED
```

---

## 4. Nifty Direction Model

### 4.1 Purpose

Nifty cannot use Bank Nifty WBCI directly. It needs a broad-market leadership proxy.

### 4.2 Nifty Leadership Universe

Use versioned Nifty 50 weight data when available.

Minimum MVP proxy constituents should include the highest-weight liquid names from the current Nifty composition, typically covering:

```text
Financials
IT
Energy
FMCG / Consumption
Capital goods
Telecom
```

Do not hardcode final weights inside strategy logic. Use a versioned weight config file when available.

### 4.3 NiftyLeadershipScore Formula

For each tracked Nifty heavyweight:

```text
NiftyStockScore_i =
  0.40 × VWAPStateScore_i
+ 0.30 × RelativeStrength5m_vs_Nifty_i
+ 0.20 × VolumeConfirmation_i
+ 0.10 × SectorContributionScore_i
```

Then:

```text
NiftyLeadershipScore = Σ(weight_i × NiftyStockScore_i)
```

If official Nifty weights are unavailable:

```text
Use equal-weighted top-liquid proxy
AND apply InstrumentUncertaintyPenalty = 10
```

### 4.4 Nifty Heavyweight Veto

No aggressive Nifty call if:

```text
top weighted Nifty constituents by configured weight are net negative
AND Nifty futures move is unsupported by premium elasticity
```

No aggressive Nifty put if:

```text
top weighted Nifty constituents are net positive
AND put premium elasticity is weak
```

### 4.5 Nifty Direction Status

```text
NIFTY direction model = PHASE 1 PROXY until weight file and replay validation exist.
```

---

## 5. FinNifty Direction Model

### 5.1 Purpose

FinNifty is a financial-sector index and is highly correlated with Bank Nifty, but it may offer cleaner financial-sector expression on some days.

### 5.2 FinNifty Leadership Universe

Use versioned FinNifty weight data when available.

The model should include banks, NBFCs, insurance, and other financial-services heavyweights.

Until official weights are configured, use a provisional financial proxy and apply uncertainty penalty.

### 5.3 FinNiftyLeadershipScore Formula

For each tracked FinNifty heavyweight:

```text
FinStockScore_i =
  0.40 × VWAPStateScore_i
+ 0.30 × RelativeStrength5m_vs_FinNifty_i
+ 0.20 × VolumeConfirmation_i
+ 0.10 × FinancialSubsectorConfirmation_i
```

Then:

```text
FinNiftyLeadershipScore = Σ(weight_i × FinStockScore_i)
```

### 5.4 FinNifty vs Bank Nifty Conflict Check

Because FinNifty and Bank Nifty are highly correlated:

```text
If FinNifty signal conflicts with Bank Nifty financial leadership,
apply ConflictPenalty = 10 to 20.
```

If FinNifty premium is strong but financial heavyweights are mixed:

```text
WAIT unless TradeQuality is exceptional.
```

### 5.5 FinNifty Direction Status

```text
FINNIFTY direction model = PHASE 1 PROXY until constituent weights and liquidity baselines are validated.
```

---

## 6. Midcap Nifty Direction Model

### 6.1 Purpose

Midcap Nifty may offer high-beta opportunities, but it carries greater liquidity and execution uncertainty.

### 6.2 MVP Direction Model

Until a constituent-weight engine exists, use a price/futures/regime proxy:

```text
MidcapDirectionScore =
  0.40 × FuturesVWAP_OR_StructureScore
+ 0.25 × TrendEfficiencyScore
+ 0.20 × PremiumElasticityScoreDirectional
+ 0.15 × BroadMarketConfirmationScore
```

### 6.3 Mandatory Midcap Penalty

Until at least 20 trading days of liquidity/spread data exist:

```text
InstrumentUncertaintyPenalty = 10 to 15
LiquidityNotBaselinedPenalty = 15
```

### 6.4 Midcap Live Eligibility

Midcap Nifty may enter live ranking only if:

```text
ContractQualityScore >= 85
PremiumElasticity >= 1.10
ExpectedMove/RequiredMove >= 1.75
MarketHostilityScore <= 30
Spread <= excellent threshold
Depth is stable
Quote freshness is excellent
```

If these fail:

```text
MIDCPNIFTY = monitor-only / excluded from trade selection
```

---

## 7. Midcap Nifty Liquidity Baseline

### 7.1 Baseline Collection Requirement

Before Midcap Nifty can be treated as fully eligible:

```text
Minimum baseline = 20 trading days
Minimum candidate observations = 100 ranking cycles
Minimum excellent-candidate observations = 20
```

Track by time of day:

- bid/ask spread percentage,
- absolute spread points,
- top-book lots,
- 5-depth lots,
- quote update frequency,
- stale quote events,
- slippage simulation,
- premium elasticity stability,
- no-bid events,
- fillability in paper mode.

### 7.2 Midcap Baseline Passing Criteria

Midcap passes liquidity baseline only if:

```text
>= 95% of observed active candidate windows have valid bid/ask
median spread_pct is within acceptable band
no repeated no-bid events in ATM/near-ATM strikes
paper-fill slippage is not materially worse than Nifty/BankNifty
quote freshness is stable during tradable windows
```

Until then:

```text
Midcap Nifty remains conditional.
```

---

## 8. Per-Instrument Lot-Size Risk Handling

### 8.1 Rule

Never use Bank Nifty lot size for all instruments.

For every candidate:

```text
lot_size_i = DHAN instrument master lot size for selected contract
```

### 8.2 Dynamic Risk Formula

```text
MaxAllowedRisk_i = risk cap based on mode and instrument override
RiskCapStopPoints_i = MaxAllowedRisk_i / (lot_size_i × lots)
PremiumStopPoints_i = entry_premium_i × premium_stop_pct
HardStopPoints_i = min(point_cap_i, PremiumStopPoints_i, RiskCapStopPoints_i)
PlannedRisk_i = HardStopPoints_i × lot_size_i × lots
```

Hard rule:

```text
PlannedRisk_i <= MaxAllowedRisk_i
```

### 8.3 Minimum Viable Stop Rule

A stop can be too tight to be executable.

```text
MinimumViableStopPoints_i = max(
  2 × spread_points_i + 2 ticks,
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

This prevents entering high-premium or noisy contracts where the risk cap creates an unrealistic stop.

---

## 9. Paper-Fill Simulator

### 9.1 Purpose

Paper trading must not assume fills at LTP or mid-price.

Use conservative bid/ask-based simulated fills.

### 9.2 Entry Fill for Long Option Buy

```text
mid = (bid + ask) / 2
spread = ask - bid
slippage_buffer = max(1 tick, 0.10 × spread, instrument_slippage_baseline)
limit_price = min(ask + 1 tick, mid + 0.60 × spread)
```

Simulated fill:

```text
if ask + slippage_buffer <= limit_price:
    simulated_entry = ask + slippage_buffer
else:
    simulated_entry = NO_FILL
```

### 9.3 Exit Fill for Long Option Sell

```text
simulated_exit = bid - max(1 tick, 0.10 × spread, instrument_slippage_baseline)
```

If simulated exit <= 0:

```text
contract_exit_quality = invalid
```

### 9.4 Emergency Exit Simulation

Emergency exits use a wider slippage assumption:

```text
emergency_slippage_buffer = max(2 ticks, 0.25 × spread, instrument_emergency_slippage_baseline)
```

### 9.5 Paper-Fill Rule

```text
Paper P&L must be calculated using simulated bid/ask fills, not LTP.
```

---

## 10. Per-Instrument ExpectedMove Model

### 10.1 Purpose

Expected move must be calculated separately for each index.

Do not use Bank Nifty volatility assumptions for Nifty, FinNifty, or Midcap Nifty.

### 10.2 Inputs

For each instrument:

```text
ATRRemainingMove_i
ATMStraddleImpliedMove_i
RegimeProjectedMove_i
OpeningRangeProjectedMove_i
GapConsumedMove_i
LiquidityAdjustment_i
InstrumentConfidenceHaircut_i
```

### 10.3 Conservative MVP Formula

```text
RawExpectedMove_i = median(
  ATRRemainingMove_i,
  ATMStraddleImpliedMove_i,
  RegimeProjectedMove_i
)
```

Then apply haircuts:

```text
ExpectedMove_i = RawExpectedMove_i
× InstrumentConfidenceHaircut_i
× LiquidityAdjustment_i
× GapRemainingAdjustment_i
```

Suggested provisional haircuts:

| Instrument | Confidence Haircut Until Validated |
|---|---:|
| BANKNIFTY | 0.85 |
| NIFTY | 0.80 |
| FINNIFTY | 0.75 |
| MIDCPNIFTY | 0.65 |

These are conservative and must be calibrated.

### 10.4 ExpectedMove Gate

Phase 1 excellent candidate requires:

```text
ExpectedMove_i / RequiredMove_i >= 1.60
```

Midcap Nifty provisional requirement:

```text
ExpectedMove_i / RequiredMove_i >= 1.75
```

---

## 11. Cost / Tax / Charges Calculator

### 11.1 Purpose

Gross P&L is not valid. All performance must be net of costs.

### 11.2 Formula

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

### 11.3 Config Rule

Do not hardcode statutory rates in strategy logic.

```text
All rates must be stored in a charges config and verified weekly.
```

The config should include:

- brokerage per order,
- STT rule for option sell side / exercise if applicable,
- exchange transaction charge rate,
- SEBI fee rate,
- stamp duty rate,
- GST rate,
- any broker platform charges.

### 11.4 Performance Rule

```text
Only net P&L after costs is valid for expectancy, profit factor, drawdown, and ROI review.
```

---

## 12. Candidate Revalidation Before Order

### 12.1 Purpose

Candidate ranking can become stale within seconds.

### 12.2 Mandatory Final Revalidation

Immediately before manual order entry, re-check:

```text
DataHealth still valid
selected option quote fresh
spread not expanded > 1.25 × ranking-time spread
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

### 12.3 Candidate Age Rule

```text
If candidate age > 5 seconds during fast market:
    revalidate before order

If candidate age > 15 seconds in normal market:
    revalidate before order
```

### 12.4 Rank Failure Rule

If top-ranked candidate fails final revalidation:

```text
Do not automatically trade rank #2.
Recalculate all candidates.
```

---

## 13. Skipped-Candidate Journal

### 13.1 Purpose

The system must learn whether filters are too strict or correctly blocking bad trades.

### 13.2 What to Log

For every ranking cycle with at least one near-candidate:

```text
timestamp
underlying
option_type
rank
OpportunityScore
DirectionScore
TradeQualityScore
ContractQualityScore
PremiumElasticity
ExpectedMoveRequiredRatio
IVCrushRiskScore
MarketHostilityScore
veto_reason
why_not_traded
subsequent_5m_MFE
subsequent_5m_MAE
subsequent_15m_MFE
subsequent_15m_MAE
subsequent_30m_MFE
subsequent_30m_MAE
would_have_hit_target
would_have_hit_stop
notes
```

### 13.3 Review Rule

Do not loosen filters because of one missed winner.

```text
Review skipped candidates only after meaningful sample size.
```

---

## 14. Phase 1 Dry-Run Acceptance Criteria

Phase 1 must complete dry-run validation before live trading.

### 14.1 Minimum Data Capture

```text
Minimum 20 trading days of multi-instrument data capture
Minimum 100 ranking cycles
Minimum 50 paper/simulated trade candidates
```

### 14.2 Operational Pass Criteria

```text
0 critical instrument mapping errors in final 5 dry-run days
0 wrong lot-size risk calculations
0 wrong tick-size order-price calculations
>= 95% dashboard ranking cycles update within acceptable latency
All emergency tests pass
Global position lock tested and working
Candidate revalidation tested and working
Paper-fill simulator active
Journal logs complete
```

### 14.3 Trading Quality Pass Criteria

Before live deployment:

```text
No evidence of systematic bad ranking
No evidence of Midcap liquidity failure if Midcap is live-enabled
Simulated fills use bid/ask and costs
Net paper expectancy not materially negative after costs
No major rule-violation workflow issue
```

### 14.4 Live Go/No-Go Rule

```text
If any critical dry-run criterion fails:
    NO LIVE TRADING
```

---

## 15. Per-Instrument Calibration Plan

Each instrument must track:

```text
spread baseline
depth baseline
quote freshness baseline
premium elasticity baseline
expected move accuracy
IV crush behavior
gap behavior
expiry-day behavior
slippage simulation error
ranking outcome attribution
```

### Calibration Status Labels

```text
UNVALIDATED
OBSERVED
VALIDATED
DEGRADED
RETIRED
```

Until validated:

```text
apply InstrumentUncertaintyPenalty
```

---

## 16. False Confidence Controls

### 16.1 Problem

Multi-instrument ranking can look precise before the underlying models are validated.

### 16.2 Controls

```text
Display score bands, not false precision.
Show calibration status per instrument.
Apply uncertainty penalties.
Require excellent gate.
Keep max open positions = 1.
Do not auto-trade.
Do not trade rank #2 without recalculation.
Keep Midcap conditional until liquidity baseline passes.
```

---

## 17. Complex Feature Retention Rule

Do not delete complex ideas if they may improve the system later.

Classify them correctly:

| Feature | Status |
|---|---|
| Stock option chains | Future enrichment / research, not Phase 1 gate |
| GEX | Research / context, not Phase 1 gate |
| CVD / order flow | Research until DHAN inference is validated |
| 20-depth | Later liquidity research |
| Sector indices | Future expansion only after Phase 1 validation |
| AI | Later classifier / summarizer after data exists |

Rule:

```text
Retain useful complexity as research.
Do not promote it to production gate until validated.
```

---

## 18. Final Phase 1 Completion Doctrine

```text
The Bank Nifty operating system can be generalized to other index options at the gate level.
It cannot be blindly generalized at the direction-model, liquidity, expected-move, or lot-size level.
```

Final implementation doctrine:

```text
Same survival gates.
Same no-trade philosophy.
Same dynamic risk cap.
Same contract-quality discipline.
Same premium-elasticity discipline.
Different instrument calibration.
```
