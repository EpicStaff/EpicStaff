from rbac.access.asserts import assert_row_org_permission
from rbac.models.enums import Permission, ResourceType
from rest_framework.exceptions import NotFound
from tables.models.flow_assistant_models import FlowAssistantConversation


def get_streamable_conversation(
    user, graph_id: int, conversation_id: int, *, api_key_org_id: int | None
) -> FlowAssistantConversation:
    """Fetch the conversation to stream a reply for, authorizing `user` via its flow's org.

    The SSE ticket proves only who the user is, and EventSource cannot send the
    X-Organization-Id header, so the org is the one that owns the conversation's
    graph. A missing, soft-deleted or another user's conversation, and one in an org
    the user is not an active member of, all raise the same NotFound, so the response
    never reveals that a conversation id exists. Superadmin passes the org check but must
    still own the conversation. With `api_key_org_id` (the org of the caller's USER API
    key), a conversation of any other org is not found either.

    Raises:
        NotFound (404): no conversation the user may stream.
        PermissionDenied (403): a member of the owning org whose role lacks READ on FLOWS.
    """
    not_found = NotFound("Conversation not found.")
    conversation = (
        FlowAssistantConversation.objects.select_related(
            "flow_assistant__graph",
            "flow_assistant__llm_config__model__llm_provider",
            "organization_user__user",
        )
        .filter(
            pk=conversation_id,
            flow_assistant__graph_id=graph_id,
            organization_user__user_id=user.pk,
            deleted_at__isnull=True,
        )
        .first()
    )
    if conversation is None:
        raise not_found
    assert_row_org_permission(
        user,
        conversation.flow_assistant.graph.org_id,
        ResourceType.FLOWS,
        Permission.READ,
        not_found=not_found,
        api_key_org_id=api_key_org_id,
    )
    return conversation
