# DHAN-v2 High-Risk Paper Profile

This folder is an isolated high-risk paper-only experiment derived from the conservative DHAN-v2 project. It does not change the conservative project.

## Gate-breakout selector

The selector records each instrument's current **validated threshold margin** (`comparable_opportunity_score - dynamic_excellent_threshold`) and compares it with that instrument's prior maximum inside a rolling 30-minute window. The current observation is compared before it is appended, preventing look-ahead. A first observation is warm-up only and cannot trigger an entry.

When several instruments break out simultaneously, the selector chooses the highest-quality eligible evaluation using comparable opportunity score, execution quality, convexity, contract quality, premium elasticity, lower market hostility, lower IV-crush risk, and opportunity confidence as deterministic tie-break fields.

The breakout condition is not a replacement for hard controls. Current eligibility, valid data health, valid contract quality, validated cost model, revalidation, paper fill, one open position, one lot, no leverage or pledge, and end-of-day closure remain mandatory. Dynamic lot sizing, two simultaneous positions, optimistic midpoint fills, overnight holding, and live execution remain disabled.

The rolling history is stored in `paper_state/gate_breakout_history.json`; the dashboard publishes `_gate_breakout` metadata and experimental breakout candidates remain clearly attributable to this high-risk profile.
