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
    return {"status": "ok", "service": "sprintmind-api"}
