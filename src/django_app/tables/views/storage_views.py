from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action, parser_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from tables.models import GraphStorageFile, StorageFile
from tables.models.graph_models import Graph
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.views.mixins import OrgScopedResolverMixin
from tables.services.rbac.authentication import JwtOrApiKeyAuthentication
from tables.services.rbac.permissions import HasOrgPermission
from tables.serializers.storage_serializers import (
    GraphStorageFileSerializer,
    StorageAddToGraphSerializer,
    StorageBulkDeleteSerializer,
    StorageCopySerializer,
    StorageDownloadZipSerializer,
    StorageFilesByIdsQuerySerializer,
    StorageFileSerializer,
    StorageGraphFilesQuerySerializer,
    StorageMkdirSerializer,
    StorageMoveSerializer,
    StoragePathQuerySerializer,
    StorageRemoveFromGraphSerializer,
    StorageRenameSerializer,
    StorageSearchQuerySerializer,
    StorageTreeQuerySerializer,
    StorageUploadSerializer,
)
from tables.services.storage_service import get_storage_manager
from tables.services.storage_service.dataclasses import FolderInfo
from tables.swagger_schemas.storage_schema import (
    STORAGE_ADD_TO_GRAPH_SWAGGER,
    STORAGE_COPY_SWAGGER,
    STORAGE_DELETE_SWAGGER,
    STORAGE_DOWNLOAD_SWAGGER,
    STORAGE_DOWNLOAD_ZIP_SWAGGER,
    STORAGE_FILES_BY_IDS_SWAGGER,
    STORAGE_GRAPH_FILES_SWAGGER,
    STORAGE_INFO_SWAGGER,
    STORAGE_LIST_SWAGGER,
    STORAGE_MKDIR_SWAGGER,
    STORAGE_MOVE_SWAGGER,
    STORAGE_REMOVE_FROM_GRAPH_SWAGGER,
    STORAGE_RENAME_SWAGGER,
    STORAGE_SEARCH_SWAGGER,
    STORAGE_TREE_SWAGGER,
    STORAGE_UPLOAD_SWAGGER,
)


class StorageAPIView(OrgScopedResolverMixin, ViewSet):
    authentication_classes = [JwtOrApiKeyAuthentication]
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FILES
    rbac_action_map = {
        "list_files": Permission.READ,
        "info": Permission.READ,
        "download": Permission.READ,
        "tree": Permission.READ,
        "graph_files": Permission.READ,
        "files_by_ids": Permission.READ,
        "search": Permission.READ,
        "download_zip": Permission.EXPORT,
        "upload": Permission.CREATE,
        "mkdir": Permission.CREATE,
        "add_to_graph": Permission.CREATE,
        "rename": Permission.UPDATE,
        "move": Permission.UPDATE,
        "copy": Permission.UPDATE,
        "delete_file": Permission.DELETE,
        "remove_from_graph": Permission.DELETE,
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.manager = get_storage_manager()

    def _assert_cross_org_superadmin(self, request, src_org_id, dst_org_id) -> bool:
        """True when this is a cross-org transfer; such transfers require
        superadmin (operating across organizations is a platform action)."""
        cross_org = bool(
            src_org_id and dst_org_id and int(src_org_id) != int(dst_org_id)
        )
        # TODO: refactor by checking permision of READ in src_org_id then check permission of
        # CREATE in dst_org_id, Part of cross-org RBAC feature
        if cross_org and not getattr(request.user, "is_superadmin", False):
            raise PermissionDenied(
                "Cross-organization file transfer requires superadmin."
            )
        return cross_org

    @extend_schema(**STORAGE_LIST_SWAGGER)
    @action(detail=False, methods=["get"], url_path="list")
    def list_files(self, request):
        org_id = self.get_active_org_id()
        params = StoragePathQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        prefix = params.validated_data["path"]

        if prefix:
            try:
                self.manager.info(org_id, prefix)
            except FileNotFoundError:
                raise NotFound({"path": f"Path does not exist: {prefix}"})

        items = self.manager.list_(org_id, prefix)
        return Response({"path": prefix, "items": [i.to_dict() for i in items]})

    @extend_schema(**STORAGE_INFO_SWAGGER)
    @action(detail=False, methods=["get"], url_path="info")
    def info(self, request):
        org_id = self.get_active_org_id()
        params = StoragePathQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        path = params.validated_data["path"]

        try:
            data = self.manager.info(org_id, path)
        except FileNotFoundError:
            raise NotFound({"path": f"File does not exist: {path}"})

        response = data.to_dict()

        graph_path = path
        if isinstance(data, FolderInfo) and not graph_path.endswith("/"):
            graph_path = graph_path + "/"

        response["graphs"] = list(
            Graph.objects.filter(
                storage_files__storage_file__path=graph_path,
                storage_files__storage_file__org_id=org_id,
            ).values("id", "name")
        )
        return Response(response)

    @extend_schema(**STORAGE_DOWNLOAD_SWAGGER)
    @action(detail=False, methods=["get"], url_path="download")
    def download(self, request):
        org_id = self.get_active_org_id()
        params = StoragePathQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        path = params.validated_data["path"]

        try:
            file_bytes = self.manager.download(org_id, path)
        except FileNotFoundError:
            raise NotFound({"path": f"File does not exist: {path}"})

        filename = path.rstrip("/").split("/")[-1] if path else "file"
        response = HttpResponse(file_bytes, content_type="application/octet-stream")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    @extend_schema(**STORAGE_UPLOAD_SWAGGER)
    @action(detail=False, methods=["post"], url_path="upload")
    @parser_classes([MultiPartParser])
    def upload(self, request):
        org_id = self.get_active_org_id()
        raw = (
            request.data.dict() if hasattr(request.data, "dict") else dict(request.data)
        )
        serializer = StorageUploadSerializer(
            data={**raw, "files": request.FILES.getlist("files")}
        )
        serializer.is_valid(raise_exception=True)
        path = serializer.validated_data["path"]
        files = serializer.validated_data["files"]

        try:
            results = [self.manager.upload_file(org_id, path, f) for f in files]
        except ValueError as e:
            raise ValidationError({"detail": str(e)})

        return Response(
            {"uploaded": [r.to_dict() for r in results]},
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(**STORAGE_DOWNLOAD_ZIP_SWAGGER)
    @action(detail=False, methods=["post"], url_path="download-zip")
    def download_zip(self, request):
        org_id = self.get_active_org_id()
        serializer = StorageDownloadZipSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        paths = serializer.validated_data["paths"]

        try:
            zip_filename, zip_chunks = self.manager.download_zip(org_id, paths)
            response = HttpResponse(
                b"".join(zip_chunks), content_type="application/zip"
            )
        except FileNotFoundError as e:
            raise ValidationError({"paths": str(e)})

        response["Content-Disposition"] = f'attachment; filename="{zip_filename}"'
        return response

    @extend_schema(**STORAGE_MKDIR_SWAGGER)
    @action(detail=False, methods=["post"], url_path="mkdir")
    def mkdir(self, request):
        org_id = self.get_active_org_id()
        serializer = StorageMkdirSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        path = serializer.validated_data["path"]

        try:
            self.manager.info(org_id, path)
            return Response(
                {"detail": f"Path already exists: {path}"},
                status=status.HTTP_409_CONFLICT,
            )
        except FileNotFoundError:
            pass
        except ValueError as e:
            raise ValidationError({"detail": str(e)})

        try:
            self.manager.mkdir(org_id, path)
        except ValueError as e:
            raise ValidationError({"detail": str(e)})
        return Response({"path": path, "created": True}, status=status.HTTP_201_CREATED)

    @extend_schema(**STORAGE_DELETE_SWAGGER)
    @action(detail=False, methods=["delete"], url_path="delete")
    def delete_file(self, request):
        org_id = self.get_active_org_id()
        serializer = StorageBulkDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        for path in serializer.validated_data["paths"]:
            self.manager.delete(org_id, path)

        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(**STORAGE_RENAME_SWAGGER)
    @action(detail=False, methods=["post"], url_path="rename")
    def rename(self, request):
        org_id = self.get_active_org_id()
        serializer = StorageRenameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from_path = serializer.validated_data["from"]
        to_path = serializer.validated_data["to"]

        try:
            self.manager.rename(org_id, from_path, to_path)
        except FileNotFoundError:
            raise ValidationError({"from": f"Source path does not exist: {from_path}"})
        except FileExistsError:
            raise ValidationError({"to": f"Destination already exists: {to_path}"})
        except ValueError as e:
            raise ValidationError({"detail": str(e)})

        return Response({"from": from_path, "to": to_path, "success": True})

    @extend_schema(**STORAGE_MOVE_SWAGGER)
    @action(detail=False, methods=["post"], url_path="move")
    def move(self, request):
        org_id = self.get_active_org_id()
        serializer = StorageMoveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from_path = serializer.validated_data["from"]
        to_path = serializer.validated_data["to"]
        src_org_id = serializer.validated_data.get("source_org_id")
        dst_org_id = serializer.validated_data.get("destination_org_id")

        try:
            if self._assert_cross_org_superadmin(request, src_org_id, dst_org_id):
                self.manager.move_cross_org(
                    int(src_org_id), from_path, int(dst_org_id), to_path
                )
            else:
                self.manager.move(org_id, from_path, to_path)
        except FileNotFoundError:
            raise ValidationError({"from": f"Source path does not exist: {from_path}"})
        except ValueError as e:
            raise ValidationError({"detail": str(e)})

        return Response({"from": from_path, "to": to_path, "success": True})

    @extend_schema(**STORAGE_COPY_SWAGGER)
    @action(detail=False, methods=["post"], url_path="copy")
    def copy(self, request):
        org_id = self.get_active_org_id()
        serializer = StorageCopySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from_path = serializer.validated_data["from"]
        to_path = serializer.validated_data["to"]
        src_org_id = serializer.validated_data.get("source_org_id")
        dst_org_id = serializer.validated_data.get("destination_org_id")

        try:
            if self._assert_cross_org_superadmin(request, src_org_id, dst_org_id):
                self.manager.copy_cross_org(
                    int(src_org_id), from_path, int(dst_org_id), to_path
                )
            else:
                self.manager.copy(org_id, from_path, to_path)
        except FileNotFoundError:
            raise ValidationError({"from": f"Source path does not exist: {from_path}"})
        except ValueError as e:
            raise ValidationError({"detail": str(e)})

        return Response({"from": from_path, "to": to_path, "success": True})

    @extend_schema(**STORAGE_ADD_TO_GRAPH_SWAGGER)
    @action(detail=False, methods=["post"], url_path="add-to-graph")
    def add_to_graph(self, request):
        org_id = self.get_active_org_id()
        serializer = StorageAddToGraphSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        paths = serializer.validated_data["paths"]
        requested_graph_ids = serializer.validated_data["graph_ids"]
        # Graphs must live in the active org. A cross-org or non-existent id is
        # rejected identically (no existence leak)
        graph_ids = list(
            Graph.objects.filter(id__in=requested_graph_ids, org_id=org_id).values_list(
                "id", flat=True
            )
        )
        missing = set(requested_graph_ids) - set(graph_ids)
        if missing:
            raise ValidationError({"graph_ids": f"Graphs not found: {sorted(missing)}"})

        results = []

        for path in paths:
            try:
                path_info = self.manager.info(org_id, path)
            except FileNotFoundError:
                raise ValidationError({"paths": f"Path does not exist: {path}"})

            if isinstance(path_info, FolderInfo) and not path.endswith("/"):
                path = path + "/"

            sf, _ = StorageFile.objects.get_or_create(org_id=org_id, path=path)

            for graph_id in graph_ids:
                obj, _ = GraphStorageFile.objects.get_or_create(
                    graph_id=graph_id, storage_file=sf
                )
                results.append(obj)

        return Response(
            GraphStorageFileSerializer(results, many=True).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(**STORAGE_REMOVE_FROM_GRAPH_SWAGGER)
    @action(detail=False, methods=["delete"], url_path="remove-from-graph")
    def remove_from_graph(self, request):
        org_id = self.get_active_org_id()
        serializer = StorageRemoveFromGraphSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        paths = serializer.validated_data["paths"]
        graph_ids = serializer.validated_data["graph_ids"]

        normalized_paths = {
            path for p in paths for path in (p, p.rstrip("/"), p.rstrip("/") + "/")
        }

        GraphStorageFile.objects.filter(
            graph_id__in=graph_ids,
            storage_file__path__in=normalized_paths,
            storage_file__org_id=org_id,
        ).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(**STORAGE_TREE_SWAGGER)
    @action(detail=False, methods=["get"], url_path="tree")
    def tree(self, request):
        org_id = self.get_active_org_id()
        params = StorageTreeQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        prefix = params.validated_data["path"]
        max_depth = params.validated_data.get("max_depth")

        if prefix:
            try:
                info = self.manager.info(org_id, prefix)
            except FileNotFoundError:
                raise NotFound({"path": f"Path does not exist: {prefix}"})

            if not isinstance(info, FolderInfo):
                raise ValidationError({"path": "tree requires a folder path"})

        root, truncated = self.manager.list_tree(org_id, prefix, max_depth=max_depth)
        return Response(
            {"path": prefix, "truncated": truncated, "tree": root.to_dict()}
        )

    @extend_schema(**STORAGE_GRAPH_FILES_SWAGGER)
    @action(detail=False, methods=["get"], url_path="graph-files")
    def graph_files(self, request):
        org_id = self.get_active_org_id()
        params = StorageGraphFilesQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        graph_id = params.validated_data["graph_id"]

        # Graph must live in the active org (404 otherwise — no existence leak).
        if not Graph.objects.filter(id=graph_id, org_id=org_id).exists():
            raise NotFound({"graph_id": f"Graph not found: {graph_id}"})

        qs = (
            GraphStorageFile.objects.filter(
                graph_id=graph_id, storage_file__org_id=org_id
            )
            .select_related("storage_file")
            .order_by("added_at")
        )
        return Response(GraphStorageFileSerializer(qs, many=True).data)

    @action(detail=False, methods=["get"], url_path="files")
    @swagger_auto_schema(**STORAGE_FILES_BY_IDS_SWAGGER)
    def files_by_ids(self, request):
        org_id = self.get_active_org_id()
        params = StorageFilesByIdsQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        qs = StorageFile.objects.filter(
            org_id=org_id, id__in=params.validated_data["ids"]
        )
        return Response(StorageFileSerializer(qs, many=True).data)

    @extend_schema(**STORAGE_SEARCH_SWAGGER)
    @action(detail=False, methods=["get"], url_path="search")
    def search(self, request):
        org_id = self.get_active_org_id()
        params = StorageSearchQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        results, total = self.manager.search(
            org_id,
            q=params.validated_data["q"],
            path=params.validated_data["path"],
            limit=params.validated_data["limit"],
            offset=params.validated_data["offset"],
        )
        return Response(
            {
                "total": total,
                "offset": params.validated_data["offset"],
                "limit": params.validated_data["limit"],
                "results": results,
            }
        )
