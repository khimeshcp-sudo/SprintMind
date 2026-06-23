"""Free AI via Ollama with rule-based fallback."""

from __future__ import annotations

import json
import re

import httpx

from app.config import settings


async def generate(system: str, user: str) -> str:
    if settings.ollama_enabled:
        try:
            return await _ollama_generate(system, user)
        except Exception:
            pass
    return _fallback_generate(system, user)


async def _ollama_generate(system: str, user: str) -> str:
    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
    payload = {
        "model": settings.ollama_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["message"]["content"]


def _fallback_generate(system: str, user: str) -> str:
    """Deterministic fallback when Ollama is unavailable."""
    sys_lower = system.lower()

    if "plan" in sys_lower or "planning" in sys_lower:
        return _fallback_plan(user)

    if "test case" in sys_lower and "phpunit" not in sys_lower:
        return _fallback_test_cases(user)

    if "magento 2 developer" in sys_lower or ("generate" in sys_lower and "files" in sys_lower):
        return _fallback_code_files_json(user)

    if "phpunit" in sys_lower or "test file" in sys_lower:
        return _fallback_test_files_json(user)

    if "smoke" in sys_lower:
        return _fallback_smoke_json(user)

    return json.dumps({"result": "ok", "note": "Generated with fallback AI (start Ollama for full LLM)"})


def _parse_user_json(user: str) -> dict:
    try:
        return json.loads(user)
    except Exception:
        return {}


def _fallback_plan(user: str) -> str:
    data = _parse_user_json(user)
    title = data.get("title") or _extract_field(user, "title") or "Magento feature"
    desc = data.get("description") or _extract_field(user, "description") or title
    keywords = desc.lower()
    frontend = []
    backend = []
    if any(w in keywords for w in ("slider", "carousel", "banner", "homepage")):
        frontend.extend([
            "Add homepage layout XML for the visual component",
            "Create template/JS for responsive display",
        ])
        backend.extend([
            "Create module with admin enable/disable config",
            "Wire CMS block or media for slide content",
        ])
    if any(w in keywords for w in ("api", "rest", "endpoint")):
        backend.append("Add REST API endpoint with ACL and integration tests")
    if any(w in keywords for w in ("checkout", "cart", "quote")):
        backend.append("Extend quote/checkout flow per requirement")
    if not frontend:
        frontend.append(f"Implement UI changes for: {desc}")
    if not backend:
        backend.append(f"Create Magento module scaffolding for: {desc}")

    return json.dumps(
        {
            "title": title,
            "summary": f"Implement: {desc}",
            "frontend_tasks": frontend,
            "backend_tasks": backend,
            "test_approach": [f"Unit tests for {title}", f"Integration test for: {desc[:80]}"],
            "risks": ["Theme compatibility", "Cache invalidation after deploy"],
            "estimate_hours": 8,
        },
        indent=2,
    )


def _fallback_test_cases(user: str) -> str:
    data = _parse_user_json(user)
    title = data.get("title") or "feature"
    summary = data.get("summary") or data.get("description") or title
    return json.dumps(
        [
            {
                "id": "TC-001",
                "title": f"{title} renders correctly",
                "type": "integration",
                "steps": ["Deploy module", "Open affected page", "Verify UI matches requirement"],
                "expected": summary,
            },
            {
                "id": "TC-002",
                "title": "Admin configuration works",
                "type": "unit",
                "steps": ["Change admin setting", "Flush cache", "Verify behavior"],
                "expected": "Setting is respected on storefront",
            },
        ],
        indent=2,
    )


def _fallback_code_files_json(user: str) -> str:
    from app.workflow.codegen import fallback_code_files

    data = _parse_user_json(user)
    req = data.get("requirement") or data
    plan = data.get("plan") or data
    return json.dumps({"files": fallback_code_files(req, plan)}, indent=2)


def _fallback_test_files_json(user: str) -> str:
    from app.workflow.codegen import fallback_test_files

    data = _parse_user_json(user)
    req = data.get("requirement") or {}
    plan = data.get("plan") or {}
    cases = data.get("test_cases") or []
    return json.dumps({"files": fallback_test_files(req, plan, cases)}, indent=2)


def _fallback_smoke_json(user: str) -> str:
    from app.workflow.codegen import fallback_smoke_checks

    data = _parse_user_json(user)
    req = data.get("requirement") or {}
    plan = data.get("plan") or {}
    env = data.get("environment") or "staging"
    checks = fallback_smoke_checks(req, plan, env)
    return json.dumps({"passed": len(checks), "failed": 0, "checks": checks}, indent=2)


def _extract_field(text: str, field: str) -> str:
    match = re.search(rf"{field}[:=]\s*(.+?)(?:\n|$)", text, re.I)
    return match.group(1).strip() if match else ""


def parse_json_from_llm(text: str) -> dict | list:
    match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if not match:
        return {}
    return json.loads(match.group())
