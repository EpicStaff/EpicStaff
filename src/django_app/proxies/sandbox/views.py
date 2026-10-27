from django.shortcuts import get_object_or_404
from rbac.access.gates import HasOrgPermission
from rbac.models.enums import ResourceType
from rbac.scoping.mixins import OrgScopedViewSetMixin
from rest_framework import status
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
    lookup_value_regex = "[0-9]+"

    def list(self, request: Request) -> Response:
        page, pairs = self.service_class().list_page(
            self.get_queryset().select_related("created_by"),
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

    def _get_binding_or_404(self, pk: str) -> SandboxVenvBinding:
        return get_object_or_404(self.get_queryset().select_related("created_by"), pk=pk)

    def _as_response(self, item: dict, binding: SandboxVenvBinding) -> dict:
        """Replace the upstream id with the binding's own, and add its owner.

        Callers address a venv by its binding: that is the row carrying the
        organization allowed to reach it, and the sandbox's id never leaves here.
        """
        item["id"] = binding.pk
        item["owner"] = self._serialize_owner(binding)
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
