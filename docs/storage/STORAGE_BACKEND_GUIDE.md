# Storage Backend Guide

## Overview

The application uses an S3-compatible object storage backend (`S3StorageBackend`) for all file management. The default server is [RustFS](https://github.com/rustfs/rustfs) (Apache-2.0), which replaced MinIO in EST-4230 after MinIO stopped publishing images.

The sandbox also uses the MinIO Admin API (which RustFS implements) to create short-lived, org-scoped credentials for each code execution. A plain S3 service without that API (for example AWS S3) can serve files, but sandbox storage access will not work.

---

## Quick Start

RustFS starts automatically as a core service (compose service name `minio`, kept for now). No extra configuration is needed.

```bash
docker compose up
```

The `minio-init` service creates the bucket on first start. The RustFS web console is disabled (`RUSTFS_CONSOLE_ENABLE=false`), because the service is reachable from `sandbox-network`.

---

## Environment Variables

Set in `.env` (generated from `src/env.yaml`). Services build the endpoint as `http(s)://MINIO_HOST:MINIO_PORT`.

| Variable | Default | Description |
|----------|---------|-------------|
| `MINIO_HOST` | `minio` | Hostname of the storage service |
| `MINIO_PORT` | `9000` | S3 API port (also used by the healthcheck and `minio-init`) |
| `MINIO_SSL` | `False` | Use HTTPS to reach the storage service |
| `MINIO_USER` | — | Root access key |
| `MINIO_PASSWORD` | — | Root secret key |
| `MINIO_BUCKET` | `epicstaff` | Bucket for file storage |
| `KNOWLEDGE_MINIO_BUCKET` | `epicstaff-knowledge` | Bucket for knowledge (GraphRAG) data |
| `STORAGE_MUTATION_CHANNEL` | `storage_mutations` | Redis pub/sub channel for storage mutation events |
| `MAX_TOTAL_FILE_SIZE` | `10485760` (10 MB) | Maximum total upload size per request |

---

## Architecture

```
StorageAPIView (REST endpoints)
       |
  StorageManager (org isolation, path composition)
       |
  get_storage_backend()          <-- factory, builds S3StorageBackend from settings
       |
  S3StorageBackend
  (boto3 / S3 API)
```

### Key files

| File | Purpose |
|------|---------|
| `tables/services/storage_service/__init__.py` | Factory functions `get_storage_backend()`, `get_storage_manager()` |
| `tables/services/storage_service/base.py` | `AbstractStorageBackend` interface |
| `tables/services/storage_service/s3_backend.py` | S3 implementation |
| `tables/services/storage_service/manager.py` | `StorageManager` (org prefixing, archive handling) |
| `tables/services/storage_service/db_sync.py` | `StorageFileSync` — keeps DB in sync with storage mutations |
| `tables/services/storage_service/dataclasses.py` | Data classes: `FileListItem`, `FileInfo`, `FolderInfo`, `UploadResult`, etc. |
| `tables/validators/file_upload_validator.py` | `FileValidator` — blocks executable uploads, scans archives |
| `tables/models/graph_models.py` | `StorageFile`, `GraphStorageFile`, `SessionStorageFile` models |
| `tables/views/storage_views.py` | `StorageAPIView` REST endpoints |
| `tables/swagger_schemas/storage_schema.py` | Swagger/OpenAPI schema definitions |
| `tables/urls.py` | Router registration (`/api/storage/`) |
| `django_app/settings.py` | `STORAGE_*` settings (read from env) |
| `shared/epicstaff_storage/storage.py` | Storage SDK for Python nodes in flows |

---

## Backend Interface

`S3StorageBackend` implements `AbstractStorageBackend`:

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

Tests exercise the same interface against `InMemoryStorageBackend` (see `django_app/tests/storage_tests/in_memory_backend.py`), a fake that mirrors S3 semantics without touching a real bucket.

---

## StorageManager

`StorageManager` is an org-aware singleton wrapper around the backend. It is the primary interface used by views.

### Organization isolation

All paths are automatically prefixed with `org_{org_id}/`. The caller works with relative paths only — the org prefix is added/stripped transparently.

### Authorization

The `StorageManager` performs **no** authorization — it only composes org-scoped
keys and delegates to the backend. Access control is enforced at the REST API layer
(`StorageAPIView`): `IsAuthenticated` + `HasOrgPermission(FILES)` + active-org
membership (via `OrgContextService`), with cross-org transfers restricted to
superadmin. See `docs/rbac/organization_scoping.md`.

### Archive auto-extraction

`upload_file()` detects ZIP and TAR archives and extracts them into the target directory automatically. Supported formats: `.zip`, `.tar`, `.tar.gz`, `.tar.bz2`, `.tar.xz`.

Archives extract into a subfolder named after the archive stem (e.g., `data.zip` → `data/`). If the subfolder already exists, the name auto-increments: `data` → `data (1)` → `data (2)`.

Password-protected ZIP files are rejected.

Document formats (`.xlsx`, `.docx`, `.pptx`, `.epub`, `.jar`, `.apk`, `.war`, `.xpi`, etc.) are NOT extracted even though they are ZIP-based.

**Note:** `.jar`, `.war`, and `.ear` also appear in the blocked executable extensions list. Since upload validation runs first, these formats are rejected before the archive detection step. They appear in both lists as a defense-in-depth measure.

### Cross-org operations

- `copy_cross_org(src_org_id, src_path, dst_org_id, dst_path)` -- copy between orgs
- `move_cross_org(src_org_id, src_path, dst_org_id, dst_path)` -- move between orgs (non-atomic: if delete fails after copy, file exists in both)

Cross-org transfers are restricted to **superadmin**, enforced at the API layer
(`StorageAPIView`); the manager itself does not check permissions.

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
- Files were deleted directly in S3 (bypassing the API)
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

The storage server is a core service — it starts with every `docker compose up`. No profiles are needed.

- **`minio`** — RustFS (`rustfs/rustfs:1.0.0`, pinned by digest), volume: `rustfs_data`. The compose service and container are still named `minio`.
- **`minio-init`** — one-shot container (same RustFS image) that creates the bucket with a SigV4-signed `curl` request; restarts on failure until successful

The `django_app` service depends on `minio` being healthy before starting.

---

## Related Documentation

- [Storage API Reference](STORAGE_API_REFERENCE.md) — complete endpoint documentation
- [Storage SDK Reference](STORAGE_SDK_REFERENCE.md) — SDK for Python nodes
- [Storage System Documentation](STORAGE_SYSTEM_DOCUMENTATION.md) — architecture and internals
