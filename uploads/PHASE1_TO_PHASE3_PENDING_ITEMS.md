# Phase 1 to Phase 3 Pending Items Tracker

**Purpose:** Track all remaining pending items from Phase 1 through Phase 3 so they can be reviewed and completed later.

**Current status:**

```text
Core paper-mode foundation exists.
Tests pass.
Live trading is not enabled.
demo_trade = true.
```

This file separates:

```text
A. Pending coding/integration items
B. Pending DHAN/API/live-data validation items
C. Pending paper evidence items
D. Pending live-readiness items
```

---

# PHASE 1 — Full Paper-Mode MVP Intelligence System

## Phase 1 Current Status

```text
Foundation implemented.
Full end-to-end dry-run workflow still pending.
Live trading excluded.
```

---

## 1.1 Pending Integration Items

| ID | Pending Item | Why It Matters | Dependency | Status |
|---|---|---|---|---|
| PENDING-P1-001 | Wire DHAN option-chain fetch into parser | Current parser exists but needs live/API payload flow | DHAN API key / option-chain access | Pending |
| PENDING-P1-002 | Wire parser into CandidateFactory | Required for real candidate generation | P1-001 | Pending |
| PENDING-P1-003 | Build full multi-instrument ranking loop | Required to evaluate all four instruments continuously | CandidateFactory + data snapshots | Pending |
| PENDING-P1-004 | Build real dry-run orchestration loop | Required for repeated ranking cycles | P1-003 | Pending |
| PENDING-P1-005 | Populate full MTIL records from real evaluations | MTIL writer exists but full record population from live flow must be wired | P1-003 | Pending |
| PENDING-P1-006 | Populate skipped-candidate records from real ranking cycles | Skipped writer exists but must be wired into ranking flow | P1-003 | Pending |
| PENDING-P1-007 | Integrate PaperFillSimulator with selected top candidate | Simulator exists but full lifecycle flow needs wiring | P1-003 | Pending |
| PENDING-P1-008 | Integrate simulated trade lifecycle over real quote stream/bars | Lifecycle module exists but needs real/dry-run time-series flow | Live/dry-run data stream | Pending |
| PENDING-P1-009 | Create complete dry-run dashboard page | Basic HTML helper exists; full dashboard shell pending | P1-003/P1-005 | Pending |
| PENDING-P1-010 | Generate daily dry-run summary automatically | Needed for daily review | MTIL data | Pending |
| PENDING-P1-011 | Generate weekly paper performance summary automatically | Needed for Phase 2 review | MTIL data | Pending |
| PENDING-P1-012 | Build full no-trade reason reporting | Required to understand rejected candidates | Ranking flow | Pending |
| PENDING-P1-013 | Build full candidate revalidation flow in orchestration | Revalidation utility exists but must be called before simulated entry | P1-003 | Pending |
| PENDING-P1-014 | Build full global position/order lock flow | Lock logic exists but must be integrated into lifecycle orchestration | Simulated lifecycle | Pending |
| PENDING-P1-015 | Build data availability / UNAVAILABLE / UNVALIDATED propagation | Prevents fake confidence when metrics unavailable | All modules | Pending |

---

## 1.2 Pending DataHealth Items

| ID | Pending Item | Why It Matters | Dependency | Status |
|---|---|---|---|---|
| PENDING-P1-016 | Validate futures quote freshness using real DHAN feed | Needed for DataHealth thresholds | DHAN live feed | Pending |
| PENDING-P1-017 | Validate option quote freshness using real DHAN feed | Needed for PremiumElasticity and paper fills | DHAN live feed | Pending |
| PENDING-P1-018 | Validate option-chain snapshot freshness | Needed for IV/OI/Greeks reliability | DHAN option-chain API | Pending |
| PENDING-P1-019 | Validate reconnect behavior | Needed for no-trade recovery rules | DHAN WebSocket | Pending |
| PENDING-P1-020 | Validate packet gap detection | Required for feed-integrity controls | Live feed | Pending |
| PENDING-P1-021 | Build DataHealth incident log from real events | Required for survivability analysis | Live feed | Pending |

---

## 1.3 Pending Instrument Mapping Items

| ID | Pending Item | Why It Matters | Dependency | Status |
|---|---|---|---|---|
| PENDING-P1-022 | Download latest DHAN detailed instrument master | Needed for actual security IDs | DHAN access / URL availability | Pending |
| PENDING-P1-023 | Validate BANKNIFTY futures/options mapping | Prevent wrong instrument selection | Instrument master | Pending |
| PENDING-P1-024 | Validate NIFTY futures/options mapping | Same | Instrument master | Pending |
| PENDING-P1-025 | Validate FINNIFTY futures/options mapping | Same | Instrument master | Pending |
| PENDING-P1-026 | Validate MIDCPNIFTY futures/options mapping | Same | Instrument master | Pending |
| PENDING-P1-027 | Confirm lot sizes per instrument | Required for risk calculations | Instrument master | Pending |
| PENDING-P1-028 | Confirm tick sizes via live bid/ask increments | Required for simulated order prices | Live quotes | Pending |
| PENDING-P1-029 | Confirm expiry calendars per instrument | Required for DTE and candidate selection | Expiry-list API | Pending |
| PENDING-P1-030 | Confirm strike ladders per instrument | Required for ATM/ITM/OTM selection | Option-chain API | Pending |

---

## 1.4 Pending Calibration Baselines

| ID | Pending Item | Why It Matters | Dependency | Status |
|---|---|---|---|---|
| PENDING-P1-031 | Build BANKNIFTY spread baseline | ContractQuality calibration | Live dry-run data | Pending |
| PENDING-P1-032 | Build NIFTY spread baseline | Same | Live dry-run data | Pending |
| PENDING-P1-033 | Build FINNIFTY spread baseline | Same | Live dry-run data | Pending |
| PENDING-P1-034 | Build MIDCPNIFTY spread baseline | Midcap live eligibility | Live dry-run data | Pending |
| PENDING-P1-035 | Build instrument-specific slippage baselines | Paper-fill realism | Dry-run data | Pending |
| PENDING-P1-036 | Build premium elasticity baselines | Ranking calibration | Dry-run data | Pending |
| PENDING-P1-037 | Build expected-move accuracy baselines | VolEdge calibration | Dry-run data | Pending |
| PENDING-P1-038 | Build IV refresh and IV stability baselines | IVCrushRisk calibration | Option-chain API | Pending |
| PENDING-P1-039 | Build OI refresh behavior baseline | OI wall / forced-flow reliability | Option-chain API | Pending |
| PENDING-P1-040 | Build Midcap liquidity baseline | Required before Midcap live eligibility | 20 trading days data | Pending |

---

## 1.5 Pending Advanced Score Wiring

These calculators/fields exist conceptually or as primitives, but full market-data driven calculation is still pending.

| ID | Pending Item | Why It Matters | Dependency | Status |
|---|---|---|---|---|
| PENDING-P1-041 | Full ForcedFlowScore calculation from real data | Breakout quality | Option/futures data | Pending |
| PENDING-P1-042 | Full LiquidityVacuumScore calculation | Reward path quality | Market structure data | Pending |
| PENDING-P1-043 | Full RangeExpansionQuality calculation | Breakout acceptance | Price/premium data | Pending |
| PENDING-P1-044 | Full TrendExhaustionRisk calculation | Late-entry avoidance | Price/premium data | Pending |
| PENDING-P1-045 | Full OppositePremiumFailure calculation | Directional premium validation | CE/PE quotes | Pending |
| PENDING-P1-046 | Full TimeToProfitProbability calculation | Theta efficiency | Trade lifecycle data | Pending |
| PENDING-P1-047 | Full TradeLocationEfficiency calculation | R/R quality | Market structure data | Pending |
| PENDING-P1-048 | Full RewardPathScore calculation | Obstacle-aware selection | Market structure data | Pending |
| PENDING-P1-049 | Full OpportunityHalfLife enforcement by archetype | Avoid stale trades | Archetype tagging | Pending |
| PENDING-P1-050 | Full DirectionalOptionBreadthScore calculation | Strike cluster confirmation | Option-chain data | Pending |

---

# PHASE 2 — Paper Validation, Calibration, and Evidence Review

## Phase 2 Current Status

```text
Validator and analyzer foundation implemented.
Real evidence cannot be produced until Phase 1 dry-run generates MTIL/skipped data.
```

---

## 2.1 Pending Evidence Collection Items

| ID | Pending Item | Requirement | Dependency | Status |
|---|---|---|---|---|
| PENDING-P2-001 | Run 20 trading days of dry-run capture | Minimum evidence period | Phase 1 dry-run loop | Pending |
| PENDING-P2-002 | Record 100+ ranking cycles | Ranking validation | Phase 1 dry-run loop | Pending |
| PENDING-P2-003 | Record 50+ simulated candidates | Basic paper sample | Phase 1 candidate lifecycle | Pending |
| PENDING-P2-004 | Verify 0 critical mapping errors in final 5 dry-run days | Mapping readiness | Phase 1 logs | Pending |
| PENDING-P2-005 | Verify 0 wrong lot-size calculations | Risk readiness | Phase 1 logs | Pending |
| PENDING-P2-006 | Verify 0 wrong tick-size calculations | Price validity | Phase 1 logs | Pending |
| PENDING-P2-007 | Verify candidate revalidation evidence | Execution readiness | Phase 1 logs | Pending |
| PENDING-P2-008 | Verify paper-fill simulator evidence | Fill realism | Phase 1 logs | Pending |
| PENDING-P2-009 | Verify MTIL completeness | Data quality | MTIL logs | Pending |
| PENDING-P2-010 | Verify skipped-candidate completeness | No-trade learning | Skipped logs | Pending |
| PENDING-P2-011 | Validate dashboard latency pass rate | Operational readiness | Dashboard telemetry | Pending |
| PENDING-P2-012 | Verify emergency tests passed | Survivability readiness | Emergency test suite | Pending |

---

## 2.2 Pending Analysis Items

| ID | Pending Item | Why It Matters | Dependency | Status |
|---|---|---|---|---|
| PENDING-P2-013 | Analyze net paper expectancy | Determines whether system has edge | MTIL data | Pending |
| PENDING-P2-014 | Analyze win rate and profit factor | Basic performance review | MTIL data | Pending |
| PENDING-P2-015 | Analyze max paper drawdown | Survival assessment | MTIL data | Pending |
| PENDING-P2-016 | Analyze performance by instrument | Instrument selection quality | MTIL data | Pending |
| PENDING-P2-017 | Analyze performance by archetype | Setup quality | MTIL data | Pending |
| PENDING-P2-018 | Analyze performance by regime | Regime fit | MTIL data | Pending |
| PENDING-P2-019 | Analyze skipped winners | Check over-filtering | Skipped logs | Pending |
| PENDING-P2-020 | Analyze no-trade saved losses | Validate no-trade filters | Skipped logs | Pending |
| PENDING-P2-021 | Analyze premium failure frequency | Validate elasticity/convexity | MTIL data | Pending |
| PENDING-P2-022 | Analyze slippage assumptions | Validate paper-fill realism | MTIL data | Pending |
| PENDING-P2-023 | Analyze OpportunityScore calibration | Ranking quality | MTIL data | Pending |
| PENDING-P2-024 | Analyze EV model calibration | Expectancy quality | MTIL data | Pending |
| PENDING-P2-025 | Analyze VolEdge calibration | Move forecast quality | MTIL data | Pending |
| PENDING-P2-026 | Analyze Midcap monitor-only data | Decide if Midcap remains monitor-only | Midcap dry-run data | Pending |
| PENDING-P2-027 | Generate daily dry-run reports | Review workflow | MTIL data | Pending |
| PENDING-P2-028 | Generate weekly paper performance reports | Evidence review | MTIL data | Pending |

---

# PHASE 3 — Manual Live Review and Controlled Deployment Preparation

## Phase 3 Current Status

```text
Readiness-review framework implemented.
Live trading remains blocked.
Phase 3 cannot approve live orders by itself.
```

---

## 3.1 Pending Live-Readiness Review Items

| ID | Pending Item | Why It Matters | Dependency | Status |
|---|---|---|---|---|
| PENDING-P3-001 | Conduct investment committee review of Phase 2 results | Governance before live | Phase 2 complete | Pending |
| PENDING-P3-002 | Confirm system remains no-live-order by default | Prevent accidental execution | Config review | Pending |
| PENDING-P3-003 | Verify cost model with actual broker/statutory rates | Net P&L accuracy | Broker details | Pending |
| PENDING-P3-004 | Verify emergency exit plan | Live survivability | Broker access later | Pending |
| PENDING-P3-005 | Verify daily loss lock design | Live risk control | Future live controls | Pending |
| PENDING-P3-006 | Verify no rule-violation pattern in paper phase | Behavioral readiness | Phase 2 evidence | Pending |
| PENDING-P3-007 | Finalize manual-live checklist | Human process control | Phase 2 evidence | Pending |
| PENDING-P3-008 | Finalize paper-vs-live fill comparison plan | Execution validation | Phase 2 evidence | Pending |
| PENDING-P3-009 | Finalize live micro-test size rules | Risk containment | Committee approval | Pending |
| PENDING-P3-010 | Finalize criteria to stop live test | Survival control | Committee approval | Pending |

---

## 3.2 Deferred Manual Live Micro-Test Items

These must remain deferred until explicit approval.

| ID | Pending Item | Rule | Status |
|---|---|---|---|
| PENDING-P3-011 | Enable manual-live mode | Only after committee approval | Deferred |
| PENDING-P3-012 | Keep max position = 1 | Non-negotiable | Deferred |
| PENDING-P3-013 | Compare live fills vs paper fills | Required immediately if live test begins | Deferred |
| PENDING-P3-014 | Log live trades into MTIL | Mandatory if live test begins | Deferred |
| PENDING-P3-015 | Stop if slippage materially exceeds paper model | Mandatory stop rule | Deferred |
| PENDING-P3-016 | Stop if any rule violation occurs | Mandatory stop rule | Deferred |
| PENDING-P3-017 | Confirm static IP / Dhan order API requirements | Required before any real order | Deferred |
| PENDING-P3-018 | Confirm broker app/web emergency exit path | Required before live | Deferred |

---

# DHAN/API Dependent Items

The following larger tracker contains detailed DHAN/API-specific pending items:

```text
uploads/DHAN_API_DEPENDENT_PENDING_ITEMS.md
```

Use that file once DHAN API credentials are available.

---

# Current No-Live-Trading Rule

Until all Phase 1, Phase 2, and Phase 3 pending items are resolved:

```text
demo_trade must remain true.
No live broker order placement.
No auto-execution.
No real capital deployment.
```

---

# Final Status Summary

```text
Phase 1 foundation: implemented, integration/data validation pending.
Phase 2 foundation: implemented, evidence collection pending.
Phase 3 foundation: implemented, live-readiness evidence pending.
Live trading: not approved.
```
