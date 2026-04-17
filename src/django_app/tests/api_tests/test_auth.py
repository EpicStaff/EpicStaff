import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from tables.models.auth_models import ApiKey


@pytest.mark.django_db
def test_jwt_obtain_and_me():
    user_model = get_user_model()
    user_model.objects.create_user(username="testuser", password="testpass123")

    client = APIClient()
    resp = client.post(
        "/api/auth/token/",
        {"username": "testuser", "password": "testpass123"},
        format="json",
    )
    assert resp.status_code == 200
    access = resp.data["access"]

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    me = client.get("/api/auth/me/")
    assert me.status_code == 200
    assert me.data["username"] == "testuser"


@pytest.mark.django_db
def test_api_key_auth_and_introspect():
    key = ApiKey(name="server")
    raw = ApiKey.generate_raw_key()
    key.set_key(raw)
    key.scopes = ["introspect"]
    key.save()

    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw)
    me = client.get("/api/auth/me/")
    assert me.status_code == 200

    introspect = client.post("/api/auth/introspect/", {"token": "bad"}, format="json")
    assert introspect.status_code == 200
    assert introspect.data["active"] is False


@pytest.mark.django_db
def test_introspect_requires_api_key():
    user_model = get_user_model()
    user_model.objects.create_user(username="t2", password="pass1234")

    client = APIClient()
    token_resp = client.post(
        "/api/auth/token/",
        {"username": "t2", "password": "pass1234"},
        format="json",
    )
    access = token_resp.data["access"]

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    resp = client.post("/api/auth/introspect/", {"token": access}, format="json")
    assert resp.status_code == 403
