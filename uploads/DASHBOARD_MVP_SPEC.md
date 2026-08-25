# Multi-Instrument MVP Dashboard Specification

## Purpose
The MVP dashboard must reduce decision latency and prevent bad trades. It is not a research heatmap. Phase 1 evaluates BANKNIFTY, NIFTY, FINNIFTY, and MIDCPNIFTY, ranks all candidates, and allows only one open position at a time.

## Dashboard Rule

```text
If the dashboard cannot show the decision in under 15 seconds, it is too complex.
```

## MVP Panels

## 1. Health Panel

Displays:

- DHAN WebSocket status
- REST option-chain status
- selected option quote freshness per evaluated instrument
- futures quote freshness per evaluated instrument
- packet gap warning
- reconnect state
- instrument master date
- data valid / invalid flag

Hard output:

```text
DATA OK / DATA INVALID
```

## 2. Risk Mode Panel

Displays:

- Normal / Defensive / Survival / No-Trade
- daily P&L
- weekly P&L
- daily loss remaining
- trades taken today
- cooldown status
- rule violation flag

Hard output:

```text
RISK OK / REDUCED / SHUTDOWN
```

## 3. Opportunity Ranking / Direction Panel

Displays one compact row per eligible instrument:

- instrument: BANKNIFTY / NIFTY / FINNIFTY / MIDCPNIFTY
- candidate side: CALL / PUT / NONE
- direction score / band
- instrument leadership state
- futures vs VWAP / opening range status
- ContractQualityScore
- PremiumElasticity
- ExpectedMove / RequiredMove
- IVCrushRiskScore
- MarketHostilityScore
- OpportunityScore
- rank

Hard output:

```text
BEST: INSTRUMENT + CALL/PUT / NO EXCELLENT CANDIDATE / GLOBAL LOCK ACTIVE
```

## 4. Option Quality Panel

Displays details for the currently highest-ranked candidate only:

- selected instrument
- selected CE/PE
- bid / ask / mid
- spread %
- depth lots
- ContractQualityScore
- PremiumElasticity
- ExpectedMove / RequiredMove
- IVCrushRiskScore
- max allowed risk rupees
- planned risk rupees
- hard stop points
- trade allowed by stop-fit

Hard output:

```text
CONTRACT OK / CONTRACT INVALID
```

## 5. Decision / Journal Panel

Displays final status:

- BUY CALL CANDIDATE
- BUY PUT CANDIDATE
- WAIT
- AVOID
- DEFENSIVE
- SURVIVAL
- NO-TRADE
- EXIT WARNING
- DATA INVALID
- CONTRACT INVALID

Also records:

- reason for decision
- veto triggered
- manual notes
- save journal button / automatic log

## Phase 1 Dashboard Constraint

```text
Show ranking compactly. Do not create four full dashboards.
The trader must see the best candidate and no-trade reasons within 15 seconds.
```

## Not in MVP Dashboard

- GEX map
- full option-chain heatmap
- all-bank option chains
- social sentiment
- AI explanation
- 20/200-depth map
- advanced Greeks
- full scenario registry

These are research/back-office items only.

---

## Phase 1 Completion Dashboard Additions

The ranking panel must also show:

- calibration status per instrument,
- candidate age in seconds,
- final revalidation status,
- instrument uncertainty penalty,
- liquidity baseline status,
- whether paper/live fill simulation is active,
- reason why top candidate is not tradable if rejected.

Hard rule:

```text
If top candidate revalidation fails, dashboard must not auto-promote rank #2.
It must show RECALCULATE REQUIRED.
```

Midcap Nifty display rule:

```text
If Midcap liquidity baseline is not passed, display MIDCAP CONDITIONAL / MONITOR-ONLY unless all stricter live criteria pass.
```
