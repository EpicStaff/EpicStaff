# Enter Worktree Tool
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

WORKTREES_DIR_NAME = ".worktrees"
NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
GIT_TIMEOUT_SECONDS = 60


class RouteTool:
    @staticmethod
    def _is_path_within_path(source_path: Path, dest_path: Path) -> bool:
        source_path = source_path.resolve()
        dest_path = dest_path.resolve()
        return dest_path in source_path.parents or source_path == dest_path

    @staticmethod
    def is_path_has_permission(path: Path | str) -> bool:
        save_file_path = os.getenv("CONTAINER_SAVEFILES_PATH", ".")
        return RouteTool._is_path_within_path(path, Path(save_file_path))

    def construct_savepath(self, *, frompath: Path | str) -> Path:
        save_file_path = os.getenv("CONTAINER_SAVEFILES_PATH", ".")
        return Path(save_file_path) / Path(frompath)


def _run_git(args: list[str], cwd: Path):
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", f"git command timed out after {GIT_TIMEOUT_SECONDS} seconds."
    except Exception as e:
        return 1, "", str(e)


def main(repo_path: str, name: str | None = None) -> str:
    """
    Create an isolated git worktree on a new branch for a repo inside the
    sandbox working root, under a managed .worktrees/<name> directory. Never
    raises: all failures are returned as readable error strings.
    """
    try:
        if not repo_path:
            return (
                "Error: repo_path argument is mandatory and was not given to the tool."
            )

        if shutil.which("git") is None:
            return "Error: git is not available in this environment."

        route_tool = RouteTool()
        repo_savepath = route_tool.construct_savepath(frompath=repo_path)

        if not RouteTool.is_path_has_permission(repo_savepath):
            return f"Error: path {repo_path} is outside the allowed directory."

        if not repo_savepath.exists():
            return f"Error: path {repo_path} does not exist."

        returncode, stdout, stderr = _run_git(
            ["rev-parse", "--is-inside-work-tree"], cwd=repo_savepath
        )
        if returncode != 0 or stdout.strip() != "true":
            return (
                f"Error: {repo_path} is not a git repository "
                f"({stderr.strip() or stdout.strip() or 'git rev-parse failed'})."
            )

        if name:
            if not NAME_PATTERN.match(name):
                return "Error: name may only contain letters, digits, '.', '_' and '-'."
            worktree_name = name
        else:
            worktree_name = uuid.uuid4().hex[:12]

        working_root = Path(os.getenv("CONTAINER_SAVEFILES_PATH", "."))
        worktrees_dir = working_root / WORKTREES_DIR_NAME
        worktree_path = worktrees_dir / worktree_name

        if not RouteTool.is_path_has_permission(worktree_path):
            return "Error: computed worktree path is outside the allowed directory."

        if worktree_path.exists():
            return (
                f"Error: worktree '{worktree_name}' already exists at {worktree_path}. "
                "Choose a different name."
            )

        worktrees_dir.mkdir(parents=True, exist_ok=True)

        branch_name = f"worktree/{worktree_name}"

        returncode, stdout, stderr = _run_git(
            ["worktree", "add", "-b", branch_name, str(worktree_path.resolve())],
            cwd=repo_savepath,
        )
        if returncode != 0:
            return (
                f"Error: failed to create worktree: {stderr.strip() or stdout.strip()}"
            )

        try:
            relative_worktree_path = worktree_path.resolve().relative_to(
                working_root.resolve()
            )
        except ValueError:
            relative_worktree_path = worktree_path

        return (
            f"Created worktree '{worktree_name}' on new branch '{branch_name}' at "
            f"{relative_worktree_path}"
        )
    except Exception as e:
        return f"Error: failed to create worktree. Unexpected exception: {e}"
