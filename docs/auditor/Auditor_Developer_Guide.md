🛠️ Auditor Developer Guide
This guide is task-oriented: how to actually do things in the audit-trail system (EST-3322), not a status summary. If you just need to understand the shape of the data, read `src/auditor/app/index_setup/README.md` (mapping/field decisions) first — this doc assumes you've seen it. For the search request body's field/operator/query-language reference (what you actually type into `filters`/`query`), see [`Filtering_And_Query_Language.md`](./Filtering_And_Query_Language.md).

## Architecture in one paragraph

`crew` and `django_app` emit `SessionAuditEvent`s via the shared `AuditClient` (`src/shared/audit/client.py`), which batches and `POST`s to `auditor`'s ingest route. `auditor` is the *only* thing that talks to the datastore — everything storage-specific hides behind `SessionAuditRepository` (`src/auditor/app/repositories/base.py`). The frontend never touches OpenSearch directly either: it gets a short-lived JWT from `django_app`'s `POST /api/audit/token/`, then calls `auditor`'s browse/export routes with it.

```
crew / django_app → AuditClient → POST /api/audit/events (X-API-Key) → auditor → SessionAuditRepository → OpenSearch
frontend → django_app POST /api/audit/token/ (RBAC) → JWT → auditor GET/POST (Bearer)
```

---

## How to change the storage backend (e.g. OpenSearch → something else)

This is the seam the whole `auditor` service is built around — swapping backends should never touch `crew`, `django_app`, or the shared client/model at all.

1. **Write a new repository**: `src/auditor/app/repositories/<newdb>_repository.py`, implementing `SessionAuditRepository` (`repositories/base.py`):
   - `write_batch(events: list[SessionAuditEvent])` — must be idempotent by `event.id` (re-sending the same id overwrites, never duplicates — this is what makes the client's retry-on-failure path safe).
   - `query(filters: dict, cursor, size)` — `filters` is a backend-agnostic dict (`org_id`, `session_id`, `kind`, `status`, `retention_days`, `search`, ...); translate it into the new DB's native query. Return `(events, next_cursor | None)`.
   - `close()`.
2. **Write a client wrapper**: `src/auditor/app/db/<newdb>_client.py`, mirroring `db/opensearch_client.py` — built during `lifespan` (`app/main.py`), never at import time.
3. **Register it**: add one entry to `_BACKEND_BUILDERS` in `repositories/factory.py`, keyed by whatever value `AUDIT_STORAGE_BACKEND` should be set to.
4. **Replace `index_setup/`** with the new DB's schema-init equivalent (or delete it if the new DB is schemaless) — this runs from `entrypoint.sh` on every boot today (`python -m app.index_setup.runner`), idempotently.
5. **Update compose**: swap the `opensearch` service block for the new DB's in `docker-compose.yaml`/`.dev.yaml`/`.override.yaml`; update the auditor service's env vars.
6. `controllers/{ingest,query,export}_routes.py` need **zero changes** — they only ever call the `SessionAuditRepository` interface.

Before committing to a new backend, confirm it can do the two things that ruled out earlier candidates:
- **Idempotent upsert-by-id** (needed for the retry-safety guarantee above).
- **Real full-text relevance search** over `input`/`output`/`details` (this is why ClickHouse/StarRocks were rejected — columnar OLAP engines with no native inverted index). If the new DB can't do this natively, you're building a second search layer, not doing a swap.

Also re-derive the type-drift answer for `input`/`output`/`details`: these hold arbitrary, type-drifting user-code payloads, and OpenSearch's `flat_object` was chosen specifically to avoid dynamic-mapping type-lock (see `index_setup/README.md`). Whatever the new DB's answer is, it changes what numeric-range filtering on nested keys costs — check that tradeoff explicitly rather than assuming it carries over.

---

## How to change the OpenSearch mapping (while staying on OpenSearch)

- **Adding a field** is additive and safe — extend `0001_create_audit_events_index.json` and issue a plain `PUT audit_events/_mapping` against the live index (the idempotent-create runner won't do this for you; it only creates the index if it's missing).
- **Changing an existing field's type is not a live operation.** OpenSearch cannot reinterpret already-indexed data. You need: a new index with the new mapping → `_reindex` (with a Painless script if the shape changes, not just the type) → alias swap. Never attempt an in-place type change — it's rejected, and the idempotent runner won't notice the drift because the index already exists.
- **No reindex/alias-swap tooling exists yet** in `index_setup/runner.py` (it only does idempotent create-if-missing). The `flat_object` fix applied this session used a dev-only delete+recreate because there was no real data to preserve — do **not** do that once real data exists; build the reindex+alias-swap path first.
- Full field-format rationale (why `error` is `text`+`wildcard`, why `flat_object` for `input`/`output`/`details`, why `event_time` not `record_time`) lives in `index_setup/README.md` — read it before changing any field's type, not just this doc.

---

## How to add a new field to `SessionAuditEvent`

1. Add the field to `src/shared/models/audit/session_audit.py`.
2. Add it to the OpenSearch mapping (`0001_create_audit_events_index.json`) — additive, so a live `PUT _mapping` is enough, no migration needed.
3. Populate it from wherever it's sourced — most likely `SessionAuditWriter` (`src/shared/audit/session_audit_writer.py`) if it's a session/node-level field, or inline at `django_app`'s HITL call site if it's specific to that path.
4. If it should be exportable, it's already covered — `export_routes.py::_to_csv` derives its CSV columns from `SessionAuditEvent.model_fields`, not from the first row, so a new field appears in every export automatically (including an all-empty column on a zero-result export, rather than a broken zero-byte file).

---

## How to add a new filter to the browse routes

`query_routes.py` currently passes a small fixed set of keys (`org_id`, `kind`, `session_id`, `retention_days`, `search`) into `repository.query(filters={...})`. To add a new one:

1. Add the query param to the route function in `query_routes.py`, add it to the `filters` dict passed to `repository.query`.
2. Implement its translation to OpenSearch DSL inside `OpenSearchSessionAuditRepository.query` (`repositories/opensearch_repository.py`) — this is the only place that knows the actual query shape.
3. If the filter targets a dotted path inside `input`/`output`/`details` (the `flat_object` fields), remember: no native numeric range queries there — equality/exists works directly, but `>`/`<` needs an OpenSearch runtime field (Painless script casting the value at query time) or promoting that specific key to a real top-level typed field if it's hot enough to be worth a dedicated column.
4. Keep `filters` backend-agnostic in shape (plain dict, not an OpenSearch query fragment) — that's what keeps the DB-swap seam above real.
5. Update [`Filtering_And_Query_Language.md`](./Filtering_And_Query_Language.md)'s field/op table (and the query-language grammar too, if the new op needs a symbol) and the matching `openapi_examples` in `src/auditor/app/swagger_schemas.py` — both are hand-maintained references, not generated from `KNOWN_FIELDS`.

---

## How the export job lifecycle works

Export is async (`export_routes.py`) because a full-org export can outlive a
single request: `POST /api/audit/export` only creates a job and schedules the
actual query/write as a `BackgroundTasks` task, returning `{"job_id": ...}`
immediately.

- `POST /api/audit/export` — same `filters`/`query` body shape as the browse
  routes (`ExportRequest`, `filters` xor `query`), plus `format` (`json`/`csv`,
  default `json`) and `detail` (`base`/`full`, default `base`). `detail=full`
  re-fetches each matched session's whole tree (deduped by `session_id`) instead
  of returning just the matched rows. Gated by `require_audit_action("export")`.
- `GET /api/audit/export/{job_id}` — poll status; while pending/failed returns
  `{"status": ...}` (`404` if the job isn't found or isn't yours, `500` if it
  failed). Once `completed`, streams the file back as a `FileResponse`
  (`410` if the file already expired off disk). CSV columns come from
  `SessionAuditEvent.model_fields`, not from the first row, so an empty result
  set still produces a valid header-only file rather than a zero-byte one.
- `GET /api/audit/export` — lists the caller's own jobs (pending, completed, or
  failed), scoped to the `org_id`/`user_id` pair from the token's claims. Order
  is **not** guaranteed (backed by a Redis set, not a sorted list).
- `DELETE /api/audit/export/{job_id}` — deletes the job's file (if any) and its
  Redis bookkeeping immediately, instead of waiting for TTL expiry.

All four routes enforce ownership the same way (`_get_owned_job` in
`export_routes.py`): a job is only visible to the `user_id`+`org_id` pair from
its own JWT claims — checked together, not `user_id` alone, so a user who lost
`AUDIT:export` in org A can't still reach an org-A job via a token minted for
org B. A non-owner and a missing job both get a `404`, never a `403`, so
ownership can't be probed from the outside.

### Redis-backed job tracking

Job state and the async result live in two different places for two different
reasons: Redis is fast to poll and self-expiring (no export ever needs to be
queried, cleaned up otherwise); the actual export file goes straight to disk
(`EXPORT_DATA_DIR`, default `/app/export_data`) because a multi-GB org export
doesn't belong in a Redis value. `src/shared/audit/export_jobs.py` centralizes
the key shapes so both `auditor` (job service) and `manager` (TTL sweep) stay
in sync — one job keeps **three** Redis keys alive together, staged onto a
caller-supplied pipeline by `register_job`/`deregister_job` so all three are
written or removed atomically:

- `auditor:export_job:{job_id}` — hash: `status`, `org_id`, `user_id`,
  `created_at`, `expires_at`, `file_path`, `format` (and `error` once failed).
  TTL'd to `EXPORT_FILE_TTL_SECONDS` plus a day of safety margin, so the hash
  outlives the file long enough for `GET`/`DELETE` to still resolve ownership
  and return a clean `410` instead of losing the job record before the sweep
  even runs.
- `auditor:export_jobs_by_expiry` — one sorted set, `job_id` scored by
  `expires_at` epoch seconds. This is what the TTL sweep scans
  (`zrangebyscore(..., max=now)`) instead of doing a Redis-wide key scan.
- `auditor:export_jobs_by_user:{org_id}:{user_id}` — one set per
  (`org_id`, `user_id`) pair of that user's own `job_id`s. This is what backs
  `GET /api/audit/export` (`get_jobs_by_user` → `SMEMBERS` → batched
  `HGETALL` pipeline, one round trip regardless of job count). TTL'd the same
  as the job hash — an abandoned index key expires on its own even if a sweep
  or delete is somehow missed.

`ExportJobService` (`app/services/export_job_service.py`) is the only thing
that reads/writes these keys from `auditor`'s side — `create_job` stages all
three via `register_job`, `mark_done`/`mark_failed` only ever touch the job
hash (and check it still exists first, so a job deleted mid-export can't be
resurrected by a background task finishing late), `delete_job` stages all
three removals via `deregister_job`.

### TTL sweep (`manager`)

`manager`'s `ExportCleanupService` (`src/manager/services/audit_export_cleanup_service.py`)
runs a periodic loop (`sweep_interval_seconds`, default 60s) independent of
`auditor` — it owns cleanup so a restarted/scaled `auditor` doesn't need its
own background task competing over the same keys. Each sweep:

1. `ZRANGEBYSCORE auditor:export_jobs_by_expiry 0 <now>` — every job whose
   `expires_at` has passed.
2. For each due job: reads `file_path`/`org_id`/`user_id` off the job hash,
   deletes the file (falling back to a glob on `{job_id}.*` under
   `EXPORT_DATA_DIR` if the hash itself already expired without `file_path`
   surviving), then calls `deregister_job` to remove all three keys.

If the job hash is already gone by sweep time (its own TTL fired first), the
sweep still removes the now-orphaned entry from the expiry zset so it doesn't
get rescanned forever, but can't clean up the per-user index key in that case
(logged, not fatal — that key has its own TTL and will self-expire).

---

## How to trace one node/session end-to-end for debugging

Both session and node ids are **deterministic** — you can compute the expected id locally and `GET` it directly by `_id`, sidestepping any search-relevance ambiguity:

```bash
# session identity doc id
python -c "import uuid; ns = uuid.UUID('c6e6a7c0-6b3b-4c2b-9f2e-8e6a2a2b6b3a'); print(str(uuid.uuid5(ns, '<session_id>')))"

# node wrapper doc id
python -c "import uuid; ns = uuid.UUID('c6e6a7c0-6b3b-4c2b-9f2e-8e6a2a2b6b3a'); print(str(uuid.uuid5(ns, '<session_id>:<node_name>:<execution_order>')))"

curl -u admin:<password> "https://localhost:9200/audit_events/_doc/<id>"
```

Then range-scan everything else in that session/node with `parent_id`/`session_id`:

```bash
curl -u admin:<password> "https://localhost:9200/audit_events/_search" -H 'content-type: application/json' -d '{"query": {"term": {"parent_id": "<node_or_session_id>"}}}'
```

Remember `kind="session"`/`kind="node"` wrapper docs always have `status: null` — that's permanent, not a sign anything's stuck. The real outcome is on the sibling `kind="event"` row ("Finish"/"Error"/"Session End").

---

## How to run the dev stack locally

`opensearch` + `auditor` are gated behind the `audit` compose profile, so a bare `docker compose up -d` skips them. Name them explicitly:

```bash
docker compose -f docker-compose.yaml --env-file ./.env up -d --build auditor opensearch
```

**If OpenSearch calls start 401-ing**, don't trust the literal value in `.env` — an unescaped `$` in a password (e.g. `OPENSEARCH_PASSWORD=Q7$mR2!vK9@xP4`) gets partially stripped by compose's variable interpolation, so the real runtime value differs from the file. Get the actual value from inside the container before debugging further:

```bash
docker compose exec auditor sh -lc 'echo $OPENSEARCH_PASSWORD'
```

Use *that* value for manual `curl`s. (Fix at the source by escaping as `$$` in `.env` if this keeps biting you.)

There is no `opensearch-dashboards` service in compose. To browse the indices ad-hoc, run the image directly against the `audit` network, mounting `src/auditor/dev/opensearch_dashboards.yml` as its config.

---

## How to add a new `auditor` route

Mirror the existing controllers (`app/controllers/*.py`) — one file per concern, `APIRouter(tags=[...])`, registered in `app/main.py::create_app`. Pick the right auth dependency:
- Producer-only write path → `Depends(verify_ingest_api_key)` (`app/core/security.py`).
- End-user read/export path → `Depends(require_audit_action("read"))` or `Depends(require_audit_action("export"))` — these are independently gated by the token's `actions` claim, so don't reuse one for the other. Always read `org_id`/`retention_days` off `claims`, never from a request parameter — those two must never be client-widenable.
- If you add a new tag/route group, add a matching entry to `OPENAPI_TAGS` in `main.py` so `/docs` documents which auth scheme it uses — that's the single least-obvious thing about this API (two schemes on different route groups).

---

## Key files reference

- `src/shared/models/audit/session_audit.py` — `SessionAuditEvent`.
- `src/shared/audit/client.py` — `AuditClient` (batching/retry/drop).
- `src/shared/audit/session_audit_writer.py` — `SessionAuditWriter` (session/node/event → `SessionAuditEvent` translation, write-once lifecycle).
- `src/crew/services/graph/session_audit_provider.py` — `crew`'s dispatch point.
- `src/django_app/tables/views/audit_token_views.py` — token minting.
- `src/auditor/app/main.py`, `controllers/*.py`, `core/security.py` — the service itself.
- `src/auditor/app/repositories/{base,opensearch_repository,factory}.py` — the backend-swap seam.
- `src/auditor/app/repositories/opensearch_query_compiler.py` — FilterNode AST → OpenSearch DSL.
- `src/auditor/app/filtering/{ast.py,query_language.py}` — the shared FilterNode AST and its text-query parser (see [`Filtering_And_Query_Language.md`](./Filtering_And_Query_Language.md)).
- `src/auditor/app/services/{match_scope.py,duration_filter.py}` — `match_scope` expansion and computed-`duration` filtering.
- `src/auditor/app/services/export_job_service.py`, `src/shared/audit/export_jobs.py` — export job Redis bookkeeping (see "How the export job lifecycle works" above).
- `src/manager/services/audit_export_cleanup_service.py` — the TTL sweep that deletes expired export jobs/files.
- `src/auditor/app/index_setup/` — mapping file, idempotent runner, field-decision README.
