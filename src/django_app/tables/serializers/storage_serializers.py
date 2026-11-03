import os

from rbac.authorship import LastEditFieldsSerializerMixin
from rest_framework import serializers
from src.shared.epicstaff_storage.path_safety import sanitize_storage_path
from tables.serializers.recycle_bin_serializers import RecycleBinEntrySerializer
from tables.services.storage_service.path_utils import (
    TRASH_DIRECTORY,
    is_trash_path,
)
from tables.validators.file_upload_validator import FileValidator

_MAX_STORAGE_PATH_BYTES = 1000


def _normalize_path(value: str) -> str:
    if len(value.encode("utf-8")) > _MAX_STORAGE_PATH_BYTES:
        raise serializers.ValidationError(f"Path too long: max {_MAX_STORAGE_PATH_BYTES} bytes.")
    try:
        path = sanitize_storage_path(value, allow_empty=True, allow_leading_slash=True)
    except ValueError as exc:
        raise serializers.ValidationError(str(exc)) from exc
    if is_trash_path(path):
        raise serializers.ValidationError(f"'{TRASH_DIRECTORY}' is a reserved folder name.")
    return path


def _normalize_source_path(value: str) -> str:
    """A path an operation takes from: the org root itself can't be deleted, moved or copied."""
    path = _normalize_path(value)
    if not path:
        raise serializers.ValidationError("The storage root can't be used here.")
    return path


class StoragePathQuerySerializer(serializers.Serializer):
    path = serializers.CharField(
        required=False,
        default="",
        help_text="Storage path (e.g. `/` or `/reports/`)",
    )

    def validate_path(self, value: str) -> str:
        return _normalize_path(value)


class StorageMkdirSerializer(serializers.Serializer):
    path = serializers.CharField(
        required=True,
        help_text="Folder path to create",
    )

    def validate_path(self, value: str) -> str:
        return _normalize_path(value)


# Each path adds a clause to every usage query, so the endpoint caps them.
STORAGE_USAGE_MAX_PATHS = 500


class StorageBulkDeleteSerializer(serializers.Serializer):
    paths = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
        help_text="List of storage paths to delete",
    )

    def validate_paths(self, value: list[str]) -> list[str]:
        return [_normalize_source_path(path) for path in value]


class StorageUsageRequestSerializer(StorageBulkDeleteSerializer):
    paths = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
        max_length=STORAGE_USAGE_MAX_PATHS,
        help_text=f"Storage paths to check, at most {STORAGE_USAGE_MAX_PATHS}",
    )


class StorageUsageEntrySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class StorageUsageKindSerializer(serializers.Serializer):
    used = serializers.BooleanField(
        help_text="True when at least one live entry of this kind links to the paths"
    )
    items = StorageUsageEntrySerializer(
        many=True,
        help_text="Distinct entries ordered by name, then id; empty unless the caller can read this resource type",
    )


class StorageUsageResponseSerializer(serializers.Serializer):
    flows = StorageUsageKindSerializer()
    surfaces = StorageUsageKindSerializer()
    agents = StorageUsageKindSerializer()


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
        return _normalize_source_path(value)

    def validate_to_path(self, value: str) -> str:
        value = _normalize_path(value)
        if FileValidator().is_executable_filename(value):
            ext = os.path.splitext(value)[1].lower()
            raise serializers.ValidationError(
                f"Renaming to '{ext}' is not allowed: blocked executable extension."
            )
        return value


class _StorageTransferSerializer(serializers.Serializer):
    """Input of a move or copy: within the active organization, or across two of them.

    A cross-organization transfer names both organizations and they differ; a transfer
    within the active organization names neither. Anything in between is rejected rather
    than silently run in the active organization.
    """

    from_path = serializers.CharField(source="from", help_text="Source path")
    to_path = serializers.CharField(source="to", help_text="Destination path")
    source_org_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
        min_value=1,
        help_text=(
            "Source organization ID, for a cross-organization transfer only. "
            "Give it together with `destination_org_id`, or omit both."
        ),
    )
    destination_org_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
        min_value=1,
        help_text=(
            "Destination organization ID, for a cross-organization transfer only. "
            "Must differ from `source_org_id`; give both, or omit both."
        ),
    )

    def validate_from_path(self, value: str) -> str:
        return _normalize_source_path(value)

    def validate_to_path(self, value: str) -> str:
        return _normalize_path(value)

    def validate(self, attrs: dict) -> dict:
        source_org_id = attrs["source_org_id"]
        destination_org_id = attrs["destination_org_id"]
        if source_org_id is None and destination_org_id is not None:
            raise serializers.ValidationError(
                {"source_org_id": "Required with `destination_org_id`: give both or neither."}
            )
        if destination_org_id is None and source_org_id is not None:
            raise serializers.ValidationError(
                {"destination_org_id": "Required with `source_org_id`: give both or neither."}
            )
        if source_org_id is not None and source_org_id == destination_org_id:
            raise serializers.ValidationError(
                {
                    "destination_org_id": (
                        "Must differ from `source_org_id`. "
                        "Within one organization, omit both org ids."
                    )
                }
            )
        return attrs


class StorageMoveSerializer(_StorageTransferSerializer):
    pass


class StorageCopySerializer(_StorageTransferSerializer):
    pass


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


class AuthorshipResponseFieldsSerializer(LastEditFieldsSerializerMixin, serializers.Serializer):
    """Documents the author and last-edit fields of a storage entry, as every API renders them.

    Schema-only: the views render storage entries from StorageManager dicts.
    """

    created_by = serializers.PrimaryKeyRelatedField(
        read_only=True, help_text="The user who created the entry"
    )
    created_at = serializers.DateTimeField(
        allow_null=True,
        help_text="When the entry was created; null for tree folders without a row",
    )


class FileItemSerializer(AuthorshipResponseFieldsSerializer):
    id = serializers.IntegerField(allow_null=True, help_text="StorageFile id")
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


class StorageInfoResponseSerializer(AuthorshipResponseFieldsSerializer):
    id = serializers.IntegerField(allow_null=True, help_text="StorageFile id")
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


class StorageFromToResponseSerializer(serializers.Serializer):
    from_path = serializers.CharField(source="from", help_text="Source path")
    to_path = serializers.CharField(source="to", help_text="Destination path")
    success = serializers.BooleanField(help_text="Operation succeeded")


class StorageRecycleBinPurgedSerializer(serializers.Serializer):
    name = serializers.CharField(
        allow_null=True,
        help_text=(
            "Org-relative path of the purged recycle bin entry; a folder's ends in '/'. "
            "Null unless the caller has FILES:READ in the organization"
        ),
    )
    size = serializers.IntegerField(
        help_text="Bytes freed: a folder's counts everything deleted with it"
    )


class StorageTransferResponseSerializer(StorageFromToResponseSerializer):
    recycle_bin_purged = StorageRecycleBinPurgedSerializer(
        many=True,
        help_text=(
            "Recycle bin entries of the destination organization purged, oldest first, "
            "to make room for the copy; empty when it fit or nothing could be purged"
        ),
    )


class StorageMkdirResponseSerializer(serializers.Serializer):
    path = serializers.CharField(help_text="Created folder path")
    created = serializers.BooleanField(help_text="Whether the folder was created")


class StorageUploadLimitsResponseSerializer(serializers.Serializer):
    max_file_size = serializers.IntegerField(
        allow_null=True, help_text="Max bytes of one file; null = unlimited"
    )
    max_archive_size = serializers.IntegerField(help_text="Max compressed bytes of one archive")
    free_bytes = serializers.IntegerField(
        min_value=0, help_text="Bytes the organization may still upload"
    )
    archive_suffixes = serializers.ListField(
        child=serializers.CharField(),
        help_text="Lower-case suffixes (with the dot) of names uploaded as archives, sorted",
    )
    document_extensions = serializers.ListField(
        child=serializers.CharField(),
        help_text=(
            "Lower-case extensions (with the dot) that are never unpacked even when "
            "they match an archive suffix, sorted"
        ),
    )


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

    def validate_paths(self, value: list[str]) -> list[str]:
        return [_normalize_path(path) for path in value]


class StorageGraphFilesQuerySerializer(serializers.Serializer):
    graph_id = serializers.IntegerField(
        required=True,
        help_text="Graph ID to list attached files for",
    )


class StorageTreeQuerySerializer(serializers.Serializer):
    path = serializers.CharField(required=False, default="")
    max_depth = serializers.IntegerField(required=False, min_value=1, allow_null=True, default=None)

    def validate_path(self, value: str) -> str:
        return _normalize_path(value)


class TreeNodeSerializer(AuthorshipResponseFieldsSerializer):
    id = serializers.IntegerField(allow_null=True)
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
    limit = serializers.IntegerField(required=False, default=50, min_value=1, max_value=200)
    offset = serializers.IntegerField(required=False, default=0, min_value=0)

    def validate_path(self, value: str) -> str:
        return _normalize_path(value)


class StorageSearchResultSerializer(AuthorshipResponseFieldsSerializer):
    id = serializers.IntegerField()
    path = serializers.CharField()
    name = serializers.CharField()


class StorageSearchResponseSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    offset = serializers.IntegerField()
    limit = serializers.IntegerField()
    results = StorageSearchResultSerializer(many=True)


class StorageFilesByIdsQuerySerializer(serializers.Serializer):
    ids = serializers.CharField(
        required=True,
        help_text="Comma-separated list of StorageFile IDs (e.g. `1,2,3`)",
    )

    def validate_ids(self, value: str) -> list[int]:
        tokens = [token.strip() for token in value.split(",") if token.strip()]

        if not tokens:
            raise serializers.ValidationError("At least one id is required.")

        if not all(token.isdigit() for token in tokens):
            raise serializers.ValidationError("ids must be a comma-separated list of integers.")

        return [int(token) for token in tokens]


class StorageFileSerializer(LastEditFieldsSerializerMixin, serializers.Serializer):
    id = serializers.IntegerField(read_only=True, help_text="StorageFile id")
    path = serializers.CharField(read_only=True, help_text="Org-relative storage path")
    name = serializers.CharField(read_only=True, help_text="Last path segment")
    item_type = serializers.CharField(read_only=True, help_text="'file' or 'folder'")
    size = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="File size in bytes, null for folders",
    )
    s3_modified = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="Storage backend LastModified timestamp",
    )
    is_system = serializers.BooleanField(
        read_only=True, help_text="True for platform-written files"
    )
    # LastEditFieldsSerializerMixin swaps this for the author's user summary; the plain
    # id stays only when authorship is omitted.
    created_by = serializers.PrimaryKeyRelatedField(
        read_only=True, help_text="The user who created the entry"
    )
    parent_path = serializers.CharField(read_only=True, help_text="Immediate parent directory path")
    created_at = serializers.DateTimeField(read_only=True, help_text="Row creation timestamp")
    updated_at = serializers.DateTimeField(read_only=True, help_text="Row last update timestamp")


class StorageRecycleBinEntrySerializer(RecycleBinEntrySerializer):
    name = serializers.CharField(help_text="Full org-relative path; folders end in '/'")
    item_type = serializers.ChoiceField(choices=["file", "folder"])


class StorageRecycleBinPageSerializer(serializers.Serializer):
    """Response of GET /api/storage/recycle-bin/ (limit/offset paging)."""

    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = StorageRecycleBinEntrySerializer(many=True)
