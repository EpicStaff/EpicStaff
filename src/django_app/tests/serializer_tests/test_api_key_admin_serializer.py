import pytest

from rbac.serializers.api_keys import ApiKeyAdminSerializer

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def key(issue_api_key, django_user_model, acme):
    owner = django_user_model.objects.create_user(
        email="serialized@example.com", password="StrongPass123!"
    )
    _, key = issue_api_key(user=owner, org=acme, name="k")
    return key


@pytest.mark.django_db
def test_admin_row_carries_the_keys_single_org(key, acme):
    data = ApiKeyAdminSerializer(key).data

    assert (data["org_id"], data["org_name"]) == (acme.id, acme.name)
    assert "org_ids" not in data


@pytest.mark.django_db
def test_no_secret_material_is_serialized(key):
    data = ApiKeyAdminSerializer(key).data

    assert "key_hash" not in data
    assert "api_key" not in data
    assert data["owner"]["email"] == "serialized@example.com"
