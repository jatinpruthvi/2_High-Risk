# Full Functional Paper-System Scope — Final Pre-Coding Clarification

**Purpose:** Clarify whether anything remains partially ready or pending before coding the complete non-live paper/MTIL system.

**Final decision:** Build the complete paper-mode system upfront. Do not build modules step-by-step in a way that causes later integration bugs. The only skipped component is live broker order placement.

---

## 1. Final Coding Scope

The first implementation must include the complete paper-mode intelligence system:

```text
Instrument master loader
Per-instrument mapping
Lot-size / tick-size validation
Data capture
Candidate generation
All four instruments: BANKNIFTY, NIFTY, FINNIFTY, MIDCPNIFTY
Opportunity ranking
ComparableOpportunityScore
PortfolioNoTradeScore
OpportunityGrade
ExpectedValue_R
VolEdgeRatio
ConvexityEdgeScore
ExecutionQualityScore
OpportunityConfidenceScore
MarketHostilityScore
IVCrushRiskScore
PremiumElasticity
ContractQualityScore
Paper-fill simulator
Simulated entry
Simulated exit
MTIL logging
Skipped-candidate logging
Trade archetype tagging
Performance analytics
Dry-run acceptance report
Global position/order lock
Candidate revalidation
No-trade reporting
```

Do not code live order placement in this phase.

---

## 2. Readiness Reclassification

The following items were previously described as partially ready because they are not live-validated. For paper-mode implementation they are now classified as:

```text
FULLY SPECIFIED FOR PAPER MODE
PROVISIONAL UNTIL VALIDATED FOR LIVE TRADING
```

| Item | Paper-Mode Status | Live Status |
|---|---|---|
| Nifty direction model | Fully specified with proxy + penalty | Needs validation |
| FinNifty direction model | Fully specified with proxy + penalty | Needs validation |
| Midcap Nifty direction model | Fully specified as monitor/conditional model | Needs liquidity validation |
| Midcap liquidity thresholds | Fully specified as strict provisional thresholds | Needs baseline validation |
| ExpectedValue_R | Fully specified with conservative provisional probabilities | Needs calibration |
| VolEdgeRatio | Fully specified | Needs instrument calibration |
| OpportunityScore | Fully specified | Needs performance validation |
| Paper-fill simulator | Fully specified | Needs paper/live comparison later |
| Cost model | Formula fully specified; rates configurable | Needs broker/statutory confirmation |
| AI layer | Roadmap only, not MVP | Not production |
| GEX/CVD/stock chains | Research fields only if available | Not production gates |

---

## 3. What Is Still Not Knowable Before Data

These are not specification gaps. They are empirical calibration items:

```text
Actual spread baseline by instrument/time
Actual slippage baseline by instrument/time
Actual premium elasticity baseline
Actual expected-move accuracy
Actual Nifty/FinNifty/Midcap direction model effectiveness
Actual paper-fill vs live-fill difference
Actual setup expectancy
Actual instrument ranking quality
```

The system must log these from day one.

---

## 4. No Partial Build Rule

Do not implement only a minimal subset if that creates future integration risk.

The first paper-mode build must include all core modules, even if some modules output:

```text
UNVALIDATED
UNAVAILABLE
PAPER_ONLY
MONITOR_ONLY
```

Rules:

```text
If metric unavailable: mark UNAVAILABLE, do not fake it.
If metric unvalidated: apply calibration penalty.
If instrument unvalidated: cap grade or monitor-only.
If data invalid: exclude candidate or no-trade.
```

---

## 5. Complete MVP Module List

### Required Core Modules

```text
1. InstrumentMasterModule
2. InstrumentMappingModule
3. LotTickValidationModule
4. DataHealthModule
5. CandidateGenerationModule
6. ContractQualityModule
7. PremiumElasticityModule
8. ExpectedMoveRequiredMoveModule
9. IVCrushRiskModule
10. DirectionModelModule
11. OpportunityScoringModule
12. ExcellenceGradeModule
13. PortfolioNoTradeModule
14. MarketHostilityModule
15. ExpectedValueModule
16. VolEdgeModule
17. ConvexityEdgeModule
18. ExecutionQualityModule
19. OpportunityConfidenceModule
20. CandidateRevalidationModule
21. GlobalPositionLockModule
22. PaperFillSimulator
23. SimulatedTradeLifecycleModule
24. MTILLogger
25. SkippedCandidateLogger
26. TradeArchetypeTagger
27. PerformanceAnalyticsModule
28. DryRunAcceptanceModule
29. DashboardShell
```

### Research/Optional Fields To Log If Available

```text
GEX scenario
CVD/order-flow proxy
stock option-chain enrichment
20-depth fields
AI advisory fields
```

These are not trade gates in MVP.

---

## 6. Live Trading Still Excluded

The following are explicitly excluded from the first build:

```text
Live order placement
Auto execution
Broker order routing
Real capital deployment
Multiple open positions
Option selling
Leverage
Pledge
B-grade live trades
Rank #2 auto-switch
```

---

## 7. Final Readiness Statement

For the complete paper-mode system:

```text
READY FOR CODING
```

For live trading:

```text
NOT READY UNTIL DRY-RUN ACCEPTANCE PASSES
```

Final doctrine:

```text
Build the full intelligence system now.
Trade capital later.
```
