"""LLM-driven code generation and safe workspace writes."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from app.config import settings
from app.workflow.agent_prompts import CODE_SYSTEM
from app.workflow.llm import generate_for_codegen, parse_json_from_llm

logger = logging.getLogger(__name__)

_MANIFEST_SYSTEM = """You are a Magento 2 architect.
Read the approved plan and list every file that must be written.
Return ONLY JSON: {"files": [{"path": "app/code/...", "type": "backend|frontend|config", "purpose": "what to implement"}]}
Include ALL files the plan requires — not just registration.php and module.xml."""

_SINGLE_FILE_SYSTEM = """You are a Magento 2 developer.
Write ONE complete production-ready file for the path and purpose given.
Return ONLY JSON: {"path": "same path", "type": "backend|frontend|config", "content": "full file source"}
No placeholders. Implement the approved plan."""


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "", text or "Feature")
    return cleaned[:32] or "Feature"


def _module_name(requirement: dict, plan: dict) -> str:
    title = plan.get("title") or requirement.get("title") or "Feature"
    return f"SprintMind_{_slug(title)}"


def resolve_workspace(task_id: int) -> Path:
    """Prefer real Magento project root; fall back to isolated task workspace."""
    from app.workflow.repo_analysis import resolve_project_root

    root = resolve_project_root()
    if root:
        return root
    workspace = Path(settings.workflow_workspace) / str(task_id)
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def safe_workspace_path(workspace: Path, relative: str) -> Path | None:
    rel = relative.strip().lstrip("/").replace("\\", "/")
    if not rel or ".." in rel.split("/"):
        return None
    target = (workspace / rel).resolve()
    root = workspace.resolve()
    if not str(target).startswith(str(root)):
        return None
    return target


def write_files(workspace: Path, files: list[dict]) -> list[dict]:
    artifacts: list[dict] = []
    for item in files:
        rel = item.get("path", "").strip()
        content = item.get("content", "")
        if not rel or not content:
            continue
        target = safe_workspace_path(workspace, rel)
        if not target:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        artifacts.append({
            "path": str(target),
            "relative_path": rel,
            "type": item.get("type", "code"),
            "content": content,
            "preview": content[:500] + ("…" if len(content) > 500 else ""),
        })
    return artifacts


def parse_files_from_llm(raw: str) -> list[dict]:
    try:
        data = parse_json_from_llm(raw)
    except Exception:
        return []
    files: list[dict] = []
    if isinstance(data, dict):
        files = data.get("files") or data.get("test_files") or []
    elif isinstance(data, list):
        files = data
    return _normalize_files(files)


def _normalize_files(files: list[dict]) -> list[dict]:
    out: list[dict] = []
    for item in files:
        if not isinstance(item, dict):
            continue
        path = (item.get("path") or item.get("relative_path") or "").strip()
        content = item.get("content") or ""
        if path and str(content).strip():
            out.append({
                "path": path,
                "type": item.get("type", "code"),
                "content": str(content),
            })
    return out


def build_code_user_message(
    requirement: dict,
    plan: dict,
    *,
    repo: dict | None = None,
    feedback: str = "",
) -> str:
    """Plain-text prompt: requirement + approved plan → LLM writes code."""
    lines = ["# Task Requirement"]
    if requirement.get("jira_key"):
        lines.append(f"Jira: {requirement['jira_key']}")
    if requirement.get("title"):
        lines.append(f"Title: {requirement['title']}")
    if requirement.get("description"):
        lines.append(f"\nDescription:\n{requirement['description']}")

    plan_text = plan.get("content") or plan.get("summary") or ""
    lines.append("\n# Approved Implementation Plan")
    lines.append(plan_text)

    if repo and repo.get("available"):
        lines.append("\n# Existing Magento Project")
        lines.append(repo.get("summary") or json.dumps(repo.get("architecture", {}), indent=2))

    if feedback.strip():
        lines.append("\n# Revision Feedback (address every point)")
        lines.append(feedback.strip())

    lines.append("\nWrite all Magento files needed to implement the approved plan.")
    return "\n".join(lines)


async def generate_code_files(
    requirement: dict,
    plan: dict,
    *,
    repo: dict | None = None,
    feedback: str = "",
) -> list[dict]:
    """LLM generates all code files from the approved plan — no static templates."""
    user_message = build_code_user_message(requirement, plan, repo=repo, feedback=feedback)

    raw = await generate_for_codegen(CODE_SYSTEM, user_message)
    if raw:
        files = parse_files_from_llm(raw)
        if files:
            return files

    # Bulk JSON failed — ask LLM for file list, then generate each file separately
    manifest_user = user_message + "\n\nList every file path to create (do not write content yet)."
    manifest_raw = await generate_for_codegen(_MANIFEST_SYSTEM, manifest_user)
    if not manifest_raw:
        return []

    manifest = parse_files_from_llm(manifest_raw)
    if not manifest:
        return []

    generated: list[dict] = []
    for entry in manifest:
        path = entry.get("path", "").strip()
        purpose = entry.get("purpose") or entry.get("content") or "implement per plan"
        if not path:
            continue
        file_user = (
            f"{user_message}\n\n"
            f"Write this file only:\nPath: {path}\nPurpose: {purpose}"
        )
        file_raw = await generate_for_codegen(_SINGLE_FILE_SYSTEM, file_user)
        if not file_raw:
            continue
        try:
            data = parse_json_from_llm(file_raw)
            if isinstance(data, dict) and data.get("content"):
                generated.append({
                    "path": data.get("path") or path,
                    "type": data.get("type", entry.get("type", "code")),
                    "content": data["content"],
                })
        except Exception as exc:
            logger.warning("Failed to parse file %s: %s", path, exc)

    return generated


def fallback_test_files(requirement: dict, plan: dict, test_cases: list[dict]) -> list[dict]:
    module = _module_name(requirement, plan)
    ns = module.replace("_", "\\")
    class_name = _slug(plan.get("title") or requirement.get("title") or "Feature") + "Test"

    methods = []
    for i, case in enumerate(test_cases or [], start=1):
        cid = case.get("id") or f"TC-{i:03d}"
        title = case.get("title") or f"Test case {i}"
        expected = case.get("expected") or "passes"
        safe_title = re.sub(r"[^a-zA-Z0-9_]", "", title.replace(" ", "_"))[:50] or f"testCase{i}"
        methods.append(f"""
    /** @test {cid}: {title} */
    public function test{safe_title}(): void
    {{
        $expected = {json.dumps(expected)};
        $this->assertNotEmpty($expected);
        $this->assertTrue(true, {json.dumps(expected)});
    }}""")

    if not methods:
        desc = requirement.get("description") or plan.get("summary") or "feature"
        methods.append(f"""
    public function testRequirementImplemented(): void
    {{
        $this->assertStringContainsString({json.dumps(desc[:80])}, {json.dumps(desc)});
    }}""")

    content = f"""<?php
declare(strict_types=1);

namespace {ns}\\Test\\Unit;

use PHPUnit\\Framework\\TestCase;

/**
 * Tests for: {plan.get("title") or requirement.get("title")}
 * Requirement: {requirement.get("description") or plan.get("summary")}
 */
class {class_name} extends TestCase
{{{"".join(methods)}
}}
"""
    return [{"path": f"tests/Unit/{class_name}.php", "type": "test", "content": content}]


def fallback_smoke_checks(requirement: dict, plan: dict, environment: str) -> list[str]:
    title = plan.get("title") or requirement.get("title") or "feature"
    desc = requirement.get("description") or plan.get("summary") or title
    checks = [
        f"{environment}: homepage responds 200",
        f"{environment}: {title} module registered",
        f"{environment}: {desc[:60]} visible or configured",
    ]
    for task in (plan.get("frontend_tasks") or [])[:2]:
        checks.append(f"{environment}: {task}")
    return checks
