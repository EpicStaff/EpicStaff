import io
from datetime import UTC, datetime

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from rbac.authorship import record_last_edit
from rbac.models import Organization, ResourceLastEdit
from tables.graph_versioning.services import GraphVersioningService
from tables.models import Graph, GraphVersion
from tables.models.graph_models import AgentNode

PASSWORD = "StrongPass123!"


@pytest.mark.django_db
def test_replaces_every_user_with_a_new_superadmin():
    get_user_model().objects.create_user(email="old@example.com", password=PASSWORD)
    out = io.StringIO()

    call_command("reset_user", "--email", "ops@example.com", "--password", PASSWORD, stdout=out)

    users = get_user_model().objects.all()
    assert [(user.email, user.is_superadmin) for user in users] == [("ops@example.com", True)]
    assert "ops@example.com" in out.getvalue()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("email", "password", "reason"),
    [
        ("---@example.com", PASSWORD, "email: The part before @ must start and end"),
        ("ops@example.com", "1", "password:"),
    ],
    ids=["new-account-email-rule", "password-validators"],
)
def test_invalid_input_fails_before_any_user_is_deleted(email, password, reason):
    get_user_model().objects.create_user(email="old@example.com", password=PASSWORD)

    with pytest.raises(CommandError, match=reason):
        call_command(
            "reset_user", f"--email={email}", f"--password={password}", stdout=io.StringIO()
        )

    assert list(get_user_model().objects.values_list("email", flat=True)) == ["old@example.com"]


@pytest.mark.django_db
def test_a_version_saved_before_the_reset_restores_without_author_or_editor():
    """Flows and versions survive the reset, so no snapshot may keep a deleted user's id."""
    old_user = get_user_model().objects.create_user(email="old@example.com", password=PASSWORD)
    flow = Graph.objects.create(name="pre-reset-flow", org=Organization.objects.create(name="Kept"))
    node = AgentNode.objects.create(graph=flow, node_name="agent", created_by=old_user)
    edited_at = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
    record_last_edit(node, old_user, edited_at=edited_at)
    version = GraphVersioningService().save_version(flow, name="before reset")

    call_command(
        "reset_user", "--email", "ops@example.com", "--password", PASSWORD, stdout=io.StringIO()
    )
    version = GraphVersion.objects.get(pk=version.pk)
    flow.refresh_from_db()
    new_superadmin = get_user_model().objects.get(email="ops@example.com")
    GraphVersioningService().restore_version(
        version, expected_save_version=flow.save_version, user=new_superadmin
    )

    connection.check_constraints()
    restored_node = AgentNode.objects.get(graph=flow)
    assert restored_node.created_by_id is None
    last_edit = ResourceLastEdit.objects.get(
        content_type=ContentType.objects.get_for_model(AgentNode), object_id=restored_node.pk
    )
    assert (last_edit.edited_by_id, last_edit.edited_at) == (None, edited_at)
