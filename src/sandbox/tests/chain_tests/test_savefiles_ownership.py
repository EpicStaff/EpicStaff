"""Coverage for giving sandboxuser ownership of the savefiles root.

Only `os.chown` (and, for the run() tests, `os.geteuid`) are faked: a non-root
test process cannot chown a directory to another uid, and the privilege drop
branch only runs as root. `os.lstat` runs for real against tmp_path, so the
"already owned" and "symlink" decisions are made from real filesystem state.
"""

import os
from pathlib import Path

import pytest

pytest.importorskip(
    "pwd",
    reason="POSIX-only: sandbox isolation requires pwd/landlock; runs in the Linux image",
)

import dynamic_venv_executor_chain
from dynamic_venv_executor_chain import AbstractHandler, DynamicVenvExecutorChain
from savefiles_ownership import ensure_savefiles_writable
from src.shared.models import CodeResultData
from utils.logger import logger


@pytest.fixture
def warnings_logged():
    messages: list[str] = []
    handler_id = logger.add(
        lambda message: messages.append(message.record["message"]), level="WARNING"
    )
    yield messages
    logger.remove(handler_id)


@pytest.fixture
def info_logged():
    messages: list[str] = []
    handler_id = logger.add(
        lambda message: messages.append(message.record["message"]),
        level="INFO",
        filter=lambda record: record["level"].name == "INFO",
    )
    yield messages
    logger.remove(handler_id)


@pytest.fixture
def chown_calls(monkeypatch):
    calls: list[tuple[Path, int, int]] = []

    def _record_chown(path, uid, gid, **kwargs):
        calls.append((Path(path), uid, gid))

    monkeypatch.setattr(os, "chown", _record_chown)
    yield calls


@pytest.fixture
def savefiles_root(tmp_path) -> Path:
    root = tmp_path / "savefiles"
    root.mkdir()
    return root


def _other_uid_and_gid(path: Path) -> tuple[int, int]:
    """Return a uid:gid pair that differs from the owner of path."""
    path_stat = os.lstat(path)
    return path_stat.st_uid + 1, path_stat.st_gid + 1


class TestEnsureSavefilesWritable:
    def test_chowns_when_owner_differs(self, savefiles_root, chown_calls):
        uid, gid = _other_uid_and_gid(savefiles_root)

        ensure_savefiles_writable(savefiles_root, uid, gid)

        assert chown_calls == [(savefiles_root, uid, gid)]

    def test_does_not_follow_symlinks_when_chowning(
        self, savefiles_root, monkeypatch
    ):
        recorded_kwargs: dict = {}
        monkeypatch.setattr(
            os, "chown", lambda path, uid, gid, **kwargs: recorded_kwargs.update(kwargs)
        )
        uid, gid = _other_uid_and_gid(savefiles_root)

        ensure_savefiles_writable(savefiles_root, uid, gid)

        assert recorded_kwargs == {"follow_symlinks": False}

    def test_does_not_touch_existing_children(
        self, savefiles_root, chown_calls
    ):
        (savefiles_root / "existing_dir").mkdir()
        (savefiles_root / "existing_file.txt").write_text("data")
        uid, gid = _other_uid_and_gid(savefiles_root)

        ensure_savefiles_writable(savefiles_root, uid, gid)

        assert [path for path, _, _ in chown_calls] == [savefiles_root]

    def test_skips_when_already_owned_by_target_uid(self, savefiles_root, chown_calls):
        root_stat = os.lstat(savefiles_root)

        # A different gid is fine: the owner bits already make it writable.
        ensure_savefiles_writable(savefiles_root, root_stat.st_uid, root_stat.st_gid + 1)

        assert chown_calls == []

    def test_logs_the_owner_change(self, savefiles_root, chown_calls, info_logged):
        uid, gid = _other_uid_and_gid(savefiles_root)

        ensure_savefiles_writable(savefiles_root, uid, gid)

        assert len(info_logged) == 1
        assert str(savefiles_root) in info_logged[0]

    def test_does_not_log_when_nothing_changes(self, savefiles_root, chown_calls, info_logged):
        root_stat = os.lstat(savefiles_root)

        ensure_savefiles_writable(savefiles_root, root_stat.st_uid, root_stat.st_gid)

        assert info_logged == []

    def test_relative_path_resolves_against_working_directory(
        self, savefiles_root, chown_calls, monkeypatch
    ):
        monkeypatch.chdir(savefiles_root)
        uid, gid = _other_uid_and_gid(savefiles_root)

        ensure_savefiles_writable(".", uid, gid)

        assert chown_calls == [(savefiles_root, uid, gid)]

    def test_trailing_slash_is_accepted(self, savefiles_root, chown_calls):
        uid, gid = _other_uid_and_gid(savefiles_root)

        ensure_savefiles_writable(f"{savefiles_root}/", uid, gid)

        assert chown_calls == [(savefiles_root, uid, gid)]

    def test_symlinked_root_is_not_followed(
        self, tmp_path, chown_calls, warnings_logged
    ):
        target = tmp_path / "elsewhere"
        target.mkdir()
        link = tmp_path / "savefiles_link"
        link.symlink_to(target)
        uid, gid = _other_uid_and_gid(target)

        # A trailing slash would make a naive lstat resolve the link.
        ensure_savefiles_writable(f"{link}/", uid, gid)

        assert chown_calls == []
        assert any("not a real directory" in message for message in warnings_logged)
        assert any(str(link) in message for message in warnings_logged)

    def test_chown_error_logs_warning_and_does_not_raise(
        self, savefiles_root, monkeypatch, warnings_logged
    ):

        def _raise_permission_error(path, uid, gid, **kwargs):
            raise PermissionError(1, "Operation not permitted")

        monkeypatch.setattr(os, "chown", _raise_permission_error)
        uid, gid = _other_uid_and_gid(savefiles_root)

        ensure_savefiles_writable(savefiles_root, uid, gid)

        assert len(warnings_logged) == 1
        assert str(savefiles_root) in warnings_logged[0]
        assert "Operation not permitted" in warnings_logged[0]
        assert "unable to write to savefiles" in warnings_logged[0]

    def test_missing_root_logs_warning_and_does_not_raise(
        self, tmp_path, chown_calls, warnings_logged
    ):
        missing_root = tmp_path / "does-not-exist"

        ensure_savefiles_writable(missing_root, 1000, 1000)

        assert chown_calls == []
        assert len(warnings_logged) == 1
        assert str(missing_root) in warnings_logged[0]


class _RecordingChain(AbstractHandler):
    def __init__(self):
        self.seen_context = None

    async def handle(self, context):
        self.seen_context = context
        return CodeResultData(execution_id=context["execution_id"], returncode=0)


class _NoStorageManager:
    async def revoke(self, access_key):
        raise AssertionError("storage is not used in these tests")


_RUN_KWARGS = dict(
    libraries=[],
    venv_name="v",
    execution_id="exec-savefiles",
    code="def main():\n    return 1",
    entrypoint="main",
    func_kwargs={},
)


def _make_chain(tmp_path: Path) -> tuple[DynamicVenvExecutorChain, _RecordingChain]:
    chain = DynamicVenvExecutorChain(
        output_path=tmp_path / "out",
        base_venv_path=tmp_path / "venvs",
    )
    recording_chain = _RecordingChain()
    chain.chain = recording_chain
    return chain, recording_chain


@pytest.fixture
def as_root_with_sandbox_ids(monkeypatch, savefiles_root):
    """Take the privilege drop branch with sandbox ids that differ from the test user's."""
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    uid, gid = _other_uid_and_gid(savefiles_root)
    monkeypatch.setattr(dynamic_venv_executor_chain, "SANDBOX_UID", uid)
    monkeypatch.setattr(dynamic_venv_executor_chain, "SANDBOX_GID", gid)
    yield uid, gid


class TestRunTakesSavefilesOwnership:
    @pytest.mark.asyncio
    async def test_chowns_savefiles_root_alongside_execution_dirs(
        self, tmp_path, savefiles_root, monkeypatch, chown_calls, as_root_with_sandbox_ids
    ):
        monkeypatch.setenv("CONTAINER_SAVEFILES_PATH", str(savefiles_root))
        uid, gid = as_root_with_sandbox_ids
        chain, recording_chain = _make_chain(tmp_path)

        result = await chain.run(**_RUN_KWARGS)

        output_path = tmp_path / "out" / "exec-savefiles"
        assert chown_calls == [
            (output_path, uid, gid),
            (output_path / "home", uid, gid),
            (output_path / "tmp", uid, gid),
            (savefiles_root, uid, gid),
        ]
        assert recording_chain.seen_context["work_dir"] == str(savefiles_root)
        assert result.returncode == 0

    @pytest.mark.asyncio
    async def test_unset_env_uses_working_directory_like_work_dir(
        self, tmp_path, savefiles_root, monkeypatch, chown_calls, as_root_with_sandbox_ids
    ):
        monkeypatch.delenv("CONTAINER_SAVEFILES_PATH", raising=False)
        monkeypatch.chdir(savefiles_root)
        uid, gid = as_root_with_sandbox_ids
        chain, recording_chain = _make_chain(tmp_path)

        await chain.run(**_RUN_KWARGS)

        assert chown_calls[-1] == (savefiles_root, uid, gid)
        assert recording_chain.seen_context["work_dir"] == "."

    @pytest.mark.asyncio
    async def test_savefiles_chown_failure_does_not_abort_execution(
        self, tmp_path, savefiles_root, monkeypatch, warnings_logged, as_root_with_sandbox_ids
    ):
        monkeypatch.setenv("CONTAINER_SAVEFILES_PATH", str(savefiles_root))

        def _fail_only_for_savefiles(path, uid, gid, **kwargs):
            if Path(path) == savefiles_root:
                raise PermissionError(1, "Operation not permitted")

        monkeypatch.setattr(os, "chown", _fail_only_for_savefiles)
        chain, recording_chain = _make_chain(tmp_path)

        result = await chain.run(**_RUN_KWARGS)

        assert result.returncode == 0
        assert recording_chain.seen_context is not None
        assert any(str(savefiles_root) in message for message in warnings_logged)

    @pytest.mark.asyncio
    async def test_non_root_does_not_chown_anything(
        self, tmp_path, savefiles_root, monkeypatch, chown_calls
    ):
        monkeypatch.setattr(os, "geteuid", lambda: 1000)
        monkeypatch.setenv("CONTAINER_SAVEFILES_PATH", str(savefiles_root))
        chain, recording_chain = _make_chain(tmp_path)

        result = await chain.run(**_RUN_KWARGS)

        assert chown_calls == []
        assert result.returncode == 0
