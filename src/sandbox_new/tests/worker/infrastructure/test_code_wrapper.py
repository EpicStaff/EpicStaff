"""Behavior of the code wrapper: what a user sees when their code runs or fails.

Every test runs the generated source in a real Python subprocess -- the same thing the
launch step does, minus the isolation -- with the shared ``dotdict`` and
``epicstaff_secrets`` packages importable, the way every sandbox venv has them. The
assertions are on the outcome only: the exit code, the one line on stderr, the result
file and what the code printed.
"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import settings

from worker.infrastructure.execution.code_wrapper import RESULT_WRITE_FAILED_EXIT_CODE, wrap_code


@dataclass
class Run:
    returncode: int
    stdout: str
    stderr: str
    result: object


def run(
    tmp_path: Path,
    code: str,
    *,
    entrypoint="main",
    func_kwargs=None,
    result_file: Path | None = None,
    **overrides,
) -> Run:
    result_file = result_file or tmp_path / "output.txt"
    source = wrap_code(
        code=code,
        result_file_path=result_file,
        entrypoint=entrypoint,
        func_kwargs=func_kwargs if func_kwargs is not None else {},
        **overrides,
    )
    code_file = tmp_path / "code.py"
    code_file.write_text(source, encoding="utf-8")
    environment = {
        **os.environ,
        "PYTHONPATH": str(settings.SHARED_DIR),
        "PYTHONIOENCODING": "utf-8",
    }
    environment.pop("SANDBOX_NETWORK_BLOCKED", None)
    completed = subprocess.run(
        [sys.executable, str(code_file)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        cwd=tmp_path,
        timeout=60,
    )
    result = json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else None
    return Run(completed.returncode, completed.stdout, completed.stderr.strip(), result)


def test_the_return_value_is_written_to_the_result_file(tmp_path):
    outcome = run(
        tmp_path,
        "def main(value):\n    print('hello')\n    return {'echo': value}",
        func_kwargs={"value": "x"},
    )

    assert (outcome.returncode, outcome.stderr) == (0, "")
    assert outcome.result == {"echo": "x"}
    assert outcome.stdout == "hello\n"


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        pytest.param("def main():\n    return \"it's\"", "it's", id="quote"),
        pytest.param('def main():\n    return "back\\\\slash"', "back\\slash", id="backslash"),
        pytest.param("def main():\n    # {braces}\n    return '{x}'", "{x}", id="braces"),
        pytest.param('def main():\n    return """a\nb"""', "a\nb", id="triple-quoted"),
        pytest.param(
            'TEXT = """\nfirst\n    indented\nlast"""\n\ndef main():\n    return TEXT',
            "\nfirst\n    indented\nlast",
            id="multi-line-string-keeps-its-indentation",
        ),
        pytest.param("def main():\n    return 'ünïcödé ✓'", "ünïcödé ✓", id="unicode"),
    ],
)
def test_awkward_user_code_runs_exactly_as_written(tmp_path, code, expected):
    outcome = run(tmp_path, code)

    assert (outcome.returncode, outcome.stderr) == (0, "")
    assert outcome.result == expected


@pytest.mark.parametrize(
    "func_kwargs",
    [{}, {"value": "it's"}, {"value": {"nested": [1, 2]}}, {"value": None}],
)
def test_awkward_arguments_reach_the_entrypoint(tmp_path, func_kwargs):
    outcome = run(tmp_path, "def main(**kwargs):\n    return kwargs", func_kwargs=func_kwargs)

    assert outcome.returncode == 0
    assert outcome.result == func_kwargs


def test_arguments_are_dot_accessible(tmp_path):
    outcome = run(
        tmp_path,
        "def main(user):\n    return user.name",
        func_kwargs={"user": {"name": "Ann"}},
    )

    assert outcome.result == "Ann"


def test_globals_are_injected(tmp_path):
    outcome = run(tmp_path, "def main():\n    return LIMIT * 2", global_kwargs={"LIMIT": 3})

    assert outcome.result == 6


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        pytest.param(
            "import os\n\ndef main():\n    return open(file_pat).read()",
            "NameError on line 4: name 'file_pat' is not defined",
            id="name-error",
        ),
        pytest.param(
            "def main():\n    user = {'name': 'Ann'}\n\n    return user['email']",
            "KeyError on line 4: key 'email' doesn't exist",
            id="key-error-quotes-the-key",
        ),
        pytest.param(
            "def main():\n    rows = {1: 'a'}\n\n    return rows[2]",
            "KeyError on line 4: key 2 doesn't exist",
            id="key-error-with-a-number",
        ),
        pytest.param(
            "def main():\n    total = 0\n\n    assert total > 0\n    return total",
            "AssertionError on line 4",
            id="empty-message",
        ),
        pytest.param(
            "def helper():\n    raise ValueError('bad input')\n\ndef main():\n    return helper()",
            "ValueError on line 2: bad input",
            id="deepest-user-frame",
        ),
        pytest.param(
            "import json\n\n\n\n\n\ndef main():\n    return json.loads('not json')",
            "JSONDecodeError on line 8: Expecting value: line 1 column 1 (char 0)",
            id="error-inside-a-library-points-at-the-users-call",
        ),
        pytest.param(
            "VALUE = 1 / 0\n\ndef main():\n    return VALUE",
            "ZeroDivisionError on line 1: division by zero",
            id="error-at-module-level",
        ),
    ],
)
def test_an_error_names_its_type_the_users_line_and_its_message(tmp_path, code, expected):
    outcome = run(tmp_path, code)

    assert outcome.returncode == 1
    assert outcome.stderr == expected
    assert outcome.result is None


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        pytest.param(
            "def main():\n    values = [1, 2]\n    print(values[0]\n    return 1",
            "SyntaxError on line 3: '(' was never closed",
            id="syntax-error",
        ),
        pytest.param(
            "def main():\n    if True:\n    return 1",
            "IndentationError on line 3: expected an indented block after 'if' statement "
            "on line 2",
            id="indentation-error",
        ),
    ],
)
def test_a_syntax_error_names_the_users_line(tmp_path, code, expected):
    outcome = run(tmp_path, code)

    assert outcome.returncode == 1
    assert outcome.stderr == expected


def test_a_syntax_error_from_code_the_user_evaluates_is_not_given_their_line(tmp_path):
    outcome = run(tmp_path, "def main():\n    return eval('(')")

    assert outcome.stderr == "SyntaxError on line 2: '(' was never closed (<string>, line 1)"


def test_a_missing_entrypoint_is_named(tmp_path):
    outcome = run(tmp_path, "def handler():\n    return 1", entrypoint="main")

    assert outcome.returncode == 1
    assert outcome.stderr == 'The code has no function named "main". Add one, or check its name.'


def test_an_entrypoint_that_is_not_a_function_counts_as_missing(tmp_path):
    outcome = run(tmp_path, "process = 5", entrypoint="process")

    assert outcome.stderr == (
        'The code has no function named "process". Add one, or check its name.'
    )


def test_a_return_value_that_is_not_json_is_explained(tmp_path):
    outcome = run(tmp_path, "def main():\n    return {1, 2}")

    assert outcome.returncode == 1
    assert outcome.stderr == (
        "The function's return value can't be saved: Object of type set is not JSON "
        "serializable. Return text, numbers, lists or dictionaries."
    )
    assert outcome.result is None


def test_an_error_with_no_line_in_the_users_code_has_no_line(tmp_path):
    outcome = run(tmp_path, "def main():\n    return 1", func_kwargs={"unexpected": 1})

    assert outcome.returncode == 1
    assert outcome.stderr == "TypeError: main() got an unexpected keyword argument 'unexpected'"


def test_no_traceback_reaches_the_user(tmp_path):
    outcome = run(tmp_path, "def main():\n    raise RuntimeError('boom')")

    assert outcome.stderr == "RuntimeError on line 2: boom"
    assert "Traceback" not in outcome.stderr


@pytest.mark.parametrize(
    ("code", "expected_stderr", "expected_result"),
    [
        pytest.param(
            "type = 'pdf'\n\ndef main():\n    raise ValueError('bad input')",
            "ValueError on line 4: bad input",
            None,
            id="type",
        ),
        pytest.param(
            "str = 1\n\ndef main():\n    return {}['email']",
            "KeyError on line 4: key 'email' doesn't exist",
            None,
            id="str",
        ),
        pytest.param(
            "len = 0\nisinstance = None\n\ndef main():\n    return {}['email']",
            "KeyError on line 5: key 'email' doesn't exist",
            None,
            id="len-and-isinstance",
        ),
        pytest.param(
            "Exception = None\nSyntaxError = None\n\ndef main():\n    raise ValueError('bad input')",
            "ValueError on line 5: bad input",
            None,
            id="exception-classes",
        ),
        pytest.param(
            "str = 1\n\ndef main():\n    return {1, 2}",
            "The function's return value can't be saved: Object of type set is not JSON "
            "serializable. Return text, numbers, lists or dictionaries.",
            None,
            id="str-with-a-return-value-that-is-not-json",
        ),
        pytest.param(
            "def open(*args, **kwargs):\n    raise RuntimeError('mine')\n\n"
            "def main():\n    return 'saved'",
            "",
            "saved",
            id="open",
        ),
        pytest.param(
            "DotDict = None\n\ndef main():\n    return 'ran'",
            "",
            "ran",
            id="DotDict",
        ),
        pytest.param(
            "callable = None\ngetattr = None\nglobals = None\n\ndef main():\n    return 'ran'",
            "",
            "ran",
            id="callable-getattr-globals",
        ),
        pytest.param(
            "json = None\nsys = None\n\ndef main():\n    return [1]",
            "",
            [1],
            id="json-and-sys",
        ),
    ],
)
def test_names_the_users_code_rebinds_dont_change_the_outcome(
    tmp_path, code, expected_stderr, expected_result
):
    outcome = run(tmp_path, code)

    assert outcome.stderr == expected_stderr
    assert outcome.returncode == (1 if expected_stderr else 0)
    assert outcome.result == expected_result


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        pytest.param(
            "class Unprintable(Exception):\n"
            "    def __str__(self):\n"
            "        raise RuntimeError('no text')\n"
            "\n"
            "def main():\n"
            "    raise Unprintable()",
            "Unprintable on line 6",
            id="message-that-raises",
        ),
        pytest.param(
            "class Key:\n"
            "    def __hash__(self):\n"
            "        return 1\n"
            "\n"
            "    def __repr__(self):\n"
            "        raise RuntimeError('no text')\n"
            "\n"
            "def main():\n"
            "    return {}[Key()]",
            "KeyError on line 9",
            id="key-that-cannot-be-shown",
        ),
        pytest.param(
            "import functools\n"
            "\n"
            "class Unprintable(Exception):\n"
            "    def __str__(self):\n"
            "        raise RuntimeError('no text')\n"
            "\n"
            "main = functools.partial(exec, 'raise Unprintable()', {'Unprintable': Unprintable})",
            "Unprintable",
            id="message-that-raises-with-no-line-in-the-users-code",
        ),
    ],
)
def test_an_error_whose_text_cannot_be_built_is_named_by_its_type(tmp_path, code, expected):
    outcome = run(tmp_path, code)

    assert outcome.returncode == 1
    assert outcome.stderr == expected


def test_a_result_file_that_cannot_be_written_exits_with_its_own_code(tmp_path):
    result_file = tmp_path / "missing-directory" / "output.txt"

    outcome = run(
        tmp_path,
        "import sys\n\ndef main():\n    print('note', file=sys.stderr)\n    return 1",
        result_file=result_file,
    )

    assert outcome.returncode == RESULT_WRITE_FAILED_EXIT_CODE
    assert outcome.stderr == (
        "note\n\nFileNotFoundError: [Errno 2] No such file or directory: "
        f"'{result_file.as_posix()}'"
    )


def test_a_result_write_error_starts_on_its_own_line_after_unfinished_user_output(tmp_path):
    result_file = tmp_path / "missing-directory" / "output.txt"

    outcome = run(
        tmp_path,
        "import sys\n\ndef main():\n    sys.stderr.write('partial')\n    return 1",
        result_file=result_file,
    )

    assert outcome.returncode == RESULT_WRITE_FAILED_EXIT_CODE
    assert outcome.stderr == (
        "partial\nFileNotFoundError: [Errno 2] No such file or directory: "
        f"'{result_file.as_posix()}'"
    )


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        pytest.param(
            "def main():\n    raise KeyboardInterrupt('stop')",
            "KeyboardInterrupt on line 2: stop",
            id="KeyboardInterrupt",
        ),
        pytest.param(
            "import asyncio\n\ndef main():\n    raise asyncio.CancelledError()",
            "CancelledError on line 4",
            id="CancelledError",
        ),
    ],
)
def test_an_error_outside_the_exception_family_gets_the_same_text(tmp_path, code, expected):
    outcome = run(tmp_path, code)

    assert outcome.returncode == 1
    assert outcome.stderr == expected


def test_the_users_own_exit_code_is_kept(tmp_path):
    outcome = run(tmp_path, "import sys\n\ndef main():\n    sys.exit(3)")

    assert outcome.returncode == 3
    assert outcome.stderr == ""


def test_tracebacks_the_user_formats_show_their_own_source(tmp_path):
    code = (
        "import traceback\n"
        "\n"
        "def main():\n"
        "    try:\n"
        "        raise ValueError('shown')\n"
        "    except ValueError:\n"
        "        return traceback.format_exc()\n"
    )

    outcome = run(tmp_path, code)

    assert 'File "<code>", line 5, in main' in outcome.result
    assert "raise ValueError('shown')" in outcome.result


def test_sys_exit_in_the_users_code_keeps_its_exit_code(tmp_path):
    outcome = run(tmp_path, "import sys\n\ndef main():\n    sys.exit(3)")

    assert outcome.returncode == 3
    assert outcome.stderr == ""


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (
            "all",
            "Network access denied: the sandbox network policy blocks all outbound "
            "network access.",
        ),
        (
            "storage_only",
            "Network access denied: the sandbox network policy allows outbound network "
            "access only to the storage endpoint.",
        ),
    ],
)
def test_a_network_denial_keeps_its_policy_message(tmp_path, monkeypatch, mode, expected):
    code = (
        "import errno\n"
        "\n"
        "def main():\n"
        "    raise PermissionError(errno.EACCES, 'Permission denied')\n"
    )
    source = wrap_code(
        code=code, result_file_path=tmp_path / "output.txt", entrypoint="main", func_kwargs={}
    )
    (tmp_path / "code.py").write_text(source, encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(tmp_path / "code.py")],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": str(settings.SHARED_DIR),
            "SANDBOX_NETWORK_BLOCKED": mode,
        },
        cwd=tmp_path,
        timeout=60,
    )

    assert completed.returncode == 1
    assert completed.stderr.strip() == expected


def test_a_network_denial_is_recognised_when_the_users_code_rebinds_names_it_uses(tmp_path):
    code = (
        "import errno\n"
        "\n"
        "denial = PermissionError(errno.EACCES, 'Permission denied')\n"
        "errno = None\n"
        "socket = None\n"
        "getattr = None\n"
        "isinstance = None\n"
        "OSError = None\n"
        "\n"
        "def main():\n"
        "    raise denial\n"
    )
    source = wrap_code(
        code=code, result_file_path=tmp_path / "output.txt", entrypoint="main", func_kwargs={}
    )
    (tmp_path / "code.py").write_text(source, encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(tmp_path / "code.py")],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": str(settings.SHARED_DIR),
            "SANDBOX_NETWORK_BLOCKED": "all",
        },
        cwd=tmp_path,
        timeout=60,
    )

    assert completed.returncode == 1
    assert completed.stderr.strip() == (
        "Network access denied: the sandbox network policy blocks all outbound network access."
    )


def test_an_access_error_is_not_a_network_denial_without_a_network_policy(tmp_path):
    code = "import errno\n\ndef main():\n    raise PermissionError(errno.EACCES, 'Permission denied')"

    outcome = run(tmp_path, code)

    assert outcome.stderr == "PermissionError on line 4: [Errno 13] Permission denied"


def test_storage_mutations_are_written_when_a_path_is_given(tmp_path):
    fake_storage = tmp_path / "packages" / "epicstaff_storage"
    fake_storage.mkdir(parents=True)
    (fake_storage / "__init__.py").write_text("")
    (fake_storage / "storage.py").write_text(
        "def get_mutations():\n    return [{'op': 'write', 'path': 'docs/a.txt'}]\n"
    )
    mutations_file = tmp_path / "storage_mutations.json"
    source = wrap_code(
        code="def main():\n    return 1",
        result_file_path=tmp_path / "output.txt",
        entrypoint="main",
        func_kwargs={},
        storage_mutations_path=mutations_file,
    )
    (tmp_path / "code.py").write_text(source, encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(tmp_path / "code.py")],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join([str(tmp_path / "packages"), str(settings.SHARED_DIR)]),
        },
        cwd=tmp_path,
        timeout=60,
    )

    assert completed.returncode == 0
    assert json.loads(mutations_file.read_text()) == [{"op": "write", "path": "docs/a.txt"}]


def test_no_mutations_file_without_a_mutations_path(tmp_path):
    outcome = run(tmp_path, "def main():\n    return 1", storage_mutations_path=None)

    assert outcome.returncode == 0
    assert not (tmp_path / "storage_mutations.json").exists()
