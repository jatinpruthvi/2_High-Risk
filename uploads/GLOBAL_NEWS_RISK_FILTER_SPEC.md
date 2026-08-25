# Global Sentiment and News Risk Filter Specification

**Purpose:** Add global market sentiment and live/news-event awareness as survivability and no-trade filters, not as entry signals.

**Core rule:**

```text
Global/news sentiment can downgrade trades.
It can slightly support directional bias.
It cannot independently trigger trades.
```

---

## 1. Role in the System

Global market and news information belongs in:

```text
MarketHostilityScore
PortfolioNoTradeScore
EventGapRisk
Gap / Opening Auction Gate
IVCrushRisk
DirectionScore penalty/boost
```

It does **not** belong as a standalone trade trigger.

Hard rule:

```text
No global/news signal can override DataHealth, ContractQuality, PremiumElasticity,
ExpectedMove/RequiredMove, IVCrushRisk, HardStopFit, or Candidate Revalidation.
```

---

## 2. GlobalRiskBias States

```text
Risk-On
Neutral
Risk-Off
Shock
```

### Interpretation

| State | Meaning | System Action |
|---|---|---|
| Risk-On | Global cues supportive | Mild support to calls, but still require full confirmation |
| Neutral | No strong global pressure | No major adjustment |
| Risk-Off | Global cues bearish/stressed | Downgrade calls, allow put bias only after Indian confirmation |
| Shock | Global panic / major news shock | Survival / No-Trade until Indian market stabilizes |

---

## 3. Global Inputs

Track as context/risk inputs:

```text
US futures: S&P 500 / Nasdaq / Dow
Europe: FTSE / DAX / STOXX or London gap direction
GIFT Nifty
US VIX / global VIX proxy
USDINR
US 10Y yield
India 10Y yield
Crude oil
Gold
Major global banking / geopolitical headlines
```

These inputs may be manual initially and automated later.

---

## 4. Global Risk Scoring

### GlobalRiskScore Formula

```text
GlobalRiskScore =
  0.25 × USIndexFuturesRisk
+ 0.20 × GiftNiftyGapRisk
+ 0.15 × EuropeMarketRisk
+ 0.15 × VIXRisk
+ 0.10 × CurrencyRisk
+ 0.10 × YieldRisk
+ 0.05 × CrudeGoldRisk
```

Score range:

```text
0 = no global risk
100 = extreme global shock
```

### State Mapping

| GlobalRiskScore | State |
|---:|---|
| 0–25 | Risk-On / Neutral |
| 25–45 | Caution |
| 45–65 | Risk-Off |
| >65 | Shock |

---

## 5. Directional Impact Rules

### If GlobalRiskBias = Risk-Off

For call candidates:

```text
DirectionScore penalty = -10 to -20
MarketHostilityScore += 10 to 25
Require A+ quality if Indian market is not clearly accepting upside
```

For put candidates:

```text
DirectionScore support = +5 to +10
```

But:

```text
No put trade is allowed unless Indian futures, price acceptance, premium elasticity,
contract quality, and expected/required move confirm.
```

### If GlobalRiskBias = Shock

```text
No new trades until Indian market opens, stabilizes, spreads normalize,
and price acceptance is visible.
```

Shock state can activate:

```text
Survival Mode
No-Trade Mode
Opening Auction extended wait
```

### If GlobalRiskBias = Risk-On

For call candidates:

```text
DirectionScore support = +5 max
```

For put candidates:

```text
DirectionScore penalty = -5 to -10 if Indian market also confirms risk-on
```

Risk-on does not bypass premium/contract gates.

---

## 6. Gap and Opening Interaction

If global cues imply gap risk:

```text
GIFT Nifty gap >0.50% = caution
GIFT Nifty gap >1.00% = extended opening wait
GIFT Nifty gap >2.00% = survival/no-trade initially
```

Global gap direction is not a trade signal.

```text
Gap direction is information.
Gap acceptance is confirmation.
```

---

## 7. NewsRiskFilter

### Purpose

Live or RSS news can improve survivability by detecting events that invalidate normal market assumptions.

News is a risk filter, not an entry engine.

### Inputs

Potential sources:

```text
RSS feeds
RBI announcements
NSE / SEBI circulars
broker alerts
major financial news
banking-sector news
global macro headlines
geopolitical headlines
economic calendar
```

### News Risk States

```text
Normal
Caution
Defensive
Survival
No-Trade
```

### NewsRiskScore Formula

```text
NewsRiskScore =
  0.30 × EventSeverity
+ 0.20 × InstrumentRelevance
+ 0.20 × SourceReliability
+ 0.15 × MarketReactionConfirmed
+ 0.15 × TimingProximity
```

Important: `MarketReactionConfirmed` is used as risk validation, not entry validation.

---

## 8. News Categories and Treatment

| News Type | Treatment |
|---|---|
| RBI policy / surprise circular | Defensive / Survival / No-Trade until accepted repricing |
| Fed decision / US macro shock | Pre-market risk penalty; wait for Indian acceptance |
| Banking-sector crisis news | Bank Nifty / FinNifty hostility penalty |
| SEBI / NSE rule change | No-trade until rule impact understood |
| Broker outage / API issue | Data/Execution invalid; no-trade |
| Geopolitical shock | Survival / No-trade depending severity |
| Budget / election headlines | Event-risk mode; no early trade |
| Company earnings | Relevant only for constituent leadership context, not direct index entry |
| Rumor / unverified headline | Do not trade; wait for price/vol confirmation |

---

## 9. RSS Feed Implementation Rule

RSS can be added as a monitoring layer.

First version should be:

```text
Keyword scanner
Source whitelist
Duplicate headline filter
Severity tagger
Manual confirmation flag
```

RSS must not place or approve trades.

### RSS Output

```text
NEWS_NORMAL
NEWS_CAUTION
NEWS_DEFENSIVE
NEWS_SURVIVAL
NEWS_NO_TRADE
```

### Example Keywords

```text
RBI
SEBI
NSE
Banking crisis
Fed
CPI
Inflation
War
Geopolitical
Cyberattack
Exchange outage
Broker outage
HDFC Bank
ICICI Bank
SBI
USDINR
Bond yield
Crude spike
```

---

## 10. Integration Into Scores

### MarketHostilityScore

Add:

```text
MarketHostilityScore += GlobalRiskPenalty + NewsRiskPenalty
```

Suggested penalties:

| Condition | Penalty |
|---|---:|
| Global caution | +5 to +10 |
| Global risk-off | +10 to +25 |
| Global shock | hard survival/no-trade |
| News caution | +5 to +10 |
| News defensive | +15 to +25 |
| News survival | +35 to +50 |
| News no-trade | hard no-trade |

### PortfolioNoTradeScore

Add:

```text
PortfolioNoTradeScore += SystemicNewsRisk + GlobalShockRisk
```

### DirectionScore

Only small adjustment allowed:

```text
Risk-off: call penalty, put support only if Indian market confirms
Risk-on: call support, put penalty only if Indian market confirms
```

Maximum directional adjustment:

```text
±10 normally
±20 during strong global risk-off for call penalty only
```

---

## 11. Hard Veto Rules

No trade if:

```text
GlobalRiskBias = Shock and Indian market not stabilized
NewsRiskState = No-Trade
Broker/exchange/API outage headline confirmed
Major RBI/SEBI/NSE surprise not yet digested
Unverified major news causing abnormal spreads
```

---

## 12. Final Doctrine

```text
Global sentiment and news are survivability tools.
They help avoid bad trades.
They do not create trades.
```

Final rule:

```text
A global/news filter may block or downgrade a trade.
It may not approve one.
```
