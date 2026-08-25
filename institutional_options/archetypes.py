from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TradeArchetype:
    code: str
    name: str
    description: str


class TradeArchetypeCatalog:
    def __init__(self, archetypes: list[TradeArchetype]):
        self.archetypes = {a.code: a for a in archetypes}

    @classmethod
    def from_csv(cls, path: str | Path) -> "TradeArchetypeCatalog":
        with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            return cls([TradeArchetype(row["archetype_code"], row["archetype_name"], row["description"]) for row in reader])

    def get(self, code: str) -> TradeArchetype:
        return self.archetypes[code]
