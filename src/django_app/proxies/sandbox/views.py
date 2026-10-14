from rbac.access.gates import HasOrgPermission
from rbac.models.enums import ResourceType
from rbac.scoping.mixins import OrgScopedViewSetMixin
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from proxies.sandbox.clients import SandboxVenvClient
from proxies.sandbox.models import SandboxVenvBinding


class SandboxVenvBindingViewSet(OrgScopedViewSetMixin, GenericViewSet):
    queryset = SandboxVenvBinding.objects.all()
    client_class = SandboxVenvClient
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.VENVS

    def list(self, request: Request) -> Response:
        bindings = self.get_queryset().select_related("created_by")
        bindings_by_resource_id = {binding.resource_id: binding for binding in bindings}
        with self.client_class() as client:
            data = client.list(
                ids=list(bindings_by_resource_id.keys()),
                limit=request.query_params.get("limit"),
                offset=request.query_params.get("offset"),
            )
        for item in data.get("result", []):
            binding = bindings_by_resource_id.get(str(item.get("id")))
            self._apply_binding_fields(item, binding)
        return Response(data)

    def retrieve(self, request: Request, pk: str) -> Response:
        binding = self._get_binding_or_404(pk)
        with self.client_class() as client:
            data = client.retrieve(pk)
        self._apply_binding_fields(data, binding)
        return Response(data)

    def create(self, request: Request) -> Response:
        with self.client_class() as client:
            data = client.create(request.data)
        # TODO: bind the venv and the binding in one transaction -- if this write
        # fails the upstream venv is orphaned (compensation/atomic deferred).
        SandboxVenvBinding.objects.create(
            org_id=self.get_active_org_id(),
            created_by=request.user,
            resource_id=str(data["id"]),
        )
        return Response(data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, pk: str) -> Response:
        self._get_binding_or_404(pk)
        with self.client_class() as client:
            data = client.update(pk, request.data)
        return Response(data)

    def destroy(self, request: Request, pk: str) -> Response:
        binding = self._get_binding_or_404(pk)
        with self.client_class() as client:
            client.remove(pk)
        binding.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _get_binding_or_404(self, resource_id: str) -> SandboxVenvBinding:
        binding = (
            self.get_queryset().select_related("created_by").filter(resource_id=resource_id).first()
        )
        if binding is None:
            raise NotFound()
        return binding

    def _apply_binding_fields(self, item: dict, binding: SandboxVenvBinding | None) -> None:
        """Inject the owner from the binding into a venv payload."""
        item["owner"] = self._serialize_owner(binding)

    def _serialize_owner(self, binding: SandboxVenvBinding | None) -> dict | None:
        """The binding's creator as a lightweight embed, or null when unknown."""
        if binding is None or binding.created_by is None:
            return None
        owner = binding.created_by
        return {
            "id": owner.id,
            "email": owner.email,
            "display_name": owner.display_name,
        }
