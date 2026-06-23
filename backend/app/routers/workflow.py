from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Task, User, WorkflowStatus
from app.routers.tasks import _get_task_or_404
from app.workflow.runner import (
    build_workflow_response,
    create_workflow_run,
    get_workflow_for_task,
    resume_workflow_background,
    start_workflow_background,
)
from app.workflow.steps import WORKFLOW_STEPS

router = APIRouter(prefix="/api/tasks", tags=["workflow"])


class WorkflowResumeRequest(BaseModel):
    approved: bool = True
    feedback: str = ""


@router.get("/workflow/steps")
async def list_workflow_steps():
    return WORKFLOW_STEPS


@router.post("/{task_id}/workflow/start")
async def workflow_start(
    task_id: int,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    task = await _get_task_or_404(db, task_id, user)
    existing = await get_workflow_for_task(db, task_id, user.id)
    if existing and existing.status == WorkflowStatus.WAITING_APPROVAL:
        return build_workflow_response(existing)

    requirement = {
        "title": task.title,
        "description": task.description,
        "jira_key": task.jira_key,
        "file_path": task.file_path,
        "file_name": task.file_name,
    }
    run = await create_workflow_run(db, task, user.id)
    background_tasks.add_task(start_workflow_background, run.id, requirement)
    return build_workflow_response(run)


@router.get("/{task_id}/workflow")
async def workflow_status(
    task_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_task_or_404(db, task_id, user)
    run = await get_workflow_for_task(db, task_id, user.id)
    if not run:
        raise HTTPException(status_code=404, detail="No workflow found. Start AI flow first.")
    return build_workflow_response(run)


@router.post("/{task_id}/workflow/resume")
async def workflow_resume(
    task_id: int,
    body: WorkflowResumeRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_task_or_404(db, task_id, user)
    run = await get_workflow_for_task(db, task_id, user.id)
    if not run:
        raise HTTPException(status_code=404, detail="No workflow found")
    if run.status != WorkflowStatus.WAITING_APPROVAL:
        raise HTTPException(status_code=400, detail="Workflow is not waiting for approval")

    run.status = WorkflowStatus.RUNNING
    state = dict(run.state_json or {})
    state.pop("pending_approval", None)
    run.state_json = state
    await db.commit()
    await db.refresh(run)

    background_tasks.add_task(
        resume_workflow_background,
        run.id,
        approved=body.approved,
        feedback=body.feedback,
    )
    return build_workflow_response(run)
