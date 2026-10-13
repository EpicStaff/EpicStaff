"""FIRST_SETUP_MODE: `cli_only` closes the browser first-setup flow.

Setup in `open` mode (the test-suite default) is covered by the first-setup tests in
test_rbac_auth.py.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse


@pytest.mark.django_db
@override_settings(FIRST_SETUP_MODE="cli_only")
def test_first_setup_is_refused_before_anything_is_written_in_cli_only_mode(api_client):
    r = api_client.post(
        reverse("first_setup"), data={"email": "attacker@example.com", "password": "StrongPass123!"}, format="json"
    )

    assert r.status_code == 403
    assert r.json()["code"] == "first_setup_disabled"
    assert get_user_model().objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(("mode", "needs_setup"), [("cli_only", False), ("open", True)])
def test_get_tells_the_frontend_whether_to_show_setup(api_client, mode, needs_setup):
    """Every frontend consumer branches on `needs_setup`; false routes to the login page."""
    with override_settings(FIRST_SETUP_MODE=mode):
        r = api_client.get(reverse("first_setup"))

    assert r.status_code == 200
    assert r.json() == {"needs_setup": needs_setup, "setup_mode": mode}
