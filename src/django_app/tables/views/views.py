import json
from datetime import datetime, timezone
from collections import defaultdict
import uuid
import base64
from tables.services.rbac.authentication import IsAuthenticatedOrApiKey
from tables.services.webhook_trigger_service import WebhookTriggerService
from tables.models.graph_models import TelegramTriggerNode
from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.serializers.model_serializers import TelegramTriggerNodeDataFieldsSerializer

from tables.services.webhook_trigger_service import WebhookTriggerService
from tables.models.graph_models import (
    TelegramTriggerNode,
    PythonNode,
    GraphSessionMessage,
)
from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.utils.telegram_fields import load_telegram_trigger_fields
from tables.models import Agent
from tables.services.realtime_service import RealtimeService
from agents.models import AgentDefinition
from tables.swagger_schemas.python_node_test_mode_schema import (
    LAST_TEST_INPUT_SWAGGER as _LAST_TEST_INPUT_SWAGGER,
)
from utils.logger import logger

from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
)
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.conf import settings


from rest_framework.mixins import RetrieveModelMixin, UpdateModelMixin, ListModelMixin
from rest_framework.viewsets import GenericViewSet

from rest_framework.decorators import api_view, action
from rest_framework.views import APIView
from rest_framework import viewsets, mixins
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework import filters

from tables.services.session_manager_service import SessionManagerService
from tables.services.converter_service import ConverterService
from tables.services.redis_service import RedisService
from tables.services.run_python_code_service import RunPythonCodeService
from tables.services.quickstart_service import QuickstartService
from tables.services.knowledge_services.indexing_service import IndexingService
from tables.services.trigger_spec import TriggerSpec

from django_filters.rest_framework import DjangoFilterBackend

from tables.models import (
    Session,
    # DocumentMetadata,
    Graph,
    PythonCode,
    SessionWarningMessage,
    SessionStorageFile,
)
from tables.serializers.model_serializers import (
    SessionSerializer,
    SessionLightSerializer,
    TelegramTriggerNodeDataFieldsSerializer,
)
from tables.serializers.storage_serializers import SessionOutputFileSerializer
from tables.serializers.serializers import (
    AnswerToLLMSerializer,
    BulkExportSerializer,
    InitRealtimeSerializer,
    NotifyEmailSerializer,
    ProcessRagIndexingSerializer,
    RunSessionSerializer,
    RegisterTelegramTriggerSerializer,
    RunPythonCodeSerializer,
    SessionExportAllSerializer,
)
from tables.services.notification_email_sender import NotificationEmailSender
from tables.throttles import NotifyEmailThrottle

from tables.serializers.quickstart_serializers import (
    QuickstartSerializer,
    QuickstartConfigSerializer,
    QuickstartStatusSerializer,
)
from tables.serializers.default_config_serializers import DefaultModelsSerializer
from tables.filters import SessionFilter  # CollectionFilter,
from tables.services.import_export_service import ViewSetImportExportService
from tables.import_export.enums import EntityType
from rest_framework.permissions import IsAuthenticated
from tables.views.mixins import (
    OrgScopedChildViewSetMixin,
    OrgScopedServiceViewSetMixin,
)
from tables.models.knowledge_models import NaiveRag, GraphRag
from tables.models.rbac_models import ApiKey
from tables.services.rbac.permissions import (
    HasOrgPermission,
    IsSuperadmin,
    IsSuperadminOrReadOnly,
)
from tables.services.rbac.permission_action_map import DEFAULT_ACTION_MAP
from tables.services.rbac.session_access import assert_session_org_access
from tables.services.rbac.permission_assert import assert_org_permission
from tables.services.rbac.org_context_service import OrgContextService
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.import_export.export_format_strategies import (
    JsonExportFormatStrategy,
    CsvExportFormatStrategy,
)
from tables.import_export.export_tabular_projections.session import (
    SessionTabularProjection,
)

from tables.swagger_schemas.default_config_schemas import (
    QUICKSTART_GET,
    QUICKSTART_POST,
    QUICKSTART_APPLY_POST,
)
from tables.swagger_schemas.knowledge_schemas.naive_rag_schemas import (
    PROCESS_RAG_INDEXING_POST,
)
from tables.swagger_schemas.realtime_schemas import INIT_REALTIME_POST
from tables.swagger_schemas.sessions_schema import (
    ANSWER_TO_LLM,
    GET_UPDATES_GET,
    RUN_SESSION_POST,
    SESSION_BULK_DELETE_POST,
    SESSION_DESTROY_DELETE,
    SESSION_LIST_GET,
    SESSION_OUTPUT_FILES_GET,
    SESSION_RETRIEVE_GET,
    SESSION_STATUSES_GET,
    SESSION_WARNINGS_GET,
    STOP_SESSION_POST,
)
from tables.swagger_schemas.telegram_schemas import (
    TELEGRAM_TRIGGER_AVAILABLE_FIELDS_GET,
    REGISTER_TELEGRAM_TRIGGER_POST,
)
from tables.swagger_schemas.webhook_schemas import REGISTER_WEBHOOKS_POST
from tables.swagger_schemas.python_code_schemas import RUN_PYTHON_CODE_POST
from .default_config import *


MAX_TOTAL_FILE_SIZE = 15 * 1024 * 1024  # 15MB

redis_service = RedisService()
# TODO: fix. Do we need init converter_service here? Instance is not used.
converter_service = ConverterService()
session_manager_service = SessionManagerService()
run_python_code_service = RunPythonCodeService()
realtime_service = RealtimeService()
quickstart_service = QuickstartService()
notification_email_sender = NotificationEmailSender()


@extend_schema_view(
    retrieve=extend_schema(**SESSION_RETRIEVE_GET),
    destroy=extend_schema(**SESSION_DESTROY_DELETE),
)
class SessionViewSet(
    OrgScopedChildViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    API endpoints for managing session objects.

    Supports listing, retrieving, deleting sessions,
    bulk deletion, and reporting aggregated status counts.

    Sessions are executions of a flow, so they are scoped as children of the
    graph (FLOWS): view/status -> READ, export -> EXPORT, delete -> DELETE.
    """

    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    rbac_action_map = {
        **DEFAULT_ACTION_MAP,
        "export": Permission.EXPORT,
        "bulk_export": Permission.EXPORT,
        "export_all": Permission.EXPORT,
        "statuses": Permission.READ,
        "bulk_delete": Permission.DELETE,
        "get_session_warnings": Permission.READ,
        "output_files": Permission.READ,
    }
    org_filter_path = "graph__org_id"
    serializer_class = SessionSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.import_export_service = ViewSetImportExportService(
            entity_type=EntityType.SESSION,
            export_prefix="session",
            filename_attr="id",
            format_strategies={
                "json": JsonExportFormatStrategy(),
                "csv": CsvExportFormatStrategy(SessionTabularProjection()),
            },
        )

    filterset_class = SessionFilter
    ordering_fields = [
        "created_at",
        "finished_at",
        "status",
        "status_updated_at",
        "id",
    ]  # allowed fields
    ordering = ["-created_at", "id"]  # default ordering

    @extend_schema(**SESSION_LIST_GET)
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_serializer_class(self):
        detailed = self.request.query_params.get("detailed", "true").lower()
        if detailed == "false":
            return SessionLightSerializer
        return SessionSerializer

    def get_queryset(self):
        qs = Session.objects.select_related("graph", "trigger").filter(
            graph__org_id=self.get_active_org_id()
        )
        detailed = self.request.query_params.get("detailed", "true").lower()

        if detailed == "false":
            qs = qs.annotate(
                has_output_files=Exists(
                    SessionStorageFile.objects.filter(session_id=OuterRef("pk"))
                )
            )

        return qs

    _FORMAT_QUERY_PARAM = OpenApiParameter(
        name="export_format",
        location=OpenApiParameter.QUERY,
        description="Export format: 'json' (default) returns a structured JSON file; 'csv' returns a flat CSV of session messages.",
        required=False,
        type=str,
        enum=["json", "csv"],
        default="json",
    )

    @extend_schema(
        description="Export a single session's messages as a downloadable file. "
        "Includes messages from all nested sub-sessions.",
        parameters=[_FORMAT_QUERY_PARAM],
        responses={
            200: OpenApiResponse(
                description="File download (application/json or text/csv)."
            ),
        },
    )
    @action(detail=True, methods=["get"])
    def export(self, request, pk: int):
        fmt = request.query_params.get("export_format", "json")
        return self.import_export_service.export_entity(self.get_object(), fmt=fmt)

    @extend_schema(
        description="Export messages from multiple sessions as a single downloadable file. "
        "Includes messages from all nested sub-sessions for each requested session.",
        request=BulkExportSerializer,
        parameters=[_FORMAT_QUERY_PARAM],
        responses={
            200: OpenApiResponse(
                description="File download (application/json or text/csv)."
            ),
            400: OpenApiResponse(
                description="Invalid request body or one or more session IDs do not exist."
            ),
        },
    )
    @action(detail=False, methods=["post"], url_path="bulk-export")
    def bulk_export(self, request):
        serializer = BulkExportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entity_ids = serializer.validated_data["ids"]

        existing_ids = Session.objects.filter(
            id__in=entity_ids, graph__org_id=self.get_active_org_id()
        ).values_list("id", flat=True)
        if len(existing_ids) != len(entity_ids):
            return Response(
                {"message": "Some entity IDs do not exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        fmt = request.query_params.get("export_format", "json")
        return self.import_export_service.bulk_export(entity_ids, fmt=fmt)

    @extend_schema(
        description="Export messages from top-level sessions matching the given filters as a single downloadable file. "
        "Includes messages from all nested sub-sessions.",
        request=SessionExportAllSerializer,
        parameters=[_FORMAT_QUERY_PARAM],
        responses={
            200: OpenApiResponse(
                description="File download (application/json or text/csv)."
            ),
            400: OpenApiResponse(description="Invalid request body."),
            404: OpenApiResponse(description="No sessions match the given filters."),
        },
    )
    @action(detail=False, methods=["post"], url_path="export_all")
    def export_all(self, request):
        serializer = SessionExportAllSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        active_org_id = self.get_active_org_id()
        if (
            "graph_id" in data
            and not Graph.objects.filter(
                id=data["graph_id"], org_id=active_org_id
            ).exists()
        ):
            raise NotFound(f"Graph {data['graph_id']} not found")

        qs = Session.objects.filter(parent_session_id=None, graph__org_id=active_org_id)

        if "graph_id" in data:
            qs = qs.filter(graph_id=data["graph_id"])
        if "graph_name" in data:
            qs = qs.filter(graph__name__iexact=data["graph_name"])
        if "status" in data:
            qs = qs.filter(status__in=data["status"])
        if "created_at_after" in data:
            qs = qs.filter(created_at__gte=data["created_at_after"])
        if "created_at_before" in data:
            qs = qs.filter(created_at__lte=data["created_at_before"])
        if "finished_at_after" in data:
            qs = qs.filter(finished_at__gte=data["finished_at_after"])
        if "finished_at_before" in data:
            qs = qs.filter(finished_at__lte=data["finished_at_before"])

        node_name = data.get("node_name")
        if node_name:
            qs = qs.filter(graphsessionmessage__name=node_name).distinct()

        if data.get("is_error_cause"):
            error_messages = GraphSessionMessage.objects.filter(
                session=OuterRef("pk"), message_data__message_type="error"
            )
            if node_name:
                error_messages = error_messages.filter(name=node_name)
            qs = qs.filter(Exists(error_messages)).distinct()

        session_ids = list(qs.values_list("id", flat=True))

        if not session_ids:
            return Response(
                {"message": "No sessions match the given filters"},
                status=status.HTTP_404_NOT_FOUND,
            )

        fmt = request.query_params.get("export_format", "json")
        return self.import_export_service.bulk_export(session_ids, fmt=fmt)

    @extend_schema(**SESSION_STATUSES_GET)
    @action(detail=False, methods=["GET"])
    def statuses(self, request):
        queryset = self.get_queryset()

        # Apply filters
        for backend in list(self.filter_backends):
            queryset = backend().filter_queryset(request, queryset, self)

        queryset = queryset.values("graph_id", "status").annotate(count=Count("status"))
        data = defaultdict(lambda: defaultdict(int))
        for row in queryset:
            data[row["graph_id"]][row["status"]] = row["count"]

        return Response(data)

    @extend_schema(**SESSION_BULK_DELETE_POST)
    @action(detail=False, methods=["post"], url_path="bulk_delete")
    def bulk_delete(self, request):
        ids = request.data.get("ids", [])
        if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
            return Response(
                {"detail": "ids must be a list of integers."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            session_list = Session.objects.filter(
                id__in=ids, graph__org_id=self.get_active_org_id()
            )
            deleted_count = session_list.count()
            for session in session_list:
                session.delete()

        return Response(
            {"deleted": deleted_count, "ids": ids}, status=status.HTTP_200_OK
        )

    @extend_schema(**SESSION_WARNINGS_GET)
    @action(detail=True, methods=["get"], url_path="warnings")
    def get_session_warnings(self, request, pk=None):
        session = self.get_object()

        warning = (
            SessionWarningMessage.objects.filter(session=session)
            .values("messages")
            .first()
        )

        return Response(warning, status=status.HTTP_200_OK)

    @extend_schema(**SESSION_OUTPUT_FILES_GET)
    @action(detail=True, methods=["get"], url_path="output-files")
    def output_files(self, request, pk=None):
        session = self.get_object()
        qs = (
            SessionStorageFile.objects.filter(session=session)
            .select_related("storage_file")
            .order_by("added_at")
        )
        return Response(SessionOutputFileSerializer(qs, many=True).data)


class RunSession(APIView):
    @extend_schema(**RUN_SESSION_POST)
    def post(self, request):
        logger.info("Received POST request to start a new session.")

        total_size = sum(f.size for f in request.FILES.values())
        max_mb = round(settings.MAX_TOTAL_FILE_SIZE / 1024 / 1024, 2)
        got_mb = round(total_size / 1024 / 1024, 2)

        if got_mb > max_mb:
            return Response(
                {
                    "files": [
                        f"Total files size exceeds {max_mb:.2f} MB (got {got_mb:.2f} MB)"
                    ]
                },
                status=400,
            )

        serializer = RunSessionSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"Invalid data received in request: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        files_dict = {}
        graph_id = serializer.validated_data.get("graph_id")
        graph_uuid = serializer.validated_data.get("graph_uuid")

        if graph_id:
            graph = Graph.objects.filter(id=graph_id).first()
        else:
            graph = Graph.objects.filter(uuid=graph_uuid).first()

        if not graph:
            return Response(
                {"message": "Provided graph does not exist"},
                status=status.HTTP_404_NOT_FOUND,
            )

        graph_id = graph.id

        # Running the flow requires READ on flows within its org (superadmin bypasses).
        assert_org_permission(
            user=request.user,
            org_id=graph.org_id,
            resource_type=ResourceType.FLOWS,
            action=Permission.READ,
        )

        variables = serializer.validated_data.get("variables", {})
        for key, file in request.FILES.items():
            files_dict[key] = self._get_file_data(file, file.content_type)

        if files_dict:
            variables["files"] = files_dict
            logger.info(f"Added {len(files_dict)} files to variables.")

        parent_session_id = serializer.validated_data.get("parent_session_id")
        # A sub-flow launched by the subflow_tool is triggered by its parent
        # session, not by a human hitting this endpoint.
        trigger = (
            TriggerSpec.parent_flow(parent_session_id)
            if parent_session_id is not None
            else TriggerSpec.manual()
        )

        try:
            # Publish session to: crew, maanger
            session_id = session_manager_service.run_session(
                graph_id=graph_id,
                variables=variables,
                user=request.user,
                trigger=trigger,
                parent_session_id=parent_session_id,
                token_budget=serializer.validated_data.get("token_budget"),
            )
            logger.info(f"Session {session_id} successfully started.")
        except Exception as e:
            logger.exception(
                f"Error occurred while starting session for graph_id {graph_id}"
            )
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"error": str(e)})

        return Response(
            data={"session_id": session_id},
            status=status.HTTP_201_CREATED,
        )

    def _get_file_data(self, file, content_type):
        file_bytes = file.read()

        return {
            "name": file.name,
            "base64_data": base64.b64encode(file_bytes).decode("utf-8"),
            "content_type": content_type,
        }


class GetUpdates(APIView):
    @extend_schema(**GET_UPDATES_GET)
    def get(self, request, *args, **kwargs):
        session_id = kwargs.get("session_id", None)
        if session_id is None:
            return Response("Session id not found", status=status.HTTP_404_NOT_FOUND)

        session = Session.objects.select_related("graph").filter(pk=session_id).first()
        if session is None:
            return Response("Session not found", status=status.HTTP_404_NOT_FOUND)
        assert_session_org_access(request.user, session)

        return Response(
            data={"status": session.status},
            status=status.HTTP_200_OK,
        )


class StopSession(APIView):
    @extend_schema(**STOP_SESSION_POST)
    def post(self, request, *args, **kwargs):
        session_id = kwargs.get("session_id", None)
        if session_id is None:
            return Response("Session id is missing", status=status.HTTP_404_NOT_FOUND)

        session = Session.objects.select_related("graph").filter(pk=session_id).first()
        if session is None:
            return Response("Session not found", status=status.HTTP_404_NOT_FOUND)
        assert_session_org_access(request.user, session)

        try:
            required_listeners = 2  # manager and crew
            received_n = session_manager_service.stop_session(session_id=session_id)
            if received_n < required_listeners:
                logger.error(f"Stop session ({session_id}) was sent but not received.")
                session = Session.objects.get(pk=session_id)
                session.status = Session.SessionStatus.ERROR
                session.status_data = {
                    "reason": f"Data was sent and received by ({received_n}) listeners, but ({required_listeners}) required."
                }
                session.save()

        except Session.DoesNotExist:
            return Response("Session not found", status=status.HTTP_404_NOT_FOUND)

        return Response(status=status.HTTP_204_NO_CONTENT)


class AnswerToLLM(APIView):
    @extend_schema(**ANSWER_TO_LLM)
    def post(self, request, *args, **kwargs):
        serializer = AnswerToLLMSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        session_id = serializer.validated_data["session_id"]
        name = serializer.validated_data["name"]
        crew_id = serializer.validated_data["crew_id"]
        execution_order = serializer.validated_data["execution_order"]
        answer = serializer.validated_data["answer"]
        try:
            session = Session.objects.get(id=session_id)
        except Session.DoesNotExist:
            return Response("Session not found", status=status.HTTP_404_NOT_FOUND)

        # Org isolation: only a member of the session's (graph) org may answer it
        # — same gate as stop/get-updates (FLOWS READ; superadmin bypass).
        assert_session_org_access(request.user, session, Permission.READ)

        logger.info(
            f"{session.status} == {Session.SessionStatus.WAIT_FOR_USER} : {session.status == Session.SessionStatus.WAIT_FOR_USER}"
        )

        if session.status != Session.SessionStatus.WAIT_FOR_USER:
            return Response(
                "Session status is not wait_for_user",
                status=status.HTTP_418_IM_A_TEAPOT,
            )

        created_at_dt = datetime.now(timezone.utc)
        created_at_iso = created_at_dt.isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        )

        session_manager_service.register_message(
            data={
                "session_id": session_id,
                "name": name,
                "execution_order": execution_order,
                "timestamp": created_at_iso,
                "message_data": {
                    "text": answer,
                    "crew_id": crew_id,
                    "message_type": "user",
                },
                "uuid": str(uuid.uuid4()),
            },
            created_at_dt=created_at_dt,
        )

        redis_service.send_user_input(
            session_id=session_id,
            node_name=name,
            crew_id=crew_id,
            execution_order=execution_order,
            message=answer,
        )

        return Response(status=status.HTTP_202_ACCEPTED)


class NotifyEmailView(APIView):
    """EST-3285 4.8: sends a notification email via notification_tool
    (channel='email'). Reuses NotificationEmailSender (Django's send_mail /
    EMAIL_BACKEND -- the same transport PasswordResetEmailSender uses), NOT a
    parallel SMTP client. Requires auth (same DEFAULT_PERMISSION_CLASSES /
    DEFAULT_AUTHENTICATION_CLASSES as every other endpoint), but auth alone
    does not prevent abuse: this is driven by notification_tool (LLM output),
    so a prompt-injected agent or a leaked API key could otherwise send
    unlimited mail to arbitrary external addresses from our domain.
    NotifyEmailThrottle caps that per authenticated user."""

    throttle_classes = [NotifyEmailThrottle]

    @extend_schema(
        summary="Send a notification email",
        request=NotifyEmailSerializer,
    )
    def post(self, request, *args, **kwargs):
        serializer = NotifyEmailSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        to_email = serializer.validated_data["to"]
        subject = serializer.validated_data["subject"]
        message = serializer.validated_data["message"]

        sent, error = notification_email_sender.send(
            to=to_email, subject=subject, message=message
        )
        if not sent:
            return Response(
                {"message": f"Failed to send notification email: {error}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"sent": True}, status=status.HTTP_200_OK)


class RunPythonCodeAPIView(APIView):
    _org_context = OrgContextService()

    @extend_schema(**RUN_PYTHON_CODE_POST)
    def post(self, request):
        serializer = RunPythonCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        python_code = serializer.validated_data["python_code"]
        variables = serializer.validated_data["variables"]

        # Executing arbitrary code is a contributor-level action, gated on
        # TOOLS.UPDATE. The code must also be visible to the active org, so a
        # caller cannot run another org's code by passing its id (rejected like
        # a non-existent pk — existence never leaks).
        org_id = self._org_context.resolve(
            request=request, view_kwargs=getattr(self, "kwargs", {})
        )
        assert_org_permission(
            user=request.user,
            org_id=org_id,
            resource_type=ResourceType.FLOWS,
            action=Permission.READ,
        )
        if not PythonCode.objects.filter(
            self._python_code_visible_q(org_id), pk=python_code.pk
        ).exists():
            raise ValidationError(
                {
                    "python_code_id": [
                        f'Invalid pk "{python_code.pk}" - object does not exist.'
                    ]
                }
            )

        execution_id = run_python_code_service.run_code(
            python_code_id=python_code.id,
            varaibles=variables,
            organization_id=org_id,
            user=request.user,
        )
        return Response({"execution_id": execution_id}, status=status.HTTP_200_OK)

    @staticmethod
    def _python_code_visible_q(org_id: int) -> Q:
        """A PythonCode is visible to an org if it is referenced by an org-owned
        tool (built-in tools are global) or by a node/edge in one of the org's
        graphs. Used to scope run-python-code so a caller cannot execute another
        org's stored code by id."""
        return (
            Q(pythoncodetool__built_in=True)
            | Q(pythoncodetool__org_id=org_id)
            | Q(pythonnode__graph__org_id=org_id)
            | Q(conditionaledge__graph__org_id=org_id)
            | Q(webhooktriggernode__graph__org_id=org_id)
            | Q(cdt_pre_nodes__graph__org_id=org_id)
            | Q(cdt_post_nodes__graph__org_id=org_id)
        )


class InitRealtimeAPIView(APIView):
    _org_context = OrgContextService()

    @extend_schema(**INIT_REALTIME_POST)
    def post(self, request):
        logger.info("Received POST request to start a new session.")

        serializer = InitRealtimeSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"Invalid data received in request: {serializer.errors}")
            return Response(
                data={"error": str(serializer.errors)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        agent_id = serializer.validated_data.get("agent_id")
        agent_definition_id = serializer.validated_data.get("agent_definition_id")
        config = serializer.validated_data.get("config", {})

        if (
            isinstance(request.auth, ApiKey)
            and request.auth.key_type == ApiKey.KeyType.SYSTEM
        ):
            # Trusted internal caller (realtime's Twilio MediaStream bridge, see
            # _voice_stream_handler) has no end-user session and therefore no
            # X-Organization-Id to send. It already resolved agent_id server-side
            # (via RealtimeChannelViewSet.lookup_by_token, itself scoped by the
            # channel's own org), so org is derived here from the agent's own
            # `org` FK instead of requiring a header — same approach as
            # lookup_by_token. This branch never runs for a JWT/user session:
            # request.auth is only an ApiKey instance for API-key-authenticated
            # requests (see IsApiKeyAuthenticated / ApiKeyAuthentication).
            #
            # Restricted to key_type=SYSTEM (same EST-3633 pattern as
            # RealtimeChannelViewSet.lookup_by_token / IsSystemApiKeyAuthenticated):
            # a self-issued key_type=USER ApiKey must NOT hit this bypass — it
            # would let any org member start a realtime session on ANY org's
            # agent (org is derived here from the agent's own row, with no
            # ownership/membership check). A USER-type key instead falls
            # through to the else branch below, which resolves org from
            # X-Organization-Id / the key owner's membership and enforces
            # AGENTS.READ normally — same as a JWT session.
            if agent_definition_id is not None:
                agent_definition = AgentDefinition.objects.filter(
                    pk=agent_definition_id
                ).first()
                if agent_definition is None:
                    raise ValidationError(
                        {
                            "agent_definition_id": f'Invalid pk "{agent_definition_id}" - object does not exist.'
                        }
                    )
                org_id = agent_definition.organization_id
            else:
                agent = Agent.objects.filter(id=agent_id).first()
                if agent is None:
                    raise ValidationError(
                        {
                            "agent_id": f'Invalid pk "{agent_id}" - object does not exist.'
                        }
                    )
                org_id = agent.org_id
            # Twilio's MediaStream bridge has no end-user session (see comment
            # above) — created_by/user_id stays None for these sessions.
            user_id = None
        else:
            # Org isolation: starting a realtime session is a read/use of an
            # agent, so require AGENTS.READ and reject an agent_id/agent_definition_id
            # outside the active org (rejected like a missing id — existence
            # never leaks).
            org_id = self._org_context.resolve(
                request=request, view_kwargs=getattr(self, "kwargs", {})
            )
            assert_org_permission(
                user=request.user,
                org_id=org_id,
                resource_type=ResourceType.AGENTS,
                action=Permission.READ,
            )
            # Browser /chats flow: a real authenticated user (JWT session or
            # USER-type ApiKey) is making this request — attribute the
            # resulting RealtimeSessionItem rows to them via created_by.
            user_id = (
                request.user.id
                if getattr(request.user, "is_authenticated", False)
                else None
            )

        if agent_id is not None:
            if not Agent.objects.filter(id=agent_id, org_id=org_id).exists():
                raise ValidationError(
                    {"agent_id": f'Invalid pk "{agent_id}" - object does not exist.'}
                )

        if agent_definition_id is not None:
            if not AgentDefinition.objects.filter(
                pk=agent_definition_id, organization_id=org_id
            ).exists():
                raise ValidationError(
                    {
                        "agent_definition_id": f'Invalid pk "{agent_definition_id}" - object does not exist.'
                    }
                )

        try:
            if agent_definition_id is not None:
                connection_key = realtime_service.init_realtime_agent_definition(
                    agent_definition_id=agent_definition_id,
                    config=config,
                    user_id=user_id,
                    org_id=org_id,
                )
            else:
                connection_key = realtime_service.init_realtime(
                    agent_id=agent_id,
                    config=config,
                    user_id=user_id,
                    org_id=org_id,
                )

        except Exception as e:
            logger.exception(
                f"Error occurred while creating realtime agent for agent_id {agent_id} "
                f"or agent_definition_id {agent_definition_id}"
            )
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"error": str(e)})
        else:
            return Response(
                data={"connection_key": connection_key}, status=status.HTTP_201_CREATED
            )


class QuickstartView(APIView):
    """
    API endpoint for managing quickstart configurations
    """

    permission_classes = [IsAuthenticated]
    rbac_resource_type = ResourceType.LLM_CONFIGS
    rbac_required_action = Permission.CREATE
    _org_context = OrgContextService()

    @extend_schema(**QUICKSTART_GET)
    def get(self, request):
        org_id = self._org_context.resolve(
            request=request, view_kwargs=getattr(self, "kwargs", {})
        )
        try:
            supported_providers = list(quickstart_service.get_supported_providers())
            last_config = quickstart_service.get_last_quickstart(org_id)
            is_synced = (
                quickstart_service.is_synced(last_config) if last_config else False
            )

            data = QuickstartStatusSerializer(
                {
                    "supported_providers": supported_providers,
                    "last_config": last_config,
                    "is_synced": is_synced,
                }
            ).data
            return Response(data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error getting quickstart status: {str(e)}")
            return Response(
                data={"detail": "Failed to retrieve quickstart status"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(**QUICKSTART_POST)
    def post(self, request):
        # The request must be in context: OrgScopedPrimaryKeyRelatedField reads the
        # active org from it and denies every pk without it (fail-safe).
        serializer = QuickstartSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        provider = serializer.validated_data["provider"]
        api_key = serializer.validated_data.get("api_key")
        secret = serializer.validated_data.get("api_key_secret_id")
        org_id = self._org_context.resolve(
            request=request, view_kwargs=getattr(self, "kwargs", {})
        )
        assert_org_permission(
            user=request.user,
            org_id=org_id,
            resource_type=self.rbac_resource_type,
            action=self.rbac_required_action,
        )

        result = quickstart_service.quickstart(
            provider=provider,
            api_key=api_key,
            secret=secret,
            org_id=org_id,
        )

        if not result.get("success", False):
            return Response(
                data={"detail": "Error quickstart", "error": result.get("error")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        config_name = result["config_name"]
        configs = QuickstartConfigSerializer(
            {
                "config_name": config_name,
                "llm_config": result["llm_config"],
                "embedding_config": result["embedding_config"],
            }
        ).data
        return Response(
            data={
                "detail": "Quickstart initiated successfully!",
                "config_name": config_name,
                "configs": configs,
            },
            status=status.HTTP_200_OK,
        )


class QuickstartApplyView(APIView):
    """
    Applies a quickstart config to DefaultModels.
    If config_name is omitted, the most recently created quickstart config is used.

    Writes the global DefaultModels singleton (install-wide defaults shared by
    every organization), so it is restricted to superadmins.
    """

    # TODO: refactor to set default models per org based on user permissions
    permission_classes = [IsAuthenticated, IsSuperadmin]
    _org_context = OrgContextService()

    @extend_schema(**QUICKSTART_APPLY_POST)
    def post(self, request):
        org_id = self._org_context.resolve(
            request=request, view_kwargs=getattr(self, "kwargs", {})
        )
        last = quickstart_service.get_last_quickstart(org_id)
        if not last:
            return Response(
                {"detail": "No quickstart config found. Run POST /quickstart/ first."},
                status=status.HTTP_404_NOT_FOUND,
            )

        dm = quickstart_service.apply_to_default_models(last["config_name"])
        return Response(DefaultModelsSerializer(dm).data, status=status.HTTP_200_OK)


class ProcessRagIndexingView(OrgScopedServiceViewSetMixin, APIView):
    """
    View for triggering RAG indexing (chunking + embedding).
    All business logic is handled by IndexingService.
    """

    _RAG_MODELS = {"naive": NaiveRag, "graph": GraphRag}
    _RAG_ORG_PATH = "base_rag_type__source_collection__org_id"

    @extend_schema(**PROCESS_RAG_INDEXING_POST)
    def post(self, request):
        serializer = ProcessRagIndexingSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        rag_id = serializer.validated_data["rag_id"]
        rag_type = serializer.validated_data["rag_type"]

        # The rag must live in the active org (404), and indexing mutates it.
        model = self._RAG_MODELS.get(rag_type)
        if model is None:
            return Response(
                {"error": f"Unknown rag_type '{rag_type}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        self.get_in_active_org_or_404(model, rag_id, self._RAG_ORG_PATH)
        assert_org_permission(
            request.user,
            self.get_active_org_id(),
            ResourceType.KNOWLEDGE_SOURCES,
            Permission.UPDATE,
        )

        try:
            indexing_data = IndexingService.validate_and_prepare_indexing(
                rag_id=rag_id, rag_type=rag_type
            )

            redis_service.publish_rag_indexing(
                rag_id=indexing_data["rag_id"],
                rag_type=indexing_data["rag_type"],
                collection_id=indexing_data["collection_id"],
                org_id=self.get_active_org_id(),
                embedder_api_key_secret_id=indexing_data["embedder_api_key_secret_id"],
                llm_api_key_secret_id=indexing_data["llm_api_key_secret_id"],
            )

            return Response(
                data={
                    "detail": "Indexing process accepted",
                    "rag_id": indexing_data["rag_id"],
                    "rag_type": indexing_data["rag_type"],
                    "collection_id": indexing_data["collection_id"],
                },
                status=status.HTTP_202_ACCEPTED,
            )

        except Exception:
            # DRF handle
            raise


# class ProcessCollectionEmbeddingView(APIView):
#     @extend_schema(request=ProcessCollectionEmbeddingSerializer)
#     def post(self, request):
#         serializer = ProcessCollectionEmbeddingSerializer(data=request.data)
#         if serializer.is_valid():
#             collection_id = serializer["collection_id"].value
#             if not SourceCollection.objects.filter(
#                 collection_id=collection_id
#             ).exists():
#                 return Response(status=status.HTTP_404_NOT_FOUND)
#             redis_service.publish_source_collection(collection_id=collection_id)
#             return Response(status=status.HTTP_202_ACCEPTED)


class TelegramTriggerNodeAvailableFieldsView(APIView):
    """
    GET endpoint that returns all possible fields that can be created
    for TelegramTriggerNode.
    """

    @extend_schema(**TELEGRAM_TRIGGER_AVAILABLE_FIELDS_GET)
    def get(self, request, format=None):
        data = load_telegram_trigger_fields()
        serializer = TelegramTriggerNodeDataFieldsSerializer({"data": data})
        return Response(serializer.data, status=status.HTTP_200_OK)


class RegisterTelegramTriggerApiView(APIView):
    @extend_schema(**REGISTER_TELEGRAM_TRIGGER_POST)
    def post(self, request):
        serializer = RegisterTelegramTriggerSerializer(data=request.data)
        if serializer.is_valid(raise_exception=True):
            telegram_trigger_node_id = serializer.validated_data[
                "telegram_trigger_node_id"
            ]
            telegram_trigger_node = TelegramTriggerNode.objects.filter(
                pk=telegram_trigger_node_id
            ).first()
            if not telegram_trigger_node:
                return Response(
                    {"error": "TelegramTriggerNode not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            telegram_trigger_service = TelegramTriggerService()

            telegram_trigger_service.register_telegram_trigger(
                telegram_trigger_instance=telegram_trigger_node,
            )

            return Response(status=status.HTTP_200_OK)


class RegisterWebhooksApiView(APIView):
    @extend_schema(**REGISTER_WEBHOOKS_POST)
    def post(self, request):
        webhook_trigger_service = WebhookTriggerService()
        webhook_trigger_service.register_webhooks()
        return Response(status=status.HTTP_200_OK)


class PythonNodeLastTestInputView(OrgScopedServiceViewSetMixin, APIView):
    """
    GET last tests input for python node from last
    successfull session with that node
    """

    _PYTHONNODE_ORG_PATH = "graph__org_id"

    @extend_schema(**_LAST_TEST_INPUT_SWAGGER)
    def get(self, request, pk):
        assert_org_permission(
            request.user,
            self.get_active_org_id(),
            ResourceType.FLOWS,
            Permission.READ,
        )

        python_node = self.get_in_active_org_or_404(
            PythonNode, pk, org_path=self._PYTHONNODE_ORG_PATH
        )

        python_node_name = f"{python_node.node_name} #{python_node.pk}"
        found_input = (
            GraphSessionMessage.objects.filter(
                session__graph_id=python_node.graph_id,
                session__status=Session.SessionStatus.END,
                name=python_node_name,
                message_data__message_type="start",
            )
            .order_by("-session__created_at", "-created_at")
            .values_list("message_data__input", flat=True)
            .first()
        )

        if found_input is None:
            return Response(
                {
                    "detail": "No matching test input found for this node.",
                    "input": None,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {
                "detail": "Last test input retrieved successfully.",
                "input": found_input,
            },
            status=status.HTTP_200_OK,
        )
