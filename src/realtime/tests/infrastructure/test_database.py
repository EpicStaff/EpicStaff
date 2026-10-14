"""A stored session item is attributed to the caller's org and user.

No async SQLite driver is installed, so the DB session is a recording stand-in; the
audio redaction on the same path is covered in test_event_redaction.py.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from infrastructure.persistence.database import save_realtime_session_item_to_db


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("identity", "expected"),
    [
        # A browser /chats session has an authenticated user.
        ({"org_id": 42, "user_id": 7}, (42, 7)),
        # A Twilio call has no end-user identity to attribute to.
        ({"org_id": 42}, (42, None)),
        ({}, (None, None)),
    ],
    ids=["browser-chat", "twilio-call", "no-identity"],
)
async def test_session_item_is_stored_with_its_org_and_creator(identity, expected):
    stored: list = []
    session = AsyncMock()
    session.add = MagicMock(side_effect=stored.append)
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session

    with patch("infrastructure.persistence.database.SessionLocal", return_value=session_cm):
        await save_realtime_session_item_to_db(data={"type": "response.done"}, connection_key="conn-key", **identity)

    (item,) = stored
    assert (item.connection_key, item.data, item.org_id, item.created_by_id) == (
        "conn-key", {"type": "response.done"}, *expected,
    )
    session.commit.assert_awaited_once()
