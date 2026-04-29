from datetime import datetime, timezone
from collections import defaultdict
import uuid
import base64
from tables.services.webhook_trigger_service import WebhookTriggerService
from tables.models.graph_models import TelegramTriggerNode
from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.serializers.telegram_trigger_serializers import (
    TelegramTriggerNodeDataFieldsSerializer,
)
from tables.utils.telegram_fields import load_telegram_trigger_fields
from tables.models import Tool
from tables.models import Crew
from tables.models.embedding_models import DefaultEmbeddingConfig
from tables.models.llm_models import DefaultLLMConfig
from tables.services.realtime_service import RealtimeService
from utils.logger import logger

from drf_spectacular.utils import (
    extend_schema,
    OpenApiResponse,
    OpenApiParameter,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
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
    SourceCollection,
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
    DefaultLLMConfigSerializer,
    DefaultEmbeddingConfigSerializer,
    ToolSerializer,
)
from tables.serializers.storage_serializers import SessionOutputFileSerializer
from tables.serializers.serializers import (
    AnswerToLLMSerializer,
    EnvironmentConfigSerializer,
    InitRealtimeSerializer,
    ProcessCollectionEmbeddingSerializer,
    ProcessRagIndexingSerializer,
    RunSessionSerializer,
    RegisterTelegramTriggerSerializer,
)

from tables.serializers.quickstart_serializers import (
    QuickstartSerializer,
    QuickstartConfigSerializer,
    QuickstartStatusSerializer,
)
from tables.serializers.default_config_serializers import DefaultModelsSerializer
from tables.models.default_models import DefaultModels
from tables.filters import SessionFilter  # CollectionFilter,

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
    filterset_class = SessionFilter
    ordering_fields = [
        "created_at",
        "finished_at",
        "status",
        "status_updated_at",
        "id",
    ]  # allowed fields
    ordering = ["-created_at", "id"]  # default ordering

    @extend_schema(
        description="Retrieve a list of sessions.",
        parameters=[
            OpenApiParameter(
                name="detailed",
                location=OpenApiParameter.QUERY,
                description="Whether to include all session details. Set to `false` to return only minimal fields. The `true` value is deprecated and will be removed in a future version.",
                required=False,
                type=drf_serializers.BooleanField(),
            )
        ],
    )
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

    @extend_schema(
        description="Get counts of each status grouped by graph ID",
        responses={
            200: OpenApiResponse(description="Mapping of graph_id to status counts"),
        },
    )
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

    @extend_schema(
        description="Delete multiple sessions by IDs",
        request=inline_serializer(
            name="SessionBulkDeleteRequest",
            fields={
                "ids": drf_serializers.ListField(child=drf_serializers.IntegerField()),
            },
        ),
        responses={200: OpenApiResponse(description="Successfully deleted IDs")},
    )
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

    @extend_schema(
        responses={
            200: OpenApiResponse(description="Session warnings retrieved successfully"),
            400: OpenApiResponse(description="Session is required"),
            404: OpenApiResponse(description="Session not found"),
        },
    )
    @action(detail=True, methods=["get"], url_path="warnings")
    def get_session_warnings(self, request, pk=None):
        session = self.get_object()

        warning = (
            SessionWarningMessage.objects.filter(session=session)
            .values("messages")
            .first()
        )

        return Response(warning, status=status.HTTP_200_OK)

    @extend_schema(
        summary="List session output files",
        description=(
            "Returns all storage files recorded as output during the given session, "
            "ordered by the time they were added."
        ),
        responses={200: SessionOutputFileSerializer(many=True)},
    )
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
    @extend_schema(
        request=RunSessionSerializer,
        responses={
            201: OpenApiResponse(description="Session Started"),
            400: OpenApiResponse(description="Bad Request - Invalid Input"),
        },
    )
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
    @extend_schema(
        responses={
            200: OpenApiResponse(description="Session details retrieved successfully"),
            404: OpenApiResponse(description="Session not found or session ID missing"),
        }
    )
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
    @extend_schema(
        responses={
            204: OpenApiResponse(description="Session stopped"),
            404: OpenApiResponse(description="Session not found or session ID missing"),
        },
    )
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
    @extend_schema(
        responses={
            200: OpenApiResponse(description="Config retrieved successfully"),
        },
    )
    def get(self, request, format=None):
        config_dict: dict = config_service.get_all()
        logger.info("Configuration retrieved successfully.")

        return Response(status=status.HTTP_200_OK, data={"data": config_dict})

    @extend_schema(
        request=EnvironmentConfigSerializer,
        responses={
            201: OpenApiResponse(description="Config updated successfully"),
            400: OpenApiResponse(description="Invalid config data provided"),
        },
    )
    def post(self, request, *args, **kwargs):
        serializer = EnvironmentConfigSerializer(data=request.data)
        if not serializer.is_valid():
            logger.error("Invalid configuration data provided.")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        config_service.set_all(config_dict=serializer.validated_data["data"])
        logger.info("Configuration updated successfully.")

        updated_config = config_service.get_all()

        return Response(data={"data": updated_config}, status=status.HTTP_201_CREATED)


@extend_schema(
    responses={
        204: OpenApiResponse(description="Config deleted successfully"),
        400: OpenApiResponse(description="No key provided"),
        404: OpenApiResponse(description="Key not found"),
    },
)
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
    @extend_schema(
        request=AnswerToLLMSerializer,
        responses={
            202: OpenApiResponse(description="User input sent"),
            400: OpenApiResponse(description="Invalid data provided"),
            404: OpenApiResponse(description="Session not found"),
            418: OpenApiResponse(description="Session status is not wait_for_input"),
        },
    )
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
    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="delete_sessions",
                location=OpenApiParameter.QUERY,
                type=drf_serializers.CharField(),
                description="Delete all sessions associated (true/false). Default is false.",
                required=False,
            )
        ],
        responses={
            200: OpenApiResponse(description="Crew deleted successfully"),
            400: OpenApiResponse(description="Invalid value for delete_sessions"),
            404: OpenApiResponse(description="Crew not found"),
        },
    )
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
    @extend_schema(
        summary="Get llm config defaults",
        responses={
            200: DefaultLLMConfigSerializer,
            404: OpenApiResponse(description="Object not found"),
        },
    )
    def get(self, request, *args, **kwargs):
        obj = DefaultLLMConfig.objects.first()
        serializer = DefaultLLMConfigSerializer(obj, many=False)

        return Response(serializer.data)

    @extend_schema(
        summary="Update llm config defaults",
        request=DefaultLLMConfigSerializer,
        responses={
            200: DefaultLLMConfigSerializer,
            404: OpenApiResponse(description="Object not found"),
            400: OpenApiResponse(description="Validation Error"),
        },
    )
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
    @extend_schema(
        summary="Get embedding config defaults",
        responses={
            200: DefaultEmbeddingConfigSerializer,
            404: OpenApiResponse(description="Object not found"),
        },
    )
    def get(self, request, *args, **kwargs):
        obj = DefaultEmbeddingConfig.objects.first()
        serializer = DefaultEmbeddingConfigSerializer(obj, many=False)

        return Response(serializer.data)

    @extend_schema(
        summary="Update embedding config defaults",
        request=DefaultEmbeddingConfigSerializer,
        responses={
            200: DefaultEmbeddingConfigSerializer,
            404: OpenApiResponse(description="Object not found"),
            400: OpenApiResponse(description="Validation Error"),
        },
    )
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
    @extend_schema(
        summary="Run Python Code",
        request=inline_serializer(
            name="RunPythonCodeRequest",
            fields={
                "python_code_id": drf_serializers.IntegerField(),
                "variables": drf_serializers.DictField(
                    child=drf_serializers.CharField(), required=False
                ),
            },
        ),
        responses={
            200: inline_serializer(
                name="RunPythonCodeResponse",
                fields={
                    "execution_id": drf_serializers.IntegerField(),
                },
            ),
            400: OpenApiResponse(description="Bad Request"),
        },
    )
    def post(self, request):
        python_code_id = request.data.get("python_code_id")
        variables = request.data.get("variables", {})

        if not python_code_id:
            return Response(
                {"error": "python_code_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        execution_id = run_python_code_service.run_code(python_code_id, variables)
        return Response({"execution_id": execution_id}, status=status.HTTP_200_OK)


class InitRealtimeAPIView(APIView):
    @extend_schema(
        request=InitRealtimeSerializer,
        responses={
            201: OpenApiResponse(description="Realtime agent created successfully"),
            400: OpenApiResponse(description="Bad Request - Invalid Input"),
        },
    )
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

    @extend_schema(
        description="Get list of supported providers",
        responses={200: OpenApiResponse(description="List of supported providers")},
    )
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

    @extend_schema(
        request=QuickstartSerializer,
        responses={202: OpenApiResponse(description="Chunking operation accepted")},
    )
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

    @extend_schema(
        responses={200: DefaultModelsSerializer},
    )
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

    @extend_schema(
        request=ProcessRagIndexingSerializer,
        responses={
            202: OpenApiResponse(description="Indexing process accepted and queued"),
            400: OpenApiResponse(
                description="Invalid request or RAG not ready for indexing"
            ),
            404: OpenApiResponse(description="RAG configuration not found"),
        },
    )
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

    def get(self, request, format=None):
        data = load_telegram_trigger_fields()
        serializer = TelegramTriggerNodeDataFieldsSerializer({"data": data})
        return Response(serializer.data, status=status.HTTP_200_OK)


class RegisterTelegramTriggerApiView(APIView):
    @extend_schema(
        request=RegisterTelegramTriggerSerializer,
        responses={
            200: OpenApiResponse(description="OK"),
            404: OpenApiResponse(description="TelegramTriggerNode not found"),
            503: OpenApiResponse(description="No webhook tunnel available"),
        },
    )
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
    @extend_schema(
        responses={200: OpenApiResponse(description="OK")},
    )
    def post(self, request):
        webhook_trigger_service = WebhookTriggerService()
        webhook_trigger_service.register_webhooks()
        return Response(status=status.HTTP_200_OK)
