import os
import re

from rest_framework import serializers

from tables.models import Graph
from tables.validators.file_upload_validator import FileValidator


_MAX_STORAGE_PATH_BYTES = 1000


def _normalize_path(value: str) -> str:
    if not value:
        return value
    value = re.sub(r"/+", "/", value)
    value = value.rstrip("/")
    if len(value.encode("utf-8")) > _MAX_STORAGE_PATH_BYTES:
        raise serializers.ValidationError(
            f"Path too long: max {_MAX_STORAGE_PATH_BYTES} bytes."
        )
    return value


class StoragePathQuerySerializer(serializers.Serializer):
    path = serializers.CharField(
        required=False,
        default="",
        help_text="Storage path (e.g. `/` or `/reports/`)",
    )

    def validate_path(self, value: str) -> str:
        return _normalize_path(value)


class StorageUploadSerializer(serializers.Serializer):
    path = serializers.CharField(
        required=False,
        default="",
        help_text="Target folder path",
    )
    files = serializers.ListField(
        child=serializers.FileField(),
        allow_empty=False,
        help_text="Files to upload",
    )

    def validate_path(self, value: str) -> str:
        return _normalize_path(value)

    def validate_files(self, value):
        return FileValidator().validate(value)


class StorageMkdirSerializer(serializers.Serializer):
    path = serializers.CharField(
        required=True,
        help_text="Folder path to create",
    )

    def validate_path(self, value: str) -> str:
        return _normalize_path(value)


class StorageBulkDeleteSerializer(serializers.Serializer):
    paths = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
        help_text="List of storage paths to delete",
    )

    def validate_paths(self, value: list[str]) -> list[str]:
        return [_normalize_path(path) for path in value]


class StorageDownloadZipSerializer(serializers.Serializer):
    paths = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=False,
        help_text="List of file paths to include in the zip",
    )

    def validate_paths(self, value: list[str]) -> list[str]:
        return [_normalize_path(path) for path in value]


class StorageRenameSerializer(serializers.Serializer):
    from_path = serializers.CharField(source="from", help_text="Source path")
    to_path = serializers.CharField(source="to", help_text="Destination path")

    def validate_from_path(self, value: str) -> str:
        return _normalize_path(value)

    def validate_to_path(self, value: str) -> str:
        value = _normalize_path(value)
        if FileValidator().is_executable_filename(value):
            ext = os.path.splitext(value)[1].lower()
            raise serializers.ValidationError(
                f"Renaming to '{ext}' is not allowed: blocked executable extension."
            )
        return value


class StorageMoveSerializer(serializers.Serializer):
    from_path = serializers.CharField(source="from", help_text="Source path")
    to_path = serializers.CharField(source="to", help_text="Destination path")
    source_org_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Source organization ID (cross-org move)",
    )
    destination_org_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Destination organization ID (cross-org move)",
    )

    def validate_from_path(self, value: str) -> str:
        return _normalize_path(value)

    def validate_to_path(self, value: str) -> str:
        return _normalize_path(value)


class StorageCopySerializer(serializers.Serializer):
    from_path = serializers.CharField(source="from", help_text="Source path")
    to_path = serializers.CharField(source="to", help_text="Destination path")
    source_org_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Source organization ID (cross-org copy)",
    )
    destination_org_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Destination organization ID (cross-org copy)",
    )

    def validate_from_path(self, value: str) -> str:
        return _normalize_path(value)

    def validate_to_path(self, value: str) -> str:
        return _normalize_path(value)


class StorageAddToGraphSerializer(serializers.Serializer):
    paths = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=False,
        help_text="Storage paths to link",
    )
    graph_ids = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False,
        help_text="Target graph IDs",
    )

    def validate_paths(self, value: list[str]) -> list[str]:
        return [_normalize_path(path) for path in value]

    def validate_graph_ids(self, value: list[int]) -> list[int]:
        existing = set(Graph.objects.filter(id__in=value).values_list("id", flat=True))
        missing = [gid for gid in value if gid not in existing]

        if missing:
            raise serializers.ValidationError(f"Graphs not found: {missing}")

        return value


class FileItemSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="File or folder name")
    type = serializers.ChoiceField(
        choices=["file", "folder"],
        help_text="Item type",
    )
    size = serializers.IntegerField(
        required=False,
        help_text="File size in bytes (files only)",
    )
    modified = serializers.DateTimeField(
        required=False,
        help_text="Last modified timestamp",
    )
    is_empty = serializers.BooleanField(
        help_text="True if the folder has no children. Always False for files.",
    )


class StorageListResponseSerializer(serializers.Serializer):
    path = serializers.CharField(help_text="Requested path")
    items = FileItemSerializer(many=True, help_text="Folder contents")


class StorageInfoResponseSerializer(serializers.Serializer):
    path = serializers.CharField(help_text="File path")
    name = serializers.CharField(help_text="File name")
    type = serializers.CharField(help_text="Item type")
    size = serializers.IntegerField(help_text="File size in bytes")
    modified = serializers.DateTimeField(help_text="Last modified timestamp")
    created = serializers.DateTimeField(required=False, help_text="Creation timestamp")
    content_type = serializers.CharField(required=False, help_text="MIME content type")
    etag = serializers.CharField(required=False, help_text="Entity tag")
    graphs = serializers.ListField(
        child=serializers.CharField(),
        help_text="List of all graph names",
    )


class StorageUploadResultSerializer(serializers.Serializer):
    type = serializers.ChoiceField(
        choices=["file", "archive"],
        help_text="Whether the file was uploaded as-is or extracted as an archive",
    )
    path = serializers.CharField(
        required=False,
        help_text="Relative path (regular files only)",
    )
    size = serializers.IntegerField(
        required=False,
        help_text="File size in bytes (regular files only)",
    )
    extracted = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Extracted file paths (archives only)",
    )


class StorageUploadResponseSerializer(serializers.Serializer):
    uploaded = StorageUploadResultSerializer(
        many=True,
        help_text="Results for each uploaded file",
    )


class StorageFromToResponseSerializer(serializers.Serializer):
    from_path = serializers.CharField(source="from", help_text="Source path")
    to_path = serializers.CharField(source="to", help_text="Destination path")
    success = serializers.BooleanField(help_text="Operation succeeded")


class StorageMkdirResponseSerializer(serializers.Serializer):
    path = serializers.CharField(help_text="Created folder path")
    created = serializers.BooleanField(help_text="Whether the folder was created")


class GraphStorageFileSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    graph_id = serializers.IntegerField(read_only=True)
    path = serializers.CharField(source="storage_file.path", read_only=True)
    added_at = serializers.DateTimeField(read_only=True)


class SessionOutputFileSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="storage_file.id", read_only=True)
    path = serializers.CharField(source="storage_file.path", read_only=True)
    name = serializers.SerializerMethodField()
    added_at = serializers.DateTimeField(read_only=True)

    def get_name(self, obj):
        return obj.storage_file.path.rsplit("/", 1)[-1]


class StorageRemoveFromGraphSerializer(serializers.Serializer):
    paths = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=False,
        help_text="Storage paths to unlink",
    )
    graph_ids = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False,
        help_text="Graph IDs to unlink from",
    )


class StorageGraphFilesQuerySerializer(serializers.Serializer):
    graph_id = serializers.IntegerField(
        required=True,
        help_text="Graph ID to list attached files for",
    )


class StorageTreeQuerySerializer(serializers.Serializer):
    path = serializers.CharField(required=False, default="")
    max_depth = serializers.IntegerField(
        required=False, min_value=1, allow_null=True, default=None
    )

    def validate_path(self, value: str) -> str:
        return _normalize_path(value)


class TreeNodeSerializer(serializers.Serializer):
    name = serializers.CharField()
    path = serializers.CharField()
    type = serializers.ChoiceField(choices=["file", "folder"])
    size = serializers.IntegerField()
    modified = serializers.CharField(allow_null=True)
    children = serializers.ListField(
        child=serializers.DictField(),
        allow_null=True,
        required=False,
        help_text="Nested TreeNode objects; null for files.",
    )


class StorageTreeResponseSerializer(serializers.Serializer):
    path = serializers.CharField()
    truncated = serializers.BooleanField()
    tree = TreeNodeSerializer()


class StorageSearchQuerySerializer(serializers.Serializer):
    q = serializers.CharField(min_length=2, max_length=100)
    path = serializers.CharField(required=False, default="")
    limit = serializers.IntegerField(
        required=False, default=50, min_value=1, max_value=200
    )
    offset = serializers.IntegerField(required=False, default=0, min_value=0)

    def validate_path(self, value: str) -> str:
        return _normalize_path(value)


class StorageSearchResultSerializer(serializers.Serializer):
    path = serializers.CharField()
    name = serializers.CharField()


class StorageSearchResponseSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    offset = serializers.IntegerField()
    limit = serializers.IntegerField()
    results = StorageSearchResultSerializer(many=True)
