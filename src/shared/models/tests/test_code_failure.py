"""The code failure contract: which parts go with which code, and the user-code error line."""

import pytest
from pydantic import ValidationError
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
        {
            "code": "sandbox_error",
            "detail": "ValueError: bad",
            "user_error": {"exception_type": "ValueError", "line": None, "message": "bad"},
        },
        {"code": "unexpected_argument", "detail": "TypeError: unexpected"},
        {"code": "user_code_error", "detail": "x", "attr": "city",
         "user_error": {"exception_type": "ValueError", "line": None, "message": "x"}},
        {"code": "not_a_code", "detail": "x"},
    ],
    ids=[
        "user-code-error-without-its-parts",
        "parts-on-another-code",
        "argument-code-without-the-argument",
        "argument-on-another-code",
        "unknown-code",
    ],
)
def test_a_failure_whose_parts_dont_match_its_code_is_rejected(fields):
    with pytest.raises(ValidationError):
        CodeFailure.model_validate(fields)


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
