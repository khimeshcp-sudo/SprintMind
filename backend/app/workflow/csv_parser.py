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
    normalized = {k.strip().lower().replace(" ", "_"): (v or "").strip() for k, v in row.items() if k}

    description = (
        normalized.get("description")
        or normalized.get("summary")
        or normalized.get("issue_description")
        or normalized.get("details")
        or normalized.get("body")
        or ""
    )
    title = normalized.get("title") or normalized.get("summary") or normalized.get("issue_key", "")

    return {
        "task_id": normalized.get("task_id") or normalized.get("id", ""),
        "title": title,
        "description": description,
        "jira_key": normalized.get("jira_key") or normalized.get("issue_key") or normalized.get("key", ""),
        "status": normalized.get("status", ""),
        "raw": row,
    }
