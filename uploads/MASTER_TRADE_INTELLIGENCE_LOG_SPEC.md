# Master Trade Intelligence Log (MTIL) Specification

**Purpose:** Create an institutional-grade Trade Intelligence Log / Trade Intelligence Database for continuous strategy evolution and alpha discovery.

This is not a simple trade journal.

```text
A journal records what happened.
MTIL explains why it happened, what conditions existed, what signals were active,
which opportunity cluster it belonged to, and what should be changed after enough evidence.
```

---

## 1. Deliverables

This MTIL specification creates three core artifacts:

```text
MASTER_TRADE_INTELLIGENCE_LOG_SPEC.md
MTIL_SCHEMA.csv
TRADE_ARCHETYPE_SCHEMA.csv
```

`MTIL_SCHEMA.csv` contains the complete database schema with:

- section,
- field name,
- data type,
- required flag,
- alpha value rating,
- survivability value rating,
- ROI optimization value rating,
- description.

`TRADE_ARCHETYPE_SCHEMA.csv` contains standardized archetype codes.

---

## 2. Design Philosophy

The MTIL must answer, after 100 / 500 / 1,000 / 5,000 trades:

```text
Which instruments work?
Which regimes work?
Which signals work?
Which signal combinations work?
Which setups fail?
Which exits add or destroy value?
Which conditions should be no-trade?
Which opportunity clusters create alpha?
Which filters saved drawdown?
```

The highest-value output is not P&L tracking.

The highest-value output is:

```text
evidence-based strategy evolution.
```

---

## 3. MTIL Core Sections

The full schema is stored in `MTIL_SCHEMA.csv` and contains 281 fields across 18 sections:

1. Trade Identity
2. Entry Data
3. Exit Data
4. Trade Result Data
5. Opportunity Quality Data
6. Market Regime Data
7. Gap Data
8. Global Market Data
9. Option Chain Data
10. Futures Data
11. Premium Elasticity Data
12. Liquidity / Execution Data
13. Technical Context
14. Event / News Data
15. Behavioral / Positioning Data
16. Trade Management Data
17. Post-Trade Analysis
18. Alpha Discovery

---

## 4. Highest Alpha-Value Fields

The fields most likely to discover future hidden alpha are:

```text
trade_archetype_code
signal_combination_id
regime_combination_id
opportunity_cluster_id
OpportunityScore
ComparableOpportunityScore
ExpectedValue_R
VolEdgeRatio
ConvexityEdgeScore
ForcedFlowScore
LiquidityVacuumScore
RangeExpansionQuality
DirectionalOptionBreadthScore
PremiumDominanceRatio
SetupSpecificExpectancy
InstrumentEdgeAttributionScore
historical_expectancy_r
historical_profit_factor
edge_decay_score
setup_category
setup_subcategory
```

These fields allow discovery of patterns such as:

```text
A04 + RiskOffPutAcceleration + HighIVValidation + Nifty
= positive expectancy
```

or:

```text
A07 + GapUp + LowVol + Midcap
= negative expectancy
```

---

## 5. Highest Survivability-Value Fields

The most important survivability fields are:

```text
risk_mode
MarketHostilityScore
PortfolioNoTradeScore
NoTradeScore
ConflictScore
DataHealthStatus
ContractQualityScore
ExecutionQualityScore
IVCrushRiskScore
TrendExhaustionRisk
LateEntryRisk
GlobalRiskScore
NewsRiskScore
event_risk_state
liquidity_regime
liquidity_regime_shift_score
spread_stability_score
depth_persistence_score
premium_failure_flag
hard_stop_points
planned_risk_rupees
max_allowed_risk_rupees
rule_violation_flag
same_direction_recent_loss_penalty
drawdown_strictness_state
```

These determine what protected capital and what caused preventable drawdowns.

---

## 6. Highest ROI Optimization Fields

The most important ROI improvement fields are:

```text
net_pnl_rupees
r_multiple
mfe_r
mae_r
time_to_profit_seconds
ExpectedValue_R
VolEdgeRatio
EVPerMinute
PremiumElasticity
PremiumAccelerationScore
TimeToProfitProbability
TradeLocationEfficiency
RewardPathScore
OpportunityGrade
SetupExpectancy_R
historical_avg_return_r
historical_win_rate
historical_sample_size
slippage_entry_points
slippage_exit_points
total_costs_rupees
```

These allow improvement of:

- entry timing,
- exit timing,
- strike selection,
- setup selection,
- instrument selection,
- time-window selection,
- no-trade filters.

---

## 7. Trade Archetype Framework

Archetype codes are stored in `TRADE_ARCHETYPE_SCHEMA.csv`.

Initial archetypes:

| Code | Archetype |
|---|---|
| A01 | Trend Day Breakout |
| A02 | Gap Continuation |
| A03 | Gap Fill Reversal |
| A04 | Short Covering Rally |
| A05 | Long Build Up Expansion |
| A06 | IV Expansion Momentum |
| A07 | OI Wall Breakout |
| A08 | Power Hour Momentum |
| A09 | Compression Breakout |
| A10 | Gamma Pin Failure |
| A11 | Liquidity Sweep Reversal |
| A12 | VWAP Reclaim Continuation |
| A13 | VWAP Rejection Continuation |
| A14 | Pullback Continuation |
| A15 | Post-Event Continuation |
| A16 | Risk-Off Put Acceleration |
| A17 | Capitulation Reversal |
| A18 | Range Failure Continuation |
| A19 | Midcap Risk-On Thrust |
| A20 | No-Trade Saved Loss |

Archetype is one of the most important alpha-discovery fields.

---

## 8. Signal Combination IDs

Every trade should generate a standardized `signal_combination_id`.

Example:

```text
BNF_CALL_A07_FORCEDFLOW_HIGH_ELASTICITY_LOW_HOSTILITY
```

Signal combination IDs should encode:

```text
instrument
side
archetype
dominant signal
premium condition
regime condition
risk condition
```

Purpose:

```text
Find which signal combinations work and which fail.
```

---

## 9. Regime Combination IDs

Every trade should generate a standardized `regime_combination_id`.

Example:

```text
TREND_EXPANSION_LOW_IV_RISKON_MORNING
```

Regime combination IDs should encode:

```text
primary regime
volatility regime
liquidity regime
global risk regime
time window
expiry context
```

Purpose:

```text
Discover which market environments produce actual expectancy.
```

---

## 10. Opportunity Cluster IDs

Every candidate/trade should map to an `opportunity_cluster_id`.

Example:

```text
CLUSTER_GAPDOWN_PUT_FINNIFTY_RISKOFF_IVEXPANSION
```

Purpose:

```text
Group similar trades and compare forward outcomes.
```

This allows future analysis like:

```text
Cluster X: 72% win rate, +0.68R expectancy
Cluster Y: 38% win rate, -0.22R expectancy
```

---

## 11. Mandatory vs Optional Fields

### Mandatory Fields

Mandatory fields are required for:

- trade reconstruction,
- risk analysis,
- P&L analysis,
- opportunity ranking validation,
- survivability review.

Examples:

```text
trade_id
date
instrument
option_type
entry_time
entry_option_bid/ask/mid
OpportunityScore
DirectionScore
TradeQualityScore
ContractQualityScore
MarketHostilityScore
PremiumElasticity
planned_risk_rupees
hard_stop_points
exit_reason_primary
net_pnl_rupees
r_multiple
trade_archetype_code
signal_combination_id
regime_combination_id
opportunity_cluster_id
```

### Optional Fields

Optional fields enrich future research but may not be available immediately.

Examples:

```text
IV percentile
skew normalization risk
synthetic futures pressure
sector breadth
global market variables
post-exit would-have-hit-target
```

Optional does not mean unimportant. It means not always available in MVP.

---

## 12. Analysis Enabled by MTIL

The MTIL enables analysis such as:

```text
Win rate by instrument
Expectancy by archetype
Profit factor by regime
Average winner by setup
Average loser by exit reason
MFE/MAE by entry timing
Premium failure rate by instrument
Slippage by contract/time
EV accuracy by setup
No-trade saved-loss rate
Skipped winner rate
IV crush loss attribution
Gap trade performance
Expiry-day performance
Midcap vs Nifty trade quality
```

---

## 13. Minimum Review Milestones

### After 100 Trades / Candidates

Review:

```text
basic win/loss
rule violations
execution slippage
premium failure frequency
candidate ranking accuracy
```

### After 500 Trades / Candidates

Review:

```text
setup expectancy
instrument performance
regime performance
EV model calibration
no-trade quality
```

### After 1,000 Trades / Candidates

Review:

```text
signal combination performance
opportunity clusters
edge decay
threshold effectiveness
instrument calibration
```

### After 5,000 Trades / Candidates

Review:

```text
structural alpha map
stable edge clusters
regime-specific allocation rules
setup retirement / promotion
long-term compounding profile
```

---

## 14. Final Institutional Test

If running this strategy for 10 years, the most valuable fields are not entry/exit/P&L.

They are:

```text
why the trade existed,
what regime existed,
what signals aligned,
what risk filters passed,
what opportunity cluster it belonged to,
what happened after entry,
and whether similar trades had positive expectancy.
```

Final doctrine:

```text
The MTIL is not a journal.
It is the strategy's memory and alpha-discovery engine.
```
