# Master TODO — Institutional Multi-Instrument Option-Buying System

**Project objective:** Build a survivability-first, multi-instrument index option-buying intelligence system that evaluates BANKNIFTY, NIFTY, FINNIFTY, and MIDCPNIFTY, ranks all opportunities, trades only the best excellent candidate in paper mode first, and evolves through evidence from MTIL.

**Primary optimization goals:**

1. Maximum 10-year survivability
2. Minimum drawdown
3. Maximum risk-adjusted ROI
4. Minimum probability of ruin
5. Maximum robustness
6. Maximum opportunity quality
7. Institutional-grade trade intelligence

**Current implementation decision:**

```text
Build complete Phase 1 paper-mode / dry-run / MTIL-functional intelligence system.
Do not build live order placement yet.
Do not build auto-execution yet.
```

**Frozen core rules:**

```text
Universe = BANKNIFTY, NIFTY, FINNIFTY, MIDCPNIFTY
Maximum open positions = 1
Maximum pending orders = 1
No live orders in MVP
No auto-execution in MVP
No leverage
No pledge
No overnight holding
No option selling
No B-grade live trades
No rank #2 auto-switch
No new instruments during MVP
No threshold lowering during dry-run
```

---

# Priority Legend

| Priority | Meaning |
|---|---|
| P0 | Critical foundation / must build first |
| P1 | High priority for MVP completion |
| P2 | Important after MVP foundation is stable |
| P3 | Future research / post-validation |

---

# Status Legend

| Status | Meaning |
|---|---|
| NOT_STARTED | Not yet implemented |
| IN_PROGRESS | Currently being worked on |
| BLOCKED | Cannot continue until dependency resolved |
| DONE | Completed |
| DEFERRED | Intentionally delayed |

---

# PHASE 1 — Full Paper-Mode MVP Intelligence System

**Goal:** Build the complete non-live intelligence engine that can evaluate all instruments, rank candidates, simulate entries/exits, log MTIL, and produce paper-mode performance analytics.

**Live trading status:** Not allowed.

**Phase 1 exit criteria:**

```text
20 trading days dry-run captured
100+ ranking cycles recorded
50+ simulated candidates recorded
MTIL logging complete
paper-fill simulator active
candidate revalidation working
global position lock working
no critical mapping errors in final 5 dry-run days
all emergency tests pass
```

---

## 1.1 Project Setup and Configuration

| ID | Priority | TODO | Why It Matters | Dependencies | Status |
|---|---|---|---|---|---|
| P1-001 | P0 | Create project folder structure | Prevents messy implementation and future refactor bugs | None | NOT_STARTED |
| P1-002 | P0 | Create central configuration structure | All thresholds and rules must be controlled from config | PARAMETERS.json | NOT_STARTED |
| P1-003 | P0 | Load and validate `PARAMETERS.json` | Prevents silent parameter mismatch | P1-002 | NOT_STARTED |
| P1-004 | P0 | Load instrument universe config | Ensures only approved instruments are evaluated | P1-003 | NOT_STARTED |
| P1-005 | P0 | Freeze MVP scope in project config | Prevents feature creep during coding | P1-003 | NOT_STARTED |
| P1-006 | P0 | Add environment mode flag: DRY_RUN / PAPER / LIVE_DISABLED | Ensures no accidental live order logic | P1-003 | NOT_STARTED |
| P1-007 | P0 | Add hard global flag disabling live orders | Critical survivability control | P1-006 | NOT_STARTED |
| P1-008 | P1 | Create parameter validation checklist | Catches missing or malformed settings | P1-003 | NOT_STARTED |
| P1-009 | P1 | Create threshold status labels: provisional / observed / validated | Prevents false precision | P1-003 | NOT_STARTED |
| P1-010 | P1 | Create change log for parameter updates | Required for governance and audit | P1-009 | NOT_STARTED |

---

## 1.2 Instrument Master and Mapping

| ID | Priority | TODO | Why It Matters | Dependencies | Status |
|---|---|---|---|---|---|
| P1-011 | P0 | Download/load DHAN detailed instrument master | Required for correct security IDs | Project setup | NOT_STARTED |
| P1-012 | P0 | Map BANKNIFTY futures and options | Required for candidate generation | P1-011 | NOT_STARTED |
| P1-013 | P0 | Map NIFTY futures and options | Required for multi-instrument ranking | P1-011 | NOT_STARTED |
| P1-014 | P0 | Map FINNIFTY futures and options | Required for multi-instrument ranking | P1-011 | NOT_STARTED |
| P1-015 | P0 | Map MIDCPNIFTY futures and options | Required for monitoring / conditional ranking | P1-011 | NOT_STARTED |
| P1-016 | P0 | Validate lot size per selected contract | Prevents wrong risk sizing | P1-012 to P1-015 | NOT_STARTED |
| P1-017 | P0 | Validate tick size per selected contract | Prevents invalid simulated order prices | P1-012 to P1-015 | NOT_STARTED |
| P1-018 | P0 | Validate expiry calendar per instrument | Prevents wrong DTE and wrong contract | P1-012 to P1-015 | NOT_STARTED |
| P1-019 | P0 | Validate strike ladder per instrument | Prevents selecting non-existent strikes | P1-012 to P1-015 | NOT_STARTED |
| P1-020 | P0 | Add hard veto for missing/stale/duplicated mapping | Prevents wrong instrument trading | P1-011 | NOT_STARTED |
| P1-021 | P1 | Track instrument master date and age | Prevents stale mapping use | P1-011 | NOT_STARTED |
| P1-022 | P1 | Create mapping audit report | Required for dry-run acceptance | P1-011 to P1-020 | NOT_STARTED |

---

## 1.3 Data Capture and DataHealth

| ID | Priority | TODO | Why It Matters | Dependencies | Status |
|---|---|---|---|---|---|
| P1-023 | P0 | Capture futures quote data per instrument | Required for direction, expected move, elasticity | Instrument mapping | NOT_STARTED |
| P1-024 | P0 | Capture selected option quote data | Required for premium, spread, paper fills | Instrument mapping | NOT_STARTED |
| P1-025 | P0 | Capture option-chain snapshots | Required for IV, OI, walls, PCR context | Instrument mapping | NOT_STARTED |
| P1-026 | P0 | Track quote freshness per instrument | DataHealth gate | P1-023, P1-024 | NOT_STARTED |
| P1-027 | P0 | Track option-chain freshness | Prevents stale IV/OI decisions | P1-025 | NOT_STARTED |
| P1-028 | P0 | Track packet gaps / feed gaps | Prevents corrupted state | P1-023, P1-024 | NOT_STARTED |
| P1-029 | P0 | Implement DataHealth status per instrument | Candidate gate | P1-026 to P1-028 | NOT_STARTED |
| P1-030 | P0 | Implement global DataHealth status | Portfolio no-trade input | P1-029 | NOT_STARTED |
| P1-031 | P1 | Track data availability per module | Helps identify missing/UNAVAILABLE metrics | P1-029 | NOT_STARTED |
| P1-032 | P1 | Create DataHealth incident log | Required for survivability review | P1-030 | NOT_STARTED |
| P1-033 | P1 | Create reconnect/recovery status flag | Prevents trading after unstable reconnect | P1-030 | NOT_STARTED |

---

## 1.4 Candidate Generation

| ID | Priority | TODO | Why It Matters | Dependencies | Status |
|---|---|---|---|---|---|
| P1-034 | P0 | Generate CE and PE candidates for each instrument | Core multi-instrument opportunity set | Instrument mapping, data capture | NOT_STARTED |
| P1-035 | P0 | Select ATM / near-ATM / ITM candidate contracts | Avoids far OTM lottery behavior | P1-034 | NOT_STARTED |
| P1-036 | P0 | Attach instrument-specific lot size to each candidate | Required for risk and paper fill | P1-016 | NOT_STARTED |
| P1-037 | P0 | Attach current bid/ask/mid to each candidate | Required for all option scoring | P1-024 | NOT_STARTED |
| P1-038 | P0 | Attach candidate timestamp | Required for half-life / revalidation | P1-034 | NOT_STARTED |
| P1-039 | P1 | Add candidate age status | Prevents stale entry decisions | P1-038 | NOT_STARTED |
| P1-040 | P1 | Add candidate availability status: VALID / INVALID / UNAVAILABLE | Prevents faking missing metrics | P1-034 | NOT_STARTED |

---

## 1.5 Core Quality Scores

| ID | Priority | TODO | Why It Matters | Dependencies | Status |
|---|---|---|---|---|---|
| P1-041 | P0 | Implement ContractQualityScore | Blocks bad contracts | Candidate data | NOT_STARTED |
| P1-042 | P0 | Implement SpreadScore | Direct execution cost | P1-041 | NOT_STARTED |
| P1-043 | P0 | Implement LiquidityScore | Exit and fill quality | P1-041 | NOT_STARTED |
| P1-044 | P0 | Implement DeltaResponsivenessScore | Strike efficiency | P1-041 | NOT_STARTED |
| P1-045 | P0 | Implement GammaSuitabilityScore | Convexity quality | P1-041 | NOT_STARTED |
| P1-046 | P0 | Implement ThetaSafetyScore | Theta survival | P1-041 | NOT_STARTED |
| P1-047 | P0 | Implement IVFairnessScore | IV risk awareness | P1-041 | NOT_STARTED |
| P1-048 | P0 | Implement PremiumElasticity | Core option-buyer gate | Candidate data, futures data | NOT_STARTED |
| P1-049 | P0 | Implement ExpectedMove / RequiredMove | Avoids unrealistic trades | Candidate + futures data | NOT_STARTED |
| P1-050 | P0 | Implement IVCrushRiskScore | Avoids premium destruction | Option-chain data | NOT_STARTED |
| P1-051 | P0 | Implement ExecutionQualityScore | Prevents bad simulated fills | Liquidity + paper fill | NOT_STARTED |
| P1-052 | P0 | Implement ConvexityEdgeScore | Ensures option worth owning | Elasticity + gamma + IV + timing | NOT_STARTED |
| P1-053 | P0 | Implement OpportunityConfidenceScore | Prevents false confidence | Calibration + data status | NOT_STARTED |
| P1-054 | P1 | Implement unavailable-metric handling | Prevents fake scores | P1-041 to P1-053 | NOT_STARTED |
| P1-055 | P1 | Log every score component to MTIL | Enables future alpha discovery | MTIL | NOT_STARTED |

---

## 1.6 Direction Models

| ID | Priority | TODO | Why It Matters | Dependencies | Status |
|---|---|---|---|---|---|
| P1-056 | P0 | Implement BANKNIFTY FastWBCI | Bank Nifty direction model | Data capture | NOT_STARTED |
| P1-057 | P0 | Implement NIFTY direction proxy | Nifty ranking needs direction score | Data capture | NOT_STARTED |
| P1-058 | P0 | Implement FINNIFTY direction proxy | FinNifty ranking needs direction score | Data capture | NOT_STARTED |
| P1-059 | P0 | Implement MIDCPNIFTY direction proxy | Midcap monitor/ranking context | Data capture | NOT_STARTED |
| P1-060 | P0 | Apply unvalidated direction penalties | Prevents false confidence | P1-057 to P1-059 | NOT_STARTED |
| P1-061 | P1 | Create NIFTY weights config placeholder | Enables future weighted model | P1-057 | NOT_STARTED |
| P1-062 | P1 | Create FINNIFTY weights config placeholder | Enables future weighted model | P1-058 | NOT_STARTED |
| P1-063 | P1 | Track direction model calibration status | Required for confidence caps | P1-056 to P1-059 | NOT_STARTED |

---

## 1.7 Edge and Opportunity Scores

| ID | Priority | TODO | Why It Matters | Dependencies | Status |
|---|---|---|---|---|---|
| P1-064 | P0 | Implement ExpectedValue_R | Converts score to expectancy | Core scores + cost model | NOT_STARTED |
| P1-065 | P0 | Implement VolEdgeRatio | Core option-buyer edge | ExpectedMove module | NOT_STARTED |
| P1-066 | P0 | Implement OpportunityScore | Core candidate ranking | Core scores | NOT_STARTED |
| P1-067 | P0 | Implement ComparableOpportunityScore | Makes cross-instrument scores comparable | OpportunityScore + penalties | NOT_STARTED |
| P1-068 | P0 | Implement OpportunityGrade | A+/A/B/C/Reject classification | P1-066, P1-067 | NOT_STARTED |
| P1-069 | P0 | Implement DynamicExcellentThreshold | Stricter in hard regimes | Risk/regime data | NOT_STARTED |
| P1-070 | P0 | Implement PortfolioNoTradeScore | Prevents best-of-weak trades | Candidate universe | NOT_STARTED |
| P1-071 | P1 | Implement ForcedFlowScore | Improves breakout alpha | Option/futures data | NOT_STARTED |
| P1-072 | P1 | Implement LiquidityVacuumScore | Reward path quality | Technical/option data | NOT_STARTED |
| P1-073 | P1 | Implement RangeExpansionQuality | Breakout quality | Technical + premium data | NOT_STARTED |
| P1-074 | P1 | Implement TrendExhaustionRisk | Avoids late entries | Technical + premium data | NOT_STARTED |
| P1-075 | P1 | Implement OppositePremiumFailure | Directional premium confirmation | Option quote data | NOT_STARTED |
| P1-076 | P1 | Implement TimeToProfitProbability | Theta efficiency | Premium + regime data | NOT_STARTED |
| P1-077 | P1 | Implement TradeLocationEfficiency | Risk/reward quality | Technical data | NOT_STARTED |
| P1-078 | P1 | Implement RewardPathScore | Target path quality | Obstacle data | NOT_STARTED |
| P1-079 | P1 | Implement OpportunityHalfLife | Prevents stale opportunities | Setup/archetype | NOT_STARTED |

---

## 1.8 Ranking, No-Trade, and Revalidation

| ID | Priority | TODO | Why It Matters | Dependencies | Status |
|---|---|---|---|---|---|
| P1-080 | P0 | Rank all valid candidates by ComparableOpportunityScore | Core selection engine | Candidate scores | NOT_STARTED |
| P1-081 | P0 | Apply hard gate exclusions before ranking | Prevents invalid candidates ranking high | Core gates | NOT_STARTED |
| P1-082 | P0 | Apply PortfolioNoTrade gate | Prevents best-of-weak trades | P1-070 | NOT_STARTED |
| P1-083 | P0 | Select only top A/A+ candidate | Core doctrine | P1-080 to P1-082 | NOT_STARTED |
| P1-084 | P0 | Return NO_TRADE if none excellent | Core survival rule | P1-083 | NOT_STARTED |
| P1-085 | P0 | Implement global position lock | Prevents multiple open positions | Simulated lifecycle | NOT_STARTED |
| P1-086 | P0 | Implement global pending order lock | Prevents overlapping candidates | Candidate engine | NOT_STARTED |
| P1-087 | P0 | Implement candidate revalidation before simulated entry | Prevents stale entry | Candidate data | NOT_STARTED |
| P1-088 | P0 | Implement no rank #2 auto-switch rule | Prevents fallback into weaker trade | Revalidation | NOT_STARTED |
| P1-089 | P1 | Implement tie-break logic | Resolves close candidates | Ranking | NOT_STARTED |
| P1-090 | P1 | Implement rank persistence rule | Prevents flickering candidates | Ranking history | NOT_STARTED |
| P1-091 | P1 | Implement trade scarcity protection | Prevents threshold lowering | Performance state | NOT_STARTED |

---

## 1.9 Paper-Fill and Simulated Trade Lifecycle

| ID | Priority | TODO | Why It Matters | Dependencies | Status |
|---|---|---|---|---|---|
| P1-092 | P0 | Implement paper entry fill model | Avoids LTP fantasy fills | Candidate quotes | NOT_STARTED |
| P1-093 | P0 | Implement paper exit fill model | Realistic exit P&L | Candidate quotes | NOT_STARTED |
| P1-094 | P0 | Implement no-fill status | Prevents assuming impossible trades | Paper fill | NOT_STARTED |
| P1-095 | P0 | Implement simulated open position lifecycle | Tracks paper trade from entry to exit | Paper fill | NOT_STARTED |
| P1-096 | P0 | Implement hard stop simulation | Risk analysis | Lifecycle | NOT_STARTED |
| P1-097 | P0 | Implement target simulation | Result analysis | Lifecycle | NOT_STARTED |
| P1-098 | P0 | Implement time-stop simulation | Long option survival | Lifecycle | NOT_STARTED |
| P1-099 | P0 | Implement premium-failure exit simulation | Core exit rule | Lifecycle | NOT_STARTED |
| P1-100 | P1 | Implement IV-exit simulation | IV risk analysis | Lifecycle | NOT_STARTED |
| P1-101 | P1 | Implement MFE / MAE tracking | Alpha discovery | Lifecycle | NOT_STARTED |
| P1-102 | P1 | Implement would-have-hit-target/stop after exit | Exit quality analysis | Lifecycle | NOT_STARTED |

---

## 1.10 MTIL and Logging

| ID | Priority | TODO | Why It Matters | Dependencies | Status |
|---|---|---|---|---|---|
| P1-103 | P0 | Implement MTIL schema writer | Core intelligence database | MTIL_SCHEMA.csv | NOT_STARTED |
| P1-104 | P0 | Log trade identity fields | Trade reconstruction | P1-103 | NOT_STARTED |
| P1-105 | P0 | Log entry fields | Entry analysis | P1-103 | NOT_STARTED |
| P1-106 | P0 | Log exit fields | Exit analysis | P1-103 | NOT_STARTED |
| P1-107 | P0 | Log result fields | Performance metrics | P1-103 | NOT_STARTED |
| P1-108 | P0 | Log opportunity-quality fields | Signal analysis | P1-103 | NOT_STARTED |
| P1-109 | P0 | Log regime/gap/global fields | Environment analysis | P1-103 | NOT_STARTED |
| P1-110 | P0 | Log option-chain/futures fields | Derivatives analysis | P1-103 | NOT_STARTED |
| P1-111 | P0 | Log elasticity/liquidity fields | Option edge analysis | P1-103 | NOT_STARTED |
| P1-112 | P0 | Log trade management fields | Exit improvement | P1-103 | NOT_STARTED |
| P1-113 | P0 | Log alpha discovery fields | Long-term edge discovery | P1-103 | NOT_STARTED |
| P1-114 | P0 | Implement skipped-candidate logger | No-trade analysis | SKIPPED_CANDIDATE_SCHEMA.csv | NOT_STARTED |
| P1-115 | P0 | Log all ranking-cycle candidates | Ranking analysis | P1-114 | NOT_STARTED |
| P1-116 | P1 | Implement archetype tagging | Setup expectancy | TRADE_ARCHETYPE_SCHEMA.csv | NOT_STARTED |
| P1-117 | P1 | Implement signal_combination_id generation | Signal combo analysis | Candidate scores | NOT_STARTED |
| P1-118 | P1 | Implement regime_combination_id generation | Regime combo analysis | Regime data | NOT_STARTED |
| P1-119 | P1 | Implement opportunity_cluster_id generation | Cluster analysis | Candidate context | NOT_STARTED |

---

## 1.11 Dashboard and Analytics

| ID | Priority | TODO | Why It Matters | Dependencies | Status |
|---|---|---|---|---|---|
| P1-120 | P1 | Build dry-run dashboard shell | Human monitoring | Core modules | NOT_STARTED |
| P1-121 | P1 | Show compact instrument ranking | Prevents four-dashboard overload | Ranking | NOT_STARTED |
| P1-122 | P1 | Show best candidate details | Paper decision visibility | Ranking | NOT_STARTED |
| P1-123 | P1 | Show no-trade reason | Helps validate filters | PortfolioNoTrade | NOT_STARTED |
| P1-124 | P1 | Show MTIL write status | Prevents silent log failure | MTIL | NOT_STARTED |
| P1-125 | P1 | Show calibration status per instrument | Prevents false confidence | Calibration | NOT_STARTED |
| P1-126 | P1 | Show paper P&L / R / ROI | Performance tracking | Lifecycle | NOT_STARTED |
| P1-127 | P1 | Create daily dry-run summary | Review workflow | Logs | NOT_STARTED |
| P1-128 | P1 | Create weekly paper performance summary | Early validation | Logs | NOT_STARTED |
| P1-129 | P1 | Create dry-run acceptance report | Required before live review | All Phase 1 logs | NOT_STARTED |

---

## 1.12 Emergency and Failure Tests

| ID | Priority | TODO | Why It Matters | Dependencies | Status |
|---|---|---|---|---|---|
| P1-130 | P1 | Test stale data blocks candidates | DataHealth validation | DataHealth | NOT_STARTED |
| P1-131 | P1 | Test wrong mapping blocks candidates | Mapping safety | Mapping | NOT_STARTED |
| P1-132 | P1 | Test lot-size mismatch blocks candidates | Risk safety | Mapping | NOT_STARTED |
| P1-133 | P1 | Test tick-size invalid price blocks candidate | Price validity | Mapping | NOT_STARTED |
| P1-134 | P1 | Test no rank #2 auto-switch | Selection discipline | Ranking | NOT_STARTED |
| P1-135 | P1 | Test global position lock | One-position rule | Lifecycle | NOT_STARTED |
| P1-136 | P1 | Test no live order path exists | MVP boundary | Project config | NOT_STARTED |
| P1-137 | P1 | Test MTIL write failure alert | Data integrity | MTIL | NOT_STARTED |
| P1-138 | P1 | Test paper-fill no-fill behavior | Fill realism | Paper fill | NOT_STARTED |
| P1-139 | P1 | Test dry-run acceptance calculations | Go-live governance | Analytics | NOT_STARTED |

---

# PHASE 2 — Paper Validation, Calibration, and Evidence Review

**Goal:** Use paper-mode output to validate whether the ranking system has positive signal quality and whether filters are too loose or too strict.

---

## 2.1 Dry-Run Validation

| ID | Priority | TODO | Why It Matters | Dependencies | Status |
|---|---|---|---|---|---|
| P2-001 | P0 | Run 20 trading days of dry-run capture | Minimum evidence period | Phase 1 complete | NOT_STARTED |
| P2-002 | P0 | Record 100+ ranking cycles | Ranking validation | P2-001 | NOT_STARTED |
| P2-003 | P0 | Record 50+ simulated candidates | Basic paper sample | P2-001 | NOT_STARTED |
| P2-004 | P0 | Verify 0 critical mapping errors in final 5 days | Mapping readiness | P2-001 | NOT_STARTED |
| P2-005 | P0 | Verify 0 wrong lot/tick calculations | Risk readiness | P2-001 | NOT_STARTED |
| P2-006 | P0 | Verify candidate revalidation works | Execution readiness | P2-001 | NOT_STARTED |
| P2-007 | P0 | Verify paper-fill simulator active | Fill realism | P2-001 | NOT_STARTED |
| P2-008 | P0 | Verify MTIL completeness | Data quality | P2-001 | NOT_STARTED |
| P2-009 | P0 | Verify skipped-candidate logging completeness | No-trade learning | P2-001 | NOT_STARTED |
| P2-010 | P1 | Validate dry-run dashboard latency | Operational readiness | P2-001 | NOT_STARTED |

---

## 2.2 Calibration and Performance Review

| ID | Priority | TODO | Why It Matters | Dependencies | Status |
|---|---|---|---|---|---|
| P2-011 | P0 | Analyze net paper expectancy | Determines if system has edge | P2-003 | NOT_STARTED |
| P2-012 | P0 | Analyze win rate and profit factor | Basic edge stats | P2-003 | NOT_STARTED |
| P2-013 | P0 | Analyze max paper drawdown | Survival assessment | P2-003 | NOT_STARTED |
| P2-014 | P0 | Analyze performance by instrument | Instrument selection quality | P2-003 | NOT_STARTED |
| P2-015 | P0 | Analyze performance by archetype | Setup quality | P2-003 | NOT_STARTED |
| P2-016 | P0 | Analyze performance by regime | Regime fit | P2-003 | NOT_STARTED |
| P2-017 | P1 | Analyze skipped winners | Check over-filtering | P2-009 | NOT_STARTED |
| P2-018 | P1 | Analyze no-trade saved losses | Validate no-trade logic | P2-009 | NOT_STARTED |
| P2-019 | P1 | Analyze premium failure frequency | Validate elasticity/convexity | P2-003 | NOT_STARTED |
| P2-020 | P1 | Analyze slippage assumptions | Validate paper-fill model | P2-003 | NOT_STARTED |
| P2-021 | P1 | Analyze OpportunityScore calibration | Ranking quality | P2-003 | NOT_STARTED |
| P2-022 | P1 | Analyze EV model calibration | Expectancy quality | P2-003 | NOT_STARTED |
| P2-023 | P1 | Analyze VolEdge calibration | Move forecast quality | P2-003 | NOT_STARTED |
| P2-024 | P1 | Analyze Midcap monitor-only data | Decide if Midcap remains monitor-only | P2-003 | NOT_STARTED |

---

# PHASE 3 — Manual Live Review and Controlled Deployment Preparation

**Goal:** Prepare for possible manual live testing only after evidence supports it. This phase is not automatic approval for real capital.

---

## 3.1 Live Readiness Review

| ID | Priority | TODO | Why It Matters | Dependencies | Status |
|---|---|---|---|---|---|
| P3-001 | P0 | Conduct investment committee review of dry-run results | Live approval governance | Phase 2 complete | NOT_STARTED |
| P3-002 | P0 | Confirm system remains no-live-order by default | Prevent accidental execution | P3-001 | NOT_STARTED |
| P3-003 | P0 | Verify cost model with actual broker rates | Net P&L accuracy | P3-001 | NOT_STARTED |
| P3-004 | P0 | Verify emergency exit plan | Live survival | P3-001 | NOT_STARTED |
| P3-005 | P0 | Verify daily loss lock design | Live risk control | P3-001 | NOT_STARTED |
| P3-006 | P0 | Verify no rule-violation patterns in paper phase | Behavioral readiness | P3-001 | NOT_STARTED |
| P3-007 | P1 | Define manual-live checklist | Human process control | P3-001 | NOT_STARTED |
| P3-008 | P1 | Define paper-vs-live fill comparison plan | Execution validation | P3-001 | NOT_STARTED |
| P3-009 | P1 | Define live micro-test size rules | Risk containment | P3-001 | NOT_STARTED |
| P3-010 | P1 | Define criteria to stop live test | Survival control | P3-001 | NOT_STARTED |

---

## 3.2 Possible Manual Live Micro-Test — Only If Approved

| ID | Priority | TODO | Why It Matters | Dependencies | Status |
|---|---|---|---|---|---|
| P3-011 | P0 | Enable manual-live mode only after approval | Prevent premature trading | P3-001 to P3-010 | DEFERRED |
| P3-012 | P0 | Keep max position = 1 | Correlation/risk control | P3-011 | DEFERRED |
| P3-013 | P0 | Compare live fills vs paper fills | Execution realism | P3-011 | DEFERRED |
| P3-014 | P0 | Log live trades into MTIL | Continuity of analysis | P3-011 | DEFERRED |
| P3-015 | P0 | Stop if slippage materially exceeds paper model | Prevent hidden drawdown | P3-013 | DEFERRED |
| P3-016 | P0 | Stop if rule violation occurs | Behavioral safety | P3-014 | DEFERRED |

---

# PHASE 4 — Future Research and Long-Term Evolution

**Goal:** Add higher-complexity research only after core evidence exists.

---

## 4.1 AI and Forecasting Research

| ID | Priority | TODO | Why It Matters | Dependencies | Status |
|---|---|---|---|---|---|
| P4-001 | P3 | Evaluate Moirai / Moirai-2 offline | Multivariate forecast research | Phase 2 data | DEFERRED |
| P4-002 | P3 | Evaluate Kronos offline | Financial K-line research | Phase 2 data | DEFERRED |
| P4-003 | P3 | Evaluate TimeGPT offline | Uncertainty interval research | Phase 2 data | DEFERRED |
| P4-004 | P3 | Evaluate Chronos / TimesFM as benchmarks | Forecast comparison | Phase 2 data | DEFERRED |
| P4-005 | P3 | Compare model outputs to EV/VolEdge improvement | Only useful if trading metrics improve | P4-001 to P4-004 | DEFERRED |
| P4-006 | P3 | Keep AI advisory only | Prevent model authority creep | P4-005 | DEFERRED |

---

## 4.2 Derivatives Microstructure Research

| ID | Priority | TODO | Why It Matters | Dependencies | Status |
|---|---|---|---|---|---|
| P4-007 | P3 | Research GEX scenario quality | Pin/release awareness | Phase 2 option-chain data | DEFERRED |
| P4-008 | P3 | Research CVD/order-flow proxy | Entry timing confirmation | Tick data | DEFERRED |
| P4-009 | P3 | Research 20-depth liquidity value | Better liquidity regime detection | Depth data | DEFERRED |
| P4-010 | P3 | Research stock option-chain enrichment | WBCI/leadership enrichment | Stock option data | DEFERRED |
| P4-011 | P3 | Research sector index expansion | Future universe expansion | Phase 2 success | DEFERRED |

---

## 4.3 Advanced System Evolution

| ID | Priority | TODO | Why It Matters | Dependencies | Status |
|---|---|---|---|---|---|
| P4-012 | P3 | Consider broker abstraction | Future execution optimization | Stable live/manual phase | DEFERRED |
| P4-013 | P3 | Consider Shoonya shadow testing | Lower cost only if net execution better | P4-012 | DEFERRED |
| P4-014 | P3 | Consider dynamic threshold optimization | Only after large sample | 500+ candidates | DEFERRED |
| P4-015 | P3 | Consider multi-position mode | Only after stable live edge | Long-term review | DEFERRED |
| P4-016 | P3 | Consider auto-execution research | Only after validated manual edge | Long-term review | DEFERRED |

---

# Explicit Non-TODO Items For MVP

Do not build these in MVP:

```text
Live order placement
Auto-execution
Broker order routing
Option selling
Multiple open positions
Leverage / pledge
Sector index expansion
AI trading authority
GEX production gate
CVD production gate
Stock option-chain production gate
Dynamic threshold optimizer
```

---

# Final Development Doctrine

```text
Build complete paper intelligence first.
Collect evidence.
Validate edge.
Only then consider capital deployment.
```


---

# Implementation Status Update — 2026-08-13

The following paper-safe implementation items have now been completed and tested:

```text
SIDE_DIRECTION_SCORING
  Direction credit is side-aware; wrong-side candidates are hard-rejected.

ENTRY_WINDOW_CONTROL
  New entries are allowed only from 09:30 through 14:14 IST.
  Existing positions remain managed after the entry cutoff.

CONTRACT_QUALITY_GATE
  opportunity_selection.require_contract_quality_min is enforced by the scorer.

CANDIDATE_DIAGNOSTICS
  candidate_diagnostics.csv records side direction, contract quality,
  rejection reasons, observed elasticity, and current IV-surface diagnostics.

OBSERVED_POST_COST_ELASTICITY_SHADOW
  Rolling bid/ask-aware option response is captured in shadow mode.
  It is not yet a trade-approval gate pending calibration data.

OPTION_SURFACE_DIAGNOSTICS_SHADOW
  Current ATM IV, call-put IV skew, and wing IV observations are captured.
  IV percentile, IV-versus-realized spread, and term structure remain deferred.
```

Validation after this update:

```text
python -m unittest discover -s tests
89 tests passing
```

The following items remain evidence-gated and are not activated as trade gates:

```text
calibrated ExpectedValue_R probabilities
walk-forward threshold optimization
outright-option versus debit-spread selection
MAE/MFE-based exit calibration from real closed paper trades
verified broker/statutory charges
live packet-gap, reconnect, and depth-freshness validation
```

Live execution remains disabled.


## BSE Monitor-Only Expansion — 2026-08-14

The attached Fyers verification confirmed live BSE SENSEX and BANKEX option-chain responses and BSE symbol-master rows. The paper runner now supports these exchanges without changing the frozen four-index trade universe:

```text
BSE:SENSEX-INDEX  -> SENSEX  -> monitor_only=true
BSE:BANKEX-INDEX  -> BANKEX  -> monitor_only=true
```

Implemented safeguards:

```text
- Fyers NSE/BSE symbol-master URLs are selected from configured exchange metadata.
- NSE_FO.csv and BSE_FO.csv are parsed and combined when both exchanges are configured.
- BSE contracts are parsed using the same CE/PE symbol parser.
- Monitor-only underlyings are fetched, captured, and shown in runner state/dashboard data.
- Monitor-only underlyings are excluded from candidate construction, ranking, paper entry,
  skipped-candidate evidence, and the one-position trading decision.
- SystemConfig still requires exactly the frozen four eligible trade underlyings.
- Live execution remains disabled.
```

Promotion remains evidence-gated: BSE indices must first pass quote freshness, bid/ask, depth, conservative fillability, expiry, lot/tick, and a separate paper-validation sample before any consideration for trade eligibility.


## Index-Universe Policy Audit — 2026-08-14

The index recommendations were applied as a research policy rather than as new trade permissions. The paper runner now monitors SENSEX, NIFTYNXT50, and NIFTYFPI. BANKEX was removed from the active monitor configuration because it duplicates the existing BANKNIFTY factor exposure and was explicitly marked for deferral. Sectoral and broad indices without a verified active option-contract and liquidity path remain excluded.

A strategy-safety issue was also corrected. Candidate construction no longer falls back to a guessed lot size of 30 and tick size of 0.05 when the instrument master is missing or the chain expiry is invalid. The candidate is blocked and an instrument error is recorded instead. This prevents a future promoted index from being mis-sized because of missing contract metadata.

Monitor-only observations are recorded in `paper_state/monitor_diagnostics.csv`, including exchange, spot, expiry, VIX, ATM bid/ask spreads, quote validity, option-leg counts, and available bid/ask quantities. These observations do not influence ranking or entry.


## Broad Research Universe Expansion — 2026-08-14

The paper runner now collects research data across every verified option-family currently present in the cached Fyers masters: NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50, NIFTYFPI, BSE SENSEX, BSE BANKEX, and BSE FOCIT. The official current NIFTY 50 constituent CSV was also used to add all 50 constituents as stock-option monitor instruments.

The original four index instruments remain the only trade-enabled baseline. Every added index and stock is `monitor_only=true` and `trade_enabled=false`. Monitor-only names are collected in rotating batches of eight, while the four trade-enabled names are fetched every cycle. This starts collecting evidence early without overwhelming the broker endpoint or allowing an unvalidated stock/index to trade merely because it receives a high proxy score.

Monitor-only candidates are built through the same candidate factory and scorer in shadow mode, but are written to separate `shadow_candidates.csv` and `shadow_candidate_diagnostics.csv` files and displayed under `_shadow_candidates` with `research_only=true`. They are never passed to the live paper-entry selector. Liquidity and quote observations remain in `monitor_diagnostics.csv`.

The monthly-expiry preference bug was corrected: the runner now passes the parsed boolean preference to expiry selection rather than comparing a boolean with the string `"true"`. Missing lot size, tick size, or expiry metadata continues to block candidate construction instead of guessing contract metadata.
