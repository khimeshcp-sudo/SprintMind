"""Magento repository analysis — git state and codebase scan."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from app.config import settings

SCAN_DIRS = (
    "app/code",
    "app/design",
    "app/etc",
    "vendor",
)

MAGENTO_PATTERNS = (
    "Controller",
    "Model",
    "Plugin",
    "Observer",
    "Api",
    "Api/Data",
    "Repository",
    "Block",
    "ViewModel",
    "view",
    "etc",
)


def _run(cmd: list[str], cwd: Path, timeout: int = 30) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, out.strip()
    except Exception as exc:
        return 1, str(exc)


def _run_git(args: list[str], root: Path, timeout: int = 30) -> tuple[int, str]:
    """Run git with safe.directory — required for Docker volume mounts (dubious ownership)."""
    safe = str(root.resolve())
    return _run(["git", "-c", f"safe.directory={safe}", *args], root, timeout)


def _configure_git_safe_directory(root: Path) -> None:
    _run(["git", "config", "--global", "--add", f"safe.directory={root.resolve()}"], root)


def resolve_project_root() -> Path | None:
    raw = (settings.magento_project_path or "").strip()
    if not raw:
        return None
    root = Path(raw).expanduser().resolve()
    return root if root.is_dir() else None


def analyze_repository(*, keywords: list[str] | None = None) -> dict[str, Any]:
    """Run git inspection and lightweight Magento codebase scan."""
    root = resolve_project_root()
    if not root:
        return {
            "available": False,
            "project_path": settings.magento_project_path or "",
            "error": "MAGENTO_PROJECT_PATH not set or directory missing",
        }

    keywords = [k.lower() for k in (keywords or []) if k]

    _configure_git_safe_directory(root)

    _, pwd = _run(["pwd"], root)
    _, status = _run_git(["status", "-sb"], root)
    _, branch_local = _run_git(["branch", "--list"], root)
    _, branch_remote = _run_git(["branch", "-r"], root)
    _, remotes = _run_git(["remote", "-v"], root)

    feature_branches = [
        line.strip().lstrip("* ").strip()
        for line in branch_local.splitlines()
        if "feature/" in line.lower()
    ]

    modules = _list_modules(root)
    design_themes = _list_design_themes(root)
    keyword_hits = _search_keywords(root, keywords) if keywords else []

    architecture = {
        "custom_modules": modules,
        "design_themes": design_themes,
        "has_app_code": (root / "app" / "code").is_dir(),
        "composer_json": (root / "composer.json").is_file(),
    }

    branch_strategy = _suggest_branch(keywords, feature_branches, status)

    return {
        "available": True,
        "project_path": str(root),
        "git": {
            "pwd": pwd,
            "status": status,
            "current_branches": branch_local,
            "remote_branches": branch_remote,
            "remotes": remotes,
            "feature_branches": feature_branches,
        },
        "architecture": architecture,
        "keyword_hits": keyword_hits,
        "branch_strategy": branch_strategy,
        "summary": _build_summary(root, modules, design_themes, status, branch_strategy),
    }


def _list_modules(root: Path) -> list[dict[str, str]]:
    code_dir = root / "app" / "code"
    if not code_dir.is_dir():
        return []
    modules: list[dict[str, str]] = []
    for reg in sorted(code_dir.rglob("registration.php")):
        rel = reg.relative_to(root)
        parts = reg.relative_to(code_dir).parts
        if len(parts) >= 3:
            vendor, name = parts[0], parts[1]
            modules.append({
                "vendor": vendor,
                "name": name,
                "module": f"{vendor}_{name}",
                "registration": str(rel),
            })
    return modules


def _list_design_themes(root: Path) -> list[str]:
    themes: list[str] = []
    for area in ("frontend", "adminhtml"):
        base = root / "app" / "design" / area
        if not base.is_dir():
            continue
        for vendor_dir in sorted(base.iterdir()):
            if not vendor_dir.is_dir():
                continue
            for theme_dir in sorted(vendor_dir.iterdir()):
                if theme_dir.is_dir():
                    themes.append(f"{area}/{vendor_dir.name}/{theme_dir.name}")
    return themes


def _search_keywords(root: Path, keywords: list[str]) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    seen: set[str] = set()
    search_roots = [root / d for d in ("app/code", "app/design") if (root / d).is_dir()]
    if not search_roots:
        search_roots = [root / "app"] if (root / "app").is_dir() else [root]

    for base in search_roots:
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".php", ".xml", ".phtml", ".js", ".less", ".html"}:
                continue
            rel = str(path.relative_to(root))
            if rel in seen:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                continue
            if any(kw in text or kw in rel.lower() for kw in keywords):
                seen.add(rel)
                hits.append({"path": rel, "type": _classify_path(rel)})
            if len(hits) >= 40:
                return hits
    return hits


def _classify_path(rel: str) -> str:
    lower = rel.lower()
    for label in MAGENTO_PATTERNS:
        if label.lower().replace("/", "") in lower.replace("/", ""):
            return label
    if "/controller/" in lower:
        return "Controller"
    if "/model/" in lower:
        return "Model"
    if "/plugin/" in lower:
        return "Plugin"
    if "/observer/" in lower:
        return "Observer"
    if "/block/" in lower:
        return "Block"
    if "/viewmodel/" in lower:
        return "ViewModel"
    if rel.endswith(".phtml"):
        return "template"
    if rel.endswith(".xml"):
        return "xml"
    return "other"


def _suggest_branch(keywords: list[str], feature_branches: list[str], status: str) -> dict[str, str]:
    jira = ""
    for kw in keywords:
        m = re.search(r"[A-Z]{2,}-\d+", kw.upper())
        if m:
            jira = m.group(0)
            break

    for branch in feature_branches:
        if jira and jira in branch.upper():
            return {
                "action": "reuse",
                "branch": branch,
                "reason": f"Existing feature branch matches Jira key {jira}",
            }

    on_feature = False
    current = ""
    for line in status.splitlines():
        if line.startswith("##"):
            current = line[3:].split("...")[0].strip()
            on_feature = current.startswith("feature/")
            break

    if on_feature and current:
        return {
            "action": "reuse",
            "branch": current,
            "reason": "Already on a feature branch — continue on current branch",
        }

    slug = re.sub(r"[^a-z0-9]+", "-", (keywords[0] if keywords else "task").lower())[:30].strip("-")
    new_branch = f"feature/{jira}-{slug}" if jira else f"feature/{slug}"
    return {
        "action": "create",
        "branch": new_branch,
        "reason": "No matching feature branch found — create new branch from develop/main",
        "commands": [
            "git checkout develop || git checkout main",
            "git pull",
            f"git checkout -b {new_branch}",
        ],
    }


def _build_summary(
    root: Path,
    modules: list[dict],
    themes: list[str],
    status: str,
    branch_strategy: dict,
) -> str:
    lines = [
        f"Project: {root}",
        f"Git: {status.splitlines()[0] if status else 'unknown'}",
        f"Custom modules: {len(modules)} ({', '.join(m['module'] for m in modules[:8]) or 'none'})",
        f"Design themes: {', '.join(themes[:6]) or 'default only'}",
        f"Branch strategy: {branch_strategy.get('action')} → {branch_strategy.get('branch')}",
    ]
    return "\n".join(lines)


def extract_keywords(requirement: dict) -> list[str]:
    parts: list[str] = []
    for key in ("jira_key", "title", "description", "summary"):
        val = requirement.get(key)
        if val:
            parts.append(str(val))
    for task in requirement.get("acceptance_criteria") or []:
        parts.append(str(task))
    tokens: list[str] = []
    for part in parts:
        tokens.extend(re.findall(r"[A-Za-z]{3,}", part))
    # preserve order, dedupe
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        low = t.lower()
        if low not in seen and low not in {"the", "and", "for", "with", "that", "this", "from"}:
            seen.add(low)
            out.append(t)
    if requirement.get("jira_key"):
        out.insert(0, str(requirement["jira_key"]))
    return out[:20]


def _current_branch(root: Path) -> str:
    _, out = _run_git(["branch", "--show-current"], root)
    return out.strip()


def _branch_exists(root: Path, name: str) -> bool:
    code, _ = _run_git(["show-ref", "--verify", f"refs/heads/{name}"], root)
    return code == 0


def ensure_git_branch(
    requirement: dict,
    *,
    branch_strategy: dict | None = None,
    keywords: list[str] | None = None,
) -> dict[str, Any]:
    """Create or checkout the feature branch in the Magento project."""
    if not settings.magento_git_create_branch:
        return {
            "success": True,
            "skipped": True,
            "reason": "MAGENTO_GIT_CREATE_BRANCH=false",
        }

    root = resolve_project_root()
    if not root:
        return {
            "success": False,
            "error": "MAGENTO_PROJECT_PATH not set or directory missing",
            "hint": "Set MAGENTO_PROJECT_PATH in .env and mount the project in docker-compose.yml",
        }

    _configure_git_safe_directory(root)

    code, _ = _run_git(["rev-parse", "--is-inside-work-tree"], root)
    if code != 0:
        return {"success": False, "error": f"Not a git repository: {root}"}

    kw = keywords or extract_keywords(requirement)
    strategy = branch_strategy or _suggest_branch(
        kw,
        _feature_branches(root),
        _git_status_short(root),
    )
    action = strategy.get("action", "create")
    branch_name = (strategy.get("branch") or "").strip()
    if not branch_name:
        return {"success": False, "error": "Could not determine branch name from task"}

    logs: list[str] = []

    def log_step(args: list[str]) -> tuple[int, str]:
        rc, out = _run_git(args, root)
        logs.append(f"$ git {' '.join(args)}\n{out or '(no output)'}")
        return rc, out

    current = _current_branch(root)
    if action == "reuse":
        if current == branch_name:
            return {
                "success": True,
                "action": "reuse",
                "branch": branch_name,
                "message": f"Already on branch {branch_name}",
                "logs": logs,
            }
        rc, out = log_step(["checkout", branch_name])
        if rc != 0:
            return {
                "success": False,
                "action": "reuse",
                "branch": branch_name,
                "error": out or f"Failed to checkout {branch_name}",
                "logs": logs,
            }
        return {
            "success": True,
            "action": "reuse",
            "branch": branch_name,
            "message": f"Checked out existing branch {branch_name}",
            "logs": logs,
        }

    if _branch_exists(root, branch_name):
        rc, out = log_step(["checkout", branch_name])
        if rc == 0:
            return {
                "success": True,
                "action": "checkout_existing",
                "branch": branch_name,
                "message": f"Branch {branch_name} already exists — checked out",
                "logs": logs,
            }
        return {
            "success": False,
            "branch": branch_name,
            "error": out or f"Branch exists but checkout failed: {branch_name}",
            "logs": logs,
        }

    _, porcelain = _run_git(["status", "--porcelain"], root)
    # Only block on tracked-file changes (not untracked ?? — those carry onto the new branch)
    blocking = [
        line for line in porcelain.splitlines()
        if line and (line[0] in "MADRCU" or line[1] in "MADRCU")
    ]
    if blocking:
        return {
            "success": False,
            "error": "Working tree has uncommitted changes to tracked files — commit or stash first",
            "status": "\n".join(blocking),
            "branch": branch_name,
            "logs": logs,
        }

    base = (settings.magento_git_base_branch or "develop").strip()
    rc, out = log_step(["checkout", base])
    if rc != 0:
        for fallback in ("main", "master"):
            if fallback == base:
                continue
            rc, out = log_step(["checkout", fallback])
            if rc == 0:
                base = fallback
                break
    if rc != 0:
        return {
            "success": False,
            "error": f"Could not checkout base branch ({base}): {out}",
            "logs": logs,
        }

    pull_rc, pull_out = log_step(["pull", "--ff-only"])
    if pull_rc != 0:
        logs.append(f"(warn) git pull skipped or failed: {pull_out}")

    rc, out = log_step(["checkout", "-b", branch_name])
    if rc != 0:
        return {
            "success": False,
            "error": out or f"Failed to create branch {branch_name}",
            "branch": branch_name,
            "base_branch": base,
            "logs": logs,
        }

    return {
        "success": True,
        "action": "create",
        "branch": branch_name,
        "base_branch": base,
        "message": f"Created and checked out {branch_name} from {base}",
        "logs": logs,
    }


def _feature_branches(root: Path) -> list[str]:
    _, branch_local = _run_git(["branch", "--list"], root)
    return [
        line.strip().lstrip("* ").strip()
        for line in branch_local.splitlines()
        if "feature/" in line.lower()
    ]


def _git_status_short(root: Path) -> str:
    _, status = _run_git(["status", "-sb"], root)
    return status
