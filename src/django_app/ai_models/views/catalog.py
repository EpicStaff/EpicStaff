from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rbac.access.gates import HasOrgPermission
from rbac.models.enums import Permission, ResourceType
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from ai_models.domain.specs import ModelKind
from ai_models.repository import CatalogRepository
from ai_models.serializers.catalog_serializers import (
    CatalogKindQuerySerializer,
    CatalogModelSerializer,
    CatalogModelsQuerySerializer,
    CatalogProviderSerializer,
    CatalogSchemasQuerySerializer,
)
from ai_models.services.config_validation import ConfigValidationService, schema_factory


def _query(serializer_class, request) -> dict:
    serializer = serializer_class(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class ModelCatalogViewSet(GenericViewSet):
    """Read-only model catalog for the config form: providers, models, per-model schemas.

    The catalog is one file for every organization and holds no tenant data, so nothing
    here is org-scoped. Reading it needs `llm_configs` read in the active organization,
    the gate of the config form, its only reader.
    """

    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.LLM_CONFIGS
    rbac_action_map = {
        "providers": Permission.READ,
        "models": Permission.READ,
        "schemas": Permission.READ,
    }

    @extend_schema(
        parameters=[CatalogKindQuerySerializer],
        responses=CatalogProviderSerializer(many=True),
        description="Providers a config of `kind` can use, recommended first.",
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def providers(self, request):
        query = _query(CatalogKindQuerySerializer, request)
        providers = CatalogRepository.default().providers(ModelKind(query["kind"]))
        return Response(CatalogProviderSerializer(providers, many=True).data)

    @extend_schema(
        parameters=[CatalogModelsQuerySerializer],
        responses=CatalogModelSerializer(many=True),
        description=(
            "Every model of `provider` and `kind`, recommended first; models past their "
            "deprecation date are left out. `search` matches part of the name."
        ),
    )
    # Not paginated: the picker lists a provider's whole catalog, at most a few hundred models.
    @action(detail=False, methods=["get"], pagination_class=None)
    def models(self, request):
        query = _query(CatalogModelsQuerySerializer, request)
        models = CatalogRepository.default().models(
            ModelKind(query["kind"]), query["provider"], search=query["search"]
        )
        return Response(CatalogModelSerializer(models, many=True).data)

    @extend_schema(
        parameters=[CatalogSchemasQuerySerializer],
        responses=OpenApiResponse(
            OpenApiTypes.OBJECT,
            description=(
                "`parameters` and `connection`: JSON Schemas (draft 2020-12) with UI hints; "
                "`defaults`: the settings a new config starts with."
            ),
        ),
        description="Schemas of one model. A model the catalog does not know gets the provider's common settings.",
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def schemas(self, request):
        query = _query(CatalogSchemasQuerySerializer, request)
        kind, provider, model = ModelKind(query["kind"]), query["provider"], query["model"]
        schemas = schema_factory(CatalogRepository.default())
        return Response(
            {
                "parameters": schemas.parameters_schema(kind, provider, model),
                "connection": schemas.connection_schema(provider),
                "defaults": ConfigValidationService().defaults(kind, provider, model),
            }
        )
