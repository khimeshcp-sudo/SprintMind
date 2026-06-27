# SprintMind — Magento Task SaaS + AI Workflow

Subscription-based SaaS for managing Magento development tasks with **JWT auth**, **Stripe billing**, and a **LangGraph AI pipeline** that plans, writes Magento 2 module code, runs tests, opens pull requests, and deploys.

**Stack:** React (Vite) + FastAPI + PostgreSQL + LangGraph, fully dockerized.

## Features

| Area | Description |
|------|-------------|
| Auth & roles | Register/login, JWT, `admin` vs `user` |
| Tasks | Create tasks with **required Jira ID** (e.g. `TAR-3111`), CSV/file upload, per-user lists |
| AI workflow | LangGraph pipeline with human approval gates at each stage |
| Code generation | File-by-file Magento 2 module code under `app/code/SprintMind/{Module}/` |
| Git integration | New branch per task (`feature/TAR-3111`), commit, push, **create PR** (no auto-merge) |
| Billing | Stripe checkout, portal, plan limits |
| Admin | Users, plans, subscriptions |

## Quick start (Docker)

```bash
cp .env.example .env
# Edit .env — set LLM keys, MAGENTO_PROJECT_PATH, and Git API token (see below)
docker compose up -d --build
```

| Service | URL |
|---------|-----|
| **App (frontend)** | http://localhost:3001 |
| **API** | http://localhost:8000 |
| **API health** | http://localhost:8000/api/health |
| **pgAdmin** | http://localhost:5050 |
| **PostgreSQL** | `localhost:5432` |

Optional local LLM (Ollama):

```bash
docker compose --profile ai up -d ollama
docker compose exec ollama ollama pull llama3.2:1b
```

### Demo accounts

| Role | Email | Password |
|------|-------|----------|
| Admin | admin@sprintmind.io | admin123 |
| User | demo@sprintmind.io | demo123 |

## AI workflow

Open a task → **Start AI Flow**. The pipeline runs with approval popups between major steps:

1. Read requirement (from task + uploaded CSV)
2. AI planning (markdown plan)
3. **Approve plan**
4. Write code (Magento module, file-by-file)
5. **Approve code**
6. Generate tests → **Approve tests**
7. Run tests → **Approve test results**
8. **Create pull request** (commit, push, open PR — merge manually in GitHub/GitLab)
9. Deploy staging → smoke test → **Approve staging**
10. Deploy production → smoke test → **Approve production**
11. Complete

Errors from any step are shown in the task detail UI (banner + failed step in the pipeline).

### Jira ID & git branches

- **Jira ID is required** on every task (format: `PROJECT-NUMBER`, e.g. `TAR-3111`).
- Git branch name: **`feature/TAR-3111`** (from Jira ID).
- A **new branch is created** when the plan is approved (`MAGENTO_GIT_CREATE_BRANCH=true`).
- If the branch already exists locally, the next free name is used (`feature/TAR-3111-2`, etc.).
- Base branch for new features: `MAGENTO_GIT_BASE_BRANCH` (default `main` in Docker).

## Architecture

```
Browser → React/Nginx (:3001) → FastAPI (:8000) → PostgreSQL
                                      │
                    LangGraph workflow (plan → code → tests → PR → deploy)
                                      │
                    Magento repo (mounted at /app/magento in API container)
                                      │
                    GitHub/GitLab API (create pull request)
```

## Environment variables

Copy `.env.example` to `.env` and configure. Key groups:

### Database & auth

```env
DATABASE_URL=postgresql+asyncpg://sprintmind:sprintmind@postgres:5432/sprintmind
POSTGRES_USER=sprintmind
POSTGRES_PASSWORD=sprintmind
POSTGRES_DB=sprintmind

SECRET_KEY=change-me-to-a-long-random-secret
ACCESS_TOKEN_EXPIRE_MINUTES=1440
```

### API & frontend

```env
API_HOST=0.0.0.0
API_PORT=8000
CORS_ORIGINS=http://localhost:3000,http://localhost:5173,http://localhost:3001
FRONTEND_URL=http://localhost:3001
VITE_API_URL=                    # leave empty in Docker; nginx proxies /api
```

### LLM (AI workflow)

Set `LLM_PROVIDER` to your primary provider. Codegen uses the configured provider first, then falls back to others if keys are set.

```env
LLM_PROVIDER=openai             # openai | groq | gemini | ollama
LLM_TIMEOUT_SECONDS=500

# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1

# Groq (fast, good for dev)
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.1-8b-instant

# Gemini (optional)
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.0-flash-lite

# Ollama (optional — use docker compose --profile ai)
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=llama3.2:1b

# Log LLM prompts/responses: docker compose logs -f api
LLM_DEBUG=true
LLM_DEBUG_FULL=true
```

### Magento project & Git

`MAGENTO_PROJECT_PATH` is your **local** Magento root. Docker mounts it read-write at `/app/magento`.

```env
MAGENTO_PROJECT_PATH=/path/to/your/magento
MAGENTO_GIT_BASE_BRANCH=main
MAGENTO_GIT_CREATE_BRANCH=true

MAGENTO_GIT_USER_NAME=SprintMind Bot
MAGENTO_GIT_USER_EMAIL=sprintmind-bot@users.noreply.github.com

# GitHub: https://api.github.com/repos/OWNER/REPO
# GitLab: https://gitlab.com/api/v4/projects/PROJECT_ID
MAGENTO_GIT_API_BASE_URL=https://api.github.com/repos/your-org/your-repo
MAGENTO_GIT_API_TOKEN=ghp_...          # repo scope for push + PR
```

### Stripe (optional)

```env
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_PRO=price_...
STRIPE_PRICE_ENTERPRISE=price_...
```

Webhook forwarding (local):

```bash
stripe listen --forward-to localhost:8000/api/billing/webhook
```

### pgAdmin

```env
PGADMIN_EMAIL=admin@sprintmind.io
PGADMIN_PASSWORD=admin123
```

## API endpoints (summary)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/register` | Register |
| POST | `/api/auth/login` | Login |
| GET | `/api/auth/me` | Current user |
| GET | `/api/tasks/dashboard` | Dashboard stats |
| GET/POST | `/api/tasks` | List / create tasks (`jira_key` required on create) |
| POST | `/api/tasks/upload` | Create task with file + Jira ID |
| GET/PATCH/DELETE | `/api/tasks/{id}` | Task CRUD |
| POST | `/api/tasks/{id}/workflow/start` | Start AI workflow |
| POST | `/api/tasks/{id}/workflow/resume` | Approve/reject at gate |
| POST | `/api/tasks/{id}/workflow/stop` | Stop workflow |
| POST | `/api/tasks/{id}/workflow/restart` | Restart from beginning |
| GET | `/api/tasks/{id}/workflow` | Workflow status & artifacts |
| GET | `/api/health` | API + Magento mount status |
| GET/POST | `/api/billing/*` | Stripe billing |

## Local development (without full Docker)

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+asyncpg://sprintmind:sprintmind@localhost:5432/sprintmind
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173 — proxies API to :8000
```

### Postgres only

```bash
docker compose up -d postgres
```

## Project structure

```
SprintMind/
├── docker-compose.yml
├── .env / .env.example
├── data/
│   ├── uploads/          # Task file uploads
│   └── workspace/        # Per-task workspace fallback
├── backend/
│   └── app/
│       ├── main.py
│       ├── config.py
│       ├── jira_utils.py           # Jira ID validation, branch naming
│       ├── models.py
│       ├── routers/                # auth, tasks, workflow, billing, …
│       └── workflow/
│           ├── graph.py            # LangGraph assembly
│           ├── nodes.py            # Pipeline steps
│           ├── codegen.py          # Magento file-by-file generation
│           ├── agent_prompts.py    # LLM system prompts
│           ├── module_context.py   # Module paths, validation
│           └── repo_analysis.py    # Git branch, commit, PR
├── frontend/
│   └── src/
│       ├── pages/                  # Tasks, TaskDetail, Dashboard, …
│       └── components/             # WorkflowProgress, ApprovalModal, …
└── deploy/                         # Staging/production deploy scripts
```

## Subscription plans (seeded)

| Plan | Price | Max tasks |
|------|-------|-----------|
| Free | $0 | 5 |
| Pro | $29/mo | 50 |
| Enterprise | $99/mo | 500 |

Admins bypass task limits. New users get the Free plan on registration.

## Troubleshooting

| Issue | What to check |
|-------|----------------|
| API won't start | `docker compose logs api` — syntax/import errors |
| Write code fails | `LLM_PROVIDER` + API key in `.env`; `docker compose logs api` |
| No Magento files | `MAGENTO_PROJECT_PATH` exists and is mounted; check `/api/health` |
| Git branch fails | Repo is a git checkout; token has push access |
| PR not created | `MAGENTO_GIT_API_BASE_URL` + `MAGENTO_GIT_API_TOKEN` |
| Workflow session lost | Click **Restart from Start** on task detail |

```bash
docker compose up -d --build api frontend
docker compose logs -f api
```
