from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models import SubscriptionStatus, TaskStatus, UserRole


# ── Auth ──────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    full_name: str = Field(min_length=2)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── User ──────────────────────────────────────────────────────────
class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    full_name: str
    role: UserRole = UserRole.USER
    is_active: bool = True


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = None
    password: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None


# ── Subscription Plan ─────────────────────────────────────────────
class PlanOut(BaseModel):
    id: int
    name: str
    description: str
    price_monthly: int
    max_tasks: int
    max_users: int
    is_active: bool
    stripe_price_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PlanCreate(BaseModel):
    name: str
    description: str = ""
    price_monthly: int = 0
    max_tasks: int = 10
    max_users: int = 1
    is_active: bool = True
    stripe_price_id: str | None = None


class PlanUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price_monthly: int | None = None
    max_tasks: int | None = None
    max_users: int | None = None
    is_active: bool | None = None
    stripe_price_id: str | None = None


class SubscriptionOut(BaseModel):
    id: int
    user_id: int
    plan_id: int
    status: SubscriptionStatus
    starts_at: datetime
    expires_at: datetime | None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    stripe_subscription_id: str | None = None
    plan: PlanOut | None = None

    model_config = {"from_attributes": True}


class SubscriptionAssign(BaseModel):
    user_id: int
    plan_id: int
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    expires_at: datetime | None = None


# ── Task ──────────────────────────────────────────────────────────
class TaskOut(BaseModel):
    id: int
    user_id: int
    title: str
    description: str
    jira_key: str | None
    file_name: str | None
    status: TaskStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskCreate(BaseModel):
    title: str
    description: str = ""
    jira_key: str | None = None


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    jira_key: str | None = None
    status: TaskStatus | None = None


# ── Dashboard ─────────────────────────────────────────────────────
class DashboardStats(BaseModel):
    total_tasks: int
    pending_tasks: int
    in_progress_tasks: int
    completed_tasks: int
    plan_name: str | None = None
    max_tasks: int | None = None
    tasks_remaining: int | None = None
    is_active: bool = True
    can_create_task: bool = True


# ── Billing / Stripe ────────────────────────────────────────────
class StripeConfigOut(BaseModel):
    stripe_enabled: bool
    publishable_key: str | None = None


class BillingStatusOut(BaseModel):
    plan_name: str | None = None
    plan_id: int | None = None
    status: str | None = None
    is_active: bool
    can_create_task: bool
    task_count: int
    max_tasks: int | None = None
    tasks_remaining: int | None = None
    max_users: int | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    stripe_subscription_id: str | None = None


class CheckoutRequest(BaseModel):
    plan_id: int


class CheckoutResponse(BaseModel):
    checkout_url: str | None = None
    activated: bool = False
    session_id: str | None = None
    plan_id: int | None = None


class PortalResponse(BaseModel):
    portal_url: str


class VerifySessionRequest(BaseModel):
    session_id: str


class VerifySessionResponse(BaseModel):
    plan_name: str
    status: str
    message: str = "Subscription activated"
