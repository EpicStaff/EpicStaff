# Exit Worktree Tool
import os
import shutil
import subprocess
from pathlib import Path

GIT_TIMEOUT_SECONDS = 60
GITDIR_PREFIX = "gitdir:"


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


def _resolve_from(base: Path, path_text: str) -> Path:
    path = Path(path_text.strip())
    return path if path.is_absolute() else base / path


def _read_worktree_git_dir(worktree_path: Path) -> Path | None:
    """The git dir a linked worktree's .git file points to, or None when the
    path is not a linked worktree."""
    dot_git = worktree_path / ".git"
    if not dot_git.is_file():
        return None

    content = dot_git.read_text(errors="replace").strip()
    if not content.startswith(GITDIR_PREFIX):
        return None
    return _resolve_from(worktree_path, content[len(GITDIR_PREFIX) :])


def _read_common_dir(git_dir: Path) -> Path:
    """The main repository's git dir, named by the worktree git dir's
    commondir file, as git itself resolves it."""
    commondir_file = git_dir / "commondir"
    if not commondir_file.is_file():
        return git_dir
    return _resolve_from(git_dir, commondir_file.read_text(errors="replace"))


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

        # The worktree's .git file and its git dir's commondir file both sit in
        # the writable root and can name any repository. Both are read here
        # and checked, and every git call names its git dir explicitly:
        # letting git discover the repository from cwd would follow pointers
        # nobody checked. Paths are resolved once, so git gets exactly the paths
        # that were checked and a relative root is not re-applied to git's cwd.
        worktree_dir = worktree_savepath.resolve()
        git_dir = _read_worktree_git_dir(worktree_dir)
        if git_dir is None:
            return f"Error: {worktree_path} is not a git worktree."
        git_dir = git_dir.resolve()

        common_dir = _read_common_dir(git_dir).resolve()
        if not (
            RouteTool.is_path_has_permission(git_dir)
            and RouteTool.is_path_has_permission(common_dir)
        ):
            return (
                f"Error: the repository of worktree {worktree_path} "
                "is outside the allowed directory."
            )

        worktree_git_args = ["--git-dir", str(git_dir), "--work-tree", str(worktree_dir)]
        returncode, stdout, stderr = _run_git(
            [*worktree_git_args, "rev-parse", "--is-inside-work-tree"], cwd=worktree_dir
        )
        if returncode != 0 or stdout.strip() != "true":
            return f"Error: {worktree_path} is not a git worktree."

        keep = bool(keep)

        if keep:
            returncode, stdout, stderr = _run_git(
                [*worktree_git_args, "status", "--porcelain"], cwd=worktree_dir
            )
            if returncode == 0 and stdout.strip():
                return (
                    f"Worktree kept at {worktree_path} (not removed) — "
                    "uncommitted changes were preserved."
                )
            return f"Worktree kept at {worktree_path} (not removed)."

        # Run from the main repository, not from the worktree being removed.
        main_git_args = ["--git-dir", str(common_dir)]
        returncode, stdout, stderr = _run_git(
            [*main_git_args, "worktree", "remove", str(worktree_dir)],
            cwd=common_dir,
        )
        if returncode == 0:
            return f"Removed worktree at {worktree_path} (clean, no uncommitted changes)."

        # A refusal here is almost always due to uncommitted/untracked
        # changes. keep=False means the caller explicitly wants the worktree
        # discarded, so force the removal.
        returncode, stdout, stderr = _run_git(
            [*main_git_args, "worktree", "remove", "--force", str(worktree_dir)],
            cwd=common_dir,
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
