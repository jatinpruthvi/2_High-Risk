# Phase 1 Pre-Coding Core Strategy Fixes

**Purpose:** Resolve the remaining roadblock before coding: improve opportunity selection through strict ranking without increasing position count, risk, drawdown, or probability of ruin.

**Final operating doctrine:**

```text
More instruments must improve selection quality, not trade frequency.
The system must not find something to trade.
It must prove that one candidate is excellent enough to deserve capital.
```

---

## 1. Final Roadblock Diagnosis

The current Phase 1 architecture is strong, but the roadblock is not the idea of ranking itself. The roadblock is **false confidence from ranking before calibration**.

A ranking engine can fail if:

- all instruments are mediocre and one is merely least bad,
- the scores are not comparable across instruments,
- Nifty/FinNifty/Midcap direction models are not validated,
- Midcap liquidity is not proven,
- paper fills are unrealistic,
- the top candidate becomes stale before order placement,
- the trader treats rank as authority rather than evidence.

Therefore the fix is:

```text
Strict ranking + excellence gate + calibration caps + paper mode + final revalidation.
```

---

## 2. Final Pre-Coding Improvements

## 2.1 Deployment State Machine

The system must not jump directly from specification to live trading.

```text
DESIGN
→ DRY_RUN
→ PAPER_RANKING
→ MANUAL_MICRO_LIVE
→ VALIDATED_MANUAL
→ AUTOMATION_REVIEW_ONLY
```

### State Rules

| State | Trading Permission |
|---|---|
| DESIGN | No market connection required; no trades |
| DRY_RUN | Live data allowed; no paper/live trades |
| PAPER_RANKING | Paper fills only; no real orders |
| MANUAL_MICRO_LIVE | Manual real order allowed only after acceptance criteria pass |
| VALIDATED_MANUAL | Manual live trading with reviewed thresholds |
| AUTOMATION_REVIEW_ONLY | Automation can be studied, not activated |

Initial state:

```text
DRY_RUN / PAPER_RANKING only
```

Hard rule:

```text
No live trading until dry-run acceptance criteria pass.
```

---

## 2.2 Comparable OpportunityScore Rule

Scores across instruments must be comparable.

Raw scores are not enough because:

- Bank Nifty has stronger convexity but higher whipsaw.
- Nifty has better liquidity but lower movement velocity.
- FinNifty overlaps with financial-sector risk.
- Midcap may show high movement but uncertain execution.

### Final Comparable Score

```text
ComparableOpportunityScore_i =
RawOpportunityScore_i
- CalibrationPenalty_i
- LiquidityUncertaintyPenalty_i
- ExecutionUncertaintyPenalty_i
- RegimeMismatchPenalty_i
- StalenessPenalty_i
```

Live ranking uses:

```text
ComparableOpportunityScore
```

not raw score alone.

---

## 2.3 Calibration Caps

Before an instrument is validated, its grade must be capped.

| Calibration Status | Maximum Live Grade |
|---|---|
| Direction and liquidity both unvalidated | No live trade |
| Direction unvalidated only | Max A, no A+ |
| Liquidity unvalidated only | Max B / paper only unless exceptional validation exists |
| Expected move unvalidated | Max A, no A+ |
| Fully validated | Full grading allowed |

### Initial Phase 1 Status

| Instrument | Initial Live Status |
|---|---|
| BANKNIFTY | Eligible after dry-run; still provisional |
| NIFTY | Paper-ranking until direction and liquidity observed |
| FINNIFTY | Paper-ranking until direction and liquidity observed |
| MIDCPNIFTY | Monitor-only until liquidity baseline passes |

This prevents false confidence from unvalidated instruments.

---

## 2.4 Midcap Nifty Monitor-Only Default

Midcap Nifty may be evaluated but should not be live-selectable initially.

```text
MIDCPNIFTY default = MONITOR_ONLY
```

It becomes live-eligible only after:

```text
20 trading days baseline
100 ranking cycles
20 excellent candidate observations
median spread acceptable
no repeated no-bid events
paper-fill slippage acceptable
quote freshness stable
```

Until then:

```text
MIDCPNIFTY can appear on dashboard as research/monitoring only.
```

---

## 2.5 Per-Instrument Liquidity Normalization

A single spread threshold can be dangerous.

Use both:

```text
spread percentage
absolute spread points
depth coverage ratio
quote freshness
paper-fill probability
```

### Depth Coverage Ratio

```text
TopBookCoverage = min(best_bid_qty, best_ask_qty) / order_qty
FiveDepthCoverage = min(cum_bid_qty_5depth, cum_ask_qty_5depth) / order_qty
```

Minimum excellent thresholds:

```text
TopBookCoverage >= 5
FiveDepthCoverage >= 10
QuoteFresh = true
Spread stable for 2 ranking windows
```

### Provisional Excellent Spread Thresholds

| Instrument | Excellent Spread % | Hard Reject Spread % |
|---|---:|---:|
| BANKNIFTY | <= 1.5% | > 2.0% |
| NIFTY | <= 1.0% | > 1.5% |
| FINNIFTY | <= 1.5% | > 2.5% |
| MIDCPNIFTY | <= 1.25% | > 2.0% |

These are provisional and must be replaced by observed baselines.

---

## 2.6 Opportunity Decay and Re-Ranking

A candidate is perishable.

```text
Fast market candidate max age = 5 seconds
Normal market candidate max age = 15 seconds
Slow market candidate max age = 30 seconds only if quotes stable
```

If candidate age exceeds limit:

```text
REVALIDATE_REQUIRED
```

If the top candidate fails final revalidation:

```text
Recalculate all candidates.
Do not automatically trade rank #2.
```

If the same candidate flickers in/out of A-grade:

```text
Wait for 2 consecutive valid ranking windows.
```

---

## 2.7 Opportunity Scarcity Protection

The system must not degrade standards due to lack of trades.

Rules:

```text
No B-grade live trades.
No threshold lowering after quiet days.
No size increase after missed winners.
No switching to Midcap to force action.
No trading simply because one instrument is ranked highest.
```

If no trades occur for 5 sessions:

```text
Review skipped-candidate journal.
Do not alter thresholds without sufficient sample.
```

---

## 2.8 Expected Range Consumed Filter

An instrument may rank high after much of the move has already happened.

```text
RangeConsumedRatio_i = IntradayMoveSoFar_i / RealisticDailyExpectedMove_i
```

Rules:

```text
If RangeConsumedRatio > 0.60:
    require A+ only

If RangeConsumedRatio > 0.75:
    no new long option unless fresh breakout/vol expansion occurs
```

This prevents late premium chasing.

---

## 2.9 Candidate Quality Must Be Asymmetric

A candidate must show measurable asymmetry:

```text
ExpectedMove / RequiredMove >= 1.60
ConvexityQualityScore >= 80
ExecutionQualityScore >= 80
PremiumElasticity >= 1.00
```

If any fail:

```text
No live trade, regardless of rank.
```

---

## 2.10 Portfolio No-Trade Final Rule

Portfolio no-trade occurs when the best candidate is not excellent.

```text
if max(OpportunityGrade) < A:
    NO_TRADE
```

Also no-trade if:

```text
PortfolioNoTradeScore > 70
Daily risk budget insufficient
Top candidate stale
Top candidate fails revalidation
Top two candidates ambiguous after tie-break
Broad event/tail risk active
```

---

## 3. Final Pre-Coding Architecture

```text
1. Load DHAN master.
2. Validate per-instrument mapping, lot size, tick size, expiry, strike.
3. Subscribe to required data feeds.
4. Build CE/PE candidates for all eligible instruments.
5. Apply hard gates.
6. Calculate per-instrument direction, trade quality, convexity, execution quality, regime fit, confidence.
7. Calculate ComparableOpportunityScore.
8. Apply calibration caps.
9. Apply PortfolioNoTradeScore.
10. Grade candidates A+/A/B/C/Reject.
11. Require rank persistence.
12. Revalidate top candidate.
13. Trade only if top candidate remains A or A+.
14. If none excellent, no trade.
```

---

## 4. Final Coding Priorities

Code in this order:

1. Instrument master loader and validator.
2. Per-instrument lot/tick/expiry map.
3. DataHealth per instrument.
4. ContractQuality per instrument.
5. Paper-fill simulator.
6. Per-instrument ExpectedMove model.
7. Candidate generator.
8. Candidate hard gates.
9. Direction proxies.
10. ConvexityQualityScore.
11. ExecutionQualityScore.
12. OpportunityConfidenceScore.
13. ComparableOpportunityScore.
14. PortfolioNoTradeScore.
15. Ranking and tie-break logic.
16. Candidate revalidation.
17. Journal and skipped-candidate log.
18. Dashboard.
19. Dry-run acceptance report.

---

## 5. Final Pre-Coding Verdict

The core strategy is improved by adding strict opportunity ranking, but only if ranking is subordinate to:

```text
Hard gates
Excellent grade requirement
Calibration status
Execution quality
Convexity quality
Portfolio no-trade logic
Candidate revalidation
```

Final rule:

```text
More instruments should increase selectivity, not activity.
```
