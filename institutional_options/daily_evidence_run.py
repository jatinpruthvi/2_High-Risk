"""Daily phase-2 evidence run: tests -> report -> dated archive.

Run once each evening after the market closes (or from Task Scheduler /
cron) to refresh the dry-run acceptance checklist against the accumulated
paper-session evidence:

    python institutional_options/daily_evidence_run.py

Steps:
  1. Run the full test suite. The phase-2 gate's `emergency_tests_passed`
     check is set from the test result (all green => passed; any failure =>
     the report shows the check FAIL, which is the honest state).
  2. Regenerate paper_state/evidence_report.txt from the accumulated
     paper_state/mtil.csv + paper_state/skipped.csv.
  3. Archive a dated copy under paper_state/reports/ so the checklist can
     be reviewed historically.

Exit codes: 0 = report written (gate may still be FAIL - that is expected
while evidence accumulates), 2 = test suite failed (report still written).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run_tests() -> bool:
    """Run the project test suite; return True only if everything passed."""
    print("[daily] running test suite ...", flush=True)
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-8:])
    print(tail, flush=True)
    return result.returncode == 0


def generate_report(state_dir: Path, emergency_passed: bool) -> Path:
    """Rebuild the evidence report via paper_evidence.build_evidence_report and
    the per-day top-N candidates report (threshold-calibration aid)."""
    import institutional_options.paper_evidence as ev
    text = ev.build_evidence_report(state_dir, emergency_tests_passed=emergency_passed)
    out = state_dir / "evidence_report.txt"
    out.write_text(text, encoding="utf-8")
    print(f"[daily] report written: {out}", flush=True)
    top = state_dir / "top_candidates_report.txt"
    top.write_text(ev.build_top_candidates_report(state_dir), encoding="utf-8")
    print(f"[daily] top-candidates report written: {top}", flush=True)
    return out


def archive_report(state_dir: Path, source: Path) -> Path:
    """Copy today's report into a dated archive folder."""
    reports = state_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = reports / f"evidence_report_{stamp}.txt"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"[daily] archived: {target}", flush=True)
    top_src = state_dir / "top_candidates_report.txt"
    if top_src.exists():
        top_target = reports / f"top_candidates_{stamp}.txt"
        top_target.write_text(top_src.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"[daily] archived: {top_target}", flush=True)
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description="Daily phase-2 evidence run")
    ap.add_argument("--state-dir", default="paper_state")
    ap.add_argument("--skip-tests", action="store_true",
                    help="Skip the test-suite step (marks emergency tests as NOT passed)")
    args = ap.parse_args()

    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    if args.skip_tests:
        tests_ok = False
        print("[daily] skipping test suite (--skip-tests); emergency gate = FAIL", flush=True)
    else:
        tests_ok = run_tests()

    report = generate_report(state_dir, emergency_passed=tests_ok)
    archive_report(state_dir, report)

    if not tests_ok:
        print("[daily] TEST SUITE FAILED - emergency_tests_passed check is FAIL.", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
