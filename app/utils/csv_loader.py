from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from app.core.domain_errors import NotFoundError, ValidationError
from app.core.error_codes import ErrorCode


def read_ads_rows(csv_path: Path) -> Iterable[dict[str, str]]:
    if not csv_path.exists():
        raise NotFoundError(f"CSV file not found: {csv_path}", code=ErrorCode.CSV_FILE_NOT_FOUND)

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"campaign", "spend", "revenue"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise ValidationError(
                f"CSV must contain columns {sorted(required)}; got {reader.fieldnames}",
                code=ErrorCode.INVALID_CSV_COLUMNS,
            )
        yield from reader

