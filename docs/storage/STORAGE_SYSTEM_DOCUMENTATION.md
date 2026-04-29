# Storage System Documentation

## Architecture and System-Level Reference for Developers

This document covers the EpicStaff storage system architecture, data models, security model, and execution-time SDK integration.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture](#2-architecture)
3. [Data Models](#3-data-models)
   - [StorageFile](#storagefile)
   - [GraphStorageFile](#graphstoragefile)
   - [SessionStorageFile](#sessionstoragefile)
4. [DB Sync Layer (StorageFileSync)](#4-db-sync-layer-storagefilesync)
5. [File Validation Pipeline (FileValidator)](#5-file-validation-pipeline-filevalidator)
6. [Archive Handling Flow](#6-archive-handling-flow)
7. [Cross-Org Operations](#7-cross-org-operations)
8. [Path Normalization](#8-path-normalization)
9. [Security](#9-security)
10. [Key Files](#10-key-files)
11. [Docker Infrastructure](#11-docker-infrastructure)

---

## 1. System Overview

EpicStaff Storage is an org-scoped file management system supporting S3-compatible and local filesystem backends. It provides REST APIs for file CRUD, archive handling, graph-file linking, and an SDK for use within flow execution (Python/Code Agent nodes).

All file operations are namespaced per organization. Permissions are enforced at every layer — REST API, StorageManager, and the flow execution SDK.

---

## 2. Architecture

```
Frontend (Angular)
    │
    ▼
StorageAPIView (REST endpoints)        SessionViewSet.output_files()
    │                                        │
    ▼                                        ▼
StorageManager                         SessionStorageFile queries
  ├─ org isolation (org_{id}/ prefix)
  ├─ permission checks (OrganizationUser)
  ├─ archive auto-extraction
  ├─ DB sync (StorageFileSync)
  │
  ▼
AbstractStorageBackend
  ├─ LocalStorageBackend (pathlib/shutil)
  └─ S3StorageBackend (boto3)

Storage SDK (EpicStaffStorage)
  └─ Used by Python/Code Agent nodes during flow execution
  └─ Direct S3 access with path allowlist
```

**StorageManager** is the central org-aware service. It wraps every backend operation with org isolation, permission checks, and DB sync. Views never call the backend directly.

**AbstractStorageBackend** defines the interface. Two implementations exist: `LocalStorageBackend` for development/testing and `S3StorageBackend` for production (MinIO or any S3-compatible service).

**StorageFileSync** keeps the `StorageFile` DB table consistent with actual storage mutations. It is called by `StorageManager` after every mutating operation.

**EpicStaffStorage SDK** is used inside flow execution (Code Agent nodes). It operates with direct S3 access and is constrained by an allowlist of permitted paths (`STORAGE_ALLOWED_PATHS`).

---

## 3. Data Models

All models live in `tables/models/graph_models.py`.

### StorageFile

Represents a single file or folder record within an organization's storage space.

| Field | Type | Notes |
|-------|------|-------|
| `org` | FK → Organization | CASCADE delete |
| `path` | CharField(max_length=2048) | Org-relative, never starts with `/` |
| `created_at` | DateTimeField | auto_now_add |
| `updated_at` | DateTimeField | auto_now |

- Unique constraint: `(org, path)`
- Index: `(org, path)`
- Folder paths stored with trailing `/` (e.g., `reports/`)
- File paths stored without trailing `/` (e.g., `reports/data.csv`)

### GraphStorageFile

M2M link between a Graph (flow definition) and a StorageFile. Tracks which files are associated with a flow at design time.

| Field | Type | Notes |
|-------|------|-------|
| `graph` | FK → Graph | CASCADE, related_name=`"storage_files"` |
| `storage_file` | FK → StorageFile | CASCADE, related_name=`"graph_storage_files"` |
| `added_at` | DateTimeField | auto_now_add |

- Unique constraint: `(graph, storage_file)`

### SessionStorageFile

Tracks output files generated during a specific flow session execution. Used by `SessionViewSet.output_files()` to return files produced by a run.

| Field | Type | Notes |
|-------|------|-------|
| `session` | FK → Session | CASCADE, related_name=`"storage_files"` |
| `storage_file` | FK → StorageFile | CASCADE, related_name=`"session_storage_files"` |
| `added_at` | DateTimeField | auto_now_add |

- Unique constraint: `(session, storage_file)`

---

## 4. DB Sync Layer (StorageFileSync)

Located at `tables/services/storage_service/db_sync.py`. Keeps the `StorageFile` table in sync with actual storage mutations. Called by `StorageManager` after every operation — never called directly from views.

| Method | Behavior |
|--------|----------|
| `on_upload(org_id, path)` | `get_or_create` StorageFile record |
| `on_delete(org_id, path)` | Delete exact match; if no match, delete all files with that prefix (folder delete) |
| `on_move(org_id, src, dst)` | Update path; if no exact match, bulk-update all paths under prefix via `Concat+Substr` |
| `on_copy(org_id, actual_dst_paths)` | `bulk_create` with `ignore_conflicts=True` |
| `on_move_cross_org(src_org, src_path, dst_org, dst_path)` | Delete from source org, create in destination org |
| `on_copy_cross_org(dst_org, dst_path)` | Create record in destination org |

**Folder delete** works by prefix matching: if no exact `path` match exists, all records whose `path` starts with `{path}/` are deleted. This handles recursive folder removal without requiring a tree walk.

**Folder move** uses `Concat+Substr` to rewrite the prefix portion of all matching paths in a single bulk update, avoiding N+1 queries.

---

## 5. File Validation Pipeline (FileValidator)

Located at `tables/validators/file_upload_validator.py`. Applied during upload and rename operations.

### Blocked Executable Extensions

**Windows:** `.exe`, `.msi`, `.com`, `.scr`, `.pif`, `.bat`, `.cmd`, `.vbs`, `.vbe`, `.wsh`, `.wsf`, `.ps1`, `.psm1`, `.psd1`

**Unix/macOS:** `.sh`, `.bash`, `.csh`, `.ksh`, `.zsh`, `.app`, `.command`, `.elf`

**Java:** `.jar`, `.war`, `.ear`

**Shared libraries:** `.dll`, `.so`, `.dylib`

### Blocked Archive Formats

`.rar`, `.7z`, `.cab`, `.iso`, `.arj`, `.lzh`, `.ace`, `.arc`, `.lz`, `.lzma`, `.zst`

Only ZIP and TAR archives are accepted. All other archive formats are rejected with the message "Use ZIP or TAR instead."

### Validation Steps

1. Check if file has a blocked archive extension → reject with "Use ZIP or TAR instead"
2. Check if file has a blocked executable extension → reject
3. If file is a ZIP or TAR archive → scan the directory listing for executable entries (no extraction performed) → reject if found

### Rename Validation

The rename serializer additionally validates that the destination filename does not have an executable extension.

---

## 6. Archive Handling Flow

When a ZIP or TAR file is uploaded, it is automatically extracted rather than stored as-is.

1. Upload receives the file
2. `StorageManager._is_archive()` checks if it is a ZIP or TAR — document formats that use ZIP internally (e.g., `.docx`, `.xlsx`) are explicitly excluded
3. `AbstractStorageBackend._check_archive_password()` rejects password-protected ZIP files before any extraction
4. Files are extracted into a subfolder named after the archive stem (e.g., `data.zip` → `data/`)
5. If the subfolder already exists, the name auto-increments: `data` → `data (1)` → `data (2)`
6. `StorageFileSync.on_upload()` is called for each extracted file to create DB records

### Document Extensions Treated as Regular Files (Not Extracted)

`.xlsx`, `.xlsm`, `.xltx`, `.docx`, `.docm`, `.dotx`, `.pptx`, `.pptm`, `.ppsx`, `.potx`, `.ods`, `.odt`, `.odp`, `.odg`, `.odf`, `.ots`, `.ott`, `.otp`, `.epub`, `.apk`, `.jar`, `.war`, `.xpi`

These formats use ZIP internally but represent document containers, not archives of arbitrary files.

**Note:** `.jar`, `.war`, and `.ear` also appear in the blocked executable extensions list. Since upload validation runs first, these formats are rejected before the archive detection step. They appear in both lists as a defense-in-depth measure.

---

## 7. Cross-Org Operations

Both cross-org operations require explicit permission verification in both the source and destination organizations.

### `copy_cross_org`

- Requires DOWNLOAD permission in source org
- Requires UPLOAD permission in destination org
- Uses server-side S3 copy (no data round-trip through application server)
- DB sync: `on_copy_cross_org(dst_org, dst_path)` creates record in destination

### `move_cross_org`

- Requires DELETE permission in source org
- Requires UPLOAD permission in destination org
- **Non-atomic**: copy happens first, then delete. If the delete step fails, the file exists in both orgs. No automatic rollback.
- DB sync: `on_move_cross_org(src_org, src_path, dst_org, dst_path)` deletes from source, creates in destination

Permissions are checked via `_require_permission()` which validates `OrganizationUser` membership.

---

## 8. Path Normalization

| Layer | Behavior |
|-------|----------|
| Serializers | Strip trailing slashes from all input paths |
| Internal storage keys | `org_{org_id}/{relative_path}` |
| DB folder records | Stored with trailing `/` (e.g., `reports/`) |
| DB file records | Stored without trailing `/` (e.g., `reports/data.csv`) |
| SDK paths | Auto-prefixed with `STORAGE_ORG_PREFIX` env var |
| SDK traversal protection | `posixpath.normpath` applied; `../` sequences resolved and rejected |
| Local backend | Resolved paths validated to stay within storage root |

---

## 9. Security

| Control | Mechanism |
|---------|-----------|
| Org isolation | All storage keys namespaced under `org_{id}/`; cross-org access requires explicit permission |
| Executable blocking | Upload and rename reject known executable extensions via `FileValidator` |
| Archive scanning | ZIP/TAR contents inspected for executable entries without extraction |
| Password-protected archives | Rejected at upload time before extraction begins |
| Path traversal protection | Local backend resolves and validates paths; SDK normalizes and checks via `posixpath.normpath` |
| Permission checks | Every `StorageManager` method verifies the user is an `OrganizationUser` member |
| SDK allowlist | Flow execution constrains file access to paths listed in `STORAGE_ALLOWED_PATHS` env var |

---

## 10. Key Files

| File | Purpose |
|------|---------|
| `tables/views/storage_views.py` | REST API endpoints (`StorageAPIView`) |
| `tables/serializers/storage_serializers.py` | Request validation and response serialization |
| `tables/swagger_schemas/storage_schema.py` | OpenAPI/Swagger schema definitions |
| `tables/models/graph_models.py` | `StorageFile`, `GraphStorageFile`, `SessionStorageFile` models |
| `tables/services/storage_service/manager.py` | `StorageManager` (org-aware wrapper) |
| `tables/services/storage_service/base.py` | `AbstractStorageBackend` interface |
| `tables/services/storage_service/local_backend.py` | Local filesystem backend |
| `tables/services/storage_service/s3_backend.py` | S3/MinIO backend |
| `tables/services/storage_service/db_sync.py` | `StorageFileSync` (DB sync layer) |
| `tables/services/storage_service/dataclasses.py` | `FileListItem`, `FileInfo`, `FolderInfo`, etc. |
| `tables/services/storage_service/enums.py` | `StorageAction` enum |
| `tables/validators/file_upload_validator.py` | `FileValidator` (upload security) |
| `tables/storage_permissions.py` | `StoragePermission` DRF permission class |
| `shared/epicstaff_storage/storage.py` | Storage SDK for flow execution |
| `tables/views/views.py` | `SessionViewSet.output_files` endpoint |

---

## 11. Docker Infrastructure

Storage infrastructure is defined in `src/docker-compose.yaml`.

| Service | Image | Purpose |
|---------|-------|---------|
| `minio` | `minio/minio:latest` | S3-compatible object storage, volume `minio_data` |
| `minio-init` | MinIO client (`mc`) | One-shot container that creates the bucket on startup |

`django_app` depends on `minio` being healthy before starting.

### Configuration Environment Variables

| Variable | Purpose |
|----------|---------|
| `STORAGE_BACKEND` | `s3` or `local` |
| `STORAGE_ENDPOINT` | S3/MinIO endpoint URL |
| `STORAGE_ACCESS_KEY` | S3 access key |
| `STORAGE_SECRET_KEY` | S3 secret key |
| `STORAGE_BUCKET_NAME` | Target bucket name |
| `STORAGE_LOCAL_ROOT` | Root path for local backend |
| `STORAGE_ORG_PREFIX` | Org prefix used by SDK (set per execution context) |
| `STORAGE_ALLOWED_PATHS` | JSON array of allowed paths for SDK access |
