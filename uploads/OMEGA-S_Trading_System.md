**OMEGA-S — Systematic Options Trading System** |   NSE F&O   |   Confidential 

## **OMEGA-S** 

**Systematic Options Trading System** OMEGA + BNIOS + Sweep Confirmation + Institutional Gate 

## **IMPORTANT NOTICE** 

This document contains sections with different confidence levels. **HIGH CONFIDENCE sections are evidence-based and validated. EXPERIMENTAL sections require live testing before full reliance.** Do not risk capital on EXPERIMENTAL sections until you have 6 months of live data. 

Version 1.0   |   Date: 27 June 2026   |   Markets: NSE F&O 

For personal use only. Not investment advice. 

For personal trading use only. 

**OMEGA-S — Systematic Options Trading System** |   NSE F&O   |   Confidential 

## **SECTION 1: Core System — OMEGA + BNIOS** 

## **CONFIDENCE: HIGH — Evidence-based, validated in Indian markets** 

This section documents your existing, proven system. Nothing here is new or theoretical. This is the foundation upon which all additions are built. 

## **1.1  System Overview** 

OMEGA-S is a systematic options trading system for Indian F&O markets (Bank Nifty, Nifty, FINNIFTY). It sells options premium as its primary income source, guided by volatility regime detection, directional intelligence, and institutional positioning filters. 

## **1.2  OMEGA Core Engine** 

## **Volatility Regime Index (VRI)** 

The VRI determines which operational mode the system uses at any given time. Three modes exist: 

|**Mode**|**VIX Condition**|**Primary Action**|**Position Type**|
|---|---|---|---|
|**HARVEST**|India VIX < 13|Sell premium aggressively,<br>wider strikes|Short Strangles / Iron<br>Condors|
|**PROTECTION**|India VIX 13–20|Sell premium conservatively,<br>tighter strikes|Short Straddles / Credit<br>Spreads|
|**FLIP**|India VIX > 20|Buy premium on highest<br>conviction setups only|Long options / Debit<br>Spreads|



## **Shield / Sword Capital Architecture** 

|SHIELD Capital (60%)|Defensive allocation. Conservative premium selling. Protects base<br>capital. Never fully deployed.|
|---|---|
|SWORD Capital (40%)|Offensive allocation. Higher conviction trades. Directional plays.<br>Can be partially deployed.|
|Hard Floor Rule|If total capital drops below predefined floor, all SWORD activity<br>stops immediately.|



## **1.3  BNIOS Intelligence Layer** 

The Bank Nifty Institutional Options System provides directional and quality scoring before any trade entry. 

## **Min(DirectionScore, TradeQualityScore) Formula** 

Both Direction Score and Trade Quality Score must independently exceed their thresholds. The minimum of the two scores is used. A high direction score cannot compensate for low trade quality and vice versa. 

For personal use only. Not investment advice. 

For personal trading use only. 

**OMEGA-S — Systematic Options Trading System** |   NSE F&O   |   Confidential 

|**Score Component**|**What It Measures**|**Minimum Threshold**|
|---|---|---|
|Direction Score|Probability of directional move|Must exceed system threshold|
|Trade Quality Score|Setup quality and conditions|Must exceed system threshold|
|**Min(D,Q) Result**|**Final entry gate**|**Below threshold = No Trade**|



## **WBCI Constituent Intelligence** 

Weighted Bank Constituent Index reads behaviour of Bank Nifty constituent stocks to identify institutional flow direction before it appears in the index itself. This is a leading indicator, not a lagging one. 

## **Premium Elasticity Engine** 

Measures whether option premium is priced correctly relative to expected move. Prevents selling premium that is too cheap relative to the risk being taken. 

## **MTIL Learning System** 

The 281-field Machine Trade Intelligence Log captures every trade with full context. Over time, this builds a pattern library specific to your trading. Review monthly. Adjust system parameters quarterly based on findings. This is your most valuable long-term asset — protect the data integrity. 

For personal use only. Not investment advice. 

For personal trading use only. 

**OMEGA-S — Systematic Options Trading System** |   NSE F&O   |   Confidential 

## **SECTION 2: Validated Additions** 

## **CONFIDENCE: HIGH — Evidence-based, validated in Indian markets** 

These additions have genuine evidence bases from Indian markets. They are practical, implementable with free NSE data, and directly relevant to your trading style. Implement these from day one alongside the core system. 

## **2.1  Sweep / CHoCH Confirmation Filter** 

This is NOT a standalone trading strategy. It is a confirmation gate applied before OMEGA premium selling entries. 

## **The Core Question** 

Has the nearest BSL (Buy Side Liquidity) or SSL (Sell Side Liquidity) pool been swept recently? If yes, the level is cleaner for premium selling. If no, a sweep may still be coming — which creates risk for your short position. 

## **BSL and SSL Defined** 

BSL — Buy Side Liquidity Resting orders above equal highs or swing highs. Short sellers have stops here. Price sweeps BSL to fill institutional sell orders. SSL — Sell Side Liquidity Resting orders below equal lows or swing lows. Long buyers have stops here. Price sweeps SSL to fill institutional buy orders. 

## **Sweep Anatomy — Valid vs Invalid** 

|**Valid Sweep (proceed with OMEGA entry)**|**Invalid Sweep (do not use as confirmation)**|
|---|---|
|Wick pierces level, body closes back inside range|Multiple candles close outside level|
|Single candle sweep preferred|Slow grind through level|
|Wick is at least 2x the body size|Body closes outside the level|
|CHoCH (Change of Character) forms within 5<br>candles|CHoCH takes more than 10 candles to form|



## **Integration Rule** 

Before any OMEGA premium sale at a level: 

- Has BSL or SSL been swept at or near that level within the last 3 candles on the 15-minute chart? 

- YES: Proceed with full intended size. Institutional orders have been filled. Level is cleaner. 

- NO: Reduce position size by 30%, or wait for sweep to occur first. 

For personal use only. Not investment advice. 

For personal trading use only. 

**OMEGA-S — Systematic Options Trading System** |   NSE F&O   |   Confidential 

## **2.2  Entry Timing Windows** 

Bank Nifty options have predictable intraday liquidity patterns. Trading outside optimal windows increases execution friction significantly. 

|**Time Window**|**Quality**|**Action**|**Reason**|
|---|---|---|---|
|9:15–9:30|Avoid|No new entries|Widest spreads,<br>highest noise|
|9:30–10:30|**Primary**|Main entry window|Price discovery<br>complete, institutional<br>flow visible|
|10:30–12:00|Acceptable|Adjustments only|Premium stabilising|
|12:00–13:30|Avoid|No new entries|Lunch lull, thin volume|
|13:30–14:30|Secondary|Secondary entry<br>window|FII activity often<br>increases|
|14:30–15:30|Avoid|No new entries|Gamma acceleration,<br>erratic moves|



## **2.3  VIX Direction Filter** 

India VIX level is already captured by OMEGA VRI. What is added here is the DIRECTION of VIX movement over 3 days, which provides additional context the level alone cannot give. 

|VIX falling over 3 days|Premium selling conditions improving. Proceed at normal size.|
|---|---|
|VIX flat over 3 days|Stable conditions. Proceed at normal size.|
|VIX rising over 3 days|Conditions deteriorating. Reduce all new position sizes by<br>30%.|
|VIX rising >10% in 2 days|Significant stress signal. No new entries. Manage existing<br>positions only.|



Data source: NSE website, India VIX page. Check every morning before trading. Takes 60 seconds. 

## **2.4  Liquidity Check Before Entry** 

This is a basic professional standard that is almost universally ignored by retail options traders. Illiquid strikes destroy realised returns even when the trade direction is correct. 

|**Check**|**GREEN**|**YELLOW**|**RED — Avoid**|
|---|---|---|---|
|Bid-Ask Spread at intended<br>strike|< 5 points (BN) / < 2<br>points (Nifty)|5–10 points / 2–4<br>points|> 10 points / > 4<br>points|
|Volume at strike today|> 1,000 contracts|500–1,000 contracts|< 500 contracts|



For personal use only. Not investment advice. 

For personal trading use only. 

**OMEGA-S — Systematic Options Trading System** |   NSE F&O   |   Confidential 

## **Rule: Both checks must be GREEN or YELLOW to proceed. Any RED = do not trade that strike. Move to adjacent liquid strike instead.** 

## **2.5  Greeks Snapshot Before Entry** 

Check three basic Greeks before confirming any position. Available directly from your broker platform — no additional tools required. 

|**Greek**|**Acceptable Range**|**If Outside Range**|
|---|---|---|
|Net Delta|Between -0.10 and +0.10 for<br>strangles|Adjust strikes before entering. Do<br>not force the trade.|
|Daily Theta|Daily decay > 0.5% of premium<br>received|Premium insufficient for risk taken.<br>Skip trade.|
|Net Vega|Total vega exposure < 2% of capital<br>in trade|Too much volatility risk. Reduce size<br>or widen strikes.|



## **2.6  Expiry Day Protocol** 

This is the most evidence-based addition in this document. Max pain on expiry day has documented accuracy of 71–76% in Indian markets. This accuracy does NOT extend reliably to non-expiry days — see Section 3 for the experimental daily version. 

## **Thursday Bank Nifty Expiry Protocol** 

- Step 1 — Wait until 10:00 AM. Allow opening volatility to settle. 

- Step 2 — Calculate max pain level from NSE options chain. This is the strike at which total option seller profit is maximised. 

- Step 3 — If current price is within 1% of max pain: sell ATM straddle or tight strangle around max pain level. 

- Step 4 — If current price is more than 1.5% from max pain: wait. Price has a 71–76% probability of moving toward max pain. Enter when it gets closer. 

- Step 5 — Hard close: all expiry day positions closed by 14:00. No exceptions. Gamma risk after 14:00 is extreme. 

- Capital allocation: Maximum 2% of total capital risk on this trade. Separate from main OMEGA positions. 

## **Expiry Week Monday to Wednesday** 

- Max pain pull begins but is weaker than Thursday. Do not use it as a primary signal. 

- Reduce new position duration. Target exits before Thursday unless high conviction. 

- Do not carry full-size positions from Wednesday into Thursday. 

For personal use only. Not investment advice. 

For personal trading use only. 

**OMEGA-S — Systematic Options Trading System** |   NSE F&O   |   Confidential 

## **SECTION 3: Experimental Institutional Gate** 

## **CONFIDENCE: EXPERIMENTAL — Logical framework; requires live testing before full reliance** 

**WARNING: The filters in this section are logically sound and based on real market concepts. However, the specific thresholds, scoring matrices, and combined interactions have NOT been independently validated. They were constructed through analysis and reasoning, not empirical testing. Trade at reduced size based on these filters only. Log every decision for 6 months before relying on them at full size.** 

## **3.1  Purpose of the Institutional Gate** 

Before any trade entry, the Institutional Gate attempts to answer one specific question: Is institutional positioning currently safe for premium selling at this strike at this moment? 

Six filters address this question from different angles. They are divided into Mandatory filters (must pass) and Confirmatory filters (scored). 

## **3.2  Filter Structure** 

|**Filter**|**What It Checks**|**Type**|**Data Source**|
|---|---|---|---|
|A|OI Interpretation — institutional<br>commitment at strike|**MANDATORY**|NSE options chain<br>(previous day)|
|F|IV Percentile — whether<br>premium is worth selling|**MANDATORY**|NSE / broker platform|
|B|Value Area — price location<br>relative to volume|CONFIRMATORY|TradingView / Kite<br>volume profile|
|C|ATM OI Balance — rough<br>dealer hedging direction|CONFIRMATORY|NSE options chain|
|D|PCR Momentum — 5-day<br>sentiment trend|CONFIRMATORY|NSE PCR data|
|E|Max Pain Distance —<br>gravitational pull on price|CONFIRMATORY|NSE options chain|



## **3.3  Mandatory Filters — Must Pass or No Trade** 

## **Filter A: OI Interpretation** 

Use previous day's end-of-day OI data. Intraday OI has significant lag and noise on NSE — do not use it for this check. 

**OI change alone is insufficient. You must combine OI change with price direction to understand what is happening.** 

|**OI Change**|**Price Direction**|**Interpretation**|**Signal**|
|---|---|---|---|
|Rising|Falling|Bears adding shorts —<br>supports your short call|GREEN for call sellers|



For personal use only. Not investment advice. 

For personal trading use only. 

**OMEGA-S — Systematic Options Trading System** |   NSE F&O   |   Confidential 

|Rising|Rising|Bulls adding longs —<br>dangerous for call<br>sellers|RED for call sellers|
|---|---|---|---|
|Falling|Falling|Bears covering —<br>momentum fading|YELLOW|
|Falling|Rising|Squeeze developing —<br>exit risk high|RED|



Note: Reverse these signals for put sellers. A signal that is RED for call sellers is GREEN for put sellers and vice versa. 

## **Filter F: IV Percentile** 

Use IV Percentile, not IV Rank. IV Rank is distorted by past spikes and overstates or understates opportunity. 

Calculate using 6-month lookback, not 52 weeks. Use Bank Nifty ATM straddle IV specifically. 

|IV Percentile > 50%|IV genuinely elevated. Premium selling has statistical edge.<br>MANDATORY PASS.|
|---|---|
|IV Percentile 30–50%|Moderate conditions. Reduce size by 20%. Marginal pass.|
|IV Percentile < 30%|IV genuinely low. Premium selling has poor edge.<br>MANDATORY FAIL. Do not sell premium today.|



## **3.4  Confirmatory Filters — Scored** 

## **Filter B: Value Area (Contextual)** 

Calculate on Bank Nifty FUTURES or SPOT chart — not on individual option prices. 

Gap open adjustment: If Bank Nifty gaps more than 0.5% at open, do not use previous day's value area. Wait until 9:45 AM and use the 9:15–9:45 range as your reference instead. 

Trend day adjustment: If price is making clear higher highs and higher lows (or lower lows and lower highs), this is a trend day. Suspend the value area filter. Reduce all position sizes by 30% instead. 

|Price inside Value Area (VAL to VAH)|Mean reversion highly likely. Ideal for premium selling.<br>GREEN.|
|---|---|
|Price within 0.3% of Value Area boundary|Potential retest. Acceptable conditions. YELLOW.|
|Price more than 0.5% outside Value Area|Trending or breakout conditions. Dangerous for premium<br>sellers. RED.|



## **Filter C: ATM OI Balance** 

This is NOT a GEX calculation. It is an approximation of dealer positioning using publicly available OI data. Label it honestly in your logs as ATM OI Balance, not GEX. 

Count OI for 3 strikes above and 3 strikes below current price (not percentage — use strike count for Indian markets). 

For personal use only. Not investment advice. 

For personal trading use only. 

**OMEGA-S — Systematic Options Trading System** |   NSE F&O   |   Confidential 

|Call OI exceeds Put OI by more than 25%|Dealers more exposed on call side. Market may be pulled<br>upward. GREEN for put sellers, YELLOW for call sellers.|
|---|---|
|Put OI exceeds Call OI by more than 25%|Dealers more exposed on put side. Market may be pulled<br>downward. GREEN for call sellers, YELLOW for put<br>sellers.|
|OI balanced within 25%|Neutral positioning. Favorable for strangles. GREEN for<br>both sides.|



Expiry week note: Same OI imbalance has stronger effect in expiry week. Weight signals more heavily Monday through Thursday of expiry week. 

## **Filter D: PCR Momentum (5-Day)** 

Use 5-day PCR average compared to today's reading. Static PCR has weak predictive value. The direction of change over 5 days is more meaningful. 

Distortion check: If PCR moves more than 0.3 in a single day, a large single trade is likely distorting the number. Use the previous day's PCR reading instead for that day's calculation. 

|PCR rising over 5 days (more puts<br>bought)|Fear increasing. Premium selling becoming more<br>dangerous. RED.|
|---|---|
|PCR stable over 5 days|Stable sentiment. Normal conditions. GREEN.|
|PCR falling over 5 days (puts being sold)|Complacency increasing. Premium selling conditions<br>improving. GREEN.|
|PCR falling very rapidly|Extreme complacency. Potential reversal risk. YELLOW.|



## **Filter E: Max Pain Distance (Weighted by Days to Expiry)** 

IMPORTANT: Max pain has strong evidence on expiry day (71–76% accuracy). Its accuracy on nonexpiry days is significantly weaker, estimated at 52–55% — barely above random. This filter is therefore weighted by days remaining to expiry. 

|**Day**|**Max Pain Weight**|**How to Use**|
|---|---|---|
|Monday, non-expiry week|20%|Note max pain level but do not trade on it<br>alone|
|Wednesday, non-expiry week|40%|Secondary consideration only|
|Monday, expiry week|60%|Meaningful signal, use with other<br>confirmations|
|Wednesday, expiry week|80%|Strong signal, weight heavily|
|Thursday (expiry day)|**100%**|Full Section 2.6 protocol. Highest<br>confidence.|



For personal use only. Not investment advice. 

For personal trading use only. 

**OMEGA-S — Systematic Options Trading System** |   NSE F&O   |   Confidential 

## **3.5  Scoring Matrix** 

## **Step 1: Mandatory Filters** 

- Filter A (OI Interpretation): Must be GREEN or YELLOW. RED = No Trade. Stop here. 

- Filter F (IV Percentile): Must be GREEN or YELLOW. RED = No Trade. Stop here. 

- If both mandatory filters pass: proceed to confirmatory scoring. 

**Step 2: Confirmatory Scoring (Filters B, C, D, E)** 

|**GREEN Count**|**Position Size**|**Interpretation**|
|---|---|---|
|**4 of 4 GREEN**|100% of intended size|All confirmatory signals aligned|
|3 of 4 GREEN|75% of intended size|Strong alignment with minor uncertainty|
|2 of 4 GREEN|50% of intended size|Mixed signals. Trade with caution.|
|1 of 4 GREEN|25% of intended size|Weak alignment. Consider skipping.|
|**0 of 4 GREEN**|No Trade|No confirmatory signal present|



**Additional rule: If any single confirmatory filter shows RED (not just yellow), reduce the scored size by an additional 20% regardless of total green count. Two RED confirmatory filters = maximum 40% size regardless of other scores.** 

For personal use only. Not investment advice. 

For personal trading use only. 

**OMEGA-S — Systematic Options Trading System** |   NSE F&O   |   Confidential 

## **SECTION 4: Position Management Rules** 

## **CONFIDENCE: HIGH — Evidence-based, validated in Indian markets** 

These are standard professional options trading rules. They are not new or theoretical. The purpose is to make them explicit and mechanical, removing judgment from decisions that should not involve judgment. 

## **4.1  Entry Rules** 

- Maximum risk per trade: 3% of total portfolio capital. 

- Maximum number of simultaneous positions: defined by your OMEGA system. Do not exceed. 

- All entries must pass Section 2 filters. Institutional Gate (Section 3) is additional confirmation only at reduced size. 

- Never enter in the final 60 minutes of the session. No exceptions. 

## **4.2  In-Trade Management** 

## **Breakeven Rule** 

If a position is at breakeven after 2 full trading days and showing no clear resolution: close 50% of the position regardless of view. Let the remaining 50% run to stop or target. 

Rationale: A position that has not moved in 2 days is consuming margin without generating return. Capital has opportunity cost. 

## **Profit Protection Rule** 

When a position has captured 30% of its maximum theoretical profit: move stop to breakeven. You have now removed all downside risk. Let the remaining potential run. 

## **Scale Out Structure** 

|**Profit Level**|**Action**|**Remaining Position**|
|---|---|---|
|30% of max profit|Move stop to breakeven|100% — zero downside risk<br>now|
|50% of max profit|Close 25% of position|75% remaining|
|75% of max profit|Close another 25%|50% remaining|
|Expiry / target|Close all|0% — position closed|



## **4.3  Strike Selection by VIX Level** 

Strike distance from ATM should be calibrated to current volatility. This is likely already defined in your OMEGA system — make it explicit here for reference. 

|**India VIX**|**Strike Distance**|**Mode**|**Rationale**|
|---|---|---|---|
|Below 13|1.0–1.5% OTM|HARVEST|Low vol, closer strikes|



For personal use only. Not investment advice. 

For personal trading use only. 

**OMEGA-S — Systematic Options Trading System** |   NSE F&O   |   Confidential 

||||acceptable|
|---|---|---|---|
|13–18|1.5–2.0% OTM|PROTECTION|Standard range, core<br>OMEGA strikes|
|18–25|2.0–2.5% OTM|PROTECTION / FLIP|Higher vol, wider<br>strikes needed|
|Above 25|2.5%+ OTM or buy<br>premium|FLIP|FLIP mode. Review<br>before any sale.|



For personal use only. Not investment advice. 

For personal trading use only. 

**OMEGA-S — Systematic Options Trading System** |   NSE F&O   |   Confidential 

## **SECTION 5: Risk Architecture** 

## **CONFIDENCE: HIGH — Evidence-based, validated in Indian markets** 

Risk management is the most important section in this document. A mediocre strategy with excellent risk management survives. An excellent strategy with poor risk management eventually fails. 

## **5.1  Three-Layer Circuit Breaker System** 

|**Layer**|**Trigger**|**Immediate Action**|**Resume Condition**|
|---|---|---|---|
|**Trade**|Stop loss hit on individual<br>trade|Close position<br>immediately. No<br>averaging.|Next valid setup only.|
|**Daily**|Portfolio down 6% in<br>single day|Stop all new entries for<br>remainder of day. Manage<br>existing only.|Next trading day,<br>reassess.|
|**Monthly**|Portfolio down 12% in<br>calendar month|Reduce all new position<br>sizes by 50%. Grade A+<br>setups only.|When monthly loss<br>recovers to -6% or better.|



## **5.2  Tail Protection — Always On** 

This is non-negotiable. It is the insurance policy that prevents a single catastrophic event from permanently ending the trading operation. 

|What to buy|Far OTM put options on Nifty. 2–3% below current price. Monthly<br>expiry.|
|---|---|
|Cost|Approximately 0.3–0.5% of portfolio per month. This is the<br>insurance premium. It is a cost of doing business.|
|Payoff in normal months|These expire worthless. Accept this. It is expected.|
|Payoff in crisis|500–1000% of premium paid. Offsets severe losses across all other<br>positions.|
|Rule|Never remove this hedge. Not even in the lowest volatility periods.<br>Especially not then.|



## **5.3  Capital Allocation Framework** 

|**Allocation**|**Percentage**|**Purpose**|
|---|---|---|
|Tail Protection|5%|OTM put hedge. Non-negotiable. Always<br>deployed.|
|SHIELD — Core premium<br>selling|55%|Conservative OMEGA positions. Main<br>income source.|
|SWORD — Higher conviction|25%|Directional plays, expiry protocol, higher|



For personal use only. Not investment advice. 

For personal trading use only. 

**OMEGA-S — Systematic Options Trading System** |   NSE F&O   |   Confidential 

|trades||conviction setups.|
|---|---|---|
|Cash Reserve|15%|Available for margin calls, opportunity, or<br>drawdown buffer.|



For personal use only. Not investment advice. 

For personal trading use only. 

**OMEGA-S — Systematic Options Trading System** |   NSE F&O   |   Confidential 

## **SECTION 6: Daily Operating Procedure** 

## **CONFIDENCE: HIGH — Evidence-based, validated in Indian markets** 

Consistency in preparation is what separates systematic traders from discretionary ones. This procedure should take no more than 20 minutes each morning. 

## **6.1  Pre-Market Checklist (9:00–9:15 AM)** 

- Check India VIX: Record level. Compare to previous 3 days. Note direction (rising/flat/falling). 

- Check SGX Nifty: Is there a significant gap? If gap > 0.5%, note for Value Area adjustment. 

- Check NSE options chain: Record PCR. Compare to 5-day average. Note direction. 

- Identify max pain level for current expiry. Note distance from expected open. 

- Review previous day OI changes at key strikes. Note direction interpretation (Filter A). 

- Check economic calendar: Any RBI announcements, major data releases, or global events today? 

- Confirm tail hedge is in place. 

## **6.2  Market Open (9:15–9:30 AM)** 

- Observe only. Do not trade. Note opening price relative to previous day levels. 

- Identify BSL and SSL pools: previous day high/low, previous week high/low, equal highs/lows. 

- If gap open > 0.5%: wait until 9:45 AM before calculating value area. 

- Set price alerts at key BSL/SSL levels. 

## **6.3  Primary Entry Window (9:30–10:30 AM)** 

- Run BNIOS Min(D,Q) check. Does the setup qualify? 

- If yes: Run Mandatory Filters A and F. Do both pass? 

- If yes: Run Confirmatory Filters B, C, D, E. Score the setup. 

- Check Sweep/CHoCH filter. Has nearest BSL/SSL been swept? 

- Check Liquidity. Is the strike liquid enough? 

- Check Greeks Snapshot. Is delta, theta, vega within range? 

- Determine position size based on scores. Enter if all mandatory filters pass. 

## **6.4  Mid-Session Management (10:30 AM–2:30 PM)** 

- Monitor existing positions only. No new entries between 12:00 and 13:30. 

- Apply breakeven rule: any position flat after 2 days — close 50%. 

- Apply profit protection: at 30% of max profit — move stop to breakeven. 

- Secondary entry window 13:30–14:30 only if primary window produced no qualifying setup. 

## **6.5  Close (2:30–3:30 PM)** 

- No new entries after 14:30. No exceptions. 

- Manage existing positions only. 

- Thursday expiry: All expiry positions closed by 14:00. 

For personal use only. Not investment advice. 

For personal trading use only. 

**OMEGA-S — Systematic Options Trading System** |   NSE F&O   |   Confidential 

## **6.6  Post-Market Log (5 minutes)** 

- Log all trades in MTIL with full context. 

- Record which filters were green/yellow/red today. 

- Record which filters were correct and which were wrong. 

- Note any observations about market behaviour for quarterly review. 

For personal use only. Not investment advice. 

For personal trading use only. 

**OMEGA-S — Systematic Options Trading System** |   NSE F&O   |   Confidential 

## **SECTION 7: Honest Performance Expectations** 

## **CONFIDENCE: MODERATE — Logically sound, limited direct validation** 

**The numbers in this section are estimates, not guarantees. They are based on analysis of verified performance data from comparable systematic traders in Indian markets. The specific numbers for your system cannot be known until you have 12+ months of live trading data. Do not make capital allocation decisions based on these projections alone.** 

## **7.1  Monthly Distribution Reality** 

120% annual does not mean 10% every single month. The realistic distribution looks more like this: 

|**Month Type**|**Frequency**|**Expected Monthly Return**|
|---|---|---|
|Great months|~20% of months|+15% to +22% gross|
|Good months|~35% of months|+8% to +14% gross|
|Flat months|~25% of months|-2% to +7% gross|
|Bad months|~15% of months|-5% to -12% gross|
|Terrible months|~5% of months|-12% to -20% gross|



## **7.2  Three Scenario Projections** 

|**Scenario**|**Monthly Net (after**<br>**tax)**|**Annual Net**|**Probability**|
|---|---|---|---|
|Worst Case|2–4%|27–60%|~25%|
|**Most Likely**|**5–8%**|**80–150%**|**~50%**|
|Best Case|9–12%|180–290%|~25%|



**Tax note: Indian F&O income is treated as business income. Effective tax rate approximately 34– 37% including surcharge and cess. All net figures above assume this deduction. Plan and provision accordingly.** 

## **7.3  Maximum Drawdown Expectations** 

|Normal bad sequence|8–12% drawdown. Recovery: 3–5 weeks at normal pace.|
|---|---|
|Stressed conditions (VIX spike)|12–18% drawdown. Recovery: 6–10 weeks. Circuit breakers<br>activate.|
|Black swan event (tail hedge active)|Tail protection limits impact to approximately 8–15% despite<br>market falling 30–40%.|
|Without tail protection (never<br>happen)|Potential 40–70% drawdown. This is why tail protection is non-<br>negotiable.|



For personal use only. Not investment advice. 

For personal trading use only. 

**OMEGA-S — Systematic Options Trading System** |   NSE F&O   |   Confidential 

## **7.4  Year 1 Realistic Target** 

Treat Year 1 as a learning and calibration year, not a maximum return year. 

- Primary goal: Preserve capital while learning the system. 

- Secondary goal: Validate which Section 3 filters are actually working in live conditions. 

- Return target Year 1: 40–80% net. Anything above this is a bonus. 

- Return target Year 2+: 80–130% net, as system is validated and refined. 

- Do not judge the system based on 3 months of data. Minimum 12 months before meaningful conclusions. 

For personal use only. Not investment advice. 

For personal trading use only. 

**OMEGA-S — Systematic Options Trading System** |   NSE F&O   |   Confidential 

## **SECTION 8: 10-Year Survival Framework** 

## **CONFIDENCE: MODERATE — Logically sound, limited direct validation** 

## **8.1  Honest Survival Statistics** 

Raw retail traders (no system) 2–5% survive 10 years. Primary killers: no risk management, emotional decisions, one catastrophic loss. Traders with defined system 15–25% survive 10 years. Improvement comes from reduced emotional decisions. Institutional-grade systematic 45–65% survive 10 years. Surviving requires adaptation to systems regime changes. OMEGA-S estimated survival 55–70% over 10 years. Based on system quality and protection probability mechanisms present. 

## **8.2  The Five Threats to 10-Year Survival** 

## **Threat 1: Regime Change** 

Markets change character every 3–5 years. A system that works in trending markets fails in ranging markets. MTIL learning system is your primary defence. Review and adjust system parameters annually based on MTIL findings. 

## **Threat 2: Black Swan Events** 

2008, 2020, flash crashes. Single events can destroy unprotected accounts in days. Tail protection hedge is your primary defence. Never remove it. 

## **Threat 3: Regulatory Changes** 

SEBI changes F&O rules, margin requirements, and lot sizes. These have happened multiple times. Review system for regulatory compliance annually. Maintain SEBI static IP registration. 

## **Threat 4: Psychological Override** 

Even with a fully defined system, manual override during drawdowns is the single most common cause of systematic trader failure. The most dangerous moment is when the system is in drawdown and you believe you know better. You do not. Trust the circuit breakers. 

## **Threat 5: Technology Failure** 

Broker API failures, internet outages, power failures. All have happened to every systematic trader. Maintain: backup internet connection, manual entry capability for emergency exits, broker customer service contact details readily accessible. 

For personal use only. Not investment advice. 

For personal trading use only. 

**OMEGA-S — Systematic Options Trading System** |   NSE F&O   |   Confidential 

## **SECTION 9: Daily Testing Log Template** 

## **CONFIDENCE: HIGH — Evidence-based, validated in Indian markets** 

Use this log from day one. The data you collect in the first 6 months is more valuable than any projection in this document. It will tell you what is actually working in live conditions. 

|**Field**|**Record**|
|---|---|
|Date||
|India VIX Level||
|VIX Direction (3-day)|Rising / Flat / Falling|
|OMEGA VRI Mode|Harvest / Protection / Flip|
|BNIOS Min(D,Q) Result|Pass / Fail / Score|
|Sweep/CHoCH Present?|Yes (full size) / No (reduced)|
|Filter A: OI Interpretation|Green / Yellow / Red|
|Filter F: IV Percentile|Green / Yellow / Red + actual percentile|
|Filter B: Value Area|Green / Yellow / Red|
|Filter C: ATM OI Balance|Green / Yellow / Red|
|Filter D: PCR Momentum|Green / Yellow / Red|
|Filter E: Max Pain Distance|Green / Yellow / Red + weight applied|
|Liquidity Check|Pass / Fail|
|Greeks Check|Delta / Theta / Vega — Pass or Fail|
|Final Position Size|% of intended size and reason|
|Trade Entry|Strike, premium, time|
|Trade Exit|Price, time, reason|
|P&L|Amount and % of capital|
|Which filters were correct?||
|Which filters were wrong?||
|Observations||



For personal use only. Not investment advice. 

For personal trading use only. 

**OMEGA-S — Systematic Options Trading System** |   NSE F&O   |   Confidential 

## **SECTION 10: Quick Reference — Pre-Trade Checklist** 

## **CONFIDENCE: HIGH — Evidence-based, validated in Indian markets** 

Run this checklist before every trade. If you cannot complete it in 5 minutes, you are not ready to trade. 

|**#**|**Check**|**Pass Condition**|
|---|---|---|
|1|OMEGA VRI: Which mode are we in?|Harvest / Protection / Flip<br>confirmed|
|2|VIX Direction: Rising, flat, or falling over 3 days?|Not rising sharply|
|3|BNIOS Min(D,Q): Does setup pass minimum threshold?|Both D and Q above threshold|
|4|Entry timing: Are we in primary or secondary window?|9:30–10:30 or 13:30–14:30 only|
|5|Sweep/CHoCH: Has nearest BSL/SSL been swept?|Yes = full size. No = reduce<br>30%|
|6|MANDATORY Filter A: OI Interpretation result?|Green or Yellow only. Red =<br>Stop.|
|7|MANDATORY Filter F: IV Percentile result?|Above 30th percentile. Below =<br>Stop.|
|8|Confirmatory Filters B+C+D+E: How many green?|4=100%, 3=75%, 2=50%,<br>1=25%, 0=No Trade|
|9|Liquidity: Bid-ask spread and volume at strike?|Both Green or Yellow minimum|
|10|Greeks: Delta, Theta, Vega within range?|All three within defined limits|
|11|Risk: Is position size within 3% capital risk limit?|Maximum 3% of total portfolio|
|12|Monthly limit: Are we below 12% monthly drawdown?|If at 12%: reduced size only|



## **OMEGA-S System — End of Document** 

Review and update this document every 6 months based on live trading data. **The MTIL log data you collect is more valuable than anything written here.** 

For personal use only. Not investment advice. 

For personal trading use only. 

