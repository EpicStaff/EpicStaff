import pytest

from tables.models.rbac_models import ApiKey
from tables.serializers.api_key_serializers import ApiKeyAdminSerializer

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
    data = ApiKeyAdminSerializer(key).data

    assert "key_hash" not in data
    assert "api_key" not in data
    assert data["owner"]["email"] == "serialized@example.com"
