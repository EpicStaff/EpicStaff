from django.db.models import Exists, OuterRef, Value
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rbac.access.action_map import DEFAULT_ACTION_MAP
from rbac.access.gates import DenyPluginCredential, HasOrgPermission
from rbac.authorship.policy import resolve_author
from rbac.models.enums import Permission, ResourceType
from rbac.scoping.mixins import OrgScopedServiceViewSetMixin, OrgScopedViewSetMixin
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from tables.services.secrets.request_actor import actor_from_request
from tables.services.secrets.secret_use_checks import check_venv_write

from proxies.models import AbstractBinding
from proxies.sandbox.models import SandboxCustomLibraryBinding, SandboxVenvBinding
from proxies.sandbox.services import CustomLibraryService, VenvService


def serialize_owner(binding: AbstractBinding) -> dict | None:
    """The binding's creator as a lightweight embed, or null when unknown."""
    if binding.created_by is None:
        return None
    owner = binding.created_by
    return {
        "id": owner.id,
        "email": owner.email,
        "display_name": owner.display_name,
    }


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
            created_by=resolve_author(request.user),
        )
        return Response(self._as_response(venv, binding), status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, pk: str) -> Response:
        """Change a venv's name or libraries.

        Changing the libraries of a venv that code declaring secrets runs in needs
        secrets:USE (`check_venv_write`), checked before anything is sent to the sandbox.

        Raises:
            Http404: No venv with this id in the active org.
            SecretUseDeniedError: The libraries change and the caller lacks secrets:USE.
                Rendered as a 400 under `libs`.
        """
        binding = self._get_binding_or_404(pk)
        service = self.service_class()
        check_venv_write(
            actor_from_request(request),
            binding,
            request.data,
            read_current_libs=lambda: service.retrieve(binding).get("libs"),
        )
        venv = service.update(binding, request.data)
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
        item["owner"] = serialize_owner(binding)
        item["is_favorite"] = bool(getattr(binding, "is_favorite", False))
        return item


class SandboxCustomLibraryBindingViewSet(OrgScopedViewSetMixin, GenericViewSet):
    """Custom libraries as this API exposes them: addressed by their binding, never
    by the sandbox's own id. The upstream id stays inside this package."""

    queryset = SandboxCustomLibraryBinding.objects.all()
    service_class = CustomLibraryService
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.CUSTOM_LIBRARIES
    lookup_value_regex = "[0-9]+"

    def list(self, request: Request) -> Response:
        page, pairs = self.service_class().list_page(
            self.get_queryset().select_related("created_by"),
            limit=request.query_params.get("limit"),
            offset=request.query_params.get("offset"),
        )
        page["result"] = [self._as_response(library, binding) for library, binding in pairs]
        return Response(page)

    def retrieve(self, request: Request, pk: str) -> Response:
        binding = self._get_binding_or_404(pk)
        return Response(self._as_response(self.service_class().retrieve(binding), binding))

    def create(self, request: Request) -> Response:
        """Create a library from an uploaded wheel, which names it.

        Raises:
            ValidationError: The request carries no file.
        """
        file = request.FILES.get("file")
        if file is None:
            raise ValidationError({"file": "No file was uploaded."})
        binding, library = self.service_class().create(
            file,
            org_id=self.get_active_org_id(),
            created_by=resolve_author(request.user),
        )
        return Response(self._as_response(library, binding), status=status.HTTP_201_CREATED)

    def destroy(self, request: Request, pk: str) -> Response:
        """Delete a library no venv names any more.

        Raises:
            Http404: No library with this id in the active org.
            ClientConflictError: Some venv still names it. Rendered as 409.
        """
        self.service_class().delete(self._get_binding_or_404(pk))
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _get_binding_or_404(self, pk: str) -> SandboxCustomLibraryBinding:
        return get_object_or_404(self.get_queryset().select_related("created_by"), pk=pk)

    def _as_response(self, item: dict, binding: SandboxCustomLibraryBinding) -> dict:
        """Replace the upstream id with the binding's own, and add its owner."""
        item["id"] = binding.pk
        item["owner"] = serialize_owner(binding)
        return item


class SandboxWheelViewSet(OrgScopedServiceViewSetMixin, GenericViewSet):
    """The versions of one custom library.

    Addressed only under their library, and scoped by its binding: a library the
    active org does not own is a 404 before the sandbox is asked anything. The
    sandbox's wheel ids are passed through, because they mean nothing outside the
    library that the caller already had to own.
    """

    service_class = CustomLibraryService
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.CUSTOM_LIBRARIES
    rbac_action_map = {**DEFAULT_ACTION_MAP, "download": Permission.READ}
    lookup_value_regex = "[0-9]+"

    def list(self, request: Request, library_pk: str) -> Response:
        return Response(self.service_class().list_wheels(self._get_library_or_404(library_pk)))

    def retrieve(self, request: Request, library_pk: str, pk: str) -> Response:
        binding = self._get_library_or_404(library_pk)
        return Response(self.service_class().retrieve_wheel(binding, pk))

    def create(self, request: Request, library_pk: str) -> Response:
        """Upload a wheel or a source archive as a new version.

        Raises:
            Http404: No library with this id in the active org.
            ValidationError: The request carries no file.
        """
        binding = self._get_library_or_404(library_pk)
        file = request.FILES.get("file")
        if file is None:
            raise ValidationError({"file": "No file was uploaded."})
        wheel = self.service_class().upload_wheel(binding, file)
        return Response(wheel, status=status.HTTP_201_CREATED)

    def destroy(self, request: Request, library_pk: str, pk: str) -> Response:
        self.service_class().remove_wheel(self._get_library_or_404(library_pk), pk)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"], url_path="file")
    def download(self, request: Request, library_pk: str, pk: str) -> HttpResponse:
        """Hand back the wheel itself, named the way the sandbox named it."""
        binding = self._get_library_or_404(library_pk)
        content, disposition = self.service_class().download_wheel(binding, pk)
        response = HttpResponse(content, content_type="application/octet-stream")
        if disposition:
            response["Content-Disposition"] = disposition
        return response

    def _get_library_or_404(self, library_pk: str) -> SandboxCustomLibraryBinding:
        return self.get_in_active_org_or_404(SandboxCustomLibraryBinding, library_pk)
