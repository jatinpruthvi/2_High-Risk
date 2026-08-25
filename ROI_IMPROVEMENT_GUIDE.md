# ROI Improvement Guide — Institutional Options Paper System

## Project Snapshot

This is a systematic options-buying operating system for Indian index options (Bank Nifty, Nifty, FinNifty, Midcap Nifty). It is currently in **paper-mode only** — no live trading, no auto-execution, max 1 position, max 2 trades/day. The core philosophy is "stop us from buying bad options first; identify good option buys second."

**Capital:** ₹1,00,000 | **Risk per trade:** ₹250–₹1,000 (dynamic) | **Target ROI:** 80–150% annual net (Year 2+)

---

## Where the System Stands Today

The system has **41 passing unit tests** covering:
- MTIL schema validation and record building
- Phase 2 dry-run acceptance checks
- Cost model validation
- Direction model proxies (Nifty/FinNifty/Midcap)
- Dashboard HTML generation
- Phase 4 research gates
- Emergency/live-order hard locks

**Completed debt fixes (Evidence Integrity Sprint 1 & 2):**
- MTILRecordBuilder now fills all required schema fields with sentinels
- Phase 2 validator aligned to canonical MTIL field names
- Required stop model integrated into risk calculations
- CandidateFactory no longer uses threshold-passing defaults
- Dashboard HTML foundation implemented
- Direction models separated from candidate factory
- DataHealth expanded with option-chain semantic validation
- Charges config validation mechanism in place

**Remaining priorities (from development_debt.md):**
1. Wire real DHAN option-chain into parser/candidate factory
2. Populate MTIL from real dry-run cycles
3. Collect actual spread/slippage/elasticity baselines
4. Replace placeholder charges with verified broker rates

---

## ROI Analysis: Current State

### Strengths (What Drives ROI)

1. **Survivability-first architecture** — Daily loss cap (₹1,500), weekly cap (₹3,000), monthly halt (10%), hard stop-fit rule, and mandatory emergency exits. This keeps the system alive through drawdown periods, which is the #1 ROI driver for options trading.

2. **Dynamic risk sizing** — PlannedRisk can be ₹250–₹1,000 based on premium, stop distance, and volatility. Not every trade risks ₹750. Lower-risk entries in poor conditions, higher-risk only for A+ setups.

3. **Multi-instrument evaluation** — Currently evaluates 4 indices but trades only 1. This selects the single best candidate rather than taking suboptimal trades.

4. **Paper-fill realism** — Uses bid/ask conservative fills with slippage buffers. No LTP fantasy fills. This means paper results translate to real execution.

5. **Required-stop model** — 20% of premium as logical stop, floored by config. This prevents buying options where the thesis breaks before the premium is lost.

6. **Comprehensive scoring** — OpportunityScore combines 7 dimensions with calibration penalties for unvalidated instruments. MIDCPNIFTY gets +10 threshold penalty until validated.

### Gaps (Where ROI is Left on the Table)

1. **EV engine is not yet live** — ExpectedValue_R is defaulted to 0.0 in CandidateFactory (line 103 of candidates.py). The Top 10 Edge spec says EV>=0.30R is the final gate. Without this, the system may take statistically poor trades that look good on scores alone.

2. **ConvexityEdgeScore not computed** — Defaults to 0.0 in CandidateFactory (line 106). The Top 10 Edge spec ranks this as the #4 highest-impact improvement. Without convexity quality, direction-right/premium-wrong trades slip through.

3. **ExecutionQualityScore not computed** — Defaults to 0.0 in CandidateFactory (line 107). Poor fills and stale spreads are not being penalized in scoring.

4. **No-Trade Alpha Tracker missing** — OPT-10 from the BNIOS review says this is a "MUST ADD" because it validates whether filters save money. Skipped-candidate analysis exists in Phase 2 but isn't integrated into daily decision-making.

5. **Instrument uncertainty penalties are partial** — NIFTY/FINNIFTY/MIDCPNIFTY all get calibration penalties, but the direction model for NIFTY and FINNIFTY still uses proxy weights (equal-weighted top-liquid as fallback). This may cause the system to skip valid trades or take poor ones.

6. **Cost model is placeholder** — CHARGES_CONFIG.json is marked as placeholder. Net P&L calculations can't be trusted until verified broker rates are in place. Phase 2 validator checks for cost_model_valid=true, which will currently fail.

7. **Dynamic excellence threshold not fully implemented** — The spec calls for gap/expiry/IV crush/uncertainty penalties that raise the threshold, but the code's `_dynamic_threshold` only handles MIDCAPNIFTY liquidity penalty and IV crush >= 50. Gap day penalties, expiry day penalties, and same-direction loss penalties are not implemented.

---

## ROI Improvement Recommendations — Priority Order

### Tier 1: Critical for ROI (Implement Next)

#### 1. Implement the Expected Value Engine

**Why:** This is the single highest-impact improvement (Top 10 Edge #1). It converts score-based decisions into cost-adjusted expectancy. Without it, you're ranking candidates by quality proxy, not by actual expected profit.

**What to add:**
- `ExpectedValueEngine` class in `edge_modules.py` or new `expected_value.py`
- Formula: `EV_R = (WinProb × AvgWin_R) - (LossProb × AvgLoss_R) - Cost_R - Slippage_R - ThetaRisk_R - IVCrushRisk_R`
- Provisional win probability mapping from the spec:
  - A+ grade: 0.55, A grade: 0.48, B grade: 0.42 (paper only)
- Adjustments: +0.03 if ForcedFlow >= 85, +0.03 if ConvexityEdge >= 90, -0.05 if instrument unvalidated
- Cap: WinProb cannot exceed 0.62
- Threshold: EV_R >= 0.30R for live, >= 0.75R for A+

**Integration:** Add `expected_value_r` as a required field in CandidateInputs. Make EV_R >= 0.30 a hard gate in OpportunityScorer.

#### 2. Compute ConvexityEdgeScore

**Why:** Top 10 Edge #4. This prevents direction-right/premium-wrong trades. Currently defaults to 0.0, which means the OpportunityScore formula in PARAMETERS.json (which includes a 0.20 weight on convexity_quality_score) effectively ignores convexity.

**What to add:**
- Compute from existing EdgeInputs fields:
  - 0.30 × PremiumElasticityScore (normalize: >=1.20 = 100, >=1.00 = 85, >=0.80 = 70)
  - 0.25 × GammaUsefulnessScore (from greeks.delta: 0.40-0.60 = 100, 0.30-0.70 = 80, etc.)
  - 0.20 × ExpectedAccelerationScore (from vol_edge_ratio: median of ATR/regime/straddle projections)
  - 0.15 × IVSupportScore (inverse of IVCrushRiskScore)
  - 0.10 × TimeToProfitQualityScore (from position in session window)

**Integration:** Populate `convexity_edge_score` in CandidateFactory. Make >= 80 a required gate.

#### 3. Compute ExecutionQualityScore

**Why:** Top 10 Edge #4 (drawdown section). Poor fills destroy ROI even when direction is right. The paper-fill simulator exists but isn't scoring execution quality.

**What to add:**
- 0.25 × SpreadStabilityScore (based on spread_pct vs ideal/acceptable/reject from ClassGateSet)
- 0.20 × DepthPersistenceScore (top book lots + 5-depth lots from quote)
- 0.20 × QuoteFreshnessScore (based on data_health timestamp age)
- 0.15 × PaperFillProbabilityScore (based on paper-fill simulator output)
- 0.10 × SlippageBaselineScore (instrument-specific baselines)
- 0.10 × RequoteRiskScore (based on spread expansion multiple)

**Integration:** Populate `execution_quality_score` in CandidateFactory. Make >= 80 required (85 for Midcap).

#### 4. Implement No-Trade Alpha Tracker

**Why:** BNIOS review OPT-10 = "MUST ADD." This validates whether your filters actually save money. Without it, you can't tell if no-trade days are protecting capital or missing winners.

**What to add:**
- Track every skipped candidate with simulated forward outcome
- Classify as SAVED_LOSS (would have hit stop) or MISSED_WINNER (would have hit target)
- Aggregate by veto reason: DataHealth, ContractQuality, IV crush, direction, premium elasticity, etc.
- Log to skipped-candidate schema with forward_r_multiple field

**Integration:** Already partially in `skipped.py` and `phase2.py`. Need forward-simulation logic that tracks what would have happened if the trade was taken.

### Tier 2: High ROI Impact (Implement in Parallel)

#### 5. Complete the Dynamic Excellence Threshold

The current `_dynamic_threshold` in scoring.py only handles MIDCAPNIFTY and IV crush. The spec calls for:
- Gap day > 0.50%: +5
- Expiry day: +5
- IV crush risk 50-70: +5
- Midcap unvalidated: +10
- Same-direction recent loss: +10

**Action:** Extend `_dynamic_threshold` in OpportunityScorer to read gap_pct, expiry_week_flag, and same-direction loss state from candidate metadata. This prevents forcing trades in hostile conditions.

#### 6. Implement Session Alpha Map (OPT-09 from BNIOS review)

**Why:** Time-of-day is already in the config (`holding_time` section) but isn't scoring candidates. The 9:30–10:30 window has 25% better fill quality than lunch. The 14:30+ window should hard-block.

**What to add:**
- SessionBucket classification: Opening, Primary, MidSession, Lunch, Secondary, PowerHour, Close
- SessionQualityScore: Primary (100), Secondary (70), Lunch (-20 penalty), PowerHour (-10), Close (hard block)
- Apply as MarketHostilityScore adjustment and TradeQualityScore penalty

#### 7. Replace Placeholder Charges Config

The `CHARGES_CONFIG.json` is currently placeholder. Phase 2 validator requires `cost_model_valid=true`. Until verified rates are in place, every dry-run validation will fail at the cost_model_validity check.

**Action:** Fill in actual Dhan/NSE/SEBI/STT/GST rates:
- Dhan brokerage: ₹20/order (as of 2026, for cash segment; verify for options)
- STT: 0.0125% on sell-side only
- Exchange transaction charge: ~0.00297% for options
- SEBI turnover fee: 0.0001%
- Stamp duty: 0.00003% on buy
- GST: 18% on brokerage + etc

### Tier 3: Medium ROI Impact (Next 1–2 Months)

#### 8. Add Premium Elasticity Calculation

Currently `premium_elasticity = 0.0` in CandidateFactory. The runbook requires >= 1.00 for excellent candidates. Without real elasticity, the system can't properly score candidates.

**Implementation:**
- Calculate as: `delta_adjusted_elasticity = (option_mid_change / underlying_move_points) / option_delta`
- Use 60-second smoothing window with 2 confirmation windows
- Compare against required moves to determine if premium confirms direction

#### 9. Implement Same-Direction Recent Loss Cooldown

The config has `same_direction_recent_loss_cooldown_min: 30` and penalty `= 20` in the spec, but CandidateFactory doesn't track recent losses.

**Action:** Add state tracking that:
- Records instrument, side, and outcome of each trade
- If same-direction trade within 30 min after a loss: apply 20-point OpportunityScore penalty
- If still not excellent after penalty: NO_TRADE

#### 10. Wire Real Direction Models

Bank Nifty uses FastWBCI (weights for HDFCBANK/SBIN/ICICIBANK are loaded). But NIFTY, FINNIFTY, and MIDCPNIFTY use proxy models with UNVALIDATED status.

**Action:** Create `direction_models.py` with:
- NiftyLeadershipProxy: 50-stock equal-weighted or NIFTY 50 constituents with proper weights
- FinNiftyLeadershipProxy: FINNIFTY bank constituents (already has HDFC/SBI/ICICI weights)
- MidcapDirectionProxy: NIFTY_MIDCAP_150 constituents (requires instrument master for weights)

Each model should output: leadership_score (-100 to +100), confidence (0-100), and validation_status.

### Tier 4: Foundation for Long-Term ROI

#### 11. Implement Forced-Flow Score

**Why:** Top 10 Edge #3. Forced-flow trades (OI wall breaks, trapped shorts covering) have 2x the win rate of direction-only trades.

**Components needed:**
- OI wall stress detection (from option chain)
- Premium expansion velocity vs delta-only
- Futures impulse persistence
- Price acceptance beyond key levels
- Leadership confirmation

#### 12. Add Setup-Specific Expectancy Tracking

**Why:** Different setups perform differently. Gap fades lose money in trending markets. Breakouts win big in volatility expansion. Without setup-level tracking, you can't disable underperforming setups.

**Action:** Tag each candidate with setup_type (from playbooks.py). Track Expectancy_R, ProfitFactor, WinRate, MAE, MFE, TimeToProfit per setup. Auto-disable setups with Expectancy_R < 0 after 30 observations.

#### 13. Implement Opportunity Half-Life

**Why:** Top 10 Edge #9. Stale candidates have negative convexity. A great opportunity at 9:32 AM is garbage at 9:37 AM.

**Action:** Each candidate gets a half-life based on setup type (gap acceptance: 5-15 min, opening range: 1-3 min, etc.). Before order entry, check if candidate_age > half_life. If so: REVALIDATE_REQUIRED.

---

## Risk Controls That Protect ROI (Do Not Change)

1. **Max 1 open position** — Sequential correlation risk eliminated
2. **Max 2 trades/day** — Prevents overtrading and emotional revenge
3. **Hard stop-fit rule** — No trade if required logical stop doesn't fit risk cap. Never widen risk.
4. **Live trading disabled** — `live_trading_enabled = false` in config, enforced by SystemConfig.validate()
5. **No auto-execution** — `auto_execution_mvp = false`, all manual
6. **No leverage/pledge** — `pledge_or_leverage_allowed = false`
7. **No overnight holding** — All positions closed same day
8. **Gap wait rules** — 15-60 min wait based on gap size
9. **Cooldown after losses** — 15 min after 1 loss, 60 min after 2 losses
10. **Emergency exit protocol** — Hard close by 14:00 on expiry day

---

## Implementation Priority Matrix

| Priority | Improvement | ROI Impact | Effort | Risk |
|----------|-------------|------------|--------|------|
| P0 | Expected Value Engine | ★★★★★ | Medium | Low |
| P0 | ConvexityEdgeScore | ★★★★☆ | Medium | Low |
| P0 | ExecutionQualityScore | ★★★★☆ | Medium | Low |
| P0 | No-Trade Alpha Tracker | ★★★★☆ | Medium | Low |
| P1 | Dynamic Excellence Threshold | ★★★☆☆ | Low | Low |
| P1 | Session Alpha Map | ★★★☆☆ | Medium | Low |
| P1 | Replace Charges Config | ★★★★☆ | Low | Low |
| P1 | Premium Elasticity Calc | ★★★★☆ | Medium | Medium |
| P2 | Same-Direction Loss Cooldown | ★★★☆☆ | Low | Low |
| P2 | Direction Models (NIFTY/FINNIFTY/MIDCP) | ★★★☆☆ | High | Medium |
| P3 | Forced-Flow Score | ★★★☆☆ | High | Medium |
| P3 | Setup Expectancy Tracking | ★★★☆☆ | Medium | Low |
| P3 | Opportunity Half-Life | ★★☆☆☆ | Medium | Low |

---

## Key Files to Modify

1. **`institutional_options/edge_modules.py`** — Add EVEngine, ConvexityEdgeCalculator, ExecutionQualityCalculator classes
2. **`institutional_options/candidates.py`** — Populate expected_value_r, convexity_edge_score, execution_quality_score instead of hardcoding 0.0
3. **`institutional_options/scoring.py`** — Extend OpportunityScorer to use new scores and complete dynamic threshold
4. **`uploads/CHARGES_CONFIG.json`** — Replace placeholder with verified Dhan/SEBI/STT rates
5. **`institutional_options/direction_models.py`** — Add NIFTY/FINNIFTY/MIDCAPNIFTY leadership proxies with proper weights
6. **`institutional_options/records.py`** — Add session_bucket, gap fields, and No-Trade Alpha fields to MTIL schema mapping

---

## Final Note on ROI Philosophy

The top ROI improvements all follow the same pattern: **add filters that say "no trade" more often, not filters that say "trade" more often.** The system's edge comes from:
1. Taking only A/A+ candidates (scarcity)
2. Ensuring positive EV after costs (precision)
3. Avoiding bad executions (execution quality)
4. Validating what actually saves money (No-Trade Alpha)

The single most important change is **implementing the Expected Value Engine**. A trade that looks A+ on OpportunityScore but has negative EV after costs is a guaranteed money loser. EV_R >= 0.30R as a hard gate would immediately improve ROI by filtering out statistically poor trades that currently pass on score alone.

---

*Generated from project analysis of 41 unit tests, 6 source modules, 4 schema CSVs, and 10 specification documents. Project is APPROVED WITH FIXES per development_debt.md — paper-mode development, no live trading.*