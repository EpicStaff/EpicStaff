import json
from datetime import datetime, timezone
from collections import defaultdict
from drf_yasg.utils import swagger_auto_schema
import uuid
import base64
from tables.serializers.model_serializers.crew_serializers import (
    ToolSerializer,
)
from tables.serializers.model_serializers.embedding_serializers import (
    DefaultEmbeddingConfigSerializer,
)
from tables.serializers.model_serializers.llm_serializers import (
    DefaultLLMConfigSerializer,
)
from tables.services.webhook_trigger_service import WebhookTriggerService
from tables.models.graph_models import (
    TelegramTriggerNode,
    PythonNode,
    GraphSessionMessage,
)
from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.utils.telegram_fields import load_telegram_trigger_fields
from tables.models import Tool
from tables.models import Crew
from tables.models.embedding_models import DefaultEmbeddingConfig
from tables.models.llm_models import DefaultLLMConfig
from tables.services.realtime_service import RealtimeService
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
from django.db.models import Count, Exists, OuterRef
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

from tables.services.config_service import YamlConfigService
from tables.services.session_manager_service import SessionManagerService
from tables.services.converter_service import ConverterService
from tables.services.redis_service import RedisService
from tables.services.run_python_code_service import RunPythonCodeService
from tables.services.quickstart_service import QuickstartService
from tables.services.knowledge_services.indexing_service import IndexingService

from django_filters.rest_framework import DjangoFilterBackend

from tables.enums import SessionWarningType

from tables.models import (
    Session,
    # DocumentMetadata,
    GraphOrganization,
    GraphOrganizationUser,
    OrganizationUser,
    Graph,
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
    EnvironmentConfigSerializer,
    InitRealtimeSerializer,
    ProcessRagIndexingSerializer,
    RunSessionSerializer,
    RegisterTelegramTriggerSerializer,
    RunPythonCodeSerializer,
    SessionExportAllSerializer,
)

from tables.serializers.quickstart_serializers import (
    QuickstartSerializer,
    QuickstartConfigSerializer,
    QuickstartStatusSerializer,
)
from tables.serializers.default_config_serializers import DefaultModelsSerializer
from tables.filters import SessionFilter  # CollectionFilter,
from tables.services.import_export_service import ViewSetImportExportService
from tables.import_export.enums import EntityType
from tables.import_export.export_format_strategies import (
    JsonExportFormatStrategy,
    CsvExportFormatStrategy,
)
from tables.import_export.export_tabular_projections.session import SessionTabularProjection

from tables.swagger_schemas.crews_schema import CREW_DELETE
from tables.swagger_schemas.default_config_schemas import (
    DEFAULT_EMBEDDING_CONFIG_GET,
    DEFAULT_EMBEDDING_CONFIG_PUT,
    DEFAULT_LLM_CONFIG_GET,
    DEFAULT_LLM_CONFIG_PUT,
    ENVIRONMENT_CONFIG_GET,
    ENVIRONMENT_CONFIG_POST,
    ENVIRONMENT_CONFIG_DELETE,
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
config_service = YamlConfigService()
run_python_code_service = RunPythonCodeService()
realtime_service = RealtimeService()
quickstart_service = QuickstartService()


@extend_schema_view(
    retrieve=extend_schema(**SESSION_RETRIEVE_GET),
    destroy=extend_schema(**SESSION_DESTROY_DELETE),
)
class SessionViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    API endpoints for managing session objects.

    Supports listing, retrieving, deleting sessions,
    bulk deletion, and reporting aggregated status counts.
    """

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
        qs = Session.objects.select_related("graph")
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

        existing_ids = Session.objects.filter(id__in=entity_ids).values_list(
            "id", flat=True
        )
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

        if (
            "graph_id" in data
            and not Graph.objects.filter(id=data["graph_id"]).exists()
        ):
            raise NotFound(f"Graph {data['graph_id']} not found")

        qs = Session.objects.filter(parent_session_id=None)

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
            session_list = Session.objects.filter(id__in=ids)
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
        username = serializer.validated_data.get("username")
        graph_organization_user = None
        warning_messages = []

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

        graph_organization = GraphOrganization.objects.filter(
            graph__id=graph_id
        ).first()

        if graph_organization:
            if not username and graph_organization.user_variables:
                warning_messages.append(SessionWarningType.USER_VARS_WITH_NO_USER.value)

        if username and not graph_organization:
            return Response(
                {"message": "No GraphOrganization exists for this flow."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if username and graph_organization:
            # NOTE (RBAC Story 0): the old graph-domain OrganizationUser was keyed by
            # a free-form `name` string. RBAC replaces it with (User x Org x Role);
            # the `username` request param is now interpreted as the User's email.
            # TODO (RBAC Story 2+): drop `username` from the payload entirely and
            # derive the membership from `request.user` + X-Organization-Id header.
            membership = OrganizationUser.objects.filter(
                user__email=username, org=graph_organization.organization
            ).first()

            if not membership:
                return Response(
                    {
                        "message": (
                            f"Provided user does not exist or does not belong to "
                            f"organization {graph_organization.organization.name}"
                        )
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            graph_organization_user, _ = GraphOrganizationUser.objects.get_or_create(
                organization_user=membership,
                graph=graph,
                defaults={"persistent_variables": graph_organization.user_variables},
            )

        variables = serializer.validated_data.get("variables", {})
        for key, file in request.FILES.items():
            files_dict[key] = self._get_file_data(file, file.content_type)

        if files_dict is not None:
            variables["files"] = files_dict
            logger.info(f"Added {len(files_dict)} files to variables.")
        if graph_organization:
            variables.update(graph_organization.persistent_variables)
            logger.info(
                f"Organization variables are used for this flow. Variables: {graph_organization.persistent_variables}"
            )
        if graph_organization_user:
            variables.update(graph_organization_user.persistent_variables)
            logger.info(
                f"Organization user variables are used for this flow. Variables: {graph_organization_user.persistent_variables}"
            )

        try:
            # Publish session to: crew, maanger
            session_id = session_manager_service.run_session(
                graph_id=graph_id, variables=variables, username=username
            )
            logger.info(f"Session {session_id} successfully started.")
        except Exception as e:
            logger.exception(
                f"Error occurred while starting session for graph_id {graph_id}"
            )
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"error": str(e)})
        else:
            if warning_messages:
                SessionWarningMessage.objects.create(
                    session_id=session_id, messages=warning_messages
                )

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

        try:
            session_status = session_manager_service.get_session_status(
                session_id=session_id
            )
        except Session.DoesNotExist:
            return Response("Session not found", status=status.HTTP_404_NOT_FOUND)

        return Response(
            data={"status": session_status},
            status=status.HTTP_200_OK,
        )


class StopSession(APIView):
    @extend_schema(**STOP_SESSION_POST)
    def post(self, request, *args, **kwargs):
        session_id = kwargs.get("session_id", None)
        if session_id is None:
            return Response("Session id is missing", status=status.HTTP_404_NOT_FOUND)
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


class EnvironmentConfig(APIView):
    @extend_schema(**ENVIRONMENT_CONFIG_GET)
    def get(self, request, format=None):
        config_dict: dict = config_service.get_all()
        logger.info("Configuration retrieved successfully.")

        return Response(status=status.HTTP_200_OK, data={"data": config_dict})

    @extend_schema(**ENVIRONMENT_CONFIG_POST)
    def post(self, request, *args, **kwargs):
        serializer = EnvironmentConfigSerializer(data=request.data)
        if not serializer.is_valid():
            logger.error("Invalid configuration data provided.")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        config_service.set_all(config_dict=serializer.validated_data["data"])
        logger.info("Configuration updated successfully.")

        updated_config = config_service.get_all()

        return Response(data={"data": updated_config}, status=status.HTTP_201_CREATED)


@extend_schema(**ENVIRONMENT_CONFIG_DELETE)
@api_view(["DELETE"])
def delete_environment_config(request, *args, **kwargs):
    key: str | None = kwargs.get("key", None)

    if key is None:
        logger.error("No key provided in DELETE request.")
        return Response("No key provided", status=status.HTTP_400_BAD_REQUEST)

    deleted_key = config_service.delete(key=key)

    if not deleted_key:
        logger.warning(f"Key '{key}' not found.")
        return Response("Key not found", status=status.HTTP_404_NOT_FOUND)

    logger.info(f"Config key '{key}' deleted successfully.")
    return Response("Config deleted successfully", status=status.HTTP_204_NO_CONTENT)


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


class CrewDeleteAPIView(APIView):
    @extend_schema(**CREW_DELETE)
    def delete(self, request, id):
        delete_sessions = request.query_params.get("delete_sessions", "false").lower()
        if delete_sessions not in {"true", "false"}:
            raise ValidationError(
                {"error": "Invalid value for delete_sessions. Use 'true' or 'false'."}
            )

        delete_sessions = delete_sessions == "true"

        crew = Crew.objects.filter(id=id).first()
        if not crew:
            raise NotFound({"error": "Crew not found"})

        try:
            with transaction.atomic():
                if delete_sessions:
                    Session.objects.filter(crew=crew).delete()
                else:
                    Session.objects.filter(crew=crew).update(crew=None)

                crew.delete()

            return Response(
                {"message": "Crew deleted successfully"}, status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DefaultLLMConfigAPIView(APIView):
    @extend_schema(**DEFAULT_LLM_CONFIG_GET)
    def get(self, request, *args, **kwargs):
        obj = DefaultLLMConfig.objects.first()
        serializer = DefaultLLMConfigSerializer(obj, many=False)

        return Response(serializer.data)

    @extend_schema(**DEFAULT_LLM_CONFIG_PUT)
    def put(self, request, *args, **kwargs):
        try:
            obj = DefaultLLMConfig.objects.get(pk=1)
        except DefaultLLMConfig.DoesNotExist:
            return Response(
                {"error": "Object not found"}, status=status.HTTP_404_NOT_FOUND
            )

        serializer = DefaultLLMConfigSerializer(obj, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class DefaultEmbeddingConfigAPIView(APIView):
    @extend_schema(**DEFAULT_EMBEDDING_CONFIG_GET)
    def get(self, request, *args, **kwargs):
        obj = DefaultEmbeddingConfig.objects.first()
        serializer = DefaultEmbeddingConfigSerializer(obj, many=False)

        return Response(serializer.data)

    @extend_schema(**DEFAULT_EMBEDDING_CONFIG_PUT)
    def put(self, request, *args, **kwargs):
        try:
            obj = DefaultEmbeddingConfig.objects.get(pk=1)
        except DefaultEmbeddingConfig.DoesNotExist:
            return Response(
                {"error": "Object not found"}, status=status.HTTP_404_NOT_FOUND
            )

        serializer = DefaultEmbeddingConfigSerializer(obj, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ToolListRetrieveUpdateGenericViewSet(
    ListModelMixin, RetrieveModelMixin, UpdateModelMixin, GenericViewSet
):
    queryset = Tool.objects.prefetch_related("tool_fields")
    serializer_class = ToolSerializer


class RunPythonCodeAPIView(APIView):
    @extend_schema(**RUN_PYTHON_CODE_POST)
    def post(self, request):
        serializer = RunPythonCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        python_code = serializer.validated_data["python_code"]
        variables = serializer.validated_data["variables"]

        execution_id = run_python_code_service.run_code(python_code.id, variables)
        return Response({"execution_id": execution_id}, status=status.HTTP_200_OK)


class InitRealtimeAPIView(APIView):
    @extend_schema(**INIT_REALTIME_POST)
    def post(self, request):
        logger.info("Received POST request to start a new session.")

        serializer = InitRealtimeSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"Invalid data received in request: {serializer.errors}")
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
                data={"error": str(serializer.errors)},
            )

        agent_id = serializer.validated_data["agent_id"]
        config = serializer.validated_data.get("config", {})

        try:
            connection_key = realtime_service.init_realtime(
                agent_id=agent_id,
                config=config,
            )

        except Exception as e:
            logger.exception(
                f"Error occurred while creating realtime agent for agent_id {agent_id}"
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

    @extend_schema(**QUICKSTART_GET)
    def get(self, request):
        try:
            supported_providers = list(quickstart_service.get_supported_providers())
            last_config = quickstart_service.get_last_quickstart()
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
        serializer = QuickstartSerializer(data=request.data)
        if serializer.is_valid():
            provider = serializer.validated_data["provider"]
            api_key = serializer.validated_data["api_key"]

            result = quickstart_service.quickstart(provider, api_key)

            if result.get("success", False):
                config_name = result["config_name"]
                configs = QuickstartConfigSerializer(
                    {
                        "config_name": config_name,
                        "llm_config": result["llm_config"],
                        "embedding_config": result["embedding_config"],
                        "realtime_config": result["realtime_config"],
                        "realtime_transcription_config": result[
                            "realtime_transcription_config"
                        ],
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
            else:
                return Response(
                    data={"detail": "Error quickstart", "error": result.get("error")},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class QuickstartApplyView(APIView):
    """
    Applies a quickstart config to DefaultModels.
    If config_name is omitted, the most recently created quickstart config is used.
    """

    @extend_schema(**QUICKSTART_APPLY_POST)
    def post(self, request):
        last = quickstart_service.get_last_quickstart()
        if not last:
            return Response(
                {"detail": "No quickstart config found. Run POST /quickstart/ first."},
                status=status.HTTP_404_NOT_FOUND,
            )

        dm = quickstart_service.apply_to_default_models(last["config_name"])
        return Response(DefaultModelsSerializer(dm).data, status=status.HTTP_200_OK)


class ProcessRagIndexingView(APIView):
    """
    View for triggering RAG indexing (chunking + embedding).
    All business logic is handled by IndexingService.
    """

    @extend_schema(**PROCESS_RAG_INDEXING_POST)
    def post(self, request):
        serializer = ProcessRagIndexingSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        rag_id = serializer.validated_data["rag_id"]
        rag_type = serializer.validated_data["rag_type"]

        try:
            indexing_data = IndexingService.validate_and_prepare_indexing(
                rag_id=rag_id, rag_type=rag_type
            )

            redis_service.publish_rag_indexing(
                rag_id=indexing_data["rag_id"],
                rag_type=indexing_data["rag_type"],
                collection_id=indexing_data["collection_id"],
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


class PythonNodeLastTestInputView(APIView):
    @swagger_auto_schema(**_LAST_TEST_INPUT_SWAGGER)
    def get(self, request, pk):
        try:
            python_node = PythonNode.objects.get(pk=pk)
        except PythonNode.DoesNotExist:
            raise NotFound(detail="PythonNode not found.")

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
