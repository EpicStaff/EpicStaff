from drf_spectacular.utils import OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

from tables.serializers.storage_serializers import (
    GraphStorageFileSerializer,
    StorageAddToGraphSerializer,
    StorageBulkDeleteSerializer,
    StorageCopySerializer,
    StorageDownloadZipSerializer,
    StorageFromToResponseSerializer,
    StorageInfoResponseSerializer,
    StorageListResponseSerializer,
    StorageMkdirResponseSerializer,
    StorageMkdirSerializer,
    StorageMoveSerializer,
    StorageRemoveFromGraphSerializer,
    StorageRenameSerializer,
    StorageSearchResponseSerializer,
    StorageTreeResponseSerializer,
    StorageUploadResponseSerializer,
    StorageUploadSerializer,
)

_STORAGE_PATH_PARAM = OpenApiParameter(
    name="path",
    location=OpenApiParameter.QUERY,
    description="Storage path (e.g. `/` or `/reports/`)",
    type=OpenApiTypes.STR,
    required=False,
    default="",
)

STORAGE_LIST_SWAGGER = dict(
    summary="List files and folders",
    description=(
        "Returns the contents of a storage folder "
        "(files and subfolders with name, type, size, modified)."
    ),
    parameters=[_STORAGE_PATH_PARAM],
    responses={
        200: StorageListResponseSerializer,
        404: OpenApiResponse(description="Path does not exist"),
    },
)

STORAGE_INFO_SWAGGER = dict(
    summary="Get file metadata",
    description=(
        "Returns metadata for a single file "
        "(name, size, content_type, modified, created, etag)."
    ),
    parameters=[_STORAGE_PATH_PARAM],
    responses={
        200: StorageInfoResponseSerializer,
        404: OpenApiResponse(description="File does not exist"),
    },
)

STORAGE_DOWNLOAD_SWAGGER = dict(
    summary="Download a file",
    description=(
        "Downloads a single file by path. Returns the file content "
        "with appropriate Content-Disposition header."
    ),
    parameters=[_STORAGE_PATH_PARAM],
    responses={200: OpenApiResponse(description="File content as binary stream")},
)

STORAGE_UPLOAD_SWAGGER = dict(
    summary="Upload files",
    description=(
        "Upload one or more files to the specified path. Send as "
        "multipart/form-data with `files` (one or more files) and "
        "`path` (target folder). Archives (ZIP/TAR) are automatically "
        "extracted. Executable files are rejected."
    ),
    request=StorageUploadSerializer,
    responses={
        201: StorageUploadResponseSerializer,
        400: OpenApiResponse(
            description="Validation error (missing files or blocked extension)"
        ),
    },
)

STORAGE_DOWNLOAD_ZIP_SWAGGER = dict(
    summary="Download multiple files as zip",
    description=(
        "Accepts a list of file paths and returns them bundled "
        "in a single .zip archive."
    ),
    request=StorageDownloadZipSerializer,
    responses={200: OpenApiResponse(description="Zip file as binary stream")},
)

STORAGE_MKDIR_SWAGGER = dict(
    summary="Create a folder",
    description="Creates a new folder at the specified path.",
    request=StorageMkdirSerializer,
    responses={
        201: StorageMkdirResponseSerializer,
        409: OpenApiResponse(description="Path already exists"),
    },
)

STORAGE_DELETE_SWAGGER = dict(
    summary="Bulk delete files or folders",
    description="Deletes the files or folders at the specified paths.",
    request=StorageBulkDeleteSerializer,
    responses={204: OpenApiResponse(description="Deleted successfully")},
)

STORAGE_RENAME_SWAGGER = dict(
    summary="Rename a file or folder",
    description=(
        "Renames a file or folder from one path to another within the same directory."
    ),
    request=StorageRenameSerializer,
    responses={200: StorageFromToResponseSerializer},
)

STORAGE_MOVE_SWAGGER = dict(
    summary="Move a file or folder",
    description=(
        "Moves a file or folder from one location to another. "
        "To move across organizations, provide `source_org_id` and "
        "`destination_org_id` — the user must be a member of both orgs."
    ),
    request=StorageMoveSerializer,
    responses={200: StorageFromToResponseSerializer},
)

STORAGE_COPY_SWAGGER = dict(
    summary="Copy a file or folder",
    description=(
        "Creates a copy of a file or folder at the destination path. "
        "To copy across organizations, provide `source_org_id` and "
        "`destination_org_id` — the user must be a member of both orgs."
    ),
    request=StorageCopySerializer,
    responses={200: StorageFromToResponseSerializer},
)

STORAGE_ADD_TO_GRAPH_SWAGGER = dict(
    summary="Add a storage file reference to graphs",
    description=(
        "Creates database references linking one or more storage files or folders to one or more graphs."
    ),
    request=StorageAddToGraphSerializer,
    responses={
        201: GraphStorageFileSerializer(many=True),
        400: OpenApiResponse(
            description="Validation error (invalid graph IDs or non-existing paths)"
        ),
    },
)

STORAGE_REMOVE_FROM_GRAPH_SWAGGER = dict(
    summary="Remove a storage file reference from graphs",
    description="Removes the database links between one or more storage paths and the given graphs.",
    request=StorageRemoveFromGraphSerializer,
    responses={204: OpenApiResponse(description="Removed successfully")},
)

STORAGE_GRAPH_FILES_SWAGGER = dict(
    summary="List storage files attached to a graph",
    description="Returns all storage paths that have been linked to the given graph.",
    parameters=[
        OpenApiParameter(
            name="graph_id",
            location=OpenApiParameter.QUERY,
            description="Graph ID to list attached files for",
            type=OpenApiTypes.INT,
            required=True,
        ),
    ],
    responses={
        200: GraphStorageFileSerializer(many=True),
        404: OpenApiResponse(description="Graph not found"),
    },
)

STORAGE_TREE_SWAGGER = dict(
    summary="Get recursive folder tree",
    description=(
        "Returns the entire folder subtree under `path` as a nested "
        "structure. Each folder has a `children` array; files have "
        "`children: null`. Response is truncated at 50 000 entries."
    ),
    parameters=[
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
    responses={
        200: StorageTreeResponseSerializer,
        404: OpenApiResponse(description="Path does not exist"),
    },
)

STORAGE_SEARCH_SWAGGER = dict(
    summary="Search files by name",
    description=(
        "Substring match on the filename (last path segment). "
        "Optional `path` narrows results to a subtree. Files only."
    ),
    parameters=[
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
    responses={200: StorageSearchResponseSerializer},
)
