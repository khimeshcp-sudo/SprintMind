"""LangGraph workflow state."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class WorkflowGraphState(TypedDict, total=False):
    task_id: int
    user_id: int
    thread_id: str
    requirement: dict
    plan: dict
    repo_analysis: dict
    git_branch: dict
    code_artifacts: list[dict]
    test_cases: list[dict]
    test_results: dict
    staging_deploy: dict
    staging_smoke: dict
    production_deploy: dict
    production_smoke: dict
    current_step: str
    step_statuses: dict[str, str]
    waiting_approval: dict | None
    approval_feedback: str
    errors: Annotated[list[str], operator.add]
    finished: bool
