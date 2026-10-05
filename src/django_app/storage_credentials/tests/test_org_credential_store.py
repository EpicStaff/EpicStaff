"""Tests for `OrgCredentialStore` which manages organization-level storage
credentials persisted as `Secret` rows."""

import pytest

from rbac.models import Organization
from tables.models import Secret
from tables.services.secrets.secret_service import secret_service

from storage_credentials.constants import SECRET_NAME_ORG_STORAGE_USER
from storage_credentials.exceptions import OrgStorageCredentialMissingError
from storage_credentials.services.org_credential_store import org_credential_store

CREDENTIAL_TEXT = "access-key-1:secret-key-1"


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org Credential Store Test Org")


@pytest.mark.django_db
def test_get_returns_credentials_for_never_revoked_secret(org):
    secret_service.create(
        text=CREDENTIAL_TEXT,
        system=True,
        org=org,
        name=SECRET_NAME_ORG_STORAGE_USER,
    )
    assert (
        Secret.all_objects.get(org=org, name=SECRET_NAME_ORG_STORAGE_USER).metadata == {}
    )

    credentials = org_credential_store.get(org_id=org.id)

    assert credentials.access_key == "access-key-1"
    assert credentials.secret_key == "secret-key-1"


@pytest.mark.django_db
def test_exists_is_true_for_never_revoked_secret(org):
    secret_service.create(
        text=CREDENTIAL_TEXT,
        system=True,
        org=org,
        name=SECRET_NAME_ORG_STORAGE_USER,
    )

    assert org_credential_store.exists(org_id=org.id) is True


@pytest.mark.django_db
def test_get_raises_when_no_secret_exists(org):
    with pytest.raises(OrgStorageCredentialMissingError):
        org_credential_store.get(org_id=org.id)


@pytest.mark.django_db
def test_delete_removes_secret(org):
    secret_service.create(
        text=CREDENTIAL_TEXT,
        system=True,
        org=org,
        name=SECRET_NAME_ORG_STORAGE_USER,
    )
    assert org_credential_store.exists(org_id=org.id) is True

    org_credential_store.delete(org_id=org.id)

    assert org_credential_store.exists(org_id=org.id) is False
    with pytest.raises(OrgStorageCredentialMissingError):
        org_credential_store.get(org_id=org.id)


@pytest.mark.django_db
def test_delete_is_idempotent(org):
    secret_service.create(
        text=CREDENTIAL_TEXT,
        system=True,
        org=org,
        name=SECRET_NAME_ORG_STORAGE_USER,
    )

    org_credential_store.delete(org_id=org.id)
    # Second delete should not raise, just be a no-op
    org_credential_store.delete(org_id=org.id)

    assert org_credential_store.exists(org_id=org.id) is False
