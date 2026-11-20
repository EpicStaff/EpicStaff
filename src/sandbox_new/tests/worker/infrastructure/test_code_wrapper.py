"""Behavior of the code wrapper and the step that writes its output.

Every test compiles the generated source. The wrapper is a long f-string with
interpolated ``repr`` output, so substring assertions alone would happily pass on source
that cannot be parsed.
"""

import subprocess
import sys

import pytest

from worker.infrastructure.execution.code_wrapper import wrap_code
from worker.infrastructure.execution.steps import WrapCodeStep
from tests.builders import make_context, make_worker_job

SIMPLE_CODE = "def main(value):\n    return {'echo': value}"


def wrap(tmp_path, **overrides):
    arguments = {
        "code": SIMPLE_CODE,
        "result_file_path": tmp_path / "output.txt",
        "entrypoint": "main",
        "func_kwargs": {"value": "x"},
        "global_kwargs": {},
        "storage_mutations_path": None,
    }
    arguments.update(overrides)
    return wrap_code(**arguments)


def test_the_generated_source_compiles(tmp_path):
    compile(wrap(tmp_path), "<wrapped>", "exec")


@pytest.mark.parametrize(
    "code",
    [
        "def main(value):\n    return \"it's\"",
        'def main(value):\n    return "back\\\\slash"',
        'def main(value):\n    return """triple"""',
        "def main(value):\n    # comment with {braces}\n    return 1",
    ],
)
def test_awkward_user_code_still_compiles(tmp_path, code):
    compile(wrap(tmp_path, code=code), "<wrapped>", "exec")


@pytest.mark.parametrize(
    "func_kwargs",
    [{}, {"value": "it's"}, {"value": {"nested": [1, 2]}}, {"value": None}],
)
def test_awkward_arguments_still_compile(tmp_path, func_kwargs):
    compile(wrap(tmp_path, func_kwargs=func_kwargs), "<wrapped>", "exec")


def test_the_entrypoint_is_called_with_the_arguments(tmp_path):
    source = wrap(tmp_path, entrypoint="handler", func_kwargs={"value": "x"})

    assert "sys_result_variable = handler(**__sys_dot_kwargs)" in source
    assert "{'value': 'x'}" in source


def test_the_result_is_written_to_the_result_file(tmp_path):
    source = wrap(tmp_path, result_file_path=tmp_path / "output.txt")

    assert (tmp_path / "output.txt").as_posix() in source
    assert "json.dumps(sys_result_variable)" in source


def test_globals_are_injected(tmp_path):
    source = wrap(tmp_path, global_kwargs={"LIMIT": 3})

    assert "{'LIMIT': 3}" in source
    compile(source, "<wrapped>", "exec")


def test_no_mutation_tail_without_a_mutations_path(tmp_path):
    assert "epicstaff_storage" not in wrap(tmp_path, storage_mutations_path=None)


def test_the_mutation_tail_is_appended_when_a_path_is_given(tmp_path):
    source = wrap(tmp_path, storage_mutations_path=tmp_path / "storage_mutations.json")

    assert "epicstaff_storage" in source
    assert (tmp_path / "storage_mutations.json").as_posix() in source
    compile(source, "<wrapped>", "exec")


def test_the_source_always_ends_by_exiting_cleanly(tmp_path):
    assert wrap(tmp_path).rstrip().endswith("sys.exit(0)")


async def test_the_wrap_step_writes_the_generated_source_to_the_code_file(tmp_path):
    context = make_context(
        make_worker_job(code=SIMPLE_CODE, entrypoint="main", func_kwargs={"value": "x"}),
        code_path=tmp_path / "code.py",
        result_file_path=tmp_path / "output.txt",
    )

    await WrapCodeStep()(context)

    source = (tmp_path / "code.py").read_text(encoding="utf-8")
    compile(source, "<wrapped>", "exec")
    assert "def main(value):" in source


async def test_the_wrap_step_includes_the_mutation_tail_when_storage_is_in_play(tmp_path):
    context = make_context(
        make_worker_job(use_storage=True, storage_org_prefix="org1"),
        code_path=tmp_path / "code.py",
        result_file_path=tmp_path / "output.txt",
        storage_mutations_path=tmp_path / "storage_mutations.json",
    )

    await WrapCodeStep()(context)

    assert "epicstaff_storage" in (tmp_path / "code.py").read_text(encoding="utf-8")


def run_wrapped(tmp_path, code, entrypoint="main"):
    """Run the wrapped source as the worker would, with stand-ins for the sandbox-only imports."""
    (tmp_path / "dotdict.py").write_text("DotDict = dict\nDotObject = object\nDotList = list\n")
    (tmp_path / "epicstaff_secrets.py").write_text("def get_secret(name):\n    return 'secret'\n")
    script = tmp_path / "code.py"
    script.write_text(wrap(tmp_path, code=code, entrypoint=entrypoint, func_kwargs={}))
    return subprocess.run(
        [sys.executable, "-E", "-s", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize(
    "line_break", ["\r", "\n\f"], ids=["carriage-return", "form-feed-at-line-start"]
)
def test_a_line_the_parser_reads_as_nested_does_not_run_at_top_level(tmp_path, line_break):
    marker = tmp_path / "hidden_ran"
    code = (
        'def main():\n    return "reviewed"\nif 0:\n    pass'
        f'{line_break}    main = lambda: open(r"{marker}", "w").close() or "hidden"'
    )

    result = run_wrapped(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output.txt").read_text() == '"reviewed"'
    assert not marker.exists()


@pytest.mark.parametrize(
    ("code", "message", "line"),
    [
        ("def main():\n    return 1\nreturn 2", "'return' outside function", 3),
        ("x = 1\ndef main(:\n    return 1", "invalid syntax", 2),
    ],
    ids=["found-by-the-compiler", "found-by-the-parser"],
)
def test_a_syntax_error_names_the_line_of_the_users_code(tmp_path, code, message, line):
    result = run_wrapped(tmp_path, code)

    assert result.returncode == 1
    assert message in result.stderr
    assert f'File "<code>", line {line}' in result.stderr
    assert code.split("\n")[line - 1] in result.stderr


@pytest.mark.parametrize(
    ("code", "entrypoint"),
    [
        ("def main():\n    return 1", "get_secret"),
        ("def main():\n    return 1", "open"),
        ("def main():\n    return 1", "__import__"),
        ("def main():\n    return 1", "DotDict"),
        ("def outer():\n    def main():\n        return 1\n    return main", "main"),
        ("if True:\n    def main():\n        return 1", "main"),
        ("open: object", "open"),
        ("from json import *", "dumps"),
        ("def main():\n    return 1", "missing"),
        ("", "main"),
        ("# def main():", "main"),
    ],
    ids=[
        "wrapper-import",
        "builtin",
        "builtin-import",
        "wrapper-helper",
        "nested-def",
        "def-under-if",
        "annotation-without-value",
        "star-import",
        "not-defined",
        "empty-code",
        "comment-only",
    ],
)
def test_an_entrypoint_the_code_does_not_bind_at_top_level_is_refused_before_any_code_runs(
    tmp_path, code, entrypoint
):
    marker = tmp_path / "code_ran"

    result = run_wrapped(tmp_path, f'{code}\nopen(r"{marker}", "w").close()', entrypoint)

    assert result.returncode == 1
    assert f"entrypoint {entrypoint!r} is not defined at the top level of code" in result.stderr
    assert not marker.exists()
    assert not (tmp_path / "output.txt").exists()


@pytest.mark.parametrize(
    ("code", "entrypoint"),
    [
        ("def main():\n    return 1", "main"),
        ("async def main():\n    return 1", "main"),
        ("def _impl():\n    return 1\nmain = _impl", "main"),
        ("main: object = dict", "main"),
        ("from collections import OrderedDict as main", "main"),
        ("from collections import OrderedDict", "OrderedDict"),
        ("import os.path", "os"),
    ],
    ids=["def", "async-def", "assignment", "annotated-assignment", "import-as", "from-import", "import"],
)
def test_an_entrypoint_the_code_binds_at_top_level_runs_the_code(tmp_path, code, entrypoint):
    marker = tmp_path / "code_ran"

    result = run_wrapped(tmp_path, f'{code}\nopen(r"{marker}", "w").close()', entrypoint)

    assert "is not defined at the top level of code" not in result.stderr
    assert marker.exists()


def test_a_syntax_warning_is_shown_once(tmp_path):
    result = run_wrapped(tmp_path, "def main():\n    return '\\d'")

    assert result.returncode == 0, result.stderr
    assert result.stderr.count("SyntaxWarning") == 1


def test_a_future_import_at_the_top_of_the_code_works(tmp_path):
    code = "from __future__ import annotations\ndef main() -> Undefined:\n    return 1"

    result = run_wrapped(tmp_path, code)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output.txt").read_text() == "1"
