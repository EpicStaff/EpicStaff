"""A USER API key belongs to exactly one organization; a SYSTEM key to none.

The database enforces it (`api_key_type_invariants`), the key goes with its org, and
rbac 0012 deletes the USER keys that existed before keys had an org.
"""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from rbac.identity.api_keys.generator import ApiKeyGenerator
from rbac.models import ApiKey
from tables.models.session_models import Session, SessionPrincipal
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

BEFORE = [("rbac", "0011_merge_retention_and_resource_types")]
AFTER = [("rbac", "0012_api_key_org")]


def _key_fields(**fields) -> dict:
    generated = ApiKeyGenerator.generate()
    return {
        "name": "org-test-key",
        "prefix": generated.prefix,
        "key_hash": generated.key_hash,
        **fields,
    }


@pytest.mark.django_db
def test_user_key_without_org_is_rejected_by_the_database(member_only):
    with pytest.raises(IntegrityError), transaction.atomic():
        ApiKey.objects.create(**_key_fields(key_type="user", created_by=member_only, org=None))


@pytest.mark.django_db
def test_system_key_with_org_is_rejected_by_the_database(acme):
    with pytest.raises(IntegrityError), transaction.atomic():
        ApiKey.objects.create(**_key_fields(key_type="system", created_by=None, org=acme))


@pytest.mark.django_db
def test_deleting_the_org_deletes_its_keys(acme, beta, member_only):
    acme_key = ApiKey.objects.create(**_key_fields(key_type="user", created_by=member_only, org=acme))
    beta_key = ApiKey.objects.create(**_key_fields(key_type="user", created_by=member_only, org=beta))

    acme.delete()

    assert not ApiKey.objects.filter(pk=acme_key.pk).exists()
    assert ApiKey.objects.filter(pk=beta_key.pk).exists()


def _migrate(targets):
    MigrationExecutor(connection).migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


@pytest.mark.django_db(transaction=True)
def test_migration_deletes_user_keys_and_keeps_system_key_and_sessions():
    try:
        old_apps = _migrate(BEFORE)
        # Only rbac goes back, so tables-side rows use the live models; the historical
        # User misses columns added later by other apps. ApiKey must be historical (no org).
        owner = get_user_model().objects.create_user(
            email="key-owner@migration.test", password="StrongPass123!"
        )
        old_api_key_model = old_apps.get_model("rbac", "ApiKey")
        system_key_pk = old_api_key_model.objects.create(
            **_key_fields(name="system", key_type="system", created_by_id=None)
        ).pk
        user_key_pk = old_api_key_model.objects.create(
            **_key_fields(name="personal", key_type="user", created_by_id=owner.pk)
        ).pk
        principal_pk = SessionPrincipal.objects.create(
            session=Session.objects.create(status=Session.SessionStatus.END),
            kind=SessionPrincipal.ActionKind.API_KEY_USER,
            user=owner,
            api_key_id=user_key_pk,
            email=owner.email,
        ).pk

        new_apps = _migrate(AFTER)

        new_api_key_model = new_apps.get_model("rbac", "ApiKey")
        assert not new_api_key_model.objects.filter(pk=user_key_pk).exists()
        assert new_api_key_model.objects.filter(pk=system_key_pk, org__isnull=True).exists()
        principal = SessionPrincipal.objects.get(pk=principal_pk)
        assert principal.api_key_id is None
        assert (principal.user_id, principal.email) == (owner.pk, "key-owner@migration.test")
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
