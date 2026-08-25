from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional


class DhanAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class DhanCredentials:
    client_id: str
    access_token: str

    @classmethod
    def from_env(cls, client_id_env: str = "DHAN_CLIENT_ID", token_env: str = "DHAN_ACCESS_TOKEN") -> "DhanCredentials":
        client_id = os.getenv(client_id_env, "")
        token = os.getenv(token_env, "")
        if not client_id or not token:
            raise DhanAPIError(f"Missing Dhan credentials in {client_id_env}/{token_env}.")
        return cls(client_id=client_id, access_token=token)


class DhanRestClient:
    """Minimal Dhan REST adapter for paper/live data and guarded order placement.

    This class does not place orders unless demo_trade is False. It intentionally keeps
    API access explicit and auditable.
    """

    def __init__(self, credentials: DhanCredentials, base_url: str = "https://api.dhan.co/v2", demo_trade: bool = True, live_trading_enabled: bool = False, timeout: int = 15):
        self.credentials = credentials
        self.base_url = base_url.rstrip("/")
        self.demo_trade = demo_trade
        self.live_trading_enabled = live_trading_enabled
        self.timeout = timeout
        self._last_option_chain_request: dict[tuple[int, str, str], float] = {}

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "access-token": self.credentials.access_token,
            "client-id": self.credentials.client_id,
        }

    def _request(self, method: str, path: str, body: Optional[Mapping[str, Any]] = None) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base_url + path, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", errors="replace")
            raise DhanAPIError(f"Dhan API HTTP {e.code}: {msg}") from e
        except urllib.error.URLError as e:
            raise DhanAPIError(f"Dhan API URL error: {e}") from e

    def expiry_list(self, underlying_scrip: int, underlying_seg: str = "IDX_I") -> Any:
        return self._request("POST", "/optionchain/expirylist", {"UnderlyingScrip": underlying_scrip, "UnderlyingSeg": underlying_seg})

    def option_chain(self, underlying_scrip: int, expiry: str, underlying_seg: str = "IDX_I", min_interval_sec: float = 3.0) -> Any:
        key = (underlying_scrip, underlying_seg, expiry)
        now = time.monotonic()
        last = self._last_option_chain_request.get(key, 0.0)
        if now - last < min_interval_sec:
            raise DhanAPIError("Option chain rate limit guard: request too soon for same underlying/expiry.")
        self._last_option_chain_request[key] = now
        return self._request("POST", "/optionchain", {"UnderlyingScrip": underlying_scrip, "UnderlyingSeg": underlying_seg, "Expiry": expiry})

    def orders(self) -> Any:
        return self._request("GET", "/orders")

    def trades(self) -> Any:
        return self._request("GET", "/trades")

    def place_order(self, payload: Mapping[str, Any]) -> Any:
        if self.demo_trade:
            return {
                "demo": True,
                "orderStatus": "DEMO_NOT_SENT",
                "payload": dict(payload),
                "message": "demo_trade=True; order not sent to Dhan."
            }
        if not self.live_trading_enabled:
            return {
                "demo": False,
                "orderStatus": "LIVE_BLOCKED",
                "payload": dict(payload),
                "message": "live_trading_enabled=False; order not sent to Dhan."
            }
        return self._request("POST", "/orders", payload)

    def download_instrument_master(self, url: str, output_path: str | Path) -> Path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                out.write_bytes(resp.read())
        except urllib.error.URLError as e:
            raise DhanAPIError(f"Failed to download instrument master: {e}") from e
        return out
