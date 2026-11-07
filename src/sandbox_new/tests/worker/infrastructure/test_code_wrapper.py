"""Behavior of the code wrapper: what a user sees when their code runs or fails.

Every test runs the generated source in a real Python subprocess -- the same thing the
launch step does, minus the isolation -- with the shared ``dotdict`` and
``epicstaff_secrets`` packages importable, the way every sandbox venv has them. The
assertions are on the outcome only: the exit code, the one line on stderr, the result
and failure files and what the code printed.
"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import settings
from src.shared.models.code_failure import CodeFailure, describe_user_code_error

from worker.infrastructure.execution.code_wrapper import RESULT_WRITE_FAILED_EXIT_CODE, wrap_code

MARKER = "5f0c2a9e7b1d4e6f8a3c0b2d9e4f7a1c"


@dataclass
class Run:
    returncode: int
    stdout: str
    stderr: str
    result: object
    # The failure file, parsed the way the capture step parses it; None when there is none.
    failure: CodeFailure | None


def run(
    tmp_path: Path,
    code: str,
    *,
    entrypoint="main",
    func_kwargs=None,
    result_file: Path | None = None,
    failure_file: Path | None = None,
    network_block_mode: str | None = None,
    **overrides,
) -> Run:
    result_file = result_file or tmp_path / "output.txt"
    failure_file = failure_file or tmp_path / "failure.json"
    source = wrap_code(
        code=code,
        result_file_path=result_file,
        failure_file_path=failure_file,
        entrypoint=entrypoint,
        func_kwargs=func_kwargs if func_kwargs is not None else {},
        result_write_marker=MARKER,
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
    if network_block_mode is not None:
        environment["SANDBOX_NETWORK_BLOCKED"] = network_block_mode
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
    failure = (
        CodeFailure.model_validate_json(failure_file.read_text(encoding="utf-8"))
        if failure_file.exists()
        else None
    )
    return Run(completed.returncode, completed.stdout, completed.stderr.strip(), result, failure)


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


def test_the_secret_and_dot_access_helpers_are_usable_without_importing_them(tmp_path):
    outcome = run(
        tmp_path,
        "def main():\n"
        "    return [callable(get_secret), DotDict.__name__, DotObject.__name__, DotList.__name__]",
    )

    assert (outcome.returncode, outcome.stderr) == (0, "")
    assert outcome.result == [True, "DotDict", "DotObject", "DotList"]


def test_common_modules_are_usable_without_importing_them(tmp_path):
    code = (
        "def main():\n"
        "    return {\n"
        "        'os': os.fspath('a'),\n"
        "        'errno': errno.EACCES,\n"
        "        'socket': socket.AF_INET == socket.AddressFamily.AF_INET,\n"
        "        'json': json.loads('[1]'),\n"
        "        'sys': sys.maxsize > 0,\n"
        "    }\n"
    )

    outcome = run(tmp_path, code)

    assert (outcome.returncode, outcome.stderr) == (0, "")
    assert outcome.result == {
        "os": "a",
        "errno": 13,
        "socket": True,
        "json": [1],
        "sys": True,
    }


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
    "rebinding",
    [
        "__sys_exit = None",
        "__sys_fail = None",
        "__sys_stderr = None",
        "__sys_builtins = None",
        "__sys_error_message = None\n__sys_failure = None\n__sys_error_parts = None\n"
        "__sys_describe_error = None\n__sys_exit_with_line = None",
    ],
    ids=["exit", "fail", "stderr", "builtins", "message-functions"],
)
def test_the_wrappers_own_names_rebound_by_the_users_code_dont_change_an_error(
    tmp_path, rebinding
):
    code = f"{rebinding}\n\ndef main():\n    raise ValueError('bad input')"
    error_line = code.count("\n") + 1

    outcome = run(tmp_path, code)

    assert outcome.returncode == 1
    assert outcome.stderr == f"ValueError on line {error_line}: bad input"


def test_the_wrappers_own_names_rebound_by_the_users_code_dont_change_a_result(tmp_path):
    outcome = run(
        tmp_path,
        "__sys_json_dumps = None\n__sys_result_file_path = 'elsewhere.txt'\n\n"
        "def main():\n    return 'saved'",
    )

    assert (outcome.returncode, outcome.stderr) == (0, "")
    assert outcome.result == "saved"


def test_the_users_code_does_not_see_the_wrappers_names_or_the_write_marker(tmp_path):
    code = (
        "SEEN_AT_MODULE_LEVEL = [name for name in globals() if name.startswith('__sys')]\n"
        "\n"
        "def main():\n"
        "    return {\n"
        "        'module_level': SEEN_AT_MODULE_LEVEL,\n"
        "        'in_main': [name for name in globals() if name.startswith('__sys')],\n"
        f"        'marker_in_globals': {MARKER!r} in repr(globals()),\n"
        "    }\n"
    )

    outcome = run(tmp_path, code)

    assert outcome.result == {"module_level": [], "in_main": [], "marker_in_globals": False}


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
        f"note\n\n{MARKER}FileNotFoundError: [Errno 2] No such file or directory: "
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
        f"partial\n{MARKER}FileNotFoundError: [Errno 2] No such file or directory: "
        f"'{result_file.as_posix()}'"
    )


def test_the_users_own_exit_with_the_write_failure_code_carries_no_marker(tmp_path):
    outcome = run(
        tmp_path,
        "import sys\n\ndef main():\n"
        "    print('diagnostics', file=sys.stderr)\n"
        f"    sys.exit({RESULT_WRITE_FAILED_EXIT_CODE})",
    )

    assert outcome.returncode == RESULT_WRITE_FAILED_EXIT_CODE
    assert outcome.stderr == "diagnostics"


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
    code = "def main():\n    raise PermissionError(errno.EACCES, 'Permission denied')\n"
    source = wrap_code(
        code=code,
        result_file_path=tmp_path / "output.txt",
        failure_file_path=tmp_path / "failure.json",
        entrypoint="main",
        func_kwargs={},
        result_write_marker=MARKER,
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
        code=code,
        result_file_path=tmp_path / "output.txt",
        failure_file_path=tmp_path / "failure.json",
        entrypoint="main",
        func_kwargs={},
        result_write_marker=MARKER,
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


def test_a_dns_failure_the_users_code_catches_carries_the_policy_message(tmp_path):
    code = (
        "def main():\n"
        "    try:\n"
        "        socket.getaddrinfo('host.invalid', 80)\n"
        "    except socket.gaierror as error:\n"
        "        return str(error)\n"
    )
    source = wrap_code(
        code=code,
        result_file_path=tmp_path / "output.txt",
        failure_file_path=tmp_path / "failure.json",
        entrypoint="main",
        func_kwargs={},
        result_write_marker=MARKER,
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

    assert completed.returncode == 0, completed.stderr
    returned = json.loads((tmp_path / "output.txt").read_text(encoding="utf-8"))
    # str() of an OSError starts with its errno, which differs between platforms.
    assert returned.endswith(
        "] Network access denied: the sandbox network policy blocks all outbound network access."
    )


def test_an_access_error_is_not_a_network_denial_without_a_network_policy(tmp_path):
    code = "def main():\n    raise PermissionError(errno.EACCES, 'Permission denied')"

    outcome = run(tmp_path, code)

    assert outcome.stderr == "PermissionError on line 2: [Errno 13] Permission denied"


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
        failure_file_path=tmp_path / "failure.json",
        entrypoint="main",
        func_kwargs={},
        result_write_marker=MARKER,
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


@pytest.mark.parametrize(
    ("code", "func_kwargs", "network_block_mode", "expected_code"),
    [
        pytest.param(
            "def main():\n    raise ValueError('bad input')",
            {},
            None,
            "user_code_error",
            id="user-code-error",
        ),
        pytest.param("def main(:\n    return 1", {}, None, "user_code_error", id="syntax-error"),
        pytest.param(
            "def handler():\n    return 1", {}, None, "missing_entrypoint", id="entrypoint"
        ),
        pytest.param(
            "def main():\n    return 1",
            {"city": "Kyiv"},
            None,
            "unexpected_argument",
            id="unexpected-argument",
        ),
        pytest.param(
            "def main(city):\n    return city", {}, None, "missing_argument", id="missing-argument"
        ),
        pytest.param("def main():\n    return {1, 2}", {}, None, "bad_return_value", id="return"),
        pytest.param(
            "def main():\n    raise PermissionError(errno.EACCES, 'Permission denied')",
            {},
            "all",
            "network_denied",
            id="network",
        ),
    ],
)
def test_a_failure_is_reported_in_the_file_as_the_line_it_writes_to_stderr(
    tmp_path, code, func_kwargs, network_block_mode, expected_code
):
    outcome = run(tmp_path, code, func_kwargs=func_kwargs, network_block_mode=network_block_mode)

    assert outcome.returncode == 1
    assert outcome.failure.code == expected_code
    assert outcome.failure.detail == outcome.stderr.splitlines()[-1]


def test_the_failure_detail_is_the_last_line_after_what_the_users_code_wrote(tmp_path):
    outcome = run(
        tmp_path,
        "import sys\n\ndef main():\n    print('working', file=sys.stderr)\n"
        "    raise ValueError('bad input')",
    )

    assert outcome.stderr == "working\nValueError on line 5: bad input"
    assert outcome.failure.detail == "ValueError on line 5: bad input"


@pytest.mark.parametrize(
    ("code", "exception_type", "line", "message"),
    [
        pytest.param(
            "def main():\n    user = {}\n    return user['email']",
            "KeyError",
            3,
            "key 'email' doesn't exist",
            id="runtime-error",
        ),
        pytest.param(
            "def main():\n    values = [1, 2]\n    print(values[0]\n    return 1",
            "SyntaxError",
            3,
            "'(' was never closed",
            id="syntax-error",
        ),
        pytest.param(
            "def main():\n    total = 0\n    assert total > 0",
            "AssertionError",
            3,
            "",
            id="no-message",
        ),
        pytest.param(
            "import functools\n\nmain = functools.partial(exec, 'raise ValueError(\"inside\")', {})",
            "ValueError",
            None,
            "inside",
            id="no-line-in-the-users-code",
        ),
    ],
)
def test_an_error_in_the_users_code_is_reported_in_parts(
    tmp_path, code, exception_type, line, message
):
    outcome = run(tmp_path, code)

    user_error = outcome.failure.user_error
    assert (user_error.exception_type, user_error.line, user_error.message) == (
        exception_type,
        line,
        message,
    )
    assert outcome.failure.detail == describe_user_code_error(exception_type, line, message)


@pytest.mark.parametrize(
    ("code", "func_kwargs", "expected_code", "expected_argument"),
    [
        pytest.param(
            "def main(city):\n    return city",
            {"city": "Kyiv", "country": "UA"},
            "unexpected_argument",
            "country",
            id="unexpected",
        ),
        pytest.param(
            "def main(city, country):\n    return city",
            {"city": "Kyiv"},
            "missing_argument",
            "country",
            id="missing",
        ),
        pytest.param(
            "def main(*, city):\n    return city",
            {},
            "missing_argument",
            "city",
            id="missing-keyword-only",
        ),
        pytest.param(
            # Python reports an argument it doesn't take before one it misses.
            "def main(city):\n    return city",
            {"country": "UA"},
            "unexpected_argument",
            "country",
            id="unexpected-before-missing",
        ),
        pytest.param(
            "def main(city, /):\n    return city",
            {"city": "Kyiv"},
            "unexpected_argument",
            "city",
            id="positional-only-given-by-name",
        ),
        pytest.param(
            # Extra arguments land in **kwargs; a required one can still be missing.
            "def main(city, **rest):\n    return city",
            {"country": "UA"},
            "missing_argument",
            "city",
            id="kwargs-takes-extras",
        ),
        pytest.param(
            "class Main:\n    def __init__(self, city):\n        self.city = city\n\nmain = Main",
            {"country": "UA"},
            "unexpected_argument",
            "country",
            id="class-entrypoint",
        ),
    ],
)
def test_an_argument_the_entrypoint_cant_take_or_misses_is_named(
    tmp_path, code, func_kwargs, expected_code, expected_argument
):
    outcome = run(tmp_path, code, func_kwargs=func_kwargs)

    assert outcome.returncode == 1
    assert (outcome.failure.code, outcome.failure.attr) == (expected_code, expected_argument)
    assert outcome.failure.detail == outcome.stderr
    assert outcome.stderr.startswith("TypeError: ")


@pytest.mark.parametrize(
    ("code", "func_kwargs"),
    [
        pytest.param(
            "def main(city):\n    return len(city, 2)",
            {"city": "Kyiv"},
            id="raised-inside-the-function",
        ),
        pytest.param(
            "def check(value):\n    return value\n\ndef main(**kwargs):\n    return check(**kwargs)",
            {"value": 1, "extra": 2},
            id="raised-calling-the-users-own-helper",
        ),
        pytest.param("main = max", {"city": "Kyiv"}, id="signature-unreadable"),
    ],
)
def test_a_type_error_that_isnt_the_entrypoints_arguments_stays_a_user_code_error(
    tmp_path, code, func_kwargs
):
    outcome = run(tmp_path, code, func_kwargs=func_kwargs)

    assert outcome.failure.code == "user_code_error"
    assert outcome.failure.attr is None
    assert outcome.failure.user_error.exception_type == "TypeError"


def test_a_successful_run_leaves_no_failure_file(tmp_path):
    outcome = run(tmp_path, "def main():\n    return 1")

    assert (outcome.returncode, outcome.failure) == (0, None)


def test_a_result_file_that_cannot_be_written_leaves_no_failure_file(tmp_path):
    outcome = run(
        tmp_path,
        "def main():\n    return 1",
        result_file=tmp_path / "missing-directory" / "output.txt",
    )

    assert outcome.returncode == RESULT_WRITE_FAILED_EXIT_CODE
    assert outcome.failure is None


def test_the_users_own_exit_leaves_no_failure_file(tmp_path):
    outcome = run(tmp_path, "import sys\n\ndef main():\n    sys.exit(3)")

    assert (outcome.returncode, outcome.failure) == (3, None)


@pytest.mark.parametrize(
    "rebinding",
    [
        "json = None",
        "def open(*args, **kwargs):\n    raise RuntimeError('mine')",
        "__sys_json_dumps = None\n__sys_failure_file_path = 'elsewhere.json'",
    ],
    ids=["json", "open", "wrappers-own-names"],
)
def test_names_the_users_code_rebinds_dont_stop_the_failure_file(tmp_path, rebinding):
    code = f"{rebinding}\n\ndef main():\n    raise ValueError('bad input')"

    outcome = run(tmp_path, code)

    assert outcome.failure.code == "user_code_error"
    assert outcome.failure.detail == outcome.stderr
    assert not (tmp_path / "elsewhere.json").exists()


def test_a_failure_file_that_cannot_be_written_still_exits_with_the_line(tmp_path):
    failure_file = tmp_path / "missing-directory" / "failure.json"

    outcome = run(
        tmp_path, "def main():\n    raise ValueError('bad input')", failure_file=failure_file
    )

    assert outcome.returncode == 1
    assert outcome.stderr == "ValueError on line 2: bad input"
    assert outcome.failure is None


def test_a_message_well_past_what_a_user_is_shown_reaches_the_worker_whole(tmp_path):
    # The worker masks secrets before it shortens, so it needs the text uncut.
    outcome = run(tmp_path, "def main():\n    raise ValueError('x' * 8_000)")

    assert outcome.failure.user_error.message == "x" * 8_000
    assert outcome.stderr == outcome.failure.detail == f"ValueError on line 2: {'x' * 8_000}"


@pytest.mark.parametrize(
    "character",
    ["x", "é", "\U0001f600", "\x01"],
    ids=["ascii", "latin", "emoji", "control-character"],
)
def test_a_huge_message_is_bounded_so_the_failure_file_stays_readable(tmp_path, character):
    outcome = run(tmp_path, f"def main():\n    raise ValueError({character!r} * 1_000_000)")

    assert outcome.failure.user_error.message == character * 9_000 + "..."
    assert outcome.failure.detail == f"ValueError on line 2: {character * 9_000}..."
    # The capture step reads at most 128 KiB.
    assert (tmp_path / "failure.json").stat().st_size < 128 * 1024
    # Stderr is the run's own output: never cut.
    assert outcome.stderr == f"ValueError on line 2: {character * 1_000_000}"


@pytest.mark.parametrize(
    "raise_statement",
    [
        "raise ValueError(PADDING + SECRET)",
        # json.dumps names the type of a value it can't save.
        "return type(PADDING + SECRET, (), {})()",
    ],
    ids=["user-code-error", "bad-return-value"],
)
def test_a_secret_straddling_the_file_bound_reaches_stderr_whole(tmp_path, raise_statement):
    # The worker masks only whole secret values; a cut through one would leave its prefix.
    secret = "sk-live-0123456789abcdef"
    code = f"PADDING = 'x' * 8_990\nSECRET = {secret!r}\n\ndef main():\n    {raise_statement}"

    outcome = run(tmp_path, code)

    assert secret in outcome.stderr
    assert secret not in outcome.failure.detail


def test_an_exit_with_a_message_is_reported_as_an_error_in_the_users_code(tmp_path):
    outcome = run(
        tmp_path, "import sys\n\ndef main():\n    \n    sys.exit('Missing API key')"
    )

    assert outcome.returncode == 1
    assert outcome.stderr == "SystemExit on line 5: Missing API key"
    assert outcome.failure.code == "user_code_error"
    assert outcome.failure.detail == outcome.stderr
    assert outcome.failure.user_error.exception_type == "SystemExit"


@pytest.mark.parametrize("exit_call", ["sys.exit(0)", "sys.exit()", "sys.exit(True)"])
def test_an_exit_with_a_status_writes_no_failure(tmp_path, exit_call):
    outcome = run(tmp_path, f"import sys\n\ndef main():\n    {exit_call}")

    assert outcome.failure is None
    assert outcome.stderr == ""


def test_an_inspect_the_users_code_broke_doesnt_leak_the_wrappers_traceback(tmp_path):
    outcome = run(
        tmp_path,
        "import inspect\ninspect.Parameter = None\n\ndef main(value):\n    return value",
        func_kwargs={"city": "Kyiv"},
    )

    assert outcome.returncode == 1
    assert outcome.stderr == "TypeError: main() got an unexpected keyword argument 'city'"
    assert outcome.failure.code == "user_code_error"
