"""Workflow execution and DB persistence."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models import Task, TaskStatus, WorkflowRun, WorkflowStatus
from app.workflow.errors import apply_failure_to_state
from app.workflow.graph import build_workflow, initial_state
from app.workflow.steps import STEP_ORDER, WORKFLOW_STEPS

logger = logging.getLogger(__name__)


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _serialize_state(values: dict) -> dict:
    safe = {}
    for k, v in values.items():
        if k == "messages":
            continue
        try:
            json.dumps(v)
            safe[k] = v
        except (TypeError, ValueError):
            safe[k] = str(v)
    return safe


async def get_workflow_for_task(db: AsyncSession, task_id: int, user_id: int) -> WorkflowRun | None:
    result = await db.execute(
        select(WorkflowRun)
        .where(WorkflowRun.task_id == task_id, WorkflowRun.user_id == user_id)
        .order_by(WorkflowRun.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _initial_step_statuses(current_step: str = "parse_requirement") -> dict[str, str]:
    statuses = {step: "pending" for step in STEP_ORDER}
    statuses[current_step] = "running"
    return statuses


async def create_workflow_run(db: AsyncSession, task: Task, user_id: int) -> WorkflowRun:
    thread_id = str(uuid.uuid4())
    run = WorkflowRun(
        task_id=task.id,
        user_id=user_id,
        thread_id=thread_id,
        status=WorkflowStatus.RUNNING,
        current_step="parse_requirement",
        state_json={
            "current_step": "parse_requirement",
            "step_statuses": _initial_step_statuses("parse_requirement"),
        },
    )
    db.add(run)
    task.status = TaskStatus.IN_PROGRESS
    await db.commit()
    await db.refresh(run)
    return run


async def _stream_until_pause(db: AsyncSession, run: WorkflowRun, config: dict) -> None:
    graph = build_workflow()
    while True:
        await db.refresh(run)
        if run.status == WorkflowStatus.CANCELLED:
            return
        snapshot = await graph.aget_state(config)
        if not snapshot.next:
            await _sync_run_from_graph(db, run)
            break
        # Check if any next node is an approval node or if pending_approval exists in state
        if _is_human_pause(snapshot):
            await _sync_run_from_graph(db, run)
            break
        async for _ in graph.astream(None, config=config, stream_mode="values"):
            await db.refresh(run)
            if run.status == WorkflowStatus.CANCELLED:
                return
            await _sync_run_from_graph(db, run)
        snapshot = await graph.aget_state(config)
        if _is_human_pause(snapshot):
            await _sync_run_from_graph(db, run)
            break


async def _persist_run_failure(db: AsyncSession, run: WorkflowRun, exc: Exception) -> None:
    state = dict(run.state_json or {})
    step = state.get("current_step") or run.current_step or "unknown"
    state = apply_failure_to_state(state, step, str(exc))
    run.state_json = _serialize_state(state)
    run.current_step = step
    run.status = WorkflowStatus.FAILED
    task = await db.get(Task, run.task_id)
    if task:
        task.status = TaskStatus.FAILED
    await db.commit()


async def execute_workflow_start(db: AsyncSession, run: WorkflowRun, requirement: dict) -> None:
    task = await db.get(Task, run.task_id)
    if not task:
        return

    from app.workflow.plan_prompts import enrich_requirement

    req = enrich_requirement(requirement)
    run.state_json = {
        **(run.state_json or {}),
        "requirement": req,
        "current_step": "parse_requirement",
    }
    await db.commit()

    graph = build_workflow()
    state = initial_state(run.task_id, run.user_id, run.thread_id, req)
    config = _config(run.thread_id)

    try:
        async for _ in graph.astream(state, config=config, stream_mode="values"):
            await db.refresh(run)
            if run.status == WorkflowStatus.CANCELLED:
                return
            await _sync_run_from_graph(db, run)
        await db.refresh(run)
        if run.status != WorkflowStatus.CANCELLED:
            await _sync_run_from_graph(db, run)
    except Exception as exc:
        logger.exception("Workflow start failed for run %s", run.id)
        await _persist_run_failure(db, run, exc)
        return


async def execute_workflow_resume(
    db: AsyncSession,
    run: WorkflowRun,
    *,
    approved: bool,
    feedback: str = "",
) -> None:
    graph = build_workflow()
    config = _config(run.thread_id)
    decision = {"approved": approved, "feedback": feedback}

    run.status = WorkflowStatus.RUNNING
    await db.commit()

    try:
        await graph.ainvoke(Command(resume=decision), config=config)
        await db.refresh(run)
        if run.status == WorkflowStatus.CANCELLED:
            return
        await _sync_run_from_graph(db, run)
        await _stream_until_pause(db, run, config)
    except Exception as exc:
        logger.exception("Workflow resume failed for run %s", run.id)
        await _persist_run_failure(db, run, exc)
        return


async def stop_workflow_run(db: AsyncSession, run: WorkflowRun) -> WorkflowRun:
    if run.status not in (WorkflowStatus.RUNNING, WorkflowStatus.WAITING_APPROVAL):
        return run

    state = dict(run.state_json or {})
    state.pop("pending_approval", None)
    state["cancelled"] = True
    state["cancel_message"] = "Stopped by user"
    run.state_json = state
    run.status = WorkflowStatus.CANCELLED
    run.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(run)
    return run


def _task_requirement(task: Task) -> dict:
    return {
        "title": task.title,
        "description": task.description,
        "jira_key": task.jira_key,
        "file_path": task.file_path,
        "file_name": task.file_name,
    }


async def stop_workflow(db: AsyncSession, task_id: int, user_id: int) -> WorkflowRun:
    run = await get_workflow_for_task(db, task_id, user_id)
    if not run:
        raise ValueError("No workflow found")
    return await stop_workflow_run(db, run)


async def restart_workflow(
    db: AsyncSession,
    task: Task,
    user_id: int,
) -> tuple[WorkflowRun, dict]:
    existing = await get_workflow_for_task(db, task.id, user_id)
    if existing and existing.status in (WorkflowStatus.RUNNING, WorkflowStatus.WAITING_APPROVAL):
        await stop_workflow_run(db, existing)

    requirement = _task_requirement(task)
    run = await create_workflow_run(db, task, user_id)
    return run, requirement


async def restart_workflow_background(run_id: int, requirement: dict) -> None:
    async with async_session() as db:
        run = await db.get(WorkflowRun, run_id)
        if not run or run.status != WorkflowStatus.RUNNING:
            return
        await execute_workflow_start(db, run, requirement)


async def start_workflow(db: AsyncSession, task: Task, user_id: int) -> WorkflowRun:
    existing = await get_workflow_for_task(db, task.id, user_id)
    if existing and existing.status == WorkflowStatus.WAITING_APPROVAL:
        return existing

    requirement = {
        "title": task.title,
        "description": task.description,
        "jira_key": task.jira_key,
        "file_path": task.file_path,
        "file_name": task.file_name,
    }
    run = await create_workflow_run(db, task, user_id)
    await execute_workflow_start(db, run, requirement)
    return run


async def start_workflow_background(run_id: int, requirement: dict) -> None:
    async with async_session() as db:
        run = await db.get(WorkflowRun, run_id)
        if not run or run.status != WorkflowStatus.RUNNING:
            return
        await execute_workflow_start(db, run, requirement)


async def resume_workflow_background(run_id: int, *, approved: bool, feedback: str = "") -> None:
    async with async_session() as db:
        run = await db.get(WorkflowRun, run_id)
        if not run or run.status == WorkflowStatus.CANCELLED:
            return
        await execute_workflow_resume(db, run, approved=approved, feedback=feedback)


async def resume_workflow(
    db: AsyncSession,
    run: WorkflowRun,
    *,
    approved: bool,
    feedback: str = "",
) -> WorkflowRun:
    await execute_workflow_resume(db, run, approved=approved, feedback=feedback)
    await db.refresh(run)
    return run


def _interrupt_payload(snapshot) -> dict | None:
    """Extract human-approval payload from LangGraph interrupt state."""
    for attr in ("interrupts",):
        items = getattr(snapshot, attr, None) or []
        for item in items:
            value = item.value if hasattr(item, "value") else item
            if isinstance(value, dict) and value.get("gate"):
                return value
    for task in getattr(snapshot, "tasks", None) or ():
        for item in getattr(task, "interrupts", None) or ():
            value = item.value if hasattr(item, "value") else item
            if isinstance(value, dict) and value.get("gate"):
                return value
    return None


def _is_human_pause(snapshot) -> bool:
    """True when the graph is waiting for user input (approval or merge code)."""
    if _interrupt_payload(snapshot):
        return True
    nxt = snapshot.next or ()
    return any("approval" in n for n in nxt) or "merge_code" in nxt


def _plan_approval_payload(plan: dict | None) -> dict | None:
    if not plan:
        return None
    return {
        "gate": "approval_plan",
        "title": "Review Implementation Plan",
        "message": "Review the AI-generated plan before code is written.",
        "data": plan,
    }


async def refresh_workflow_run(db: AsyncSession, run: WorkflowRun) -> WorkflowRun:
    if run.status in (WorkflowStatus.RUNNING, WorkflowStatus.WAITING_APPROVAL):
        await _sync_run_from_graph(db, run)
        await db.refresh(run)
    return run


async def _sync_run_from_graph(db: AsyncSession, run: WorkflowRun) -> None:
    await db.refresh(run)
    if run.status == WorkflowStatus.CANCELLED:
        return

    graph = build_workflow()
    snapshot = await graph.aget_state(_config(run.thread_id))
    values = dict(snapshot.values or {})
    has_checkpoint = bool(values or snapshot.next or snapshot.tasks)

    pending_approval = _interrupt_payload(snapshot)
    if pending_approval:
        values["pending_approval"] = pending_approval
    elif values.get("plan") and snapshot.next and any("approval_plan" in n for n in snapshot.next):
        values["pending_approval"] = _plan_approval_payload(values.get("plan"))

    if not has_checkpoint:
        if run.status in (WorkflowStatus.RUNNING, WorkflowStatus.WAITING_APPROVAL):
            state = dict(run.state_json or {})
            if not state.get("pending_approval") and state.get("plan"):
                state["pending_approval"] = _plan_approval_payload(state.get("plan"))
            if run.status == WorkflowStatus.WAITING_APPROVAL and not state.get("pending_approval"):
                state["session_error"] = "Workflow session lost after API restart — click Restart from Start"
            run.state_json = state
            run.updated_at = datetime.now(UTC)
            await db.commit()
        return

    run.state_json = _serialize_state(values)
    run.current_step = values.get("current_step", run.current_step)

    statuses = dict(values.get("step_statuses") or {})
    current = values.get("current_step") or run.current_step
    if current and statuses.get(current) not in ("completed", "failed"):
        statuses[current] = "running"
        values["step_statuses"] = statuses
        run.state_json = _serialize_state(values)
    run.updated_at = datetime.now(UTC)

    if values.get("finished"):
        run.status = WorkflowStatus.COMPLETED
        task = await db.get(Task, run.task_id)
        if task:
            task.status = TaskStatus.COMPLETED
    elif values.get("cancelled"):
        run.status = WorkflowStatus.CANCELLED
    elif values.get("pending_approval") or _is_human_pause(snapshot):
        run.status = WorkflowStatus.WAITING_APPROVAL
    elif any(v == "failed" for v in statuses.values()) and current in statuses and statuses[current] == "failed":
        run.status = WorkflowStatus.FAILED
        task = await db.get(Task, run.task_id)
        if task and task.status == TaskStatus.IN_PROGRESS:
            task.status = TaskStatus.FAILED
    elif snapshot.next:
        run.status = WorkflowStatus.RUNNING
    else:
        run.status = WorkflowStatus.COMPLETED

    await db.commit()
    await db.refresh(run)


def build_workflow_response(run: WorkflowRun) -> dict[str, Any]:
    state = run.state_json or {}
    step_statuses = dict(state.get("step_statuses") or {})
    step_errors_map = dict(state.get("step_errors") or {})
    global_errors = state.get("errors") or []
    current = run.current_step or state.get("current_step")
    waiting = None
    if run.status == WorkflowStatus.WAITING_APPROVAL:
        waiting = state.get("pending_approval") or _plan_approval_payload(state.get("plan"))
    elif state.get("pending_approval"):
        waiting = state.get("pending_approval")

    steps = []
    for step_def in WORKFLOW_STEPS:
        sid = step_def["id"]
        status = step_statuses.get(sid, "pending")
        if waiting and waiting.get("gate") == sid:
            status = "running"
        elif sid == current and status not in ("completed", "failed"):
            status = "running"
        if run.status == WorkflowStatus.COMPLETED and sid == "finished":
            status = "completed"
        if run.status == WorkflowStatus.CANCELLED and sid == current:
            status = "failed"
        step_errs = list(step_errors_map.get(sid) or [])
        if status == "failed" and not step_errs:
            label = step_def["label"]
            prefix = f"{label}: "
            step_errs = [e[len(prefix):] if e.startswith(prefix) else e for e in global_errors if e.startswith(prefix)]
        steps.append({**step_def, "status": status, "errors": step_errs})

    completed = sum(1 for s in steps if s["status"] == "completed")
    running = sum(1 for s in steps if s["status"] == "running")
    progress = int(((completed + running * 0.5) / len(steps)) * 100) if steps else 0

    return {
        "id": run.id,
        "task_id": run.task_id,
        "thread_id": run.thread_id,
        "status": run.status.value,
        "current_step": run.current_step,
        "progress_percent": progress,
        "steps": steps,
        "waiting_approval": waiting,
        "plan": state.get("plan"),
        "plan_revision": state.get("plan_revision", 0),
        "code_artifacts": state.get("code_artifacts"),
        "test_cases": state.get("test_cases"),
        "test_results": state.get("test_results"),
        "staging_deploy": state.get("staging_deploy"),
        "staging_smoke": state.get("staging_smoke"),
        "production_deploy": state.get("production_deploy"),
        "production_smoke": state.get("production_smoke"),
        "merge_request_url": state.get("merge_request_url"),
        "merge_result": state.get("merge_result"),
        "requirement": state.get("requirement"),
        "repo_analysis": state.get("repo_analysis"),
        "git_branch": state.get("git_branch"),
        "cancel_message": state.get("cancel_message"),
        "errors": global_errors,
        "step_errors": step_errors_map,
        "session_error": state.get("session_error"),
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
    }
