from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import Base, async_session, engine
from app.migrations import migrate_schema
from app.routers import auth, billing, subscriptions, tasks, users, workflow
from app.services import seed_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await migrate_schema(conn)
    async with async_session() as db:
        await seed_database(db)
    yield
    await engine.dispose()


app = FastAPI(title="SprintMind SaaS API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(tasks.router)
app.include_router(workflow.router)
app.include_router(users.router)
app.include_router(subscriptions.router)
app.include_router(billing.router)


@app.get("/api/health")
async def health():
    import shutil
    from pathlib import Path

    from app.workflow.repo_analysis import resolve_project_root

    root = resolve_project_root()
    magento = {
        "project_path": settings.magento_project_path or None,
        "mounted": str(root) if root else None,
        "git_available": shutil.which("git") is not None,
        "git_create_branch": settings.magento_git_create_branch,
        "git_base_branch": settings.magento_git_base_branch,
    }
    if root and shutil.which("git"):
        import subprocess
        proc = subprocess.run(
            ["git", "-c", f"safe.directory={root.resolve()}", "branch", "--show-current"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        magento["current_branch"] = (proc.stdout or "").strip() or None

    return {"status": "ok", "service": "sprintmind-api", "magento": magento}
