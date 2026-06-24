from __future__ import annotations

"""
Views for the Flow Assistant feature.

Non-streaming endpoints: DRF APIView.
Streaming endpoint: SSEMixin (Django View) with ticket auth.
"""

from asgiref.sync import async_to_sync, sync_to_async
from django.db.models import Count
from django.utils import timezone
from rest_framework import status
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from utils.logger import logger

from tables.models.flow_assistant_models import FlowAssistantConversation
from tables.serializers.flow_assistant_serializers import (
    AuditConversationSerializer,
    FlowAssistantConversationSerializer,
    FlowAssistantSerializer,
    SendMessageSerializer,
    SessionSummarySerializer,
    StartConversationSerializer,
)
from tables.services.flow_assistant import (
    FlowAssistantService,
    LLMConfigInvalidError,
    LLMConfigMissingError,
    build_node_index,
)
from tables.services.flow_assistant.helpers import request_cancel
from tables.services.flow_assistant.stream_serializer import serialize_stream_event
from tables.services.rbac.organization_resolution import resolve_organization_user
from tables.services.rbac.permissions import IsSuperadmin
from tables.services.rbac.sse_ticket_service import SseTicketService
from tables.utils.mixins import SSEMixin


def _get_graph_or_404(graph_id: int):
    """Return the Graph or raise 404-style exception."""
    from django.http import Http404
    from tables.models.graph_models import Graph

    try:
        return Graph.objects.get(pk=graph_id)
    except Graph.DoesNotExist:
        raise Http404(f"Graph {graph_id} not found.")


def _get_conversation_or_404(
    graph_id: int,
    conversation_id: int,
    organization_user=None,
):
    """Return FlowAssistantConversation, raising 404 / 403 as appropriate.

    When organization_user is supplied the conversation must belong to that
    membership and must not be soft-deleted.
    """
    from django.http import Http404
    from rest_framework.exceptions import PermissionDenied

    try:
        conv = FlowAssistantConversation.objects.select_related(
            "flow_assistant__graph",
            "flow_assistant__llm_config__model__llm_provider",
        ).prefetch_related("message_rows").get(
            pk=conversation_id,
            flow_assistant__graph_id=graph_id,
        )
    except FlowAssistantConversation.DoesNotExist:
        raise Http404(f"Conversation {conversation_id} not found.")

    if organization_user is not None:
        if conv.organization_user_id != organization_user.pk:
            raise PermissionDenied(
                "You do not have permission to access this conversation."
            )
        if conv.deleted_at is not None:
            raise Http404(f"Conversation {conversation_id} not found.")

    return conv


# ── Config endpoints ──────────────────────────────────────────────────────────


class FlowAssistantConfigView(APIView):
    """
    GET   /api/flow-assistants/<graph_id>/   — fetch config + system prompt preview
    PATCH /api/flow-assistants/<graph_id>/   — update llm_config
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, graph_id: int):
        _get_graph_or_404(graph_id)
        service = FlowAssistantService()
        assistant = service.get_or_create(graph_id)

        serializer = FlowAssistantSerializer(assistant)
        return Response(serializer.data)

    def patch(self, request, graph_id: int):
        _get_graph_or_404(graph_id)
        service = FlowAssistantService()
        assistant = service.get_or_create(graph_id)

        serializer = FlowAssistantSerializer(assistant, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


# ── Conversation list / start endpoint ────────────────────────────────────────


class FlowAssistantConversationsView(APIView):
    """
    GET  /api/flow-assistants/<graph_id>/conversations/ — list user's sessions
    POST /api/flow-assistants/<graph_id>/conversations/ — start a new conversation
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, graph_id: int):
        _get_graph_or_404(graph_id)
        organization_user = resolve_organization_user(request)

        queryset = (
            FlowAssistantConversation.objects.filter(
                flow_assistant__graph_id=graph_id,
                organization_user=organization_user,
                deleted_at__isnull=True,
            )
            .annotate(message_count=Count("message_rows"))
            .order_by("-last_message_at")
        )

        paginator = LimitOffsetPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = SessionSummarySerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request, graph_id: int):
        _get_graph_or_404(graph_id)
        organization_user = resolve_organization_user(request)
        StartConversationSerializer(data=request.data).is_valid(raise_exception=True)

        service = FlowAssistantService()
        assistant = service.get_or_create(graph_id)
        conversation = service.start_conversation(assistant, organization_user)
        return Response(
            {"conversation_id": conversation.pk},
            status=status.HTTP_201_CREATED,
        )


# ── Single conversation endpoint ──────────────────────────────────────────────


class FlowAssistantConversationView(APIView):
    """
    GET    /api/flow-assistants/<graph_id>/conversations/<conversation_id>/
    DELETE /api/flow-assistants/<graph_id>/conversations/<conversation_id>/
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, graph_id: int, conversation_id: int):
        _get_graph_or_404(graph_id)
        organization_user = resolve_organization_user(request)
        conversation = _get_conversation_or_404(
            graph_id, conversation_id, organization_user
        )
        serializer = FlowAssistantConversationSerializer(conversation)
        return Response(serializer.data)

    def delete(self, request, graph_id: int, conversation_id: int):
        _get_graph_or_404(graph_id)
        organization_user = resolve_organization_user(request)
        conversation = _get_conversation_or_404(
            graph_id, conversation_id, organization_user
        )
        conversation.deleted_at = timezone.now()
        conversation.save(update_fields=["deleted_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Send message endpoint ─────────────────────────────────────────────────────


class FlowAssistantSendMessageView(APIView):
    """POST /api/flow-assistants/<graph_id>/conversations/<conversation_id>/messages/"""

    permission_classes = [IsAuthenticated]

    def post(self, request, graph_id: int, conversation_id: int):
        _get_graph_or_404(graph_id)
        organization_user = resolve_organization_user(request)
        conversation = _get_conversation_or_404(
            graph_id, conversation_id, organization_user
        )

        serializer = SendMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = serializer.validated_data["message"]

        service = FlowAssistantService()
        service.append_user_message(conversation, message)
        service.apply_title_if_missing(conversation, message)

        ticket, _ttl = SseTicketService().issue(request.user)
        stream_url = request.build_absolute_uri(
            f"/api/flow-assistants/{graph_id}/conversations/{conversation_id}/stream/"
            f"?ticket={ticket}"
        )
        return Response({"stream_url": stream_url}, status=status.HTTP_200_OK)


# ── SSE streaming endpoint ────────────────────────────────────────────────────


class FlowAssistantStreamView(SSEMixin):
    """
    GET /api/flow-assistants/<graph_id>/conversations/<conversation_id>/stream/?ticket=...

    Streams LLM events for the last user message in the conversation.
    Authentication is via a one-shot SSE ticket (consumed on first use).
    """

    async def get_initial_data(self):
        # No initial data — the stream starts with the LLM reply
        return
        yield  # make this an async generator

    async def get_live_updates(self, pubsub):
        """
        Iterates FlowAssistantService.stream_reply and yields SSE events.
        The pubsub parameter is ignored (we use an in-process async iterator).
        """
        graph_id = self.kwargs["graph_id"]
        conversation_id = self.kwargs["conversation_id"]
        user = self.user  # set by SSEMixin.get() after ticket validation

        # Load conversation — scope check uses organization_user
        try:
            conversation = await sync_to_async(
                lambda: FlowAssistantConversation.objects.select_related(
                    "flow_assistant__graph",
                    "flow_assistant__llm_config__model__llm_provider",
                    "organization_user__user",
                ).get(
                    pk=conversation_id,
                    flow_assistant__graph_id=graph_id,
                )
            )()
        except FlowAssistantConversation.DoesNotExist:
            yield {
                "event": "error",
                "data": {"type": "error", "detail": "Conversation not found."},
            }
            return

        # The conversation must belong to the ticket-holder user.
        # We compare by user_id (not org membership pk) since the ticket is
        # issued per-user and the SSE flow is stateless w.r.t. org context.
        if conversation.organization_user.user_id != user.pk:
            yield {"event": "error", "data": {"type": "error", "detail": "Forbidden."}}
            return

        if conversation.deleted_at is not None:
            yield {
                "event": "error",
                "data": {"type": "error", "detail": "Conversation not found."},
            }
            return

        # Find the last user message to use as the prompt for this turn.
        last_user_row = await sync_to_async(
            lambda: conversation.message_rows.filter(role="user")
            .order_by("-message_index")
            .first()
        )()
        last_user_message = last_user_row.content if last_user_row else ""

        if not last_user_message:
            yield {
                "event": "error",
                "data": {"type": "error", "detail": "No pending user message found."},
            }
            return

        # Build node index once for enriching tool_call SSE events.
        node_index = await sync_to_async(build_node_index)(graph_id)

        service = FlowAssistantService()

        try:
            async for event in service.stream_reply(conversation, last_user_message):
                result = await serialize_stream_event(
                    event, graph_id=graph_id, node_index=node_index
                )
                if result is None:
                    logger.warning(
                        "FlowAssistant stream: unknown event type {!r}, skipping",
                        getattr(event, "type", None),
                    )
                    continue
                sse_event, terminate = result
                yield sse_event
                if terminate:
                    return

        except LLMConfigMissingError as exc:
            logger.warning(
                "FlowAssistant stream error (LLMConfigMissingError): {}", exc
            )
            yield {
                "event": "error",
                "data": {
                    "type": "error",
                    "detail": str(exc),
                },
            }
        except LLMConfigInvalidError as exc:
            logger.warning(
                "FlowAssistant stream error (LLMConfigInvalidError): {}", exc
            )
            yield {
                "event": "error",
                "data": {"type": "error", "detail": str(exc)},
            }
        except Exception as exc:
            logger.exception("Unexpected error in FlowAssistantStreamView: {}", exc)
            yield {
                "event": "error",
                "data": {"type": "error", "detail": "Unexpected error."},
            }


# ── Audit endpoint ────────────────────────────────────────────────────────────


class FlowAssistantAuditView(APIView):
    """
    GET /api/flow-assistants/audit/conversations/

    Superadmin-only paginated audit log of all conversations.

    Query params (all optional):
      organization_id       int   — filter by org
      organization_user_id  int   — filter by OrganizationUser pk
      from                  str   — ISO 8601 lower bound on started_at
      to                    str   — ISO 8601 upper bound on started_at
      include_deleted       bool  — include soft-deleted rows (default false)
    """

    permission_classes = [IsAuthenticated, IsSuperadmin]
    pagination_class = LimitOffsetPagination

    def get(self, request):
        from django.utils.dateparse import parse_datetime

        queryset = (
            FlowAssistantConversation.objects.select_related(
                "organization_user__user",
                "organization_user__org",
                "flow_assistant",
            )
            .annotate(message_count=Count("message_rows"))
            .order_by("-last_message_at")
        )

        org_id = request.query_params.get("organization_id")
        if org_id is not None:
            try:
                queryset = queryset.filter(organization_user__org_id=int(org_id))
            except ValueError:
                pass

        org_user_id = request.query_params.get("organization_user_id")
        if org_user_id is not None:
            try:
                queryset = queryset.filter(organization_user_id=int(org_user_id))
            except ValueError:
                pass

        from_param = request.query_params.get("from")
        if from_param:
            parsed = parse_datetime(from_param)
            if parsed:
                queryset = queryset.filter(started_at__gte=parsed)

        to_param = request.query_params.get("to")
        if to_param:
            parsed = parse_datetime(to_param)
            if parsed:
                queryset = queryset.filter(started_at__lte=parsed)

        include_deleted = request.query_params.get("include_deleted", "false").lower()
        if include_deleted not in ("true", "1", "yes"):
            queryset = queryset.filter(deleted_at__isnull=True)

        paginator = LimitOffsetPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = AuditConversationSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


# ── Cancel endpoint ───────────────────────────────────────────────────────────


class FlowAssistantCancelView(APIView):
    """
    POST /api/flow-assistants/<graph_id>/conversations/<conversation_id>/cancel/

    Sets a short-lived Redis flag that causes the in-progress stream_reply
    generator to interrupt at its next cancel checkpoint, persist any partial
    assistant content, and return a done event with interrupted=True.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, graph_id: int, conversation_id: int):
        organization_user = resolve_organization_user(request)
        conv = FlowAssistantConversation.objects.filter(
            pk=conversation_id,
            organization_user=organization_user,
            flow_assistant__graph_id=graph_id,
            deleted_at__isnull=True,
        ).first()
        if conv is None:
            return Response({"detail": "Conversation not found."}, status=404)
        async_to_sync(request_cancel)(conv.id)
        return Response({"cancelled": True}, status=status.HTTP_202_ACCEPTED)
