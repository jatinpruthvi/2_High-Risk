from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChargesConfig:
    brokerage_per_order_rupees: float
    gst_rate_pct: float
    stt_sell_rate_pct: float
    exchange_transaction_charge_rate_pct: float
    sebi_turnover_fee_rate_pct: float
    stamp_duty_buy_rate_pct: float
    ipft_rate_pct: float = 0.0

    @classmethod
    def from_file(cls, path: str | Path) -> "ChargesConfig":
        raw = json.loads(Path(path).read_text())
        return cls(
            brokerage_per_order_rupees=float(raw.get("brokerage_per_order_rupees", 0.0)),
            gst_rate_pct=float(raw.get("gst_rate_pct", 0.0)),
            stt_sell_rate_pct=float(raw.get("stt_sell_rate_pct", 0.0)),
            exchange_transaction_charge_rate_pct=float(raw.get("exchange_transaction_charge_rate_pct", 0.0)),
            sebi_turnover_fee_rate_pct=float(raw.get("sebi_turnover_fee_rate_pct", 0.0)),
            stamp_duty_buy_rate_pct=float(raw.get("stamp_duty_buy_rate_pct", 0.0)),
            ipft_rate_pct=float(raw.get("ipft_rate_pct", 0.0)),
        )


@dataclass(frozen=True)
class CostBreakdown:
    brokerage: float
    gst: float
    stt: float
    exchange_transaction_charges: float
    sebi_charges: float
    stamp_duty: float
    ipft: float
    total: float


class CostCalculator:
    def __init__(self, charges: ChargesConfig):
        self.charges = charges

    def round_trip_cost(self, buy_value: float, sell_value: float) -> CostBreakdown:
        turnover = buy_value + sell_value
        brokerage = 2.0 * self.charges.brokerage_per_order_rupees
        gst = brokerage * self.charges.gst_rate_pct / 100.0
        stt = sell_value * self.charges.stt_sell_rate_pct / 100.0
        exch = turnover * self.charges.exchange_transaction_charge_rate_pct / 100.0
        sebi = turnover * self.charges.sebi_turnover_fee_rate_pct / 100.0
        stamp = buy_value * self.charges.stamp_duty_buy_rate_pct / 100.0
        ipft = turnover * self.charges.ipft_rate_pct / 100.0
        total = brokerage + gst + stt + exch + sebi + stamp + ipft
        return CostBreakdown(brokerage, gst, stt, exch, sebi, stamp, ipft, total)


@dataclass(frozen=True)
class ChargesValidationResult:
    valid: bool
    reasons: tuple[str, ...]


def validate_charges_config(path: str | Path) -> ChargesValidationResult:
    raw = json.loads(Path(path).read_text())
    reasons: list[str] = []
    status = str(raw.get("status", "")).upper()
    if "PLACEHOLDER" in status or not status:
        reasons.append("Charges config status is placeholder/unverified")
    required = [
        "brokerage_per_order_rupees",
        "gst_rate_pct",
        "stt_sell_rate_pct",
        "exchange_transaction_charge_rate_pct",
        "sebi_turnover_fee_rate_pct",
        "stamp_duty_buy_rate_pct",
    ]
    for key in required:
        value = raw.get(key)
        if value is None:
            reasons.append(f"Missing {key}")
        else:
            try:
                if float(value) < 0:
                    reasons.append(f"Negative {key}")
            except (TypeError, ValueError):
                reasons.append(f"Non-numeric {key}")
    return ChargesValidationResult(valid=not reasons, reasons=tuple(reasons))
