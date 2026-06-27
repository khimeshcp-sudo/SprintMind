"""Jira key validation and git branch naming."""

from __future__ import annotations

import re

JIRA_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")


def normalize_jira_key(value: str | None) -> str:
    return (value or "").strip().upper()


def validate_jira_key(value: str | None) -> str:
    key = normalize_jira_key(value)
    if not key:
        raise ValueError("Jira ID is required (e.g. TAR-3111)")
    if not JIRA_KEY_RE.match(key):
        raise ValueError("Invalid Jira ID — use PROJECT-NUMBER format (e.g. TAR-3111)")
    return key


def branch_name_from_jira(jira_key: str) -> str:
    return f"feature/{validate_jira_key(jira_key)}"
