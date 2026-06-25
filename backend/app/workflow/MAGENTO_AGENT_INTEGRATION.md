"""Drop-in replacements for nodes.py integration — rename to nodes.py after fixing ownership.

Run:
  sudo chown cp:cp backend/app/workflow/nodes.py backend/app/workflow/state.py
  # Then apply the edits below or copy from this guide.
"""

# --- parse_requirement_node: after statuses["parse_requirement"] = "completed" add:
#
#     keywords = extract_keywords(req)
#     repo = analyze_repository(keywords=keywords)
#
# And in return dict add: "repo_analysis": repo,

# --- generate_plan_node: replace system prompt block with:
#
#     repo = state.get("repo_analysis") or {}
#     user_payload = {"requirement": req, "repository_analysis": repo}
#     if feedback:
#         user_payload["revision_feedback"] = feedback
#     raw = await generate(PLAN_SYSTEM, json.dumps(user_payload, indent=2))

# --- write_code_node: replace workspace + system with:
#
#     repo = state.get("repo_analysis") or {}
#     workspace = resolve_workspace(task_id)
#     user_payload = {"requirement": req, "plan": plan, "repository_analysis": repo}
#     if feedback:
#         user_payload["revision_feedback"] = feedback
#     raw = await generate(CODE_SYSTEM, json.dumps(user_payload, indent=2))

# --- run_tests_node: replace workspace line with:
#
#     workspace = resolve_workspace(task_id)

# --- state.py: add after plan: dict
#
#     repo_analysis: dict

# --- runner.py build_workflow_response return dict add:
#
#     "repo_analysis": state.get("repo_analysis"),
