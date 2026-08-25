"""Dependency-free Fyers v3 REST client for the paper trading runner.

Implements the endpoints validated against the live Fyers API:

  * POST /api/v3/validate-authcode      auth-code -> access + refresh token
  * POST /api/v3/validate-refresh-token refresh token -> new access token
  * GET  /data/options-chain-v3         option chain + expiry calendar + VIX
  * GET  /data/depth                     read-only multi-level market depth
  * GET  /data/quotes                   quotes for up to 50 symbols
  * GET  /data/history                  historical candles
  * GET  https://public.fyers.in/sym_details/NSE_FO.csv  symbol master (no auth)

Notes on the Fyers v3 quirks that were verified live:

  * ``appIdHash`` is SHA-256 of ``appId-appType:appSecret`` (hex digest), NOT
    base64.  appId here is the full "3YCSQXVJFP-100" string including app type.
  * Market data endpoints live under /data (not /api/v3) and are GET.
  * The Authorization header for data endpoints is ``<app_id>:<access_token>``.

This module never places orders. It only reads market data and manages the
session tokens needed to do so.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

AUTH_BASE = "https://api-t1.fyers.in/api/v3"
DATA_BASE = "https://api-t1.fyers.in/data"
SYMBOL_MASTER_URL = "https://public.fyers.in/sym_details/NSE_FO.csv"
IST = timezone(timedelta(hours=5, minutes=30))
REDIRECT_URI = "https://trade.fyers.in/api-login/redirect-uri/index.html"
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


class FyersAPIError(RuntimeError):
    def __init__(self, message: str, status_code: Optional[int] = None,
                 retry_after_seconds: Optional[float] = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class FyersCredentials:
    app_id: str          # full "APPID-100" string
    secret_id: str
    pin: str = ""        # trading PIN required by Fyers v3 validate-refresh-token

    @property
    def app_id_hash(self) -> str:
        return hashlib.sha256(f"{self.app_id}:{self.secret_id}".encode()).hexdigest()

    @classmethod
    def from_env(cls, app_id_env: str = "FYERS_APP_ID", secret_env: str = "FYERS_SECRET_ID",
                 pin_env: str = "FYERS_PIN") -> "FyersCredentials":
        app_id = os.getenv(app_id_env, "")
        secret = os.getenv(secret_env, "")
        if not app_id or not secret:
            raise FyersAPIError(f"Missing Fyers credentials in {app_id_env}/{secret_env}.")
        return cls(app_id=app_id, secret_id=secret, pin=os.getenv(pin_env, "") or "")


@dataclass
class TokenStore:
    """Persists access + refresh tokens to a JSON file (gitignored directory)."""

    path: str | Path
    access_token: str = ""
    refresh_token: str = ""
    updated_at: Optional[str] = None

    def load(self) -> None:
        p = Path(self.path)
        if not p.exists():
            return
        try:
            raw = json.loads(p.read_text(encoding="utf-8-sig"))
            self.access_token = raw.get("access_token", "")
            self.refresh_token = raw.get("refresh_token", "")
            self.updated_at = raw.get("updated_at")
        except (json.JSONDecodeError, OSError):
            self.access_token = ""
            self.refresh_token = ""

    def save(self, access_token: str, refresh_token: str) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.updated_at = datetime.now(timezone.utc).isoformat()
        p = Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "updated_at": self.updated_at,
        }, indent=2), encoding="utf-8")

    def clear(self) -> None:
        p = Path(self.path)
        if p.exists():
            p.unlink()


def _req(url: str, method: str = "GET", body: Optional[Mapping[str, Any]] = None,
         auth_header: str = "", timeout: int = 60, raw_text: bool = False):
    headers = dict(UA)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if auth_header:
        headers["Authorization"] = auth_header
        headers["version"] = "3"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if raw_text:
                return resp.status, raw.decode("utf-8", "replace")
            try:
                return resp.status, json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                return resp.status, raw[:500].decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        retry_after = None
        try:
            raw_retry_after = e.headers.get("Retry-After", "") if e.headers else ""
            retry_after = float(raw_retry_after) if raw_retry_after else None
        except (TypeError, ValueError):
            retry_after = None
        raise FyersAPIError(
            f"Fyers HTTP {e.code} on {url}: {detail}",
            status_code=e.code,
            retry_after_seconds=retry_after,
        ) from e
    except urllib.error.URLError as e:
        raise FyersAPIError(f"Fyers URL error on {url}: {e}") from e


def login_url(app_id: str, state: str = "paper-runner") -> str:
    return (f"{AUTH_BASE}/generate-authcode?"
            + urllib.parse.urlencode({"client_id": app_id, "redirect_uri": REDIRECT_URI,
                                      "response_type": "code", "state": state}))


class FyersRestClient:
    """Read-only Fyers market data client (never places orders)."""

    def __init__(self, credentials: FyersCredentials, token_store: TokenStore,
                 timeout: int = 60,
                 request_min_interval_sec: float = 0.35,
                 max_transient_retries: int = 2,
                 transient_backoff_sec: tuple[float, ...] = (1.0, 3.0),
                 max_backoff_sec: float = 8.0):
        self.credentials = credentials
        self.tokens = token_store
        self.tokens.load()
        self.timeout = timeout
        self._auth_header = ""
        try:
            self._request_min_interval_sec = max(0.0, float(request_min_interval_sec))
        except (TypeError, ValueError):
            self._request_min_interval_sec = 0.35
        try:
            self._max_transient_retries = max(0, min(4, int(max_transient_retries)))
        except (TypeError, ValueError):
            self._max_transient_retries = 2
        try:
            parsed_backoff = tuple(max(0.0, float(x)) for x in transient_backoff_sec)
        except (TypeError, ValueError):
            parsed_backoff = (1.0, 3.0)
        self._transient_backoff_sec = parsed_backoff or (1.0,)
        try:
            self._max_backoff_sec = max(0.0, float(max_backoff_sec))
        except (TypeError, ValueError):
            self._max_backoff_sec = 8.0
        self._request_last_request_at = 0.0
        self._request_stats = {
            "requests": 0,
            "successes": 0,
            "errors": 0,
            "rate_limit_hits": 0,
            "retries": 0,
            "last_status": None,
            "last_error": "",
            "last_retry_sleep_seconds": 0.0,
            "min_interval_seconds": self._request_min_interval_sec,
            "max_transient_retries": self._max_transient_retries,
        }
        self._depth_last_request_at = 0.0
        self._depth_min_interval_sec = 0.10
        self._depth_backoff_sec = (0.50, 1.00)
        self._depth_cache_ttl_sec = 0.50
        self._depth_cache: dict[str, tuple[float, Any]] = {}
        self._depth_stats = {
            "requests": 0,
            "successes": 0,
            "errors": 0,
            "rate_limit_hits": 0,
            "retries": 0,
            "cache_hits": 0,
            "last_error": "",
        }

    def _pace_request(self, minimum_interval: Optional[float] = None) -> None:
        interval = self._request_min_interval_sec if minimum_interval is None else max(
            self._request_min_interval_sec, float(minimum_interval)
        )
        wait = interval - (time.monotonic() - self._request_last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._request_last_request_at = time.monotonic()

    def _api_request(self, url: str, method: str = "GET",
                     body: Optional[Mapping[str, Any]] = None,
                     auth_header: str = "", timeout: Optional[int] = None,
                     raw_text: bool = False):
        attempts = self._max_transient_retries + 1
        for attempt in range(attempts):
            self._pace_request()
            self._request_stats["requests"] += 1
            try:
                status, resp = _req(
                    url,
                    method=method,
                    body=body,
                    auth_header=auth_header,
                    timeout=self.timeout if timeout is None else timeout,
                    raw_text=raw_text,
                )
                self._request_stats["successes"] += 1
                self._request_stats["last_status"] = status
                self._request_stats["last_error"] = ""
                self._request_stats["last_retry_sleep_seconds"] = 0.0
                return status, resp
            except FyersAPIError as exc:
                if exc.status_code == 429:
                    self._request_stats["rate_limit_hits"] += 1
                if self._is_transient_error(exc) and attempt < attempts - 1:
                    self._request_stats["retries"] += 1
                    retry_after = getattr(exc, "retry_after_seconds", None)
                    if retry_after is None:
                        retry_after = self._transient_backoff_sec[
                            min(attempt, len(self._transient_backoff_sec) - 1)
                        ]
                    delay = min(self._max_backoff_sec, max(0.0, float(retry_after)))
                    self._request_stats["last_retry_sleep_seconds"] = delay
                    if delay > 0:
                        time.sleep(delay)
                    continue
                self._request_stats["errors"] += 1
                self._request_stats["last_status"] = exc.status_code
                self._request_stats["last_error"] = str(exc)[:300]
                raise
        raise FyersAPIError("Fyers request exhausted retry budget")

    def request_stats(self) -> dict[str, Any]:
        return dict(self._request_stats)
    # -- session management ---------------------------------------------------

    def ensure_session(self, interactive: bool = True) -> str:
        """Return a usable Authorization header, refreshing or logging in as needed."""
        if self._auth_header and self.tokens.access_token:
            return self._auth_header
        if not self.tokens.access_token:
            self._interactive_login() if interactive else self._raise_no_session()
            return self._auth_header
        # Try the saved access token; refresh if it fails.
        header = self._combined_header()
        try:
            probe_ok = self._probe(header)
        except FyersAPIError as exc:
            if self._is_transient_error(exc):
                self._auth_header = header
                return header
            raise
        if probe_ok:
            self._auth_header = header
            return header
        if self.tokens.refresh_token:
            try:
                self._refresh()
                header = self._combined_header()
                if self._probe(header):
                    self._auth_header = header
                    return header
            except FyersAPIError as exc:
                if self._is_transient_error(exc):
                    self._auth_header = self._combined_header()
                    return self._auth_header
                pass
        self.tokens.clear()
        if interactive:
            self._interactive_login()
            return self._auth_header
        self._raise_no_session()

    def _combined_header(self) -> str:
        return f"{self.credentials.app_id}:{self.tokens.access_token}"

    @staticmethod
    def _is_transient_error(exc: FyersAPIError) -> bool:
        code = exc.status_code
        if code in {408, 425, 429, 500, 502, 503, 504}:
            return True
        # Fyers/Cloudflare may return HTTP 403 for an edge access block.
        # Preserve the token only when the error is explicitly identified as
        # Cloudflare; an ordinary 403 remains an authentication failure.
        detail = str(exc).lower()
        return code == 403 and ("cloudflare" in detail or "error 1010" in detail)

    def _probe(self, header: str) -> bool:
        try:
            status, _ = self._api_request(
                f"{DATA_BASE}/quotes?" + urllib.parse.urlencode({"symbols": "NSE:NIFTY50-INDEX"}),
                auth_header=header,
                timeout=20,
            )
            return status == 200
        except FyersAPIError as exc:
            # Rate limits and temporary broker/server failures do not prove that
            # the saved token is invalid. Preserve the token and let the caller
            # publish a truthful transient data error instead of prompting login.
            if self._is_transient_error(exc):
                raise
            return False

    def _pin(self) -> str:
        """Fyers v3 refresh requires the trading PIN. Prefer the FYERS_PIN env
        var; fall back to a FYERS_PIN= line in creds.env next to the token file
        (paper_state/creds.env, gitignored)."""
        if self.credentials.pin:
            return self.credentials.pin
        try:
            env_path = Path(self.tokens.path).parent / "creds.env"
            if env_path.exists():
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("FYERS_PIN=") and len(line) > len("FYERS_PIN="):
                        return line[len("FYERS_PIN="):].strip().strip('"').strip("'")
        except OSError:
            pass
        return ""

    def _refresh(self) -> None:
        body = {
            "grant_type": "refresh_token",
            "appIdHash": self.credentials.app_id_hash,
            "refresh_token": self.tokens.refresh_token,
        }
        pin = self._pin()
        if pin:
            body["pin"] = pin
        status, resp = _req(f"{AUTH_BASE}/validate-refresh-token", "POST", body)
        if not isinstance(resp, dict) or resp.get("s") != "ok" or not resp.get("access_token"):
            raise FyersAPIError(f"Refresh failed: {resp}")
        self.tokens.save(resp["access_token"], resp.get("refresh_token") or self.tokens.refresh_token)

    def _interactive_login(self) -> None:
        print("\n" + "=" * 70)
        print("FYERS LOGIN REQUIRED (one-time; token is saved to paper_state/)")
        print("Open this URL in your browser:")
        print(login_url(self.credentials.app_id))
        print("=" * 70)
        auth_code = input("Paste the auth_code from the address bar: ").strip()
        status, resp = _req(f"{AUTH_BASE}/validate-authcode", "POST", {
            "grant_type": "authorization_code",
            "appIdHash": self.credentials.app_id_hash,
            "code": auth_code,
        })
        if not isinstance(resp, dict) or resp.get("s") != "ok" or not resp.get("access_token"):
            raise FyersAPIError(f"Auth-code exchange failed: {resp}")
        self.tokens.save(resp["access_token"], resp.get("refresh_token", ""))
        self._auth_header = self._combined_header()

    def _raise_no_session(self) -> None:
        raise FyersAPIError("No Fyers session. Provide FYERS_APP_ID/FYERS_SECRET_ID "
                            "env vars and run interactively to log in once.")

    # -- market data (read-only) ---------------------------------------------

    def option_chain(self, symbol: str, strikecount: int = 30, expiry_timestamp: str = "",
                     header: str = "") -> Any:
        params = {"symbol": symbol, "strikecount": str(strikecount)}
        if expiry_timestamp:
            params["timestamp"] = expiry_timestamp
        url = f"{DATA_BASE}/options-chain-v3?" + urllib.parse.urlencode(params)
        status, resp = self._api_request(url, auth_header=header or self._auth_header)
        return resp

    def quotes(self, symbols: list[str], header: str = "") -> Any:
        url = f"{DATA_BASE}/quotes?" + urllib.parse.urlencode({"symbols": ",".join(symbols)})
        status, resp = self._api_request(url, auth_header=header or self._auth_header)
        return resp

    def market_depth(self, symbol: str, ohlcv_flag: int | str = 1, header: str = "") -> Any:
        """Return read-only Fyers market depth with bounded pacing and 429 retry."""
        if not str(symbol or "").strip():
            raise FyersAPIError("Market depth requires a Fyers symbol")
        symbol = str(symbol).strip()
        now_monotonic = time.monotonic()
        cached = self._depth_cache.get(symbol)
        if cached is not None and now_monotonic - cached[0] <= self._depth_cache_ttl_sec:
            self._depth_stats["cache_hits"] += 1
            return cached[1]
        params = urllib.parse.urlencode({"symbol": symbol, "ohlcv_flag": str(ohlcv_flag)})
        url = f"{DATA_BASE}/depth?{params}"
        for attempt in range(3):
            self._pace_request(self._depth_min_interval_sec)
            self._depth_last_request_at = self._request_last_request_at
            self._depth_stats["requests"] += 1
            self._request_stats["requests"] += 1
            try:
                status, resp = _req(url, auth_header=header or self._auth_header, timeout=self.timeout)
                self._depth_stats["successes"] += 1
                self._depth_stats["last_error"] = ""
                self._request_stats["successes"] += 1
                self._request_stats["last_status"] = status
                self._request_stats["last_error"] = ""
                if isinstance(resp, Mapping) and str(resp.get("s", "")).lower() == "ok":
                    self._depth_cache[symbol] = (time.monotonic(), resp)
                return resp
            except FyersAPIError as exc:
                if exc.status_code == 429:
                    self._depth_stats["rate_limit_hits"] += 1
                    self._request_stats["rate_limit_hits"] += 1
                if self._is_transient_error(exc) and attempt < self._max_transient_retries:
                    self._depth_stats["retries"] += 1
                    self._request_stats["retries"] += 1
                    retry_after = getattr(exc, "retry_after_seconds", None)
                    if retry_after is None:
                        retry_after = self._depth_backoff_sec[min(attempt, len(self._depth_backoff_sec) - 1)]
                    delay = min(self._max_backoff_sec, max(0.0, float(retry_after)))
                    self._request_stats["last_retry_sleep_seconds"] = delay
                    if delay > 0:
                        time.sleep(delay)
                    continue
                self._depth_stats["errors"] += 1
                self._depth_stats["last_error"] = str(exc)[:300]
                self._request_stats["errors"] += 1
                self._request_stats["last_status"] = exc.status_code
                self._request_stats["last_error"] = str(exc)[:300]
                raise
        raise FyersAPIError("Fyers depth request exhausted retry budget")

    def depth_stats(self) -> dict[str, Any]:
        return dict(self._depth_stats)

    def history(self, symbol: str, resolution: str = "1",
                range_from: str | int = "", range_to: str | int = "",
                cont_flag: str = "1", header: str = "") -> Any:
        params = {"symbol": symbol, "resolution": resolution,
                  "date_format": "1", "range_from": range_from, "range_to": range_to,
                  "cont_flag": cont_flag}
        url = f"{DATA_BASE}/history?" + urllib.parse.urlencode(params)
        status, resp = self._api_request(url, auth_header=header or self._auth_header)
        return resp

    # -- symbol master ---------------------------------------------------------

    def download_symbol_master(self, output_path: str | Path,
                               exchange: str = "NSE") -> Path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        exchange = str(exchange or "NSE").upper()
        if exchange not in {"NSE", "BSE"}:
            raise FyersAPIError(f"Unsupported Fyers symbol-master exchange: {exchange}")
        url = f"https://public.fyers.in/sym_details/{exchange}_FO.csv"
        status, text = self._api_request(url, raw_text=True, timeout=120)
        out.write_text(text, encoding="utf-8")
        return out

    def fetch_symbol_master(self, output_path: str | Path, max_age_hours: float = 20.0,
                            exchange: str = "NSE") -> Path:
        """Download an exchange's derivatives master once per day."""
        out = Path(output_path)
        if out.exists() and (time.time() - out.stat().st_mtime) < max_age_hours * 3600:
            return out
        return self.download_symbol_master(out, exchange=exchange)


@dataclass(frozen=True)
class FyersInstrument:
    """One option contract from the NSE_FO symbol master."""

    fyers_symbol: str      # e.g. NSE:NIFTY26AUG5000CE
    token: str
    underlying: str        # NIFTY / BANKNIFTY / FINNIFTY / MIDCPNIFTY
    expiry_date: Optional[date]
    expiry_ts: int
    strike: Optional[float]
    option_type: Optional[str]
    lot_size: int
    tick_size: float


class FyersSymbolMaster:
    """Parsed NSE_FO.csv: option contracts with expiry, lot and tick per underlying.

    Column layout (0-indexed) of NSE_FO.csv:
      0 token, 1 display name, 2 exchange, 3 lot size, 4 tick, 5 -, 6 hours,
      7 date string, 8 expiry unix ts, 9 Fyers symbol (NSE:...), 12 strike/token,
      13 underlying, ...
    """

    COL_LOT = 3
    COL_TICK = 4
    COL_EXPIRY_TS = 8
    COL_SYM = 9
    COL_UND = 13
    DEFAULT_INDEX_UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"}

    def __init__(self, instruments: list[FyersInstrument]):
        self.instruments = tuple(instruments)
        self._by_und_expiry: dict[tuple[str, date], list[FyersInstrument]] = {}
        for inst in self.instruments:
            if inst.expiry_date is None:
                continue
            self._by_und_expiry.setdefault((inst.underlying.upper(), inst.expiry_date), []).append(inst)

    @classmethod
    def from_csv(cls, path: str | Path,
                 allowed_exchanges: Optional[set[str]] = None,
                 allowed_underlyings: Optional[set[str]] = None) -> "FyersSymbolMaster":
        out: list[FyersInstrument] = []
        exchanges = {str(x).upper() for x in (allowed_exchanges or {"NSE"})}
        underlyings = ({str(x).upper() for x in allowed_underlyings}
                       if allowed_underlyings is not None
                       else set(cls.DEFAULT_INDEX_UNDERLYINGS))
        with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.reader(f):
                if len(row) <= cls.COL_SYM:
                    continue
                sym = row[cls.COL_SYM]
                exchange = sym.split(":", 1)[0].upper() if ":" in sym else ""
                if exchange not in exchanges:
                    continue
                underlying = row[cls.COL_UND].strip().upper()
                if underlyings is not None and underlying not in underlyings:
                    continue
                try:
                    expiry_ts = int(float(row[cls.COL_EXPIRY_TS]))
                    lot = int(float(row[cls.COL_LOT]))
                    tick = float(row[cls.COL_TICK])
                except (ValueError, IndexError):
                    continue
                expiry_date = datetime.fromtimestamp(expiry_ts, timezone.utc).astimezone(IST).date()
                display_name = row[1].strip() if len(row) > 1 else ""
                strike, opt = cls._parse_option_symbol(sym, display_name)

                out.append(FyersInstrument(sym, row[0], underlying, expiry_date, expiry_ts,
                                           strike, opt, lot, tick))
        return cls(out)

    @classmethod
    def combine(cls, *masters: "FyersSymbolMaster") -> "FyersSymbolMaster":
        instruments: list[FyersInstrument] = []
        for master in masters:
            instruments.extend(master.instruments)
        return cls(instruments)

    @staticmethod
    def _parse_option_symbol(sym: str, display_name: str = "") -> tuple[Optional[float], Optional[str]]:
        """Parse option metadata without treating encoded expiry digits as strike.

        Current Fyers numeric symbols look like ``NIFTY2681824200CE`` where the
        date prefix and strike are concatenated.  The symbol alone is ambiguous;
        the public symbol master display-name column is the authoritative source
        for the strike, e.g. ``NIFTY 18 Aug 26 24200 CE``.
        """
        import re

        display = str(display_name or "").strip().upper()
        match = re.search(r"(\d+(?:\.\d+)?)\s+(CE|PE)\s*$", display)
        if match:
            return float(match.group(1)), match.group(2)

        body = str(sym or "").split(":", 1)[-1].upper()
        if body.endswith(("CE", "PE")):
            opt = body[-2:]
            body_without_opt = body[:-2]
            # Alpha-month symbols such as NIFTY26AUG24200CE are unambiguous.
            match = re.search(r"\d{2}[A-Z]{3}(\d+(?:\.\d+)?)$", body_without_opt)
            if match:
                return float(match.group(1)), opt
            # Do not guess from a numeric date+strike symbol.  The display name
            # should be present in a valid symbol master row.
        return None, None

    def expiry_dates(self, underlying: str) -> tuple[date, ...]:
        return tuple(sorted({e for (u, e) in self._by_und_expiry if u == underlying.upper()}))

    def lot_size(self, underlying: str, expiry: date) -> int:
        rows = self._by_und_expiry.get((underlying.upper(), expiry), [])
        lots = {r.lot_size for r in rows}
        if not lots:
            raise FyersAPIError(f"No instrument rows for {underlying} {expiry}")
        # Prefer the most common lot size; some expiries carry multiple.
        from collections import Counter
        return Counter(lots).most_common(1)[0][0]

    def tick_size(self, underlying: str, expiry: date) -> float:
        rows = self._by_und_expiry.get((underlying.upper(), expiry), [])
        if not rows:
            raise FyersAPIError(f"No instrument rows for {underlying} {expiry}")
        ticks = {r.tick_size for r in rows}
        return min(ticks)

    def symbol_for(self, underlying: str, expiry: date, strike: float, option_type: str) -> str:
        rows = self._by_und_expiry.get((underlying.upper(), expiry), [])
        for r in rows:
            if r.strike is not None and abs(r.strike - strike) < 1e-6 and (r.option_type or "").upper() == option_type.upper():
                return r.fyers_symbol
        raise FyersAPIError(f"No Fyers symbol for {underlying} {expiry} {strike} {option_type}")
