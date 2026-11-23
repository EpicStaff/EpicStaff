from drf_spectacular.utils import extend_schema
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from rbac.access.asserts import assert_org_permission
from rbac.models.enums import Permission, ResourceType
from rbac.scoping.mixins import OrgScopedServiceViewSetMixin
from rest_framework import status
from rest_framework.exceptions import ErrorDetail
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.views import APIView
from src.shared.models.search_config_suggestion import (
    GraphRagSuggestInput,
    NaiveRagSuggestInput,
    SuggestOutput,
)
from tables.exceptions import (
    GraphRagLlmNotConfiguredException,
    NoGraphRagForCollectionException,
)
from tables.models import SourceCollection
from tables.serializers.search_config_serializers import (
    GraphRagSuggestInputSerializer,
    NaiveRagSuggestInputSerializer,
)
from tables.services.knowledge_services.collection_management_service import (
    CollectionManagementService,
)
from tables.services.knowledge_services.graph_rag_service import GraphRagService
from tables.services.knowledge_services.search_config_service import (
    build_naive_params,
    get_graph_strategy,
    recommend_graph_search_method,
    resolve_effective_budget,
    safe_budget,
)
from tables.swagger_schemas.knowledge_schemas.search_config_schemas import (
    GRAPH_RAG_SUGGEST_PARAMS_POST,
    NAIVE_RAG_SUGGEST_PARAMS_POST,
)
from tables.utils.litellm_model_info import resolve_context_window
from user_audit.read_only import reads_only

NON_FIELD_ERRORS = api_settings.NON_FIELD_ERRORS_KEY


def _parse_body(request, input_model: type[BaseModel]) -> BaseModel:
    """Validate the request body as `input_model`, refusing it with a 400 naming each field."""
    if not isinstance(request.data, dict):
        raise DRFValidationError("Request body must be a JSON object.", code="invalid")
    try:
        return input_model(**request.data)
    except PydanticValidationError as error:
        problems: dict[str, list[ErrorDetail]] = {}
        for problem in error.errors():
            attr = ".".join(str(part) for part in problem["loc"]) or NON_FIELD_ERRORS
            problems.setdefault(attr, []).append(ErrorDetail(problem["msg"], code=problem["type"]))
        raise DRFValidationError(problems) from error


def _resolve_graph_llm_ctx(collection_id: int) -> tuple[int, str, str | None, bool]:
    """Resolve the graph-suggest context window from the collection's own GraphRag.

    Raises:
        NoGraphRagForCollectionException: The collection has no GraphRag.
        GraphRagLlmNotConfiguredException: The GraphRag has no LLM config, e.g. its
            LLM config was deleted. The graph view calls this before it fetches
            metrics, so a missing LLM is reported even while the index is not ready.
    """
    graph_rag = GraphRagService.get_or_none_graph_rag_by_collection(collection_id)
    if graph_rag is None:
        raise NoGraphRagForCollectionException(collection_id)
    llm_cfg = graph_rag.llm
    if llm_cfg is None:
        raise GraphRagLlmNotConfiguredException(collection_id)
    model_name = llm_cfg.model.name if llm_cfg.model else ""
    user_override = getattr(llm_cfg, "context_window", None)
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
    @reads_only
    def post(self, request):
        req = _parse_body(request, NaiveRagSuggestInput)

        self.get_in_active_org_or_404(SourceCollection, req.knowledge_collection_id)
        assert_org_permission(
            request.user,
            self.get_active_org_id(),
            ResourceType.KNOWLEDGE_SOURCES,
            Permission.READ,
        )

        metrics = CollectionManagementService.get_collection_metrics(
            req.knowledge_collection_id, "naive"
        )
        suggested, clamped = build_naive_params(metrics, req.user_custom_params)
        # Naive params derive only from the corpus (chunk count), so no LLM context
        # window applies and the LLM fields of the response stay empty.
        return _build_response(metrics, None, None, None, suggested, clamped, False)


class GraphRagSuggestParamsView(OrgScopedServiceViewSetMixin, APIView):
    serializer_class = GraphRagSuggestInputSerializer

    @extend_schema(**GRAPH_RAG_SUGGEST_PARAMS_POST)
    @reads_only
    def post(self, request):
        req = _parse_body(request, GraphRagSuggestInput)

        self.get_in_active_org_or_404(SourceCollection, req.knowledge_collection_id)
        assert_org_permission(
            request.user,
            self.get_active_org_id(),
            ResourceType.KNOWLEDGE_SOURCES,
            Permission.READ,
        )

        try:
            strategy = get_graph_strategy(req.search_method)
        except ValueError as error:
            raise DRFValidationError(
                {"search_method": ["Unknown graph search method."]}, code="invalid_choice"
            ) from error

        ctx, llm_name, warning, is_trusted = _resolve_graph_llm_ctx(req.knowledge_collection_id)
        metrics = CollectionManagementService.get_collection_metrics(
            req.knowledge_collection_id, "graph"
        )
        suggested, clamped = strategy.builder(metrics, ctx, is_trusted, req.user_custom_params)
        effective_budget = resolve_effective_budget(ctx, is_trusted, req.user_custom_params)
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
