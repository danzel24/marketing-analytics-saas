from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable


def read_ads_rows(csv_path: Path) -> Iterable[dict[str, str]]:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"campaign", "spend", "revenue"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise ValueError(
                f"CSV must contain columns {sorted(required)}; got {reader.fieldnames}"
            )
        yield from reader

