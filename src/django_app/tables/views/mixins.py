from django.db import transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.settings import api_settings

from tables.serializers.serializers import (
    ToolUsageDetailSerializer,
    ToolUsageSerializer,
)
from tables.services.rbac.org_context_service import OrgContextService
from tables.services.rbac.permissions import IsSuperadmin
from tables.services.tools_usage_service import ToolNotFoundError, get_tools_usage


class CopyActionMixin:
    """Mixin that adds a ``copy`` action to a ViewSet.

    Requires two class attributes:
        copy_service_class: Copy service to instantiate.
        copy_serializer_class: Serializer for the response.
    """

    copy_service_class = None
    copy_serializer_class = None

    @action(detail=True, methods=["post"], url_path="copy")
    def copy(self, request, pk: int):
        instance = self.get_object()
        name = request.data.get("name") if isinstance(request.data, dict) else None
        # Org-scoped viewsets stamp the copy with the active org so the new row
        # satisfies the NOT NULL org constraint. Non-org-scoped viewsets (e.g.
        # tool copies) don't expose get_active_org_id and copy without an org.
        extra = {}
        if hasattr(self, "get_active_org_id"):
            extra["org_id"] = self.get_active_org_id()
        try:
            with transaction.atomic():
                new_instance = self.copy_service_class().copy(
                    instance, name=name, **extra
                )
        except Exception as e:
            return Response({"message": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            self.copy_serializer_class(new_instance).data,
            status=status.HTTP_201_CREATED,
        )


class OrgScopedResolverMixin:
    """Resolves and caches the active org id for the request.

    The shared base for every org-aware viewset mixin below, and the public
    primitive to inherit directly when a viewset scopes its queryset in a way
    the standard mixins don't cover (see OrgScopedQuerysetMixin).

    Relies on IsAuthenticated running first (request.user is authenticated).
    Pairs with HasOrgPermission, which uses the same OrgContextService.
    """

    _org_context = OrgContextService()

    def get_active_org_id(self) -> int:
        if not hasattr(self.request, "_rbac_active_org_id"):
            self.request._rbac_active_org_id = self._org_context.resolve(
                request=self.request, view_kwargs=self.kwargs
            )
        return self.request._rbac_active_org_id


class OrgScopedViewSetMixin(OrgScopedResolverMixin):
    """For top-level resources that own an `org` FK directly.

    Place FIRST in the ViewSet's base list so get_queryset/perform_create
    wrap the concrete ViewSet base.
    """

    def get_queryset(self):
        return super().get_queryset().filter(org_id=self.get_active_org_id())

    def perform_create(self, serializer):
        serializer.save(org_id=self.get_active_org_id(), created_by=self.request.user)


class OrgScopedChildViewSetMixin(OrgScopedResolverMixin):
    """For child resources scoped transitively through a parent FK.

    Set `org_filter_path` to the ORM lookup that reaches the owning org,
    e.g. "graph__org_id", "crew__org_id", "agent__org_id". Does not stamp
    org on create (children have no org column; the parent FK carries it).
    """

    org_filter_path: str = None

    def get_queryset(self):
        if not self.org_filter_path:
            raise NotImplementedError(
                f"{self.__class__.__name__} must set org_filter_path."
            )
        return (
            super()
            .get_queryset()
            .filter(**{self.org_filter_path: self.get_active_org_id()})
        )

    def perform_create(self, serializer):
        # A child may only be created under a parent that lives in the active
        # org — otherwise a caller could attach a child to another org's parent.
        self._assert_parent_in_active_org(serializer)
        serializer.save()

    def _assert_parent_in_active_org(self, serializer):
        if not self.org_filter_path:
            return
        parent_field, _, org_lookup = self.org_filter_path.partition("__")
        parent = serializer.validated_data.get(parent_field)
        if parent is None:
            return
        org_id = parent
        for attr in org_lookup.split("__"):
            org_id = getattr(org_id, attr, None)
            if org_id is None:
                break
        if org_id != self.get_active_org_id():
            raise NotFound()


class OrgScopedHybridViewSetMixin(OrgScopedResolverMixin):
    """For top-level resources that are EITHER shared built-ins (org IS NULL,
    visible to every org) OR an org's own custom rows.

    Declare `global_visibility_q` — a Q matching the built-in subset
    (e.g. Q(is_custom=False) for models, Q(built_in=True) for tools) — and
    `custom_create_values` — the field values that force a newly-created row
    OUT of that built-in subset (e.g. {"is_custom": True} for models,
    {"built_in": False} for tools). Without the latter, a created row could
    default into the global subset and leak across orgs. Place FIRST in the
    ViewSet's base list. `org` stays nullable (no NOT NULL flip): built-ins
    keep org=NULL.
    """

    global_visibility_q: Q = None
    custom_create_values: dict = None

    def get_queryset(self):
        if self.global_visibility_q is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} must set global_visibility_q."
            )
        return (
            super()
            .get_queryset()
            .filter(self.global_visibility_q | Q(org_id=self.get_active_org_id()))
        )

    def perform_create(self, serializer):
        # A row created via the org API is, by definition, that org's custom row:
        # stamp the org and force it out of the shared/built-in subset.
        if self.custom_create_values is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} must set custom_create_values."
            )
        serializer.save(
            org_id=self.get_active_org_id(),
            created_by=self.request.user,
            **self.custom_create_values,
        )


class OrgScopedQuerysetMixin(OrgScopedResolverMixin):
    """For resources whose org scope does not fit the standard mixins above.

    Implement `get_org_scope_q(org_id) -> Q` to return the filter expression.
    Use this when a resource is reachable through several different parents, or
    when its visibility is inherited from a hybrid (built-in/custom) parent.

    Set `scope_distinct = True` when the scope Q spans reverse or multi-valued
    joins that can duplicate rows. Does not stamp org on create (override
    perform_create if the resource owns an org column).
    """

    scope_distinct: bool = False

    def get_org_scope_q(self, org_id: int) -> Q:
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement get_org_scope_q()."
        )

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .filter(self.get_org_scope_q(self.get_active_org_id()))
        )
        return queryset.distinct() if self.scope_distinct else queryset


class OrgScopedServiceViewSetMixin(OrgScopedResolverMixin):
    """For views that delegate to services using raw ids and so cannot rely on
    get_object()/get_queryset scoping (common in the knowledge endpoints).

    Provides one helper to fetch a target row scoped to the active org, raising
    404 on a missing or cross-org id (no existence leak, D1). The `org_path` is
    the ORM lookup from `model` to the org id — the same vocabulary as
    OrgScopedChildViewSetMixin.org_filter_path (default "org_id" for an
    org-owning model; e.g. "base_rag_type__source_collection__org_id" for a
    knowledge child).

    Works on both ViewSets and plain APIViews (only needs request + kwargs).
    Pair with HasOrgPermission (ViewSets) or assert_org_permission (APIViews)
    for the verb gate.
    """

    def get_in_active_org_or_404(self, model, pk, org_path: str = "org_id", **filters):
        obj = model.objects.filter(
            pk=pk, **{org_path: self.get_active_org_id()}, **filters
        ).first()
        if obj is None:
            raise NotFound()
        return obj


class ToolUsageActionsMixin:
    MAX_USAGE_IDS = api_settings.PAGE_SIZE

    def _usage_response(self, request, tool_model):
        ids = request.data.get("ids")
        if ids is not None:
            if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
                return Response(
                    {"detail": "ids must be a list of integers."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if len(ids) > self.MAX_USAGE_IDS:
                return Response(
                    {
                        "detail": (
                            f"maximum {self.MAX_USAGE_IDS} allowed, got {len(ids)}"
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            ids = set(ids)

        rows = get_tools_usage(self.get_active_org_id(), tool_model, ids=ids)
        serializer = ToolUsageSerializer(rows, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def _usage_detail_response(self, pk, service_fn, not_found_name):
        org_id = self.get_active_org_id()
        try:
            detail = service_fn(int(pk), org_id)
        except (ToolNotFoundError, ValueError):
            raise NotFound(f"{not_found_name} {pk} not found.")
        serializer = ToolUsageDetailSerializer(detail)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SuperadminWriteMixin:
    """Global-readable, superadmin-writable resources (registry / catalog /
    defaults).

    Reads (safe actions) require only IsAuthenticated; writes
    (create/update/partial_update/destroy + any custom action listed in
    `superadmin_write_actions`) additionally require IsSuperadmin. Does NOT
    org-scope — these rows are global. Pairs with the project default
    permission_classes = [IsAuthenticated].
    """

    superadmin_write_actions = frozenset(
        {"create", "update", "partial_update", "destroy"}
    )

    def get_permissions(self):
        if getattr(self, "action", None) in self.superadmin_write_actions:
            return [IsAuthenticated(), IsSuperadmin()]
        return [IsAuthenticated()]
