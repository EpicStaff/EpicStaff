from utils.logger import MAX_LOG_LENGTH, truncate_filter


def _record(message: str, **extra) -> dict:
    return {"message": message, "extra": extra}


def test_long_messages_are_truncated():
    record = _record("x" * (MAX_LOG_LENGTH + 50))

    assert truncate_filter(record) is True
    assert record["message"] == "x" * MAX_LOG_LENGTH + "..."


def test_short_messages_are_untouched():
    record = _record("short")

    truncate_filter(record)

    assert record["message"] == "short"


def test_audit_records_are_never_truncated():
    message = "Storage import: " + "(1, 'bulk/file.txt'), " * 50
    record = _record(message, audit=True)

    truncate_filter(record)

    assert record["message"] == message


def test_newlines_are_escaped_in_audit_records_too():
    record = _record("line one\r\nline two", audit=True)

    truncate_filter(record)

    assert record["message"] == "line one\\nline two"
