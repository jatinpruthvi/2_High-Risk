# Top 50 Missing Opportunity Filters — Institutional Solution Design

**Perspective:** Billion-dollar hedge-fund investment committee, institutional options portfolio manager, volatility trader, market microstructure specialist, and survivability-focused risk committee.

**Purpose:** Convert the Top 50 Missing Opportunity Filters into institutional-quality filter designs that improve opportunity selection, reduce false positives, improve convexity capture, reduce drawdown, and protect long-term compounding.

**Scope:** This is not a coding exercise. This document defines trading-edge logic, thresholds, vetoes, ranking impact, and risk controls.

---

## Canonical Rule

Opportunity filters are not standalone entry signals.

They can:

```text
approve quality,
downgrade quality,
block weak trades,
improve ranking,
improve no-trade decisions.
```

They cannot override:

```text
Survival Gate
DataHealth
ContractQuality
HardStopFit
Risk Limits
NoTrade Mode
Global Position Lock
Candidate Revalidation
```

---

## Final Opportunity Filter Stack

A final live candidate must pass:

```text
Hard survival gates
EV_R >= 0.30R
VolEdgeRatio >= 1.60
ConvexityEdgeScore >= 80
ExecutionQualityScore >= 80
OpportunityConfidenceScore >= 70
TradeLocationEfficiency >= 75
RewardPathScore >= 75
LateEntryRisk <= 70
TrendExhaustionRisk <= 70
OpportunityHalfLife not expired
```

For breakout trades:

```text
ForcedFlowScore >= 70
RangeExpansionQuality >= 75
LiquidityVacuumScore >= 70
DirectionalOptionBreadthScore >= 70
```

---

# 1. EV > 0 After Costs Filter

## Why It Matters

A setup can look strong but still be negative expectancy after costs.

## Institutional Solution

```text
EV_R = P_win × AvgWin_R - P_loss × AvgLoss_R - Cost_R - Slippage_R - ThetaRisk_R - IVCrushRisk_R
```

## Threshold / Veto

```text
EV_R >= +0.30R required
EV_R >= +0.75R for A+
EV_R <= 0 = hard reject
```

## Integration

Final approval gate after OpportunityScore.

## Risk Control

Use conservative probability assumptions until statistically validated.

---

# 2. VolEdge Positive Filter

## Why It Matters

Long options require realized movement to exceed implied/required movement.

## Institutional Solution

```text
VolEdgeRatio = ForecastRealizedMove / RequiredMove
```

## Threshold / Veto

```text
>= 1.60 required
>= 2.00 A+
< 1.30 reject / paper only
ForecastRealizedMove <= RequiredMove = hard reject
```

## Integration

Feeds EV, ExpectedMove/RequiredMove, ConvexityEdgeScore.

## Risk Control

Use conservative forecast, not optimistic max projection.

---

# 3. ConvexityEdge >= 80 Filter

## Why It Matters

Direction may be right but option convexity may be poor.

## Institutional Solution

```text
ConvexityEdgeScore =
0.30 × PremiumElasticityScore
+ 0.25 × GammaUsefulnessScore
+ 0.20 × ExpectedAccelerationScore
+ 0.15 × IVSupportScore
+ 0.10 × TimeToProfitQualityScore
```

## Threshold / Veto

```text
>= 80 required
>= 90 A+
< 70 reject even if direction is strong
```

## Integration

Required quality gate before live trade.

## Risk Control

Reject spread-driven false elasticity.

---

# 4. ForcedFlowScore >= 70 Filter

## Why It Matters

Best long-option trades happen when participants are forced to hedge, cover, or chase.

## Institutional Solution

```text
ForcedFlowScore =
0.25 × OIWallStress
+ 0.20 × PremiumExpansion
+ 0.15 × FuturesImpulse
+ 0.15 × PriceAcceptance
+ 0.10 × LeadershipConfirmation
+ 0.10 × LiquidityVacuum
+ 0.05 × OppositeSideFailure
```

## Threshold / Veto

```text
>= 70 required for breakout/breakdown trades
>= 85 A+
< 50 reject breakout trade
```

## Integration

Feeds OpportunityScore and EV probability.

## Risk Control

No trade on OI alone.

---

# 5. LiquidityVacuumScore Positive Filter

## Why It Matters

Option buyers need clear reward path and fast price travel.

## Institutional Solution

```text
LiquidityVacuumScore =
0.30 × DistanceToNextObstacle
+ 0.25 × ThinZonePresence
+ 0.20 × OpposingOIWeakness
+ 0.15 × SpreadStability
+ 0.10 × FuturesImpulse
```

## Threshold / Veto

```text
>= 70 required for breakout trades
>= 80 A+
DistanceToNextObstacle < RequiredMove = hard reject
```

## Integration

Feeds ExpectedMove, RewardPathScore, and OpportunityScore.

## Risk Control

Use objective obstacles only.

---

# 6. OpportunityHalfLife Not Expired Filter

## Why It Matters

A candidate can decay quickly and become a late entry.

## Institutional Solution

Assign half-life by setup type.

| Setup | Half-Life |
|---|---:|
| Premium impulse breakout | 30–90 sec |
| Opening range breakout | 1–3 min |
| Gap acceptance | 5–15 min |
| Pullback continuation | 5–20 min |
| Gamma wall break | 30 sec–3 min |

## Threshold / Veto

```text
CandidateAge > OpportunityHalfLife = REVALIDATE_REQUIRED
```

## Integration

Candidate revalidation and OpportunityConfidenceScore.

## Risk Control

Use setup-specific half-life, not global age.

---

# 7. OppositePremiumFailure Filter

## Why It Matters

Directional option edge is cleaner when the opposite side fails.

## Institutional Solution

```text
PremiumDominanceRatio = DirectionalPremiumChange / max(OppositePremiumChange, tiny_value)
```

## Threshold / Veto

```text
>= 1.5 acceptable
>= 2.0 strong
< 1.0 reject directional option buy
Both CE and PE expanding strongly = uncertainty/event risk
```

## Integration

Feeds ConvexityEdgeScore and MarketHostilityScore.

## Risk Control

Use mid-price and quote freshness.

---

# 8. RangeExpansionQuality >= 75 Filter

## Why It Matters

Most breakouts fail without auction acceptance and premium confirmation.

## Institutional Solution

```text
RangeExpansionQuality =
0.25 × BreakStrength
+ 0.20 × AcceptanceScore
+ 0.20 × VolumeParticipation
+ 0.20 × PremiumExpansion
+ 0.15 × SpreadStability
```

## Threshold / Veto

```text
>= 75 required for breakout trades
>= 85 A+
< 60 reject breakout
```

## Integration

Feeds ForcedFlowScore and OpportunityScore.

## Risk Control

Reject breakouts without premium expansion.

---

# 9. TrendAge Not Exhausted Filter

## Why It Matters

Late entries cause poor reward/risk and premium overpayment.

## Institutional Solution

```text
TrendExhaustionRisk =
0.25 × ATR_ExtensionRisk
+ 0.20 × DistanceFromVWAPRisk
+ 0.20 × PremiumOverextensionRisk
+ 0.15 × LeadershipDivergenceRisk
+ 0.10 × VolumeClimaxRisk
+ 0.10 × TimeOfDayDecayRisk
```

## Threshold / Veto

```text
> 70 = no new entry
50–70 = A+ only after fresh consolidation
< 50 acceptable
```

## Integration

Feeds MarketHostility and EV.

## Risk Control

Allow exception only after fresh consolidation + re-acceleration.

---

# 10. Reward Path Clear Filter

## Why It Matters

Direction can be correct but target path can be blocked.

## Institutional Solution

```text
RewardPathScore =
0.30 × TargetDistanceQuality
+ 0.25 × ObstacleClearance
+ 0.20 × OIWallDistance
+ 0.15 × ValueAreaClearance
+ 0.10 × GapBoundaryClearance
```

## Threshold / Veto

```text
>= 75 required
< 60 reject
TargetDistance < RequiredMove = hard reject
```

## Integration

Feeds TradeLocationEfficiency and EV.

## Risk Control

Use objective obstacle map.

---

# 11. No Major Obstacle Nearby Filter

## Why It Matters

Nearby VWAP, OI wall, OR boundary, or prior level can kill convexity.

## Institutional Solution

```text
ObstacleProximityRisk = RequiredMove / DistanceToNearestMajorObstacle
```

## Threshold / Veto

```text
DistanceToObstacle >= 1.25 × RequiredMove required
DistanceToObstacle < RequiredMove = hard reject
```

## Integration

Feeds RewardPathScore and LiquidityVacuumScore.

## Risk Control

If obstacle map uncertain, apply penalty.

---

# 12. IV Surface Stable Filter

## Why It Matters

Unstable IV can destroy option premium.

## Institutional Solution

```text
IVSurfaceStabilityScore =
0.25 × ATMIVStability
+ 0.20 × SkewStability
+ 0.20 × TermStructureStability
+ 0.15 × CrossStrikeIVConsistency
+ 0.10 × EventPremiumRiskInverse
+ 0.10 × QuoteQuality
```

## Threshold / Veto

```text
>= 75 supportive
50–75 caution
< 50 reject unless realized move dominates
```

## Integration

Feeds IVCrushRisk and ConvexityEdgeScore.

## Risk Control

Stale IV = penalty or invalid.

---

# 13. Skew Not Crushing Against Trade Filter

## Why It Matters

Skew normalization can offset favorable direction.

## Institutional Solution

```text
SkewNormalizationRisk =
0.30 × SkewExtreme
+ 0.25 × MeanReversionSpeed
+ 0.20 × EventCompletionRisk
+ 0.15 × OppositeWingDemandShift
+ 0.10 × IVSurfaceInstability
```

## Threshold / Veto

```text
> 75 avoid OTM/wing long options
50–75 prefer ATM/ITM only
< 50 acceptable
```

## Integration

Feeds StrikeSelection and IVCrushRisk.

## Risk Control

Use as penalty unless extreme and premium weak.

---

# 14. Straddle Supports Expansion Filter

## Why It Matters

ATM straddle firming can confirm volatility expansion.

## Institutional Solution

```text
StraddleSupportScore =
0.30 × ATMStraddleChangeRate
+ 0.25 × DirectionalLegDominance
+ 0.20 × IVChangeConfirmation
+ 0.15 × RealizedMoveAcceleration
+ 0.10 × SpreadStability
```

## Threshold / Veto

```text
>= 75 supports expansion
< 60 no straddle support
Both legs rising equally = uncertainty; wait
```

## Integration

Feeds VolEdge and ConvexityEdge.

## Risk Control

Do not treat equal two-sided straddle bid as directional edge.

---

# 15. Multi-Strike Premium Confirms Filter

## Why It Matters

One strike can be noisy; institutional pressure appears across strike cluster.

## Institutional Solution

```text
MultiStrikePremiumConfirmation =
0.30 × ATMChange
+ 0.25 × AdjacentStrikeAlignment
+ 0.20 × VolumeDistribution
+ 0.15 × IVConsistency
+ 0.10 × SpreadQualityAcrossCluster
```

## Threshold / Veto

```text
>= 75 cluster confirmation
< 55 isolated strike noise
```

## Integration

Feeds DirectionalOptionBreadthScore.

## Risk Control

Reject far-OTM-only activity.

---

# 16. ATM and ITM Both Responsive Filter

## Why It Matters

ATM and ITM response confirms tradable delta, not lottery OTM flow.

## Institutional Solution

```text
ATM_ITM_ResponseScore =
0.50 × ATMElasticity
+ 0.35 × ITMElasticity
+ 0.15 × SpreadStability
```

## Threshold / Veto

```text
>= 75 required for strong direction
ATM responsive but ITM dead = caution
ITM responsive but ATM dead = data/strike issue
```

## Integration

Feeds ContractQuality and ConvexityEdge.

## Risk Control

Use fresh quotes only.

---

# 17. OTM Not Leading Alone Filter

## Why It Matters

Far OTM spikes are often retail lottery or noise.

## Institutional Solution

```text
OTMNoiseRisk = OTMActivityScore - ATMConfirmationScore
```

## Threshold / Veto

```text
OTM leading without ATM confirmation = reject
OTM can support only after ATM/ITM confirm
```

## Integration

Feeds DirectionalOptionBreadth and MarketHostility.

## Risk Control

Far OTM cannot trigger trades in MVP.

---

# 18. Futures Impulse Persists Filter

## Why It Matters

One futures spike is noise. Persistence shows real pressure.

## Institutional Solution

```text
FuturesImpulsePersistence =
0.30 × ImpulseMagnitude
+ 0.25 × FollowThroughDuration
+ 0.20 × PullbackShallowness
+ 0.15 × VolumeParticipation
+ 0.10 × BasisStability
```

## Threshold / Veto

```text
>= 75 persistent impulse
< 55 one-tick noise
```

## Integration

Feeds DirectionScore and ForcedFlowScore.

## Risk Control

Still require option premium confirmation.

---

# 19. VWAP Displacement Accepted Filter

## Why It Matters

Accepted displacement from VWAP shows auction control.

## Institutional Solution

```text
VWAPDisplacementQuality =
0.30 × VWAPSlope
+ 0.25 × AcceptedDistanceFromVWAP
+ 0.20 × RetestHoldOrReject
+ 0.15 × VolumeParticipation
+ 0.10 × PremiumConfirmation
```

## Threshold / Veto

```text
>= 75 accepted displacement
Flat VWAP = no directional option trade
```

## Integration

Feeds RegimeFit and DirectionScore.

## Risk Control

Flat VWAP remains no-trade unless exceptional forced-flow exists.

---

# 20. OR Breakout Accepted Filter

## Why It Matters

Opening range breaks fail often unless accepted.

## Institutional Solution

```text
OpeningRangeAcceptance =
0.25 × BreakStrength
+ 0.25 × AcceptanceDuration
+ 0.20 × RetestQuality
+ 0.15 × PremiumExpansion
+ 0.15 × SpreadStability
```

## Threshold / Veto

```text
>= 75 OR accepted
>= 85 A+ OR drive
< 60 avoid OR breakout
```

## Integration

Feeds RangeExpansionQuality.

## Risk Control

No ORB before 9:30. Gap rules override ORB.

---

# 21. Gap Accepted, Not Merely Opened Filter

## Why It Matters

Gap direction is information; gap acceptance is edge.

## Institutional Solution

```text
GapAcceptanceQuality =
0.25 × HoldBeyondGapBoundary
+ 0.20 × ORAcceptance
+ 0.20 × PremiumResponse
+ 0.15 × LeadershipConfirmation
+ 0.10 × SpreadNormalization
+ 0.10 × VolumeParticipation
```

## Threshold / Veto

```text
>= 75 gap continuation candidate
< 60 wait / no trade
```

## Integration

Feeds GapRisk and RegimeFit.

## Risk Control

Minimum gap wait must be completed.

---

# 22. Premium Not Already Overextended Filter

## Why It Matters

Buying already-expanded premium reduces reward/risk.

## Institutional Solution

```text
PremiumOverextensionRisk =
0.35 × PremiumMoveVsRecentMedian
+ 0.25 × IVExpansionAlreadyOccurred
+ 0.20 × RangeConsumedRatio
+ 0.20 × TimeSinceImpulse
```

## Threshold / Veto

```text
> 75 no new long option
50–75 A+ only after consolidation
```

## Integration

Feeds LateEntryRisk and TrendExhaustionRisk.

## Risk Control

Fresh re-acceleration can reset the score.

---

# 23. Required Move Still Realistic Filter

## Why It Matters

Option trade fails if target move is no longer realistic.

## Institutional Solution

```text
RealismRatio = RealisticRemainingMove / RequiredMove
```

## Threshold / Veto

```text
>= 1.60 required
>= 2.00 A+
< 1.30 reject
```

## Integration

Feeds VolEdge and EV.

## Risk Control

Use conservative remaining move after range consumed.

---

# 24. Spread Stable During Impulse Filter

## Why It Matters

Spread widening during move means execution edge is unstable.

## Institutional Solution

```text
SpreadStabilityScore = 100 - SpreadExpansionRisk
```

```text
SpreadExpansionRisk = CurrentSpread / MedianRecentSpread
```

## Threshold / Veto

```text
Spread > 1.25 × ranking spread = revalidate
Spread > 2.0 × median = no trade / liquidity shock
```

## Integration

Feeds ExecutionQualityScore.

## Risk Control

Liquidity shock overrides opportunity.

---

# 25. Depth Not Disappearing Filter

## Why It Matters

Vanishing depth creates slippage and exit risk.

## Institutional Solution

```text
DepthPersistenceScore =
0.50 × TopBookPersistence
+ 0.50 × FiveDepthPersistence
```

## Threshold / Veto

```text
Depth drop > 60% = liquidity shock
Depth persistence < 70 = execution penalty
```

## Integration

Feeds ExecutionQualityScore.

## Risk Control

Use persistence, not one snapshot.

---

# 26. Quote Not Stale Filter

## Why It Matters

Stale quote invalidates every premium calculation.

## Institutional Solution

```text
QuoteFreshnessScore = function(seconds_since_last_quote_update)
```

## Threshold / Veto

```text
Selected option stale > 8 sec = invalid
Futures stale > 5 sec = invalid
Candidate built from stale quote = reject
```

## Integration

Feeds DataHealth and ExecutionQuality.

## Risk Control

No exception.

---

# 27. Candidate Not Stale Filter

## Why It Matters

Even if data is fresh, the candidate decision may be old.

## Institutional Solution

```text
CandidateAge = current_time - candidate_creation_time
```

## Threshold / Veto

```text
Fast market > 5 sec = revalidate
Normal market > 15 sec = revalidate
Top candidate failed revalidation = recalculate all
```

## Integration

Feeds CandidateRevalidation.

## Risk Control

Never auto-trade rank #2.

---

# 28. Candidate Survives Re-Rank Filter

## Why It Matters

Flickering rankings are unreliable.

## Institutional Solution

```text
RankStabilityScore = stability of candidate grade/rank across consecutive windows
```

## Threshold / Veto

```text
Candidate must remain A/A+ for 2 ranking windows
or be A+ impulse exception with all strong gates
```

## Integration

Feeds OpportunityConfidence.

## Risk Control

Reject flickering A/B candidates.

---

# 29. Instrument Regime Fit Strong Filter

## Why It Matters

Each instrument has regimes where it performs better.

## Institutional Solution

Use instrument regime matrix.

## Threshold / Veto

```text
RegimeFitScore >= 70 required
MIDCPNIFTY >= 80 until validated
RegimeFitScore < 60 = reject
```

## Integration

Feeds OpportunityScore and ranking.

## Risk Control

No instrument is automatically preferred.

---

# 30. Setup Type Positive Expectancy Filter

## Why It Matters

Some setup types may not work after costs.

## Institutional Solution

Use Setup-Specific Expectancy Engine.

## Threshold / Veto

```text
Setup Expectancy_R < 0 after 30 observations = paper-only
ProfitFactor < 1.1 after 50 observations = disable live
```

## Integration

Feeds EV and OpportunityConfidence.

## Risk Control

Avoid small-sample overreaction.

---

# 31. Time-of-Day Favorable Filter

## Why It Matters

Option-buying quality varies by session.

## Institutional Solution

```text
TimeOfDayScore = setup/instrument/regime expectancy by time window
```

## Threshold / Veto

```text
Lunch chop without trend = no trade
After 15:00 = no new MVP trade
First 15 min = no new trade
```

## Integration

Feeds TimeToProfitProbability and MarketHostility.

## Risk Control

Time is filter, not signal.

---

# 32. Expiry Environment Favorable Filter

## Why It Matters

Expiry can create pin, theta acceleration, and fake breaks.

## Institutional Solution

```text
ExpiryEnvironmentScore =
0.30 × PinRiskInverse
+ 0.25 × GammaUsefulness
+ 0.20 × ThetaSafety
+ 0.15 × SpreadQuality
+ 0.10 × TimeToProfitProbability
```

## Threshold / Veto

```text
>= 75 expiry trade allowed
< 60 no new expiry trade
```

## Integration

Feeds RegimeFit and ConvexityEdge.

## Risk Control

Expiry trades must be quick and ATM/near-ATM.

---

# 33. Event Risk Resolved Filter

## Why It Matters

Unresolved events create IV shock and two-sided risk.

## Institutional Solution

```text
EventResolutionScore =
0.30 × EventCompletedOrAbsent
+ 0.25 × IVStabilization
+ 0.20 × PriceAcceptance
+ 0.15 × SpreadNormalization
+ 0.10 × NewsClarity
```

## Threshold / Veto

```text
>= 75 event resolved
< 60 no trade
Unresolved high-risk event = hard no-trade
```

## Integration

Feeds NewsRisk and IVCrushRisk.

## Risk Control

Trade reaction, not headline.

---

# 34. Global Risk Not Shock Filter

## Why It Matters

Global shock can invalidate local signals.

## Institutional Solution

Use GlobalRiskScore.

## Threshold / Veto

```text
GlobalRiskState = Shock = no trade until Indian stabilization
Risk-Off = call penalty; puts still need Indian confirmation
```

## Integration

Feeds MarketHostility and PortfolioNoTrade.

## Risk Control

Global sentiment cannot trigger trades.

---

# 35. News Not Unresolved Filter

## Why It Matters

Unverified news can cause whipsaw and spread shock.

## Institutional Solution

Use NewsRiskFilter.

## Threshold / Veto

```text
NEWS_NO_TRADE = hard no-trade
NEWS_SURVIVAL = survival/no new risk
unverified major headline + abnormal spreads = no trade
```

## Integration

Feeds PortfolioNoTrade.

## Risk Control

No headline trading.

---

# 36. Direction Not Based on One Candle Filter

## Why It Matters

One candle often creates false momentum.

## Institutional Solution

```text
DirectionPersistenceScore =
0.40 × MultiCandleFollowThrough
+ 0.25 × PremiumPersistence
+ 0.20 × FuturesPersistence
+ 0.15 × LeadershipPersistence
```

## Threshold / Veto

```text
>= 70 required unless A+ impulse exception
< 50 reject one-candle signal
```

## Integration

Feeds DirectionScore and OpportunityConfidence.

## Risk Control

A+ impulse exception requires ForcedFlowScore >=85 and ExecutionQuality >=90.

---

# 37. Leadership Not Narrow Filter

## Why It Matters

Narrow leadership creates fragile index moves.

## Institutional Solution

```text
LeadershipBreadthScore =
0.40 × WeightedConstituentBreadth
+ 0.25 × TopConstituentAgreement
+ 0.20 × SectorParticipation
+ 0.15 × PremiumBreadth
```

## Threshold / Veto

```text
>= 70 acceptable
< 50 downgrade/reject index move
```

## Integration

Feeds DirectionScore and Confidence.

## Risk Control

One-stock driven moves need exceptional premium confirmation.

---

# 38. Constituent Confirmation Real Filter

## Why It Matters

Constituent data can be stale or superficially aligned.

## Institutional Solution

```text
ConstituentConfirmationQuality =
0.30 × Freshness
+ 0.25 × VWAPAlignment
+ 0.20 × RelativeStrength
+ 0.15 × VolumeConfirmation
+ 0.10 × FuturesConfirmation
```

## Threshold / Veto

```text
>= 70 valid
< 50 ignore constituent confirmation
```

## Integration

Feeds instrument DirectionScore.

## Risk Control

Stale constituent feeds invalidate leadership confidence.

---

# 39. No Same-Direction Recent Loss Penalty Filter

## Why It Matters

A recent loss in a correlated direction can signal regime mismatch.

## Institutional Solution

```text
SameDirectionRecentLossPenalty = 20
```

Apply when:

```text
same-direction index trade appears within 30 minutes after a loss
```

## Threshold / Veto

If candidate no longer A after penalty:

```text
NO_TRADE
```

## Integration

Feeds OpportunityScore and PortfolioNoTrade.

## Risk Control

Prevents disguised revenge trades.

---

# 40. No Daily Risk Pressure Filter

## Why It Matters

Even excellent trades may be inappropriate if daily loss budget is low.

## Institutional Solution

```text
RemainingDailyLossBudget = MaxDailyLoss - RealizedLossToday
MaxRiskNewTrade = min(NormalRiskCap, InstrumentRiskCap, 0.80 × RemainingDailyLossBudget)
```

## Threshold / Veto

```text
PlannedRisk > MaxRiskNewTrade = no trade
```

## Integration

Feeds PortfolioNoTrade.

## Risk Control

Prevents daily drawdown cascade.

---

# 41. MarketHostility Low Filter

## Why It Matters

High hostility can destroy otherwise good trades.

## Institutional Solution

Use MarketHostilityScore.

## Threshold / Veto

```text
<= 35 normal live trade
35–55 defensive/watch only in Phase 1
>55 survival/no trade
>75 hard no-trade
```

## Integration

Feeds OpportunityScore and PortfolioNoTrade.

## Risk Control

In Phase 1, excellent trades require <=35.

---

# 42. PortfolioNoTrade Low Filter

## Why It Matters

The whole opportunity set can be poor even if one candidate ranks highest.

## Institutional Solution

Use PortfolioNoTradeScore.

## Threshold / Veto

```text
>70 hard portfolio no-trade
50–70 no new live trade unless A+ and no systemic risk
```

## Integration

Portfolio-level final gate.

## Risk Control

Prevents best-of-bad trading.

---

# 43. Confidence Not Capped Filter

## Why It Matters

Unvalidated instruments should not receive full confidence.

## Institutional Solution

Use OpportunityConfidenceScore caps.

## Threshold / Veto

```text
Direction + liquidity both unvalidated = no live trade
Liquidity unvalidated = max B / paper unless exceptional
Direction unvalidated = no A+
```

## Integration

Feeds grade and OpportunityScore.

## Risk Control

Prevents false precision.

---

# 44. Calibration Status Acceptable Filter

## Why It Matters

An instrument/setup may not be proven.

## Institutional Solution

Calibration statuses:

```text
UNVALIDATED
OBSERVED
VALIDATED
DEGRADED
RETIRED
```

## Threshold / Veto

```text
RETIRED = no trade
DEGRADED = paper/defensive only
UNVALIDATED = capped grade
```

## Integration

Feeds OpportunityConfidence and InstrumentUncertaintyPenalty.

## Risk Control

Prevents unproven expansion from harming capital.

---

# 45. IV Crush Risk Low Filter

## Why It Matters

IV crush can kill correct-direction options.

## Institutional Solution

Use IVCrushRiskScore.

## Threshold / Veto

```text
<= 50 for excellent candidate
50–70 penalty / stricter threshold
70–85 no new long unless realized move dominates
>85 hard no-trade
```

## Integration

Feeds EV, ConvexityEdge, PortfolioNoTrade.

## Risk Control

Post-event IV requires stabilization.

---

# 46. Gamma Risk Useful Not Chaotic Filter

## Why It Matters

Gamma can help acceleration or create unstable whipsaw.

## Institutional Solution

```text
GammaQualityScore =
0.30 × GammaUsefulness
+ 0.25 × RegimeSuitability
+ 0.20 × ThetaManageability
+ 0.15 × SpreadStability
+ 0.10 × ReversalRiskInverse
```

## Threshold / Veto

```text
>= 70 acceptable
< 50 gamma risk chaotic; no trade
```

## Integration

Feeds ConvexityEdge.

## Risk Control

Avoid expiry gamma in chop/pin regimes.

---

# 47. Theta Cost Acceptable Filter

## Why It Matters

Slow trades lose to theta.

## Institutional Solution

```text
ThetaEfficiency = ExpectedPremiumGainPerMinute / ThetaRiskPerMinute
```

## Threshold / Veto

```text
>= 2.0 required
>= 3.0 for expiry/lunch
< 1.5 reject
```

## Integration

Feeds ConvexityEdge and TimeToProfitProbability.

## Risk Control

Observed decay can override model theta.

---

# 48. Trade Location Asymmetric Filter

## Why It Matters

Good location improves R/R and reduces stop size.

## Institutional Solution

```text
TradeLocationEfficiency =
0.25 × DistanceToInvalidationQuality
+ 0.25 × DistanceToTargetQuality
+ 0.20 × RewardPathOpenness
+ 0.15 × EntryNotExtendedScore
+ 0.15 × TimeOfDayLocationScore
```

## Threshold / Veto

```text
>= 75 required
>= 85 A+
< 60 reject
```

## Integration

Feeds EV and OpportunityScore.

## Risk Control

Do not chase far from invalidation.

---

# 49. Stop Fits and Is Executable Filter

## Why It Matters

A stop can mathematically fit risk cap but be too tight for market noise/spread.

## Institutional Solution

```text
MinimumViableStopPoints = max(2 × spread_points + 2 ticks, instrument_noise_floor)
```

## Threshold / Veto

```text
HardStopPoints < MinimumViableStopPoints = reject
RequiredStopRisk > MaxAllowedRisk = reject
```

## Integration

HardStopFit and ExecutionQuality.

## Risk Control

Prevents unrealistic stops.

---

# 50. Paper-Fill Probability Acceptable Filter

## Why It Matters

If realistic paper fill is unlikely, live execution quality is poor.

## Institutional Solution

```text
PaperFillProbabilityScore =
0.40 × LimitFillProbability
+ 0.25 × SpreadStability
+ 0.20 × DepthCoverage
+ 0.15 × RequoteRiskInverse
```

## Threshold / Veto

```text
>= 75 required
< 60 reject live candidate
```

## Integration

Feeds ExecutionQualityScore.

## Risk Control

No LTP-based fantasy fills.

---

# Final Institutional Summary

The 50 opportunity filters are grouped into eight practical decision layers:

```text
1. EV / VolEdge filters
2. Convexity filters
3. Market structure filters
4. Premium behavior filters
5. Execution/liquidity filters
6. Regime/event filters
7. Confidence/calibration filters
8. Risk-budget/survivability filters
```

Final rule:

```text
A candidate is tradable only when it is not merely the best available,
but objectively excellent across expectancy, convexity, liquidity, timing,
location, and survivability.
```
