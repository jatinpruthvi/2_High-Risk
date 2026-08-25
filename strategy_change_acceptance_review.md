# Strategy Change Acceptance Review

## Executive decision

The attached review is **substantively valuable and should not be dismissed**. It correctly identifies several gaps between the current paper-data foundation and the project’s stronger strategy/evidence specification. However, not every proposed fix should be applied literally.

The most important distinction is between **safety and evidence-integrity fixes**, which should be accepted, and **policy changes that would undo the user-approved all-59 paper-selector revision**, which should be rejected. The current project policy is intentionally:

> **All 59 configured instruments may participate in the main paper selector, while live review remains bounded to the original four indices.**

The attached review is also correct that a passing unit-test suite does not prove end-to-end readiness. The current repository has since reached 133 passing tests, but that still does not substitute for real multi-day paper evidence, real revalidation observations, valid fill records, or complete MTIL outcomes.

## Decision summary

| Finding | Decision | Priority | Short rationale |
|---:|---|---|---|
| 1. Mandatory excellent-candidate gates | **ACCEPT** | P0 | Execution quality, convexity quality, opportunity confidence, and regime fit must be explicit hard gates before ranking/entry. |
| 2. Portfolio no-trade engine not integrated | **ACCEPT** | P0 | The calculator exists but is not in the active selection path; broad weakness must be able to veto the best-of-weak candidates. |
| 3. A+ risk-budget formula | **ACCEPT** | P0 | The configured three-way cap must be implemented exactly; the current A+ path does not explicitly apply the normal-risk cap. |
| 4. DataHealth before candidate construction | **ACCEPT** | P0 | The richer health orchestrator is not wired into the active cycle, and current Fyers timestamps are cycle-assigned rather than source timestamps. |
| 5. MTIL affirmative defaults | **ACCEPT** | P0 | Safety and revalidation fields must reflect observed facts, not unconditional `True` values or fabricated `dte=0`. |
| 6. Revert the 59-name paper universe to four | **REJECT** | Policy | This contradicts the current user-approved all-59 paper policy. Accept the documentation correction, not the rollback. |
| 7. Complete candidate revalidation | **ACCEPT** | P0 | A fresh score alone is not a complete portfolio/entry revalidation snapshot. |
| 8. Proxy elasticity used for approval | **ACCEPT WITH CONDITIONS** | P1 | Keep the proxy for clearly labelled research/shadow analysis, but do not call it observed delta-adjusted elasticity or use it as validated approval evidence. |
| 9. Global/news risk enforcement disabled | **ACCEPT WITH CONDITIONS** | P0/P1 | Require verified, fresh risk/news context for acceptance or live review; retain disabled enforcement only in explicitly labelled proxy-research mode. |
| 10. Calibration overrides marked `VALIDATED` | **ACCEPT WITH CONDITIONS** | P0 | Preserve an operational paper override only if every row is tagged as override/proxy evidence and excluded from canonical validation. Do not represent unvalidated data as `VALIDATED`. |
| 11. Skipped-candidate forward MFE/MAE | **ACCEPT** | P2 | Needed before skipped-candidate analytics can support claims about saved losses or missed winners. It need not block broad data capture. |
| 12. Fyers mapping versus DHAN mapping | **ACCEPT WITH CONDITIONS** | P1 | Fyers mapping is acceptable for Fyers paper research, not as proof of DHAN execution correctness. Add a separate DHAN-master validation before any live review. |
| 13. Fyers liquidity fields unavailable | **ACCEPT** | P0/P1 | Missing quantities, depth, and IV must be labelled unavailable and excluded from positive liquidity calibration; they must not be silently treated as zero-quality observations or valid evidence. |
| 14. Emergency behavior and bypass | **ACCEPT** | P0 | Add deterministic outage/reconnect/fail-closed tests and remove unrestricted manual acceptance bypasses. |
| 15. Non-canonical MTIL test aliases | **ACCEPT** | P1 | Acceptance tests should use real canonical MTIL rows; legacy aliases may remain only for explicitly versioned historical data. |
| 16. Required-stop fallback to zero | **ACCEPT** | P0/P1 | Missing required-stop configuration must fail closed rather than silently making the stop requirement zero. |
| 17. Duplicate confidence authorities | **ACCEPT** | P2 | Establish one authoritative gate-resolution path and preserve class/instrument provenance. |
| 18. Structured mapping/lot/tick flags | **ACCEPT** | P1 | Populate them from actual validation and prevent the acceptance report from treating defaults as proof. |
| 19. Placeholder costs | **ACCEPT WITH CONDITIONS** | P1 | Paper capture may continue with an explicit unvalidated cost profile, but ROI/expectancy cannot be treated as reliable until broker/statutory rates are verified. |
| 20. Unrealized risk absent from daily/weekly budgets | **ACCEPT** | P1 | Reserve risk for the open simulated position so remaining-budget checks reflect actual exposure, not only realized P&L. |

## Detailed decisions

### 1. Mandatory excellent-candidate gates — **Accept**

This is a genuine P0 gap. The current scorer hard-rejects several configured dimensions, but the gate provider’s `execution_quality_min` defaults to zero, there is no explicit convexity minimum, and the active engine does not call the separate `AdvancedEdgeCalculator.final_edge_approval()` routine. The configured specification requires quality thresholds for execution, convexity, opportunity confidence, and regime fit.

The fix should be accepted, with one implementation constraint: **do not blindly call the advanced approval function using unavailable or fabricated inputs**. Implement explicit hard gates in the active scorer using the current gate snapshot, and make every unavailable required metric fail closed for an approval decision. Add exact boundary tests for values just below, equal to, and just above each threshold.

### 2. Portfolio no-trade engine — **Accept**

The finding is accurate. `PortfolioNoTradeCalculator` exists as a formula object, but the active `PaperOpportunityEngine` evaluates candidates, filters eligible rows, and selects the best one without computing the portfolio-wide weakness veto. This permits a technically eligible candidate to be selected even when the entire opportunity set is weak or data breadth is poor.

The calculator should be integrated before final selection. The runner should persist the component snapshot and veto reason. Missing inputs must not be converted into optimistic zeros; they should either produce a conservative veto or an explicit unavailable state that blocks approval.

### 3. A+ risk budget — **Accept**

The finding is accurate. The current risk calculator applies the A+ cap and separately checks 80% of remaining daily budget, but it does not express the configured new-trade cap as:

> `min(NormalRiskCap, InstrumentRiskCap, 0.80 × RemainingDailyBudget)`

The implementation should calculate and persist this exact cap, compare planned risk against it, and emit a structured rejection code. This should apply to A+ and should not be weakened by paper-only overrides. Paper mode can use different explicitly documented caps, but the same formula must apply to the active profile.

### 4. DataHealth integration — **Accept**

This is a genuine P0 issue. The active runner builds candidates with `DataHealth(True)` and does not invoke the richer `DataHealthOrchestrator` before candidate construction and ranking. In addition, the Fyers parser assigns the current cycle timestamp to parsed quotes rather than preserving an exchange/source timestamp, so quote freshness cannot be honestly established from that field.

The accepted fix is to integrate instrument, chain, option, and global health checks before ranking. The parser should preserve source timestamps when available. When source timestamps, packet continuity, reconnect status, or chain semantics are unavailable, the system may continue broad research capture, but it must not claim a valid approval-quality data-health result.

### 5. MTIL affirmative defaults — **Accept**

This finding should be accepted without qualification. The MTIL builder currently hardcodes `entry_revalidation_passed`, mapping, lot-size, and tick-size fields as affirmative and uses `dte=0` and sentinel/zero values for several analytical fields. Even if the upstream path often validates some of these conditions, the record does not prove that the value came from that validation.

The builder should receive an explicit evidence snapshot containing actual values and provenance. Unknown values must be represented as unavailable or false according to the schema semantics. The phase-2 validator must distinguish **field populated** from **requirement proven**. A populated `false` or `UNAVAILABLE` field should not be accepted as a safety pass.

### 6. Four-index rollback — **Reject the rollback; accept the documentation correction**

The attached finding correctly detects a contradiction between older frozen-scope text and the newer all-59 policy. However, the recommended rollback to four paper-enabled instruments should be rejected because the current user-approved policy explicitly promotes all 59 configured instruments into the main paper selector. The four-index boundary is now the **live-review boundary**, not the paper-data boundary.

The correct action is to make the policy canonical everywhere:

| Boundary | Correct policy |
|---|---|
| Main paper selector | All 59 configured instruments, subject to class and instrument gates |
| Live review | Original four indices only |
| Live order placement | Disabled |
| Evidence profile | All-59 paper policy, separately versioned from any former four-index evidence |

Older TODO/specification text that still calls the four names the only trade-enabled baseline should be revised, not used to silently undo the current policy.

### 7. Candidate revalidation — **Accept**

The current `CandidateRevalidator` checks candidate age, quote validity, spread expansion, score threshold, and hard-stop fit. The runner then rescans the refreshed candidate, which is useful but does not replace an explicit final portfolio snapshot. The attached finding is therefore materially correct.

The accepted design is to recompute the full candidate and portfolio gate snapshot at revalidation time, including DataHealth, metadata, ContractQuality, observed/proxy elasticity status, expected/required ratio, IV-crush, hostility, score, hard-stop fit, global risk, overlap, position lock, pending-order lock, and current paper-fill eligibility. Persist every result, including blocked reasons.

### 8. Proxy elasticity — **Accept with conditions**

The finding is accurate: the current approval-side elasticity begins with a moneyness delta proxy, while the observed bid/ask-aware calculator remains diagnostic. The proxy is acceptable for **clearly labelled research or shadow ranking**, because collecting broad observations is part of the project’s purpose. It is not acceptable to call that value observed delta-adjusted elasticity or to use it as validated evidence of the authoritative formula.

The accepted condition is a mode separation:

| Mode | Proxy elasticity | Observed elasticity |
|---|---|---|
| `PROXY_RESEARCH` | May be recorded and used for exploratory ranking | Optional |
| Strict paper-entry evidence | May not be represented as observed approval evidence | Required or candidate remains blocked |
| Live review | Not sufficient | Required, validated, and cost-adjusted |

### 9. Global/news risk filter — **Accept with conditions**

The specification requires these filters, but enabling them without a verified and fresh source would be unsafe because the system would either make unsupported decisions or block inconsistently. The current configuration’s disabled enforcement is therefore acceptable only as an explicitly named **proxy-research mode**, not as a claim of full acceptance readiness.

For strict paper-entry acceptance and any future live review, the source must be verified, timestamped, fresh, and fail closed when missing or stale. The system should record `RISK_CONTEXT_UNAVAILABLE` rather than silently treating unavailable context as normal.

### 10. Calibration overrides — **Accept with conditions**

The attached finding identifies a real evidence-integrity risk. The runner configuration currently contains a paper-only calibration override that labels core direction and liquidity as `VALIDATED`, even though the frozen parameters identify those areas as unvalidated. The comment documents the intent, but a comment does not prevent downstream analytics from interpreting the value as empirical validation.

The override should not be removed if it is needed to observe the paper selector, but it must be renamed and partitioned. Recommended labels are `PAPER_OVERRIDE`, `PROXY_RESEARCH`, or `UNVALIDATED_WITH_OVERRIDE`; the canonical calibration status should remain empirical and unvalidated. Every candidate, skipped row, shadow outcome, MTIL row, manifest, and report must carry the profile and exclude override rows from frozen-parameter validation.

### 11. Skipped-candidate MFE/MAE — **Accept**

This is an important P2 evidence improvement. Current skipped-candidate rows cannot prove that a rejection saved a loss or missed a winner unless future price/quote observations are attached to the original candidate. Implement a forward-observation queue keyed by `skip_id`, with explicit 5-minute, 15-minute, and 30-minute windows and conservative bid/ask-aware outcomes.

This should not force trades or block broad paper-data capture. It should block claims based on skipped-winner or saved-loss statistics until the forward outcomes are actually populated.

### 12. Fyers mapping versus DHAN mapping — **Accept with conditions**

Fyers mapping is valid for a Fyers-backed paper-research session, but it cannot establish that a future Dhan order would use the same security ID, freeze quantity, buy/sell indicator, lot size, tick size, expiry, or strike ladder. The correct label is `FYERS_PAPER_RESEARCH_ONLY`.

Before any live review, add a DHAN detailed-master cross-check and require agreement on contract identity and risk metadata. Do not treat successful Fyers paper selection as evidence of Dhan order-routing correctness.

### 13. Fyers liquidity unavailability — **Accept**

The parser supplies zero bid/ask quantities, no five-level depth, and unavailable Greeks/IV for the Fyers chain path. Those are not valid observations of market liquidity. The current system’s contract gates may reject such candidates, but the evidence layer must also distinguish `LIQUIDITY_UNAVAILABLE` from a genuine measured low-liquidity result.

The accepted fix is to label those fields unavailable, exclude them from positive liquidity calibration denominators, and prevent them from being used to claim validated execution quality. A richer validated feed is required before liquidity-dependent performance conclusions are made.

### 14. Emergency behavior and bypass — **Accept**

This is a P0 operational gap. The runner catches cycle exceptions and continues, but the specification requires deterministic handling of disconnects, stale feeds, reconnect stabilization, incidents, and unmanaged-position conditions. The daily evidence script also exposes `--assume-tests-passed`, which can mark the emergency check true without executing tests.

Add deterministic failure-path tests and make new entries fail closed after outage, stale-feed, or reconnect events until a stability window passes. Remove the unrestricted assumption flag, or require a verifiable test artifact tied to the current code and configuration. The evidence report must never claim emergency readiness from a manually asserted boolean alone.

### 15. Canonical MTIL test aliases — **Accept**

Acceptance fixtures should be built from the real `MTILRecordBuilder` using canonical field names. Backward-compatible aliases may remain for explicitly versioned legacy data, but they must not be used by the current acceptance fixture. This is a straightforward evidence-quality improvement.

### 16. Required-stop fallback — **Accept**

A missing required-stop configuration currently returns zero. That is unsafe because it can make a candidate appear to satisfy a stop requirement that was never calculated. Missing, malformed, or disabled required-stop configuration should produce a hard candidate block for any mode that permits paper entry.

### 17. Confidence-floor authority — **Accept**

The current system consults global score floors and instrument gate floors using `max()`. This is conservative, but it makes the authority ambiguous and can produce confusing audit records. Keep one explicit resolution function: global policy floor, class floor, instrument learned floor, and active-mode floor should be resolved in a documented order and persisted as a single gate snapshot.

The fix should not lower any existing threshold. It should clarify precedence and preserve the per-instrument provenance already implemented.

### 18. Structured mapping flags — **Accept**

This is coupled to finding 5. Mapping, lot-size, tick-size, expiry, strike, and buy/sell validation flags should be generated by the actual mapping/contract-validation path and passed into MTIL. Default affirmative values must be removed. Missing flags should produce `UNAVAILABLE` or a failed acceptance check, not a pass.

### 19. Cost configuration — **Accept with conditions**

Verified broker and statutory charges are essential for post-cost expectancy, risk sizing, and ROI claims. Paper capture can continue with a clearly named placeholder cost profile, but evidence rows must carry `COST_MODEL_UNVALIDATED`, and no profitability or live-readiness conclusion should rely on those results. Before live review, replace the placeholder with verified current rates and regression-test the round-trip calculation.

### 20. Unrealized risk in daily/weekly budgets — **Accept**

The risk controller should reserve the risk of the open simulated position when deciding whether another entry is allowed and when evaluating daily/weekly limits. The current one-position rule prevents a second position, but it does not by itself make realized-P&L-only budgets a complete exposure measure. Add an explicit open-risk reservation and persist the calculation in the risk snapshot.

## Recommended implementation order

| Order | Workstream | Findings | Reason |
|---:|---|---|---|
| 1 | Truthful safety gates and risk | 1, 3, 4, 5, 7, 16, 18 | Prevent invalid candidates and fabricated acceptance evidence. |
| 2 | Portfolio veto and failure handling | 2, 14, 20 | Prevent best-of-weak selection and unsafe continuation after outages or open-risk changes. |
| 3 | Evidence-profile separation | 6, 8, 9, 10, 12, 13, 19 | Preserve the all-59 paper policy while preventing proxy, override, Fyers-only, and placeholder-cost data from being mistaken for validated/live evidence. |
| 4 | Research-quality enrichment | 11, 15, 17 | Improve skipped analytics, canonical fixtures, and gate provenance after safety is correct. |

## Final policy recommendation

**Accept the safety and evidence-integrity findings. Accept several research improvements with explicit conditions. Reject only the recommendation to roll the paper universe back from 59 to four.** The correct outcome is an all-59 paper-data system with strict, truthful gates and a separate four-index live-review boundary.

Until the P0 items are implemented and a fresh run produces truthful revalidation, fill, MTIL, and emergency evidence, the authoritative status should remain:

```text
Paper-data development: ALLOWED
All-59 paper selector: ALLOWED under strict gates
Validated strategy evidence: NOT YET ESTABLISHED
Live trading: NO-GO
```

**Basis:** Current repository implementation, active `PARAMETERS.json` and `PAPER_RUNNER.json`, the project’s all-59 paper-policy requirement, and the user-supplied strategy review. **Time:** August 16, 2026 PDT. **Confidence:** High for the wiring and evidence-integrity classifications; medium for exact line-level details in the supplied review because the attachment reports 128 tests while the current working tree has since reached 133 tests. This is research and analysis only, not personalized financial advice.
