import json

from rbac.identity.passwords.failure_description import describe_failure

SECRET = "victim@example.com RAW_TOKEN_MARKER"


def _raise_with_secret():
    raise ValueError(SECRET)


def _caught(function):
    try:
        function()
    except Exception as error:
        return error
    raise AssertionError("expected an exception")


def test_describes_type_file_line_and_function_of_the_innermost_frame():
    error = _caught(_raise_with_secret)

    description = describe_failure(error)

    line = _raise_with_secret.__code__.co_firstlineno + 1
    assert description == (
        f"error_type=ValueError at=test_failure_description.py:{line} in _raise_with_secret"
    )


def test_never_includes_the_exception_message():
    description = describe_failure(_caught(_raise_with_secret))

    assert "victim@example.com" not in description
    assert "RAW_TOKEN_MARKER" not in description


def test_names_a_library_frame_by_basename_only():
    error = _caught(lambda: json.loads("{"))

    description = describe_failure(error)

    assert description.startswith("error_type=JSONDecodeError at=decoder.py:")
    assert "/" not in description
    assert "\\" not in description


def test_an_exception_that_was_never_raised_has_an_unknown_location():
    assert describe_failure(ValueError(SECRET)) == "error_type=ValueError at=unknown"
