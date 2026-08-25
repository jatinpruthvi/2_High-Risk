from __future__ import annotations

from pathlib import Path

from .config import SystemConfig


def main() -> None:
    cfg_path = Path("uploads/PARAMETERS.json")
    cfg = SystemConfig.from_file(cfg_path)
    universe = cfg.section("instrument_universe")["eligible_underlyings"]
    print("Institutional Options Paper System configuration loaded.")
    print("Universe:", ", ".join(universe))
    print("Live execution: DISABLED")


if __name__ == "__main__":
    main()
