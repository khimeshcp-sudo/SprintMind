"""LangGraph workflow state."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from app.workflow.errors import merge_step_errors


class WorkflowGraphState(TypedDict, total=False):
    task_id: int
    user_id: int
    thread_id: str
    requirement: dict
    plan: dict
    plan_revision: int
    repo_analysis: dict
    git_branch: dict
    code_artifacts: list[dict]
    module_identity: dict
    test_cases: list[dict]
    test_results: dict
    staging_deploy: dict
    staging_smoke: dict
    production_deploy: dict
    production_smoke: dict
    merge_request_id: str | int
    merge_request_url: str
    merge_result: dict
    current_step: str
    step_statuses: dict[str, str]
    waiting_approval: dict | None
    approval_feedback: str
    errors: Annotated[list[str], operator.add]
    step_errors: Annotated[dict[str, list[str]], merge_step_errors]
    finished: bool
