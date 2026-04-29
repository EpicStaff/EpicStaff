from tables.serializers.storage_serializers import (
    GraphStorageFileSerializer,
    StorageAddToGraphSerializer,
    StorageBulkDeleteSerializer,
    StorageCopySerializer,
    StorageDownloadZipSerializer,
    StorageFromToResponseSerializer,
    StorageGraphFilesQuerySerializer,
    StorageInfoResponseSerializer,
    StorageListResponseSerializer,
    StorageMkdirResponseSerializer,
    StorageMkdirSerializer,
    StorageMoveSerializer,
    StoragePathQuerySerializer,
    StorageRemoveFromGraphSerializer,
    StorageRenameSerializer,
    StorageSearchQuerySerializer,
    StorageSearchResponseSerializer,
    StorageTreeQuerySerializer,
    StorageTreeResponseSerializer,
    StorageUploadResponseSerializer,
    StorageUploadSerializer,
)

STORAGE_LIST_SWAGGER = dict(
    operation_summary="List files and folders",
    operation_description=(
        "Returns the contents of a storage folder "
        "(files and subfolders with name, type, size, modified)."
    ),
    query_serializer=StoragePathQuerySerializer,
    responses={200: StorageListResponseSerializer, 404: "Path does not exist"},
)

STORAGE_INFO_SWAGGER = dict(
    operation_summary="Get file metadata",
    operation_description=(
        "Returns metadata for a single file "
        "(name, size, content_type, modified, created, etag)."
    ),
    query_serializer=StoragePathQuerySerializer,
    responses={200: StorageInfoResponseSerializer, 404: "File does not exist"},
)

STORAGE_DOWNLOAD_SWAGGER = dict(
    operation_summary="Download a file",
    operation_description=(
        "Downloads a single file by path. Returns the file content "
        "with appropriate Content-Disposition header."
    ),
    query_serializer=StoragePathQuerySerializer,
    responses={200: "File content as binary stream"},
)

STORAGE_UPLOAD_SWAGGER = dict(
    operation_summary="Upload files",
    operation_description=(
        "Upload one or more files to the specified path. Send as "
        "multipart/form-data with `files` (one or more files) and "
        "`path` (target folder). Archives (ZIP/TAR) are automatically "
        "extracted. Executable files are rejected."
    ),
    request_body=StorageUploadSerializer,
    responses={
        201: StorageUploadResponseSerializer,
        400: "Validation error (missing files or blocked extension)",
    },
)

STORAGE_DOWNLOAD_ZIP_SWAGGER = dict(
    operation_summary="Download multiple files as zip",
    operation_description=(
        "Accepts a list of file paths and returns them bundled "
        "in a single .zip archive."
    ),
    request_body=StorageDownloadZipSerializer,
    responses={200: "Zip file as binary stream"},
)

STORAGE_MKDIR_SWAGGER = dict(
    operation_summary="Create a folder",
    operation_description="Creates a new folder at the specified path.",
    request_body=StorageMkdirSerializer,
    responses={201: StorageMkdirResponseSerializer, 409: "Path already exists"},
)

STORAGE_DELETE_SWAGGER = dict(
    operation_summary="Bulk delete files or folders",
    operation_description="Deletes the files or folders at the specified paths.",
    request_body=StorageBulkDeleteSerializer,
    responses={204: "Deleted successfully"},
)

STORAGE_RENAME_SWAGGER = dict(
    operation_summary="Rename a file or folder",
    operation_description=(
        "Renames a file or folder from one path to another within the same directory."
    ),
    request_body=StorageRenameSerializer,
    responses={200: StorageFromToResponseSerializer},
)

STORAGE_MOVE_SWAGGER = dict(
    operation_summary="Move a file or folder",
    operation_description=(
        "Moves a file or folder from one location to another. "
        "To move across organizations, provide `source_org_id` and "
        "`destination_org_id` — the user must be a member of both orgs."
    ),
    request_body=StorageMoveSerializer,
    responses={200: StorageFromToResponseSerializer},
)

STORAGE_COPY_SWAGGER = dict(
    operation_summary="Copy a file or folder",
    operation_description=(
        "Creates a copy of a file or folder at the destination path. "
        "To copy across organizations, provide `source_org_id` and "
        "`destination_org_id` — the user must be a member of both orgs."
    ),
    request_body=StorageCopySerializer,
    responses={200: StorageFromToResponseSerializer},
)

STORAGE_ADD_TO_GRAPH_SWAGGER = dict(
    operation_summary="Add a storage file reference to graphs",
    operation_description=(
        "Creates database references linking one or more storage files or folders to one or more graphs."
    ),
    request_body=StorageAddToGraphSerializer,
    responses={
        201: GraphStorageFileSerializer(many=True),
        400: "Validation error (invalid graph IDs or non-existing paths)",
    },
)

STORAGE_REMOVE_FROM_GRAPH_SWAGGER = dict(
    operation_summary="Remove a storage file reference from graphs",
    operation_description="Removes the database links between one or more storage paths and the given graphs.",
    request_body=StorageRemoveFromGraphSerializer,
    responses={204: "Removed successfully"},
)

STORAGE_GRAPH_FILES_SWAGGER = dict(
    operation_summary="List storage files attached to a graph",
    operation_description="Returns all storage paths that have been linked to the given graph.",
    query_serializer=StorageGraphFilesQuerySerializer,
    responses={200: GraphStorageFileSerializer(many=True), 404: "Graph not found"},
)

STORAGE_TREE_SWAGGER = dict(
    operation_summary="Get recursive folder tree",
    operation_description=(
        "Returns the entire folder subtree under `path` as a nested "
        "structure. Each folder has a `children` array; files have "
        "`children: null`. Response is truncated at 50 000 entries."
    ),
    query_serializer=StorageTreeQuerySerializer,
    responses={200: StorageTreeResponseSerializer, 404: "Path does not exist"},
)

STORAGE_SEARCH_SWAGGER = dict(
    operation_summary="Search files by name",
    operation_description=(
        "Substring match on the filename (last path segment). "
        "Optional `path` narrows results to a subtree. Files only."
    ),
    query_serializer=StorageSearchQuerySerializer,
    responses={200: StorageSearchResponseSerializer},
)
