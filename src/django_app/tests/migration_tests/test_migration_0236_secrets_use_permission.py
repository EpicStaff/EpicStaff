"""Tests for the 0236 migration: built-in secrets masks after --create-db, and the custom-role USE grant."""

import importlib

import pytest
from django.apps import apps as real_apps

from tables.models.rbac_models import Organization, Role, RolePermission
from tables.models.rbac_models.rbac_enums import BuiltInRole

migration = importlib.import_module("tables.migrations.0236_secrets_use_permission")
grant_use_to_custom_roles = migration.grant_use_to_custom_roles


@pytest.mark.django_db
class TestBuiltInMasksAfterCreateDb:
    """Verifies the migration actually ran against test_crew (built via --create-db) and left the expected masks."""

    def test_org_admin_keeps_207(self):
        role = Role.objects.get(
            name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
        )
        row = RolePermission.objects.get(role=role, resource_type="secrets")
        assert row.permissions == 207

    def test_member_is_revoked_to_128(self):
        role = Role.objects.get(
            name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True
        )
        row = RolePermission.objects.get(role=role, resource_type="secrets")
        assert row.permissions == 128

    def test_viewer_is_revoked_to_128(self):
        role = Role.objects.get(
            name=BuiltInRole.VIEWER, is_built_in=True, org__isnull=True
        )
        row = RolePermission.objects.get(role=role, resource_type="secrets")
        assert row.permissions == 128


@pytest.mark.django_db
class TestCustomRoleUseGrant:
    """Calls the migration's forward function directly against the current schema, since no schema changed between 0235 and 0236."""

    def test_role_with_flows_update_gains_secrets_use(self):
        org = Organization.objects.create(name="Custom Grant Org")
        role_with_update = Role.objects.create(
            name="Editor", is_built_in=False, org=org
        )
        RolePermission.objects.create(
            role=role_with_update, resource_type="flows", permissions=4
        )

        grant_use_to_custom_roles(real_apps, None)

        row = RolePermission.objects.get(role=role_with_update, resource_type="secrets")
        assert row.permissions & 64

    def test_role_without_flows_update_is_untouched(self):
        org = Organization.objects.create(name="Custom No-Grant Org")
        role_without_update = Role.objects.create(
            name="Reader", is_built_in=False, org=org
        )
        RolePermission.objects.create(
            role=role_without_update, resource_type="flows", permissions=2
        )

        grant_use_to_custom_roles(real_apps, None)

        assert not RolePermission.objects.filter(
            role=role_without_update, resource_type="secrets"
        ).exists()

    def test_built_in_role_is_never_touched_by_the_grant(self):
        role_member = Role.objects.get(
            name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True
        )
        RolePermission.objects.filter(role=role_member, resource_type="flows").update(
            permissions=4
        )
        before = RolePermission.objects.get(
            role=role_member, resource_type="secrets"
        ).permissions

        grant_use_to_custom_roles(real_apps, None)

        after = RolePermission.objects.get(
            role=role_member, resource_type="secrets"
        ).permissions
        assert after == before
