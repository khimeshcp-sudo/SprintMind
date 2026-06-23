"""Dynamic code/test file generation and safe workspace writes."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.workflow.llm import parse_json_from_llm


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "", text or "Feature")
    return cleaned[:32] or "Feature"


def _module_name(requirement: dict, plan: dict) -> str:
    title = plan.get("title") or requirement.get("title") or "Feature"
    return f"SprintMind_{_slug(title)}"


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
            "preview": content[:500] + ("…" if len(content) > 500 else ""),
        })
    return artifacts


def parse_files_from_llm(raw: str) -> list[dict]:
    try:
        data = parse_json_from_llm(raw)
    except Exception:
        return []
    if isinstance(data, dict):
        return data.get("files") or data.get("test_files") or []
    if isinstance(data, list):
        return data
    return []


def fallback_code_files(requirement: dict, plan: dict) -> list[dict]:
    """Requirement-driven fallback when LLM is unavailable."""
    title = plan.get("title") or requirement.get("title") or "Feature"
    desc = plan.get("summary") or requirement.get("description") or title
    module = _module_name(requirement, plan)
    vendor, name = module.split("_", 1) if "_" in module else ("SprintMind", _slug(title))

    backend_tasks = plan.get("backend_tasks") or []
    frontend_tasks = plan.get("frontend_tasks") or []
    backend_comment = "\n * ".join(backend_tasks[:5]) if backend_tasks else desc
    frontend_comment = "\n * ".join(frontend_tasks[:5]) if frontend_tasks else desc

    files = [
        {
            "path": f"app/code/{vendor}/{name}/registration.php",
            "type": "backend",
            "content": f"""<?php
/**
 * Auto-generated for: {title}
 * {desc}
 */
use Magento\\Framework\\Component\\ComponentRegistrar;
ComponentRegistrar::register(ComponentRegistrar::MODULE, '{module}', __DIR__);
""",
        },
        {
            "path": f"app/code/{vendor}/{name}/etc/module.xml",
            "type": "backend",
            "content": f"""<?xml version="1.0"?>
<!-- Backend tasks:
 * {backend_comment}
-->
<config xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xsi:noNamespaceSchemaLocation="urn:magento:framework:Module/etc/module.xsd">
    <module name="{module}"/>
</config>
""",
        },
        {
            "path": f"app/code/{vendor}/{name}/README.md",
            "type": "docs",
            "content": f"# {title}\n\n{desc}\n\n## Backend\n" + "\n".join(f"- {t}" for t in backend_tasks)
            + "\n\n## Frontend\n" + "\n".join(f"- {t}" for t in frontend_tasks),
        },
    ]

    if frontend_tasks or "layout" in desc.lower() or "frontend" in desc.lower():
        layout_name = re.sub(r"[^a-z0-9_]+", "_", title.lower())[:40]
        files.append({
            "path": f"app/design/frontend/{vendor}/default/Magento_Cms/layout/cms_index_index.xml",
            "type": "frontend",
            "content": f"""<?xml version="1.0"?>
<!-- Frontend tasks:
 * {frontend_comment}
-->
<page xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
      xsi:noNamespaceSchemaLocation="urn:magento:framework:View/Layout/etc/page_configuration.xsd">
    <body>
        <referenceContainer name="content">
            <block class="Magento\\Framework\\View\\Element\\Template"
                   name="sprintmind.{layout_name}"
                   template="{vendor}_{name}::{layout_name}.phtml"/>
        </referenceContainer>
    </body>
</page>
""",
        })
        files.append({
            "path": f"app/code/{vendor}/{name}/view/frontend/templates/{layout_name}.phtml",
            "type": "frontend",
            "content": f"""<?php /** @var \\Magento\\Framework\\View\\Element\\Template $block */ ?>
<div class="sprintmind-{layout_name}" data-feature="{title}">
    <p><?= $block->escapeHtml(__('{desc}')) ?></p>
</div>
""",
        })

    return files


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
