from datetime import datetime
from collections import defaultdict

from tables.models import Tool
from tables.models import Crew
from tables.models.crew_models import DefaultAgentConfig, DefaultCrewConfig
from tables.models.embedding_models import DefaultEmbeddingConfig
from tables.models.llm_models import DefaultLLMConfig
from tables.services.realtime_service import RealtimeService
from utils.logger import logger

from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from django.db import transaction
from django.db.models import Count

from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page

from rest_framework.mixins import RetrieveModelMixin, UpdateModelMixin, ListModelMixin
from rest_framework.viewsets import GenericViewSet

from rest_framework.decorators import api_view, action
from rest_framework.views import APIView
from rest_framework import generics
from rest_framework import viewsets, mixins
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError

from tables.services.config_service import YamlConfigService
from tables.services.session_manager_service import SessionManagerService
from tables.services.converter_service import ConverterService
from tables.services.redis_service import RedisService
from tables.services.run_python_code_service import RunPythonCodeService
from tables.services.quickstart_service import QuickstartService

from django_filters.rest_framework import DjangoFilterBackend


from tables.models import Session, SourceCollection
from tables.serializers.model_serializers import (
    SessionSerializer,
    DefaultLLMConfigSerializer,
    DefaultEmbeddingConfigSerializer,
    ToolSerializer,
)
from tables.serializers.serializers import (
    AnswerToLLMSerializer,
    EnvironmentConfigSerializer,
    InitRealtimeSerializer,
    RunSessionSerializer,
)
from tables.serializers.knowledge_serializers import CollectionStatusSerializer
from tables.serializers.quickstart_serializers import QuickstartSerializer

from .default_config import *

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
    serializer_class = SessionSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["graph_id"]

    def get_queryset(self):
        return Session.objects.select_related("graph").all()

    @swagger_auto_schema(
        operation_description="Get counts of each status grouped by graph ID",
        responses={
            200: openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "graph_id": openapi.Schema(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            choice.value: openapi.Schema(
                                type=openapi.TYPE_INTEGER, description=choice.label
                            )
                            for choice in Session.SessionStatus
                        },
                        description="Status counts",
                    ),
                },
                description="Mapping of graph_id to status counts",
            )
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

    @swagger_auto_schema(
        method="post",
        operation_description="Delete multiple sessions by IDs",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["ids"],
            properties={
                "ids": openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Items(type=openapi.TYPE_INTEGER),
                    description="List of session IDs to delete",
                )
            },
        ),
        responses={200: openapi.Response("Successfully deleted IDs")},
    )
    @action(detail=False, methods=["post"], url_path="bulk_delete")
    def bulk_delete(self, request):
        ids = request.data.get("ids", [])
        if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
            return Response(
                {"detail": "ids must be a list of integers."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sessions = Session.objects.filter(id__in=ids)
        deleted_count = sessions.count()
        sessions.delete()
        return Response(
            {"deleted": deleted_count, "ids": ids}, status=status.HTTP_200_OK
        )


class RunSession(APIView):

    @swagger_auto_schema(
        request_body=RunSessionSerializer,
        responses={
            201: openapi.Response(
                description="Session Started",
                examples={"application/json": {"session_id": 123}},
            ),
            400: "Bad Request - Invalid Input",
        },
    )
    def post(self, request):
        logger.info("Received POST request to start a new session.")

        serializer = RunSessionSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"Invalid data received in request: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        graph_id = serializer.validated_data["graph_id"]
        variables = serializer.validated_data.get("variables")
        try:
            # Publish session to: crew, maanger
            session_id = session_manager_service.run_session(
                graph_id=graph_id, variables=variables
            )
            logger.info(f"Session {session_id} successfully started.")
        except Exception as e:
            logger.exception(
                f"Error occurred while starting session for graph_id {graph_id}"
            )
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"error": str(e)})
        else:
            return Response(
                data={"session_id": session_id}, status=status.HTTP_201_CREATED
            )


class GetUpdates(APIView):
    @swagger_auto_schema(
        responses={
            200: openapi.Response(
                description="Session details retrieved successfully",
                examples={
                    "application/json": {
                        "status": "run",
                        "conversation": "Sample conversation",
                    }
                },
            ),
            404: openapi.Response(
                description="Session not found or session ID missing"
            ),
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

    @swagger_auto_schema(
        responses={
            204: openapi.Response(description="Session stoped"),
            404: openapi.Response(
                description="Session not found or session ID missing"
            ),
        },
    )
    def post(self, request, *args, **kwargs):
        session_id = kwargs.get("session_id", None)
        if session_id is None:
            return Response("Session id is missing", status=status.HTTP_404_NOT_FOUND)

        try:
            session_manager_service.stop_session(session_id=session_id)
        except Session.DoesNotExist:
            return Response("Session not found", status=status.HTTP_404_NOT_FOUND)

        return Response(status=status.HTTP_204_NO_CONTENT)


class EnvironmentConfig(APIView):
    @swagger_auto_schema(
        responses={
            200: openapi.Response(
                description="Config retrieved successfully",
                examples={"application/json": {"data": {"key": "value"}}},
            ),
        },
    )
    def get(self, request, format=None):

        config_dict: dict = config_service.get_all()
        logger.info("Configuration retrieved successfully.")

        return Response(status=status.HTTP_200_OK, data={"data": config_dict})

    @swagger_auto_schema(
        request_body=EnvironmentConfigSerializer,
        responses={
            201: openapi.Response(
                description="Config updated successfully",
                examples={"application/json": {"data": {"key": "value"}}},
            ),
            400: openapi.Response(description="Invalid config data provided"),
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


@swagger_auto_schema(
    method="delete",
    responses={
        204: openapi.Response(description="Config deleted successfully"),
        400: openapi.Response(description="No key provided"),
        404: openapi.Response(description="Key not found"),
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

    @swagger_auto_schema(
        request_body=AnswerToLLMSerializer,
        responses={
            202: openapi.Response(description="User input sent"),
            400: openapi.Response(description="Invalid data provided"),
            404: openapi.Response(description="Session not found"),
            418: openapi.Response(description="Session status is not wait_for_input"),
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

        session_manager_service.register_message(
            data={
                "session_id": session_id,
                "name": name,
                "execution_order": execution_order,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "message_data": {
                    "text": answer,
                    "crew_id": crew_id,
                    "message_type": "user",
                },
            },
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

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter(
                name="delete_sessions",
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                description="Delete all sessions associated (true/false). Default is false.",
                required=False,
            )
        ],
        responses={
            200: "Crew deleted successfully",
            400: "Invalid value for delete_sessions",
            404: "Crew not found",
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

    @swagger_auto_schema(
        operation_summary="Get llm config defaults",
        responses={
            200: DefaultLLMConfigSerializer,
            404: openapi.Response(description="Object not found"),
        },
    )
    def get(self, request, *args, **kwargs):
        obj = DefaultLLMConfig.objects.first()
        serializer = DefaultLLMConfigSerializer(obj, many=False)

        return Response(serializer.data)

    @swagger_auto_schema(
        operation_summary="Update llm config defaults",
        request_body=DefaultLLMConfigSerializer,
        responses={
            200: DefaultLLMConfigSerializer,
            404: openapi.Response(description="Object not found"),
            400: openapi.Response(description="Validation Error"),
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

    @swagger_auto_schema(
        operation_summary="Get embedding config defaults",
        responses={
            200: DefaultEmbeddingConfigSerializer,
            404: openapi.Response(description="Object not found"),
        },
    )
    def get(self, request, *args, **kwargs):
        obj = DefaultEmbeddingConfig.objects.first()
        serializer = DefaultEmbeddingConfigSerializer(obj, many=False)

        return Response(serializer.data)

    @swagger_auto_schema(
        operation_summary="Update embedding config defaults",
        request_body=DefaultEmbeddingConfigSerializer,
        responses={
            200: DefaultEmbeddingConfigSerializer,
            404: openapi.Response(description="Object not found"),
            400: openapi.Response(description="Validation Error"),
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
    queryset = Tool.objects.all()
    serializer_class = ToolSerializer


class RunPythonCodeAPIView(APIView):
    @swagger_auto_schema(
        operation_summary="Run Python Code",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "python_code_id": openapi.Schema(
                    type=openapi.TYPE_INTEGER,
                    description="ID of the Python code to execute",
                ),
                "variables": openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    additional_properties=openapi.Schema(type=openapi.TYPE_STRING),
                    description="Key-value arguments for the code",
                ),
            },
            required=["python_code_id"],
        ),
        responses={
            200: openapi.Response(
                description="Execution ID",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        "execution_id": openapi.Schema(
                            type=openapi.TYPE_INTEGER, description="ID of the execution"
                        )
                    },
                ),
            ),
            400: "Bad Request",
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

    @swagger_auto_schema(
        request_body=InitRealtimeSerializer,
        responses={
            201: openapi.Response(
                description="Realtime agent created successfully",
                examples={
                    "application/json": {
                        "connection_key": "d8cb1ef6-28a3-4689-a0b6-4faeb05a4f2b"
                    }
                },
            ),
            400: "Bad Request - Invalid Input",
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

        try:
            connection_key = realtime_service.init_realtime(
                agent_id=agent_id,
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


class CollectionStatusAPIView(APIView):
    def get(self, request, collection_id):
        try:
            collection = SourceCollection.objects.get(collection_id=collection_id)
            serializer = CollectionStatusSerializer(collection)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except SourceCollection.DoesNotExist:
            return Response(
                {"error": "Collection not found"}, status=status.HTTP_404_NOT_FOUND
            )


class QuickstartView(APIView):
    """
    API endpoint for managing quickstart configurations
    """

    @swagger_auto_schema(
        operation_description="Get list of supported providers",
        responses={200: openapi.Response(description="List of supported providers")},
    )
    def get(self, request):
        """
        Get list of supported providers for quickstart configuration
        """
        try:
            supported_providers = list(quickstart_service.get_supported_providers())

            return Response(
                data={
                    "supported_providers": supported_providers,
                    "count": len(supported_providers),
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.error(f"Error getting supported providers: {str(e)}")
            return Response(
                data={
                    "detail": "Failed to retrieve supported providers",
                    "error": "An unexpected error occurred",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @swagger_auto_schema(request_body=QuickstartSerializer)
    def post(self, request):
        serializer = QuickstartSerializer(data=request.data)
        if serializer.is_valid():
            provider = serializer.validated_data["provider"]
            api_key = serializer.validated_data["api_key"]

            quickstart = quickstart_service.quickstart(provider, api_key)

            if quickstart.get("success", False):
                config_name = quickstart.get("config_name")
                return Response(
                    data={
                        "detail": "Quickstart initiated successfully!",
                        "config_name": config_name,
                    },
                    status=status.HTTP_200_OK,
                )
            else:
                error = quickstart.get("error")
                return Response(
                    data={"detail": "Error quickstart", "error": error},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
