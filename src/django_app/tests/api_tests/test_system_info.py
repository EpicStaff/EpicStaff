import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from tables.import_export.constants import IMPORT_VERSION
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

URL_NAME = "system_info"

DOCUMENTED_KEYS = {
    "version",
    "git_ref",
    "git_sha",
    "commit_date",
    "import_version",
    "features",
}


@pytest.fixture
def member_client(client_as, member_only):
    return client_as(member_only)


@pytest.mark.django_db
def test_requires_authentication():
    response = APIClient().get(reverse(URL_NAME))

    assert response.status_code == 401


@pytest.mark.django_db
@override_settings(
    EPICSTAFF_VERSION="v1.6.0",
    EPICSTAFF_GIT_REF="main",
    EPICSTAFF_GIT_SHA="3f9c2a1e" + "0" * 32,
    EPICSTAFF_COMMIT_DATE="2026-11-24T14:02:00+02:00",
)
def test_returns_build_identity(member_client):
    body = member_client.get(reverse(URL_NAME)).json()

    assert body["version"] == "v1.6.0"
    assert body["git_ref"] == "main"
    assert body["git_sha"] == "3f9c2a1e" + "0" * 32
    assert body["commit_date"] == "2026-11-24T14:02:00+02:00"


@pytest.mark.django_db
@override_settings(
    EPICSTAFF_VERSION="",
    EPICSTAFF_GIT_REF="",
    EPICSTAFF_GIT_SHA="",
    EPICSTAFF_COMMIT_DATE="",
)
def test_empty_build_values_are_null(member_client):
    body = member_client.get(reverse(URL_NAME)).json()

    assert body["version"] is None
    assert body["git_ref"] is None
    assert body["git_sha"] is None
    assert body["commit_date"] is None


@pytest.mark.django_db
@override_settings(
    CHAT_ENABLED=True,
    PLUGINS_ENABLED=False,
    SESSION_AUDIT_TRAIL_ENABLED=True,
    USER_AUDIT_TRAIL_ENABLED=False,
)
def test_reports_each_feature_flag(member_client):
    body = member_client.get(reverse(URL_NAME)).json()

    assert body["features"] == {
        "chats": True,
        "plugins": False,
        "session_audit": True,
        "user_audit": False,
    }


@pytest.mark.django_db
def test_import_version_matches_constant(member_client):
    body = member_client.get(reverse(URL_NAME)).json()

    assert body["import_version"] == IMPORT_VERSION


@pytest.mark.django_db
def test_response_is_not_cached(member_client):
    response = member_client.get(reverse(URL_NAME))

    assert response["Cache-Control"] == "private, no-store"


@pytest.mark.django_db
def test_returns_only_documented_keys(member_client):
    body = member_client.get(reverse(URL_NAME)).json()

    assert set(body) == DOCUMENTED_KEYS


@pytest.mark.django_db
def test_works_for_member_without_admin_role(member_client):
    response = member_client.get(reverse(URL_NAME))

    assert response.status_code == 200
