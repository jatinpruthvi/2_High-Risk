# Instrument Mapping Specification — DHAN MVP

## Purpose
Prevent wrong-contract trading by mapping all instruments through DHAN's detailed instrument master.

## Source
Download daily before market open:

```text
https://images.dhan.co/api-data/api-scrip-master-detailed.csv
```

## Canonical Option Key

```text
UNDERLYING|INSTRUMENT_TYPE|EXPIRY|STRIKE|OPTION_TYPE
```

Example:

```text
BANKNIFTY|OPTIDX|2026-06-30|55000|CE
```

## Required Fields

- EXCH_ID
- SEGMENT
- SECURITY_ID
- INSTRUMENT
- UNDERLYING_SECURITY_ID
- UNDERLYING_SYMBOL
- SYMBOL_NAME
- DISPLAY_NAME
- LOT_SIZE
- SM_EXPIRY_DATE
- STRIKE_PRICE
- OPTION_TYPE
- TICK_SIZE
- EXPIRY_FLAG
- SM_FREEZE_QTY
- BUY_SELL_INDICATOR

## Bank Nifty Option Mapping Rule

Filter detailed master where:

```text
EXCH_ID = NSE
SEGMENT = D
INSTRUMENT = OPTIDX
UNDERLYING_SYMBOL = BANKNIFTY
SM_EXPIRY_DATE = selected expiry
STRIKE_PRICE = selected strike
OPTION_TYPE = CE or PE
```

The resulting `SECURITY_ID` is used for DHAN market data and trading.

## Bank Nifty Futures Mapping Rule

Filter detailed master where:

```text
EXCH_ID = NSE
SEGMENT = D
INSTRUMENT = FUTIDX
UNDERLYING_SYMBOL = BANKNIFTY
SM_EXPIRY_DATE = selected futures expiry
```

## Equity Mapping Rule

Filter detailed master where:

```text
EXCH_ID = NSE
SEGMENT = E
UNDERLYING_SYMBOL = stock symbol
INSTRUMENT = EQUITY
SERIES = EQ
```

## MVP Key Equity IDs Observed

| Symbol | DHAN Security ID |
|---|---:|
| HDFCBANK | 1333 |
| ICICIBANK | 4963 |
| SBIN | 3045 |
| AXISBANK | 5900 |
| KOTAKBANK | 1922 |

These are reference values only. Always refresh from master.

## Validation Rules

Before market open:

1. Download master.
2. Confirm Bank Nifty futures current expiry exists.
3. Confirm current option expiry exists.
4. Confirm selected option contract has valid security ID.
5. Confirm lot size = expected lot size.
6. Confirm BUY_SELL_INDICATOR allows trading.
7. Confirm tick size by observing live bid/ask increments.

## Hard Veto

```text
No trade if instrument mapping is missing, stale, duplicated, or inconsistent.
```

---

# Phase 1 Multi-Instrument Mapping Extension

## Eligible Index Underlyings

Phase 1 evaluates the following index option underlyings:

```text
BANKNIFTY
NIFTY
FINNIFTY
MIDCPNIFTY
```

These symbols must not be permanently hardcoded as final tradable identifiers. They are canonical internal names that must be resolved through the DHAN detailed instrument master every trading day.

## Generic Index Option Mapping Rule

For any eligible index option, filter detailed master where:

```text
EXCH_ID = NSE
SEGMENT = D
INSTRUMENT = OPTIDX
UNDERLYING_SYMBOL = selected underlying
SM_EXPIRY_DATE = selected expiry
STRIKE_PRICE = selected strike
OPTION_TYPE = CE or PE
```

The resulting `SECURITY_ID` is used for DHAN market data and trading.

## Generic Index Futures Mapping Rule

For any eligible index future, filter detailed master where:

```text
EXCH_ID = NSE
SEGMENT = D
INSTRUMENT = FUTIDX
UNDERLYING_SYMBOL = selected underlying
SM_EXPIRY_DATE = selected futures expiry
```

## Dynamic Fields Required Per Instrument

For every eligible index, load from master:

- security_id
- lot_size
- tick_size
- expiry calendar
- strike ladder
- freeze quantity
- buy/sell indicator
- display name

## Hard Veto

```text
No instrument can enter Phase 1 ranking if its futures or option mapping is missing, stale, duplicated, or inconsistent.
```

## Midcap Nifty Extra Rule

Midcap Nifty is eligible for evaluation but requires extra liquidity validation before live selection:

```text
If MIDCPNIFTY selected option spread/depth/quote freshness is not excellent:
    exclude MIDCPNIFTY from live trade selection.
```

---

# Per-Instrument Risk Mapping Requirement

For every selected index option candidate, the risk engine must load:

```text
lot_size_i
true_tick_size_i
expiry_date_i
strike_step_i
freeze_qty_i
buy_sell_indicator_i
```

from DHAN master or live validation.

Hard rule:

```text
Do not use BANKNIFTY lot size or tick size for NIFTY, FINNIFTY, or MIDCPNIFTY.
```

Before a candidate can enter ranking:

```text
lot_size_i must be valid
tick_size_i must be validated from live bid/ask increments
expiry must match selected contract
strike must exist in master
```
