from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Mapping


class SkippedCandidateWriter:
    def __init__(self, schema_path: str | Path, output_path: str | Path):
        self.schema_path = Path(schema_path)
        self.output_path = Path(output_path)
        with self.schema_path.open("r", encoding="utf-8-sig", newline="") as f:
            self.fields = [row["field"] for row in csv.DictReader(f)]
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.output_path.exists():
            with self.output_path.open("w", encoding="utf-8", newline="") as f:
                csv.DictWriter(f, fieldnames=self.fields, extrasaction="ignore").writeheader()

    def append(self, record: Mapping[str, Any]) -> None:
        row = {field: record.get(field, "") for field in self.fields}
        with self.output_path.open("a", encoding="utf-8", newline="") as f:
            csv.DictWriter(f, fieldnames=self.fields, extrasaction="ignore").writerow(row)
