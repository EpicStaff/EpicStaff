import pytest
from django.core.exceptions import ValidationError

from rbac.models import Organization
from storage_credentials.constants import SECRET_NAME_ORG_STORAGE_USER
from storage_credentials.services.org_credential_store import org_credential_store
from tables.models import Secret
from tables.services.secrets import secret_service


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org SecretNameValidation")


@pytest.mark.django_db
def test_create_rejects_name_that_runs_as_code_inside_an_fstring_without_saving(org):
    with pytest.raises(ValidationError):
        secret_service.create(text="sk-live-abc123", org_id=org.id, name="KEY{exec(input())}")

    assert not Secret.all_objects.filter(org=org).exists()


@pytest.mark.django_db
def test_system_storage_credentials_name_still_passes(org):
    org_credential_store.save(org=org, access_key="access", secret_key="secret-key")

    assert Secret.all_objects.filter(
        org=org, name=SECRET_NAME_ORG_STORAGE_USER, system=True
    ).exists()
