"""Parse task CSV uploads (Jira export format)."""

from __future__ import annotations

import csv
from pathlib import Path


def parse_task_csv(file_path: str | Path) -> dict:
    path = Path(file_path)
    if not path.exists():
        return {}

    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        row = next(reader, None)
        if not row:
            return {}

    # Normalize keys (case-insensitive)
    normalized = {k.strip().lower().replace(" ", "_"): v.strip() for k, v in row.items() if k}

    return {
        "task_id": normalized.get("task_id") or normalized.get("id", ""),
        "title": normalized.get("title", ""),
        "description": normalized.get("description", ""),
        "status": normalized.get("status", ""),
        "raw": row,
    }
