"""Own each flow assistant conversation by its user instead of by an org membership.

A superadmin may act in an org they are not a member of, and has no membership row there
to own a conversation. The org stays reachable through the conversation's flow.

Forward: `user` is copied from the membership's user, then `organization_user` is dropped.
Backward: `organization_user` is filled with the user's membership in the flow's org. A
conversation with no such membership (a superadmin's in an org they are not a member of)
cannot be owned by a membership and is deleted with its messages.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import OuterRef, Subquery


def copy_user_from_membership(apps, schema_editor):
    conversation_model = apps.get_model("tables", "FlowAssistantConversation")
    membership_model = apps.get_model("rbac", "OrganizationUser")
    conversation_model._base_manager.update(
        user_id=Subquery(
            membership_model.objects.filter(pk=OuterRef("organization_user_id")).values("user_id")[:1]
        )
    )
    # The update queues deferred FK checks; Postgres refuses the SET NOT NULL ALTER TABLE
    # below while they are pending, so run them now.
    schema_editor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def restore_membership_from_user(apps, schema_editor):
    conversation_model = apps.get_model("tables", "FlowAssistantConversation")
    membership_model = apps.get_model("rbac", "OrganizationUser")
    membership_ids = {
        (user_id, org_id): membership_id
        for membership_id, user_id, org_id in membership_model.objects.values_list("pk", "user_id", "org_id")
    }
    restored = []
    without_membership = []
    for conversation_id, user_id, org_id in conversation_model._base_manager.values_list(
        "pk", "user_id", "flow_assistant__graph__org_id"
    ):
        membership_id = membership_ids.get((user_id, org_id))
        if membership_id is None:
            without_membership.append(conversation_id)
        else:
            restored.append(conversation_model(pk=conversation_id, organization_user_id=membership_id))
    conversation_model._base_manager.bulk_update(restored, ["organization_user"], batch_size=1000)
    conversation_model._base_manager.filter(pk__in=without_membership).delete()
    schema_editor.execute("SET CONSTRAINTS ALL IMMEDIATE")


class Migration(migrations.Migration):
    dependencies = [
        ("tables", "0297_merge_20261120_1512"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="flowassistantconversation",
            name="user",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="flow_assistant_conversations",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="flowassistantconversation",
            name="organization_user",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="flow_assistant_conversations",
                to="rbac.organizationuser",
            ),
        ),
        migrations.RunPython(copy_user_from_membership, restore_membership_from_user),
        migrations.AlterField(
            model_name="flowassistantconversation",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="flow_assistant_conversations",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RemoveField(
            model_name="flowassistantconversation",
            name="organization_user",
        ),
    ]
