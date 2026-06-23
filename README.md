# SprintMind — Magento Task SaaS Platform

A subscription-based SaaS platform for managing Magento tasks with **user login**, **role-based access**, **task upload**, and an **admin dashboard** for users, plans, and subscriptions.

Built with **React** (not Streamlit — better suited for multi-user SaaS auth, CRUD, and polished UI) + **FastAPI** + **PostgreSQL**, fully dockerized.

## Features

| Feature | Description |
|---------|-------------|
| User login / register | JWT authentication |
| Task upload | Create tasks with file attachments, saved to DB |
| Per-user task list | Users see only their tasks; admins see all |
| Dashboard | Stats, plan usage, recent tasks |
| Role-based access | `admin` vs `user` roles |
| Admin CRUD | Manage users, subscription plans, assignments |
| Subscription limits | Task limits enforced per plan (blocks at max) |
| **Stripe billing** | Checkout, webhooks, billing portal, plan upgrades |

## Quick start (Docker)

```bash
cp .env.example .env
# Add your Stripe test keys to .env (see Stripe setup below)
docker compose up -d --build
```

Open **http://localhost:3001**

### Demo accounts

| Role | Email | Password |
|------|-------|----------|
| Admin | admin@sprintmind.io | admin123 |
| User | demo@sprintmind.io | demo123 |

## Architecture

```
Browser → React (Nginx :3000) → FastAPI (:8000) → PostgreSQL
                                      ↓
                              File uploads → data/uploads/
```

## API endpoints

| Method | Path | Access | Description |
|--------|------|--------|-------------|
| POST | `/api/auth/register` | Public | Register |
| POST | `/api/auth/login` | Public | Login (OAuth2 form) |
| GET | `/api/auth/me` | Auth | Current user |
| GET | `/api/tasks/dashboard` | Auth | Dashboard stats |
| GET/POST | `/api/tasks` | Auth | List / create tasks |
| POST | `/api/tasks/upload` | Auth | Upload task with file |
| GET/PATCH/DELETE | `/api/tasks/{id}` | Auth | Task CRUD |
| GET/POST/PATCH/DELETE | `/api/users` | Admin | User CRUD |
| GET/POST/PATCH/DELETE | `/api/plans` | Admin/公开 | Plan management |
| GET/POST | `/api/subscriptions` | Admin | Subscription assignments |
| GET | `/api/billing/status` | Auth | Current plan usage & limits |
| POST | `/api/billing/checkout` | Auth | Start Stripe checkout (or activate free plan) |
| POST | `/api/billing/portal` | Auth | Stripe customer portal |
| POST | `/api/billing/webhook` | Stripe | Webhook handler |

## Stripe setup

1. Create a [Stripe account](https://dashboard.stripe.com/register) (test mode).
2. Create **Products** with recurring **Prices** for Pro ($29/mo) and Enterprise ($99/mo).
3. Copy API keys and price IDs into `.env`:

```env
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_PRICE_PRO=price_...
STRIPE_PRICE_ENTERPRISE=price_...
FRONTEND_URL=http://localhost:3001
```

4. Forward webhooks locally:

```bash
stripe listen --forward-to localhost:8000/api/billing/webhook
```

Copy the `whsec_...` secret to `STRIPE_WEBHOOK_SECRET` in `.env`.

### How limits work

| Check | Behavior |
|-------|----------|
| Active subscription | User must have `active` or `trial` status (and valid period) |
| `max_tasks` | Task create/upload blocked when count ≥ plan limit (HTTP 403) |
| No subscription | Task create blocked (HTTP 402) |
| Free plan | Activated instantly without Stripe |
| Paid plan | Redirects to Stripe Checkout; webhook activates subscription |
| Admin | Bypasses all limits |

New users are auto-assigned the **Free** plan (5 tasks) on registration.

## Local development

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
# Start Postgres (or use docker compose up postgres -d)
export DATABASE_URL=postgresql+asyncpg://sprintmind:sprintmind@localhost:5432/sprintmind
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173
```

### Tests

```bash
cd backend
pip install aiosqlite
pytest tests/ -v
```

## Why React over Streamlit?

Streamlit is great for internal data apps but lacks:
- Proper multi-user JWT sessions
- Role-based routing and admin CRUD
- Custom SaaS-grade UI/UX
- Production deployment with Nginx

React + FastAPI is the standard stack for subscription SaaS platforms.

## Project structure

```
SprintMind/
├── docker-compose.yml
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app
│   │   ├── models.py        # User, Task, Plan, Subscription
│   │   ├── auth.py          # JWT + RBAC
│   │   └── routers/         # API routes
│   └── tests/
├── frontend/
│   └── src/
│       ├── pages/           # Login, Dashboard, Tasks, Admin
│       └── components/      # Layout, sidebar
└── docker/nginx/
```

## Subscription plans (seeded)

| Plan | Price | Max Tasks |
|------|-------|-----------|
| Free | $0 | 5 |
| Pro | $29/mo | 50 |
| Enterprise | $99/mo | 500 |

Admins can create/edit plans and assign subscriptions from the admin panel.
