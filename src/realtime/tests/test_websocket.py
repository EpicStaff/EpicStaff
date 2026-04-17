from api.connection_repository import ConnectionRepository
from tests.fixtures import *
from fastapi.testclient import TestClient
from tests.conftest import CONNECTION_KEY, CONNECTION_URL


def test_ws_connection(sample_chat_data, monkeypatch):
    from api.main import app

    monkeypatch.setattr(
        "utils.auth.introspect_token",
        lambda token: {"active": True, "user_id": 1, "username": "test"},
    )

    ConnectionRepository().save_connection(
        connection_key=CONNECTION_KEY, data=sample_chat_data
    )

    with TestClient(app).websocket_connect(CONNECTION_URL) as websocket:
        websocket.send_json(
            data={
                "type": "session.update",
            }
        )
