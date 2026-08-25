from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class MTILError(ValueError):
    pass


@dataclass(frozen=True)
class MTILField:
    section: str
    field: str
    type: str
    required: bool
    alpha_value: str
    survivability_value: str
    roi_optimization_value: str
    description: str


class MTILSchema:
    def __init__(self, fields: list[MTILField]):
        self.fields = fields
        self.field_names = [f.field for f in fields]
        self.required = {f.field for f in fields if f.required}

    @classmethod
    def from_csv(cls, path: str | Path) -> "MTILSchema":
        with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields = [
                MTILField(
                    section=row["section"],
                    field=row["field"],
                    type=row["type"],
                    required=row["required"].strip().lower() == "yes",
                    alpha_value=row["alpha_value"],
                    survivability_value=row["survivability_value"],
                    roi_optimization_value=row["roi_optimization_value"],
                    description=row["description"],
                )
                for row in reader
            ]
        return cls(fields)

    def validate_record(self, record: Mapping[str, Any]) -> None:
        missing = [name for name in self.required if record.get(name) in (None, "")]
        if missing:
            raise MTILError(f"MTIL record missing required fields: {sorted(missing)}")


class MTILWriter:
    def __init__(self, schema: MTILSchema, path: str | Path):
        self.schema = schema
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            with self.path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.schema.field_names, extrasaction="ignore")
                writer.writeheader()

    def append(self, record: Mapping[str, Any]) -> None:
        self.schema.validate_record(record)
        row = {name: record.get(name, "") for name in self.schema.field_names}
        with self.path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.schema.field_names, extrasaction="ignore")
            writer.writerow(row)
