# Storage Backend Guide

## Overview

The application uses an S3-compatible object storage backend (`S3StorageBackend`) for all file management. The default server is [RustFS](https://github.com/rustfs/rustfs) (Apache-2.0), which replaced MinIO after MinIO stopped publishing images.

`django_app` also uses the storage backend Admin API to mint short-lived, org-scoped credentials for storage-enabled code execution (session, Test-run, and realtime). The sandbox never talks to the Admin API itself — it only ever receives credentials already minted by `django_app`, carried in the execution payload (see **Service Account Credential Management** below). RustFS implements a MinIO-compatible Admin API with documented differences (see **RustFS API Compatibility** below). A plain S3 service without an Admin API (for example AWS S3) can serve files, but storage-enabled code execution will not work.

---

## Quick Start

RustFS starts automatically as a core service (compose service name `storage`). No extra configuration is needed.

```bash
docker compose up
```

The `storage-init` service creates the bucket on first start. The RustFS web console is disabled (`RUSTFS_CONSOLE_ENABLE=false`), because the service is reachable from `sandbox-network`.

---

## Environment Variables

Set in `.env` (generated from `src/env.yaml`). Services build the endpoint as `http(s)://STORAGE_HOST:STORAGE_PORT`.

| Variable | Default | Description |
|----------|---------|-------------|
| `STORAGE_HOST` | `storage` | Hostname of the storage service |
| `STORAGE_PORT` | `9000` | S3 API port (also used by the healthcheck and `storage-init`) |
| `STORAGE_SSL` | `False` | Use HTTPS to reach the storage service |
| `STORAGE_USER` | — | Root access key |
| `STORAGE_PASSWORD` | — | Root secret key |
| `STORAGE_BUCKET` | `epicstaff` | Bucket for file storage |
| `KNOWLEDGE_STORAGE_BUCKET` | `epicstaff-knowledge` | Bucket for knowledge (GraphRAG) data |
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
| `tables/services/storage_service/dataclasses.py` | Data classes: `FileListItem`, `FileInfo`, `FolderInfo`, `FileDownload`, etc. |
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
- `upload_chunks(path, chunks, size_guard, before_commit)` -- store an async stream as multipart parts of `part_size`; `before_commit` runs before the object becomes visible and aborts it by raising
- `upload_stream(path, file)` -- store a readable of unknown size, one part in memory
- `put_bytes(path, data)` -- store bytes in one request
- `download(path)` -- download a file
- `download_range(path, first, last)` -- a byte range and its `Content-Range`
- `unique_key(key, is_folder)` -- the key, or its first free `name (n)` variant
- `delete(path)` -- delete a file or folder
- `mkdir(path)` -- create a folder
- `claim_folder(path)` -- create a folder marker only if none exists (atomic in S3); False if taken
- `move(src, dst)` -- move / rename
- `copy(src, dst)` -- copy into a folder; returns `(key, size)` of every created object, sizes from the store; a failure midway deletes what it created
- `delete_keys(keys)` -- delete exactly these keys (batched `DeleteObjects`, ≤1000 per call)
- `info(path)` -- file metadata
- `head_file(path)` -- file metadata from one short, non-retried request (`None` if absent); used by the agent-write listener
- `exists(path)` -- check existence

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

Uploads go through the streaming endpoint (`tables/views/storage_upload_stream_view.py` →
`storage_service/upload/`), which routes on the file name: `is_archive_name()`
covers `.zip`, `.tar`, `.tgz`, `.taz`, `.tar.gz`, `.tar.bz2`, `.tbz`, `.tbz2`,
`.tar.xz`, `.txz`. The archive itself is capped at `DJANGO_MAX_ARCHIVE_FILE_SIZE`
while it is buffered; its unpacked size has no cap of its own and is bounded
only by the organization's free storage quota.

### Upload limits

A plain file is capped at `DJANGO_MAX_STREAM_UPLOAD_FILE_SIZE` (default `2gb`,
`none` = unlimited), an archive at `DJANGO_MAX_ARCHIVE_FILE_SIZE` (default `50mb`,
must be set); over either the upload fails with `413 upload_too_large`. A
`Content-Length` already over the cap is rejected before the upload waits for a
slot (`upload/admission.py`). So is, with one query (`check_target`), a target
whose parent folder is a file (`409 storage_path_is_file`) and, for a plain file,
replacing an existing file without `FILES:UPDATE` (`403 overwrite_not_permitted`);
the connection is released before the wait, so none is held through it. The
overwrite is authorized again under the org row lock right before the row is
written. The org quota is checked once the slot is held, in
`save_stream` before the body is read, and again on the real byte count under
the org row lock (`record_files_within_quota`).

`GET /api/storage/upload-limits/` (`FILES:READ`) returns what
`upload/limits.py`'s `upload_limits()` assembles: `max_file_size` (null =
unlimited), `max_archive_size`, `free_bytes`, and the sorted `archive_suffixes` /
`document_extensions` from `archive_unpacking/names.py`, so the frontend can apply
`is_archive_name()`'s rule itself. `free_bytes` ignores uploads in flight and does
not credit a file an upload would overwrite; the upload's own 413 is
authoritative. See `STORAGE_API_REFERENCE.md` → Upload Limits.

Before anything is written, `inspect_archive()` makes one pass over the headers:
it confirms the bytes really are an archive (a file with an archive extension
but no ZIP/gzip/bzip2/xz/tar signature is stored as a plain file; one that has
the signature but does not parse is rejected as damaged), and rejects empty or
encrypted archives, symlinks, hardlinks and any other tar member that is not a
plain file or folder (FIFOs, devices, sparse files), ZIP members compressed with
a method `zipfile` cannot inflate (Deflate64, implode, ...), zip-slip names, names
with control characters or blank segments, a file and a folder with the same
name, embedded executables, more than `DJANGO_MAX_ARCHIVE_ENTRIES` entries
(folders included), and a declared unpacked size past the free quota (413).

Tars are opened through `archive_unpacking/safe_readers.py`, never bare `tarfile.open`/`is_tarfile`:
`open_tar()`/`is_tar()` reject a GNU long-name/long-link or pax header over
`MAX_TAR_EXTENDED_HEADER_BYTES` (64 KiB), more than `MAX_TAR_HEADER_CHAIN`
headers stacked on one member, and global pax headers over 64 KiB in total,
before `tarfile` reads them into memory; iteration drops members already passed.
`zip_entry_count()` counts the central directory before `ZipFile` builds an
object per entry, so the entry cap fires first. The knowledge upload validator
(`FileValidator`) does not use these readers yet: it still calls `tarfile` and
`zipfile` directly.

Members are read in archive order through `archive_unpacking/extraction.py`'s `iter_archive_members()`,
and `ArchiveExtractionGuard` (capped at the same free quota) is charged as each
is read, so a ZIP whose declared sizes lie is still stopped mid-member; the
keys written so far are then deleted (exactly those keys, plus the claimed
folder marker, via `delete_keys`; never a name- or prefix-based `delete`, which
could hit a plain file named like the folder). Their uploads to storage overlap
(`upload/archive_members.py`'s `ArchiveMemberUploader`, up to
`DJANGO_ARCHIVE_UPLOAD_CONCURRENCY` at a time).

Archives extract into a subfolder named after the archive stem, deduped as
`<stem> (1)`, `<stem> (2)`, …; the name is claimed with a conditional folder-marker
write (`claim_folder`, `PutObject` with `If-None-Match: *`), so a repeated or
concurrent archive upload never shares a folder: the loser of a race sees the
winner's marker and moves on to the next name. No DB lock is held during these
S3 calls. Empty folders in the archive are kept
as folder markers. All rows of one archive are written with two bulk INSERTs
(`StorageFileSync.on_bulk_upload`) while the org lock is held.

A file larger than `DJANGO_UPLOAD_PART_SIZE` inside an archive is streamed with
`upload_stream()` (parts of that size, one at a time), so memory stays near
`DJANGO_ARCHIVE_UPLOAD_CONCURRENCY` × part size.

Two concurrent uploads to the same path both succeed and the last one to commit
wins; its StorageFile row may carry the other upload's size if their row writes
and commits interleave.

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

### Upgrade step: count files that predate size tracking

Rows written before sizes were tracked have `size = NULL`, which the org quota
counts as 0. Copies are charged at the size S3 reports, but the files themselves
stay uncounted until their rows are refreshed. After deploying, run
`backfill_storage_files` once (below): it upserts every file row with its S3 size.
It also deletes rows it finds no S3 object for, which includes rows of empty
folders (their marker objects are skipped by the listing), so check `--dry-run`
and any graph links to empty folders first.

### `backfill_storage_files` — S3 → DB

Walks the backend for every org, upserts a `StorageFile` row per key (name, size, modified), then deletes the org's rows that match no listed object (`StorageReconciler.reconcile_tree`). Safe to re-run (idempotent).

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
| GET | `/upload-limits/` | Size limits, free quota and archive-name rules of the streaming upload | — |
| POST | `/upload/stream` | Stream one file (raw body, no trailing slash) | `path`, `filename` (query) |
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

## RustFS API Compatibility

RustFS implements a MinIO-compatible Admin API with the following confirmed differences from MinIO:

1. **AEAD ID 2 Encryption in responses** — RustFS returns responses encrypted with AEAD ID 2 (PBKDF2-HMAC-SHA256 + AES-256-GCM), per the official MinIO admin SDK (`madmin-go/encrypt.go`). The `miniopy_async` library only implements AEAD ID 0/1 (Argon2id-based), making it unable to decrypt AEAD ID 2 responses.
   
   The application works around this limitation in `StorageAdminGateway`:
   - `list_service_accounts()` uses `_AdminResponseDecryptor` to decrypt AEAD ID 2 responses from RustFS (PBKDF2 key derivation, same AES-256-GCM cipher the library already implements for AEAD ID 0)
   - `create_service_account()` sidesteps the problem differently: it generates `access_key`/`secret_key` client-side and never reads the (still AEAD-ID-2-encrypted) response at all — the *request* is still encrypted the ordinary way via the library's own `encrypt()` (Argon2id, AEAD ID 0), nothing PBKDF2 about it
   
   This is not a RustFS-specific quirk but a documented third encryption mode in the official MinIO Admin API specification.

2. **Expiration enforcement** — RustFS enforces service account expiration server-side, independent of application-level revocation. Once a service account reaches its expiration timestamp, the storage backend rejects operations from that account regardless of whether `django_app` ever explicitly revoked it.

3. **Cascade deletion on `remove_user`** — Removing a parent user cascades to revoke all service accounts it minted, identical to MinIO behavior.

4. **Error codes** — RustFS returns error codes different from MinIO:
   - `"InvalidArgument"` instead of `"XMinioInvalidObjectName"` for invalid object names
   - `"KeyTooLongError"` for keys exceeding the size limit

---

## Service Account Credential Management

### Temporary credential lifecycle

All minting happens in `django_app`, via the `storage_credentials` app
(`storage_credentials/services/session_credential_service.py` and
`storage_credentials/clients/minio_admin_client.py`'s `StorageAdminGateway`).
**Neither the sandbox nor realtime ever calls the Admin API** — they only ever
receive already-minted credentials, carried on the execution payload
(`CodeTaskData.storage_credentials`), so a compromised sandbox process never
has access to anything capable of minting or revoking storage credentials.

There are three entry points, one per execution context, all funneling
through the same `_mint_and_persist()`:

1. **Session** — `issue_for_session()`, called once from `run_session()` when
   the session graph contains at least one storage-enabled node. One account
   is minted and reused by every storage node in that session.
2. **Test run** — `issue_for_test_run()`, called from the django "Test run"
   endpoint. One account per execution.
3. **Realtime chat** — `issue_for_realtime_chat()`, called once per chat from
   `converter_service.py` when the agent's tools require storage. One account
   is reused for the whole chat, not re-minted per tool call.

Minting itself (`_mint_and_persist()`):

- Builds an IAM policy scoped to `org_<id>/<allowed_paths>` — the allowed
  paths are first validated and org-prefixed by `CredentialScopeValidator`
  (`scope_validator.py`), which fails closed on an empty, malformed, or
  org-escaping path list. This is what stops a session from ever being handed
  a credential wider than the union of its own nodes' declared paths.
- Calls `create_service_account()` with that policy and an expiration derived
  from `STORAGE_TEMP_CREDENTIALS_TTL_HOURS` (default 24h; `<= 0` means no
  expiration — the `expiration` argument is omitted from the request
  entirely, not set to some very long value).
- Persists `(access_key, issued_at)` in the `TemporaryStorageAccount` Postgres
  table (`storage_credentials/models.py`), keyed to exactly one of
  `session` / `python_code_result` / `realtime_agent_chat` via a
  `CheckConstraint`. `secret_key` is never persisted — it only ever travels
  in the in-memory/Redis payload for that one execution.
- Minting is not best-effort: a failure (scope validation, the Admin API
  call, or the DB write) raises and stops the caller (session startup, the
  Test-run request, or realtime chat init) — there is no silent fallback to
  an unscoped or missing credential.

### Revocation

Revocation is also django-only, via `session_credential_service.revoke_for_session()` /
`revoke_for_test_run()` / `revoke_for_realtime_chat()`, each triggered by the
natural end-of-life signal for its owner:

- **Session** — a terminal status (`end`/`error`/`stop`/`expired`) seen by
  `redis_pubsub.py`'s `session_status_handler`.
- **Test run** — the result message on `code_results_handler`.
- **Realtime chat** — `RealtimeAgentChatViewSet.end`.

Each looks up the row by its owner's id, calls
`StorageAdminGateway.delete_service_account()`, and deletes the
`TemporaryStorageAccount` row only after a successful revoke — a failed
revoke leaves the row in place for the manager's daily cleanup job
(`src/manager/services/storage_account_cleanup_service.py`) to retry later.
Revocation failure is logged and swallowed: it never blocks the caller's own
completion (status update, result persistence, or chat teardown).

### Deny Statement Verification

The `Deny` statement in the temporary credential policy (`policies.py`'s `build_temporary_policy`) is the primary defense against self-minting: it blocks `admin:CreateServiceAccount`, `admin:RemoveServiceAccount`, `admin:UpdateServiceAccount` with `Resource: ["arn:aws:s3:::*"]`.

Live-fire verified against RustFS (2026-09-29), both directions:
- With `Resource: ["arn:aws:s3:::*"]` (current code): a temporary credential attempting `admin:CreateServiceAccount` on itself is rejected with `403 AccessDenied`.
- With `Resource: ["*"]` (the pre-EST-3892 form): RustFS rejects the policy document itself at creation time — `400 InvalidArgument: Policy format is invalid` — a temporary credential could not even be issued.

So the ARN form isn't just a safer choice among two working options — it's the only one RustFS accepts at all. This enforces a hard boundary: a minted credential cannot expand its own access or mint credentials that outlive it.

### Data source for credential tracking

Credential tracking is the `TemporaryStorageAccount` Postgres table described
above — not a Django `Secret.metadata` registry (an earlier, now-removed
approach) and not a live query against RustFS's own service-account list.
`StorageAdminGateway.list_service_accounts()` still exists on the client for
completeness but has no current caller; nothing in the credential lifecycle
reads RustFS's account list to decide what to clean up. The manager's cleanup
job only ever deletes `TemporaryStorageAccount` rows whose owner (session /
Test-run / realtime chat) has already reached a terminal state — it never
calls the storage backend itself.

---

## Docker Compose

The storage server is a core service — it starts with every `docker compose up`. No profiles are needed.

- **`storage`** — RustFS (`rustfs/rustfs:1.0.0`, pinned by digest), volume: `rustfs_data`.
- **`storage-init`** — one-shot container (`curlimages/curl:8.22.0`, pinned by digest) that creates the bucket with a SigV4-signed `curl` request; restarts on failure until successful

The `django_app` and `knowledge_new` services depend on `storage` being healthy before starting.

---

## Related Documentation

- [Storage API Reference](STORAGE_API_REFERENCE.md) — complete endpoint documentation
- [Storage SDK Reference](STORAGE_SDK_REFERENCE.md) — SDK for Python nodes
- [Storage System Documentation](STORAGE_SYSTEM_DOCUMENTATION.md) — architecture and internals
