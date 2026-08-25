# Development Debt — Institutional Options Paper System

**Purpose:** Track implementation gaps, bugs, conflicts, and technical debt discovered during system review so they can be resolved step by step before relying on Phase 1/2/3 outputs.

**Current verdict:**

```text
APPROVED WITH FIXES
Continue development: YES
Use for live trading: NO
Use Phase 2 evidence as production truth: NOT YET
```

---

## 1. Executive Summary

The implementation is directionally aligned with the roadmap and survivability-first philosophy, but it is not yet a complete Phase 1 / Phase 2 / Phase 3 implementation.

Current codebase is a strong foundation, but not yet a finished paper-trading operating system.

Most important issue:

```text
The MTIL / Phase 2 evidence path has schema and field-alignment problems that must be fixed before dry-run analytics can be trusted.
```

Current test status at review time:

```text
34 unit tests passing
```

But tests do not yet cover several critical end-to-end integration paths.

---

## 2. Final Review Scores

| Category | Score |
|---|---:|
| Architecture alignment | 7 / 10 |
| Code modularity | 8 / 10 |
| Survivability alignment | 7 / 10 |
| MTIL readiness | 4 / 10 |
| Phase 2 readiness | 5 / 10 |
| Live safety | 7 / 10 |
| Research future compatibility | 8 / 10 |
| End-to-end paper-mode completeness | 5 / 10 |

---

## 3. Critical Bugs / Critical Debt

### DEBT-001 — MTILRecordBuilder Does Not Satisfy MTIL Schema

**Severity:** Critical  
**Area:** MTIL / data integrity / Phase 2 evidence

#### Problem

`MTIL_SCHEMA.csv` has many required fields, but `MTILRecordBuilder.from_paper_trade()` does not populate all required fields.

Observed during review:

```text
Required fields: 90
Record keys produced: 81
Missing required fields: 40
```

Examples of missing required fields:

```text
primary_regime
gap_direction
gap_pct
atm_iv
entry_revalidation_passed
entry_order_type
vwap_position
atr_value
event_risk_state
rbi_day_flag
session_bucket
```

#### Why It Matters

This breaks the MTIL-first philosophy.

If MTIL rows fail validation or are incomplete, Phase 2 analytics cannot be trusted.

#### Required Fix

Before real dry-run:

```text
MTILRecordBuilder must either:
1. populate every required MTIL field, or
2. MTIL schema required flags must be adjusted for fields unavailable at MVP stage.
```

Preferred institutional fix:

```text
Keep fields, but allow explicit sentinel values:
UNAVAILABLE
UNVALIDATED
NOT_APPLICABLE
0
false
```

Do not leave required fields blank.

---

### DEBT-002 — Phase 2 Validator Uses Field Names Not Present In MTIL Schema

**Severity:** Critical  
**Area:** Phase 2 validation / schema alignment

#### Problem

`phase2.py` checks fields such as:

```text
revalidation_passed
paper_fill_model
simulated_entry_fill
```

But in `MTIL_SCHEMA.csv`, the canonical equivalent is:

```text
entry_revalidation_passed
```

And:

```text
paper_fill_model
simulated_entry_fill
```

exist in `JOURNAL_SCHEMA.csv`, not in `MTIL_SCHEMA.csv`.

#### Why It Matters

Phase 2 acceptance may fail incorrectly or pass based on synthetic test data rather than canonical MTIL data.

#### Required Fix

Align Phase 2 validator with canonical MTIL schema:

```text
entry_revalidation_passed
entry_fill_price
entry_option_bid
entry_option_ask
entry_option_mid
exit_fill_price
```

If `paper_fill_model` is required, add it to MTIL schema or stop using it in Phase 2.

---

### DEBT-003 — OpportunityScorer Ignores Required Logical Stop

**Severity:** Critical  
**Area:** Risk management / stop-fit / survivability

#### Problem

In `OpportunityScorer.evaluate()`, the risk context currently sets:

```text
required_stop_points = max(candidate.required_move, 0.0) * 0.0
```

That always becomes:

```text
0
```

So required logical stop is effectively ignored.

#### Why It Matters

The system may mark a trade as stop-fit even when the real logical stop exceeds the risk cap.

This violates the core survivability rule:

```text
If required stop risk > max allowed risk, skip trade.
```

#### Required Fix

Add to `CandidateInputs`:

```text
required_stop_points
```

or implement a proper required-stop model based on:

```text
structure
spread
volatility
invalidation level
instrument noise floor
```

Until fixed, paper ranking may overstate eligibility.

---

### DEBT-004 — CandidateFactory Uses Threshold-Passing Defaults

**Severity:** Critical  
**Area:** Candidate generation / false confidence

#### Problem

`CandidateFactory` sets important fields to passing/default values:

```text
premium_elasticity = 1.0
expected_value_r = 0.30
convexity_edge_score = 80
execution_quality_score = 80
opportunity_confidence_score = 70
regime_fit_score = 75
```

#### Why It Matters

These values are exactly the thresholds required for candidate eligibility.

If not overwritten by real calculations, candidates may appear tradable by default.

#### Required Fix

Unavailable values should be:

```text
UNAVAILABLE / UNVALIDATED
```

and should not pass gates.

Safer defaults:

```text
premium_elasticity = 0
expected_value_r = 0
convexity_edge_score = 0
execution_quality_score = 0
opportunity_confidence_score = capped / penalized
```

or candidate factory must require these values from calculators before evaluation.

---

## 4. High Priority Bugs / Debt

### DEBT-005 — Live Execution Path Exists

**Severity:** High  
**Area:** Live safety / execution

#### Problem

`DhanRestClient.place_order()` will send a real order if:

```text
demo_trade = false
```

#### Why It Matters

The project doctrine says Phase 1–3 must not enable live trading.

#### Current Control

`PARAMETERS.json` has:

```text
demo_trade = true
```

Phase 3 cannot approve live orders.

#### Required Fix

Add an additional global hard lock:

```text
LIVE_TRADING_ENABLED = false
```

Before any real order can be sent, require:

```text
demo_trade = false
AND LIVE_TRADING_ENABLED = true
AND committee approval artifact exists
```

---

### DEBT-006 — Tests Hide MTIL Schema Mismatch

**Severity:** High  
**Area:** Test quality / schema integrity

#### Problem

Phase 2 tests create synthetic CSV rows with fields not matching canonical MTIL schema.

#### Why It Matters

Tests pass but do not guarantee Phase 2 works with real MTIL rows.

#### Required Fix

Add integration tests that:

```text
1. build MTIL row from MTILRecordBuilder
2. validate using MTILSchema
3. feed same row into Phase2 validator
4. verify acceptance logic uses canonical field names
```

---

### DEBT-007 — Dashboard Is Not Operational Yet

**Severity:** High  
**Area:** Phase 1 dry-run UX / monitoring

#### Problem

`DashboardHTML` is currently a static helper.

#### Why It Matters

It does not yet fulfill Phase 1 dashboard requirements:

```text
live/dry-run ranking
best candidate
no-trade reason
MTIL write status
calibration status
paper P&L
```

#### Required Fix

Implement full dry-run dashboard page using ranking/evaluation outputs.

---

### DEBT-008 — Candidate Factory Does Not Compute Direction Models

**Severity:** High  
**Area:** Direction models / candidate generation

#### Problem

CandidateFactory accepts a precomputed direction score.

It does not compute:

```text
Nifty direction proxy
FinNifty direction proxy
Midcap direction proxy
Bank Nifty FastWBCI
```

#### Why It Matters

Candidate generation cannot yet stand alone from real market snapshots.

#### Required Fix

Implement separate direction-model calculators and feed candidate factory with validated direction scores.

---

## 5. Medium Priority Bugs / Debt

### DEBT-009 — DataHealth Orchestrator Is Minimal

**Severity:** Medium-High

Currently checks:

```text
futures quote freshness
option-chain freshness
```

Still missing:

```text
selected option quote freshness
packet gaps
reconnect state
option-chain IV/OI validity
depth freshness
```

---

### DEBT-010 — Option Chain Parser Needs Deeper Semantic Validation

**Severity:** Medium

Parser does not yet validate:

```text
missing security_id
zero bid/ask
zero IV
invalid Greeks
strike ordering anomalies
timestamp consistency
```

---

### DEBT-011 — Cost Config Is Placeholder

**Severity:** Medium

`CHARGES_CONFIG.json` is placeholder.

This is acceptable for paper mode but blocks live-readiness.

---

### DEBT-012 — Phase 2 Mapping Error Detection Is Heuristic

**Severity:** Medium

Current Phase 2 validator scans text fields for words like:

```text
mapping
lot
tick
```

Better structured fields needed:

```text
mapping_validation_passed
lot_size_validation_passed
tick_size_validation_passed
```

---

## 6. Missing Functionality By Phase

## Phase 1 Missing Functionality

```text
Real Dhan option-chain fetch → parser → candidate factory flow
Real candidate generation loop across all instruments
Direction model calculators
Full DataHealth orchestration
Full MarketHostility calculation from live inputs
Full PortfolioNoTrade calculation from all candidates
Full MTIL population
Full skipped-candidate population
Full dry-run dashboard
Full simulated lifecycle from real quote stream
Daily dry-run summary
Weekly dry-run summary
```

## Phase 2 Missing Functionality

```text
MTIL schema-aligned validator
OpportunityScore calibration diagnostics
EV calibration diagnostics
VolEdge diagnostics
Slippage validation by instrument/time
Premium failure analysis by setup/regime
Midcap monitor-only decision report
MTIL section completeness report
Skipped-winner MFE/MAE analysis
```

## Phase 3 Missing Functionality

```text
Committee approval artifact handling
Hard live-order deployment lock
Emergency exit drill evidence tracking
Daily loss lock live implementation
Paper-vs-live fill comparison storage
Live micro-test controller
```

## Phase 4 Missing Functionality

No critical gap. Phase 4 is appropriately research-only.

---

## 7. Hidden Dependencies

```text
DHAN credentials required for real data
Instrument master required for true symbols, lot sizes, tick sizes
Option-chain payload required to validate parser
Live quote timestamps required to calibrate DataHealth
Real spread/depth data required for ExecutionQuality calibration
Real dry-run MTIL rows required for Phase 2
Broker charge verification required before live review
Emergency execution path requires actual broker access
```

---

## 8. Cross-Phase Conflicts

### Conflict 1 — Phase 2 Depends On MTIL, But MTIL Builder Is Incomplete

Phase 2 cannot be trusted until MTIL record generation is schema-complete.

### Conflict 2 — Phase 3 Depends On Phase 2 Acceptance, But Phase 2 Acceptance Uses Non-Canonical Fields

Fix Phase 2 schema alignment before Phase 3 evidence can be trusted.

### Conflict 3 — Phase 4 Research Depends On Clean MTIL

If MTIL is incomplete, future AI/GEX/CVD research will be garbage-in/garbage-out.

---

## 9. Data Collection Gaps

If we collected 1,000 trades today using current MTIL builder, we would regret missing:

```text
complete regime fields
complete gap fields
complete event/news fields
complete ATR/VWAP/ORB context
entry_revalidation_passed
paper fill model evidence
full alpha discovery fields
actual required stop model
mapping validation flags
lot/tick validation flags
```

The schema contains many fields, but the current builder does not yet populate them.

---

## 10. Architecture Drift

### Drift 1 — Unavailable Metrics Should Not Approve Trades

Documentation says unavailable metrics must be:

```text
UNAVAILABLE / UNVALIDATED
```

but CandidateFactory currently assigns threshold-passing defaults.

### Drift 2 — MTIL Is Central But Builder Is Incomplete

The schema is rich, but current builder does not populate enough fields.

### Drift 3 — Phase 2 Tests Use Non-Canonical Synthetic Rows

Tests pass but do not validate real MTIL compatibility.

---

## 11. Technical Debt Risks

```text
Schema mismatch between MTIL and JOURNAL_SCHEMA
Multiple score formulas historically exist; code uses simplified subset
Hardcoded provisional values in CandidateFactory
Phase 2 field names not canonical
Dhan order wrapper exists before deployment lock is complete
RecordBuilder may become brittle if schema changes
Tests may give false confidence
```

---

## 12. Survivability Risks

```text
Required stop ignored in OpportunityScorer
CandidateFactory defaults may create false excellent candidates
Live order wrapper can send if misconfigured
Incomplete MTIL can hide drawdown causes
Phase 2 could approve readiness using incomplete evidence
Missing real DataHealth orchestration could allow stale data in future integration
```

---

## 13. Recommended Immediate Fix Sprint

Next sprint should be:

```text
MTIL + Phase2 Evidence Integrity Sprint
```

Priority order:

1. MTIL schema-complete record builder.
2. Phase2 validator canonical field alignment.
3. Required stop handling.
4. CandidateFactory unavailable/unvalidated handling.
5. End-to-end integration test.
6. Deployment/live-order hard lock.
7. Structured mapping/lot/tick validation flags.

---

## 14. Final Verdict

```text
APPROVED WITH FIXES
```

Continue development, but do not treat Phase 1 / Phase 2 as complete.

Do not use dry-run analytics for investment decisions until MTIL and Phase2 schema alignment are fixed.

Do not enable live trading.

---

# Resolution Update — Evidence Integrity Sprint 1

**Status date:** 2026-06-03

The following debt items have been completed in code and validated by tests.

## Completed Items

### DEBT-001 — MTILRecordBuilder Does Not Satisfy MTIL Schema

**Status:** DONE

**Fix implemented:**

- `MTILRecordBuilder.from_paper_trade(..., schema=MTILSchema)` now supports schema-complete record generation.
- Missing required fields are filled with explicit sentinel/default values instead of blanks:

```text
UNAVAILABLE
UNVALIDATED
NOT_APPLICABLE-style defaults
0
false
```

**Validation:**

- Added integration test that builds a paper trade record, applies MTIL schema defaults, and validates with `MTILSchema.validate_record()`.

---

### DEBT-002 — Phase 2 Validator Uses Field Names Not Present In MTIL Schema

**Status:** DONE

**Fix implemented:**

- Phase 2 now checks canonical MTIL field:

```text
entry_revalidation_passed
```

with backward-compatible fallback to:

```text
revalidation_passed
```

- Paper-fill evidence can now be detected from canonical MTIL fields:

```text
entry_fill_price
paper_fill_model
simulated_entry_fill
```

**Validation:**

- Added integration test that passes a schema-complete MTIL builder record into `DryRunValidator` and verifies candidate revalidation and paper-fill checks are recognized.

---

### DEBT-003 — OpportunityScorer Ignores Required Logical Stop

**Status:** DONE

**Fix implemented:**

- Added `required_stop_points` to `CandidateInputs`.
- `OpportunityScorer` now passes `candidate.required_stop_points` into `DynamicRiskCalculator`.

**Validation:**

- Existing dynamic risk tests continue passing.
- Candidate scoring now respects required stop when provided.

---

### DEBT-004 — CandidateFactory Uses Threshold-Passing Defaults

**Status:** DONE

**Fix implemented:**

CandidateFactory no longer assigns passing defaults for critical fields.

Changed defaults from threshold-passing values to safe non-approval values:

```text
premium_elasticity = 0.0
expected_value_r = 0.0
convexity_edge_score = 0.0
execution_quality_score = 0.0
opportunity_confidence_score = 0.0
regime_fit_score = 0.0
```

**Validation:**

- Added test confirming CandidateFactory-generated candidates do not receive tradeable default values.

---

### DEBT-005 — Live Execution Path Exists

**Status:** DONE FOR PHASE 1-3 SAFETY

**Fix implemented:**

- Added second hard live-trading lock:

```text
live_trading_enabled = false
```

- `SystemConfig` rejects configs where `live_trading_enabled` is not false for current MVP/Phase 1-3.
- `DhanRestClient.place_order()` now refuses live order placement unless both are true:

```text
demo_trade = false
live_trading_enabled = true
```

Current config remains:

```text
demo_trade = true
live_trading_enabled = false
```

**Validation:**

- Existing Dhan demo-order test confirms demo order is not sent.
- Config validation enforces live lock.

---

### DEBT-006 — Tests Hide MTIL Schema Mismatch

**Status:** DONE

**Fix implemented:**

Added test coverage for:

```text
PaperTrade → MTILRecordBuilder → MTILSchema.validate_record → MTILWriter → Phase2 DryRunValidator
```

This prevents Phase 2 tests from relying only on non-canonical synthetic rows.

---

### DEBT-012 — Phase 2 Mapping Error Detection Is Heuristic

**Status:** PARTIALLY FIXED

**Fix implemented:**

- Added optional MTIL schema fields:

```text
mapping_validation_passed
lot_size_validation_passed
tick_size_validation_passed
```

- Phase 2 validator now uses these structured fields if present.
- Falls back to legacy text scanning only if structured flags are absent.

**Remaining work:**

- Full orchestration must populate these fields from live/dry-run mapping validation.

---

## Current Test Status

```text
python -m unittest discover -s tests
36 tests passing
```

## Remaining High-Priority Debt

Still open:

```text
DEBT-007 — Dashboard is not operational yet
DEBT-008 — CandidateFactory does not compute direction models internally
DEBT-009 — DataHealth orchestrator is minimal
DEBT-010 — Option-chain parser needs deeper semantic validation
DEBT-011 — Cost config is placeholder
```

## Next Recommended Fix Order

1. Full dry-run dashboard flow.
2. Direction-model calculators for BANKNIFTY / NIFTY / FINNIFTY / MIDCPNIFTY.
3. DataHealth orchestration expansion.
4. Option-chain semantic validation.
5. Cost config verification once broker rates are available.


---

# Resolution Update — Debt Sprint 2

**Status date:** 2026-06-03

The following remaining high-priority debt items have been addressed with foundation implementations and tests.

## Completed / Addressed Items

### DEBT-007 — Dashboard Is Not Operational Yet

**Status:** DONE FOR PAPER-MODE FOUNDATION

**Fix implemented:**

- Added `institutional_options/dashboard.py`.
- Added `DryRunDashboard.render_selection()` and `DryRunDashboard.write_selection()`.
- Dashboard renders:

```text
latest decision
selected candidate
no-trade reasons
candidate rows
instrument
side
grade
score
threshold
contract quality
premium elasticity
market hostility
IV crush
eligibility
reasons
```

**Validation:**

- Added test confirming dashboard HTML is generated and contains ranked candidate information.

**Remaining later work:**

- Full real-time refresh/UI polish can be improved after live dry-run flow is wired.

---

### DEBT-008 — CandidateFactory Does Not Compute Direction Models Internally

**Status:** RESOLVED BY SEPARATE DIRECTION MODEL MODULE

**Fix implemented:**

- Added `institutional_options/direction_models.py`.
- Implemented:

```text
DirectionModelCalculator
LeadershipInput
MidcapDirectionInput
VWAPStateScore
RelativeStrength5mScore
VolumeConfirmationScore
BankNifty FastWBCI-style score
Nifty leadership proxy
FinNifty leadership proxy
Midcap direction proxy
Generic InstrumentDirectionScore
```

**Design decision:**

CandidateFactory remains input-driven by design. Direction models are calculated upstream and passed into candidate creation. This avoids mixing market-snapshot interpretation with option-chain candidate construction.

**Validation:**

- Added tests for Nifty leadership proxy and Midcap direction proxy.

---

### DEBT-009 — DataHealth Orchestrator Is Minimal

**Status:** PARTIALLY DONE / FOUNDATION EXPANDED

**Fix implemented:**

- Expanded `DataHealthOrchestrator` with:

```text
candidate option quote health evaluation
option-chain semantic health evaluation
per-instrument futures freshness
option-chain freshness
global health summary
```

**Validation:**

- Added test for candidate quote DataHealth.

**Remaining later work:**

- Real WebSocket packet-gap detection.
- Reconnect state tracking.
- Depth freshness tracking.
- Live selected-option quote stream integration.

These require live DHAN data and are tracked in DHAN API dependent items.

---

### DEBT-010 — Option Chain Parser Needs Deeper Semantic Validation

**Status:** DONE FOR FOUNDATION

**Fix implemented:**

- Added `OptionChainSemanticValidator` and `OptionChainValidationReport`.
- Validator checks:

```text
underlying price positive
strikes exist
strike ordering
missing CE/PE warnings
missing security_id errors
invalid IV warnings
missing delta warnings
invalid bid/ask errors when tradable quote validation is required
```

**Validation:**

- Added test confirming semantic validation detects missing PE as warning and keeps snapshot valid if no hard error exists.

---

### DEBT-011 — Cost Config Is Placeholder

**Status:** VALIDATION MECHANISM DONE / RATES STILL PENDING

**Fix implemented:**

- Added `validate_charges_config()` in `institutional_options/costs.py`.
- It verifies:

```text
status is not placeholder
required charge fields exist
charge fields are numeric and non-negative
```

**Validation:**

- Added test confirming current placeholder config correctly fails validation.

**Remaining later work:**

- Replace placeholder rates with verified Dhan/NSE/SEBI/STT/GST rates before any live review.

---

## Current Test Status

```text
python -m unittest discover -s tests
41 tests passing
```

## Remaining Development Debt After Sprint 2

The major remaining debt is now integration/data dependent rather than specification dependent:

```text
1. Wire real Dhan option-chain fetch into parser/candidate factory.
2. Wire real dry-run orchestration loop across all four instruments.
3. Populate MTIL from real dry-run cycles.
4. Populate skipped-candidate logs from real ranking cycles.
5. Collect actual spread/slippage/elasticity baselines.
6. Replace placeholder charges with verified broker/statutory values.
7. Add live WebSocket packet-gap/reconnect/depth freshness validation once DHAN feed is available.
```

## Updated Final Verdict

```text
Evidence-integrity critical bugs are fixed.
Dashboard/direction/datahealth/parser/cost-validation foundations are implemented.
Continue development into end-to-end dry-run orchestration.
Live trading remains NO-GO.
```
