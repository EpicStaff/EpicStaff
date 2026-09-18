import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse


@pytest.mark.django_db
@override_settings(FIRST_SETUP_MODE="cli_only")
def test_post_first_setup_is_refused_in_cli_only_mode(api_client):
    r = api_client.post(
        reverse("first_setup"),
        data={"email": "attacker@example.com", "password": "StrongPass123!"},
        format="json",
    )
    assert r.status_code == 403
    assert r.json()["code"] == "first_setup_disabled"


@pytest.mark.django_db
@override_settings(FIRST_SETUP_MODE="cli_only")
def test_refused_post_creates_no_user(api_client):
    """The gate must run before the service, so nothing is written."""
    api_client.post(
        reverse("first_setup"),
        data={"email": "attacker@example.com", "password": "StrongPass123!"},
        format="json",
    )
    assert get_user_model().objects.count() == 0


@pytest.mark.django_db
@override_settings(FIRST_SETUP_MODE="cli_only")
def test_get_reports_no_setup_needed_in_cli_only_mode(api_client):
    """Zero frontend changes depend on this: every FE consumer branches on
    `needs_setup` being truthy, so false routes them to the login page."""
    r = api_client.get(reverse("first_setup"))
    assert r.status_code == 200
    body = r.json()
    assert body["needs_setup"] is False
    assert body["setup_mode"] == "cli_only"


@pytest.mark.django_db
@override_settings(FIRST_SETUP_MODE="open")
def test_get_reports_setup_needed_in_open_mode(api_client):
    r = api_client.get(reverse("first_setup"))
    assert r.status_code == 200
    body = r.json()
    assert body["needs_setup"] is True
    assert body["setup_mode"] == "open"


@pytest.mark.django_db
@override_settings(FIRST_SETUP_MODE="open")
def test_post_first_setup_still_works_in_open_mode(api_client):
    r = api_client.post(
        reverse("first_setup"),
        data={"email": "admin@example.com", "password": "StrongPass123!"},
        format="json",
    )
    assert r.status_code == 201
    assert get_user_model().objects.filter(is_superadmin=True).count() == 1
