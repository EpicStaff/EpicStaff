from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rbac.access.gates import DenyPluginCredential, HasOrgPermission, IsPerson
from rbac.authorship import resolve_author
from rbac.models.enums import Permission, ResourceType
from rbac.scoping.fields import resolve_active_org_id
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

from ai_models.domain.specs import ModelKind
from ai_models.repository import CatalogRepository
from ai_models.serializers.catalog_serializers import (
    CatalogFavoriteQuerySerializer,
    CatalogKindQuerySerializer,
    CatalogModelSerializer,
    CatalogModelsQuerySerializer,
    CatalogProviderSerializer,
    CatalogSchemasQuerySerializer,
)
from ai_models.services.catalog_model_resolver import CatalogModelResolver
from ai_models.services.config_validation import ConfigValidationService, schema_factory
from ai_models.services.model_favorites import (
    ModelFavoritesService,
    UnknownFavoriteModelError,
)


def _query(serializer_class, request) -> dict:
    serializer = serializer_class(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _refusal_example(name: str, message: str) -> OpenApiExample:
    return OpenApiExample(
        name,
        value={"status_code": 403, "code": "permission_denied", "message": message},
        response_only=True,
        status_codes=["403"],
    )


_FAVORITE_REFUSED_403 = OpenApiResponse(
    response=OpenApiTypes.OBJECT,
    description=(
        "The caller lacks `llm_configs` read in the active organization, authenticated "
        "with a plugin credential, or is not a person (the system API key). Nothing was "
        "written."
    ),
    examples=[
        _refusal_example("Plugin credential", DenyPluginCredential.message),
        _refusal_example("Not a person", IsPerson.message),
    ],
)


class ModelCatalogViewSet(GenericViewSet):
    """Read-only model catalog for the config form: providers, models, per-model schemas.

    The catalog is one file for every organization and holds no tenant data. Only the
    model list is org-scoped: it adds the active organization's own custom models, never
    another organization's. Reading needs `llm_configs` read in the active organization,
    the gate of the config form, its only reader. The form also stars LLM models for the
    person using it (`favorite/`), a personal mark the model list carries back.
    """

    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.LLM_CONFIGS
    rbac_action_map = {
        "providers": Permission.READ,
        "models": Permission.READ,
        "schemas": Permission.READ,
        "favorite": Permission.READ,
    }

    def get_permissions(self):
        permissions = super().get_permissions()
        if self.action == "favorite":
            # A star is a row keyed to the person: a plugin credential and the system
            # API key have no person to write it for.
            return [*permissions, DenyPluginCredential(), IsPerson()]
        return permissions

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
            "The active organization's custom models of `provider` and `kind` "
            "(`custom: true`, by name), then every catalog model, recommended first; "
            "models past their deprecation date are left out. `search` matches part of "
            "the name. `is_favorite`: the caller starred the model (`favorite/`); always "
            "false for an embedding model and for a caller that is not a person."
        ),
    )
    # Not paginated: the picker lists a provider's whole catalog, at most a few hundred models.
    @action(detail=False, methods=["get"], pagination_class=None)
    def models(self, request):
        query = _query(CatalogModelsQuerySerializer, request)
        kind, provider, search = ModelKind(query["kind"]), query["provider"], query["search"]
        org_id = resolve_active_org_id(request)
        custom_models = [
            {
                "name": name,
                "recommended": False,
                "deprecation_date": None,
                "limits": {},
                "custom": True,
            }
            for name in CatalogModelResolver().custom_model_names(
                kind, provider, org_id=org_id, search=search
            )
        ]
        catalog_models = CatalogRepository.default().models(kind, provider, search=search)
        favorite_names = (
            ModelFavoritesService().favorite_names(
                provider, org_id=org_id, user=resolve_author(request.user)
            )
            if kind is ModelKind.LLM
            else set()
        )
        serializer = CatalogModelSerializer(
            [*custom_models, *catalog_models],
            many=True,
            context={"favorite_names": favorite_names},
        )
        return Response(serializer.data)

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

    @extend_schema(
        methods=["POST"],
        summary="Favorite an LLM model",
        parameters=[CatalogFavoriteQuerySerializer],
        request=None,
        description=(
            "Stars the LLM model `model` of `provider`, named as the model list names it, "
            "for the current user. A personal mark, not shared with the organization. "
            "Idempotent: starring a favorite again succeeds without change."
        ),
        responses={
            200: OpenApiResponse(description="Model starred (or already was)."),
            401: UNAUTHORIZED_401_RESPONSE,
            403: _FAVORITE_REFUSED_403,
            404: OpenApiResponse(
                response=OpenApiTypes.OBJECT,
                description=(
                    "The active organization has no stored model of these names: an "
                    "unknown provider or model, another organization's custom model, or "
                    "a custom name no config has saved yet. Nothing was written."
                ),
            ),
        },
    )
    @extend_schema(
        methods=["DELETE"],
        summary="Unfavorite an LLM model",
        parameters=[CatalogFavoriteQuerySerializer],
        request=None,
        description=(
            "Removes the LLM model `model` of `provider` from the current user's favorites. "
            "Idempotent: unstarring a model that is not a favorite, or one the active "
            "organization does not see, succeeds without change."
        ),
        responses={
            200: OpenApiResponse(description="Model unstarred (or was not a favorite)."),
            401: UNAUTHORIZED_401_RESPONSE,
            403: _FAVORITE_REFUSED_403,
        },
    )
    @action(detail=False, methods=["post", "delete"], pagination_class=None)
    def favorite(self, request):
        query = _query(CatalogFavoriteQuerySerializer, request)
        provider, model = query["provider"], query["model"]
        org_id = resolve_active_org_id(request)
        favorites = ModelFavoritesService()
        if request.method == "POST":
            try:
                favorites.add(provider, model, org_id=org_id, user=request.user)
            except UnknownFavoriteModelError as error:
                raise NotFound(str(error)) from error
        else:
            favorites.remove(provider, model, org_id=org_id, user=request.user)
        return Response(status=status.HTTP_200_OK)
