from django.core.exceptions import ValidationError
from django.db.models import Q
from django.db.models.deletion import RestrictedError
from django_filters import rest_framework as filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rbac.access.action_map import DEFAULT_ACTION_MAP
from rbac.access.gates import HasOrgPermission
from rbac.authorship import authorship_prefetches
from rbac.models.enums import Permission, ResourceType
from rbac.scoping.mixins import (
    BuiltInWriteProtectedMixin,
    OrgScopedHybridViewSetMixin,
    OrgScopedViewSetMixin,
    SuperadminWriteMixin,
)
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet
from tables.exceptions import InUseRestrictedError
from tables.services.secrets.secret_use_checks import (
    check_embedding_config_write,
    check_embedding_model_write,
    check_llm_config_write,
    check_llm_model_write,
)
from tables.swagger_schemas.bulk_delete_schemas import (
    EMBEDDING_CONFIG_BULK_DELETE_POST,
    LLM_CONFIG_BULK_DELETE_POST,
)
from tables.views.mixins import BulkDeleteActionMixin
from tables.views.secret_use import SecretUseCheckedViewSetMixin
from utils.logger import logger

from ai_models.filters import EmbeddingModelFilter, LLMModelFilter, ProviderFilter
from ai_models.models import EmbeddingConfig, EmbeddingModel, LLMConfig, LLMModel, Provider
from ai_models.serializers.model_serializers.embedding_serializers import (
    EmbeddingConfigSerializer,
    EmbeddingModelSerializer,
)
from ai_models.serializers.model_serializers.llm_serializers import (
    LLMConfigSerializer,
    LLMModelSerializer,
)
from ai_models.serializers.model_serializers.provider_serializers import ProviderSerializer
from ai_models.services.delete_services.embedding_config_delete_service import (
    EmbeddingConfigDeleteService,
)
from ai_models.services.delete_services.llm_config_delete_service import LLMConfigDeleteService


class BasePredefinedRestrictedViewSet(ModelViewSet):
    """
    Base ViewSet class for predefined models.
    Allows updating non-critical fields of predefined objects.
    Prevents deletion of predefined objects.
    """

    # No permission_classes / rbac_resource_type here on purpose: this is an
    # abstract base. Every concrete subclass (LLMModelReadWriteViewSet,
    # EmbeddingModelReadWriteViewSet) declares its own gate.

    def get_queryset(self):
        if self.action == "destroy":
            return self.queryset.filter(predefined=False)

        return self.queryset

    def perform_create(self, serializer):
        if serializer.validated_data.get("predefined", False):
            e = f"Attempt to create predefined {self.queryset.model.__name__.lower()}"
            logger.error(e)
            raise PermissionDenied(e)
        serializer.save()

    def perform_update(self, serializer):
        instance = self.get_object()
        validated_data = serializer.validated_data

        if instance.predefined:
            # Should not be able to change name
            if "name" in validated_data and validated_data["name"] != instance.name:
                e = f"Cannot change the name of a predefined {self.queryset.model.__name__.lower()}"
                logger.warning(e)
                raise ValidationError({"name": e})

            # Should not be able to remove predefined
            if "predefined" in validated_data and validated_data["predefined"] is False:
                e = "Cannot unset predefined status for this object"
                logger.warning(e)
                raise ValidationError({"predefined": e})

        else:
            if validated_data.get("predefined", False):
                e = f"Attempt to set predefined=True for custom {self.queryset.model.__name__.lower()}"
                logger.error(e)
                raise PermissionDenied(e)

        serializer.save()

    def perform_destroy(self, instance):
        if instance.predefined:
            e = f"Attempt to delete predefined {self.queryset.model.__name__.lower()}"
            logger.error(e)
            raise PermissionDenied(e)
        try:
            instance.delete()
        except RestrictedError as error:
            # Only configs restrict a model row. Configs of another organization can use it
            # too (ones stored before configs were scoped): those are counted, never named.
            own_names = sorted(
                config.custom_name
                for config in error.restricted_objects
                if config.org_id == instance.org_id
            )
            other_count = len(error.restricted_objects) - len(own_names)
            users = [", ".join(own_names)] if own_names else []
            if other_count:
                users.append(
                    f"{other_count} config{'s' if other_count > 1 else ''} of another organization"
                )
            raise InUseRestrictedError(
                f"This model is used by these configs: {' and '.join(users)}. "
                "Choose another model for them before deleting it."
            ) from None


@extend_schema_view(bulk_delete=extend_schema(**LLM_CONFIG_BULK_DELETE_POST))
class LLMConfigReadWriteViewSet(
    SecretUseCheckedViewSetMixin, OrgScopedViewSetMixin, BulkDeleteActionMixin, ModelViewSet
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.LLM_CONFIGS
    rbac_action_map = {**DEFAULT_ACTION_MAP, "bulk_delete": Permission.DELETE}
    delete_service_class = LLMConfigDeleteService
    secret_use_check = check_llm_config_write
    # The check locks the model rows it reads; see SecretUseCheckedViewSetMixin.
    secret_use_check_locks_rows = True

    class LLMConfigFilter(filters.FilterSet):
        model_provider_id = filters.CharFilter(
            field_name="model__llm_provider__id", lookup_expr="icontains"
        )

        class Meta:
            model = LLMConfig
            fields = [
                "custom_name",
                "model",
                "is_visible",
            ]

    queryset = LLMConfig.objects.select_related(
        "api_key_secret", "model__llm_provider"
    ).prefetch_related("tags", *authorship_prefetches())
    serializer_class = LLMConfigSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = LLMConfigFilter


class ProviderReadWriteViewSet(SuperadminWriteMixin, ModelViewSet):
    # No rbac_resource_type: Provider is a global catalog (no org column).
    # SuperadminWriteMixin gates writes to a superadmin's session (rows are
    # seeded via the upload_models command; no API key may write them) and
    # provides the permission classes. Reads are intentionally
    # global-readable — the frontend lists providers here
    # (LLMProvidersService.getProviders).
    uses_organization_context = False
    queryset = Provider.objects.all()
    serializer_class = ProviderSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = ProviderFilter


class LLMModelReadWriteViewSet(
    # A model row holds no secret, but LiteLLM routes a config's requests by the model's
    # name (a vendor prefix, or a URL), so renaming a model can move the secrets of its
    # configs: the secret check gates that.
    # Built-in protection runs before the secret check: a built-in model is immutable
    # (403) whatever the caller holds, and the secret check counts the configs of every
    # org that uses it. Both mixins hand every perform_* they override on to super(), so
    # the hybrid org mixin after them still runs: it scopes get_queryset and stamps the
    # org on create.
    BuiltInWriteProtectedMixin,
    SecretUseCheckedViewSetMixin,
    OrgScopedHybridViewSetMixin,
    BasePredefinedRestrictedViewSet,
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.LLM_CONFIGS
    rbac_action_map = {**DEFAULT_ACTION_MAP}
    secret_use_check = check_llm_model_write
    # The check locks the model row it reads; see SecretUseCheckedViewSetMixin.
    secret_use_check_locks_rows = True
    global_visibility_q = Q(is_custom=False)
    # force created rows into the org's custom, non-predefined subset (also
    # preserves BasePredefinedRestrictedViewSet's "no creating predefined" rule)
    custom_create_values = {"is_custom": True, "predefined": False}
    queryset = LLMModel.objects.select_related("llm_provider").prefetch_related(
        "tags", *authorship_prefetches(last_edit=False)
    )
    serializer_class = LLMModelSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = LLMModelFilter


class EmbeddingModelReadWriteViewSet(
    # As LLMModelReadWriteViewSet: renaming a model can move the secrets of its configs.
    BuiltInWriteProtectedMixin,
    SecretUseCheckedViewSetMixin,
    OrgScopedHybridViewSetMixin,
    BasePredefinedRestrictedViewSet,
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.LLM_CONFIGS
    rbac_action_map = {**DEFAULT_ACTION_MAP}
    secret_use_check = check_embedding_model_write
    # The check locks the model row it reads; see SecretUseCheckedViewSetMixin.
    secret_use_check_locks_rows = True
    global_visibility_q = Q(is_custom=False)
    # force created rows into the org's custom, non-predefined subset (also
    # preserves BasePredefinedRestrictedViewSet's "no creating predefined" rule)
    custom_create_values = {"is_custom": True, "predefined": False}
    queryset = EmbeddingModel.objects.select_related("embedding_provider").prefetch_related(
        "tags", *authorship_prefetches(last_edit=False)
    )
    serializer_class = EmbeddingModelSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = EmbeddingModelFilter


@extend_schema_view(bulk_delete=extend_schema(**EMBEDDING_CONFIG_BULK_DELETE_POST))
class EmbeddingConfigReadWriteViewSet(
    SecretUseCheckedViewSetMixin, OrgScopedViewSetMixin, BulkDeleteActionMixin, ModelViewSet
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.LLM_CONFIGS
    rbac_action_map = {**DEFAULT_ACTION_MAP, "bulk_delete": Permission.DELETE}
    delete_service_class = EmbeddingConfigDeleteService
    secret_use_check = check_embedding_config_write
    # The check locks the model rows it reads; see SecretUseCheckedViewSetMixin.
    secret_use_check_locks_rows = True

    class EmbeddingConfigFilter(filters.FilterSet):
        model_provider_id = filters.CharFilter(
            field_name="model__embedding_provider__id", lookup_expr="icontains"
        )

        class Meta:
            model = EmbeddingConfig
            fields = [
                "custom_name",
                "model",
                "is_visible",
            ]

    queryset = EmbeddingConfig.objects.select_related(
        "api_key_secret", "model__embedding_provider"
    ).prefetch_related("tags", *authorship_prefetches())
    serializer_class = EmbeddingConfigSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = EmbeddingConfigFilter
