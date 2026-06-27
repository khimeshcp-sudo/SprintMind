"""Module identity, path helpers, and Magento file validation."""

from __future__ import annotations

import re

from app.jira_utils import branch_name_from_jira, normalize_jira_key, validate_jira_key

_STOP = frozenset({"add", "new", "the", "a", "an", "on", "for", "to", "and", "of", "in", "with", "create"})


def _pascal(title: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", title or "Feature")
    meaningful = [w for w in words if w.lower() not in _STOP]
    source = meaningful or words or ["Feature"]
    name = "".join(w[:1].upper() + w[1:] for w in source[:5])
    return re.sub(r"[^A-Za-z0-9]", "", name)[:40] or "Feature"


def resolve_module_identity(requirement: dict, plan: dict | None = None) -> dict:
    title = (requirement.get("title") or (plan or {}).get("title") or "Feature").strip()
    jira = normalize_jira_key(requirement.get("jira_key"))
    vendor = "SprintMind"
    module_name = _pascal(title)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:45] or "task"
    branch = branch_name_from_jira(jira) if jira else f"feature/{slug}"
    return {
        "vendor": vendor,
        "module_name": module_name,
        "module_id": f"{vendor}_{module_name}",
        "namespace": f"{vendor}\\{module_name}",
        "code_path": f"app/code/{vendor}/{module_name}",
        "branch": branch,
        "jira_key": jira,
        "task_title": title,
    }


def build_branch_strategy(
    requirement: dict,
    plan: dict | None = None,
    *,
    task_id: int | None = None,
) -> dict[str, str]:
    """Always create a fresh branch named feature/{JIRA_ID} (e.g. feature/TAR-3111)."""
    jira = validate_jira_key(requirement.get("jira_key"))
    branch = branch_name_from_jira(jira)
    return {
        "action": "create",
        "branch": branch,
        "reason": f"New feature branch for Jira {jira}",
        "jira_key": jira,
    }


def force_module_path(path: str, identity: dict) -> str | None:
    """All files must live under app/code/Vendor/Module/."""
    path = path.strip().lstrip("/").replace("\\", "/")
    base = identity["code_path"]
    if not path:
        return None
    if path.startswith(base + "/") or path == base:
        return path
    name = path.split("/")[-1]
    if path.startswith("app/design/"):
        if name.endswith(".phtml"):
            return f"{base}/view/frontend/templates/{name}"
        if name.endswith(".xml"):
            return f"{base}/view/frontend/layout/{name}"
        return None
    if path.startswith("app/code/"):
        parts = path.split("/")
        if len(parts) >= 5:
            return f"{base}/{'/'.join(parts[4:])}"
    if name.endswith(".phtml"):
        return f"{base}/view/frontend/templates/{name}"
    if name.endswith(".xml"):
        if "layout" in path.lower() or name.startswith("catalog_") or "default" in name:
            return f"{base}/view/frontend/layout/{name}"
        return f"{base}/etc/{name}" if not path.startswith("app/") else None
    if not path.startswith("app/"):
        return f"{base}/{path}"
    return None


def extract_plan_sections(plan_text: str) -> dict[str, str]:
    """Split markdown plan into sections for targeted codegen context."""
    sections: dict[str, str] = {"overview": ""}
    current_key = "overview"
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        if buffer:
            sections[current_key] = "\n".join(buffer).strip()
            buffer = []

    for line in (plan_text or "").splitlines():
        heading = re.match(r"^#{1,3}\s+(.+)", line.strip())
        if heading:
            flush()
            current_key = heading.group(1).strip().lower()
            current_key = re.sub(r"[^a-z0-9]+", "_", current_key).strip("_") or "section"
        else:
            buffer.append(line)
    flush()
    return {k: v for k, v in sections.items() if v}


def validate_file_content(path: str, content: str, identity: dict) -> list[str]:
    """Return validation issues for generated Magento files."""
    issues: list[str] = []
    text = (content or "").strip()
    if not text:
        return ["File content is empty"]

    lower = text.lower()
    if "objectmanager" in lower.replace(" ", ""):
        issues.append("Must not use ObjectManager — use constructor DI")
    if re.search(r"//\s*todo|placeholder|stub|dummy|implement later|your code here", lower):
        issues.append("Contains placeholder or TODO stub text")
    if "namespace namespace" in lower or "namespace Namespace\\" in text:
        issues.append("Invalid placeholder namespace")

    module_id = identity["module_id"]
    namespace = identity["namespace"]
    name = path.split("/")[-1]

    if name == "registration.php":
        if "ComponentRegistrar" not in text:
            issues.append("registration.php must use ComponentRegistrar::register")
        if module_id not in text:
            issues.append(f"registration.php must register module '{module_id}'")
    elif name == "module.xml":
        if module_id not in text:
            issues.append(f"module.xml must declare module name='{module_id}'")
    elif path.endswith(".php") and "/Test/" not in path:
        if "declare(strict_types=1)" not in text and name != "registration.php":
            issues.append("PHP class files must include declare(strict_types=1)")
        if "namespace " in text:
            ns_match = re.search(r"namespace\s+([\w\\]+)\s*;", text)
            if ns_match:
                file_ns = ns_match.group(1)
                rel = path.split(f"{identity['code_path']}/")[-1] if identity["code_path"] in path else path
                rel = rel.replace(".php", "").replace("/", "\\")
                expected_suffix = rel.replace("registration", "").strip("\\")
                if expected_suffix and not file_ns.startswith(namespace):
                    issues.append(f"Namespace should start with {namespace}, got {file_ns}")
    elif path.endswith(".phtml"):
        if "<?php" not in text and "$block" not in text and "$escaper" not in text:
            issues.append("phtml template should use $block or proper Magento escaping")
    elif path.endswith(".xml"):
        if "<" not in text or ">" not in text:
            issues.append("Invalid XML content")

    return issues


def file_type_hint(path: str, identity: dict) -> str:
    """Per-file Magento conventions injected into the LLM user message."""
    module_id = identity["module_id"]
    namespace = identity["namespace"]
    name = path.split("/")[-1]

    if name == "registration.php":
        return (
            f"registration.php — register module '{module_id}' with "
            f"\\Magento\\Framework\\Component\\ComponentRegistrar::register(MODULE, '{module_id}', __DIR__)"
        )
    if name == "module.xml":
        return f'etc/module.xml — <module name="{module_id}" setup_version="1.0.0"> with sequence if needed'
    if name == "di.xml":
        return "etc/di.xml — preferences, virtualTypes, plugins (name/type/sortOrder), type arguments"
    if name == "events.xml":
        return "etc/events.xml — observer name, instance class, event name"
    if name == "routes.xml":
        return "routes.xml — router id (standard/admin), route frontName, module name"
    if name.endswith("routes.xml"):
        return "Define frontName matching controllers under Controller/"
    if "/Controller/" in path and path.endswith(".php"):
        return f"Controller — namespace {namespace}\\Controller\\...; inject context + dependencies; execute() returns ResultInterface"
    if "/Model/" in path and path.endswith(".php"):
        return f"Model — namespace {namespace}\\Model; business logic; use resource models or repositories as per plan"
    if "/Api/" in path and path.endswith(".php"):
        return f"Service contract — namespace {namespace}\\Api; interface only with @api annotations if public"
    if "/Block/" in path and path.endswith(".php"):
        return f"Block — namespace {namespace}\\Block; extend Template or AbstractBlock; inject via constructor"
    if "/Observer/" in path and path.endswith(".php"):
        return f"Observer — namespace {namespace}\\Observer; implement ObserverInterface; execute(Observer $observer)"
    if "/Plugin/" in path and path.endswith(".php"):
        return f"Plugin — namespace {namespace}\\Plugin; before/around/after plugin methods"
    if path.endswith(".phtml"):
        return "Frontend template — use $block helpers, escape output, no raw business logic"
    if "/layout/" in path and path.endswith(".xml"):
        return "Layout XML — page/layout handle, referenceBlock/referenceContainer, block class and template attributes"
    if name == "requirejs-config.js":
        return "requirejs-config.js — map, shim, or mixins for frontend JS"
    if path.endswith(".csv"):
        return "i18n/en_US.csv — original string,translation pairs"
    return f"Implement per approved plan under module {module_id}"
