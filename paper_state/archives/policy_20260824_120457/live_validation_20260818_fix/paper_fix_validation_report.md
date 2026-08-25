# DHAN-v2 Paper-Only Fix and Live Validation Report

## Result

The post-fix Fyers-backed paper runner started successfully against the live market feed and completed healthy cycles. The runner was stopped after validation. No live order path was enabled or invoked.

## Implemented fixes

1. Hardened Fyers depth normalization for malformed, non-finite, zero-filled, or invalid bid/ask levels.
2. Required positive top-of-book price and quantity before accepting depth liquidity evidence.
3. Stopped treating zero-filled placeholder levels as valid five-level depth; five-level quantities are now recorded only when all first five levels on both sides are positive and usable.
4. Preserved valid top-of-book evidence when optional LTP/OI/volume fields are malformed, while retaining fail-closed behavior for invalid bid/ask or source timestamp data.
5. Added structured depth failure reasons to runner state and detailed diagnostic logging.
6. Added explicit `OPTIONS_CHAIN_UNAVAILABLE` and `fail_closed=true` state for instruments such as NIFTYFPI when Fyers does not return `data.optionsChain`.
7. Added dashboard visibility for depth status, five-level counts, rate-limit counts, and chain-unavailability reason codes.
8. Added regression tests for zero-filled levels, invalid best quotes, and missing option-chain data.

## Validation

| Check | Result |
|---|---|
| Python compilation | PASS |
| Unittest suite | PASS — 173 tests |
| Paper preflight | PASS — 59/59 instruments, live disabled, one open position maximum |
| Dashboard endpoint | HTTP 200 |
| Live cycle health | `last_cycle_ok=true` |
| Market state | Open during observation |
| Runner mode | `PAPER (no orders placed)` |
| Depth requests | 65 |
| Successful depth legs | 59 |
| Five-level legs | 55; zero-filled placeholder levels excluded |
| Failed depth legs | 6, fail-closed |
| Rate-limit errors | 0 |
| Open positions | 0 |
| Closed trades | 0 |
| Order-like log activity | None detected |
| Post-run process check | No runner/dashboard process remains |

## Remaining limitations

NIFTYFPI still has no usable Fyers option-chain payload and remains paper-eligible but fail-closed. BANKEX has a zero-filled best ask on one observed leg, and NIFTYNXT50 has invalid source timestamps on several observed legs; these cannot be safely fabricated or replaced by midpoint data. The transaction-cost configuration remains unvalidated, so canonical promotion remains blocked. The daily operator mode file is stale and the runner correctly falls back to computed `NORMAL` rather than treating stale manual context as current.

The validated code was committed locally as `4f14ccf` (`Harden live paper depth diagnostics and fail-closed handling`). It has not been pushed to `origin/main`.
