"""`OrgCredentialStore` keeps an organization's storage credentials as a system `Secret`."""

import pytest

from rbac.models import Organization
from tables.services.secrets.secret_service import secret_service

from storage_credentials.constants import SECRET_NAME_ORG_STORAGE_USER
from storage_credentials.exceptions import OrgStorageCredentialMissingError
from storage_credentials.services.org_credential_store import org_credential_store


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org Credential Store Test Org")


@pytest.mark.django_db
def test_stored_credentials_are_read_back_until_deleted(org):
    secret_service.create(
        text="access-key-1:secret-key-1", system=True, org=org, name=SECRET_NAME_ORG_STORAGE_USER
    )

    credentials = org_credential_store.get(org_id=org.id)
    assert (credentials.access_key, credentials.secret_key) == ("access-key-1", "secret-key-1")
    assert org_credential_store.exists(org_id=org.id) is True

    org_credential_store.delete(org_id=org.id)
    org_credential_store.delete(org_id=org.id)  # idempotent

    assert org_credential_store.exists(org_id=org.id) is False
    with pytest.raises(OrgStorageCredentialMissingError):
        org_credential_store.get(org_id=org.id)


@pytest.mark.django_db
def test_an_org_without_credentials_is_reported_missing(org):
    assert org_credential_store.exists(org_id=org.id) is False
    with pytest.raises(OrgStorageCredentialMissingError):
        org_credential_store.get(org_id=org.id)
