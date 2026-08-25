# Multi-Instrument Index Option-Buying MVP Production Runbook

**Version:** MVP v1.0  
**Capital:** ₹1,00,000  
**Mode:** Manual execution only  
**Universe:** Bank Nifty, Nifty, FinNifty, Midcap Nifty  
**Lot limit:** 1 index option position maximum  
**Leverage / pledge:** Not allowed  
**Overnight holding:** Not allowed  
**Primary purpose:** Prevent bad option buys first; identify good option buys second.

---

## 0. What This File Is

This is the **live trading runbook** for the MVP.

The full master document is the institutional research reference. This runbook is the **only actionable live checklist** during market hours.

```text
Master document = knowledge / research / architecture
MVP runbook = live execution rules
```

If a live rule is not in this runbook, it cannot trigger a trade in MVP.

---

## 1. Non-Negotiable MVP Rules

1. Trade only eligible index options: Bank Nifty, Nifty, FinNifty, Midcap Nifty.
2. Trade only the single highest-ranked excellent opportunity.
3. Maximum open positions = 1 across the entire universe.
4. Maximum pending orders = 1 across the entire universe.
5. Do not trade if no excellent candidate exists.
6. No pledge.
7. No leverage.
8. No averaging losing options.
9. No overnight holding.
10. No auto-trading.
11. No pure market order for entry.
12. No new trade before 9:30 AM.
13. No trade if data is stale, spread is abnormal, or contract quality fails.
14. No trade if the hard stop cannot fit the risk limit.
15. No trade if the setup cannot be explained through the 5-gate decision cycle.

---

## 2. Dynamic Risk Limits

### Core Interpretation

```text
₹750 is the normal-mode maximum risk ceiling, not the target risk.
Actual risk is dynamic and may be lower than ₹750.
```

The system must never interpret `normal_risk_cap_rupees = 750` as:

```text
Every trade must risk exactly ₹750.
```

It means only:

```text
Normal-mode planned loss must not exceed ₹750.
```

Actual risk may be ₹250, ₹400, ₹600, or ₹750 depending on premium, stop distance, volatility, spread, setup quality, and regime.

| Rule | Limit |
|---|---:|
| Normal risk cap | 0.75% of capital = ₹750 maximum |
| Preferred normal risk band | ₹400–₹600 when trade quality is good but not A+ |
| Minimum meaningful planned risk | ₹250 |
| A+ risk cap | 1.00% of capital = ₹1,000 maximum |
| Defensive mode risk | ₹250–₹500 maximum |
| Survival mode risk | ₹0 new speculative risk |
| No-trade mode risk | ₹0 |
| Max daily loss | ₹1,500 or 2 cap-sized/full-risk losses |
| Max weekly loss | ₹3,000 |
| Monthly review drawdown | 6% |
| Monthly hard halt | 10% |
| Max trades per day | 2 total across all instruments |
| Max consecutive losses | 2 losses = 60-min cooldown; 3 losses = stop for day |

### Dynamic Risk Bands

These are guidance bands and caps, not minimum-risk requirements. Dynamic stop logic may produce lower actual planned risk.

| Setup Quality / Mode | Planned Risk Guidance |
|---|---:|
| C-grade / unclear | No trade |
| B-grade | ₹250–₹400 |
| A-grade | usually ₹500–₹750 cap; may be lower if premium stop is smaller |
| A+ grade | up to ₹1,000 max; may be lower if dynamic stop is smaller |
| Defensive mode | ₹250–₹500 |
| Survival mode | ₹0 |
| No-trade mode | ₹0 |

### Position Size and Stop-Fit Rule

```text
MaxAllowedRisk = min(Capital × risk_pct_for_mode, risk_cap_for_mode)
StopRiskPerLot = stop_points × lot_size
PlannedRisk = StopRiskPerLot × number_of_lots
```

For each selected instrument, use the DHAN instrument-master lot size. Example for Bank Nifty if lot_size = 30:

```text
₹750 normal risk cap = 25 option points maximum stop for 1 lot
₹1,000 A+ cap = 33.33 option points maximum stop for 1 lot
```

Hard rule:

```text
If the required logical stop risk exceeds MaxAllowedRisk, skip the trade.
Do not widen risk to fit a trade.
Do not force full ₹750 risk if the premium-based stop is smaller.
```

---

## 3. Dynamic Hard Stop-Loss Rules

Every trade must have a hard stop before entry. The hard stop is dynamic and must respect both premium percentage and rupee risk cap.

### Normal Trade

```text
MaxAllowedRisk = min(Capital × 0.75%, ₹750)
HardStopPoints = min(25 option points, 20% of entry premium, MaxAllowedRisk / lot_size)
PlannedRisk = HardStopPoints × lot_size × lots
```

### A+ Trade

```text
MaxAllowedRisk = min(Capital × 1.00%, ₹1,000)
HardStopPoints = min(33 option points, 25% of entry premium, MaxAllowedRisk / lot_size)
PlannedRisk = HardStopPoints × lot_size × lots
```

### Defensive Trade

```text
MaxAllowedRisk = Capital × 0.25% to 0.50%
For ₹1,00,000 capital: ₹250–₹500 maximum
HardStopPoints must fit within that cap.
```

### Examples

If entry premium is ₹80:

```text
20% premium stop = 16 points
Risk = 16 × 30 = ₹480
Actual planned risk = ₹480, not ₹750
```

If entry premium is ₹100:

```text
20% premium stop = 20 points
Risk = 20 × 30 = ₹600
Actual planned risk = ₹600, not ₹750
```

If entry premium is ₹400:

```text
20% premium stop = 80 points
Risk cap stop = ₹750 / 30 = 25 points
HardStopPoints = min(25, 80, 25) = 25 points
Actual planned risk = ₹750
```

### Hard Stop Authority

If option premium reaches the hard stop:

```text
Exit immediately.
No debate.
No averaging.
No thesis rescue.
```

---

## 4. MVP 5-Gate Live Decision Cycle

A trade candidate exists only if all five gates pass.

```text
Gate 1: Data OK?
Gate 2: Contract OK?
Gate 3: Regime OK?
Gate 4: Direction + Premium OK?
Gate 5: Market Hostility OK?
```

If any gate fails:

```text
WAIT / AVOID / DEFENSIVE / SURVIVAL / NO-TRADE
```


---

## 3A. Phase 1 Multi-Instrument Opportunity Selection Rule

The MVP now evaluates four index-option instruments but still permits only one active opportunity.

```text
Evaluate: BANKNIFTY, NIFTY, FINNIFTY, MIDCPNIFTY
Rank all candidates.
Trade only the highest-ranked excellent candidate.
If no candidate is excellent, no trade.
```

This is not permission to trade more. It is permission to choose better.

### Global Position Lock

```text
If any position is open in any eligible instrument:
    no new trade in any other instrument.

If any order is pending in any eligible instrument:
    no new order in any other instrument.
```

### Excellent Candidate Requirement

A candidate must pass all of the following before it can be ranked as tradable:

```text
ContractQualityScore >= 80
PremiumElasticity >= 1.00
ExpectedMove/RequiredMove >= 1.60
MarketHostilityScore <= 35
IVCrushRiskScore <= 50
RegimeConfidence >= 75
HardStopFit == true
DataHealth == valid
```

If none pass:

```text
NO TRADE
```

### Midcap Nifty Caution

Midcap Nifty is included in Phase 1 evaluation, but it requires stricter liquidity validation until enough spread/slippage data is captured.

```text
If Midcap Nifty spread, depth, or quote freshness is not clearly excellent:
    exclude it from live trade selection.
```

### Sequential Correlation Protection

Maximum one open position removes concurrent correlation risk, but not sequential overtrading risk.

If a trade loses and another same-direction index trade appears within 30 minutes:

```text
Apply same-direction recent-loss penalty.
Trade only if still excellent after penalty.
```
---

# GATE 1 — Data OK?

## Required Conditions

| Data Check | Pass Requirement |
|---|---| 
| Bank Nifty futures feed | Fresh; no stale invalid flag |
| Selected option quote | Fresh bid/ask |
| DHAN WebSocket | Connected and stable |
| Option chain | Fresh enough for IV/OI context |
| Instrument mapping | Verified from daily DHAN master |
| Dashboard timestamps | Current and visible |

## Data Health Thresholds

| Item | Warning | Invalid |
|---|---:|---:|
| Bank Nifty futures tick | 3 sec no update | 5 sec no update |
| Selected option quote | 5 sec no update | 8 sec no update |
| Option-chain snapshot | 15 sec stale for entry | 30 sec invalid |
| IV data | 30 sec downgrade | 60 sec invalid |
| OI data | 180 sec downgrade | 300 sec invalid |

## Data Gate Decision

```text
If DataHealth invalid → NO TRADE.
If reconnect occurred → wait 30 seconds of stable data before trading.
```

---

# GATE 2 — Contract OK?

Use only liquid ATM / slightly ITM contracts in MVP.

## Contract Quality Requirements

| Check | Required |
|---|---:|
| ContractQualityScore | ≥70 |
| Preferred ContractQualityScore | ≥80 |
| ATM spread | ≤1.5% acceptable; >2.0% reject |
| ITM spread | >2.5% reject |
| OTM spread | >4.0% reject |
| Absolute spread cap | Avoid if >8 points |
| Top bid/ask quantity | Minimum 2 lots each side |
| 5-depth liquidity | Minimum 10 lots each side |
| Bid/ask validity | Bid and ask must both exist |

## Contract Gate Hard Rejects

Reject if:

- bid = 0,
- ask = 0,
- quote stale,
- spread abnormal,
- IV invalid for active strike,
- no realistic exit liquidity,
- premium does not respond to futures move.

---

# GATE 3 — Regime OK?

## Tradable Regimes

| Regime | Trade Permission |
|---|---|
| Trend expansion | Allowed if premium/contract confirms |
| Range-to-trend transition | Allowed after breakout acceptance |
| Post-compression expansion | Allowed after trigger |
| Gap continuation after acceptance | Allowed after gap rules pass |
| Gamma/strike break | Allowed only if premium elasticity confirms |

## Avoid / No-Trade Regimes

| Regime | Action |
|---|---|
| Flat VWAP range | No trade |
| Choppy overlapping candles | No trade |
| Dealer pin / expiry magnet | Avoid |
| Lunch decay without trend | Avoid |
| Post-event IV crush drift | Avoid |
| News chaos | Survival / wait |
| Regime confidence <60 | Wait / no trade |

---

# GATE 4 — Direction + Premium OK?

This gate combines directional confirmation and option premium confirmation.

## Direction Requirements

For **Call Candidate**:

```text
Instrument DirectionScore bullish or improving
+ selected instrument futures above VWAP / accepted above OR
+ instrument leadership proxy not contradicting
+ no major resistance immediately above
```

For **Put Candidate**:

```text
Instrument DirectionScore bearish or weakening
+ selected instrument futures below VWAP / accepted below OR
+ instrument leadership proxy not contradicting
+ no major support immediately below
```

## Instrument Direction Logic

Bank Nifty uses FastWBCI. Nifty, FinNifty, and Midcap Nifty use instrument-specific price/futures/regime leadership proxies until dedicated weighted leadership engines are validated. Apply uncertainty penalties where leadership models are not yet fully validated.

## FastWBCI Formula

FastWBCI uses only top-3 live leadership for Bank Nifty entries:

```text
FastWBCI =
0.45 × Top3 VWAP State
+ 0.35 × Top3 5-minute Relative Strength
+ 0.20 × Top3 Volume/Futures Confirmation
```

Top 3:

```text
HDFCBANK, ICICIBANK, SBIN
```

## Direction Thresholds

| Score | Meaning |
|---:|---|
| Instrument DirectionScore / leadership score > +45 | Bullish permission |
| Instrument DirectionScore / leadership score < -45 | Bearish permission |
| -20 to +20 | Mixed; no-trade / wait |

## Premium Requirements

A trade is not valid unless option premium confirms.

| Premium Check | Required |
|---|---:|
| Delta-adjusted PremiumElasticity | ≥0.80 |
| Strong PremiumElasticity | ≥1.00 |
| Weak threshold | <0.60 warning |
| Reject / exit threshold | <0.50 |
| ExpectedMove / RequiredMove | ≥1.30 |
| Hard reject ratio | <1.10 |
| IVCrushRiskScore | Must not hard veto |

Phase 1 selection uses stricter excellent-candidate thresholds before ranking:

```text
PremiumElasticity >= 1.00
ExpectedMove/RequiredMove >= 1.60
ContractQualityScore >= 80
MarketHostilityScore <= 35
IVCrushRiskScore <= 50
```

---

# GATE 5 — Market Hostility OK?

MarketHostility is the simplified live version of NoTradeScore + ConflictScore.

## Hard No-Trade Conditions

No trade if any are true:

1. Daily loss limit hit.
2. Two-loss cooldown not completed.
3. DataHealth invalid.
4. ContractQuality <60.
5. Spread > hard reject threshold.
6. PremiumElasticity <0.50.
7. ExpectedMove / RequiredMove <1.10.
8. Regime confidence <60.
9. IVCrushRiskScore >85.
10. No clear invalidation.
11. Trade is FOMO / revenge motivated.
12. Trade cannot be explained through the 5 gates.

## MarketHostility Guide

| Condition | Action |
|---|---|
| Low hostility | Trade allowed if all gates pass |
| Medium hostility | Reduced risk only |
| High hostility | Wait / avoid |
| Extreme hostility | No-trade |

---

## 5. Gap and Opening Rules

### Opening Range Definition

```text
MVP Opening Range = 9:15 to 9:30 high/low.
No ORB trade before 9:30.
```

### Gap Rules

| Gap Size | Minimum Wait | Mode |
|---|---:|---|
| <0.25% | 15 min | Normal after confirmation |
| 0.25–0.50% | 15 min | Wait |
| 0.50–0.90% | 20–30 min | Defensive |
| 0.90–1.50% | 30–45 min | Defensive |
| >1.50% | 45–60 min | Survival |
| >2.00% | 60 min minimum | No-trade / survival |

### Gap Trade Rule

```text
Gap direction is not a trade signal.
Gap acceptance is the signal.
```

No gap-day trade unless:

- minimum wait completed,
- spread normalized,
- FastWBCI confirms,
- premium elasticity confirms,
- clear invalidation exists.

---

## 6. Entry Rules

## Call Entry Allowed Only If

```text
Data OK
+ Contract OK
+ Regime OK
+ Instrument DirectionScore / leadership score > +45
+ selected instrument futures above VWAP / OR accepted
+ call PremiumElasticity >=0.80
+ ExpectedMove/RequiredMove >=1.30
+ IVCrushRiskScore not high
+ MarketHostility OK
+ hard stop fits risk cap
```

## Put Entry Allowed Only If

```text
Data OK
+ Contract OK
+ Regime OK
+ Instrument DirectionScore / leadership score < -45
+ selected instrument futures below VWAP / OR accepted
+ put PremiumElasticity >=0.80
+ ExpectedMove/RequiredMove >=1.30
+ IVCrushRiskScore not high
+ MarketHostility OK
+ hard stop fits risk cap
```

## Entry Order Rule

```text
Use manual marketable-limit order only.
No pure market order for entry.
```

Entry limit:

```text
Buy limit <= ask + 1 tick
AND not worse than mid + 0.60 × spread
```

Max re-quotes:

```text
2 re-quotes within 20 seconds.
If not filled, skip or reassess.
```

---

## 7. Exit Rules

## Immediate Exit Conditions

Exit if any are true:

1. Hard stop hit.
2. Premium failure exit triggers.
3. Data/liquidity emergency.
4. Trade thesis invalidated.
5. Daily loss limit hit.
6. IVCrushRiskScore rises above 70 while trade not profitable.
7. Spread widens severely and exit liquidity is deteriorating.

## Premium Failure Exit

```text
If futures move >=50 points in favor
but delta-adjusted PremiumElasticity <0.50 for 2 valid windows:
    reduce or exit.
```

## Time Stops

| Trade State | Max Time |
|---|---:|
| Losing scalp | 3–5 min |
| Losing normal momentum trade | 5–12 min |
| Flat trade | 10–20 min |
| Normal max hold | 30 min |
| Extended max hold | 45 min |

MVP hard preference:

```text
Do not hold beyond 45 minutes.
```

Exceptional trend-day hold beyond 45 minutes requires manual review and all gates still valid.

## Partial Profit Logic

```text
At +1.5R, exit 50% if possible or trail aggressively.
For 1-lot MVP, choose either full exit or trail based on premium strength.
```

Because MVP uses 1 lot, partial exits may not be practical. Therefore:

```text
For 1-lot MVP, default: take full profit at planned target or trail after +1.5R.
```

---

## 8. No-Trade Rules

No trade when:

1. Data stale.
2. Spread too wide.
3. ContractQuality <60.
4. FastWBCI mixed.
5. PremiumElasticity weak.
6. ExpectedMove/RequiredMove fails.
7. IVCrushRiskScore >85.
8. Regime confidence <60.
9. Market in flat VWAP range.
10. Lunch session without trend.
11. Expiry pin dominates.
12. Event risk unresolved.
13. Gap rules not satisfied.
14. Daily/weekly/monthly risk limit hit.
15. Trader is emotional, fatigued, or chasing.

---

## 9. Emergency Protocol

If internet / DHAN API / WebSocket / broker platform fails while in position:

1. Do not add.
2. Attempt exit through most reliable available channel.
3. If API unavailable, use broker app/web manually.
4. If no execution channel works, stop all new decisions.
5. Record incident in journal.
6. Resume only after manual review and stable data.

If not in position:

```text
No-trade until system restored.
```

---

## 10. Journal Requirements

Every trade must be logged.

Required fields:

```text
trade_id,date,entry_time,exit_time,trade_type,regime,risk_mode,setup_grade,
BN_futures_entry,BN_futures_exit,option_symbol,security_id,strike,expiry,
entry_bid,entry_ask,entry_mid,entry_fill,
exit_bid,exit_ask,exit_mid,exit_fill,
spread_entry,spread_exit,slippage_entry,slippage_exit,
DirectionScore,TradeQualityScore,ContractQualityScore,FastWBCI,SlowWBCI,
PremiumElasticity,IVCrushRiskScore,MarketHostilityScore,
max_allowed_risk_rupees,planned_risk_rupees,required_stop_points,required_stop_rupees,
hard_stop_points,hard_stop_rupees,reason_entry,reason_exit,rule_violations,pnl_points,pnl_rupees,notes
```

Skipped trades should also be logged if they were valid candidates.

---

## 11. Daily Shutdown Rules

Stop trading for the day if:

1. Loss reaches ₹1,500.
2. Two cap-sized/full-risk losses occur.
3. Three total losses occur.
4. Any major rule violation occurs.
5. Data/API instability persists.
6. Emotional control is compromised.

---

## 12. MVP Build Priority

Code only the following first:

1. DHAN instrument master loader for BANKNIFTY, NIFTY, FINNIFTY, MIDCPNIFTY.
2. DataHealth monitor per instrument.
3. Selected contract monitor per candidate instrument.
4. ContractQuality filter per instrument.
5. PremiumElasticity filter per instrument.
6. Direction engine per instrument: FastWBCI for Bank Nifty; price/futures leadership proxies for Nifty/FinNifty/Midcap until dedicated engines are validated.
7. ExpectedMove / RequiredMove per instrument.
8. IVCrushRiskScore per instrument.
9. MarketHostility / NoTrade logic per instrument.
10. OpportunityScore ranking engine.
11. Global position/order lock.
12. Journal and incident logs.
13. Simple dashboard with opportunity ranking.

Do not code in MVP:

- AI,
- GEX gates,
- CVD/order-flow gates,
- all-bank option chains,
- auto-execution,
- 20/200-depth,
- social sentiment,
- event strategy modules.

---

## 13. Final MVP Doctrine

```text
The MVP does not exist to catch every Bank Nifty move.
It exists to stop us from buying bad options.
```

Trade only when the five gates agree.

If uncertain:

```text
No trade.
```

Cash is a position.

---

## 14. Phase 1 Completion Rules

The following rules complete the Phase 1 multi-instrument opportunity-selection upgrade.

### 14.1 Same System, Instrument-Specific Calibration

```text
Use the same survival gates for all instruments.
Do not use the same calibration blindly for all instruments.
```

Universal gates:

```text
DataHealth
ContractQuality
PremiumElasticity
ExpectedMove/RequiredMove
IVCrushRisk
MarketHostility
HardStopFit
NoTrade rules
```

Instrument-specific items:

```text
Direction model
Lot size
Tick size
Normal spread/depth
Expected move
Premium elasticity baseline
Expiry behavior
Gap behavior
```

### 14.2 Direction Model Rule

```text
BANKNIFTY uses FastWBCI.
NIFTY uses Nifty leadership proxy until Nifty weights are configured and validated.
FINNIFTY uses financial leadership proxy until FinNifty weights are configured and validated.
MIDCPNIFTY uses futures/price/regime proxy and extra liquidity penalties until validated.
```

### 14.3 Lot-Size Risk Rule

```text
Never use Bank Nifty lot size for all instruments.
Every candidate must use lot size from DHAN instrument master.
```

If the dynamic hard stop becomes too tight to be executable:

```text
Reject the trade.
```

### 14.4 Paper-Fill Rule

```text
Paper trades must use bid/ask simulated fills.
LTP fills are invalid for performance review.
```

### 14.5 Candidate Revalidation Rule

Before manual order entry:

```text
Revalidate DataHealth, spread, ContractQuality, PremiumElasticity,
ExpectedMove/RequiredMove, IVCrushRisk, MarketHostility,
OpportunityScore, global lock, and HardStopFit.
```

If top candidate fails:

```text
Do not trade rank #2 automatically.
Recalculate all candidates.
```

### 14.6 Dry-Run Rule

Before live Phase 1 trading:

```text
Minimum 20 trading days of multi-instrument data capture
Minimum 100 ranking cycles
Minimum 50 paper/simulated trade candidates
0 critical mapping errors in final 5 dry-run days
0 wrong lot-size calculations
0 wrong tick-size calculations
Emergency tests passed
Candidate revalidation passed
Paper-fill simulator active
```

If any critical dry-run rule fails:

```text
NO LIVE TRADING
```

### 14.7 Complex Feature Retention Rule

Do not delete potentially useful complex modules. Classify them correctly.

```text
Stock option chains = future enrichment / research
GEX = research / context
CVD / order flow = research until validated
20-depth = later liquidity research
AI = later summarizer/classifier after data exists
```

These cannot become Phase 1 production gates until validated.

---

## 15. Final Institutional Hardening Rules

### 15.1 Excellence Grades

```text
A+ = OpportunityScore >= 90 and all strong gates pass
A  = OpportunityScore >= 80 and all excellent gates pass
B  = 70-79; watch/paper only
C  = 60-69; no trade
Reject = <60 or any hard gate fail
```

Live Phase 1 trades only A or A+.

### 15.2 Portfolio-Level No Trade

No trade if:

```text
No candidate grade >= A
Best OpportunityScore < DynamicExcellentThreshold
PortfolioNoTradeScore > 70
Broad event/tail-risk veto active
Daily risk budget insufficient
Global position lock active
Global execution reliability invalid
3 or more instruments have invalid DataHealth
Top candidate fails revalidation
Top two candidates ambiguous after tie-break
```

### 15.3 Additional Required Scores

Every live candidate must calculate:

```text
OpportunityConfidenceScore
ConvexityQualityScore
ExecutionQualityScore
RegimeFitScore
PortfolioNoTradeScore
DynamicExcellentThreshold
```

Minimum live requirements:

```text
OpportunityConfidenceScore >= 70
ConvexityQualityScore >= 80
ExecutionQualityScore >= 80
RegimeFitScore >= 70
```

Midcap stricter:

```text
ExecutionQualityScore >= 85
RegimeFitScore >= 80 until validated
```

### 15.4 Rank Persistence

```text
Candidate must remain A or A+ for 2 consecutive ranking windows
OR be A+ with strong breakout/gap acceptance and all gates excellent.
```

If not persistent:

```text
WAIT_FOR_CONFIRMATION
```

### 15.5 Remaining Daily Risk Budget

```text
RemainingDailyLossBudget = MaxDailyLoss - RealizedLossToday
MaxAllowedRiskForNewTrade = min(NormalRiskCap, InstrumentRiskCap, 0.80 × RemainingDailyLossBudget)
```

If planned risk exceeds this:

```text
NO TRADE
```

### 15.6 Trade Scarcity Protection

```text
Do not lower standards because no trades occurred.
Do not trade B-grade setups due to boredom.
Do not increase size after missed winners.
```

If no trades occur for 5 sessions:

```text
Review skipped-candidate journal.
Do not change thresholds without sufficient sample.
```

### 15.7 Tie-Break Logic

If candidates are within 3 OpportunityScore points:

```text
1. Higher ExecutionQualityScore
2. Higher ConvexityQualityScore
3. Higher ContractQualityScore
4. Higher PremiumElasticity
5. Lower MarketHostilityScore
6. Lower IVCrushRiskScore
7. Higher OpportunityConfidenceScore
8. More validated instrument
```

If still ambiguous:

```text
NO TRADE
```
