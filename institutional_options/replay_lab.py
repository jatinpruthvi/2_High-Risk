"""Offline replay + parameter-sweep lab for captured paper sessions.

The live runner (paper_runner.py with ``capture: true``) writes every poll's
raw chain/history payloads to ``paper_state/sessions/<session>.jsonl.gz``.
This module replays those payloads through the *same* PaperRunner pipeline with
the clock pinned to the captured timestamps, so:

  * the phase-2 evidence (mtil.csv / skipped.csv) can accumulate from replayed
    real market days instead of one live session per day, and
  * exit-policy / threshold parameters can be swept across real days to find
    settings that improve ROI without increasing drawdown.

Replay evidence is written to a scratch state dir (never the live paper_state),
so replays can never pollute the live evidence base. Lot sizes come from the
cached NSE_FO symbol master (no auth needed).

Usage:
    python -m institutional_options.replay_lab --session paper_state/sessions/20260813_093022.jsonl.gz --out paper_state/replay/run1
    python -m institutional_options.replay_lab --session ... --override exit_management:vol_time_stop_fraction=0.3 --out paper_state/replay/vts
    python -m institutional_options.replay_lab --session ... --sweep exit_management:vol_time_stop_fraction=0|0.2|0.35 --sweep exit_management:stop_exit_slippage_frac=0|0.1 --out paper_state/replay/sweep
"""
from __future__ import annotations

import argparse
import gzip
import itertools
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional
from unittest import mock

from .config import SystemConfig
from .fyers_client import FyersSymbolMaster
from .paper_evidence import build_evidence_report
from .paper_runner import PaperRunner

EMPTY_PAYLOAD = {"s": "ok", "data": {"optionsChain": []}}


def iter_capture(path: str | Path):
    """Yield each captured cycle dict from a sessions/*.jsonl.gz file."""
    with gzip.open(str(path), "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


class SessionReplayClient:
    """Fakes the Fyers client API using captured payloads, one cycle at a time.

    The runner calls ``option_chain`` for every underlying each cycle in
    universe order, then ``history``. The client serves the current cycle's
    records and advances to the next cycle once every universe symbol has been
    consumed. ``history`` is never cached by the runner in replay mode, so each
    cycle sees the captured candles for that cycle.
    """

    def __init__(self, records: list[dict], universe_symbols: list[str]):
        self.records = records
        self.universe_symbols = list(universe_symbols)
        self._cycle = 0
        self._served: set[str] = set()
        self.cycles_run = 0

    def _current(self) -> dict:
        return self.records[min(self._cycle, len(self.records) - 1)]

    def option_chain(self, symbol: str, strikecount: int = 30,
                     expiry_timestamp: str = "", header: str = "") -> Any:
        # Advance only when a symbol repeats (start of a new cycle). This keeps
        # the runner's per-cycle sequence option_chain(A), history(A),
        # option_chain(B), history(B) reading the SAME cycle's records.
        if self._served and symbol in self._served:
            self._cycle += 1
            self._served.clear()
        rec = self._current()
        self._served.add(symbol)
        self.cycles_run = self._cycle
        return rec.get("chains", {}).get(symbol) or EMPTY_PAYLOAD

    def history(self, symbol: str, resolution: str = "1", range_from: str = "",
                range_to: str = "", cont_flag: str = "1", header: str = "") -> Any:
        rec = self._current()
        return rec.get("history", {}).get(symbol) or []

    def market_depth(self, symbol: str, ohlcv_flag: int | str = 1, header: str = "") -> Any:
        """Return captured depth or an explicit fail-closed legacy error."""
        rec = self._current()
        depth = rec.get("depth", {})
        if isinstance(depth, Mapping) and symbol in depth:
            return depth[symbol]
        return {"s": "error", "message": "Captured depth unavailable for symbol"}

    def fetch_symbol_master(self, output_path: str | Path) -> Path:
        # Master is injected by replay_session; never re-download.
        p = Path(output_path)
        if p.exists():
            return p
        raise RuntimeError("replay mode requires an injected symbol master")


class _ReplayClock:
    """Mutable now_ist() replacement; the driver advances it per cycle."""

    def __init__(self) -> None:
        self.t = datetime(2026, 1, 1, 10, 0)

    def __call__(self):
        return self.t


def load_runner_cfg(base: Optional[Mapping[str, Any]] = None,
                    overrides: Optional[Mapping[str, Any]] = None) -> dict:
    cfg = dict(base) if base is not None else {}
    if overrides:
        cfg = {**cfg, **overrides}
    return cfg


def replay_session(session_path: str | Path,
                   runner_cfg: Optional[Mapping[str, Any]] = None,
                   state_dir: str | Path = "paper_state/replay/run",
                   master_path: Optional[str | Path] = None,
                   config: Optional[SystemConfig] = None,
                   master: Optional[FyersSymbolMaster] = None) -> PaperRunner:
    """Replay one captured session through the real pipeline into ``state_dir``.

    Returns the runner; its ``snapshot()`` holds the session outcome and the
    phase-2 evidence files (mtil.csv / skipped.csv) live in ``state_dir``.
    """
    session_path = Path(session_path)
    if not session_path.exists():
        raise FileNotFoundError(f"capture file not found: {session_path}")
    records = list(iter_capture(session_path))
    if not records:
        raise ValueError(f"empty capture file: {session_path}")
    # Universe symbols are the chains captured in the first cycle.
    first = records[0].get("chains", {})
    symbols = list(first.keys())
    if not symbols:
        raise ValueError("capture has no chains in its first cycle")

    cfg = SystemConfig.from_file("uploads/PARAMETERS.json") if config is None else config
    runner_cfg = dict(runner_cfg or {})
    runner_cfg.setdefault("poll_seconds", 0.01)
    # Replay must never write into the live paper_state evidence files.
    out = Path(state_dir)
    out.mkdir(parents=True, exist_ok=True)

    if master is None:
        if master_path is None:
            # Prefer the live cached master (gitignored, downloaded without auth).
            candidate = Path("paper_state/NSE_FO.csv")
            master_path = candidate if candidate.exists() else None
        if master_path is None:
            raise FileNotFoundError(
                "no cached NSE_FO symbol master found; pass --master or run the live "
                "runner once to download paper_state/NSE_FO.csv")
        master = FyersSymbolMaster.from_csv(master_path)

    client = SessionReplayClient(records, symbols)
    runner = PaperRunner(cfg, runner_cfg, state_dir=out, client=client,
                         master=master, replay=True)
    clock = _ReplayClock()
    with mock.patch("institutional_options.paper_runner.now_ist", new=clock):
        for rec in records:
            try:
                clock.t = datetime.fromisoformat(rec["ts"])
            except (KeyError, TypeError, ValueError):
                clock.t = datetime(2026, 1, 1, 10, 0)
            runner.run_one_cycle()
    return runner


def _parse_override(spec: str) -> tuple[str, str, Any]:
    section, _, rest = spec.partition(":")
    key, _, value = rest.partition("=")
    if not section or not key or not value:
        raise ValueError(f"override must be section:key=value, got {spec!r}")
    try:
        parsed: Any = json.loads(value)
    except json.JSONDecodeError:
        parsed = value
    return section.strip(), key.strip(), parsed


def _merge_override(cfg: dict, section: str, key: str, value: Any) -> dict:
    cfg = dict(cfg)
    overrides = dict(cfg.get("config_overrides", {}))
    sec = dict(overrides.get(section, {}))
    sec[key] = value
    overrides[section] = sec
    cfg["config_overrides"] = overrides
    return cfg


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Replay captured paper sessions and sweep parameters")
    ap.add_argument("--session", required=True, help="path to a sessions/*.jsonl.gz capture")
    ap.add_argument("--out", default="paper_state/replay/run", help="scratch state dir for the run")
    ap.add_argument("--master", default=None, help="path to a cached NSE_FO.csv (default: paper_state/NSE_FO.csv)")
    ap.add_argument("--override", action="append", default=[], metavar="section:key=value",
                    help="single config override (repeatable)")
    ap.add_argument("--sweep", action="append", default=[], metavar="section:key=v1|v2|v3",
                    help="sweep a parameter over | separated values (repeatable; cartesian)")
    ap.add_argument("--report", action="store_true", help="write evidence_report.txt into each run dir")
    args = ap.parse_args(argv)

    base = json.loads(Path("uploads/PAPER_RUNNER.json").read_text(encoding="utf-8"))

    singles = {_parse_override(o) for o in args.override}
    sweeps = [_parse_sweep(s) for s in args.sweep]

    combos: list[list[tuple[str, str, Any]]] = [list(singles)]
    if sweeps:
        combos = [list(singles) + list(chosen)
                  for chosen in itertools.product(*sweeps)]

    for i, combo in enumerate(combos):
        out = Path(args.out) if len(combos) == 1 else Path(args.out) / f"run_{i}"
        cfg = base
        for section, key, value in combo:
            cfg = _merge_override(cfg, section, key, value)
        runner = replay_session(args.session, runner_cfg=cfg, state_dir=out,
                                master_path=args.master)
        snap = runner.snapshot()
        n_trades = len(snap.get("closed_trades", []))
        print(f"[{i}] {out}: cycles={client_cycles(runner)} trades={n_trades} "
              f"realized_pnl={snap.get('realized_pnl'):+.2f}")
        if args.report:
            try:
                text = build_evidence_report(out)
                report = out / "evidence_report.txt"
                report.write_text(text, encoding="utf-8")
                print(f"    report -> {report}")
            except Exception as e:
                print(f"    report failed: {e}")
    return 0


def _parse_sweep(spec: str) -> list[tuple[str, str, Any]]:
    section, _, rest = spec.partition(":")
    key, _, values = rest.partition("=")
    if not section or not key or not values:
        raise ValueError(f"sweep must be section:key=v1|v2, got {spec!r}")
    out = []
    for v in values.split("|"):
        try:
            parsed: Any = json.loads(v)
        except json.JSONDecodeError:
            parsed = v
        out.append((section.strip(), key.strip(), parsed))
    return out


def client_cycles(runner: PaperRunner) -> int:
    client = getattr(runner, "client", None)
    return getattr(client, "cycles_run", 0)


if __name__ == "__main__":
    raise SystemExit(main())
