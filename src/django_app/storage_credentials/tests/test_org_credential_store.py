"""Regression test for the `.exclude(metadata__revoked=True)` bug: with
`metadata={}` (the state of a freshly provisioned, never-revoked row),
Postgres evaluates `metadata -> 'revoked'` as SQL NULL, and
`NOT (NULL = 'true'::jsonb)` is also NULL -- so the row was wrongly excluded
from the queryset and every never-revoked org's credentials were invisible
to `OrgCredentialStore`. `get()`/`exists()` must instead select the single
(org, name, system) row and test `revoked` in Python.
"""

import pytest

from tables.models import Organization, Secret
from tables.services.secrets.secret_service import secret_service

from storage_credentials.constants import SECRET_NAME_ORG_MINIO_USER
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
        name=SECRET_NAME_ORG_MINIO_USER,
    )
    assert Secret.objects.get(org=org, name=SECRET_NAME_ORG_MINIO_USER).metadata == {}

    credentials = org_credential_store.get(org_id=org.id)

    assert credentials.access_key == "access-key-1"
    assert credentials.secret_key == "secret-key-1"


@pytest.mark.django_db
def test_exists_is_true_for_never_revoked_secret(org):
    secret_service.create(
        text=CREDENTIAL_TEXT,
        system=True,
        org=org,
        name=SECRET_NAME_ORG_MINIO_USER,
    )

    assert org_credential_store.exists(org_id=org.id) is True


@pytest.mark.django_db
def test_get_raises_for_revoked_secret(org):
    secret = secret_service.create(
        text=CREDENTIAL_TEXT,
        system=True,
        org=org,
        name=SECRET_NAME_ORG_MINIO_USER,
    )
    secret.metadata = {"revoked": True}
    secret.save(update_fields=["metadata"])

    with pytest.raises(OrgStorageCredentialMissingError):
        org_credential_store.get(org_id=org.id)


@pytest.mark.django_db
def test_exists_is_false_for_revoked_secret(org):
    secret = secret_service.create(
        text=CREDENTIAL_TEXT,
        system=True,
        org=org,
        name=SECRET_NAME_ORG_MINIO_USER,
    )
    secret.metadata = {"revoked": True}
    secret.save(update_fields=["metadata"])

    assert org_credential_store.exists(org_id=org.id) is False


@pytest.mark.django_db
def test_get_raises_when_no_secret_exists(org):
    with pytest.raises(OrgStorageCredentialMissingError):
        org_credential_store.get(org_id=org.id)
