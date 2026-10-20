import pytest

from rbac.models import ApiKey
from rbac.serializers.api_keys import ApiKeyAdminSerializer

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def key(db, django_user_model):
    owner = django_user_model.objects.create_user(
        email="serialized@example.com", password="StrongPass123!"
    )
    return ApiKey.objects.create(
        name="k",
        key_type=ApiKey.KeyType.USER,
        prefix="es-000000000",
        key_hash="hash-serializer",
        created_by=owner,
    )


@pytest.mark.django_db
def test_org_ids_come_from_the_attached_attribute(key):
    key._visible_org_ids = [7, 9]

    assert ApiKeyAdminSerializer(key).data["org_ids"] == [7, 9]


@pytest.mark.django_db
def test_org_ids_default_to_empty_when_not_attached(key):
    assert ApiKeyAdminSerializer(key).data["org_ids"] == []


@pytest.mark.django_db
def test_no_secret_material_is_serialized(key):
    key.visible_owner = key.created_by

    data = ApiKeyAdminSerializer(key).data

    assert "key_hash" not in data
    assert "api_key" not in data
    assert data["owner"]["email"] == "serialized@example.com"


@pytest.mark.django_db
def test_owner_is_withheld_when_visibility_was_never_attached(key):
    data = ApiKeyAdminSerializer(key).data

    assert data["owner"] is None
    assert "serialized@example.com" not in str(data)


@pytest.mark.django_db
def test_owner_is_withheld_when_the_service_decided_to_hide_it(key):
    key.visible_owner = None

    assert ApiKeyAdminSerializer(key).data["owner"] is None
