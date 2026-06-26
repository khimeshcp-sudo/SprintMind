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


def _configure_git_identity(root: Path) -> None:
    """Set commit author for the repo (required in Docker where no global identity exists)."""
    name = (settings.magento_git_user_name or "SprintMind Bot").strip()
    email = (settings.magento_git_user_email or "sprintmind-bot@users.noreply.github.com").strip()
    _run_git(["config", "user.name", name], root)
    _run_git(["config", "user.email", email], root)
    _run(
        ["git", "config", "--global", "user.name", name],
        root,
    )
    _run(
        ["git", "config", "--global", "user.email", email],
        root,
    )


def _git_identity_config_args() -> list[str]:
    name = (settings.magento_git_user_name or "SprintMind Bot").strip()
    email = (settings.magento_git_user_email or "sprintmind-bot@users.noreply.github.com").strip()
    return ["-c", f"user.name={name}", "-c", f"user.email={email}"]


def _run_git_commit(root: Path, message: str, timeout: int = 30) -> tuple[int, str]:
    """Commit with explicit author — avoids failures when repo/global git identity is unset."""
    safe = str(root.resolve())
    return _run(
        ["git", "-c", f"safe.directory={safe}", *_git_identity_config_args(), "commit", "-m", message],
        root,
        timeout,
    )


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


def _friendly_git_error(message: str) -> str:
    text = (message or "").strip()
    lower = text.lower()
    if "author identity unknown" in lower or "tell me who you are" in lower:
        return (
            "Git commit author is not configured. Set MAGENTO_GIT_USER_NAME and "
            "MAGENTO_GIT_USER_EMAIL in .env, then retry."
        )
    if "permission denied" in lower or "returned error: 403" in lower:
        return (
            "Git push denied: the configured GitHub token does not have write access to "
            "this repository. Use a token from an account with push permission (repo scope) "
            "or grant the token user write access to the repo."
        )
    if "could not read username" in lower:
        return (
            "Git push failed: remote requires authentication. Ensure MAGENTO_GIT_API_TOKEN "
            "is set to a GitHub personal access token with repo scope."
        )
    return text


def _api_error_message(data: dict | list | str, fallback: str = "") -> str:
    if isinstance(data, str):
        return data or fallback
    if isinstance(data, list):
        parts = []
        for item in data:
            if isinstance(item, dict):
                parts.append(item.get("message") or str(item))
            else:
                parts.append(str(item))
        return "; ".join(parts) or fallback
    if isinstance(data, dict):
        msg = data.get("message") or data.get("error")
        if isinstance(msg, list):
            return "; ".join(str(m) for m in msg)
        if msg:
            return str(msg)
        if data.get("errors"):
            return _api_error_message(data["errors"], fallback)
    return fallback


def commit_changes(
    root: Path,
    branch_name: str,
    message: str,
    *,
    paths: list[str] | None = None,
) -> dict[str, Any]:
    """Stage and commit generated changes on the target branch."""
    _configure_git_safe_directory(root)
    _configure_git_identity(root)

    code, _ = _run_git(["rev-parse", "--is-inside-work-tree"], root)
    if code != 0:
        return {"success": False, "error": f"Not a git repository: {root}"}

    logs: list[str] = []

    def log_step(args: list[str]) -> tuple[int, str]:
        rc, out = _run_git(args, root)
        logs.append(f"$ git {' '.join(args)}\n{out or '(no output)'}")
        return rc, out

    current = _current_branch(root)
    if current != branch_name:
        rc, out = log_step(["checkout", branch_name])
        if rc != 0:
            return {
                "success": False,
                "error": out or f"Failed to checkout branch {branch_name}",
                "logs": logs,
            }

    if paths:
        for rel in paths:
            rel = rel.strip().lstrip("/")
            if not rel:
                continue
            rc, out = log_step(["add", "--", rel])
            if rc != 0:
                return {
                    "success": False,
                    "error": out or f"Failed to stage {rel}",
                    "logs": logs,
                }
    rc, out = log_step(["add", "-A"])
    if rc != 0:
        return {
            "success": False,
            "error": out or "Failed to stage changes",
            "logs": logs,
        }

    _, porcelain = _run_git(["status", "--porcelain"], root)
    if not porcelain.strip():
        return {
            "success": True,
            "branch": branch_name,
            "skipped": True,
            "message": "No changes to commit",
            "logs": logs,
        }

    rc, out = _run_git_commit(root, message)
    logs.append(f"$ git commit -m {message!r}\n{out or '(no output)'}")
    if rc != 0:
        return {
            "success": False,
            "error": _friendly_git_error(out or "Git commit failed"),
            "logs": logs,
        }

    return {
        "success": True,
        "branch": branch_name,
        "message": message,
        "output": out,
        "logs": logs,
    }


def _remote_origin_url(root: Path) -> str:
    _, out = _run_git(["remote", "get-url", "origin"], root)
    return out.strip()


def _with_git_token(remote_url: str) -> str | None:
    """Return HTTPS remote URL with API token embedded for non-interactive push/pull."""
    token = (settings.magento_git_api_token or "").strip()
    if not token or not remote_url:
        return None
    if remote_url.startswith("git@"):
        return None
    if "://" in remote_url:
        scheme, rest = remote_url.split("://", 1)
        if "@" in rest.split("/")[0]:
            return remote_url
        provider = _git_provider()
        user = "oauth2" if provider == "gitlab" else "x-access-token"
        return f"{scheme}://{user}:{token}@{rest}"
    return None


def _run_git_authenticated(args: list[str], root: Path) -> tuple[int, str]:
    """Run git using a temporary authenticated origin URL when a token is configured."""
    remote_url = _remote_origin_url(root)
    auth_url = _with_git_token(remote_url)
    if not auth_url:
        return _run_git(args, root)

    rc_set, set_out = _run_git(["remote", "set-url", "origin", auth_url], root)
    if rc_set != 0:
        return rc_set, set_out or "Failed to configure authenticated git remote"
    try:
        return _run_git(args, root)
    finally:
        _run_git(["remote", "set-url", "origin", remote_url], root)


def push_branch(root: Path, branch_name: str) -> dict[str, Any]:
    _configure_git_safe_directory(root)
    rc, out = _run_git_authenticated(["push", "-u", "origin", branch_name], root)
    return {
        "success": rc == 0,
        "branch": branch_name,
        "output": out,
        "error": None if rc == 0 else _friendly_git_error(out),
    }


def _git_provider() -> str:
    base = (settings.magento_git_api_base_url or "").lower()
    if "/repos/" in base or "github" in base:
        return "github"
    return "gitlab"


def create_merge_request(branch_name: str) -> dict[str, Any]:
    if not settings.magento_git_api_base_url or not settings.magento_git_api_token:
        return {
            "success": False,
            "error": "Git API base URL or token not configured",
        }

    import httpx

    provider = _git_provider()
    base = settings.magento_git_api_base_url.rstrip("/")
    target_branch = settings.magento_git_base_branch or "main"
    title = f"Merge {branch_name} into {target_branch}"
    description = "Auto-generated merge request from SprintMind AI workflow."
    headers = {
        "Content-Type": "application/json",
    }
    if provider == "github":
        headers["Authorization"] = f"token {settings.magento_git_api_token}"
    else:
        headers["Authorization"] = f"Bearer {settings.magento_git_api_token}"

    try:
        with httpx.Client(timeout=30.0) as client:
            if provider == "github":
                url = f"{base}/pulls"
                payload = {
                    "title": title,
                    "head": branch_name,
                    "base": target_branch,
                    "body": description,
                }
            else:
                url = f"{base}/merge_requests"
                payload = {
                    "source_branch": branch_name,
                    "target_branch": target_branch,
                    "title": title,
                    "description": description,
                }
            res = client.post(url, json=payload, headers=headers)
        data = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
        if res.status_code not in (200, 201):
            if provider == "github" and res.status_code == 422:
                existing = _find_existing_github_pull(base, branch_name, target_branch, headers)
                if existing:
                    return existing
            return {
                "success": False,
                "error": _api_error_message(data, res.text),
                "status_code": res.status_code,
            }
        return {
            "success": True,
            "id": data.get("number") or data.get("iid") or data.get("id"),
            "web_url": data.get("html_url") or data.get("web_url") or data.get("url") or data.get("http_url_to_repo"),
            "data": data,
            "provider": provider,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _find_existing_github_pull(
    base: str,
    branch_name: str,
    target_branch: str,
    headers: dict[str, str],
) -> dict[str, Any] | None:
    import httpx

    owner = base.rstrip("/").split("/repos/")[-1].split("/")[0] if "/repos/" in base else ""
    head = f"{owner}:{branch_name}" if owner else branch_name
    try:
        with httpx.Client(timeout=30.0) as client:
            res = client.get(
                f"{base}/pulls",
                params={"head": head, "base": target_branch, "state": "open"},
                headers=headers,
            )
        if res.status_code != 200:
            return None
        pulls = res.json()
        if not pulls:
            return None
        pr = pulls[0]
        return {
            "success": True,
            "id": pr.get("number"),
            "web_url": pr.get("html_url"),
            "data": pr,
            "provider": "github",
            "existing": True,
        }
    except Exception:
        return None


def merge_merge_request(mr_id: str | int, mr_url: str | None = None) -> dict[str, Any]:
    if not settings.magento_git_api_base_url or not settings.magento_git_api_token:
        return {
            "success": False,
            "error": "Git API base URL or token not configured",
        }

    import httpx

    provider = _git_provider()
    base = settings.magento_git_api_base_url.rstrip("/")
    if provider == "github":
        endpoint = f"{base}/pulls/{mr_id}/merge"
    else:
        endpoint = f"{base}/merge_requests/{mr_id}/merge"

    headers = {
        "Content-Type": "application/json",
    }
    if provider == "github":
        headers["Authorization"] = f"token {settings.magento_git_api_token}"
    else:
        headers["Authorization"] = f"Bearer {settings.magento_git_api_token}"

    try:
        with httpx.Client(timeout=30.0) as client:
            res = client.put(endpoint, headers=headers)
        data = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
        if res.status_code not in (200, 201):
            return {
                "success": False,
                "error": _api_error_message(data, res.text),
                "status_code": res.status_code,
                "mergeable": False,
            }
        return {"success": True, "data": data, "web_url": mr_url, "merged": True}
    except Exception as exc:
        return {"success": False, "error": str(exc), "mergeable": False}


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
    # Auto-stash tracked changes to allow branch creation
    blocking = [
        line for line in porcelain.splitlines()
        if line and (line[0] in "MADRCU" or line[1] in "MADRCU")
    ]
    if blocking:
        logs.append(f"Uncommitted changes detected — auto-stashing: {len(blocking)} file(s)")
        stash_rc, stash_out = log_step(["stash", "push", "-m", f"auto-stash-for-{branch_name}"])
        if stash_rc != 0:
            logs.append(f"(warn) git stash failed: {stash_out}")
            # Still try to proceed — stash might not be critical

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

    pull_rc, pull_out = _run_git_authenticated(["pull", "--ff-only", "origin", base], root)
    logs.append(f"$ git pull --ff-only origin {base}\n{pull_out or '(no output)'}")
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
