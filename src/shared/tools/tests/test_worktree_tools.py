import shutil
import subprocess

import pytest

from conftest import load_tool_main

enter_worktree_main = load_tool_main("enter_worktree_tool").main
exit_worktree_main = load_tool_main("exit_worktree_tool").main

GIT_MISSING = shutil.which("git") is None


def _run_git(args, cwd):
    subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True
    )


@pytest.fixture
def git_repo(sandbox_dir):
    """Initialize a real git repo with one commit inside the sandbox root."""
    repo_dir = sandbox_dir / "repo"
    repo_dir.mkdir()

    _run_git(["init"], cwd=repo_dir)
    _run_git(["config", "user.email", "test@example.com"], cwd=repo_dir)
    _run_git(["config", "user.name", "Test User"], cwd=repo_dir)

    (repo_dir / "README.md").write_text("hello\n")
    _run_git(["add", "README.md"], cwd=repo_dir)
    _run_git(["commit", "-m", "initial commit"], cwd=repo_dir)

    return repo_dir


@pytest.mark.skipif(GIT_MISSING, reason="git is not available in this environment")
class TestEnterWorktreeTool:
    def test_enter_worktree_happy_path(self, sandbox_dir, git_repo):
        result = enter_worktree_main(repo_path="repo", name="feature-x")

        assert result.startswith("Created worktree 'feature-x'")
        assert (sandbox_dir / ".worktrees" / "feature-x").exists()
        assert (sandbox_dir / ".worktrees" / "feature-x" / "README.md").exists()

    def test_enter_worktree_generates_name_when_omitted(self, sandbox_dir, git_repo):
        result = enter_worktree_main(repo_path="repo")

        assert result.startswith("Created worktree '")
        assert (sandbox_dir / ".worktrees").exists()
        assert any((sandbox_dir / ".worktrees").iterdir())

    def test_enter_worktree_duplicate_name_returns_error(self, sandbox_dir, git_repo):
        first = enter_worktree_main(repo_path="repo", name="dup")
        assert first.startswith("Created worktree")

        second = enter_worktree_main(repo_path="repo", name="dup")

        assert second.startswith("Error:")
        assert "already exists" in second

    def test_enter_worktree_non_repo_returns_error(self, sandbox_dir):
        plain_dir = sandbox_dir / "not_a_repo"
        plain_dir.mkdir()

        result = enter_worktree_main(repo_path="not_a_repo")

        assert result.startswith("Error:")
        assert "is not a git repository" in result

    def test_enter_worktree_missing_repo_path_returns_error(self, sandbox_dir):
        result = enter_worktree_main(repo_path="")

        assert result.startswith("Error:")
        assert "repo_path" in result

    def test_enter_worktree_invalid_name_returns_error(self, sandbox_dir, git_repo):
        result = enter_worktree_main(repo_path="repo", name="../escape")

        assert result.startswith("Error:")
        assert "letters, digits" in result

    def test_enter_worktree_path_escape_returns_permission_error(self, sandbox_dir):
        result = enter_worktree_main(repo_path="../../etc")

        assert result.startswith("Error:")
        assert "outside the allowed directory" in result


@pytest.mark.skipif(GIT_MISSING, reason="git is not available in this environment")
class TestExitWorktreeTool:
    def test_exit_worktree_round_trip_clean(self, sandbox_dir, git_repo):
        enter_result = enter_worktree_main(repo_path="repo", name="clean-wt")
        assert enter_result.startswith("Created worktree")

        worktree_path = ".worktrees/clean-wt"
        exit_result = exit_worktree_main(worktree_path=worktree_path)

        assert exit_result.startswith("Removed worktree")
        assert "clean" in exit_result
        assert not (sandbox_dir / ".worktrees" / "clean-wt").exists()

    def test_exit_worktree_keep_true_preserves_it(self, sandbox_dir, git_repo):
        enter_worktree_main(repo_path="repo", name="kept-wt")

        exit_result = exit_worktree_main(worktree_path=".worktrees/kept-wt", keep=True)

        assert "kept" in exit_result
        assert (sandbox_dir / ".worktrees" / "kept-wt").exists()

    def test_exit_worktree_keep_true_with_dirty_tree(self, sandbox_dir, git_repo):
        enter_worktree_main(repo_path="repo", name="dirty-kept-wt")
        worktree_dir = sandbox_dir / ".worktrees" / "dirty-kept-wt"
        (worktree_dir / "scratch.txt").write_text("uncommitted work")

        exit_result = exit_worktree_main(
            worktree_path=".worktrees/dirty-kept-wt", keep=True
        )

        assert "kept" in exit_result
        assert "uncommitted changes were preserved" in exit_result
        assert worktree_dir.exists()
        assert (worktree_dir / "scratch.txt").exists()

    def test_exit_worktree_discards_uncommitted_changes_when_not_kept(
        self, sandbox_dir, git_repo
    ):
        enter_worktree_main(repo_path="repo", name="dirty-wt")
        worktree_dir = sandbox_dir / ".worktrees" / "dirty-wt"
        (worktree_dir / "scratch.txt").write_text("uncommitted work")

        exit_result = exit_worktree_main(worktree_path=".worktrees/dirty-wt")

        assert exit_result.startswith("Removed worktree")
        assert "forced" in exit_result
        assert not worktree_dir.exists()

    def test_exit_worktree_missing_path_returns_error(self, sandbox_dir):
        result = exit_worktree_main(worktree_path="")

        assert result.startswith("Error:")
        assert "worktree_path" in result

    def test_exit_worktree_nonexistent_path_returns_error(self, sandbox_dir):
        result = exit_worktree_main(worktree_path=".worktrees/does-not-exist")

        assert result.startswith("Error:")
        assert "does not exist" in result

    def test_exit_worktree_non_worktree_path_returns_error(self, sandbox_dir):
        plain_dir = sandbox_dir / "plain"
        plain_dir.mkdir()

        result = exit_worktree_main(worktree_path="plain")

        assert result.startswith("Error:")
        assert "is not a git worktree" in result

    def test_exit_worktree_path_escape_returns_permission_error(self, sandbox_dir):
        result = exit_worktree_main(worktree_path="../../etc")

        assert result.startswith("Error:")
        assert "outside the allowed directory" in result
