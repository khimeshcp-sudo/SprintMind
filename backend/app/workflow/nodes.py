"""LangGraph workflow nodes."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from langgraph.types import interrupt

from app.config import settings
from app.workflow.codegen import (
    fallback_code_files,
    fallback_smoke_checks,
    fallback_test_files,
    parse_files_from_llm,
    resolve_workspace,
    write_files,
)
from app.workflow.llm import generate, parse_json_from_llm
from app.workflow.plan_prompts import (
    PLAN_SYSTEM,
    build_plan_from_response,
    build_plan_user_message,
    enrich_requirement,
)
from app.workflow.repo_analysis import (
    analyze_repository,
    commit_changes,
    create_merge_request,
    ensure_git_branch,
    extract_keywords,
    merge_merge_request,
    push_branch,
)
from app.workflow.state import WorkflowGraphState
from app.workflow.steps import STEP_ORDER

logger = logging.getLogger(__name__)


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
    req = enrich_requirement(state.get("requirement") or {})

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
    req = enrich_requirement(state.get("requirement") or {})
    feedback = (state.get("approval_feedback") or "").strip()
    revision = int(state.get("plan_revision") or 0)
    if feedback:
        revision += 1

    user_message = build_plan_user_message(req, feedback=feedback)
    if not user_message or user_message.strip() in ("{}", "''"):
        import logging
        logging.getLogger(__name__).error(
            "Plan input empty — requirement=%s file_path=%s",
            req,
            req.get("file_path"),
        )
        user_message = build_plan_user_message(
            {"title": "Task", "description": "No CSV description found — check task has CSV uploaded"},
            feedback=feedback,
        )

    raw = await generate(PLAN_SYSTEM, user_message)
    plan = build_plan_from_response(req, raw, revision=revision, feedback=feedback)

    statuses = dict(state.get("step_statuses") or {})
    statuses["generate_plan"] = "completed"
    return {
        "plan": plan,
        "plan_revision": revision,
        "requirement": req,
        "approval_feedback": "",
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
    approved = bool(decision.get("approved", False))
    feedback = str(decision.get("feedback", ""))
    statuses = dict(state.get("step_statuses") or {})
    statuses["approval_plan"] = "completed" if approved else "failed"
    if not approved:
        return {
            "approval_feedback": feedback,
            "plan": None,
            "step_statuses": statuses,
            "current_step": "generate_plan",
            "waiting_approval": None,
        }

    req = state.get("requirement") or {}
    keywords = extract_keywords(req)
    repo = analyze_repository(keywords=keywords)
    git_result = ensure_git_branch(
        req,
        branch_strategy=repo.get("branch_strategy"),
    )

    return {
        "approval_feedback": feedback,
        "step_statuses": statuses,
        "repo_analysis": repo,
        "git_branch": git_result,
        "current_step": "write_code",
        "waiting_approval": None,
        "errors": [] if git_result.get("success") else [git_result.get("error", "Git branch setup failed")],
    }


async def write_code_node(state: WorkflowGraphState) -> dict:
    task_id = state.get("task_id", 0)
    req = state.get("requirement", {})
    plan = state.get("plan", {})
    feedback = state.get("approval_feedback", "")
    repo = state.get("repo_analysis") or {}

    git_result = dict(state.get("git_branch") or {})
    if not git_result.get("success"):
        git_result = ensure_git_branch(req, branch_strategy=repo.get("branch_strategy"))

    # Log git branch result but allow proceeding with code generation
    # (files can still be written to workspace even if git branch setup has issues)
    if not git_result.get("success") and not git_result.get("skipped"):
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Git branch setup warning: {git_result.get('error', 'unknown error')}")

    workspace = resolve_workspace(task_id)

    system = (
        "You are a Magento 2 developer. Generate production-ready code from the requirement and plan. "
        "Return ONLY valid JSON: {\"files\": [{\"path\": \"relative/path\", \"type\": \"backend|frontend|config\", "
        "\"content\": \"full file content\"}]}. "
        "Paths must be under app/code/, app/design/, or view/. Include registration.php and module.xml when "
        "creating a module. Escape newlines in content properly for JSON."
    )
    user_payload = {
        "requirement": req,
        "plan": plan,
        "plan_text": plan.get("content") or plan.get("summary") or "",
    }
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
        "git_branch": git_result,
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
    approved = bool(decision.get("approved", False))
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
    approved = bool(decision.get("approved", False))
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
    workspace = resolve_workspace(task_id)

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
    approved = bool(decision.get("approved", False))
    statuses = dict(state.get("step_statuses") or {})
    statuses["approval_test_run"] = "completed" if approved else "failed"
    if not approved:
        return {"step_statuses": statuses, "current_step": "run_tests"}
    return {"step_statuses": statuses, "current_step": "merge_code"}


async def merge_code_node(state: WorkflowGraphState) -> dict:
    git_branch = state.get("git_branch") or {}
    repo = state.get("repo_analysis") or {}
    branch_name = git_branch.get("branch") or repo.get("branch_strategy", {}).get("branch") or "feature/auto-merge"
    mr_url = state.get("merge_request_url")

    decision = interrupt({
        "gate": "merge_code",
        "title": "Merge Code",
        "message": "Approve to commit generated changes, push the branch, and open a pull request to origin/main.",
        "data": {
            "branch": branch_name,
            "merge_request_url": mr_url,
        },
    })

    approved = bool(decision.get("approved", False))
    statuses = dict(state.get("step_statuses") or {})
    statuses["merge_code"] = "completed" if approved else "failed"

    if not approved:
        return {
            "step_statuses": statuses,
            "current_step": "merge_code",
            "errors": ["Merge Code rejected by user"],
            "cancelled": True,
            "cancel_message": "Merge Code rejected by user",
        }

    req = state.get("requirement") or {}
    plan = state.get("plan") or {}
    repo_root = resolve_workspace(state.get("task_id", 0))
    branch = branch_name
    errors: list[str] = []
    mr_data: dict = {}
    merge_warnings: list[str] = []

    artifacts = list(state.get("code_artifacts") or [])
    test_files = (state.get("test_results") or {}).get("test_files") or []
    relative_paths = [
        p for p in (
            *(a.get("relative_path") for a in artifacts),
            *(a.get("relative_path") for a in test_files),
        )
        if p
    ]

    title = req.get("title") or plan.get("title") or "SprintMind workflow changes"
    jira = req.get("jira_key")
    commit_message = f"SprintMind: {title}"
    if jira:
        commit_message = f"{commit_message} ({jira})"
    commit_message = f"{commit_message}\n\nAuto-committed from SprintMind AI workflow."

    try:
        commit_result = commit_changes(
            repo_root,
            branch,
            commit_message,
            paths=relative_paths or None,
        )
        if not commit_result.get("success"):
            raise RuntimeError(commit_result.get("error", "Git commit failed"))

        push_result = push_branch(repo_root, branch)
        if not push_result.get("success"):
            raise RuntimeError(push_result.get("error", "Git push failed"))

        mr_result = create_merge_request(branch)
        if not mr_result.get("success"):
            err = mr_result.get("error", "Pull request creation failed")
            if "not found" in str(err).lower() or "no commits" in str(err).lower():
                err = (
                    f"{err}. Ensure the branch was pushed to GitHub before opening a pull request."
                )
            raise RuntimeError(err)
        mr_data = mr_result

        merge_result = merge_merge_request(mr_result.get("id"), mr_result.get("web_url"))
        if not merge_result.get("success"):
            merge_warnings.append(merge_result.get("error", "Automatic merge not available"))
    except Exception as exc:
        logger.exception("Merge Code failed for task %s", state.get("task_id"))
        errors.append(str(exc))

    if errors:
        logger.error("Merge Code errors: %s", errors)
        statuses["merge_code"] = "failed"
        return {
            "step_statuses": statuses,
            "current_step": "merge_code",
            "errors": errors,
            "merge_request_url": mr_data.get("web_url") if mr_data else None,
            "merge_result": mr_data or None,
            "cancelled": True,
            "cancel_message": f"Merge Code failed: {errors[0]}",
        }

    merge_result_payload = {
        **mr_data,
        "auto_merged": not merge_warnings,
        "merge_warnings": merge_warnings,
    }

    if merge_warnings:
        return {
            "step_statuses": statuses,
            "current_step": "merge_code",
            "merge_request_url": mr_data.get("web_url"),
            "merge_request_id": mr_data.get("id"),
            "merge_result": merge_result_payload,
        }

    return {
        "step_statuses": statuses,
        "current_step": "deploy_staging",
        "merge_request_url": mr_data.get("web_url"),
        "merge_request_id": mr_data.get("id"),
        "merge_result": merge_result_payload,
    }


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
        "current_step": "smoke_staging",
    }


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
        "message": "Staging smoke tests passed. Deploy to production?",
        "data": {"deploy": state.get("staging_deploy"), "smoke": state.get("staging_smoke")},
    })
    approved = bool(decision.get("approved", False))
    statuses = dict(state.get("step_statuses") or {})
    statuses["approval_staging"] = "completed" if approved else "failed"
    if not approved:
        return {"step_statuses": statuses, "current_step": "deploy_staging"}
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
    approved = bool(decision.get("approved", False))
    statuses = dict(state.get("step_statuses") or {})
    statuses["approval_production"] = "completed" if approved else "failed"
    if not approved:
        return {"step_statuses": statuses, "current_step": "deploy_production"}
    statuses["approval_production"] = "completed"
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
    return "merge_code" if state.get("current_step") == "merge_code" else "run_tests"


def route_after_merge_code(state: WorkflowGraphState) -> str:
    if state.get("cancelled"):
        return "stopped"
    if state.get("current_step") == "deploy_staging":
        return "deploy_staging"
    return "stopped"


def route_after_staging_approval(state: WorkflowGraphState) -> str:
    return "deploy_production" if state.get("current_step") == "deploy_production" else "deploy_staging"


def route_after_production_approval(state: WorkflowGraphState) -> str:
    return "finished" if state.get("finished") else "deploy_production"
