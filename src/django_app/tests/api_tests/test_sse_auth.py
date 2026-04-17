import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_sse_requires_auth():
    client = APIClient()
    resp = client.get("/api/run-session/subscribe/1/?test=true")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_sse_accepts_jwt(monkeypatch):
    user_model = get_user_model()
    user_model.objects.create_user(username="sseuser", password="pass1234")

    async def _fake_stream(self, test_mode=False):
        yield "data: ok\n\n"

    monkeypatch.setattr(
        "tables.views.sse_views.RunSessionSSEView.event_stream", _fake_stream
    )

    client = APIClient()
    token_resp = client.post(
        "/api/auth/token/",
        {"username": "sseuser", "password": "pass1234"},
        format="json",
    )
    access = token_resp.data["access"]

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    resp = client.get("/api/run-session/subscribe/1/?test=true")
    assert resp.status_code == 200
