"""tables 0298 moves a flow assistant conversation's owner from a membership to its user.

Forward: `user` is the membership's user, whatever the conversation's soft-delete state.
Backward: `organization_user` is the user's membership in the flow's org; a conversation
whose user has no membership there (a superadmin's) is deleted with its messages.
"""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

BEFORE = [("tables", "0297_merge_20261120_1512")]
AFTER = [("tables", "0298_flow_assistant_conversation_user")]


def _migrate(targets):
    MigrationExecutor(connection).migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


def _conversation_columns() -> set[str]:
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(
            cursor, "tables_flowassistantconversation"
        )
    return {column.name for column in description}


@pytest.mark.django_db(transaction=True)
def test_conversation_owner_moves_to_the_user_and_back():
    try:
        old_apps = _migrate(BEFORE)
        organization = old_apps.get_model("rbac", "Organization").objects.create(name="owner-migration-org")
        role = old_apps.get_model("rbac", "Role").objects.create(name="owner-migration-role", org=organization)
        user_model = old_apps.get_model("tables", "User")
        member = user_model.objects.create(email="member@owner-migration.test", password="!")
        superadmin = user_model.objects.create(email="superadmin@owner-migration.test", password="!", is_superadmin=True)
        membership = old_apps.get_model("rbac", "OrganizationUser").objects.create(
            user=member, org=organization, role=role
        )
        graph = old_apps.get_model("tables", "Graph").objects.create(org=organization, name="owner-migration-flow", metadata={})
        assistant = old_apps.get_model("tables", "FlowAssistant").objects.create(graph=graph)
        old_conversation_model = old_apps.get_model("tables", "FlowAssistantConversation")
        live_pk = old_conversation_model.objects.create(flow_assistant=assistant, organization_user=membership).pk
        binned_pk = old_conversation_model._base_manager.create(
            flow_assistant=assistant, organization_user=membership, active=False, soft_deleted_at=timezone.now()
        ).pk

        new_apps = _migrate(AFTER)
        assert "organization_user_id" not in _conversation_columns()
        new_conversation_model = new_apps.get_model("tables", "FlowAssistantConversation")
        assert dict(new_conversation_model._base_manager.values_list("pk", "user_id")) == {
            live_pk: member.pk,
            binned_pk: member.pk,
        }
        superadmin_conversation = new_conversation_model._base_manager.create(flow_assistant_id=assistant.pk, user_id=superadmin.pk)
        new_apps.get_model("tables", "FlowAssistantMessage")._base_manager.create(
            conversation=superadmin_conversation, message_index=0, role="user", content="hi"
        )

        reverted_apps = _migrate(BEFORE)
        assert "user_id" not in _conversation_columns()
        reverted_conversation_model = reverted_apps.get_model("tables", "FlowAssistantConversation")
        assert dict(reverted_conversation_model._base_manager.values_list("pk", "organization_user_id")) == {
            live_pk: membership.pk,
            binned_pk: membership.pk,
        }
        assert not reverted_apps.get_model("tables", "FlowAssistantMessage")._base_manager.filter(
            conversation_id=superadmin_conversation.pk
        ).exists()
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
