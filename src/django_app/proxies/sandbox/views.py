from django.db.models import Exists, OuterRef, Value
from django.shortcuts import get_object_or_404
from rbac.access.action_map import DEFAULT_ACTION_MAP
from rbac.access.gates import DenyPluginCredential, HasOrgPermission
from rbac.authorship.policy import resolve_author
from rbac.models.enums import Permission, ResourceType
from rbac.scoping.mixins import OrgScopedViewSetMixin
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from proxies.sandbox.models import SandboxVenvBinding
from proxies.sandbox.services import VenvService


class SandboxVenvBindingViewSet(OrgScopedViewSetMixin, GenericViewSet):
    """Venvs as this API exposes them: addressed by their binding, never by the
    sandbox's own id. The upstream id stays inside this package."""

    queryset = SandboxVenvBinding.objects.all()
    service_class = VenvService
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.VENVS
    rbac_action_map = {**DEFAULT_ACTION_MAP, "favorite": Permission.READ}
    lookup_value_regex = "[0-9]+"

    def get_queryset(self):
        """The organization's bindings, each carrying whether the caller favorited it.

        One `EXISTS` subquery for the whole page rather than a lookup per row. A caller
        that is not a person -- an API key, a plugin service account -- favorites
        nothing, so the annotation is a constant for them.
        """
        author = resolve_author(self.request.user)
        is_favorite = (
            Exists(author.favorited_venvs.filter(pk=OuterRef("pk")))
            if author is not None
            else Value(False)
        )
        return super().get_queryset().annotate(is_favorite=is_favorite)

    def get_permissions(self):
        permissions = super().get_permissions()
        # A favorite belongs to a person.
        if self.action == "favorite":
            return [*permissions, DenyPluginCredential()]
        return permissions

    def list(self, request: Request) -> Response:
        bindings = self.get_queryset().select_related("created_by")
        if request.query_params.get("is_favorite") == "true":
            # Filtering the annotation keeps the one query shape: a caller who favorites
            # nothing gets an empty page instead of a second branch here.
            bindings = bindings.filter(is_favorite=True)
        page, pairs = self.service_class().list_page(
            bindings,
            search=request.query_params.get("search"),
            order=request.query_params.get("order"),
            limit=request.query_params.get("limit"),
            offset=request.query_params.get("offset"),
        )
        page["result"] = [self._as_response(venv, binding) for venv, binding in pairs]
        return Response(page)

    def retrieve(self, request: Request, pk: str) -> Response:
        binding = self._get_binding_or_404(pk)
        return Response(self._as_response(self.service_class().retrieve(binding), binding))

    def create(self, request: Request) -> Response:
        binding, venv = self.service_class().create(
            request.data,
            org_id=self.get_active_org_id(),
            created_by=request.user,
        )
        return Response(self._as_response(venv, binding), status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, pk: str) -> Response:
        binding = self._get_binding_or_404(pk)
        venv = self.service_class().update(binding, request.data)
        return Response(self._as_response(venv, binding))

    def destroy(self, request: Request, pk: str) -> Response:
        """Delete a venv nothing runs in any more.

        Raises:
            Http404: No venv with this id in the active org.
            VenvInUseError: Some Python code still runs in it. Rendered as 409.
        """
        self.service_class().delete(self._get_binding_or_404(pk))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post", "delete"], url_path="favorite")
    def favorite(self, request: Request, pk: str) -> Response:
        """Mark this venv as the caller's favorite, or take the mark off again.

        Idempotent both ways: marking what is already marked, and unmarking what is
        not, both answer 200.

        Raises:
            Http404: No venv with this id in the active org.
        """
        binding = self._get_binding_or_404(pk)
        if request.method == "POST":
            binding.favorited_by.add(request.user)
        else:
            binding.favorited_by.remove(request.user)
        return Response(status=status.HTTP_200_OK)

    def _get_binding_or_404(self, pk: str) -> SandboxVenvBinding:
        return get_object_or_404(self.get_queryset().select_related("created_by"), pk=pk)

    def _as_response(self, item: dict, binding: SandboxVenvBinding) -> dict:
        """Replace the upstream id with the binding's own, and add its owner.

        Callers address a venv by its binding: that is the row carrying the
        organization allowed to reach it, and the sandbox's id never leaves here.
        """
        item["id"] = binding.pk
        item["owner"] = self._serialize_owner(binding)
        item["is_favorite"] = bool(getattr(binding, "is_favorite", False))
        return item

    def _serialize_owner(self, binding: SandboxVenvBinding) -> dict | None:
        """The binding's creator as a lightweight embed, or null when unknown."""
        if binding.created_by is None:
            return None
        owner = binding.created_by
        return {
            "id": owner.id,
            "email": owner.email,
            "display_name": owner.display_name,
        }
