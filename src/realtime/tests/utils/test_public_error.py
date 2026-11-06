from tests.conftest import PUBLIC_ERROR_REFERENCE
from src.shared.public_error import PublicErrorMessage, build_public_error_message


def test_public_message_is_the_fixed_text_plus_the_reference():
    message = build_public_error_message(PublicErrorMessage.TOOL_EXECUTION_FAILED, "abc123def456")

    assert message == "Tool execution failed (reference: abc123def456)"
    assert PUBLIC_ERROR_REFERENCE.search(message).group(1) == "abc123def456"
