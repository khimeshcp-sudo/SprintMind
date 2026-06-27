"""Plan generation from CSV task description."""

from __future__ import annotations

PLAN_SYSTEM = """You are a Senior Magento 2 Developer and Solution Architect.

Read the task description below (from a Jira/CSV export) and write a clear implementation plan.

Your plan must include:
- Requirement summary
- Acceptance criteria (extract from the description — numbered list)
- Technical approach: Magento module name suggestion, EVERY file to create (full paths under app/code/Vendor/Module/), controllers, observers, plugins, layout XML, templates, JS
- Testing approach
- Risks and rough time estimate

Write in clear, readable markdown. Do NOT return JSON — use headings and bullet lists.
Use ## Acceptance Criteria and ## Technical Approach as section headings."""


def enrich_requirement(requirement: dict) -> dict:
    """Merge CSV file fields into requirement (title, description, etc.)."""
    from app.workflow.csv_parser import parse_task_csv

    req = {k: v for k, v in (requirement or {}).items() if v is not None}
    file_path = req.get("file_path")
    if file_path:
        parsed = parse_task_csv(file_path)
        for key, value in parsed.items():
            if key == "raw":
                req["raw"] = value
            elif value is not None and str(value).strip():
                req[key] = str(value).strip()
    if not req.get("description") and req.get("title"):
        req["description"] = req["title"]
    return req


def build_plan_user_message(requirement: dict, *, feedback: str = "") -> str:
    """Build the user message sent to the AI — CSV description only."""
    lines: list[str] = []

    title = (requirement.get("title") or "").strip()
    jira = (requirement.get("jira_key") or "").strip()
    description = (requirement.get("description") or "").strip()

    if jira:
        lines.append(f"Jira Key: {jira}")
    if title:
        lines.append(f"Title: {title}")
    if description:
        lines.append("")
        lines.append("Task Description:")
        lines.append(description)
    elif requirement.get("raw"):
        lines.append("")
        lines.append("CSV Fields:")
        for key, value in requirement["raw"].items():
            if value and str(value).strip():
                lines.append(f"- {key}: {value}")
    else:
        lines.append(str(requirement))

    if feedback.strip():
        lines.append("")
        lines.append("---")
        lines.append("REVIEWER FEEDBACK — revise the plan and address every point:")
        lines.append(feedback.strip())

    return "\n".join(lines).strip()


def build_plan_from_response(requirement: dict, ai_response: str, *, revision: int = 0, feedback: str = "") -> dict:
    content = (ai_response or "").strip()
    if not content:
        content = _fallback_plan_markdown(requirement, feedback)
    plan = {
        "title": requirement.get("title") or "Implementation Plan",
        "jira_key": requirement.get("jira_key", ""),
        "description": requirement.get("description", ""),
        "content": content,
        "revision": revision,
        "format": "markdown",
    }
    if feedback:
        plan["revision_feedback"] = feedback
    return plan


def _fallback_plan_markdown(requirement: dict, feedback: str = "") -> str:
    title = requirement.get("title") or "Magento Task"
    desc = requirement.get("description") or title
    text = f"""# Implementation Plan: {title}

## Requirement Summary
{desc}

## Acceptance Criteria
- Deliver the functionality described in the task
- Follow Magento 2 coding standards

## Technical Approach
- Backend module under app/code/ with DI and service contracts
- Frontend layout XML and templates as needed

## Testing
- PHPUnit tests and manual storefront verification

## Risks & Estimate
- Cache/theme compatibility
- Estimate: ~8 hours
"""
    if feedback.strip():
        text += f"\n## Reviewer Feedback Addressed\n{feedback.strip()}\n"
    return text
