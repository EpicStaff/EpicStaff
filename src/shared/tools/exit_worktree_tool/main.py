# Exit Worktree Tool
import os
import shutil
import subprocess
from pathlib import Path

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


def _find_main_repo_root(worktree_path: Path):
    """The main repository root — 'git worktree remove' must be run from
    there (or from another linked worktree), not from the worktree being
    removed itself."""
    returncode, stdout, stderr = _run_git(
        ["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=worktree_path
    )
    if returncode != 0:
        return None, stderr.strip() or stdout.strip()

    common_dir = Path(stdout.strip())
    main_root = common_dir.parent if common_dir.name == ".git" else common_dir
    return main_root, None


def main(worktree_path: str, keep: bool = False) -> str:
    """
    Remove a git worktree created by the Enter Worktree Tool, or preserve it
    when keep=True. keep=True never removes the worktree, whether it is clean
    or dirty — preserving uncommitted work is the safe outcome, and the
    returned message says so explicitly when changes are present. If a plain
    removal is refused (uncommitted changes) and keep=False, retries with
    --force since keep=False is an explicit request to discard the worktree.
    Never raises: all failures are returned as readable error strings.
    """
    try:
        if not worktree_path:
            return "Error: worktree_path argument is mandatory and was not given to the tool."

        if shutil.which("git") is None:
            return "Error: git is not available in this environment."

        route_tool = RouteTool()
        worktree_savepath = route_tool.construct_savepath(frompath=worktree_path)

        if not RouteTool.is_path_has_permission(worktree_savepath):
            return f"Error: path {worktree_path} is outside the allowed directory."

        if not worktree_savepath.exists():
            return f"Error: worktree path {worktree_path} does not exist."

        returncode, stdout, stderr = _run_git(
            ["rev-parse", "--is-inside-work-tree"], cwd=worktree_savepath
        )
        if returncode != 0 or stdout.strip() != "true":
            return f"Error: {worktree_path} is not a git worktree."

        keep = bool(keep)

        if keep:
            returncode, stdout, stderr = _run_git(
                ["status", "--porcelain"], cwd=worktree_savepath
            )
            if returncode == 0 and stdout.strip():
                return (
                    f"Worktree kept at {worktree_path} (not removed) — "
                    "uncommitted changes were preserved."
                )
            return f"Worktree kept at {worktree_path} (not removed)."

        main_root, error = _find_main_repo_root(worktree_savepath)
        if error or main_root is None:
            return (
                f"Error: could not locate the main repository for worktree "
                f"{worktree_path}: {error}"
            )

        returncode, stdout, stderr = _run_git(
            ["worktree", "remove", str(worktree_savepath.resolve())], cwd=main_root
        )
        if returncode == 0:
            return (
                f"Removed worktree at {worktree_path} (clean, no uncommitted changes)."
            )

        # A refusal here is almost always due to uncommitted/untracked
        # changes. keep=False means the caller explicitly wants the worktree
        # discarded, so force the removal.
        returncode, stdout, stderr = _run_git(
            ["worktree", "remove", "--force", str(worktree_savepath.resolve())],
            cwd=main_root,
        )
        if returncode != 0:
            return (
                f"Error: failed to remove worktree {worktree_path}: "
                f"{stderr.strip() or stdout.strip()}"
            )

        return (
            f"Removed worktree at {worktree_path} "
            "(forced — uncommitted changes were discarded)."
        )
    except Exception as e:
        return f"Error: failed to remove worktree. Unexpected exception: {e}"
