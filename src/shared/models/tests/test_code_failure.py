"""The code failure contract: the parts each code needs, lenient reading, and the user-code error line."""

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError
from shared.models import code_failure as code_failure_module
from shared.models.code_failure import (
    CodeFailure,
    CodeFailureCode,
    UserCodeError,
    describe_user_code_error,
)
from shared.models.tools import CodeResultData


@pytest.mark.parametrize(
    "failure",
    [
        CodeFailure(
            code=CodeFailureCode.USER_CODE_ERROR,
            detail="KeyError on line 4: key 'email' doesn't exist",
            user_error=UserCodeError(
                exception_type="KeyError", line=4, message="key 'email' doesn't exist"
            ),
        ),
        CodeFailure(
            code=CodeFailureCode.UNEXPECTED_ARGUMENT,
            detail="TypeError: main() got an unexpected keyword argument 'city'",
            attr="city",
        ),
        CodeFailure(
            code=CodeFailureCode.SANDBOX_ERROR,
            detail="The code couldn't run because of a server error (reference: 0a1b2c3d4e5f).",
        ),
    ],
    ids=["user-code-error", "argument", "plain"],
)
def test_a_failure_survives_the_trip_through_a_code_result(failure):
    result = CodeResultData(
        execution_id="exec-1",
        stdout="",
        stderr=failure.detail,
        returncode=1,
        failure=failure,
        reference="0a1b2c3d4e5f",
    )

    assert CodeResultData.model_validate_json(result.model_dump_json()) == result


def test_a_result_from_a_sender_that_knows_no_failure_still_reads():
    result = CodeResultData.model_validate_json(
        '{"execution_id": "exec-1", "result_data": null, "stdout": "", "stderr": "boom", '
        '"returncode": 1}'
    )

    assert (result.failure, result.reference) == (None, None)


@pytest.mark.parametrize(
    "fields",
    [
        {"code": "user_code_error", "detail": "ValueError: bad"},
        {"code": "unexpected_argument", "detail": "TypeError: unexpected"},
        {"code": None, "detail": "x"},
        {"code": 42, "detail": "x"},
    ],
    ids=[
        "user-code-error-without-its-parts",
        "argument-code-without-the-argument",
        "no-code",
        "code-that-isnt-a-string",
    ],
)
def test_a_failure_without_the_parts_its_code_needs_is_rejected(fields):
    with pytest.raises(ValidationError):
        CodeFailure.model_validate(fields)


def test_a_code_this_version_doesnt_know_is_read_as_unknown():
    # A newer sandbox can send a code an older consumer doesn't know yet; the result
    # still reads, with the detail the consumer shows for it.
    result = CodeResultData.model_validate_json(
        '{"execution_id": "exec-1", "stdout": "", "stderr": "", "returncode": 1, '
        '"failure": {"code": "memory_exceeded", "detail": "The code ran out of memory.", '
        '"attr": "limit"}}'
    )

    assert result.failure.code is CodeFailureCode.UNKNOWN
    assert result.failure.detail == "The code ran out of memory."


@pytest.mark.parametrize("code", ["missing_entrypoint", "memory_exceeded"])
def test_a_part_on_a_code_that_doesnt_use_it_is_dropped_not_rejected(code):
    failure = CodeFailure.model_validate(
        {
            "code": code,
            "detail": "x",
            "attr": "city",
            "user_error": {"exception_type": "ValueError", "line": None, "message": "x"},
        }
    )

    assert (failure.attr, failure.user_error) == (None, None)


@pytest.mark.parametrize(
    ("exception_type", "line", "message", "expected"),
    [
        ("KeyError", 4, "key 'email' doesn't exist", "KeyError on line 4: key 'email' doesn't exist"),
        ("TypeError", None, "main() missing 1 required positional argument: 'a'",
         "TypeError: main() missing 1 required positional argument: 'a'"),
        ("AssertionError", 4, "", "AssertionError on line 4"),
        ("Unprintable", None, "", "Unprintable"),
    ],
)
def test_a_user_code_error_reads_as_type_line_and_message(exception_type, line, message, expected):
    assert describe_user_code_error(exception_type, line, message) == expected


def test_the_contract_imports_nothing_but_pydantic_and_the_standard_library():
    # The sandbox's domain and crew both use this module as it is; an import of a
    # service's own package here would drag that package into them.
    tree = ast.parse(Path(code_failure_module.__file__).read_text(encoding="utf-8"))
    imported = {
        name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for name in (
            [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""]
        )
    }

    assert imported <= {"enum", "typing", "pydantic", "__future__"}
