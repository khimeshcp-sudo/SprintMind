"""Workflow step error helpers."""

from __future__ import annotations

from app.workflow.steps import WORKFLOW_STEPS

STEP_LABELS = {s["id"]: s["label"] for s in WORKFLOW_STEPS}


def merge_step_errors(left: dict | None, right: dict | None) -> dict[str, list[str]]:
    out = dict(left or {})
    for step, msgs in (right or {}).items():
        items = msgs if isinstance(msgs, list) else [str(msgs)]
        out.setdefault(step, []).extend(items)
    return out


def record_step_failure(
    step: str,
    messages: list[str] | str,
    *,
    statuses: dict[str, str] | None = None,
) -> dict:
    msgs = [messages] if isinstance(messages, str) else list(messages)
    label = STEP_LABELS.get(step, step)
    labeled = [f"{label}: {m}" for m in msgs]
    step_statuses = dict(statuses or {})
    step_statuses[step] = "failed"
    return {
        "step_statuses": step_statuses,
        "step_errors": {step: msgs},
        "errors": labeled,
    }


def apply_failure_to_state(state: dict, step: str, messages: list[str] | str) -> dict:
    """Merge a step failure into an existing workflow state dict."""
    update = record_step_failure(step, messages, statuses=state.get("step_statuses"))
    merged_statuses = dict(state.get("step_statuses") or {})
    merged_statuses.update(update["step_statuses"])
    return {
        **state,
        "step_statuses": merged_statuses,
        "step_errors": merge_step_errors(state.get("step_errors"), update["step_errors"]),
        "errors": list(state.get("errors") or []) + update["errors"],
    }
