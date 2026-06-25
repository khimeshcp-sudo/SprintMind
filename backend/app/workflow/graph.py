"""LangGraph workflow assembly."""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.workflow.nodes import (
    approval_code_node,
    approval_deploy_staging_node,
    approval_plan_node,
    approval_production_node,
    approval_smoke_staging_node,
    approval_staging_node,
    approval_test_run_node,
    approval_tests_node,
    create_branch_node,
    deploy_production_node,
    deploy_staging_node,
    generate_plan_node,
    generate_tests_node,
    parse_requirement_node,
    route_after_code_approval,
    route_after_create_branch,
    route_after_deploy_staging_approval,
    route_after_plan_approval,
    route_after_production_approval,
    route_after_smoke_staging_approval,
    route_after_staging_approval,
    route_after_test_run_approval,
    route_after_tests_approval,
    run_tests_node,
    smoke_production_node,
    smoke_staging_node,
    write_code_node,
)
from app.workflow.state import WorkflowGraphState
from app.workflow.steps import STEP_ORDER

_checkpointer = MemorySaver()
_compiled_graph = None


def reset_workflow_graph() -> None:
    """Clear cached graph (e.g. after structural changes)."""
    global _compiled_graph
    _compiled_graph = None


def build_workflow():
    global _compiled_graph
    if _compiled_graph is not None:
        return _compiled_graph

    g = StateGraph(WorkflowGraphState)

    g.add_node("parse_requirement", parse_requirement_node)
    g.add_node("generate_plan", generate_plan_node)
    g.add_node("approval_plan", approval_plan_node)
    g.add_node("write_code", write_code_node)
    g.add_node("approval_code", approval_code_node)
    g.add_node("generate_tests", generate_tests_node)
    g.add_node("approval_tests", approval_tests_node)
    g.add_node("run_tests", run_tests_node)
    g.add_node("approval_test_run", approval_test_run_node)
    g.add_node("create_branch", create_branch_node)
    g.add_node("approval_deploy_staging", approval_deploy_staging_node)
    g.add_node("deploy_staging", deploy_staging_node)
    g.add_node("approval_smoke_staging", approval_smoke_staging_node)
    g.add_node("smoke_staging", smoke_staging_node)
    g.add_node("approval_staging", approval_staging_node)
    g.add_node("deploy_production", deploy_production_node)
    g.add_node("smoke_production", smoke_production_node)
    g.add_node("approval_production", approval_production_node)

    g.add_edge(START, "parse_requirement")
    g.add_edge("parse_requirement", "generate_plan")
    g.add_edge("generate_plan", "approval_plan")
    g.add_conditional_edges("approval_plan", route_after_plan_approval, {
        "write_code": "write_code",
        "generate_plan": "generate_plan",
    })
    g.add_edge("write_code", "approval_code")
    g.add_conditional_edges("approval_code", route_after_code_approval, {
        "generate_tests": "generate_tests",
        "write_code": "write_code",
    })
    g.add_edge("generate_tests", "approval_tests")
    g.add_conditional_edges("approval_tests", route_after_tests_approval, {
        "run_tests": "run_tests",
        "generate_tests": "generate_tests",
    })
    g.add_edge("run_tests", "approval_test_run")
    g.add_conditional_edges("approval_test_run", route_after_test_run_approval, {
        "create_branch": "create_branch",
        "run_tests": "run_tests",
    })
    g.add_conditional_edges("create_branch", route_after_create_branch, {
        "approval_deploy_staging": "approval_deploy_staging",
        "create_branch": "create_branch",
    })
    g.add_conditional_edges("approval_deploy_staging", route_after_deploy_staging_approval, {
        "deploy_staging": "deploy_staging",
        "approval_deploy_staging": "approval_deploy_staging",
    })
    g.add_edge("deploy_staging", "approval_smoke_staging")
    g.add_conditional_edges("approval_smoke_staging", route_after_smoke_staging_approval, {
        "smoke_staging": "smoke_staging",
        "approval_smoke_staging": "approval_smoke_staging",
    })
    g.add_edge("smoke_staging", "approval_staging")
    g.add_conditional_edges("approval_staging", route_after_staging_approval, {
        "deploy_production": "deploy_production",
        "approval_staging": "approval_staging",
    })
    g.add_edge("deploy_production", "smoke_production")
    g.add_edge("smoke_production", "approval_production")
    g.add_conditional_edges("approval_production", route_after_production_approval, {
        "finished": END,
        "deploy_production": "deploy_production",
    })

    _compiled_graph = g.compile(checkpointer=_checkpointer)
    return _compiled_graph


def initial_state(task_id: int, user_id: int, thread_id: str, requirement: dict) -> WorkflowGraphState:
    statuses = {step: "pending" for step in STEP_ORDER}
    statuses["parse_requirement"] = "pending"
    return WorkflowGraphState(
        task_id=task_id,
        user_id=user_id,
        thread_id=thread_id,
        requirement=requirement,
        code_artifacts=[],
        test_cases=[],
        errors=[],
        step_statuses=statuses,
        current_step="parse_requirement",
        waiting_approval=None,
        finished=False,
    )
