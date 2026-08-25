# DHAN API Dependent Pending Items

**Purpose:** Track all items that cannot be fully completed until DHAN API credentials, access token, and live market/data access are available.

**Current status:**

```text
System coding can continue in paper/offline mode.
The items below require DHAN API key / access token / live data subscription / instrument master access / live market session to validate.
```

---

## 1. DHAN Credentials and Authentication

| ID | Pending Item | Why It Requires DHAN Access | Status |
|---|---|---|---|
| DAPI-001 | Verify `DHAN_CLIENT_ID` | Required for authenticated API calls | Pending API key |
| DAPI-002 | Verify `DHAN_ACCESS_TOKEN` | Required for REST/WebSocket calls | Pending API key |
| DAPI-003 | Validate token lifecycle / expiry | Access token behavior must be observed | Pending API key |
| DAPI-004 | Validate API permission level | Need to confirm data, option-chain, and order permissions | Pending API key |
| DAPI-005 | Confirm static IP requirement for future order APIs | Needed before any live order path | Pending broker/API setup |

---

## 2. Instrument Master Validation

| ID | Pending Item | Why It Requires DHAN Access/Data | Status |
|---|---|---|---|
| DAPI-006 | Download latest detailed instrument master | Needed for actual security IDs | Pending API/data access |
| DAPI-007 | Validate BANKNIFTY option/future mappings | Must confirm actual DHAN symbols/security IDs | Pending instrument master |
| DAPI-008 | Validate NIFTY option/future mappings | Same | Pending instrument master |
| DAPI-009 | Validate FINNIFTY option/future mappings | Same | Pending instrument master |
| DAPI-010 | Validate MIDCPNIFTY option/future mappings | Same | Pending instrument master |
| DAPI-011 | Confirm actual lot sizes per instrument | Risk sizing depends on true lot size | Pending instrument master |
| DAPI-012 | Confirm actual tick sizes via live quotes | Master tick field may need normalization | Pending live quotes |
| DAPI-013 | Confirm expiry calendars per instrument | Required for DTE and candidate selection | Pending option-chain/expiry API |
| DAPI-014 | Confirm strike ladder per instrument | Required for candidate generation | Pending option-chain/expiry API |

---

## 3. Live Market Data Validation

| ID | Pending Item | Why It Requires Live DHAN Feed | Status |
|---|---|---|---|
| DAPI-015 | Validate futures quote feed | Required for DataHealth and direction inputs | Pending live feed |
| DAPI-016 | Validate selected option quote feed | Required for PremiumElasticity and paper fills | Pending live feed |
| DAPI-017 | Validate bid/ask availability | Required for spread and ContractQuality | Pending live feed |
| DAPI-018 | Validate top bid/ask quantity fields | Required for LiquidityScore | Pending live feed |
| DAPI-019 | Validate 5-depth availability | Required for depth persistence | Pending live/depth feed |
| DAPI-020 | Validate quote timestamp behavior | Required for stale quote thresholds | Pending live feed |
| DAPI-021 | Validate WebSocket reconnect behavior | Required for emergency/no-trade logic | Pending live feed |
| DAPI-022 | Validate packet gap detection | Required for DataHealth engine | Pending live feed |

---

## 4. Option Chain API Validation

| ID | Pending Item | Why It Requires DHAN API | Status |
|---|---|---|---|
| DAPI-023 | Validate option-chain endpoint response | Parser must be tested against actual DHAN payloads | Pending API key |
| DAPI-024 | Validate expiry-list endpoint response | Required for expiry selection | Pending API key |
| DAPI-025 | Validate option-chain rate limit behavior | Need confirm 3-second rule in practice | Pending API key |
| DAPI-026 | Validate OI fields | Required for OI wall / OI change logic | Pending API key |
| DAPI-027 | Validate previous OI fields | Required for OI change | Pending API key |
| DAPI-028 | Validate IV field stability | Required for IVCrushRisk | Pending API key |
| DAPI-029 | Validate Greeks fields | Required for delta/gamma/theta/vega logic | Pending API key |
| DAPI-030 | Validate top bid/ask in option-chain vs live quote | Needed for stale/sync checks | Pending API + live feed |

---

## 5. Candidate Factory Live Validation

| ID | Pending Item | Why It Requires Live Data | Status |
|---|---|---|---|
| DAPI-031 | Generate real candidates from live option-chain | Candidate factory currently tested with synthetic data | Pending option-chain data |
| DAPI-032 | Validate ATM selection per instrument | Needs real strikes and live underlying price | Pending option-chain data |
| DAPI-033 | Validate CE/PE candidate creation | Needs real option-chain payload | Pending option-chain data |
| DAPI-034 | Validate ITM/ATM/OTM classification | Needs live strike ladder | Pending option-chain data |
| DAPI-035 | Validate candidate timestamps | Needs live feed behavior | Pending live data |

---

## 6. DataHealth Calibration

| ID | Pending Item | Why It Requires Live Feed | Status |
|---|---|---|---|
| DAPI-036 | Measure normal futures quote update interval | Needed to calibrate stale thresholds | Pending live data |
| DAPI-037 | Measure normal option quote update interval | Same | Pending live data |
| DAPI-038 | Measure normal option-chain refresh behavior | Same | Pending API data |
| DAPI-039 | Measure OI refresh behavior | OI is not tick-level | Pending API data |
| DAPI-040 | Measure IV refresh behavior | Required for IV validity windows | Pending API data |
| DAPI-041 | Validate reconnect stable-wait rule | Requires actual reconnects | Pending live feed |

---

## 7. Liquidity and Slippage Baselines

| ID | Pending Item | Why It Requires Live Data | Status |
|---|---|---|---|
| DAPI-042 | Build BANKNIFTY spread baseline | Required for ContractQuality calibration | Pending live quotes |
| DAPI-043 | Build NIFTY spread baseline | Same | Pending live quotes |
| DAPI-044 | Build FINNIFTY spread baseline | Same | Pending live quotes |
| DAPI-045 | Build MIDCPNIFTY spread baseline | Same; Midcap remains monitor-only | Pending live quotes |
| DAPI-046 | Build depth baseline by instrument | Required for ExecutionQuality | Pending depth feed |
| DAPI-047 | Build paper-fill slippage baseline | Required for fill realism | Pending live quotes |
| DAPI-048 | Measure no-fill frequency | Required for PaperFillProbability | Pending live/paper cycles |
| DAPI-049 | Measure spread shock frequency | Required for liquidity regime detection | Pending live data |

---

## 8. Premium Elasticity Calibration

| ID | Pending Item | Why It Requires Live Data | Status |
|---|---|---|---|
| DAPI-050 | Calculate live raw elasticity | Needs synchronized option/futures changes | Pending live feed |
| DAPI-051 | Calculate live delta-adjusted elasticity | Needs live greeks and quotes | Pending live feed/API |
| DAPI-052 | Build elasticity baseline by instrument | Required for ranking calibration | Pending paper cycles |
| DAPI-053 | Validate PremiumDominanceRatio | Needs CE and PE quote behavior | Pending live feed |
| DAPI-054 | Validate premium failure rules | Needs trade lifecycle data | Pending paper trades |

---

## 9. Expected Move / VolEdge Calibration

| ID | Pending Item | Why It Requires Data | Status |
|---|---|---|---|
| DAPI-055 | Build ATR remaining-move baseline | Needs intraday history/live candles | Pending data capture |
| DAPI-056 | Build ATM straddle implied-move baseline | Needs option-chain data | Pending API data |
| DAPI-057 | Validate ForecastRealizedMove accuracy | Needs forward outcomes | Pending paper cycles |
| DAPI-058 | Validate VolEdgeRatio thresholds | Needs trade/candidate outcomes | Pending paper cycles |
| DAPI-059 | Validate range-consumed filter | Needs intraday movement data | Pending paper cycles |

---

## 10. MTIL and Paper-Mode Live Validation

| ID | Pending Item | Why It Requires Live/Dry-Run Data | Status |
|---|---|---|---|
| DAPI-060 | Populate MTIL with real dry-run records | Current tests use synthetic data | Pending live dry-run |
| DAPI-061 | Populate skipped-candidate log with real cycles | Same | Pending live dry-run |
| DAPI-062 | Validate all required MTIL fields can be populated | Requires real candidate/evaluation flow | Pending dry-run |
| DAPI-063 | Validate ranking-cycle IDs | Requires live candidate cycles | Pending dry-run |
| DAPI-064 | Validate trade archetype tagging on real candidates | Requires real opportunities | Pending dry-run |
| DAPI-065 | Validate signal/regime/opportunity cluster IDs | Requires real ranking cycles | Pending dry-run |

---

## 11. Phase 2 Evidence Requirements Waiting For Live Dry-Run

| ID | Pending Item | Required Evidence | Status |
|---|---|---|---|
| DAPI-066 | 20 trading days dry-run | Minimum Phase 2 evidence period | Pending live dry-run |
| DAPI-067 | 100+ ranking cycles | Ranking validation | Pending live dry-run |
| DAPI-068 | 50+ simulated candidates | Basic paper sample | Pending live dry-run |
| DAPI-069 | No critical mapping errors in final 5 days | Mapping readiness | Pending live dry-run |
| DAPI-070 | No wrong lot/tick calculations | Risk readiness | Pending live dry-run |
| DAPI-071 | Candidate revalidation evidence | Execution readiness | Pending live dry-run |
| DAPI-072 | Paper-fill simulator evidence | Fill realism | Pending live dry-run |
| DAPI-073 | MTIL completeness evidence | Data quality | Pending live dry-run |
| DAPI-074 | Skipped-candidate completeness evidence | No-trade learning | Pending live dry-run |

---

## 12. Phase 3 Live-Readiness Items Waiting For Prior Evidence

| ID | Pending Item | Dependency | Status |
|---|---|---|---|
| DAPI-075 | Verify broker charges against actual account | Requires broker/DHAN account details | Pending API/account access |
| DAPI-076 | Verify emergency exit path | Requires actual broker access | Pending later phase |
| DAPI-077 | Verify order rejection behavior | Requires order API; not Phase 1/2 | Pending later phase |
| DAPI-078 | Compare paper vs live fills | Requires future approved micro-live test | Pending later phase |
| DAPI-079 | Confirm static IP setup if live order APIs used | Required before real orders | Pending later phase |

---

# Final Rule

Until DHAN credentials and live data are available:

```text
Continue coding offline/paper infrastructure.
Use synthetic fixtures for tests.
Do not assume live values.
Do not mark calibration as VALIDATED.
Do not enable live trading.
```

Once DHAN API key/access is available, resolve this file from top to bottom.
