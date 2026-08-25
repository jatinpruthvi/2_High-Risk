"""Entry point for the live paper trading program with visual dashboard.

    python -m institutional_options.paper_trade

Starts the Fyers-backed paper runner (no orders placed) and serves a live
dashboard at http://127.0.0.1:8765 (configurable via uploads/PAPER_RUNNER.json).

First run requires one interactive Fyers login (the auth URL is printed);
the access token is then saved to paper_state/tokens.json and auto-refreshes.
"""
from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path

from .config import SystemConfig
from .fyers_client import FyersSymbolMaster
from .paper_dashboard import PaperDashboard
from .paper_runner import PaperRunner


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Start the paper-only options runner")
    ap.add_argument("--preflight", action="store_true", help="Validate the paper universe and safety boundary without logging in or starting the runner")
    ap.add_argument("--state-dir", default=None, help="Evidence/state directory; use a dated directory for a clean research session")
    args = ap.parse_args(argv)
    cfg = SystemConfig.from_file("uploads/PARAMETERS.json")
    runner_cfg_path = Path("uploads/PAPER_RUNNER.json")
    runner_cfg = json.loads(runner_cfg_path.read_text(encoding="utf-8")) if runner_cfg_path.exists() else {}
    underlyings = runner_cfg.get("underlyings", {})
    enabled = [name for name, meta in underlyings.items() if meta.get("trade_enabled") is True and meta.get("monitor_only") is False]
    state_dir = Path(args.state_dir or runner_cfg.get("state_dir", "paper_state"))
    if args.preflight:
        configured = list(cfg.section("instrument_universe").get("eligible_underlyings", []))
        if set(configured) != set(underlyings) or len(configured) != 59 or len(enabled) != 59:
            raise SystemExit("PREFLIGHT FAILED: the configured and runner paper universes are not the expected 59 instruments.")
        if cfg.section("execution").get("live_trading_enabled") is not False:
            raise SystemExit("PREFLIGHT FAILED: live execution is not disabled.")
        if cfg.section("instrument_universe").get("max_open_positions") != 1 or cfg.section("instrument_universe").get("max_pending_orders") != 1:
            raise SystemExit("PREFLIGHT FAILED: position or pending-order limit is not one.")
        masters = []
        for exchange in sorted({str(meta.get("exchange", "NSE")).upper() for meta in underlyings.values()}):
            path = state_dir / f"{exchange}_FO.csv"
            if not path.exists():
                raise SystemExit(f"PREFLIGHT FAILED: cached {exchange}_FO.csv is missing; start the runner once to refresh the master.")
            masters.append(FyersSymbolMaster.from_csv(path, allowed_exchanges={exchange}, allowed_underlyings=set(underlyings)))
        master = FyersSymbolMaster.combine(*masters)
        missing = []
        for underlying in configured:
            rows = [item for item in master.instruments if item.underlying.upper() == underlying.upper()]
            if not rows or not master.expiry_dates(underlying) or not any(item.option_type == "CE" for item in rows) or not any(item.option_type == "PE" for item in rows) or not {item.lot_size for item in rows} or not {item.tick_size for item in rows}:
                missing.append(underlying)
        if missing:
            raise SystemExit("PREFLIGHT FAILED: contract metadata is incomplete for " + ", ".join(missing))
        print(f"PREFLIGHT PASS: 59 instruments paper-enabled; metadata=59/59; monitor-only=0; live execution=DISABLED; max_open_positions=1; max_pending_orders=1; state_dir={state_dir}")
        return 0

    state_dir = str(state_dir)
    runner = PaperRunner(cfg, runner_cfg, state_dir=state_dir)
    dash_cfg = runner_cfg.get("dashboard", {})
    dashboard = PaperDashboard(
        runner.snapshot,
        host=str(dash_cfg.get("host", "127.0.0.1")),
        port=int(dash_cfg.get("port", 8765)),
    )
    url = dashboard.start()
    print(f"\nDashboard: {url}  (Ctrl+C to stop)")
    stop = threading.Event()
    try:
        runner.run_forever(stop_event=stop)
    except KeyboardInterrupt:
        print("\nStopping paper runner…")
    finally:
        dashboard.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
