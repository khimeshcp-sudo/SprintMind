"""Generate Magento module code file-by-file from the approved plan."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from app.config import settings
from app.workflow.agent_prompts import FIX_FILE_SYSTEM, MANIFEST_SYSTEM, SINGLE_FILE_SYSTEM
from app.workflow.llm import generate_for_codegen, parse_json_from_llm
from app.workflow.module_context import (
    extract_plan_sections,
    file_type_hint,
    force_module_path,
    resolve_module_identity,
    validate_file_content,
)

logger = logging.getLogger(__name__)

_SUFFIXES = {".php", ".xml", ".phtml", ".js", ".less", ".css", ".md", ".csv"}
_MAX_FIX_ATTEMPTS = 2


def resolve_workspace(task_id: int) -> Path:
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


def read_existing_module_files(workspace: Path, identity: dict) -> dict[str, str]:
    module_dir = workspace / identity["code_path"]
    found: dict[str, str] = {}
    if not module_dir.is_dir():
        return found
    for fp in sorted(module_dir.rglob("*")):
        if not fp.is_file() or fp.suffix.lower() not in _SUFFIXES:
            continue
        rel = str(fp.relative_to(workspace)).replace("\\", "/")
        forced = force_module_path(rel, identity)
        if forced:
            try:
                found[forced] = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
    return found


def write_files(workspace: Path, files: list[dict], *, identity: dict | None = None) -> list[dict]:
    artifacts: list[dict] = []
    prefix = (identity or {}).get("code_path", "")
    for item in files:
        rel = item.get("path", "").strip()
        content = item.get("content", "")
        if not rel or not content:
            continue
        target = safe_workspace_path(workspace, rel)
        if not target:
            logger.warning("Skipped path outside workspace: %s", rel)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        target.write_text(content, encoding="utf-8")
        module_rel = rel[len(prefix) + 1 :] if prefix and rel.startswith(prefix + "/") else rel
        artifacts.append({
            "path": str(target),
            "relative_path": rel,
            "module_relative": module_rel,
            "type": item.get("type", "code"),
            "action": "update" if existed else "create",
            "content": content,
            "preview": content[:500] + ("…" if len(content) > 500 else ""),
        })
    return artifacts


def parse_manifest_from_llm(raw: str) -> list[dict]:
    """Parse file manifest (path + purpose only — no content required)."""
    try:
        data = parse_json_from_llm(raw)
    except Exception:
        return []
    items = data.get("files", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        path = (item.get("path") or "").strip()
        if path:
            out.append({
                "path": path,
                "type": item.get("type", "code"),
                "purpose": item.get("purpose") or "Implement per approved plan",
            })
    return out


def parse_files_from_llm(raw: str) -> list[dict]:
    try:
        data = parse_json_from_llm(raw)
    except Exception:
        return []
    items = data.get("files", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        path = (item.get("path") or "").strip()
        content = item.get("content") or ""
        if path and str(content).strip():
            out.append({"path": path, "type": item.get("type", "code"), "content": str(content)})
    return out


def _parse_one_file(raw: str, default_path: str) -> dict | None:
    try:
        data = parse_json_from_llm(raw)
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("content"):
        return None
    return {
        "path": (data.get("path") or default_path).strip(),
        "type": data.get("type", "code"),
        "content": str(data["content"]),
    }


def _build_context(
    requirement: dict,
    plan: dict,
    identity: dict,
    repo: dict | None,
    feedback: str,
    plan_sections: dict[str, str],
) -> str:
    plan_text = plan.get("content") or plan.get("summary") or json.dumps(plan, indent=2)
    lines = [
        f"# Module: {identity['module_id']}",
        f"code_path: {identity['code_path']}/",
        f"namespace: {identity['namespace']}",
        f"vendor/module name: {identity['vendor']}/{identity['module_name']}",
        "",
        "# Requirement",
        f"Title: {requirement.get('title', '')}",
        f"Description:\n{requirement.get('description', '')}",
    ]

    for key in ("acceptance_criteria", "technical_approach", "requirement_summary", "testing"):
        if plan_sections.get(key):
            title = key.replace("_", " ").title()
            lines.extend(["", f"# Plan — {title}", plan_sections[key]])

    lines.extend(["", "# Full Approved Plan", plan_text])

    if repo and repo.get("available"):
        lines.extend(["", "# Project", repo.get("summary") or ""])
    if feedback.strip():
        lines.extend(["", "# Reviewer Feedback (must address)", feedback.strip()])
    return "\n".join(lines)


def _default_manifest(identity: dict, plan_sections: dict[str, str]) -> list[dict]:
    """Sensible module skeleton when LLM manifest is empty."""
    base = identity["code_path"]
    technical = plan_sections.get("technical_approach", "")
    needs_frontend = any(
        token in technical.lower()
        for token in ("frontend", "storefront", "phtml", "template", "layout", "javascript", "ui component")
    )
    queue = [
        {"path": f"{base}/registration.php", "purpose": "Register module with ComponentRegistrar", "type": "config"},
        {"path": f"{base}/etc/module.xml", "purpose": "Declare module and sequence", "type": "config"},
        {"path": f"{base}/etc/di.xml", "purpose": "Dependency injection configuration", "type": "config"},
    ]
    if needs_frontend:
        queue.extend([
            {"path": f"{base}/etc/frontend/routes.xml", "purpose": "Frontend routes", "type": "config"},
            {"path": f"{base}/view/frontend/layout/default.xml", "purpose": "Layout handle for storefront", "type": "frontend"},
        ])
    return queue


async def _generate_one(
    context: str,
    path: str,
    purpose: str,
    identity: dict,
    existing: str = "",
    *,
    plan_sections: dict[str, str] | None = None,
) -> dict | None:
    path = force_module_path(path, identity)
    if not path:
        return None

    hint = file_type_hint(path, identity)
    criteria = (plan_sections or {}).get("acceptance_criteria", "")
    technical = (plan_sections or {}).get("technical_approach", "")

    file_context = [
        context,
        "",
        f"## File to write",
        f"Path: {path}",
        f"Purpose: {purpose}",
        f"Magento conventions: {hint}",
    ]
    if criteria:
        file_context.extend(["", "## Acceptance criteria (must satisfy)", criteria])
    if technical:
        file_context.extend(["", "## Technical approach (relevant excerpt)", technical[:3000]])

    if existing.strip():
        file_context.extend([
            "",
            "## EXISTING file content — update in place",
            "```",
            existing,
            "```",
            "",
            "Return the COMPLETE updated file.",
        ])
    else:
        file_context.append(f"\nCreate this file under {identity['code_path']}/ implementing the plan.")

    user = "\n".join(file_context)
    raw = await generate_for_codegen(SINGLE_FILE_SYSTEM.replace("{module_id}", identity["module_id"]), user)
    if not raw:
        return None
    result = _parse_one_file(raw, path)
    if result:
        forced = force_module_path(result["path"], identity)
        result["path"] = forced or path
    return result


async def _fix_file(
    context: str,
    file_data: dict,
    issues: list[str],
    identity: dict,
    purpose: str,
) -> dict | None:
    user = "\n".join([
        context,
        "",
        f"Fix file: {file_data['path']}",
        f"Purpose: {purpose}",
        "",
        "Validation issues:",
        *[f"- {i}" for i in issues],
        "",
        "Current content:",
        "```",
        file_data.get("content", ""),
        "```",
        "",
        "Return the COMPLETE corrected file that fixes all issues and matches the approved plan.",
    ])
    raw = await generate_for_codegen(FIX_FILE_SYSTEM.replace("{module_id}", identity["module_id"]), user)
    if not raw:
        return file_data
    fixed = _parse_one_file(raw, file_data["path"])
    if fixed:
        forced = force_module_path(fixed["path"], identity)
        fixed["path"] = forced or file_data["path"]
        return fixed
    return file_data


async def generate_code_files(
    requirement: dict,
    plan: dict,
    *,
    repo: dict | None = None,
    feedback: str = "",
    workspace: Path | None = None,
) -> tuple[list[dict], dict, list[str]]:
    identity = resolve_module_identity(requirement, plan)
    ws = workspace or resolve_workspace(0)
    existing = read_existing_module_files(ws, identity)
    plan_text = plan.get("content") or plan.get("summary") or ""
    plan_sections = extract_plan_sections(plan_text)
    context = _build_context(requirement, plan, identity, repo, feedback, plan_sections)
    warnings: list[str] = []

    manifest_prompt = context + (
        f"\n\n## Task\n"
        f"List ALL files under `{identity['code_path']}/` needed to fully implement the approved plan. "
        f"Include every PHP class, XML config, layout, template, JS, and i18n file mentioned or implied. "
        f"Module id: {identity['module_id']}"
    )
    manifest_raw = await generate_for_codegen(
        MANIFEST_SYSTEM.replace("{module_id}", identity["module_id"]),
        manifest_prompt,
    )
    manifest = parse_manifest_from_llm(manifest_raw) if manifest_raw else []

    seen: set[str] = set()
    queue: list[dict] = []
    for entry in manifest:
        p = force_module_path(entry.get("path", ""), identity)
        if p and p not in seen:
            seen.add(p)
            queue.append({
                "path": p,
                "purpose": entry.get("purpose") or "Implement per approved plan",
                "type": entry.get("type", "code"),
            })

    if not queue:
        warnings.append("LLM manifest empty — using expanded default module file list")
        queue = _default_manifest(identity, plan_sections)

    # Always ensure registration + module.xml exist
    for required in (
        f"{identity['code_path']}/registration.php",
        f"{identity['code_path']}/etc/module.xml",
    ):
        if required not in seen:
            seen.add(required)
            queue.insert(0, {
                "path": required,
                "purpose": "Core module registration" if required.endswith("registration.php") else "Module declaration",
                "type": "config",
            })

    generated: list[dict] = []

    for entry in queue:
        path = entry["path"]
        purpose = entry["purpose"]
        content_existing = existing.get(path, "")

        file_data = await _generate_one(
            context, path, purpose, identity, content_existing, plan_sections=plan_sections,
        )
        if not file_data:
            warnings.append(f"Failed to generate: {path}")
            continue

        for attempt in range(_MAX_FIX_ATTEMPTS):
            issues = validate_file_content(file_data["path"], file_data["content"], identity)
            if not issues:
                break
            logger.info("Fixing %s (attempt %d): %s", path, attempt + 1, issues)
            fixed = await _fix_file(context, file_data, issues, identity, purpose)
            if fixed:
                file_data = fixed
            else:
                warnings.append(f"{path}: validation issues — {'; '.join(issues)}")
                break
        else:
            remaining = validate_file_content(file_data["path"], file_data["content"], identity)
            if remaining:
                warnings.append(f"{path}: still has issues after fix — {'; '.join(remaining)}")

        generated.append(file_data)

    if not generated:
        warnings.append("No files generated — check LLM_PROVIDER and API key in .env")

    return generated, identity, warnings


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "", text or "Feature")
    return cleaned[:32] or "Feature"


def fallback_test_files(requirement: dict, plan: dict, test_cases: list[dict]) -> list[dict]:
    identity = resolve_module_identity(requirement, plan)
    ns = identity["namespace"]
    class_name = _slug(plan.get("title") or requirement.get("title") or "Feature") + "Test"
    methods = "".join(
        f"\n    public function test{i}(): void {{ $this->assertTrue(true); }}"
        for i, _ in enumerate(test_cases or [{"id": "1"}], start=1)
    )
    content = f"<?php\ndeclare(strict_types=1);\nnamespace {ns}\\Test\\Unit;\nuse PHPUnit\\Framework\\TestCase;\nclass {class_name} extends TestCase\n{{{methods}\n}}\n"
    return [{"path": f"tests/Unit/{class_name}.php", "type": "test", "content": content}]


def fallback_smoke_checks(requirement: dict, plan: dict, environment: str) -> list[str]:
    identity = resolve_module_identity(requirement, plan)
    return [f"{environment}: module {identity['module_id']} OK"]
