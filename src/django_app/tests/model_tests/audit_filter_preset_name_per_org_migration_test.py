from importlib import import_module

import pytest
from django.db import connection

from tables.models.audit_filter_preset_models import AuditFilterPreset
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

dedupe_migration = import_module("tables.migrations.0262_audit_filter_preset_name_unique_per_org")


@pytest.fixture
def allow_duplicate_names_in_org(db):
    """Recreate the pre-0262 schema, where only (org, created_by, name) was unique.

    Postgres DDL is transactional: the test transaction's rollback restores the constraint.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE tables_auditfilterpreset "
            "DROP CONSTRAINT unique_audit_filter_preset_name_per_org;"
        )
    yield


def _preset(org, user, name):
    return AuditFilterPreset.objects.create(org=org, created_by=user, name=name)


@pytest.mark.django_db
def test_same_name_from_two_users_in_one_org_gets_numbered(
    allow_duplicate_names_in_org, acme, admin_acme, member_only
):
    oldest = _preset(acme, admin_acme, "Failed runs")
    newer = _preset(acme, member_only, "Failed runs")

    dedupe_migration.dedupe_preset_names_per_org(AuditFilterPreset)

    oldest.refresh_from_db()
    newer.refresh_from_db()
    assert (oldest.name, newer.name) == ("Failed runs", "Failed runs (2)")


@pytest.mark.django_db
def test_same_name_in_two_orgs_is_untouched(
    allow_duplicate_names_in_org, acme, beta, admin_acme, superadmin
):
    acme_preset = _preset(acme, admin_acme, "Failed runs")
    beta_preset = _preset(beta, superadmin, "Failed runs")

    dedupe_migration.dedupe_preset_names_per_org(AuditFilterPreset)

    acme_preset.refresh_from_db()
    beta_preset.refresh_from_db()
    assert (acme_preset.name, beta_preset.name) == ("Failed runs", "Failed runs")


@pytest.mark.django_db
def test_rename_skips_a_taken_number_and_fits_the_column(
    allow_duplicate_names_in_org, acme, admin_acme, member_only
):
    long_name = "x" * 150
    _preset(acme, admin_acme, "Failed runs")
    _preset(acme, admin_acme, "Failed runs (2)")
    third = _preset(acme, member_only, "Failed runs")
    _preset(acme, admin_acme, long_name)
    long_duplicate = _preset(acme, member_only, long_name)

    dedupe_migration.dedupe_preset_names_per_org(AuditFilterPreset)

    third.refresh_from_db()
    long_duplicate.refresh_from_db()
    assert third.name == "Failed runs (3)"
    assert long_duplicate.name == "x" * 146 + " (2)"


@pytest.mark.django_db
def test_rename_skips_a_numbered_name_created_after_the_duplicate(
    allow_duplicate_names_in_org, acme, admin_acme, member_only
):
    _preset(acme, admin_acme, "Failed runs")
    duplicate = _preset(acme, member_only, "Failed runs")
    _preset(acme, admin_acme, "Failed runs (2)")

    dedupe_migration.dedupe_preset_names_per_org(AuditFilterPreset)

    duplicate.refresh_from_db()
    assert duplicate.name == "Failed runs (3)"
