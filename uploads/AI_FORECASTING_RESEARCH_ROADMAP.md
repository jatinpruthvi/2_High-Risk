# AI Forecasting Research Roadmap

**Purpose:** Add a verified-model AI research roadmap without giving AI production trading authority.

**Core doctrine:**

```text
AI can improve forecasts, uncertainty estimation, anomaly detection, and research.
AI cannot trigger trades, size trades, override hard gates, or place orders in MVP.
```

---

## 1. Final Decision

Add an AI Forecasting Research Layer to the long-term roadmap.

Do **not** add AI to MVP production trading logic.

```text
MVP = rule-based, deterministic, manual, survival-first.
AI = research / advisory / validation layer only.
```

---

## 2. Verified Models Only

Only verified models may enter the research roadmap.

Allowed research candidates:

```text
Moirai / Moirai-2
Kronos
TimeGPT
Chronos / Chronos-Bolt / Chronos-2
TimesFM
```

Unverified / uncertain model names must not enter architecture.

Rule:

```text
No model may be included unless a real paper, repository, official documentation,
or vendor documentation is verified.
```

---

## 3. Safe AI Use Cases

AI may be researched for:

```text
Regime probability forecasting
Forecast realized volatility range
Forecast uncertainty bands
Anomaly detection
Stress regime detection
No-trade probability estimation
VolEdge improvement
ExpectedValue input improvement
Edge decay detection
Post-trade attribution assistance
```

AI may not be used for MVP:

```text
Trade triggering
Position sizing
Strike selection as sole authority
Order placement
Auto-execution
Risk override
Replacing OpportunityScore
Replacing hard gates
Replacing human/manual confirmation
```

---

## 4. Research Architecture

Recommended long-term architecture:

```text
Layer 1: Deterministic Trading OS
  Survival gates
  DataHealth
  ContractQuality
  PremiumElasticity
  ExpectedValue
  VolEdge
  OpportunityScore
  NoTrade logic

Layer 2: AI Forecasting Research Layer
  Moirai / TimeGPT / Kronos / Chronos / TimesFM
  Forecasts regime, realized volatility, uncertainty, anomalies

Layer 3: Model Governance Layer
  Walk-forward validation
  Drift monitoring
  Net P&L impact after costs
  Regime-specific performance

Layer 4: Hard Risk Engine
  Deterministic
  Non-AI
  Always dominant
```

---

## 5. Model Role Classification

| Model | Research Role | Production Authority |
|---|---|---|
| Moirai / Moirai-2 | Multivariate regime / volatility forecasting | None in MVP |
| Kronos | Financial OHLCV / K-line pattern research | None in MVP |
| TimeGPT | Probabilistic forecasts / uncertainty bands | None in MVP |
| Chronos | General time-series forecasting benchmark | None in MVP |
| TimesFM | General time-series forecasting benchmark | None in MVP |

---

## 6. Evaluation Standard

A model is useful only if it improves at least one of:

```text
ExpectedValue accuracy
VolEdge accuracy
Regime classification
No-trade detection
Drawdown reduction
Premium failure avoidance
IV crush avoidance
Opportunity ranking quality
```

It is not useful merely because forecast error is lower.

Trading evaluation must be based on:

```text
net P&L after costs
drawdown
profit factor
false trade reduction
missed winner rate
no-trade quality
regime-specific performance
```

---

## 7. Promotion Path

AI model promotion stages:

```text
Research-only
→ Offline replay evaluation
→ Shadow mode alongside rule engine
→ Advisory score with no authority
→ Risk-filter contribution only after validation
```

No AI model can become a production trade trigger in the current roadmap.

---

## 8. Hard Vetoes

AI cannot override:

```text
Survival Gate
DataHealth invalid
ContractQuality failure
PremiumElasticity failure
ExpectedMove/RequiredMove failure
IVCrushRisk hard veto
HardStopFit failure
MarketHostility no-trade
PortfolioNoTrade no-trade
Daily/weekly/monthly risk limits
Global position lock
```

---

## 9. Rejected For MVP

The following are rejected for MVP production:

```text
Reinforcement learning trade construction
Neural-SDE / PINN production vol surface model
LOB transformer execution model
AI strike selector
AI position sizing
AI auto-execution
AI dealer/GEX authority
```

These may remain future research topics only after clean replay data and stable MVP performance exist.

---

## 10. Final Roadmap Placement

AI Forecasting Research Layer should begin only after:

```text
Phase 1 dry-run data exists
Paper-fill simulator is active
Journal/replay storage is reliable
At least 100 ranking cycles exist
At least 50 simulated candidates exist
Core EV / VolEdge / ConvexityEdge engines are implemented
```

---

## 11. Final Doctrine

```text
The model is not the edge.
The trading process is the edge.
```

AI may improve the process only if it improves:

```text
better no-trade decisions
better volatility forecasts
better regime detection
better EV estimates
lower drawdown
higher net risk-adjusted ROI
```

Final rule:

```text
AI supports the system.
AI does not run the system.
```
