import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_save_realtime_session_item_sets_org_id():
    from infrastructure.persistence.database import save_realtime_session_item_to_db

    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__.return_value = mock_session
    mock_session_cm.__aexit__.return_value = None

    with patch(
        "infrastructure.persistence.database.SessionLocal",
        return_value=mock_session_cm,
    ):
        await save_realtime_session_item_to_db(
            data={"type": "response.done"},
            connection_key="conn-key-1",
            org_id=42,
        )

    mock_session.add.assert_called_once()
    saved_item = mock_session.add.call_args[0][0]
    assert saved_item.connection_key == "conn-key-1"
    assert saved_item.org_id == 42
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_realtime_session_item_defaults_org_id_to_none():
    from infrastructure.persistence.database import save_realtime_session_item_to_db

    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__.return_value = mock_session
    mock_session_cm.__aexit__.return_value = None

    with patch(
        "infrastructure.persistence.database.SessionLocal",
        return_value=mock_session_cm,
    ):
        await save_realtime_session_item_to_db(
            data={"type": "response.done"},
            connection_key="conn-key-2",
        )

    saved_item = mock_session.add.call_args[0][0]
    assert saved_item.org_id is None


@pytest.mark.asyncio
async def test_save_realtime_session_item_sets_created_by_id_from_user_id():
    """Browser `/chats` sessions carry a `user_id` on `RealtimeAgentChatData`
    (finding #33 follow-up) — it must land on `created_by_id`."""
    from infrastructure.persistence.database import save_realtime_session_item_to_db

    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__.return_value = mock_session
    mock_session_cm.__aexit__.return_value = None

    with patch(
        "infrastructure.persistence.database.SessionLocal",
        return_value=mock_session_cm,
    ):
        await save_realtime_session_item_to_db(
            data={"type": "response.done"},
            connection_key="conn-key-3",
            org_id=42,
            user_id=7,
        )

    saved_item = mock_session.add.call_args[0][0]
    assert saved_item.created_by_id == 7


@pytest.mark.asyncio
async def test_save_realtime_session_item_defaults_created_by_id_to_none():
    """Twilio voice calls have no `user_id` on the chat data — `created_by_id`
    must stay `None`, not error or default to something else."""
    from infrastructure.persistence.database import save_realtime_session_item_to_db

    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__.return_value = mock_session
    mock_session_cm.__aexit__.return_value = None

    with patch(
        "infrastructure.persistence.database.SessionLocal",
        return_value=mock_session_cm,
    ):
        await save_realtime_session_item_to_db(
            data={"type": "response.done"},
            connection_key="conn-key-4",
            org_id=42,
        )

    saved_item = mock_session.add.call_args[0][0]
    assert saved_item.created_by_id is None
