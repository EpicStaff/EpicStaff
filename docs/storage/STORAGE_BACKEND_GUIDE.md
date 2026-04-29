# Storage Backend Guide

## Overview

The application supports three storage backends for file management:

| Backend | `STORAGE_BACKEND` value | Use case |
|---------|------------------------|----------|
| **MinIO (S3-compatible)** | `s3` (default) | Development and production with self-hosted object storage |
| **AWS S3** | `s3` | Production with managed cloud storage |
| **Local filesystem** | `local` | Simple deployments without object storage |

The backend is selected at startup via the `STORAGE_BACKEND` environment variable. No code changes are needed to switch.

---

## Quick Start

### MinIO (default)

MinIO starts automatically as a core service. No extra configuration needed.

```bash
docker compose up
```

MinIO console is available at `http://localhost:9001` (default credentials: `minioadmin` / `minioadmin_secret`).
The `minio-init` service auto-creates the bucket on first start.

### AWS S3

```bash
# Set env vars in .env
STORAGE_BACKEND=s3
STORAGE_ENDPOINT=           # leave empty for AWS
STORAGE_ACCESS_KEY=<your-aws-access-key>
STORAGE_SECRET_KEY=<your-aws-secret-key>
STORAGE_BUCKET_NAME=<your-bucket-name>
```

### Local storage

```bash
# Set env vars in .env
STORAGE_BACKEND=local
STORAGE_LOCAL_ROOT=/app/storage
```

Files are stored at the `STORAGE_LOCAL_ROOT` path inside the container.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `STORAGE_BACKEND` | `s3` | Backend type: `s3` or `local` |
| `STORAGE_ENDPOINT` | `http://minio:9000` | S3 endpoint URL. Leave empty for AWS S3. |
| `STORAGE_ACCESS_KEY` | `minioadmin` | S3 access key / MinIO root user |
| `STORAGE_SECRET_KEY` | `minioadmin_secret` | S3 secret key / MinIO root password |
| `STORAGE_BUCKET_NAME` | `epicstaff` | S3 bucket name |
| `STORAGE_LOCAL_ROOT` | `/app/storage` | Root directory for local backend |
| `MINIO_PORT` | `9000` | MinIO API port (used in healthcheck and mc commands) |
| `MINIO_CONSOLE_PORT` | `9001` | MinIO web console port |
| `STORAGE_MUTATION_CHANNEL` | `storage_mutations` | Redis pub/sub channel for storage mutation events |
| `MAX_TOTAL_FILE_SIZE` | `10485760` (10 MB) | Maximum total upload size per request |

---

## Architecture

```
StorageAPIView (REST endpoints)
       |
  StorageManager (org isolation, permissions)
       |
  get_storage_backend()          <-- factory, reads STORAGE_BACKEND env var
       |
  +-----------+-----------------+
  |                             |
LocalStorageBackend     S3StorageBackend
(pathlib / shutil)      (boto3 / S3 API)
```

### Key files

| File | Purpose |
|------|---------|
| `tables/services/storage_service/__init__.py` | Factory functions `get_storage_backend()`, `get_storage_manager()` |
| `tables/services/storage_service/base.py` | `AbstractStorageBackend` interface |
| `tables/services/storage_service/local_backend.py` | Local filesystem implementation |
| `tables/services/storage_service/s3_backend.py` | S3/MinIO implementation |
| `tables/services/storage_service/manager.py` | `StorageManager` (org prefixing, permissions, archive handling) |
| `tables/services/storage_service/enums.py` | `StorageAction` enum |
| `tables/services/storage_service/decorators.py` | `@check_permission` decorator |
| `tables/services/storage_service/db_sync.py` | `StorageFileSync` — keeps DB in sync with storage mutations |
| `tables/services/storage_service/dataclasses.py` | Data classes: `FileListItem`, `FileInfo`, `FolderInfo`, `UploadResult`, etc. |
| `tables/storage_permissions.py` | `StoragePermission` DRF permission class |
| `tables/validators/file_upload_validator.py` | `FileValidator` — blocks executable uploads, scans archives |
| `tables/models/graph_models.py` | `StorageFile`, `GraphStorageFile`, `SessionStorageFile` models |
| `tables/views/storage_views.py` | `StorageAPIView` REST endpoints |
| `tables/swagger_schemas/storage_schema.py` | Swagger/OpenAPI schema definitions |
| `tables/urls.py` | Router registration (`/api/storage/`) |
| `django_app/settings.py` | `STORAGE_*` settings (read from env) |
| `shared/epicstaff_storage/storage.py` | Storage SDK for Python/Code Agent nodes in flows |

---

## Backend Interface

Both backends implement the same `AbstractStorageBackend` methods:

- `list_(prefix)` -- list files and folders
- `upload(path, file)` -- upload a file
- `download(path)` -- download a file
- `delete(path)` -- delete a file or folder
- `mkdir(path)` -- create a folder
- `move(src, dst)` -- move / rename
- `copy(src, dst)` -- copy
- `info(path)` -- file metadata
- `exists(path)` -- check existence
- `download_zip(paths)` -- create a zip archive
- `upload_archive(prefix, archive)` -- extract an archive (ZIP or TAR)

---

## StorageManager

`StorageManager` is an org-aware singleton wrapper around the backend. It is the primary interface used by views.

### Organization isolation

All paths are automatically prefixed with `org_{org_id}/`. The caller works with relative paths only — the org prefix is added/stripped transparently.

### Permission checks

Every public method is decorated with `@check_permission`, which calls `_require_permission()` before touching storage. Currently checks org membership via `OrganizationUser`. Extension points exist for role-based access and path-based ACLs.

### Archive auto-extraction

`upload_file()` detects ZIP and TAR archives and extracts them into the target directory automatically. Supported formats: `.zip`, `.tar`, `.tar.gz`, `.tar.bz2`, `.tar.xz`.

Archives extract into a subfolder named after the archive stem (e.g., `data.zip` → `data/`). If the subfolder already exists, the name auto-increments: `data` → `data (1)` → `data (2)`.

Password-protected ZIP files are rejected.

Document formats (`.xlsx`, `.docx`, `.pptx`, `.epub`, `.jar`, `.apk`, `.war`, `.xpi`, etc.) are NOT extracted even though they are ZIP-based.

**Note:** `.jar`, `.war`, and `.ear` also appear in the blocked executable extensions list. Since upload validation runs first, these formats are rejected before the archive detection step. They appear in both lists as a defense-in-depth measure.

### Cross-org operations

- `copy_cross_org(user_name, src_org_id, src_path, dst_org_id, dst_path)` -- copy between orgs
- `move_cross_org(user_name, src_org_id, src_path, dst_org_id, dst_path)` -- move between orgs (non-atomic: if delete fails after copy, file exists in both)

Both require the user to have permission in source and destination orgs.

---

## File Validation

`FileValidator` (in `tables/validators/file_upload_validator.py`) enforces upload security:

- Blocks executable file extensions (Windows, Unix, Java, shared libs)
- Blocks unsupported archive formats (only ZIP and TAR allowed)
- Scans ZIP/TAR contents for embedded executable files without extracting
- Rename operations also validate the destination extension

---

## Database Sync

`StorageFileSync` (in `tables/services/storage_service/db_sync.py`) maintains `StorageFile` records in the database:

- Creates records on upload
- Deletes records (or prefix-matched records for folders) on delete
- Updates paths (or bulk-updates folder children) on move/rename
- Bulk-creates on copy
- Handles cross-org operations

The DB mirror powers the search endpoint (`GET /api/storage/search/`). Normal mutations stay in sync automatically; the commands below exist for initial import and drift repair.

---

## Management Commands

Two management commands reconcile the `StorageFile` table with the storage backend. Both iterate every organization by default and accept `--org-id <id>` to scope to one org. Both accept `--dry-run` to preview without writing.

Run inside the `django_app` container:

```bash
docker exec django_app python manage.py <command> [flags]
```

### `backfill_storage_files` — S3 → DB

Walks the backend for every org, upserts a `StorageFile` row per key. Additive only: inserts missing rows, updates `name` on existing rows, never deletes. Safe to re-run (idempotent).

Use when:
- Bootstrapping the mirror for files that pre-date the sync layer
- Recovering from a bug that dropped `StorageFile` rows
- After a backend migration that seeded files outside the app

```bash
docker exec django_app python manage.py backfill_storage_files --dry-run
docker exec django_app python manage.py backfill_storage_files
docker exec django_app python manage.py backfill_storage_files --org-id 1
```

Dry-run output:
```
[org=1] dry-run: 142813 keys found
[org=2] dry-run: 37 keys found
```

Live run logs progress per 1000-row batch: `[org=1] upserted 12000/142813`.

### `prune_storage_files` — DB → S3

Deletes `StorageFile` rows whose corresponding backend key no longer exists (orphans). Complements `backfill`: backfill fixes "DB missing rows"; prune fixes "DB has orphan rows".

Cascading: deleting a `StorageFile` row also removes linked `GraphStorageFile` and `SessionStorageFile` entries via FK `CASCADE`. Always run with `--dry-run` first on production.

Use when:
- Files were deleted directly in S3/MinIO (bypassing the API)
- Recovering from a missed sync hook
- After a backend migration that removed objects

```bash
docker exec django_app python manage.py prune_storage_files --dry-run
docker exec django_app python manage.py prune_storage_files
docker exec django_app python manage.py prune_storage_files --org-id 1
```

Dry-run output:
```
[org=1] 142813 keys in S3, 142850 rows in DB, 37 orphans to prune
```

Memory: the command loads all S3 keys per org into a `set` (~20 MB at 200k keys) and streams DB rows via `.iterator()`, so it's safe at 140k+ scale.

---

## Graph and Session File Tracking

Three models track file relationships:

- `StorageFile` — core record per org-scoped path
- `GraphStorageFile` — links files to graphs (flows) for reuse
- `SessionStorageFile` — tracks files created during flow execution sessions

---

## API Endpoints

Base path: `/api/storage/`

| Method | Path | Description | Parameters |
|--------|------|-------------|------------|
| GET | `/list/` | List files and folders | `path` (query) |
| GET | `/tree/` | Recursive folder tree (one nested JSON response, up to 50 000 entries) | `path`, `max_depth` (query) |
| GET | `/search/` | Substring search on filename (DB-backed) | `q`, `path`, `limit`, `offset` (query) |
| GET | `/info/` | File/folder metadata + linked graphs | `path` (query) |
| GET | `/download/` | Download a file | `path` (query) |
| POST | `/upload/` | Upload files (multipart) | `path` (form), `files` (multipart) |
| POST | `/download-zip/` | Download multiple files/folders as ZIP | `paths` (JSON body) |
| POST | `/mkdir/` | Create a folder | `path` (body) |
| DELETE | `/delete/` | Bulk delete files/folders | `paths` (JSON body, min 1) |
| POST | `/rename/` | Rename file/folder | `from`, `to` (body) |
| POST | `/move/` | Move (same-org + cross-org) | `from`, `to`, `source_org_id`, `destination_org_id` (body) |
| POST | `/copy/` | Copy (same-org + cross-org) | `from`, `to`, `source_org_id`, `destination_org_id` (body) |
| POST | `/add-to-graph/` | Link storage files to graphs | `paths`, `graph_ids` (body) |
| DELETE | `/remove-from-graph/` | Unlink storage files from graphs | `paths`, `graph_ids` (body) |
| GET | `/graph-files/` | List files attached to a graph | `graph_id` (query) |

`GET /api/sessions/{id}/output-files/` lives on the `SessionViewSet` and returns files tracked during session execution.

Archive uploads are auto-detected and extracted. Cross-org move/copy is triggered when `source_org_id` and `destination_org_id` differ.

Full Swagger documentation is available at the `/swagger/` endpoint.

---

## Docker Compose

MinIO is a core service — it starts with every `docker compose up`. No profiles are needed.

- **`minio`** — S3-compatible object storage (`minio/minio:latest`), volume: `minio_data`
- **`minio-init`** — one-shot container that creates the bucket using `mc` (MinIO client), restarts on failure until successful

The `django_app` service depends on `minio` being healthy before starting.

---

## Related Documentation

- [Storage API Reference](STORAGE_API_REFERENCE.md) — complete endpoint documentation
- [Storage SDK Reference](STORAGE_SDK_REFERENCE.md) — SDK for Python/Code Agent nodes
- [Storage System Documentation](STORAGE_SYSTEM_DOCUMENTATION.md) — architecture and internals
