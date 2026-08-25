# Emergency Exit and Failure Test Specification

## Purpose
Define how the MVP behaves if DHAN, internet, broker API, dashboard, or local system fails during market hours.

## Core Rule

```text
If execution reliability is uncertain, do not add risk.
If in position, prioritize risk reduction through the most reliable available channel.
```

## Test 1 — WebSocket Disconnect While Flat

Expected behavior:

1. DataHealth becomes invalid.
2. Dashboard shows NO-TRADE.
3. No trade candidate can be generated.
4. Reconnect attempts start.
5. After reconnect, wait 30 seconds stable data before signals resume.

## Test 2 — WebSocket Disconnect While In Position

Expected behavior:

1. No add allowed.
2. Mark position as unmanaged-risk state.
3. Use broker app/web/API to monitor/exit if needed.
4. Record incident in journal.
5. Resume only after manual review.

## Test 3 — REST Option Chain Failure

Expected behavior:

1. OI/IV/GEX context frozen.
2. No new trade if trade depends on option-chain context.
3. Existing position managed using live selected option quote and futures.
4. Retry with backoff.

## Test 4 — Order Rejection

Expected behavior:

1. Freeze new signals.
2. Log rejection reason.
3. Refresh order book/positions.
4. Do not retry blindly.
5. Resume only after cause identified.

## Test 5 — Internet Failure

Expected behavior:

1. Use backup internet if available.
2. If in position, use mobile broker app/web to exit if risk requires.
3. If no execution access, no new decisions; record incident.

## Test 6 — Dashboard Freeze

Expected behavior:

1. If timestamps stale, trader must not trade.
2. Restart dashboard.
3. Verify data recovery.
4. Wait 30 seconds stable data.

## Test 7 — Wrong Instrument Mapping Simulation

Expected behavior:

1. ContractQuality and mapping validation fail.
2. No trade candidate allowed.
3. Mapping error logged.

## Pass Criteria

The emergency system passes if:

- no new trade can be generated during data invalid state,
- order rejection does not trigger repeated blind retries,
- stale dashboard prevents trading,
- incident is logged,
- and recovery requires stable data before resuming.

---

## Phase 1 Multi-Instrument Failure Rule

If any core data/execution failure occurs while flat:

```text
All instruments are blocked from new entries.
```

If an instrument-specific feed fails:

```text
Remove that instrument from the opportunity ranking.
Do not substitute stale data.
```

If a position is open in any eligible instrument:

```text
Global position lock remains active.
No new trade in BANKNIFTY, NIFTY, FINNIFTY, or MIDCPNIFTY is allowed until the open position is closed and system health is restored.
```
