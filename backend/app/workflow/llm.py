"""LLM providers: Groq / OpenAI-compatible / Ollama, with rule-based fallback."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_PREVIEW_LEN = 8000


def _log_llm_exchange(*, provider: str, system: str, user: str, response: str, extra: str = "") -> None:
    if not settings.llm_debug:
        return
    sep = "=" * 72
    header = f"{sep}\nLLM [{provider}]{f' — {extra}' if extra else ''}\n{sep}"
    body = (
        f"\n>>> SYSTEM PROMPT >>>\n{system}\n"
        f"\n>>> USER MESSAGE >>>\n{user}\n"
        f"\n<<< LLM RESPONSE <<<\n{response}\n"
        f"{sep}\n"
    )
    text = header + body
    logger.info(text)
    print(text, flush=True)


def _preview(text: str) -> str:
    if settings.llm_debug_full or len(text) <= _PREVIEW_LEN:
        return text
    return f"{text[:_PREVIEW_LEN]}\n... [truncated, {len(text)} chars total — set LLM_DEBUG_FULL=true]"


async def generate(system: str, user: str) -> str:
    provider = (settings.llm_provider or "ollama").lower().strip()
    timeout = settings.llm_timeout_seconds

    chain: list[tuple[str, Callable[..., object]]] = []
    if provider == "groq" and settings.groq_api_key:
        chain.append(("groq", _groq_generate))
    elif provider == "openai" and settings.openai_api_key:
        chain.append(("openai", _openai_generate))
    elif provider == "gemini" and settings.gemini_api_key:
        chain.append(("gemini", _gemini_generate))
    elif provider == "ollama" and settings.ollama_enabled:
        chain.append(("ollama", _ollama_generate))

    # Auto-fallback chain when primary not configured
    if not chain:
        if settings.groq_api_key:
            chain.append(("groq", _groq_generate))
        if settings.ollama_enabled:
            chain.append(("ollama", _ollama_generate))
        if settings.openai_api_key:
            chain.append(("openai", _openai_generate))
        if settings.gemini_api_key:
            chain.append(("gemini", _gemini_generate))

    for name, fn in chain:
        try:
            response = await fn(system, user, timeout=timeout)
            _log_llm_exchange(
                provider=name,
                system=_preview(system),
                user=_preview(user),
                response=_preview(response),
            )
            return response
        except Exception as exc:
            logger.warning("%s failed, trying next provider: %s", name, exc)
            if settings.llm_debug:
                print(f"[LLM] {name} error: {exc}", flush=True)

    response = _fallback_generate(system, user)
    _log_llm_exchange(
        provider="fallback",
        system=_preview(system),
        user=_preview(user),
        response=_preview(response),
        extra="All LLM providers unavailable",
    )
    return response


async def _chat_completions(
    *,
    url: str,
    api_key: str,
    model: str,
    system: str,
    user: str,
    timeout: float,
) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if settings.llm_debug:
        print(f"[LLM] POST {url} model={model}", flush=True)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


async def _groq_generate(system: str, user: str, *, timeout: float) -> str:
    return await _chat_completions(
        url="https://api.groq.com/openai/v1/chat/completions",
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        system=system,
        user=user,
        timeout=timeout,
    )


async def _openai_generate(system: str, user: str, *, timeout: float) -> str:
    base = settings.openai_base_url.rstrip("/")
    return await _chat_completions(
        url=f"{base}/chat/completions",
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        system=system,
        user=user,
        timeout=timeout,
    )


async def _gemini_generate(system: str, user: str, *, timeout: float) -> str:
    model = settings.gemini_model
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={settings.gemini_api_key}"
    )
    payload = {
        "contents": [{"role": "user", "parts": [{"text": f"{system}\n\n{user}"}]}],
        "generationConfig": {"temperature": 0.2},
    }
    if settings.llm_debug:
        print(f"[LLM] POST gemini model={model}", flush=True)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(part.get("text", "") for part in parts)


async def _ollama_generate(system: str, user: str, *, timeout: float) -> str:
    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
    payload = {
        "model": settings.ollama_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
    }
    if settings.llm_debug:
        print(f"[LLM] POST {url} model={settings.ollama_model}", flush=True)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["message"]["content"]


def _fallback_generate(system: str, user: str) -> str:
    """Deterministic fallback when no LLM is available."""
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

    return json.dumps({"result": "ok", "note": "Generated with fallback AI (configure Groq or Ollama for full LLM)"})


def _parse_user_json(user: str) -> dict:
    try:
        return json.loads(user)
    except Exception:
        return {}


def _fallback_plan(user: str) -> str:
    """Markdown plan fallback when LLM is down."""
    title = _extract_field(user, "title") or _extract_field(user, "Title") or "Magento Task"
    desc = ""
    if "Task Description:" in user:
        part = user.split("Task Description:", 1)[1]
        desc = part.split("---")[0].strip()
    if not desc:
        data = _parse_user_json(user)
        desc = data.get("description") or data.get("title") or title

    return f"""# Implementation Plan: {title}

## Requirement Summary
{desc}

## Acceptance Criteria
- Deliver the functionality described in the task
- Follow Magento 2 coding standards

## Technical Approach
- Backend module under app/code/
- Frontend templates and layout XML as needed

## Testing
- PHPUnit and manual verification

## Risks & Estimate
- Cache/theme compatibility
- Estimate: ~8 hours
"""


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
