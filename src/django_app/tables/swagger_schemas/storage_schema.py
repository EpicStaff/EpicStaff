from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse

from tables.serializers.storage_serializers import (
    GraphStorageFileSerializer,
    StorageAddToGraphSerializer,
    StorageBulkDeleteSerializer,
    StorageCopySerializer,
    StorageDownloadZipSerializer,
    StorageFileSerializer,
    StorageFromToResponseSerializer,
    StorageInfoResponseSerializer,
    StorageListResponseSerializer,
    StorageMkdirResponseSerializer,
    StorageMkdirSerializer,
    StorageMoveSerializer,
    StorageRemoveFromGraphSerializer,
    StorageRenameSerializer,
    StorageSearchResponseSerializer,
    StorageTransferResponseSerializer,
    StorageTreeResponseSerializer,
    StorageUploadLimitsResponseSerializer,
    StorageUsageRequestSerializer,
    StorageUsageResponseSerializer,
)

_STORAGE_PATH_PARAM = OpenApiParameter(
    name="path",
    location=OpenApiParameter.QUERY,
    description="Storage path (e.g. `/` or `/reports/`)",
    type=OpenApiTypes.STR,
    required=False,
    default="",
)

STORAGE_LIST_SWAGGER = {
    "summary": "List files and folders",
    "description": (
        "Returns the contents of a storage folder "
        "(files and subfolders with name, type, size, modified)."
    ),
    "parameters": [_STORAGE_PATH_PARAM],
    "responses": {
        200: StorageListResponseSerializer,
        404: OpenApiResponse(description="Path does not exist"),
    },
}

STORAGE_INFO_SWAGGER = {
    "summary": "Get file metadata",
    "description": (
        "Returns metadata for a single file (name, size, content_type, modified, created, etag) "
        "and `graphs`, the flows using it by id and name. `graphs` is empty when the caller "
        "lacks READ on flows."
    ),
    "parameters": [_STORAGE_PATH_PARAM],
    "responses": {
        200: StorageInfoResponseSerializer,
        404: OpenApiResponse(description="File does not exist"),
    },
}

STORAGE_DOWNLOAD_SWAGGER = {
    "summary": "Download a file",
    "description": (
        "Downloads a single file by path. Returns the file content "
        "with appropriate Content-Disposition header. A single "
        "`Range: bytes=first-[last]` header returns only that part (206)."
    ),
    "parameters": [_STORAGE_PATH_PARAM],
    "responses": {
        200: OpenApiResponse(description="File content as binary stream"),
        206: OpenApiResponse(description="The requested byte range, with Content-Range"),
        416: OpenApiResponse(description="Range starts past the end of the file"),
    },
}

STORAGE_DOWNLOAD_ZIP_SWAGGER = {
    "summary": "Download multiple files as zip",
    "description": (
        "Accepts a list of file paths and returns them bundled in a single .zip archive."
    ),
    "request": StorageDownloadZipSerializer,
    "responses": {200: OpenApiResponse(description="Zip file as binary stream")},
}

STORAGE_MKDIR_SWAGGER = {
    "summary": "Create a folder",
    "description": "Creates a new folder at the specified path.",
    "request": StorageMkdirSerializer,
    "responses": {
        201: StorageMkdirResponseSerializer,
        409: OpenApiResponse(description="Path already exists"),
    },
}

STORAGE_DELETE_SWAGGER = {
    "summary": "Bulk delete files or folders",
    "description": "Deletes the files or folders at the specified paths.",
    "request": StorageBulkDeleteSerializer,
    "responses": {204: OpenApiResponse(description="Deleted successfully")},
}

STORAGE_USAGE_SWAGGER = {
    "summary": "Preview what deleting files or folders would unlink",
    "description": (
        "Read-only check to call before a delete. Deleting a file or folder permanently "
        "removes the links pointing at it, and a restore does not bring them back. For the "
        "given paths this reports the live flows, surfaces and agents that hold such a link, "
        "using the same lookup as the delete: a path naming a live file means that file, any "
        "other path means the folder and everything under it. A path with nothing live at it "
        "contributes nothing, so it is not an error. Flows are those attached to the files "
        "and those with a live node whose inline surface is linked to them; agents are those "
        "running such a node. "
        "For each kind, `used` is always true when a link exists, whatever the caller may "
        "read, so nobody destroys links unwarned. `items` lists the distinct entries "
        "ordered by name, then id, only when the caller holds READ on that resource type "
        "(flows, surfaces or agents) in the active organization; otherwise it is empty. "
        "Needs FILES:READ."
    ),
    "request": StorageUsageRequestSerializer,
    "responses": {200: StorageUsageResponseSerializer},
}

STORAGE_RENAME_SWAGGER = {
    "summary": "Rename a file or folder",
    "description": ("Renames a file or folder from one path to another within the same directory."),
    "request": StorageRenameSerializer,
    "responses": {200: StorageFromToResponseSerializer},
}

STORAGE_MOVE_SWAGGER = {
    "summary": "Move a file or folder",
    "description": (
        "Moves a file or folder from one location to another. "
        "To move across organizations, provide both `source_org_id` and "
        "`destination_org_id`, two different organizations; this requires a superadmin. "
        "Within the active organization, omit both. Giving only one of them, or the same "
        "organization twice, is a 400. "
        "A move across organizations that doesn't fit the destination's storage quota "
        "first purges the destination's oldest storage recycle bin entries, just enough "
        "of them, and lists them in `recycle_bin_purged` (always empty within one "
        "organization); if the whole bin isn't enough, nothing is purged and it's a 413. "
        "Only a user session (not an API key) holding FILES:DELETE in the destination "
        "may cause a purge; for anyone else the bin counts as used and it's a 413. "
        "An entry's `name` is null unless the caller has FILES:READ there. "
        "The purge commits with the copy, so if removing the source then fails, "
        "the request fails but the entries stay purged."
    ),
    "request": StorageMoveSerializer,
    "responses": {200: StorageTransferResponseSerializer},
}

STORAGE_COPY_SWAGGER = {
    "summary": "Copy a file or folder",
    "description": (
        "Creates a copy of a file or folder at the destination path. "
        "To copy across organizations, provide both `source_org_id` and "
        "`destination_org_id`, two different organizations; this requires a superadmin. "
        "Within the active organization, omit both. Giving only one of them, or the same "
        "organization twice, is a 400. "
        "A copy that doesn't fit the destination's storage quota first purges the "
        "destination's oldest storage recycle bin entries, just enough of them, and lists "
        "them in `recycle_bin_purged`; if the whole bin isn't enough, nothing is purged "
        "and it's a 413. "
        "Only a user session (not an API key) holding FILES:DELETE in the destination "
        "may cause a purge; for anyone else the bin counts as used and it's a 413. "
        "An entry's `name` is null unless the caller has FILES:READ there."
    ),
    "request": StorageCopySerializer,
    "responses": {200: StorageTransferResponseSerializer},
}

STORAGE_ADD_TO_GRAPH_SWAGGER = {
    "summary": "Add a storage file reference to graphs",
    "description": (
        "Creates database references linking one or more storage files or folders to one or more graphs."
    ),
    "request": StorageAddToGraphSerializer,
    "responses": {
        201: GraphStorageFileSerializer(many=True),
        400: OpenApiResponse(
            description="Validation error (invalid graph IDs or non-existing paths)"
        ),
    },
}

STORAGE_REMOVE_FROM_GRAPH_SWAGGER = {
    "summary": "Remove a storage file reference from graphs",
    "description": "Removes the database links between one or more storage paths and the given graphs.",
    "request": StorageRemoveFromGraphSerializer,
    "responses": {204: OpenApiResponse(description="Removed successfully")},
}

STORAGE_GRAPH_FILES_SWAGGER = {
    "summary": "List storage files attached to a graph",
    "description": "Returns all storage paths that have been linked to the given graph.",
    "parameters": [
        OpenApiParameter(
            name="graph_id",
            location=OpenApiParameter.QUERY,
            description="Graph ID to list attached files for",
            type=OpenApiTypes.INT,
            required=True,
        ),
    ],
    "responses": {
        200: GraphStorageFileSerializer(many=True),
        404: OpenApiResponse(description="Graph not found"),
    },
}

STORAGE_TREE_SWAGGER = {
    "summary": "Get recursive folder tree",
    "description": (
        "Returns the entire folder subtree under `path` as a nested "
        "structure. Each folder has a `children` array; files have "
        "`children: null`. Response is truncated at 50 000 entries."
    ),
    "parameters": [
        OpenApiParameter(
            name="path",
            location=OpenApiParameter.QUERY,
            type=OpenApiTypes.STR,
            required=False,
            default="",
        ),
        OpenApiParameter(
            name="max_depth",
            location=OpenApiParameter.QUERY,
            type=OpenApiTypes.INT,
            required=False,
            default=None,
        ),
    ],
    "responses": {
        200: StorageTreeResponseSerializer,
        404: OpenApiResponse(description="Path does not exist"),
    },
}

STORAGE_FILES_BY_IDS_SWAGGER = {
    "summary": "Bulk fetch storage files by id",
    "description": (
        "Returns StorageFile records for the given comma-separated `ids`. "
        "IDs that are missing or belong to another organization are silently omitted."
    ),
    "parameters": [
        OpenApiParameter(
            name="ids",
            location=OpenApiParameter.QUERY,
            description="Comma-separated list of storage file IDs",
            type=OpenApiTypes.STR,
            required=True,
        ),
    ],
    "responses": {
        200: StorageFileSerializer(many=True),
        400: OpenApiResponse(description="Invalid or empty ids"),
    },
}

STORAGE_SEARCH_SWAGGER = {
    "summary": "Search files by name",
    "description": (
        "Substring match on the filename (last path segment). "
        "Optional `path` narrows results to a subtree. Files only."
    ),
    "parameters": [
        OpenApiParameter(
            name="q",
            location=OpenApiParameter.QUERY,
            type=OpenApiTypes.STR,
            required=True,
        ),
        OpenApiParameter(
            name="path",
            location=OpenApiParameter.QUERY,
            type=OpenApiTypes.STR,
            required=False,
            default="",
        ),
        OpenApiParameter(
            name="limit",
            location=OpenApiParameter.QUERY,
            type=OpenApiTypes.INT,
            required=False,
            default=50,
        ),
        OpenApiParameter(
            name="offset",
            location=OpenApiParameter.QUERY,
            type=OpenApiTypes.INT,
            required=False,
            default=0,
        ),
    ],
    "responses": {200: StorageSearchResponseSerializer},
}

STORAGE_UPLOAD_LIMITS_SWAGGER = {
    "summary": "Get upload limits",
    "description": (
        "Returns the limits the streaming upload enforces, so a client can reject an "
        "oversize file before sending it. Sizes are in bytes: `max_file_size` caps one "
        "plain file (null means unlimited) and `max_archive_size` one compressed "
        "archive (always set). `free_bytes` is what the active organization may still "
        "upload; it ignores uploads still in flight and does not credit a file the "
        "upload would overwrite, and it shrinks as files are added, so read it again "
        "before each batch. Files in the recycle bin count against it, but an upload "
        "that doesn't fit purges the oldest storage bin entries first when the caller "
        "may purge (a user session with FILES:DELETE), so more may fit. A file name is "
        "uploaded as an archive (and capped by `max_archive_size`) iff its lower-cased "
        "name ends with one of `archive_suffixes` and with none of `document_extensions`; "
        "both lists are lower-case, include the leading dot and are sorted. "
        "Needs FILES:READ."
    ),
    "responses": {200: StorageUploadLimitsResponseSerializer},
}
