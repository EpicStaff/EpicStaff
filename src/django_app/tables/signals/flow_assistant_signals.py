from django.dispatch import receiver
from rbac.models import OrganizationUser
from rbac.signals import member_removed, superadmin_revoked

from tables.models.flow_assistant_models import FlowAssistantConversation


@receiver(member_removed)
def delete_conversations_in_left_org(sender, user_id, org_id, **kwargs):
    """A removed member can no longer open their conversations on the org's flows."""
    FlowAssistantConversation.all_objects.filter(
        user_id=user_id, flow_assistant__graph__org_id=org_id
    ).delete()


@receiver(superadmin_revoked)
def delete_conversations_outside_memberships(sender, user_id, **kwargs):
    """A former superadmin can no longer open conversations in orgs they are not a member of."""
    FlowAssistantConversation.all_objects.filter(user_id=user_id).exclude(
        flow_assistant__graph__org_id__in=OrganizationUser.objects.filter(user_id=user_id).values(
            "org_id"
        )
    ).delete()
