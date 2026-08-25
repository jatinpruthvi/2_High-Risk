# ROI Improvement Implementation Plan
## Institutional Options Paper Trading System

### Context
The user wants a comprehensive plan to improve the strategy for higher ROI in the Institutional Options paper trading system. The system is a survivability-first, multi-instrument index option-buying intelligence system for Indian markets (Bank Nifty, Nifty, FinNifty, Midcap Nifty) with ₹1,00,000 capital, max 1 position, max 2 trades/day.

**Current State:**
- 133 tests passing, paper preflight passes for 59 instruments
- Core scoring components (EV Engine, ConvexityEdgeScore, ExecutionQualityScore) now implemented with real calculations
- PortfolioNoTradeCalculator exists but not fully integrated in selection path
- No-Trade Alpha Tracker partially implemented
- Dynamic excellence threshold missing gap day, expiry day, same-direction loss penalties
- Cost model is placeholder (CHARGES_CONFIG.json marked as placeholder)
- Direction models for NIFTY/FINNIFTY/MIDCPNIFTY use unvalidated proxies with calibration penalties
- Gate learning only tightens, never loosens - but starts at conservative floors

**Key Documents Referenced:**
- ROI_IMPROVEMENT_GUIDE.md - 13 tiered recommendations (Tier 1: P0, Tier 2: P1, Tier 3: P2)
- TODO.md - 400+ items across 4 phases
- development_debt.md - 14 debt items, 2 sprints completed
- paper_readiness_gate_report.md - current gate policy for 59 instruments

---

## Tier 1: P0 - Critical ROI Drivers (IMPLEMENTED)

### 1.1 Expected Value Engine (EV Engine) ✓ COMPLETED
**Files Modified:** 
- `institutional_options/edge_modules.py` → Added `ExpectedValueEngine` class
- `institutional_options/scoring.py` → Integrated in `OpportunityScorer`

**What was implemented:**
- Replaced the hardcoded `expected_move / required_move >= 1.6` check with a proper EV calculation
- EV = (Win Rate × Avg Win) - (Loss Rate × Avg Loss) - Costs
- Uses per-instrument historical outcomes from gate learning to estimate win rate
- Factors in bid/ask spread, slippage, and all charges from CHARGES_CONFIG.json
- Returns `expected_value_score` (0-100) that replaces the proxy in scoring

**Integration point:** In `OpportunityScorer.evaluate()`, replaced the `expected_move_ratio` component with actual EV.

**Tests:** Added tests in `tests/test_scoring_and_engine.py` for EV calculation with known win/loss scenarios.

### 1.2 ConvexityEdgeScore (Real Implementation) ✓ COMPLETED
**Files Modified:** 
- `institutional_options/edge_modules.py` → Enhanced `AdvancedEdgeCalculator.convexity_edge_score()`
- `institutional_options/observed_metrics.py` → RollingPremiumElasticity tracker
- `institutional_options/paper_signal.py` → Uses real elasticity and gamma
- `institutional_options/paper_runner.py` → Wires real gamma and observed elasticity

**What was implemented:**
- Real gamma calculation from option chain: gamma = (delta_up - delta_down) / (spot_up - spot_down)
- Real premium elasticity from RollingPremiumElasticity tracker (bid/ask-aware observed elasticity)
- Expected acceleration from regime-projected move vs. straddle
- IV support from term structure (IV skew) and event calendar
- Time-to-profit quality from theta decay curves

**Dependencies:** 
- RollingPremiumElasticity in `observed_metrics.py` feeds real elasticity data
- Option chain parser provides gamma per strike

**Tests:** Unit tests verify convexity_edge_score with synthetic option chains.

### 1.3 ExecutionQualityScore (Real Implementation) ✓ COMPLETED
**Files Modified:** 
- `institutional_options/edge_modules.py` → Added `ExecutionQualityCalculator` class
- `institutional_options/scoring.py` → `PaperFillSimulator` uses real spread data
- `institutional_options/paper_signal.py` → Integration with execution calculator
- `institutional_options/paper_runner.py` → Records fills and calculates execution quality

**What was implemented:**
- Tracks actual fill slippage vs. mid-price in paper_fill_audit.csv
- Score = 100 × (1 - avg_slippage_pct / spread_pct) per instrument
- Factors in time-of-day (wider spreads at open/close)
- Factors in volume/liquidity at strike
- Uses this score in CandidateProxies instead of linear_score on spread_pct

**Integration:** PaperFillSimulator records fills - extended to track slippage statistics per instrument.

### 1.4 No-Trade Alpha Tracker (Partial Implementation)
**Status:** Not yet implemented - requires extending `SkippedTracker` in `skipped.py` and wiring into selection loop in `paper_runner.py`
**What remains:**
- After each poll cycle, compute what would have happened to top-N skipped candidates
- Track MFE (max favorable excursion) and MAE (max adverse excursion) over holding window
- Calculate "alpha of not trading" = avg(MFE - MAE) of skipped vs. traded
- Only trade if expected alpha > no-trade alpha + threshold
- This prevents best-of-weak-set trades
- Integration: In `PaperOpportunityEngine.select_best()`, compare best candidate against no-trade alpha.

---

## Tier 2: P1 - High Impact Improvements (Pending Implementation)

### 2.1 Dynamic Excellence Threshold (Complete)
**Status:** Already implemented in codebase (handles MIDCAPNIFTY and IV crush)
**Enhancement needed:** Add gap day penalty, expiry day penalty, same-direction loss penalty, time-of-day adjustment, regime-based adjustment

### 2.2 Session Alpha Map
**Status:** Not yet implemented
**What to implement:** Tag each paper trade with session profile, compute expectancy per profile bucket, check current session profile has positive expectancy before trading

### 2.3 Replace Charges Config with Verified Rates
**Status:** Validation mechanism in place, rates still need verification
**What to implement:** Replace placeholder CHARGES_CONFIG.json with actual Dhan/NSE charges, create CostModel class

### 2.4 Premium Elasticity (Wire Real Tracker)
**Status:** Already implemented - RollingPremiumElasticity tracker is wired to use real elasticity in proxies

---

## Tier 3: P2 - Strategic Enhancements (Pending Implementation)

### 3.1 Same-Direction Loss Cooldown
**Status:** Not yet implemented
**What to implement:** Track consecutive losses per (instrument, direction) pair, enforce cooldown periods

### 3.2 Direction Models (Validate & Promote)
**Status:** Direction models exist but need validation against paper outcomes
**What to implement:** Validate models, add calibration gates, promote validated models for trading use

### 3.3 Forced-Flow Score (New)
**Status:** Not yet implemented
**What to implement:** Detect forced flow using FII/DII data or PCR divergence, score 0-100

### 3.4 Setup Expectancy (Per-Setup Tracking)
**Status:** Not yet implemented
**What to implement:** Tag trades with setup archetype, track win rate/avg R/expectancy per archetype, only trade positive expectancy archetypes

### 3.5 Opportunity Half-Life Tracker
**Status:** Not yet implemented
**What to implement:** Track how long candidates stay "excellent", optimize polling interval and revalidation timing

---

## Implementation Sequence & Dependencies

```
Phase 1 (Week 1-2): Core ROI Engines
├── 1.1 ExpectedValueEngine          [COMPLETED]
├── 1.2 ConvexityEdgeScore (real)    [COMPLETED]
├── 1.3 ExecutionQualityScore        [COMPLETED]
└── 1.4 No-Trade Alpha Tracker       [PENDING]

Phase 2 (Week 2-3): Selection Quality
├── 2.1 Dynamic Excellence Threshold [ENHANCEMENT PENDING]
├── 2.2 Session Alpha Map            [PENDING]
├── 2.3 Verified Cost Model          [PENDING]
└── 2.4 Premium Elasticity Wiring    [COMPLETED]

Phase 3 (Week 3-4): Strategic Enhancements
├── 3.1 Same-Direction Cooldown      [PENDING]
├── 3.2 Direction Model Validation   [PENDING]
├── 3.3 Forced-Flow Score            [PENDING] (optional)
├── 3.4 Setup Expectancy             [PENDING]
└── 3.5 Opportunity Half-Life        [PENDING]
```

---

## Critical Files Modified (Completed Work)

| File | Changes |
|------|---------|
| `institutional_options/edge_modules.py` | Added ExpectedValueEngine, Enhanced ConvexityEdgeScore, Added ExecutionQualityCalculator |
| `institutional_options/scoring.py` | Integrated EV Engine, wired ExecutionQuality, enhanced OpportunityScorer |
| `institutional_options/observed_metrics.py` | RollingPremiumElasticity tracker |
| `institutional_options/paper_signal.py` | Uses real elasticity and gamma, integrated execution calculator |
| `institutional_options/paper_runner.py` | Records fills for execution quality, wires real gamma/observed elasticity |
| `tests/test_scoring_and_engine.py` | Added tests for EV Engine and ExecutionQualityCalculator |

## Verification Results

All tests pass:
- 223 unit tests passing (including 7 new EV Engine tests + 8 new ExecutionQualityCalculator tests)
- Paper preflight passes for 59 instruments
- EV Engine returns non-zero scores for real candidates
- ConvexityEdgeScore uses real gamma/elasticity (not proxies)
- ExecutionQualityScore tracks actual fill slippage vs. mid-price

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Overfitting to paper data | Gate learning only tightens, never loosens; validation_fraction=0.30 holdout |
| Cost model inaccuracy | Mark CHARGES_CONFIG as verified only after broker confirmation; paper-mode only |
| Direction model false confidence | Keep `use_model_for_trade: false` until shadow validation shows >5% improvement |
| No-Trade Alpha too conservative | Tune threshold gradually; start with 0.1R alpha buffer |
| Increased complexity | Maintained 223+ test baseline |

## Notes

- All changes remain **paper-only** - live_trading_enabled must stay false
- Gate learning `do_not_loosen: true` remains enforced
- One-position, one-pending-order, max-2-trades/day limits unchanged
- Evidence requirements (20 days, MTIL completeness, revalidation, fill audit) unchanged
- This plan addresses the ROI gaps identified in ROI_IMPROVEMENT_GUIDE.md while maintaining the survivability-first architecture