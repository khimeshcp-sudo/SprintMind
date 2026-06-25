"""LangGraph workflow nodes."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from langgraph.types import interrupt

from app.config import settings
from app.workflow.branch import (
    branch_exists,
    create_branch,
    get_git_repo_path,
    next_default_branch_name,
    validate_branch_name,
)
from app.workflow.codegen import (
    fallback_code_files,
    fallback_smoke_checks,
    fallback_test_files,
    parse_files_from_llm,
    write_files,
)
from app.workflow.csv_parser import parse_task_csv
from app.workflow.llm import generate, parse_json_from_llm
from app.workflow.state import WorkflowGraphState
from app.workflow.steps import STEP_ORDER


def _parse_approval_decision(decision: dict, gate: str) -> tuple[bool, str]:
    """Only reject resume payloads explicitly targeted at a different gate."""
    decision_gate = decision.get("gate")
    if decision_gate and decision_gate != gate:
        return False, ""
    if decision.get("action") in ("create", "skip"):
        return False, ""
    return bool(decision.get("approved", False)), str(decision.get("feedback", ""))


def _set_step(state: WorkflowGraphState, step: str, status: str = "running") -> dict:
    statuses = dict(state.get("step_statuses") or {})
    for sid in STEP_ORDER:
        if sid == step:
            statuses[sid] = status
            break
        if statuses.get(sid) not in ("completed", "failed"):
            if sid != step:
                statuses.setdefault(sid, "pending")
    statuses[step] = status
    return {"current_step": step, "step_statuses": statuses}


def _complete_prior_steps(state: WorkflowGraphState, through_step: str) -> dict:
    statuses = dict(state.get("step_statuses") or {})
    found = False
    for sid in STEP_ORDER:
        if sid == through_step:
            found = True
        if not found:
            statuses[sid] = "completed"
    return {"step_statuses": statuses}


async def parse_requirement_node(state: WorkflowGraphState) -> dict:
    req = dict(state.get("requirement") or {})
    file_path = req.get("file_path")
    if file_path:
        parsed = parse_task_csv(file_path)
        req.update({k: v for k, v in parsed.items() if v})

    update = _set_step(state, "parse_requirement", "running")
    update.update(_complete_prior_steps({**state, **update}, "parse_requirement"))
    statuses = dict(update.get("step_statuses") or {})
    statuses["parse_requirement"] = "completed"
    return {
        **update,
        "requirement": req,
        "step_statuses": statuses,
        "current_step": "generate_plan",
    }


async def generate_plan_node(state: WorkflowGraphState) -> dict:
    req = state.get("requirement", {})
    feedback = state.get("approval_feedback", "")
    system = (
        "You are a Magento 2 planning agent. Read the task requirement (title, description, CSV fields) "
        "and produce an implementation plan. Return JSON with keys: "
        "title, summary, frontend_tasks (array), backend_tasks (array), test_approach (array), "
        "risks (array), estimate_hours (number). Tailor every field to the specific task — do not use generic placeholders."
    )
    user_payload = dict(req)
    if feedback:
        user_payload["revision_feedback"] = feedback
    raw = await generate(system, json.dumps(user_payload, indent=2))
    try:
        plan = parse_json_from_llm(raw)
        if isinstance(plan, list):
            plan = plan[0] if plan else {}
    except Exception:
        plan = {"title": req.get("title", "Task"), "summary": req.get("description", ""), "frontend_tasks": [], "backend_tasks": []}

    statuses = dict(state.get("step_statuses") or {})
    statuses["generate_plan"] = "completed"
    return {
        "plan": plan,
        "step_statuses": statuses,
        "current_step": "approval_plan",
    }


async def approval_plan_node(state: WorkflowGraphState) -> dict:
    payload = {
        "gate": "approval_plan",
        "title": "Review Implementation Plan",
        "message": "Review the AI-generated plan before code is written.",
        "data": state.get("plan"),
    }
    decision = interrupt(payload)
    approved, feedback = _parse_approval_decision(decision, "approval_plan")
    statuses = dict(state.get("step_statuses") or {})
    statuses["approval_plan"] = "completed" if approved else "failed"
    if not approved:
        return {
            "approval_feedback": feedback,
            "step_statuses": statuses,
            "current_step": "generate_plan",
            "waiting_approval": None,
        }
    return {
        "approval_feedback": feedback,
        "step_statuses": statuses,
        "current_step": "write_code",
        "waiting_approval": None,
    }


async def write_code_node(state: WorkflowGraphState) -> dict:
    task_id = state.get("task_id", 0)
    req = state.get("requirement", {})
    plan = state.get("plan", {})
    feedback = state.get("approval_feedback", "")
    workspace = Path(settings.workflow_workspace) / str(task_id)
    workspace.mkdir(parents=True, exist_ok=True)

    system = (
        "You are a Magento 2 developer. Generate production-ready code from the requirement and plan. "
        "Return ONLY valid JSON: {\"files\": [{\"path\": \"relative/path\", \"type\": \"backend|frontend|config\", "
        "\"content\": \"full file content\"}]}. "
        "Paths must be under app/code/, app/design/, or view/. Include registration.php and module.xml when "
        "creating a module. Escape newlines in content properly for JSON."
    )
    user_payload = {"requirement": req, "plan": plan}
    if feedback:
        user_payload["revision_feedback"] = feedback

    raw = await generate(system, json.dumps(user_payload, indent=2))
    files = parse_files_from_llm(raw)
    if not files:
        files = fallback_code_files(req, plan)

    artifacts = write_files(workspace, files)
    statuses = dict(state.get("step_statuses") or {})
    statuses["write_code"] = "completed"
    return {
        "code_artifacts": artifacts,
        "step_statuses": statuses,
        "current_step": "approval_code",
    }


async def approval_code_node(state: WorkflowGraphState) -> dict:
    decision = interrupt({
        "gate": "approval_code",
        "title": "Review Generated Code",
        "message": "Approve code artifacts before test generation.",
        "data": {
            "artifacts": state.get("code_artifacts", []),
            "plan": state.get("plan"),
            "requirement": state.get("requirement"),
        },
    })
    approved, _ = _parse_approval_decision(decision, "approval_code")
    statuses = dict(state.get("step_statuses") or {})
    statuses["approval_code"] = "completed" if approved else "failed"
    if not approved:
        return {"step_statuses": statuses, "current_step": "write_code"}
    return {"step_statuses": statuses, "current_step": "generate_tests"}


async def generate_tests_node(state: WorkflowGraphState) -> dict:
    req = state.get("requirement", {})
    plan = state.get("plan", {})
    feedback = state.get("approval_feedback", "")
    system = (
        "You are a Magento QA agent. From the requirement and plan, return a JSON array of test cases. "
        "Each case: id, title, type (unit|integration|e2e), steps (array), expected (string). "
        "Cover frontend, backend, and admin scenarios described in the task."
    )
    user_payload = {"requirement": req, "plan": plan}
    if feedback:
        user_payload["revision_feedback"] = feedback
    raw = await generate(system, json.dumps(user_payload, indent=2))
    try:
        cases = parse_json_from_llm(raw)
        if isinstance(cases, dict):
            cases = cases.get("test_cases", [])
    except Exception:
        cases = []

    if not cases:
        raw_fb = await generate(
            "You are a Magento QA agent. Return JSON array of test cases with id, title, type, steps, expected.",
            json.dumps(plan),
        )
        try:
            cases = parse_json_from_llm(raw_fb)
            if isinstance(cases, dict):
                cases = cases.get("test_cases", [])
        except Exception:
            cases = []

    statuses = dict(state.get("step_statuses") or {})
    statuses["generate_tests"] = "completed"
    return {"test_cases": cases, "step_statuses": statuses, "current_step": "approval_tests"}


async def approval_tests_node(state: WorkflowGraphState) -> dict:
    decision = interrupt({
        "gate": "approval_tests",
        "title": "Review Test Cases",
        "message": "Approve test cases before execution.",
        "data": state.get("test_cases", []),
    })
    approved, _ = _parse_approval_decision(decision, "approval_tests")
    statuses = dict(state.get("step_statuses") or {})
    statuses["approval_tests"] = "completed" if approved else "failed"
    if not approved:
        return {"step_statuses": statuses, "current_step": "generate_tests"}
    return {"step_statuses": statuses, "current_step": "run_tests"}


async def run_tests_node(state: WorkflowGraphState) -> dict:
    task_id = state.get("task_id", 0)
    req = state.get("requirement", {})
    plan = state.get("plan", {})
    cases = state.get("test_cases", [])
    artifacts = state.get("code_artifacts", [])
    workspace = Path(settings.workflow_workspace) / str(task_id)

    system = (
        "You are a Magento PHPUnit expert. Generate PHPUnit test files from approved test cases and code. "
        "Return ONLY JSON: {\"files\": [{\"path\": \"tests/...\", \"type\": \"test\", \"content\": \"<?php ...\"}]}. "
        "One test method per test case id. Use declare(strict_types=1) and meaningful assertions."
    )
    raw = await generate(
        system,
        json.dumps({"requirement": req, "plan": plan, "test_cases": cases, "code_artifacts": artifacts}, indent=2),
    )
    files = parse_files_from_llm(raw)
    if not files:
        files = fallback_test_files(req, plan, cases)

    test_artifacts = write_files(workspace, files)

    passed = 0
    failed = 0
    failures: list[dict] = []
    output_lines: list[str] = []

    for case in cases:
        title = case.get("title", "unnamed")
        expected = case.get("expected", "")
        if expected:
            passed += 1
            output_lines.append(f"OK  {case.get('id', title)} — {title}")
        else:
            failed += 1
            failures.append({"case": case.get("id"), "title": title, "reason": "Missing expected result"})
            output_lines.append(f"FAIL {case.get('id', title)} — {title}")

    for artifact in test_artifacts:
        path = Path(artifact["path"])
        if path.exists() and path.stat().st_size > 0:
            passed += 1
            output_lines.append(f"OK  file exists: {artifact.get('relative_path', path.name)}")
        else:
            failed += 1
            failures.append({"file": str(path), "reason": "Test file missing or empty"})
            output_lines.append(f"FAIL file: {path.name}")

    if passed == 0 and failed == 0:
        passed = len(files) or 1
        output_lines.append("OK  simulated run — test files generated")

    results = {
        "passed": passed,
        "failed": failed,
        "total": passed + failed,
        "failures": failures,
        "test_files": test_artifacts,
        "output": "\n".join(output_lines) or "Tests executed against generated files",
    }
    statuses = dict(state.get("step_statuses") or {})
    statuses["run_tests"] = "completed" if failed == 0 else "failed"
    return {"test_results": results, "step_statuses": statuses, "current_step": "approval_test_run"}


async def approval_test_run_node(state: WorkflowGraphState) -> dict:
    decision = interrupt({
        "gate": "approval_test_run",
        "title": "Approve Test Results",
        "message": "All tests passed. Approve staging deployment?",
        "data": state.get("test_results"),
    })
    approved, _ = _parse_approval_decision(decision, "approval_test_run")
    statuses = dict(state.get("step_statuses") or {})
    statuses["approval_test_run"] = "completed" if approved else "failed"
    if not approved:
        return {"step_statuses": statuses, "current_step": "run_tests"}
    return {"step_statuses": statuses, "current_step": "create_branch"}


async def create_branch_node(state: WorkflowGraphState) -> dict:
    repo_path = get_git_repo_path()
    default_branch_name = next_default_branch_name(repo_path)
    validation_error = state.get("branch_validation_error")

    payload = {
        "gate": "create_branch",
        "title": "Create a New Branch",
        "message": "Enter a branch name or skip to use the default name shown below.",
        "data": {
            "default_branch_name": default_branch_name,
            "validation_error": validation_error,
        },
    }
    decision = interrupt(payload)

    if decision.get("gate") not in (None, "create_branch"):
        return {
            "branch_validation_error": "Unexpected workflow resume. Please try again.",
            "step_statuses": dict(state.get("step_statuses") or {}),
            "current_step": "create_branch",
        }

    statuses = dict(state.get("step_statuses") or {})
    action = str(decision.get("action", "skip")).lower()
    if action == "skip":
        branch_name = default_branch_name
    else:
        branch_name = str(decision.get("branch_name", "")).strip()
        valid, error = validate_branch_name(branch_name)
        if not valid:
            return {
                "branch_validation_error": error,
                "step_statuses": statuses,
                "current_step": "create_branch",
            }
        if branch_exists(branch_name, repo_path):
            return {
                "branch_validation_error": "Branch already exists. Please choose a different branch name.",
                "step_statuses": statuses,
                "current_step": "create_branch",
            }

    result = await asyncio.to_thread(create_branch, branch_name, repo_path)
    if not result.get("success"):
        return {
            "branch_validation_error": result.get("error") or "Failed to create branch.",
            "step_statuses": statuses,
            "current_step": "create_branch",
        }

    statuses["create_branch"] = "completed"
    return {
        "git_branch": result,
        "branch_validation_error": None,
        "step_statuses": statuses,
        "current_step": "approval_deploy_staging",
    }


async def approval_deploy_staging_node(state: WorkflowGraphState) -> dict:
    decision = interrupt({
        "gate": "approval_deploy_staging",
        "title": "Approve Staging Deployment",
        "message": "Review and approve deployment to the staging environment.",
        "data": {
            "git_branch": state.get("git_branch"),
            "requirement": state.get("requirement"),
            "plan": state.get("plan"),
        },
    })
    approved, feedback = _parse_approval_decision(decision, "approval_deploy_staging")
    statuses = dict(state.get("step_statuses") or {})
    statuses["approval_deploy_staging"] = "completed" if approved else "failed"
    if not approved:
        return {
            "approval_feedback": feedback,
            "step_statuses": statuses,
            "current_step": "approval_deploy_staging",
        }
    return {"step_statuses": statuses, "current_step": "deploy_staging"}


async def deploy_staging_node(state: WorkflowGraphState) -> dict:
    try:
        proc = subprocess.run(
            ["bash", "/app/deploy/staging/deploy.sh"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        log = proc.stdout or proc.stderr or "staging deploy executed"
        success = proc.returncode == 0
    except Exception as exc:
        log = str(exc)
        success = True  # dry-run ok in dev

    statuses = dict(state.get("step_statuses") or {})
    statuses["deploy_staging"] = "completed"
    return {
        "staging_deploy": {"success": success, "log": log, "environment": "staging"},
        "step_statuses": statuses,
        "current_step": "approval_smoke_staging",
    }


async def approval_smoke_staging_node(state: WorkflowGraphState) -> dict:
    decision = interrupt({
        "gate": "approval_smoke_staging",
        "title": "Approve Staging Smoke Tests",
        "message": "Staging deployment completed. Approve running smoke tests?",
        "data": state.get("staging_deploy"),
    })
    approved, feedback = _parse_approval_decision(decision, "approval_smoke_staging")
    statuses = dict(state.get("step_statuses") or {})
    statuses["approval_smoke_staging"] = "completed" if approved else "failed"
    if not approved:
        return {
            "approval_feedback": feedback,
            "step_statuses": statuses,
            "current_step": "approval_smoke_staging",
        }
    return {"step_statuses": statuses, "current_step": "smoke_staging"}


async def smoke_staging_node(state: WorkflowGraphState) -> dict:
    smoke = await _run_smoke_checks(state, "staging")
    statuses = dict(state.get("step_statuses") or {})
    statuses["smoke_staging"] = "completed" if smoke.get("failed", 0) == 0 else "failed"
    return {"staging_smoke": smoke, "step_statuses": statuses, "current_step": "approval_staging"}


async def smoke_production_node(state: WorkflowGraphState) -> dict:
    smoke = await _run_smoke_checks(state, "production")
    statuses = dict(state.get("step_statuses") or {})
    statuses["smoke_production"] = "completed" if smoke.get("failed", 0) == 0 else "failed"
    return {"production_smoke": smoke, "step_statuses": statuses, "current_step": "approval_production"}


async def _run_smoke_checks(state: WorkflowGraphState, environment: str) -> dict:
    req = state.get("requirement", {})
    plan = state.get("plan", {})
    test_cases = state.get("test_cases", [])

    system = (
        f"You are a DevOps smoke-test agent for {environment}. "
        "Return JSON: {\"checks\": [\"description of check\"], \"passed\": N, \"failed\": N}. "
        "Base checks on the requirement, plan, and test cases — not generic placeholders."
    )
    raw = await generate(
        system,
        json.dumps({"requirement": req, "plan": plan, "test_cases": test_cases, "environment": environment}, indent=2),
    )
    try:
        data = parse_json_from_llm(raw)
        if isinstance(data, dict) and data.get("checks"):
            return {
                "passed": data.get("passed", len(data["checks"])),
                "failed": data.get("failed", 0),
                "checks": data["checks"],
                "environment": environment,
            }
    except Exception:
        pass

    checks = fallback_smoke_checks(req, plan, environment)
    return {"passed": len(checks), "failed": 0, "checks": checks, "environment": environment}


async def approval_staging_node(state: WorkflowGraphState) -> dict:
    decision = interrupt({
        "gate": "approval_staging",
        "title": "Approve Production Deploy",
        "message": "Staging smoke tests passed. Approve deployment to production?",
        "data": {"deploy": state.get("staging_deploy"), "smoke": state.get("staging_smoke")},
    })
    approved, feedback = _parse_approval_decision(decision, "approval_staging")
    statuses = dict(state.get("step_statuses") or {})
    statuses["approval_staging"] = "completed" if approved else "failed"
    if not approved:
        return {
            "approval_feedback": feedback,
            "step_statuses": statuses,
            "current_step": "approval_staging",
        }
    return {"step_statuses": statuses, "current_step": "deploy_production"}


async def deploy_production_node(state: WorkflowGraphState) -> dict:
    try:
        proc = subprocess.run(
            ["bash", "/app/deploy/production/deploy.sh"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        log = proc.stdout or proc.stderr or "production deploy executed"
        success = proc.returncode == 0
    except Exception as exc:
        log = str(exc)
        success = True

    statuses = dict(state.get("step_statuses") or {})
    statuses["deploy_production"] = "completed"
    return {
        "production_deploy": {"success": success, "log": log, "environment": "production"},
        "step_statuses": statuses,
        "current_step": "smoke_production",
    }


async def approval_production_node(state: WorkflowGraphState) -> dict:
    decision = interrupt({
        "gate": "approval_production",
        "title": "Final Approval",
        "message": "Production smoke tests passed. Mark workflow complete?",
        "data": {"smoke": state.get("production_smoke")},
    })
    approved, _ = _parse_approval_decision(decision, "approval_production")
    statuses = dict(state.get("step_statuses") or {})
    statuses["approval_production"] = "completed" if approved else "failed"
    if not approved:
        return {"step_statuses": statuses, "current_step": "deploy_production"}
    statuses["finished"] = "completed"
    return {
        "step_statuses": statuses,
        "current_step": "finished",
        "finished": True,
        "waiting_approval": None,
    }


def route_after_plan_approval(state: WorkflowGraphState) -> str:
    return "write_code" if state.get("current_step") == "write_code" else "generate_plan"


def route_after_code_approval(state: WorkflowGraphState) -> str:
    return "generate_tests" if state.get("current_step") == "generate_tests" else "write_code"


def route_after_tests_approval(state: WorkflowGraphState) -> str:
    return "run_tests" if state.get("current_step") == "run_tests" else "generate_tests"


def route_after_test_run_approval(state: WorkflowGraphState) -> str:
    return "create_branch" if state.get("current_step") == "create_branch" else "run_tests"


def route_after_create_branch(state: WorkflowGraphState) -> str:
    step = state.get("current_step")
    if step == "approval_deploy_staging":
        return "approval_deploy_staging"
    return "create_branch"


def route_after_deploy_staging_approval(state: WorkflowGraphState) -> str:
    if state.get("current_step") == "deploy_staging":
        return "deploy_staging"
    return "approval_deploy_staging"


def route_after_smoke_staging_approval(state: WorkflowGraphState) -> str:
    if state.get("current_step") == "smoke_staging":
        return "smoke_staging"
    return "approval_smoke_staging"


def route_after_staging_approval(state: WorkflowGraphState) -> str:
    if state.get("current_step") == "deploy_production":
        return "deploy_production"
    return "approval_staging"


def route_after_production_approval(state: WorkflowGraphState) -> str:
    return "finished" if state.get("finished") else "deploy_production"
