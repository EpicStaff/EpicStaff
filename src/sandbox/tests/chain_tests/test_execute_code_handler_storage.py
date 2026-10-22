"""Storage mutations recorded by a job reach main.py, which publishes them.

main.py reads `<output>/<execution id>/storage_mutations.json` after the run, so the
handler must have the job write its recorded mutations exactly there - and only when
the job was given storage access. The real epicstaff_storage talks to S3 via boto3;
these tests put a fake with the same `get_mutations()` entry point inside the jail.
"""

import asyncio
import json
import sys

import pytest

pytest.importorskip(
    "pwd",
    reason="POSIX-only: sandbox isolation requires pwd/landlock; runs in the Linux image",
)

import dynamic_venv_executor_chain as chain_mod
from dynamic_venv_executor_chain import ExecuteCodeHandler

from conftest import copy_shared_libs_into_jail, make_execute_context

_FAKE_STORAGE_MODULE = """
_mutations = []


def record(operation, path):
    _mutations.append({"operation": operation, "path": path})


def get_mutations():
    return list(_mutations)
"""

_CODE_THAT_WRITES_A_FILE = (
    "def main(**kwargs):\n"
    "    from epicstaff_storage.storage import record\n"
    "    record('write', 'reports/q3.csv')\n"
    "    return 1\n"
)


@pytest.fixture(autouse=True)
def storage_library_in_the_jail(tmp_path, monkeypatch):
    shared_libs_path = copy_shared_libs_into_jail(tmp_path)
    package = shared_libs_path / "epicstaff_storage"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "storage.py").write_text(_FAKE_STORAGE_MODULE)
    real_build_base_env = chain_mod.build_base_env
    monkeypatch.setattr(
        chain_mod,
        "build_base_env",
        lambda python: {**real_build_base_env(python), "PYTHONPATH": str(shared_libs_path)},
    )


def _run(tmp_path, *, drop_keys=(), **overrides):
    context = make_execute_context(
        tmp_path,
        python_executable=sys.executable,
        code=_CODE_THAT_WRITES_A_FILE,
        **overrides,
    )
    for key in drop_keys:
        del context[key]
    result = asyncio.run(ExecuteCodeHandler().handle(context))
    return result, context["result_file_path"].parent / "storage_mutations.json"


def test_storage_job_leaves_its_mutations_where_main_publishes_them_from(tmp_path):
    result, mutations_file = _run(
        tmp_path,
        use_storage=True,
        temp_storage_access_key="scoped-ak",
        temp_storage_secret_key="scoped-sk",
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(mutations_file.read_text()) == [
        {"operation": "write", "path": "reports/q3.csv"}
    ]


@pytest.mark.parametrize(
    ("overrides", "drop_keys"),
    [({"use_storage": False}, ()), ({}, ("use_storage",))],
    ids=["use-storage-false", "use-storage-absent"],
)
def test_job_without_storage_access_publishes_no_mutations(tmp_path, overrides, drop_keys):
    result, mutations_file = _run(tmp_path, drop_keys=drop_keys, **overrides)

    assert result.returncode == 0, result.stderr
    assert not mutations_file.exists()
