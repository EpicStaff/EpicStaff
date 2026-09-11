from drf_spectacular.utils import extend_schema
from loguru import logger
from pydantic import ValidationError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from src.shared.models.search_config_suggestion import (
    GraphRagSuggestInput,
    NaiveRagSuggestInput,
    SuggestOutput,
)
from tables.exceptions import (
    CollectionNotFoundException,
    GraphRagIndexNotReadyException,
    NaiveRagIndexNotReadyException,
    NoGraphRagForCollectionException,
    NoNaiveRagForCollectionException,
)
from tables.models import SourceCollection
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.serializers.search_config_serializers import (
    GraphRagSuggestInputSerializer,
    NaiveRagSuggestInputSerializer,
)
from tables.services.rbac.permission_assert import assert_org_permission
from tables.views.mixins import OrgScopedServiceViewSetMixin
from tables.swagger_schemas.knowledge_schemas.search_config_schemas import (
    GRAPH_RAG_SUGGEST_PARAMS_POST,
    NAIVE_RAG_SUGGEST_PARAMS_POST,
)
from tables.services.knowledge_services.search_config_service import (
    build_naive_params,
    get_graph_strategy,
    recommend_graph_search_method,
    resolve_effective_budget,
    safe_budget,
)
from tables.services.knowledge_services.collection_management_service import (
    CollectionManagementService,
)
from tables.services.knowledge_services.graph_rag_service import GraphRagService
from tables.utils.litellm_model_info import resolve_context_window


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


def _resolve_graph_llm_ctx(collection_id: int) -> tuple[int, str, str | None, bool]:
    """Resolve the graph-suggest context window from the collection's own GraphRag.

    The budget is sized against `GraphRag.llm` — the LLM that runs the search's
    synthesis — not a caller-supplied id, so the KnowledgeNode surface (no owning
    agent) needs nothing extra. When GraphRag has no llm, fall back to the default
    context window (is_trusted=False → custom values pass through with the same
    relaxed clamping as before).
    """
    graph_rag = GraphRagService.get_or_none_graph_rag_by_collection(collection_id)
    if graph_rag is None:
        raise NoGraphRagForCollectionException(collection_id)
    llm_cfg = graph_rag.llm
    if llm_cfg is not None:
        model_name = llm_cfg.model.name if llm_cfg.model else ""
        user_override = getattr(llm_cfg, "context_window", None)
    else:
        model_name, user_override = "", None
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
    effective_budget: int | None = None,
) -> Response:
    payload = SuggestOutput(
        metrics=metrics,
        resolved_llm_name=llm_name or None,
        llm_resolution_warning=warning,
        effective_llm_context_window=ctx,
        safe_token_budget=(
            None
            if ctx is None
            else effective_budget
            if effective_budget is not None
            else safe_budget(ctx, is_trusted)
        ),
        clamped_fields=clamped,
        suggested_params=suggested,
        recommended_search_method=recommended_method,
    )
    return Response(payload.model_dump(), status=status.HTTP_200_OK)


class NaiveRagSuggestParamsView(OrgScopedServiceViewSetMixin, APIView):
    serializer_class = NaiveRagSuggestInputSerializer

    @extend_schema(**NAIVE_RAG_SUGGEST_PARAMS_POST)
    def post(self, request):
        try:
            req = NaiveRagSuggestInput(**(request.data or {}))
        except ValidationError as exc:
            return _validation_error_response(exc)
        except TypeError:
            return Response(
                {"error": "Request body must be a JSON object."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        self.get_in_active_org_or_404(SourceCollection, req.knowledge_collection_id)
        assert_org_permission(
            request.user,
            self.get_active_org_id(),
            ResourceType.KNOWLEDGE_SOURCES,
            Permission.READ,
        )

        try:
            metrics = CollectionManagementService.get_collection_metrics(
                req.knowledge_collection_id, "naive"
            )
            suggested, clamped = build_naive_params(metrics, req.user_custom_params)
            # Naive params derive only from the corpus (chunk count); no LLM /
            # context window is involved, so the ctx-based response fields are null.
            return _build_response(metrics, None, None, None, suggested, clamped, False)
        except (
            CollectionNotFoundException,
            NoNaiveRagForCollectionException,
            NaiveRagIndexNotReadyException,
        ) as exc:
            return Response({"error": str(exc)}, status=exc.status_code)
        except Exception:
            logger.exception("Unexpected error in NaiveRagSuggestParamsView")
            raise


class GraphRagSuggestParamsView(OrgScopedServiceViewSetMixin, APIView):
    serializer_class = GraphRagSuggestInputSerializer

    @extend_schema(**GRAPH_RAG_SUGGEST_PARAMS_POST)
    def post(self, request):
        try:
            req = GraphRagSuggestInput(**(request.data or {}))
        except ValidationError as exc:
            return _validation_error_response(exc)
        except TypeError:
            return Response(
                {"error": "Request body must be a JSON object."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        self.get_in_active_org_or_404(SourceCollection, req.knowledge_collection_id)
        assert_org_permission(
            request.user,
            self.get_active_org_id(),
            ResourceType.KNOWLEDGE_SOURCES,
            Permission.READ,
        )

        try:
            strategy = get_graph_strategy(req.search_method)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            ctx, llm_name, warning, is_trusted = _resolve_graph_llm_ctx(
                req.knowledge_collection_id
            )
            metrics = CollectionManagementService.get_collection_metrics(
                req.knowledge_collection_id, "graph"
            )
            suggested, clamped = strategy.builder(
                metrics, ctx, is_trusted, req.user_custom_params
            )
            effective_budget = resolve_effective_budget(
                ctx, is_trusted, req.user_custom_params
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
                effective_budget=effective_budget,
            )
        except (
            CollectionNotFoundException,
            NoGraphRagForCollectionException,
            GraphRagIndexNotReadyException,
        ) as exc:
            # User-actionable, no sensitive detail — safe to surface verbatim.
            return Response({"error": str(exc)}, status=exc.status_code)
        except Exception:
            # No 5xx on the wire: log the traceback and defer to the project's
            # custom_exception_handler, which envelopes unexpected errors without
            # emitting a 500 in production.
            logger.exception("Unexpected error in GraphRagSuggestParamsView")
            raise
