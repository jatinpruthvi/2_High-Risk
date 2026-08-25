# Pre-Paper-Data Readiness and Gate Report

## Executive conclusion

> **The codebase is ready for a controlled paper-data restart, but it is not ready to claim validated profitability or permit live execution.** The revised all-59 policy is configured, the safety boundary remains paper-only, fresh-run provenance is now enforced, cached contract metadata passes the 59-instrument audit, and the final test suite passes. The existing `paper_state` still contains legacy four-instrument evidence; it will be archived automatically when the revised runner starts.

This implementation does **not** manufacture paper trades or mark evidence criteria as passed without observations. The remaining 20-day, outcome, revalidation, fill, MTIL, and emergency-evidence requirements must be earned by a fresh paper-data run.

## Implemented readiness fixes

| Area | Implemented behavior |
|---|---|
| **Stale evidence isolation** | The runner now writes `run_manifest.json` with a policy signature, universe, live-execution status, and parameter provenance. If the state directory contains legacy evidence without a manifest, or a manifest with a different policy signature, the old evidence is moved into a timestamped `archives/policy_*` directory before the new run begins. Authentication files are preserved. |
| **Master provenance** | A real runner startup records `master_provenance.json` with exchange-master SHA-256 hashes, file timestamps, contract-row counts, expiry counts, CE/PE coverage, lot sizes, and tick sizes for every configured underlying. The runner refreshes the symbol masters through its normal startup path before selection. |
| **Offline preflight** | `python -m institutional_options.paper_trade --preflight` validates the 59-name universe, paper-enabled flags, one-position and one-pending-order limits, live-disabled status, and cached CE/PE, expiry, lot-size, and tick-size coverage without starting the runner or logging in. Current result: **PASS, metadata 59/59**. |
| **Gate-learning policy** | `warmup_days`, minimum observations, minimum learning days, minimum outcomes, winner quantile, high-watermark quantile, positive-expectancy requirement, and `do_not_loosen` are validated and used. The high-watermark gate is persisted per instrument. |
| **Evidence audit streams** | `revalidation_audit.csv` records both blocked and passed pre-entry/fresh-score revalidation. `paper_fill_audit.csv` records entry and exit fill attempts, including no-fill reasons. These streams do not replace closed-trade MTIL evidence. |
| **Paper-only override guard** | Any runner override that attempts to set `execution.live_trading_enabled` to `true` is rejected immediately. |
| **Regression coverage** | Added tests for configuration policy validation, high-watermark persistence, stale-state archival, run-manifest creation, and live-execution override rejection. |

## Validation results

| Validation | Result |
|---|---:|
| Recursive package and test compilation | PASS |
| JSON configuration parsing | PASS |
| Full unittest suite | **133 tests passed** |
| Offline paper preflight | **PASS** |
| Configured instruments | 59 |
| Paper-enabled instruments | 59 |
| Monitor-only instruments | 0 |
| Live execution | Disabled |
| Maximum open positions | 1 |
| Maximum pending orders | 1 |
| Cached contract metadata | 59/59 ready |

## Gate policy for the 59 instruments

Every instrument has its own gate record and snapshot identity, but it does not start with a separately optimized threshold. It starts at the conservative floor for its assigned instrument class. The current groups are six NSE indices, three BSE indices, and fifty NSE stock-option underlyings.

| Gate class | Instruments | Count | Contract quality minimum | ATM spread reject | Top-book minimum | Five-depth minimum | Excellent score minimum |
|---|---|---:|---:|---:|---:|---:|---:|
| `NSE_INDEX` | NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50, NIFTYFPI | 6 | 80 | 2.0% | 2 lots | 10 lots/side | 80 |
| `BSE_INDEX` | SENSEX, BANKEX, FOCIT | 3 | 85 | 3.0% | 3 lots | 15 lots/side | 85 |
| `NSE_STOCK_OPTION` | Configured NIFTY 50 stocks | 50 | 90 | 3.0% | 3 lots | 20 lots/side | 87 |

The common starting floors are direction **≥65**, premium elasticity **≥1.0**, expected/required ratio **≥1.6**, trade quality **≥70**, final confidence **≥65**, regime confidence **≥60**, market hostility **≤35**, and IV-crush risk **≤50**. Contract metadata, quote freshness, data health, expiry, risk fit, rank persistence, revalidation, paper-fill conditions, and the one-position lock remain independent mandatory controls.

### Instrument-specific learning

An individual instrument’s learned gates activate only after all of the following are satisfied:

| Requirement | Threshold |
|---|---:|
| Observations | At least 100 |
| Distinct sessions | At least 20, never below the configured five-day warm-up |
| Outcomes | At least 20 |
| Winners | At least 10 |
| Post-cost expectancy | Positive |
| Lower-bound winner quantile | Conservative 75th percentile, configured as `winning_quantile: 0.25` |
| Upper-bound features | Conservative upper-tail limit |
| Floor policy | `do_not_loosen: true` |

Until activation, every instrument remains at its class floor. After activation, learning may **tighten** an instrument’s gates from successful evidence; it cannot lower the class floor, bypass metadata validation, bypass revalidation, or force a paper entry. A per-instrument `high_watermark_gate` is also persisted from eligible passing observations for audit and future gate review.

## Remaining evidence-gated work

The following items are intentionally not fabricated by code and remain necessary before the paper phase can be considered complete:

| Priority | Item | Current state | Required next action |
|---|---|---|---|
| Critical | Fresh revised run | Existing `paper_state` is legacy four-instrument evidence | Start `python -m institutional_options.paper_trade` from the current working tree. The runner will archive stale evidence automatically and create a new manifest. |
| Critical | Trading days | Existing report had 2 of 20 required days | Collect at least 20 fresh market days under the all-59 manifest. |
| Critical | Revalidation evidence | Existing report had 0/0 | Let fresh cycles exercise both passed and blocked revalidation; review `revalidation_audit.csv`. Do not force a candidate merely to create a pass. |
| Critical | Paper-fill evidence | Existing report marked simulator evidence false | Review `paper_fill_audit.csv`; a successful closed simulated trade is still required for MTIL acceptance. No-fill observations are valid and should remain recorded. |
| Critical | MTIL completeness | Existing report had 0.00% | Confirm fresh closed paper trades populate the required MTIL fields. The system must not fill missing fields with guessed market data. |
| Critical | Emergency tests | Existing report did not record them as passed | Run the emergency/failure-path tests against the current tree and generate the evidence report with the explicit emergency-test flag only after the test run passes. |
| Operational | First-session review | Not yet performed under the revised manifest | Verify the startup log lists all 59 names, `run_manifest.json` exists, `master_provenance.json` exists, and no timeout/stale-data/mapping error causes a candidate to pass. |
| Evidence quality | Performance validation | Zero validated closed-trade sample in the legacy report | Do not interpret early paper results as a profitable edge. Review expectancy after costs by instrument, class, archetype, and regime only after sufficient sample size. |

## Safe start procedure

Run the offline check first:

```text
python -m institutional_options.paper_trade --preflight
```

Then start a clean or automatically isolated paper session:

```text
python -m institutional_options.paper_trade --state-dir paper_state
```

The process remains paper-only. It does not place broker orders, does not enable live trading, retains the one-open-position and one-pending-order limits, and does not permit leverage, pledge, overnight holding, or option selling. A no-trade session is valid research evidence; risk limits and gates must not be relaxed to create trades.

**This report is research and analysis only, not personalized financial advice.**

**Basis:** Current repository code, configuration, cached contract-master audit, paper-runner integration tests, and the 133-test validation run. **Time:** August 16, 2026 PDT. **Confidence:** High for code/configuration safeguards and metadata coverage; low for strategy profitability because the fresh all-59 evidence period has not yet been collected.
