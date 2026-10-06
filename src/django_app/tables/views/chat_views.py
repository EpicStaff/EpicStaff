from django.db.models import Case, F, IntegerField, OuterRef, Prefetch, Subquery, Value, When
from django_filters import rest_framework as filters
from rbac.access.action_map import DEFAULT_ACTION_MAP
from rbac.access.gates import HasOrgPermission
from rbac.models.enums import Permission, ResourceType
from rbac.scoping.mixins import OrgScopedChildViewSetMixin, OrgScopedViewSetMixin
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from tables.models import ChatBinding, ChatConversation, ChatMessage, Session
from tables.serializers.chat_serializers import (
    ChatBindingSerializer,
    ChatConversationSerializer,
    ChatInboundSerializer,
    ChatMessageSerializer,
    ChatOperatorMessageSerializer,
)
from tables.services.chat.conversation_service import ConversationService

# Chat reuses the FLOWS resource type. Sending a message runs the flow, which needs READ
# on FLOWS (same as /run-session/); changing who handles a conversation is an UPDATE.
_CHAT_ACTION_MAP = {
    **DEFAULT_ACTION_MAP,
    "inbound": Permission.READ,
    "messages": Permission.READ,
    "claim": Permission.UPDATE,
    "release": Permission.UPDATE,
    "close": Permission.UPDATE,
    "operator_message": Permission.UPDATE,
}


class ChatBindingViewSet(OrgScopedViewSetMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    rbac_action_map = _CHAT_ACTION_MAP
    queryset = ChatBinding.objects.select_related("graph").order_by("name")
    serializer_class = ChatBindingSerializer
    # PROTO: unpaginated; the real version pages like the other list endpoints.
    pagination_class = None

    @action(detail=True, methods=["post"], url_path="inbound")
    def inbound(self, request, pk=None):
        """Accept an end-user message for this binding (widget / "simulate end user")."""
        binding = self.get_object()
        serializer = ChatInboundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = ConversationService().submit_user_message(
            binding,
            external_id=serializer.validated_data["external_id"],
            content=serializer.validated_data["content"],
        )
        return Response(
            {
                "conversation_id": result.conversation.pk,
                "message_id": result.message.pk,
                "action": result.action,
            }
        )


class ChatConversationFilter(filters.FilterSet):
    # A plain number, not a ModelChoiceFilter: that one validates the id against every
    # org's bindings and would answer 400 vs 200 depending on whether it exists elsewhere.
    binding = filters.NumberFilter(field_name="binding_id")
    mode = filters.ChoiceFilter(choices=ChatConversation.Mode.choices)

    class Meta:
        model = ChatConversation
        fields = ["binding", "mode"]


class ChatConversationViewSet(OrgScopedChildViewSetMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    rbac_action_map = _CHAT_ACTION_MAP
    org_filter_path = "binding__org_id"
    serializer_class = ChatConversationSerializer
    filterset_class = ChatConversationFilter
    # PROTO: unpaginated; the real version pages like the other list endpoints.
    pagination_class = None
    queryset = (
        ChatConversation.objects.select_related("binding", "assigned_operator", "active_session")
        .prefetch_related(Prefetch("sessions", queryset=Session.objects.only("id", "token_usage")))
        .annotate(
            last_message_content=Subquery(
                ChatMessage.objects.filter(conversation=OuterRef("pk"))
                .order_by("-id")
                .values("content")[:1]
            ),
            awaiting_human_first=Case(
                When(mode=ChatConversation.Mode.AWAITING_HUMAN, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            ),
        )
        .order_by("awaiting_human_first", F("last_message_at").desc(nulls_last=True), "-id")
    )

    @action(detail=True, methods=["get"], url_path="messages")
    def messages(self, request, pk=None):
        conversation = self.get_object()
        # PROTO: the whole thread every poll; the real version pages / streams.
        messages = conversation.messages.select_related("author").order_by("id")
        return Response(ChatMessageSerializer(messages, many=True).data)

    @action(detail=True, methods=["post"], url_path="claim")
    def claim(self, request, pk=None):
        conversation = ConversationService().claim(self.get_object(), operator=request.user)
        return self._conversation_response(conversation)

    @action(detail=True, methods=["post"], url_path="release")
    def release(self, request, pk=None):
        conversation = ConversationService().release(self.get_object())
        return self._conversation_response(conversation)

    @action(detail=True, methods=["post"], url_path="close")
    def close(self, request, pk=None):
        conversation = ConversationService().close(self.get_object())
        return self._conversation_response(conversation)

    @action(detail=True, methods=["post"], url_path="operator-message")
    def operator_message(self, request, pk=None):
        conversation = self.get_object()
        serializer = ChatOperatorMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = ConversationService().send_operator_message(
            conversation, operator=request.user, content=serializer.validated_data["content"]
        )
        return Response(ChatMessageSerializer(message).data, status=status.HTTP_201_CREATED)

    def _conversation_response(self, conversation: ChatConversation) -> Response:
        # Re-read through the scoped queryset for the annotations the serializer needs.
        conversation = self.get_queryset().get(pk=conversation.pk)
        return Response(self.get_serializer(conversation).data)
