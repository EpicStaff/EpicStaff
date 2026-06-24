"""Unit-test fixtures (minimal — fakes are imported directly by test modules)."""

import pytest

from communication.message import Message


@pytest.fixture
def small_message():
    return Message(payload={"key": "value"})


@pytest.fixture
def large_payload_bytes():
    """Returns raw bytes that exceed 1 MB when json-encoded."""
    return b"x" * (1024**2 + 1)
