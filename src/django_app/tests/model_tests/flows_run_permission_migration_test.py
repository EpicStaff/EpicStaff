"""The data migration that grants flows:RUN to custom roles which could run flows before."""

from importlib import import_module

import pytest
from django.apps import apps

from rbac.models import Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

run_migration = import_module("rbac.migrations.0007_flows_run_permission")

FLOWS = ResourceType.FLOWS.value


def _custom_role(org, name, by_resource):
    role = Role.objects.create(name=name, org=org, is_built_in=False)
    for resource_type, permissions in by_resource.items():
        RolePermission.objects.create(
            role=role, resource_type=resource_type, permissions=int(permissions)
        )
    return role


def _mask(role, resource_type):
    row = RolePermission.objects.filter(role=role, resource_type=resource_type).first()
    return None if row is None else row.permissions


@pytest.mark.django_db
def test_custom_role_holding_flows_read_gains_run_and_keeps_its_bits(acme):
    reader = _custom_role(acme, "reader", {FLOWS: Permission.READ | Permission.EXPORT})

    run_migration.grant_run_to_custom_roles(apps, None)

    assert _mask(reader, FLOWS) == Permission.READ | Permission.EXPORT | Permission.RUN


@pytest.mark.django_db
def test_custom_role_without_flows_read_is_left_alone(acme):
    writer = _custom_role(acme, "writer-only", {FLOWS: Permission.UPDATE})
    no_flows = _custom_role(acme, "agents-reader", {ResourceType.AGENTS.value: Permission.READ})

    run_migration.grant_run_to_custom_roles(apps, None)

    assert _mask(writer, FLOWS) == Permission.UPDATE
    assert _mask(no_flows, FLOWS) is None
    assert _mask(no_flows, ResourceType.AGENTS.value) == Permission.READ


@pytest.mark.django_db
def test_built_in_roles_are_left_to_the_seeder(role_viewer):
    RolePermission.objects.filter(role=role_viewer, resource_type=FLOWS).update(
        permissions=int(Permission.READ)
    )

    run_migration.grant_run_to_custom_roles(apps, None)

    assert _mask(role_viewer, FLOWS) == Permission.READ


@pytest.mark.django_db
def test_reverse_clears_run_from_custom_roles_only(acme, role_member):
    runner = _custom_role(acme, "runner", {FLOWS: Permission.READ | Permission.RUN})
    member_mask = _mask(role_member, FLOWS)
    assert member_mask & Permission.RUN, "the seeded Member role is expected to hold run"

    run_migration.revoke_run_from_custom_roles(apps, None)

    assert _mask(runner, FLOWS) == Permission.READ
    assert _mask(role_member, FLOWS) == member_mask


@pytest.mark.django_db
def test_forward_is_idempotent(acme):
    runner = _custom_role(acme, "already-runs", {FLOWS: Permission.READ | Permission.RUN})

    run_migration.grant_run_to_custom_roles(apps, None)

    assert _mask(runner, FLOWS) == Permission.READ | Permission.RUN

