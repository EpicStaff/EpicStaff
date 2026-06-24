from drf_spectacular.utils import extend_schema
from loguru import logger
from pydantic import ValidationError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from src.shared.models.adaptive_context import (
    GraphRagSuggestRequest,
    NaiveRagSuggestRequest,
    SuggestResponse,
)
from tables.exceptions import (
    CollectionNotFoundException,
    GraphRagArtifactMissingException,
    GraphRagIndexNotReadyException,
    LLMConfigNotFoundException,
    NoGraphRagForCollectionException,
)
from tables.models.llm_models import LLMConfig
from tables.serializers.adaptive_context_serializers import (
    GraphRagSuggestRequestSerializer,
    NaiveRagSuggestRequestSerializer,
)
from tables.swagger_schemas.knowledge_schemas.adaptive_context_schemas import (
    GRAPH_RAG_SUGGEST_PARAMS_POST,
    NAIVE_RAG_SUGGEST_PARAMS_POST,
)
from tables.services.knowledge_services.adaptive_context_service import (
    build_naive_params,
    get_graph_strategy,
    recommend_graph_search_method,
    safe_budget,
)
from tables.services.knowledge_services.collection_management_service import (
    CollectionManagementService,
)
from tables.utils.llm_context_windows import resolve_context_window


def _validation_error_response(exc: ValidationError) -> Response:
    return Response(
        {
            "error": "Validation error",
            "details": [
                {"field": ".".join(str(p) for p in err["loc"]), "msg": err["msg"]}
                for err in exc.errors()
            ],
        },
        status=status.HTTP_400_BAD_REQUEST,
    )


def _resolve_llm_ctx(llm_config_id: int) -> tuple[int, str, str | None, bool]:
    """Resolve (effective_ctx, resolved_llm_name, warning, is_trusted) for an LLMConfig ID.

    `is_trusted=True` when ctx came from litellm; False when it came from
    LLMConfig.context_window override or the global fallback.
    """
    try:
        cfg = LLMConfig.objects.select_related("model").get(pk=llm_config_id)
    except LLMConfig.DoesNotExist:
        raise LLMConfigNotFoundException(llm_config_id)

    model_name = cfg.model.name if cfg.model else ""
    user_override = getattr(cfg, "context_window", None)
    ctx, warning, is_trusted = resolve_context_window(model_name, user_override)
    return ctx, model_name, warning, is_trusted


def _build_response(
    metrics,
    ctx,
    llm_name,
    warning,
    suggested,
    clamped,
    is_trusted: bool,
    recommended_method: str | None = None,
) -> Response:
    payload = SuggestResponse(
        metrics=metrics,
        resolved_llm_name=llm_name or None,
        llm_resolution_warning=warning,
        effective_llm_context_window=ctx,
        safe_token_budget=safe_budget(ctx, is_trusted),
        clamped_fields=clamped,
        suggested_params=suggested,
        recommended_search_method=recommended_method,
    )
    return Response(payload.model_dump(), status=status.HTTP_200_OK)


class NaiveRagSuggestParamsView(APIView):
    serializer_class = NaiveRagSuggestRequestSerializer

    @extend_schema(**NAIVE_RAG_SUGGEST_PARAMS_POST)
    def post(self, request):
        try:
            req = NaiveRagSuggestRequest(**(request.data or {}))
        except ValidationError as exc:
            return _validation_error_response(exc)

        try:
            ctx, llm_name, warning, is_trusted = _resolve_llm_ctx(req.llm_config_id)
            metrics = CollectionManagementService.get_collection_metrics(
                req.knowledge_collection_id, "naive"
            )
            suggested, clamped = build_naive_params(metrics, req.user_custom_params)
        except (CollectionNotFoundException, LLMConfigNotFoundException) as exc:
            return Response({"error": str(exc)}, status=exc.status_code)
        except Exception:
            logger.exception("Unexpected error in NaiveRagSuggestParamsView")
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return _build_response(
            metrics, ctx, llm_name, warning, suggested, clamped, is_trusted
        )


class GraphRagSuggestParamsView(APIView):
    serializer_class = GraphRagSuggestRequestSerializer

    @extend_schema(**GRAPH_RAG_SUGGEST_PARAMS_POST)
    def post(self, request):
        try:
            req = GraphRagSuggestRequest(**(request.data or {}))
        except ValidationError as exc:
            return _validation_error_response(exc)

        try:
            strategy = get_graph_strategy(req.search_method)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            ctx, llm_name, warning, is_trusted = _resolve_llm_ctx(req.llm_config_id)
            metrics = CollectionManagementService.get_collection_metrics(
                req.knowledge_collection_id, "graph"
            )
            suggested, clamped = strategy.builder(
                metrics, ctx, is_trusted, req.user_custom_params
            )
        except (CollectionNotFoundException, LLMConfigNotFoundException) as exc:
            return Response({"error": str(exc)}, status=exc.status_code)
        except (
            NoGraphRagForCollectionException,
            GraphRagIndexNotReadyException,
        ) as exc:
            # User-actionable, no sensitive detail — safe to surface verbatim.
            return Response({"error": str(exc)}, status=exc.status_code)
        except GraphRagArtifactMissingException as exc:
            # Server/deployment fault: the message embeds an on-disk path. Log
            # the full detail, return a generic message to the client.
            logger.error(f"GraphRag artifact missing: {exc}")
            return Response(
                {
                    "error": (
                        "GraphRAG index artifacts are missing on the server. "
                        "Contact an administrator."
                    )
                },
                status=exc.status_code,
            )
        except Exception:
            logger.exception("Unexpected error in GraphRagSuggestParamsView")
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return _build_response(
            metrics,
            ctx,
            llm_name,
            warning,
            suggested,
            clamped,
            is_trusted,
            recommended_method=recommend_graph_search_method(metrics),
        )
