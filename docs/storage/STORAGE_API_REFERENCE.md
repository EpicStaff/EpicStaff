# Storage API Reference

## Complete API Endpoint Documentation

This document provides a comprehensive reference for all storage-related API endpoints with request/response examples.

Base path: `/api/storage/`

---

## Authentication & organization scoping

All storage endpoints require authentication and the `X-Organization-Id` header
identifying the **active organization** (see `rbac/roles_and_permissions.md` and
`rbac/organization_scoping.md`). Files are stored and served **per organization** —
every operation acts only on the active org's files (internally keyed by
`org_{id}/…`; the path never contains a user identifier).

Access is gated by the caller's **FILES** permission in the active org:

| Permission | Endpoints |
|---|---|
| `READ` | list, tree, search, info, download, graph-files, upload-limits |
| `EXPORT` | download-zip |
| `CREATE` | upload, mkdir, add-to-graph |
| `UPDATE` | rename, move, copy |
| `DELETE` | delete, remove-from-graph |

A caller lacking the required permission gets `403`. Built-in role grants:
Org Admin = C R U D E; Member = C R U E; Viewer = R.

**Cross-org file transfer** — `move` / `copy` with
`source_org_id != destination_org_id` — is **superadmin-only**; any other caller
gets `403`. Such a request must still send the `X-Organization-Id` header (any org
the caller can resolve); the active org is otherwise unused for the transfer.

**Graph references are org-scoped.** `add-to-graph` links files only to graphs in the
active org, and `graph-files` serves only an active-org graph — a graph id from
another org (or a non-existent one) is rejected exactly like a missing id, with no
existence leak.

---

## Table of Contents

1. [List Files](#list-files)
2. [Folder Tree](#folder-tree)
3. [Search Files](#search-files)
4. [File Info](#file-info)
5. [Download File](#download-file)
6. [Upload Limits](#upload-limits)
7. [Upload Files](#upload-files)
8. [Download ZIP](#download-zip)
9. [Create Folder](#create-folder)
10. [Bulk Delete](#bulk-delete)
11. [Rename](#rename)
12. [Move](#move)
13. [Copy](#copy)
14. [Add to Graph](#add-to-graph)
15. [Remove from Graph](#remove-from-graph)
16. [Graph Files](#graph-files)
17. [Session Output Files](#session-output-files)
18. [Blocked Extensions Reference](#blocked-extensions-reference)
19. [Archive Format Reference](#archive-format-reference)
20. [Path Normalization](#path-normalization)
21. [HTTP Status Codes](#http-status-codes)

---

## List Files

**GET** `/api/storage/list/`

Lists files and folders at the given path.

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | string | No | `""` | Directory path to list |

**Response:** `200 OK`
```json
{
    "path": "reports",
    "items": [
        {"name": "Q1-summary.pdf", "type": "file", "size": 102400, "modified": "2026-04-15T10:30:00Z", "is_empty": false},
        {"name": "charts", "type": "folder", "size": 0, "modified": null, "is_empty": true}
    ]
}
```

**Error:** `404 Not Found`
```json
{"path": "Path does not exist: nonexistent/folder"}
```

**Item fields:**

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | File or folder name |
| `type` | string | `"file"` or `"folder"` |
| `size` | integer | Size in bytes; `0` for folders |
| `modified` | string \| null | ISO 8601 timestamp; `null` for empty folders |
| `is_empty` | boolean | Always present. `true` if the folder has no children; always `false` for files |

---

## Folder Tree

**GET** `/api/storage/tree/`

Returns the entire folder subtree under `path` as a nested structure. One paginated S3 `list_objects_v2` call (no delimiter) powers the whole response — much faster than N calls to `/list/`. Files only appear as leaf nodes with `children: null`; folders carry a `children` array (possibly empty).

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | string | No | `""` | Root path for the subtree. Empty = org root. |
| `max_depth` | integer | No | unlimited | Max levels to return, counted **from** `path` (not from the org root). Must be ≥ 1. |

**Response:** `200 OK`
```json
{
    "path": "reports",
    "truncated": false,
    "tree": {
        "name": "reports",
        "path": "reports/",
        "type": "folder",
        "size": 0,
        "modified": null,
        "children": [
            {
                "name": "2025",
                "path": "reports/2025/",
                "type": "folder",
                "size": 0,
                "modified": null,
                "children": [
                    {
                        "name": "q1.pdf",
                        "path": "reports/2025/q1.pdf",
                        "type": "file",
                        "size": 102400,
                        "modified": "2026-04-15T10:30:00Z",
                        "children": null
                    }
                ]
            },
            {
                "name": "empty_folder",
                "path": "reports/empty_folder/",
                "type": "folder",
                "size": 0,
                "modified": null,
                "children": []
            }
        ]
    }
}
```

**Field notes:**

| Field | Description |
|-------|-------------|
| `path` (top-level) | The requested path, unchanged |
| `truncated` | `true` if the hard cap of **50 000 entries** was hit |
| `tree.children` | `null` for files, array (possibly empty) for folders |
| Folder paths | Always end with `/` |
| File paths | Never end with `/` |

**`max_depth` behavior:** depth is measured from the queried path. With `?path=a/b&max_depth=2`, you see up to `a/b/X/Y`. Content deeper than `max_depth` is collapsed into synthetic empty folders at the cut — ancestors within range are always shown, even if their only content is below the cut.

**Errors:**
- `404 Not Found` — `path` does not exist
- `400 Bad Request` — `path` points to a file rather than a folder

---

## Search Files

**GET** `/api/storage/search/`

Substring match on filename (the last path segment). Backed by a Postgres `pg_trgm` GIN index on the `StorageFile` mirror, not live S3 — normal writes stay in sync via `StorageFileSync`, but if you bypass the API to mutate the backend you'll need to run `backfill_storage_files` / `prune_storage_files`.

**Query Parameters:**

| Parameter | Type | Required | Default | Constraints | Description |
|-----------|------|----------|---------|-------------|-------------|
| `q` | string | Yes | — | min 2, max 100 chars | Substring to match, case-insensitive |
| `path` | string | No | `""` | — | Restrict results to this subtree |
| `limit` | integer | No | `50` | 1–200 | Max results to return |
| `offset` | integer | No | `0` | ≥ 0 | Pagination offset |

**Response:** `200 OK`
```json
{
    "total": 137,
    "offset": 0,
    "limit": 50,
    "results": [
        {"path": "reports/2025/q1_report.pdf", "name": "q1_report.pdf"},
        {"path": "archive/old_report.txt",    "name": "old_report.txt"}
    ]
}
```

**Field notes:**

| Field | Description |
|-------|-------------|
| `total` | Total matching rows across all pages |
| `results[].path` | Full org-relative path |
| `results[].name` | Last path segment (the matched filename) |

Response is intentionally lean — no `size`/`modified`. Call `/api/storage/info/?path=...` for full metadata on a click.

**Semantics:**
- **Files only.** Folders are not indexed.
- **Filename only.** Search for `report` matches `q1_report.pdf` but not the folder `reports/`.
- **Case-insensitive.** `REPORT` and `report` return the same results.
- **Substring, not fuzzy.** `reprot` returns nothing — typo tolerance is out of scope.
- **Missing `path`** returns an empty result set, not 404.

**Errors:**
- `400 Bad Request` — `q` shorter than 2 chars, or other validation failure

---

## File Info

**GET** `/api/storage/info/`

Returns metadata for a file or folder, including linked graphs.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Path to the file or folder |

**Response (file):** `200 OK`
```json
{
    "name": "Q1-summary.pdf",
    "path": "reports/Q1-summary.pdf",
    "size": 102400,
    "content_type": "application/pdf",
    "modified": "2026-04-15T10:30:00Z",
    "graphs": [{"id": 1, "name": "Monthly Report Flow"}]
}
```

**Response (folder):** `200 OK`
```json
{
    "name": "reports",
    "path": "reports",
    "modified": "2026-04-15T10:30:00Z",
    "graphs": []
}
```

**Error:** `404 Not Found`
```json
{"path": "File does not exist: some/path"}
```

---

## Download File

**GET** `/api/storage/download/`

Downloads a single file as a binary stream.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Path to the file |

**Response:** `200 OK`
- Content-Type: `application/octet-stream`
- Header: `Content-Disposition: attachment; filename="<name>"`
- Body: Binary file stream

**Error:** `400 Bad Request`
```json
{"path": "File does not exist: some/path"}
```

---

## Upload Limits

**GET** `/api/storage/upload-limits/`

The limits [Upload a File](#upload-a-file) enforces for the active organization, so a
client can reject a file before sending it. Needs `FILES:READ`.

**Response:** `200 OK`
```json
{
    "upload_path": "/api/storage/upload/stream",
    "max_file_size": 2147483648,
    "max_archive_size": 52428800,
    "free_bytes": 53687091200,
    "archive_suffixes": [".tar", ".tar.bz2", ".tar.gz", ".tar.xz", ".taz", ".tbz", ".tbz2", ".tgz", ".txz", ".zip"],
    "document_extensions": [".apk", ".docm", ".docx", ".dotx", ".epub", ".jar", ".odf", ".odg", ".odp", ".ods", ".odt", ".otp", ".ots", ".ott", ".potx", ".ppsx", ".pptm", ".pptx", ".war", ".xlsm", ".xlsx", ".xltx", ".xpi"]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `upload_path` | string | URL path to POST files to (`DJANGO_UPLOAD_STREAM_PATH`, default `/api/storage/upload/stream`) |
| `max_file_size` | integer \| null | Max bytes of one plain file (`DJANGO_MAX_STREAM_UPLOAD_FILE_SIZE`); `null` = unlimited |
| `max_archive_size` | integer | Max compressed bytes of one archive (`DJANGO_MAX_ARCHIVE_FILE_SIZE`); never `null` |
| `free_bytes` | integer | Bytes the organization may still upload (quota minus used, never below 0) |
| `archive_suffixes` | string[] | Lower-case suffixes, with the leading dot, of names uploaded as archives; sorted |
| `document_extensions` | string[] | Lower-case extensions, with the leading dot, never unpacked even if they match an archive suffix; sorted |

A file name is uploaded as an archive — and capped by `max_archive_size` instead
of `max_file_size` — iff its lower-cased name ends with one of `archive_suffixes`
and with none of `document_extensions`. This is exactly the server's routing rule.

`free_bytes` is a snapshot: it ignores uploads still in flight and does not credit
a file an upload would overwrite (the upload itself only charges the size
difference). It shrinks as files are added, so read it again before each batch;
the upload's own `413` stays authoritative.

**Errors:** `400` no `X-Organization-Id` header (`org_context_required`) · `401` not
authenticated · `403` missing `FILES:READ`, or the header names an organization the
caller is not a member of.

---

## Upload a File

**POST** `/api/storage/upload/stream`

Streams one file into storage. The request body is the raw file — Django reads it
in chunks and pipes it into object storage, so memory stays bounded by one part
regardless of file size. One plain file may be at most
`DJANGO_MAX_STREAM_UPLOAD_FILE_SIZE` (default `2gb`; `none` = unlimited) and one
archive at most `DJANGO_MAX_ARCHIVE_FILE_SIZE` (default `50mb`, compressed); a
bigger one is rejected with `413` (`upload_too_large`). Everything is also bounded
by the organization's free storage quota (`413`, `storage_quota_exceeded`).
Read the limits up front from [Upload Limits](#upload-limits).

When the request declares a `Content-Length` over the size limit, it is rejected
with `413` at once, before it waits for an upload slot (so never with a `429` or
`503` a client would retry). The quota is checked once the upload holds a slot,
before any of the body is read. Both limits are enforced again on the bytes
actually received, so a missing or wrong `Content-Length` is still stopped.

An archive (`.zip`, `.tar`, `.tgz`, `.taz`, `.tar.gz`, `.tar.bz2`, `.tbz`, `.tbz2`,
`.tar.xz`, `.txz`) up to `DJANGO_MAX_ARCHIVE_FILE_SIZE` is unpacked into a new
folder instead of being stored. A file that carries an archive extension without
actually being one is stored as a plain file. Document formats (`.xlsx`, `.docx`,
`.pptx`, `.jar`, etc.) are stored as-is and never extracted.

Note the exact path: there is **no trailing slash**.

**Request:**
- Content-Type: `application/octet-stream`
- Body: the raw file bytes (not `multipart/form-data`, one file per request)

| Query param | Type | Required | Description |
|-------------|------|----------|-------------|
| `path` | string | No | Destination directory; omit for the storage root |
| `filename` | string | Yes | Target file name; must not contain a path separator |

**Validation rules:**
- Blocks executable extensions (see [Blocked Extensions Reference](#blocked-extensions-reference))
- Blocks unsupported archive formats (see [Archive Format Reference](#archive-format-reference))
- Rejects names with control characters or blank segments (file name and `path`)
- Checks the whole archive before anything is written: executables inside,
  empty, password-protected or damaged archives, zip-slip and symlinked members,
  tar members that are not plain files or folders (hardlinks, FIFOs, devices,
  sparse files), tar headers over 64 KiB, ZIP members with an unsupported
  compression method (e.g. Deflate64), bad member names, a file and a folder
  with the same name, more than `DJANGO_MAX_ARCHIVE_ENTRIES` entries; empty
  folders inside are kept. Each of these answers `400`
- The unpacked size has no cap of its own: an archive that would not fit the
  organization's free storage quota is rejected with `413`

**Response (regular file):** `200 OK`
```json
{"status": "DONE", "path": "reports/data.csv", "size": 5120}
```

**Response (archive):** `200 OK`
```json
{
    "status": "DONE",
    "path": "reports/dataset-3f2a9c1b",
    "extracted": ["reports/dataset-3f2a9c1b/file1.csv", "reports/dataset-3f2a9c1b/file2.csv"]
}
```

**Errors:** `400` blocked extension, malformed name or bad archive · `401` not
authenticated (with `WWW-Authenticate`) · `403` missing `FILES:CREATE` in the
active organization · `408` no body data for `DJANGO_UPLOAD_IDLE_TIMEOUT`
(`upload_idle_timeout`) or the upload ran past `DJANGO_UPLOAD_MAX_DURATION`
(`upload_duration_exceeded`) · `413` over `DJANGO_MAX_STREAM_UPLOAD_FILE_SIZE` or
`DJANGO_MAX_ARCHIVE_FILE_SIZE` (`upload_too_large`) or over the organization
storage quota (`storage_quota_exceeded`) · `429` + `Retry-After` the organization already runs
`DJANGO_UPLOAD_MAX_CONCURRENCY_PER_ORG` uploads on this worker
(`org_upload_limit_reached`) · `500` unexpected server error · `503` +
`Retry-After` no upload slot freed up within `DJANGO_UPLOAD_SLOT_TIMEOUT`
(`upload_slots_busy`) · `503` + `Retry-After: 30` object storage unreachable, or no
folder name for an archive could be claimed in it (`storage_unavailable`).
An aborted upload leaves no object and no row behind.

```json
{"status_code": 400, "code": "invalid", "message": "'setup.exe' has a blocked executable extension"}
```

---

## Download ZIP

**POST** `/api/storage/download-zip/`

Packages one or more files and/or folders into a ZIP archive and streams it. Folders are recursively included.

**Request:**
```json
{"paths": ["reports/file1.csv", "reports/file2.csv"]}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `paths` | string[] | Yes | Paths to include in the ZIP |

**Response:** `200 OK`
- Content-Type: `application/zip`
- Header: `Content-Disposition: attachment; filename="download.zip"`
- Body: Binary ZIP stream

**Error:** `400 Bad Request`
```json
{"paths": "..."}
```

---

## Create Folder

**POST** `/api/storage/mkdir/`

Creates a new folder at the specified path, including any intermediate directories.

**Request:**
```json
{"path": "reports/2026"}
```

**Response:** `201 Created`
```json
{"path": "reports/2026", "created": true}
```

**Error:** `409 Conflict`
```json
{"detail": "Path already exists: reports/2026"}
```

---

## Bulk Delete

**DELETE** `/api/storage/delete/`

Deletes one or more files or folders. Folders are deleted recursively.

**Request:**
```json
{"paths": ["reports/old-file.csv", "reports/archive"]}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `paths` | string[] | Yes | At least 1 path required |

**Response:** `204 No Content`

---

## Rename

**POST** `/api/storage/rename/`

Renames a file or folder in-place. Cannot rename to a blocked executable extension.

**Request:**
```json
{"from": "reports/old-name.pdf", "to": "reports/new-name.pdf"}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `from` | string | Yes | Current path of the file or folder |
| `to` | string | Yes | New path (same directory) |

**Response:** `200 OK`
```json
{"from": "reports/old-name.pdf", "to": "reports/new-name.pdf", "success": true}
```

**Error (source not found):** `400 Bad Request`
```json
{"from": "Source path does not exist: ..."}
```

**Error (destination exists):** `400 Bad Request`
```json
{"to": "Destination already exists: ..."}
```

**Error (blocked extension):** `400 Bad Request`
```json
{"detail": "..."}
```

---

## Move

**POST** `/api/storage/move/`

Moves a file or folder to a new location. Supports cross-organization moves by providing `source_org_id` and `destination_org_id`.

> **Note:** Cross-org move is non-atomic. If the delete step fails after the copy completes, the file will exist in both organizations.

A cross-org move counts against the destination organization's storage quota. Over quota it fails with `413` and the source is left untouched.

**Request (same org):**
```json
{"from": "reports/file.pdf", "to": "archive/file.pdf"}
```

**Request (cross-org):**
```json
{
    "from": "reports/file.pdf",
    "to": "archive/file.pdf",
    "source_org_id": 1,
    "destination_org_id": 2
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `from` | string | Yes | Source path |
| `to` | string | Yes | Destination path |
| `source_org_id` | integer \| null | No | Source organization ID for cross-org move |
| `destination_org_id` | integer \| null | No | Destination organization ID for cross-org move |

**Response:** `200 OK`
```json
{"from": "reports/file.pdf", "to": "archive/file.pdf", "success": true}
```

**Error:** `400 Bad Request`
```json
{"from": "Source path does not exist: ..."}
```

**Error:** `413` — a cross-org move that does not fit the destination organization's storage quota.

---

## Copy

**POST** `/api/storage/copy/`

Copies a file or folder to a new location. Supports cross-organization copies. If the destination path already exists, the name is auto-incremented: `file.pdf` → `file (1).pdf` → `file (2).pdf`.

**Request (same org):**
```json
{"from": "reports/file.pdf", "to": "backup/file.pdf"}
```

**Request (cross-org):**
```json
{
    "from": "reports/file.pdf",
    "to": "backup/file.pdf",
    "source_org_id": 1,
    "destination_org_id": 2
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `from` | string | Yes | Source path |
| `to` | string | Yes | Destination path |
| `source_org_id` | integer \| null | No | Source organization ID for cross-org copy |
| `destination_org_id` | integer \| null | No | Destination organization ID for cross-org copy |

**Response:** `200 OK`
```json
{"from": "reports/file.pdf", "to": "backup/file.pdf", "success": true}
```

**Error:** `413` — the copy (every file in a copied folder included) does not fit the destination organization's storage quota. Nothing is left behind.

---

## Add to Graph

**POST** `/api/storage/add-to-graph/`

Links one or more existing storage paths to one or more graphs. Creates `StorageFile` records as needed.

**Request:**
```json
{"paths": ["reports/data.csv", "images/logo.png"], "graph_ids": [1, 2]}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `paths` | string[] | Yes | Paths to the files or folders |
| `graph_ids` | integer[] | Yes | Graph IDs to link |

**Response:** `201 Created`
```json
[
    {"id": 10, "graph_id": 1, "path": "reports/data.csv", "added_at": "2026-04-15T10:30:00Z"},
    {"id": 11, "graph_id": 2, "path": "reports/data.csv", "added_at": "2026-04-15T10:30:00Z"},
    {"id": 12, "graph_id": 1, "path": "images/logo.png", "added_at": "2026-04-15T10:30:00Z"},
    {"id": 13, "graph_id": 2, "path": "images/logo.png", "added_at": "2026-04-15T10:30:00Z"}
]
```

**Error:** `400 Bad Request`
```json
{"paths": ["Path does not exist: bad/path.txt"]}
```

**Error (graph not in the active org, or non-existent):** `400 Bad Request`
```json
{"graph_ids": ["Graphs not found: [999, 1000]"]}
```

Only graphs in the caller's **active organization** may be linked. A cross-org id
and a non-existent id are reported identically (no existence leak), and the whole
request is rejected atomically — nothing is linked unless every id is valid.

---

## Remove from Graph

**DELETE** `/api/storage/remove-from-graph/`

Unlinks one or more storage paths from one or more graphs.

**Request:**
```json
{"paths": ["reports/data.csv"], "graph_ids": [1]}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `paths` | string[] | Yes | Paths to the files or folders |
| `graph_ids` | integer[] | Yes | Graph IDs to unlink |

**Response:** `204 No Content`

---

## Graph Files

**GET** `/api/storage/graph-files/`

Lists all storage paths linked to a specific graph.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `graph_id` | integer | Yes | Graph ID to query |

**Response:** `200 OK`
```json
[
    {"id": 10, "graph_id": 1, "path": "reports/data.csv", "added_at": "2026-04-15T10:30:00Z"},
    {"id": 11, "graph_id": 1, "path": "reports/charts/", "added_at": "2026-04-15T10:31:00Z"}
]
```

**Error:** `404 Not Found`
```json
{"graph_id": "Graph not found: 999"}
```

---

## Session Output Files

**GET** `/api/sessions/{id}/output-files/`

Lists all files written to storage during a session's execution. This endpoint lives on the `SessionViewSet`, not on `StorageAPIView`.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | integer | Session ID |

**Response:** `200 OK`
```json
[
    {"id": 5, "path": "reports/generated-report.pdf", "name": "generated-report.pdf", "added_at": "2026-04-15T11:00:00Z"}
]
```

---

## Blocked Extensions Reference

### Blocked Executable Extensions

Uploading or renaming to any of these extensions is rejected.

| Platform | Extensions |
|----------|------------|
| Windows | `.exe`, `.msi`, `.com`, `.scr`, `.pif`, `.bat`, `.cmd`, `.vbs`, `.vbe`, `.wsh`, `.wsf`, `.ps1`, `.psm1`, `.psd1` |
| Unix/macOS | `.sh`, `.bash`, `.csh`, `.ksh`, `.zsh`, `.app`, `.command`, `.elf` |
| Java | `.jar`, `.war`, `.ear` |
| Shared libs | `.dll`, `.so`, `.dylib` |

---

## Archive Format Reference

### Blocked Archive Formats

These archive formats are rejected on upload.

`.rar`, `.7z`, `.cab`, `.iso`, `.arj`, `.lzh`, `.ace`, `.arc`, `.lz`, `.lzma`, `.zst`

### Supported Archive Formats (auto-extracted)

These formats are accepted and automatically extracted into a subfolder named after the archive stem.

`.zip`, `.tar`, `.tar.gz`, `.tar.bz2`, `.tar.xz`

---

## Path Normalization

All path inputs are normalized before processing:

- Trailing slashes are stripped from all inputs
- Paths never start with `/`
- Folder paths stored in the database use a trailing `/`

---

## HTTP Status Codes

| Code | Meaning | Common Use |
|------|---------|------------|
| 200 | OK | Successful GET, POST (non-creating), rename, move, copy |
| 201 | Created | Successful upload, folder creation, add-to-graph |
| 204 | No Content | Successful delete, remove-from-graph |
| 400 | Bad Request | Validation error, blocked extension, invalid graph IDs |
| 404 | Not Found | Non-existing path, file, or graph |
| 409 | Conflict | Resource already exists (e.g. mkdir on existing path) |
| 413 | Content Too Large | Upload over the per-file or archive size limit (`upload_too_large`); upload, copy or cross-org move over the organization storage quota (`storage_quota_exceeded`) |
| 500 | Internal Server Error | Unexpected server error |
