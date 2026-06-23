import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_admin
from app.config import settings
from app.database import get_db
from app.models import Task, TaskStatus, User, UserRole
from app.schemas import DashboardStats, TaskCreate, TaskOut, TaskUpdate
from app.services import dashboard_stats
from app.subscription_service import enforce_task_creation

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

UPLOAD_DIR = Path(settings.upload_dir)


async def _save_upload_file(user: User, file: UploadFile) -> tuple[str, str]:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    user_dir = UPLOAD_DIR / str(user.id)
    user_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}_{file.filename}"
    dest = user_dir / safe_name
    content = await file.read()
    dest.write_bytes(content)
    return file.filename or safe_name, str(dest)


@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    stats = await dashboard_stats(db, user)
    return DashboardStats(**stats)


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    query = select(Task).order_by(Task.created_at.desc())
    if user.role != UserRole.ADMIN:
        query = query.where(Task.user_id == user.id)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(
    body: TaskCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await enforce_task_creation(db, user)
    task = Task(user_id=user.id, title=body.title, description=body.description, jira_key=body.jira_key)
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


@router.post("/upload", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def upload_task(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    title: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
    jira_key: Annotated[str | None, Form()] = None,
    file: UploadFile | None = File(None),
):
    await enforce_task_creation(db, user)

    file_name = None
    file_path = None
    if file and file.filename:
        file_name, file_path = await _save_upload_file(user, file)

    task = Task(
        user_id=user.id,
        title=title,
        description=description,
        jira_key=jira_key or None,
        file_name=file_name,
        file_path=file_path,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    task = await _get_task_or_404(db, task_id, user)
    return task


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: int,
    body: TaskUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    task = await _get_task_or_404(db, task_id, user)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    await db.commit()
    await db.refresh(task)
    return task


@router.patch("/{task_id}/upload", response_model=TaskOut)
async def update_task_with_file(
    task_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    title: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
    jira_key: Annotated[str | None, Form()] = None,
    status: Annotated[str | None, Form()] = None,
    file: UploadFile | None = File(None),
):
    task = await _get_task_or_404(db, task_id, user)
    task.title = title
    task.description = description
    task.jira_key = jira_key or None
    if status:
        try:
            task.status = TaskStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid status") from None

    if file and file.filename:
        file_name, file_path = await _save_upload_file(user, file)
        task.file_name = file_name
        task.file_path = file_path

    await db.commit()
    await db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    task = await _get_task_or_404(db, task_id, user)
    await db.delete(task)
    await db.commit()


async def _get_task_or_404(db: AsyncSession, task_id: int, user: User) -> Task:
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if user.role != UserRole.ADMIN and task.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not allowed")
    return task
