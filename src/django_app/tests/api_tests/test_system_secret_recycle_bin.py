"""System secrets (org storage credentials) stay out of everything the recycle bin opened up:
the bin itself, the link fields that keep binned secrets, and a flow version's restore."""

import uuid

import pytest
from django.utils import timezone
from tables.graph_versioning.manager import GraphVersioningManager
from tables.models import Secret
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

SYSTEM_NAME = "system_minio_org_user"


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def _system_secret(org, *, binned=False):
    secret = Secret.all_objects.create(name=SYSTEM_NAME, value="ciphertext-s", org=org, system=True)
    if binned:
        Secret.all_objects.filter(pk=secret.pk).update(
            active=False, soft_deleted_at=timezone.now(), soft_delete_batch=uuid.uuid4()
        )
    return secret


def test_managers_never_return_system_secrets(acme):
    live = _system_secret(acme)

    assert not Secret.objects.filter(pk=live.pk).exists()
    assert not Secret.deleted_objects.filter(pk=live.pk).exists()
    assert Secret.all_objects.filter(pk=live.pk).exists()


def test_a_binned_system_secret_is_not_in_the_bin_and_cannot_be_restored_or_purged(admin_client, acme):
    secret = _system_secret(acme, binned=True)

    listed = admin_client.get("/api/secrets/recycle-bin/")
    assert listed.status_code == 200
    assert secret.pk not in [entry["id"] for entry in listed.json()]
    assert admin_client.post(f"/api/secrets/{secret.pk}/restore/").status_code == 404
    assert admin_client.delete(f"/api/secrets/{secret.pk}/purge/").status_code == 404
    assert admin_client.post("/api/secrets/recycle-bin/restore/", {"ids": [secret.pk]}, format="json").status_code == 404
    assert Secret.all_objects.filter(pk=secret.pk, active=False).exists()


def test_a_link_field_refuses_a_system_secret(admin_client, acme):
    secret = _system_secret(acme)

    response = admin_client.post(
        "/api/python-code-tool/",
        {
            "name": "reads_storage_admin",
            "description": "tries to link a system secret",
            "python_code": {"code": "def main():\n    return 1", "entrypoint": "main", "secret_ids": [secret.pk]},
        },
        format="json",
    )

    assert response.status_code == 400, response.content
    assert f'Invalid pk \\"{secret.pk}\\"' in response.content.decode()
    assert not secret.python_codes.exists()


def test_a_version_restore_never_resolves_a_system_secret(acme):
    _system_secret(acme)

    resolved, missing = GraphVersioningManager._resolve_names(names=[SYSTEM_NAME], org_id=acme.pk)

    assert resolved == []
    assert missing == [SYSTEM_NAME]


def test_a_version_restore_resolves_the_user_secret_that_shares_a_system_name(acme):
    _system_secret(acme)
    user_secret = Secret.objects.create(name=SYSTEM_NAME, value="ciphertext-u", org=acme)

    resolved, missing = GraphVersioningManager._resolve_names(names=[SYSTEM_NAME], org_id=acme.pk)

    assert resolved == [user_secret]
    assert missing == []
