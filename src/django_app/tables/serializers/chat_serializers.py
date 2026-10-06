from rbac.scoping.fields import OrgScopedPrimaryKeyRelatedField
from rest_framework import serializers
from tables.models import ChatBinding, ChatConversation, ChatMessage, Graph
from tables.services.chat.conversation_service import conversation_tokens_used

_PREVIEW_LENGTH = 120


def _user_name(user) -> str | None:
    if user is None:
        return None
    return user.display_name or user.email


class ChatBindingSerializer(serializers.ModelSerializer):
    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())
    graph_name = serializers.CharField(source="graph.name", read_only=True)

    class Meta:
        model = ChatBinding
        fields = [
            "id",
            "graph",
            "graph_name",
            "name",
            "channel",
            "is_active",
            "concurrency_policy",
            "history_window",
            "token_budget_per_conversation",
            "on_budget_exhausted",
            "budget_exhausted_message",
            "handoff_enabled",
        ]


class ChatInboundSerializer(serializers.Serializer):
    external_id = serializers.CharField(max_length=255)
    content = serializers.CharField()


class ChatOperatorMessageSerializer(serializers.Serializer):
    content = serializers.CharField()


class ChatConversationSerializer(serializers.ModelSerializer):
    binding_name = serializers.CharField(source="binding.name", read_only=True)
    graph = serializers.IntegerField(source="binding.graph_id", read_only=True)
    channel = serializers.CharField(source="binding.channel", read_only=True)
    assigned_operator_name = serializers.SerializerMethodField()
    active_session_status = serializers.CharField(
        source="active_session.status", read_only=True, default=None
    )
    tokens_used = serializers.SerializerMethodField()
    token_budget = serializers.IntegerField(
        source="binding.token_budget_per_conversation", read_only=True
    )
    last_message_preview = serializers.SerializerMethodField()

    class Meta:
        model = ChatConversation
        fields = [
            "id",
            "binding",
            "binding_name",
            "graph",
            "channel",
            "external_id",
            "mode",
            "assigned_operator",
            "assigned_operator_name",
            "active_session",
            "active_session_status",
            "tokens_used",
            "token_budget",
            "handoff_reason",
            "last_message_at",
            "last_message_preview",
        ]
        read_only_fields = fields

    def get_assigned_operator_name(self, conversation: ChatConversation) -> str | None:
        return _user_name(conversation.assigned_operator)

    def get_tokens_used(self, conversation: ChatConversation) -> int:
        return conversation_tokens_used(conversation)

    def get_last_message_preview(self, conversation: ChatConversation) -> str | None:
        # Annotated by ChatConversationViewSet.get_queryset.
        content = getattr(conversation, "last_message_content", None)
        return content[:_PREVIEW_LENGTH] if content is not None else None


class ChatMessageSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = ["id", "role", "content", "session", "interrupted", "author_name", "created_at"]
        read_only_fields = fields

    def get_author_name(self, message: ChatMessage) -> str | None:
        return _user_name(message.author)
