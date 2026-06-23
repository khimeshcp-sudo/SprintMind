"""Workflow step definitions for UI progress."""

WORKFLOW_STEPS = [
    {"id": "parse_requirement", "label": "Read Requirement", "icon": "file"},
    {"id": "generate_plan", "label": "AI Planning", "icon": "brain"},
    {"id": "approval_plan", "label": "Approve Plan", "icon": "user"},
    {"id": "write_code", "label": "Write Code", "icon": "code"},
    {"id": "approval_code", "label": "Approve Code", "icon": "user"},
    {"id": "generate_tests", "label": "Generate Tests", "icon": "test"},
    {"id": "approval_tests", "label": "Approve Tests", "icon": "user"},
    {"id": "run_tests", "label": "Run Tests", "icon": "play"},
    {"id": "approval_test_run", "label": "Approve Test Results", "icon": "user"},
    {"id": "deploy_staging", "label": "Deploy Staging", "icon": "rocket"},
    {"id": "smoke_staging", "label": "Smoke Test (Staging)", "icon": "check"},
    {"id": "approval_staging", "label": "Approve Staging", "icon": "user"},
    {"id": "deploy_production", "label": "Deploy Production", "icon": "rocket"},
    {"id": "smoke_production", "label": "Smoke Test (Prod)", "icon": "check"},
    {"id": "approval_production", "label": "Approve Production", "icon": "user"},
    {"id": "finished", "label": "Complete", "icon": "flag"},
]

STEP_ORDER = [s["id"] for s in WORKFLOW_STEPS]
