"""Git branch naming validation and creation for the AI workflow."""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

# Git refname rules: no spaces, ~, ^, :, ?, *, [, \, .., @{, cannot start with - or end with . or /
_BRANCH_PATTERN = re.compile(
    r"^(?!-)(?!.*\.\.)(?!.*//)(?!.*@\{)(?!.*[~^:?*\[\]\\])(?!.*\s)(?!.*\.$)(?!.*/$)"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9._/-]*[a-zA-Z0-9])?$"
)
_DEFAULT_PREFIX = "sm-new"
_DEFAULT_PATTERN = re.compile(rf"^{re.escape(_DEFAULT_PREFIX)}(\d+)$")
_BASE_BRANCH = "main"


def _git_cmd(repo_path: Path, *args: str) -> list[str]:
    resolved = str(repo_path.resolve())
    return ["git", "-c", f"safe.directory={resolved}", "-C", resolved, *args]


def get_git_repo_path() -> Path:
    configured = (settings.git_repo_path or "").strip()
    candidates: list[Path] = []

    if configured:
        candidates.append(Path(configured))

    workspace = Path(settings.workflow_workspace).resolve()
    candidates.append(workspace.parent.parent)

    for parent in workspace.parents:
        if (parent / ".git").exists():
            candidates.append(parent)
            break

    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if _is_git_repo(resolved):
            return resolved

    return candidates[0].resolve() if candidates else workspace.parent.parent


def _is_git_repo(path: Path) -> bool:
    if not path.is_dir():
        return False
    return _run_git(path, "rev-parse", "--is-inside-work-tree").returncode == 0


def validate_branch_name(name: str) -> tuple[bool, str | None]:
    trimmed = (name or "").strip()
    if not trimmed:
        return False, "Branch name is required."
    if len(trimmed) > 255:
        return False, "Branch name must be 255 characters or fewer."
    if trimmed.startswith("-") or trimmed.endswith(".") or trimmed.endswith("/"):
        return False, "Branch name cannot start with '-' or end with '.' or '/'."
    if ".." in trimmed or "@{" in trimmed:
        return False, "Branch name contains invalid characters or sequences."
    if not _BRANCH_PATTERN.match(trimmed):
        return (
            False,
            "Use only letters, numbers, hyphens, underscores, slashes, and dots. "
            "Avoid spaces and special characters (~, ^, :, ?, *, [, \\).",
        )
    return True, None


def _run_git(repo_path: Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        return subprocess.run(
            _git_cmd(repo_path, *args),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        logger.warning("git %s timed out after %ss", " ".join(args), timeout)
        return subprocess.CompletedProcess(
            args=["git", *args],
            returncode=124,
            stdout=exc.stdout.decode() if exc.stdout else "",
            stderr=exc.stderr.decode() if exc.stderr else f"git command timed out after {timeout}s",
        )


def list_branches(repo_path: Path | None = None) -> list[str]:
    repo = repo_path or get_git_repo_path()
    if not _is_git_repo(repo):
        return []

    local = _run_git(repo, "branch", "--format=%(refname:short)")
    remote = _run_git(repo, "branch", "-r", "--format=%(refname:short)")
    names: set[str] = set()
    for proc in (local, remote):
        if proc.returncode != 0:
            continue
        for line in proc.stdout.splitlines():
            branch = line.strip()
            if not branch or branch.endswith("/HEAD"):
                continue
            if branch.startswith("origin/"):
                branch = branch[len("origin/") :]
            names.add(branch)
    return sorted(names)


def branch_exists(name: str, repo_path: Path | None = None) -> bool:
    trimmed = (name or "").strip()
    if not trimmed:
        return False
    return trimmed in list_branches(repo_path)


def next_default_branch_name(repo_path: Path | None = None, prefix: str = _DEFAULT_PREFIX) -> str:
    branches = list_branches(repo_path)
    highest = 0
    for branch in branches:
        match = _DEFAULT_PATTERN.match(branch)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}{highest + 1}"


def _resolve_base_branch(repo: Path) -> tuple[str | None, str | None]:
    """Resolve the ref to branch from (always main). Returns (ref, error)."""
    fetch = _run_git(repo, "fetch", "origin", _BASE_BRANCH, timeout=10)
    if fetch.returncode not in (0, 124):
        logger.info("git fetch origin %s skipped: %s", _BASE_BRANCH, (fetch.stderr or fetch.stdout).strip())

    remote_ref = f"origin/{_BASE_BRANCH}"
    if _run_git(repo, "rev-parse", "--verify", remote_ref, timeout=10).returncode == 0:
        return remote_ref, None

    if _run_git(repo, "rev-parse", "--verify", _BASE_BRANCH, timeout=10).returncode == 0:
        return _BASE_BRANCH, None

    return None, (
        f"Base branch '{_BASE_BRANCH}' was not found locally or on origin. "
        "Cannot create a new branch."
    )


def create_branch(name: str, repo_path: Path | None = None) -> dict:
    repo = repo_path or get_git_repo_path()
    trimmed = (name or "").strip()

    valid, error = validate_branch_name(trimmed)
    if not valid:
        return {"success": False, "branch_name": trimmed, "error": error}

    if branch_exists(trimmed, repo):
        return {
            "success": False,
            "branch_name": trimmed,
            "error": "Branch already exists. Please choose a different branch name.",
        }

    if not repo.is_dir():
        return {"success": False, "branch_name": trimmed, "error": f"Git repository not found at {repo}."}

    git_check = _run_git(repo, "rev-parse", "--is-inside-work-tree")
    if git_check.returncode != 0:
        stderr = (git_check.stderr or git_check.stdout or "").strip()
        return {
            "success": False,
            "branch_name": trimmed,
            "error": (
                f"Git repository is not available at {repo}."
                + (f" {stderr}" if stderr else " Configure GIT_REPO_PATH.")
            ),
        }

    base_ref, base_error = _resolve_base_branch(repo)
    if not base_ref:
        return {"success": False, "branch_name": trimmed, "error": base_error}

    proc = _run_git(repo, "checkout", "-b", trimmed, base_ref, timeout=30)
    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "git checkout failed").strip()
        return {"success": False, "branch_name": trimmed, "error": stderr}

    return {
        "success": True,
        "branch_name": trimmed,
        "base_branch": _BASE_BRANCH,
        "message": f"Created and checked out branch '{trimmed}' from '{_BASE_BRANCH}'.",
    }
