# Top 20 Hedge-Fund Edge Ideas — Institutional Solution Design

**Purpose:** Convert the 20 ideas a professional hedge-fund options desk would add into complete institutional solution designs.

**Scope:** Trading-edge design only. This is not a coding document.

**Objective:** Improve decision quality, convexity capture, expected value, asymmetry, drawdown profile, survivability, and risk-adjusted ROI without increasing position count, leverage, probability of ruin, or complexity without edge.

**Canonical rule:**

```text
These modules may approve quality only after hard survival gates pass.
They may block or downgrade trades.
They may not override DataHealth, ContractQuality, HardStopFit, Risk Limits, NoTrade Mode, or Global Position Lock.
```

---

# 1. Expected Value Engine

## Institutional Problem

A high OpportunityScore does not guarantee positive expectancy after spread, slippage, theta, IV crush, and stop probability.

## Objective

Convert candidate quality into cost-adjusted expected value.

## Formula

```text
ExpectedValue_R =
  (WinProbability × AvgWin_R)
- (LossProbability × AvgLoss_R)
- Cost_R
- Slippage_R
- ThetaRisk_R
- IVCrushRisk_R
```

## Thresholds

```text
EV >= +0.30R required for live trade
EV >= +0.75R required for A+
EV <= 0 = reject
0 < EV < 0.30R = paper/watch only
```

## Integration

Final approval gate after OpportunityScore.

```text
if ExpectedValue_R < 0.30:
    NO_TRADE
```

## Hidden Risks

- False probability estimates.
- Overfitting after small samples.
- Optimistic average winner assumptions.

## Controls

- Use conservative provisional probabilities.
- Use net P&L after costs.
- Recalibrate only after sufficient sample by setup/instrument/regime.

## Verdict

```text
MUST ADD — highest impact improvement.
```

---

# 2. Forecast Realized Volatility vs Implied Move

## Institutional Problem

Option buyers only win when realized movement exceeds the implied/required cost of the option.

## Objective

Determine whether forecast realized movement is large enough to justify buying premium.

## Formula

```text
VolEdgeRatio = ForecastRealizedMove / RequiredMove
```

```text
VolEdgePoints =
ForecastRealizedMove
- RequiredMove
- SpreadSlippageEquivalent
- IVCompressionEquivalent
```

## Forecast Inputs

```text
ATRRemainingMove
RegimeProjectedMove
ATMStraddleImpliedRemainingMove
OpeningRangeProjection
RecentImpulseProjection
```

Use conservative median, not optimistic max.

## Thresholds

```text
VolEdgeRatio >= 1.60 required for live A
VolEdgeRatio >= 2.00 required for A+
VolEdgeRatio < 1.30 = reject/paper only
ForecastRealizedMove <= RequiredMove = hard reject
```

## Integration

Feeds:

```text
ExpectedMove/RequiredMove
ExpectedValue Engine
ConvexityEdgeScore
OpportunityScore
```

## Hidden Risks

- Vol forecast can fail during events.
- ATR may understate breakout regimes.
- Straddle may overprice event risk.

## Controls

- Use regime haircuts.
- Require premium elasticity confirmation.
- Do not trade on VolEdge alone.

## Verdict

```text
MUST ADD — core option-buyer edge.
```

---

# 3. Forced-Flow / Trapped-Participant Score

## Institutional Problem

The best option trades occur when other participants are forced to hedge, cover, unwind, or chase.

## Objective

Identify setups where movement is likely to accelerate because someone is trapped.

## Formula

```text
ForcedFlowScore =
  0.25 × OIWallStressScore
+ 0.20 × PremiumExpansionScore
+ 0.15 × FuturesImpulseScore
+ 0.15 × PriceAcceptanceScore
+ 0.10 × LeadershipConfirmationScore
+ 0.10 × LiquidityVacuumScore
+ 0.05 × OppositeSideFailureScore
```

## Thresholds

```text
>= 70 required for breakout/breakdown trades
>= 85 A+ boost
< 50 reject breakout trade
```

## Integration

Feeds:

```text
WinProbability
OpportunityScore
ConvexityEdgeScore
RangeExpansionQuality
```

## Hidden Risks

- OI side cannot prove dealer positioning.
- False wall breaks occur.
- Public data may lag.

## Controls

```text
No trade on OI alone.
Require price acceptance + premium expansion + liquidity quality.
```

## Verdict

```text
STRONGLY RECOMMENDED — high edge when constrained.
```

---

# 4. ConvexityEdgeScore

## Institutional Problem

Direction can be correct while the option is a poor vehicle.

## Objective

Measure whether buying gamma/vega exposure is attractive right now.

## Formula

```text
ConvexityEdgeScore =
  0.30 × PremiumElasticityScore
+ 0.25 × GammaUsefulnessScore
+ 0.20 × ExpectedAccelerationScore
+ 0.15 × IVSupportScore
+ 0.10 × TimeToProfitQualityScore
```

## Thresholds

```text
>= 80 required
>= 90 A+ boost
< 70 reject even if direction is strong
```

## Integration

Required input to:

```text
OpportunityScore
ExpectedValue Engine
A/A+ Classification
```

## Hidden Risks

- Gamma can hurt in chop.
- Elasticity may be spread-driven.
- IV can reverse suddenly.

## Controls

- Use mid-price.
- Require spread stability.
- Require two valid elasticity windows unless A+ impulse.

## Verdict

```text
MUST ADD — essential for long options.
```

---

# 5. LiquidityVacuumScore

## Institutional Problem

Option buyers need room for fast travel. Nearby obstacles reduce payoff asymmetry.

## Objective

Measure whether price has a clear path before hitting resistance/support/liquidity magnets.

## Formula

```text
LiquidityVacuumScore =
  0.30 × DistanceToNextObstacleScore
+ 0.25 × ThinZoneScore
+ 0.20 × OpposingOIWeaknessScore
+ 0.15 × SpreadStabilityScore
+ 0.10 × FuturesImpulseScore
```

## Objective Obstacles

```text
PDH/PDL
Opening range high/low
VWAP
Major OI wall
Round number
HVN/POC
Prior swing high/low
Gap boundary
Expiry magnet strike
```

## Thresholds

```text
>= 70 for breakout trades
>= 80 for A+ continuation
Target obstacle distance < RequiredMove = hard reject
```

## Integration

Feeds:

```text
ExpectedMove
ForcedFlowScore
TradeLocation
OpportunityScore
```

## Hidden Risks

- Obstacle maps can become subjective.
- OI walls can break violently.

## Controls

- Use objective levels first.
- Penalize uncertain maps.
- Do not use subjective SMC labels as primary evidence.

## Verdict

```text
STRONGLY RECOMMENDED — improves payoff path quality.
```

---

# 6. Opportunity Half-Life Engine

## Institutional Problem

Signals decay. A great opportunity can become a poor entry seconds later.

## Objective

Estimate how long each candidate remains valid before revalidation is required.

## Provisional Half-Life Table

| Setup Type | Half-Life |
|---|---:|
| Premium impulse breakout | 30–90 sec |
| Opening range breakout | 1–3 min |
| Gap acceptance | 5–15 min |
| Pullback continuation | 5–20 min |
| Compression breakout | 2–10 min after trigger |
| Gamma wall break | 30 sec–3 min |
| Liquidity sweep reversal | 2–8 min |

## Rule

```text
if CandidateAge > OpportunityHalfLife:
    REVALIDATE_REQUIRED
```

## Integration

Feeds:

```text
CandidateRevalidation
RankPersistence
OpportunityConfidenceScore
ExecutionQualityScore
```

## Hidden Risks

- Too short may miss slow trades.
- Too long permits stale entries.

## Controls

Use setup-specific half-life, not one global value.

## Verdict

```text
STRONGLY RECOMMENDED — prevents stale edge capture.
```

---

# 7. Opposite-Premium Failure Filter

## Institutional Problem

If both CE and PE premiums expand, the market may be pricing uncertainty rather than direction.

## Objective

Confirm directional premium dominance.

## Rules

For calls:

```text
Call premium expanding
AND put premium flat/weak/failing
```

For puts:

```text
Put premium expanding
AND call premium flat/weak/failing
```

## Formula

```text
PremiumDominanceRatio = DirectionalPremiumChange / max(OppositePremiumChange, tiny_value)
```

## Thresholds

```text
>= 1.5 acceptable
>= 2.0 strong
< 1.0 reject directional option buy
```

## Integration

Feeds:

```text
PremiumElasticity
ConvexityEdgeScore
ForcedFlowScore
MarketHostilityScore
```

## Hidden Risks

- Opposite side can temporarily expand during transitions.
- Spread noise can distort premium comparison.

## Controls

- Use mid-price.
- Require quote freshness.
- Confirm over valid window.

## Verdict

```text
MUST ADD — simple and high-value.
```

---

# 8. Trend Age / Exhaustion Filter

## Institutional Problem

Option buyers often lose by entering after the easy move is already complete.

## Objective

Prevent buying the last candle.

## Formula

```text
TrendExhaustionRisk =
  0.25 × ATR_ExtensionRisk
+ 0.20 × DistanceFromVWAPRisk
+ 0.20 × PremiumOverextensionRisk
+ 0.15 × LeadershipDivergenceRisk
+ 0.10 × VolumeClimaxRisk
+ 0.10 × TimeOfDayDecayRisk
```

## Thresholds

```text
> 70 = no new entry
50–70 = A+ only after fresh consolidation breakout
< 50 = acceptable
```

## Exception

Allow late continuation only if:

```text
fresh consolidation forms
premium re-accelerates
ForcedFlowScore >= 85
LiquidityVacuumScore >= 80
```

## Integration

Feeds:

```text
MarketHostilityScore
OpportunityScore penalty
ExpectedValue Engine
TradeLocation
```

## Hidden Risks

- Strong trend days remain extended.
- May block rare runners.

## Controls

Use exception only after consolidation + re-acceleration.

## Verdict

```text
MUST ADD — major drawdown reducer.
```

---

# 9. Setup-Specific Expectancy Tracking

## Institutional Problem

Generic scores hide which setup types actually produce positive expectancy.

## Objective

Track, downgrade, or disable setups by real performance.

## Required Setup Tags

```text
Breakout continuation
Pullback continuation
Liquidity sweep reversal
Gap continuation
Gap fade
Gamma wall break
Compression breakout
Post-event continuation
Range failure avoid
Trend exhaustion avoid
```

## Metrics

```text
Win rate
Average win
Average loss
Profit factor
Expectancy_R
MFE
MAE
Time to profit
Premium failure frequency
Slippage cost
Rule violation frequency
```

## Disable / Downgrade Rules

```text
Expectancy_R < 0 after 30 observations = downgrade to paper-only
ProfitFactor < 1.1 after 50 observations = disable live until reviewed
3 consecutive losses in same regime = defensive mode for that setup
```

## Integration

Feeds:

```text
WinProbability
EV Engine
OpportunityConfidenceScore
InstrumentCalibrationStatus
SetupGrade
```

## Hidden Risks

- Small sample bias.
- Hindsight optimization.
- Regime-specific variance.

## Controls

No production rule change under 30 observations.
Review by instrument and regime.

## Verdict

```text
MUST ADD — long-term edge decay control.
```

---

# 10. Range-Expansion Quality Filter

## Institutional Problem

Most breakouts fail. Option buyers require accepted expansion, not a one-tick breach.

## Objective

Measure whether breakout/range expansion is real, accepted, and premium-confirmed.

## Formula

```text
RangeExpansionQuality =
  0.25 × BreakStrengthScore
+ 0.20 × AcceptanceScore
+ 0.20 × VolumeParticipationScore
+ 0.20 × PremiumExpansionScore
+ 0.15 × SpreadStabilityScore
```

## Thresholds

```text
>= 75 required for breakout trades
>= 85 A+ breakout
< 60 reject breakout trade
```

## Hard Reject

```text
Breakout without premium expansion
Breakout with spread widening
Breakout directly into major obstacle
```

## Fast Exception

Only if:

```text
ForcedFlowScore >= 85
PremiumElasticity >= 1.20
ExecutionQualityScore >= 90
LiquidityVacuumScore >= 80
```

## Verdict

```text
MUST ADD — core breakout quality control.
```

---

# 11. Regime Transition Probability

## Institutional Problem

Most edge appears during transitions, not stable labels. Current regime classification may detect regimes after the opportunity has begun.

## Objective

Estimate probability that current market is transitioning from one state to another.

## Target Transitions

```text
Range → Trend
Compression → Expansion
Pin → Release
Trend → Exhaustion
Panic → Stabilization
Event Chaos → Accepted Repricing
Low IV → IV Expansion
High IV → IV Crush
```

## Formula

```text
RegimeTransitionProbability =
  0.25 × VolatilityShiftScore
+ 0.20 × RangeEfficiencyChange
+ 0.20 × PremiumBehaviorShift
+ 0.15 × LeadershipShift
+ 0.10 × OIWallStressChange
+ 0.10 × LiquidityRegimeShift
```

## Thresholds

```text
>= 70 transition likely
>= 85 high-conviction transition
< 50 no transition edge
```

## Integration

Feeds:

```text
RegimeFitScore
OpportunityScore
ForcedFlowScore
VolEdge Engine
```

## Hidden Risks

- Early transition signals can be false.
- Over-classification creates noise.

## Controls

Require premium behavior shift plus price acceptance before live entry.

## Verdict

```text
STRONGLY RECOMMENDED — improves early opportunity detection.
```

---

# 12. Volatility Compression-to-Expansion Detector

## Institutional Problem

Some of the best option trades happen when realized volatility is about to expand from compression.

## Objective

Detect when compression is ending and option premium is starting to price expansion.

## Formula

```text
CompressionExpansionScore =
  0.25 × RangeCompressionScore
+ 0.20 × ATRExpansionTrigger
+ 0.20 × StraddleBidFirming
+ 0.15 × PremiumElasticityEmergence
+ 0.10 × VolumeParticipation
+ 0.10 × BreakAcceptance
```

## Thresholds

```text
>= 75 expansion candidate
>= 85 A+ if VolEdge positive and liquidity clean
< 60 no expansion trade
```

## Integration

Feeds:

```text
VolEdge Engine
ConvexityEdgeScore
RegimeTransitionProbability
OpportunityScore
```

## Hidden Risks

- Compression can persist longer than expected.
- Early buying causes theta bleed.

## Controls

Do not buy before trigger. Require premium elasticity emergence.

## Verdict

```text
MUST ADD — high-quality option-buyer edge.
```

---

# 13. Gamma Pin Failure Detector

## Institutional Problem

Pinned markets are bad for option buyers until the pin fails. The failure can create powerful convexity.

## Objective

Detect transition from dealer/expiry pin to directional release.

## Formula

```text
GammaPinFailureScore =
  0.25 × PinPersistenceBreak
+ 0.20 × StrikeAcceptanceBeyondPin
+ 0.20 × ATMOptionExpansion
+ 0.15 × OIWallStress
+ 0.10 × FuturesImpulse
+ 0.10 × SpreadStability
```

## Thresholds

```text
>= 75 pin failure candidate
>= 85 A+ gamma release
< 60 avoid pin trade
```

## Integration

Feeds:

```text
ForcedFlowScore
ConvexityEdgeScore
RegimeTransitionProbability
OpportunityScore
```

## Hidden Risks

- Public OI does not reveal dealer side.
- False pin breaks are common.

## Controls

Require price acceptance and premium expansion. No dealer certainty claims.

## Verdict

```text
STRONGLY RECOMMENDED — high edge around expiry/pin regimes.
```

---

# 14. IV Surface Stability Filter

## Institutional Problem

Option buyers can lose if IV surface is unstable, distorted, or about to normalize.

## Objective

Evaluate whether IV conditions support long option ownership.

## Formula

```text
IVSurfaceStabilityScore =
  0.25 × ATMIVStability
+ 0.20 × SkewStability
+ 0.20 × TermStructureStability
+ 0.15 × CrossStrikeIVConsistency
+ 0.10 × EventPremiumRiskInverse
+ 0.10 × QuoteQuality
```

## Thresholds

```text
>= 75 stable/supportive
50–75 caution
< 50 reject long option unless realized move already dominates
```

## Integration

Feeds:

```text
IVCrushRisk
ConvexityEdgeScore
EV Engine
TradeQualityScore
```

## Hidden Risks

- IV data can be stale.
- Broker IV can be model-dependent.

## Controls

Use only fresh IV. Penalize invalid/stale IV. Confirm with premium behavior.

## Verdict

```text
STRONGLY RECOMMENDED — prevents volatility-surface traps.
```

---

# 15. Skew Normalization Risk

## Institutional Problem

Skew can normalize against the long option even when direction is correct.

## Objective

Detect whether put/call skew is likely to crush or flatten after fear/euphoria subsides.

## Formula

```text
SkewNormalizationRisk =
  0.30 × SkewExtremeScore
+ 0.25 × SkewMeanReversionSpeed
+ 0.20 × EventCompletionRisk
+ 0.15 × OppositeWingDemandShift
+ 0.10 × IVSurfaceInstability
```

## Thresholds

```text
> 75 = avoid wing/OTM long options
50–75 = prefer ATM/ITM only
< 50 = acceptable
```

## Integration

Feeds:

```text
IVCrushRisk
StrikeSelection
ConvexityEdgeScore
EV Engine
```

## Hidden Risks

- Skew can remain extreme in panic.
- Normalization timing is hard.

## Controls

Use as penalty, not standalone veto unless extreme and premium weak.

## Verdict

```text
NICE TO STRONGLY RECOMMENDED — important for avoiding expensive tails.
```

---

# 16. Time-to-Profit Probability Model

## Institutional Problem

Long options must work quickly. A trade with correct direction but slow movement can still lose.

## Objective

Estimate probability that the trade reaches favorable premium movement within the required time window.

## Formula

```text
TimeToProfitProbability =
  0.25 × MomentumVelocityScore
+ 0.20 × PremiumAccelerationScore
+ 0.20 × RegimeSpeedScore
+ 0.15 × LiquidityVacuumScore
+ 0.10 × TimeOfDayScore
+ 0.10 × ForcedFlowScore
```

## Thresholds

```text
>= 70 required for normal long option trade
>= 85 A+ time-quality
< 60 no trade unless swing thesis exists, which MVP does not use
```

## Integration

Feeds:

```text
ConvexityEdgeScore
EV Engine
HoldingTime Engine
Exit Logic
```

## Hidden Risks

- High speed can also mean reversal risk.
- May over-favor momentum spikes.

## Controls

Require price acceptance and spread stability.

## Verdict

```text
MUST ADD — directly reduces theta bleed.
```

---

# 17. Trade Location Efficiency Score

## Institutional Problem

Same signal has different expectancy depending on location.

## Objective

Measure whether entry is close to invalidation and far enough from target/obstacles.

## Formula

```text
TradeLocationEfficiency =
  0.25 × DistanceToInvalidationQuality
+ 0.25 × DistanceToTargetQuality
+ 0.20 × RewardPathOpenness
+ 0.15 × EntryNotExtendedScore
+ 0.15 × TimeOfDayLocationScore
```

## Thresholds

```text
>= 75 required
>= 85 A+ location
< 60 reject
```

## Integration

Feeds:

```text
EV Engine
OpportunityScore
RiskReward
HardStopFit
```

## Hidden Risks

- Location maps can be subjective.
- Waiting for ideal location can miss impulse trades.

## Controls

Use objective levels first. Allow A+ impulse exception only with ForcedFlowScore >= 85.

## Verdict

```text
MUST ADD — large drawdown reduction.
```

---

# 18. Candidate EV Per Minute of Risk

## Institutional Problem

Two trades may have equal EV, but one realizes edge faster with less theta exposure.

## Objective

Prioritize opportunities with better edge velocity.

## Formula

```text
EVPerMinute = ExpectedValue_R / ExpectedHoldingMinutes
```

Adjusted:

```text
RiskAdjustedEVPerMinute = EVPerMinute / MaxAdverseExcursionRisk
```

## Thresholds

```text
EVPerMinute > 0.02R/min = acceptable
> 0.04R/min = strong intraday opportunity
< 0.01R/min = too slow for MVP long option buying
```

## Integration

Tie-breaker and ranking enhancer.

Feeds:

```text
OpportunityScore
TimeToProfitProbability
ExpectedValue Engine
```

## Hidden Risks

- May over-favor scalps.
- Fast EV estimates are noisy.

## Controls

Use as ranking variable, not hard trigger.

## Verdict

```text
STRONGLY RECOMMENDED AS TIE-BREAKER / CAPITAL EFFICIENCY METRIC.
```

---

# 19. Instrument-Specific Edge Attribution

## Institutional Problem

Multi-instrument ranking can hide which instrument actually produces edge.

## Objective

Track edge separately by instrument, setup, regime, time, and contract type.

## Required Attribution Buckets

```text
Instrument
Setup type
Regime
Time of day
Expiry distance
IV regime
Contract type
Opportunity grade
Entry reason
Exit reason
```

## Metrics

```text
Net expectancy
Profit factor
Win rate
Avg win/loss
MFE/MAE
Premium failure rate
Slippage cost
No-trade saved-loss rate
Skipped-winner rate
```

## Rules

```text
If an instrument has negative expectancy after 50 qualified candidates:
    downgrade calibration status

If live trades underperform paper by large margin:
    tighten ExecutionQuality requirements

If one instrument consistently contributes no edge:
    keep monitor-only
```

## Integration

Feeds:

```text
CalibrationStatus
OpportunityConfidenceScore
InstrumentUncertaintyPenalty
UniverseSelection
```

## Hidden Risks

- Sample size may be small.
- Regime-specific variance can mislead.

## Controls

Use minimum sample and regime segmentation.

## Verdict

```text
MUST ADD — essential for multi-instrument survival.
```

---

# 20. Drawdown-State Strictness Escalator

## Institutional Problem

The system should become stricter after losses, not merely smaller.

## Objective

Improve survivability by raising quality thresholds during drawdown or poor recent performance.

## Formula

```text
DrawdownStrictnessLevel = function(
  CurrentDrawdown,
  ConsecutiveLosses,
  RecentRuleViolations,
  RecentSlippageDeterioration,
  SetupUnderperformance
)
```

## Levels

| State | Rule |
|---|---|
| Normal | Base thresholds |
| Caution | +5 DynamicExcellentThreshold |
| Defensive | +10 threshold, A+ only |
| Recovery | paper/watch only or half-risk A+ |
| Shutdown | no trade |

## Triggers

```text
1 loss = caution review
2 losses = defensive / cooldown
3 losses = stop day
Weekly loss > 2% = A+ only next session
Monthly DD > 6% = recovery mode
Rule violation = shutdown or paper mode
```

## Integration

Feeds:

```text
PortfolioNoTradeScore
DynamicExcellentThreshold
RiskMode
PositionSizing
```

## Hidden Risks

- Too strict after drawdown may reduce recovery opportunities.
- Trader may override due frustration.

## Controls

Use predefined rules, not discretionary fear. Journal all blocked trades.

## Verdict

```text
MUST ADD — strongest survivability improvement after hard risk caps.
```

---

# Final Institutional Integration

The 20 ideas should be integrated as four layers:

## Layer 1 — EV / Convexity Layer

```text
ExpectedValue Engine
VolEdge Engine
ConvexityEdgeScore
TimeToProfitProbability
EVPerMinute
```

## Layer 2 — Market Structure / Forced Movement Layer

```text
ForcedFlowScore
LiquidityVacuumScore
RangeExpansionQuality
GammaPinFailureDetector
RegimeTransitionProbability
CompressionExpansionDetector
```

## Layer 3 — Volatility Quality Layer

```text
IVSurfaceStability
SkewNormalizationRisk
IVCrush interaction
Volatility supply/demand context
```

## Layer 4 — Learning / Survivability Layer

```text
Setup-Specific Expectancy
Instrument-Specific Edge Attribution
Drawdown-State Strictness Escalator
OpportunityHalfLife
Trade Location Efficiency
```

---

# Final Candidate Approval Stack

A final live candidate must pass:

```text
Hard survival gates
OpportunityScore >= DynamicExcellentThreshold
ExpectedValue_R >= 0.30R
VolEdgeRatio >= 1.60
ConvexityEdgeScore >= 80
ExecutionQualityScore >= 80
OpportunityConfidenceScore >= 70
TradeLocationEfficiency >= 75
TimeToProfitProbability >= 70
TrendExhaustionRisk <= 70
OpportunityHalfLife not expired
```

For breakout trades:

```text
ForcedFlowScore >= 70
RangeExpansionQuality >= 75
LiquidityVacuumScore >= 70
```

For pin/gamma-release trades:

```text
GammaPinFailureScore >= 75
```

For compression breakout trades:

```text
CompressionExpansionScore >= 75
```

---

# Final Committee Verdict

These 20 improvements are not feature bloat if implemented as **filters and ranking quality layers**, not as trade triggers.

They improve:

- EV realism,
- convexity capture,
- no-trade quality,
- late-entry avoidance,
- drawdown control,
- edge decay detection,
- instrument selection quality,
- and 10-year survivability.

Final doctrine:

```text
The system should not trade because an instrument is ranked highest.
It should trade only when the candidate has positive expectancy,
clean convexity,
forced or accepted movement,
real execution quality,
and survival-compatible risk.
```
