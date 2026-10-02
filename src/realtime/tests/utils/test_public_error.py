from tests.conftest import PUBLIC_ERROR_REFERENCE
from utils.public_error import (
    PublicErrorMessage,
    build_public_error_message,
    new_error_correlation_id,
)


def test_correlation_id_is_twelve_hex_characters():
    correlation_id = new_error_correlation_id()

    assert len(correlation_id) == 12
    int(correlation_id, 16)


def test_correlation_ids_are_unique():
    correlation_ids = {new_error_correlation_id() for _ in range(1000)}

    assert len(correlation_ids) == 1000


def test_public_message_is_the_fixed_text_plus_the_reference():
    message = build_public_error_message(PublicErrorMessage.TOOL_EXECUTION_FAILED, "abc123def456")

    assert message == "Tool execution failed (reference: abc123def456)"
    assert PUBLIC_ERROR_REFERENCE.search(message).group(1) == "abc123def456"
