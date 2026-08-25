from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Any

from .dhan import DhanRestClient


@dataclass(frozen=True)
class OrderIntent:
    dhan_client_id: str
    transaction_type: str
    exchange_segment: str
    product_type: str
    order_type: str
    validity: str
    security_id: str
    quantity: int
    price: float
    correlation_id: str = ""

    def validation_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.transaction_type.upper() not in {"BUY", "SELL"}:
            errors.append("transaction_type must be BUY or SELL")
        if self.exchange_segment.upper() not in {"NSE_FNO", "BSE_FNO"}:
            errors.append("exchange_segment must be NSE_FNO or BSE_FNO")
        if self.product_type.upper() != "INTRADAY":
            errors.append("product_type must be INTRADAY")
        if self.order_type.upper() != "LIMIT":
            errors.append("order_type must be LIMIT")
        if self.validity.upper() != "DAY":
            errors.append("validity must be DAY")
        if not str(self.dhan_client_id).strip():
            errors.append("dhan_client_id is required")
        if not str(self.security_id).strip():
            errors.append("security_id is required")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int) or self.quantity <= 0:
            errors.append("quantity must be a positive integer")
        if not isinstance(self.price, (int, float)) or not math.isfinite(float(self.price)) or float(self.price) <= 0:
            errors.append("price must be a finite positive number")
        return tuple(errors)

    def to_dhan_payload(self) -> dict[str, Any]:
        return {
            "dhanClientId": self.dhan_client_id,
            "correlationId": self.correlation_id,
            "transactionType": self.transaction_type,
            "exchangeSegment": self.exchange_segment,
            "productType": self.product_type,
            "orderType": self.order_type,
            "validity": self.validity,
            "securityId": self.security_id,
            "quantity": self.quantity,
            "disclosedQuantity": 0,
            "price": self.price,
            "triggerPrice": 0,
            "afterMarketOrder": False,
            "amoTime": "",
            "boProfitValue": 0,
            "boStopLossValue": 0,
        }


class ExecutionRouter:
    """Guarded execution router.

    demo_trade=True returns simulated order responses. demo_trade=False sends to Dhan via DhanRestClient.
    This module is not used by the paper-mode engine unless explicitly called.
    """

    def __init__(self, dhan_client: DhanRestClient):
        self.dhan_client = dhan_client

    def place(self, intent: OrderIntent) -> Mapping[str, Any]:
        errors = intent.validation_errors()
        if errors:
            return {
                "demo": bool(getattr(self.dhan_client, "demo_trade", False)),
                "orderStatus": "REJECTED_VALIDATION",
                "payload": intent.to_dhan_payload(),
                "message": "; ".join(errors),
                "validationErrors": list(errors),
            }
        return self.dhan_client.place_order(intent.to_dhan_payload())
