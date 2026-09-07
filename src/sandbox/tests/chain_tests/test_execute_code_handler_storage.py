"""Storage-mutations wiring inside ExecuteCodeHandler.

Two behaviors are covered:

Behavior A — wrap_code (pure, sync):
  The storage-mutations block is appended only when storage_mutations_path is
  truthy.  The block's exact import and path embedding are asserted by reading
  the actual wrap_code output.

Behavior B — handle (async):
  When context["use_storage"] is truthy, handle() derives storage_mutations_path
  as Path(result_file_path).parent / "storage_mutations.json" and passes it to
  wrap_code before writing the generated source to temp_code_path.  Tests drive
  handle() with a fake subprocess (same approach as test_build_environment_handler.py)
  and inspect the written file.
"""

from pathlib import Path
from typing import Any

import pytest

from dynamic_venv_executor_chain import ExecuteCodeHandler


# ---------------------------------------------------------------------------
# Helpers shared across both classes
# ---------------------------------------------------------------------------


def _make_execute_context(tmp_path: Path, **overrides) -> dict[str, Any]:
    """Minimal valid context for ExecuteCodeHandler.handle().

    Mirrors _make_execute_context in test_build_environment_handler.py so the
    fake-subprocess helper works without modification.
    """
    exec_dir = tmp_path / "exec"
    exec_dir.mkdir(parents=True, exist_ok=True)

    ctx: dict[str, Any] = {
        "python_executable": tmp_path / "venv" / "bin" / "python",
        "temp_code_path": exec_dir / "code.py",
        "result_file_path": exec_dir / "output.txt",
        "home_path": str(exec_dir / "home"),
        "code": "def main(**kwargs):\n    return 1",
        "entrypoint": "main",
        "func_kwargs": {},
        "global_kwargs": {},
        "execution_id": "test-exec-storage",
        "use_storage": False,
    }
    ctx.update(overrides)
    return ctx


def _patch_subprocess(monkeypatch, recorded: dict, result_file_path: Path) -> None:
    """Monkeypatch asyncio.create_subprocess_exec to record kwargs and fake success.

    Pre-writes result_file_path so the handler can read it after the subprocess
    call without a real interpreter — identical pattern to test_build_environment_handler.py.
    """

    class _FakeProcess:
        returncode = 0

        async def communicate(self):
            return (b"", b"")

    async def _fake_create(*args, **kwargs):
        recorded.update(kwargs)
        result_file_path.write_text('"ok"')
        return _FakeProcess()

    import dynamic_venv_executor_chain

    monkeypatch.setattr(
        dynamic_venv_executor_chain.asyncio,
        "create_subprocess_exec",
        _fake_create,
    )


# ---------------------------------------------------------------------------
# Behavior A — wrap_code storage block (pure, sync)
# ---------------------------------------------------------------------------


class TestWrapCodeStorageMutationsBlock:
    """wrap_code appends the mutations block only when storage_mutations_path is set."""

    def _wrap(self, tmp_path: Path, storage_mutations_path=None) -> str:
        result_file_path = tmp_path / "output.txt"
        return ExecuteCodeHandler().wrap_code(
            code="def main(**kwargs):\n    return 1",
            result_file_path=result_file_path,
            entrypoint="main",
            func_kwargs={},
            global_kwargs={},
            storage_mutations_path=storage_mutations_path,
        )

    def test_mutations_import_present_when_path_given(self, tmp_path):
        mutations_path = tmp_path / "storage_mutations.json"
        wrapped = self._wrap(tmp_path, storage_mutations_path=mutations_path)

        assert "from epicstaff_storage.storage import get_mutations as __es_get_muts" in wrapped

    def test_mutations_path_embedded_when_path_given(self, tmp_path):
        mutations_path = tmp_path / "storage_mutations.json"
        wrapped = self._wrap(tmp_path, storage_mutations_path=mutations_path)

        assert mutations_path.as_posix() in wrapped

    def test_mutations_block_absent_when_path_is_none(self, tmp_path):
        wrapped = self._wrap(tmp_path, storage_mutations_path=None)

        assert "get_mutations" not in wrapped
        assert "get_mutations as __es_get_muts" not in wrapped

    def test_mutations_block_absent_contains_no_storage_mutations_import(self, tmp_path):
        """The top-level try block always imports epicstaff_storage, but the
        mutations-specific symbol (__es_get_muts / get_mutations) must be absent
        when no path is given."""
        wrapped = self._wrap(tmp_path, storage_mutations_path=None)

        assert "__es_get_muts" not in wrapped

    def test_entrypoint_call_present_regardless_of_mutations_path(self, tmp_path):
        mutations_path = tmp_path / "storage_mutations.json"

        with_path = self._wrap(tmp_path, storage_mutations_path=mutations_path)
        without_path = self._wrap(tmp_path, storage_mutations_path=None)

        assert "main(**__sys_dot_kwargs)" in with_path
        assert "main(**__sys_dot_kwargs)" in without_path

    def test_sys_exit_zero_is_last_statement_with_path(self, tmp_path):
        mutations_path = tmp_path / "storage_mutations.json"
        wrapped = self._wrap(tmp_path, storage_mutations_path=mutations_path)

        assert wrapped.rstrip().endswith("sys.exit(0)")

    def test_sys_exit_zero_is_last_statement_without_path(self, tmp_path):
        wrapped = self._wrap(tmp_path, storage_mutations_path=None)

        assert wrapped.rstrip().endswith("sys.exit(0)")


# ---------------------------------------------------------------------------
# Behavior B — handle wires the mutations path from context["use_storage"]
# ---------------------------------------------------------------------------


class TestHandleStorageMutationsWiring:
    """handle() passes storage_mutations_path to wrap_code only when use_storage is set.

    The test inspects temp_code_path on disk after calling handle() because that is
    the file wrap_code writes to — it is the canonical record of what wrap_code returned.
    """

    @pytest.mark.asyncio
    async def test_use_storage_true_injects_mutations_import_into_written_code(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("STORAGE_ENDPOINT", "http://minio:9000")
        monkeypatch.setenv("STORAGE_BUCKET_NAME", "epicstaff")

        recorded: dict = {}
        context = _make_execute_context(
            tmp_path,
            use_storage=True,
            temp_storage_access_key="scoped-ak",
            temp_storage_secret_key="scoped-sk",
        )
        _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

        await ExecuteCodeHandler().handle(context)

        written = context["temp_code_path"].read_text()
        assert "from epicstaff_storage.storage import get_mutations as __es_get_muts" in written

    @pytest.mark.asyncio
    async def test_use_storage_true_embeds_correct_mutations_path_in_written_code(
        self, tmp_path, monkeypatch
    ):
        """The mutations path is result_file_path.parent / storage_mutations.json."""
        monkeypatch.setenv("STORAGE_ENDPOINT", "http://minio:9000")
        monkeypatch.setenv("STORAGE_BUCKET_NAME", "epicstaff")

        recorded: dict = {}
        context = _make_execute_context(
            tmp_path,
            use_storage=True,
            temp_storage_access_key="scoped-ak",
            temp_storage_secret_key="scoped-sk",
        )
        _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

        await ExecuteCodeHandler().handle(context)

        expected_mutations_path = (
            Path(context["result_file_path"]).parent / "storage_mutations.json"
        )
        written = context["temp_code_path"].read_text()
        assert expected_mutations_path.as_posix() in written

    @pytest.mark.asyncio
    async def test_use_storage_false_omits_mutations_block_from_written_code(
        self, tmp_path, monkeypatch
    ):
        recorded: dict = {}
        context = _make_execute_context(tmp_path, use_storage=False)
        _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

        await ExecuteCodeHandler().handle(context)

        written = context["temp_code_path"].read_text()
        assert "get_mutations" not in written
        assert "__es_get_muts" not in written

    @pytest.mark.asyncio
    async def test_use_storage_absent_omits_mutations_block_from_written_code(
        self, tmp_path, monkeypatch
    ):
        """use_storage not present in context at all — equivalent to False."""
        recorded: dict = {}
        context = _make_execute_context(tmp_path)
        del context["use_storage"]
        _patch_subprocess(monkeypatch, recorded, context["result_file_path"])

        await ExecuteCodeHandler().handle(context)

        written = context["temp_code_path"].read_text()
        assert "get_mutations" not in written
        assert "__es_get_muts" not in written
