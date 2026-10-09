"""Revoking a superadmin clears them from the version snapshots of every org they are not in.

As a superadmin they may edit flows of an organization they are not a member of; once the
role is revoked that organization must not see them in a version preview, nor get them
back on its nodes by restoring a version.
"""

from datetime import UTC, datetime

import pytest
from django.contrib.contenttypes.models import ContentType

from rbac.authorship import record_last_edit
from rbac.governance.users import UserManagementService
from rbac.models import OrganizationUser, ResourceLastEdit
from tables.models import Graph
from tables.models.graph_models import AgentNode
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

EDITED_AT = datetime(2024, 2, 3, 4, 5, 6, tzinfo=UTC)


@pytest.fixture
def acting_superadmin(db, django_user_model):
    """Keeps an active superadmin once `superadmin` is revoked."""
    return django_user_model.objects.create_user(
        email="acting-superadmin-revoke@example.com",
        password="StrongPass123!",
        is_superadmin=True,
    )


@pytest.fixture
def flow(acme):
    return Graph.objects.create(name="superadmin-edited-flow", org=acme)


@pytest.fixture
def superadmin_node(flow, superadmin):
    """A node the superadmin authored and last edited in acme, where they are no member."""
    node = AgentNode.objects.create(graph=flow, node_name="agent", created_by=superadmin)
    record_last_edit(node, superadmin, edited_at=EDITED_AT)
    return node


def _revoke(acting_superadmin, superadmin):
    UserManagementService().revoke_superadmin(
        actor=acting_superadmin, target_user_id=superadmin.pk
    )


def _restore(service, version, user):
    version.graph.refresh_from_db()
    return service.restore_version(
        version, expected_save_version=version.graph.save_version, user=user
    )


def _last_edit_of(instance) -> ResourceLastEdit | None:
    return ResourceLastEdit.objects.filter(
        content_type=ContentType.objects.get_for_model(instance), object_id=instance.pk
    ).first()


@pytest.mark.django_db
def test_preview_after_revoke_shows_no_former_superadmin(
    service, flow, superadmin, acting_superadmin, superadmin_node
):
    version = service.save_version(flow, name="v1")

    _revoke(acting_superadmin, superadmin)
    version.refresh_from_db()

    entry = service.preview_version(version)["node_authorship"][str(superadmin_node.id)]
    assert entry["created_by"] is None
    assert entry["last_edited_by"] is None
    assert entry["last_edited_at"] == EDITED_AT


@pytest.mark.django_db
def test_restore_after_revoke_writes_no_former_superadmin_onto_nodes(
    service, flow, admin_acme, superadmin, acting_superadmin, superadmin_node
):
    version = service.save_version(flow, name="v1")

    _revoke(acting_superadmin, superadmin)
    version.refresh_from_db()
    _restore(service, version, admin_acme)

    [restored] = flow.agent_node_list.all()
    assert restored.id != superadmin_node.id
    assert restored.created_by_id is None
    last_edit = _last_edit_of(restored)
    assert last_edit.edited_by_id is None
    assert last_edit.edited_at == EDITED_AT


@pytest.mark.django_db
def test_revoke_keeps_the_snapshots_of_an_org_the_superadmin_is_a_member_of(
    service, flow, acme, role_member, superadmin, acting_superadmin, superadmin_node
):
    OrganizationUser.objects.create(user=superadmin, org=acme, role=role_member)
    version = service.save_version(flow, name="v1")

    _revoke(acting_superadmin, superadmin)
    version.refresh_from_db()

    assert version.snapshot["node_authorship"][str(superadmin_node.id)]["created_by"] == (
        superadmin.id
    )
    assert version.snapshot["node_last_edit"][str(superadmin_node.id)]["edited_by"] == (
        superadmin.id
    )
    entry = service.preview_version(version)["node_authorship"][str(superadmin_node.id)]
    assert entry["created_by"] == superadmin
    assert entry["last_edited_by"] == superadmin
