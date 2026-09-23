🛠️ Auditor Developer Guide
This guide is task-oriented: how to actually do things in the audit-trail system (EST-3322), not a status summary. If you just need to understand the shape of the data, read `src/auditor/app/domains/sessions/mappings/README.md` (mapping/field decisions) first — this doc assumes you've seen it. For the code map (the audit-domain abstraction, file-by-file roles, cross-layer contracts), see `wiki/services/auditor.md`. For the search request body's field/operator/query-language reference (what you actually type into `filters`/`query`), see [`Filtering_And_Query_Language.md`](./Filtering_And_Query_Language.md).

## Architecture in one paragraph

`crew` and `django_app` emit `SessionAuditEvent`s via the shared `AuditClient` (`src/shared/audit/client.py`), which batches and `POST`s to `auditor`'s ingest route. `auditor` is the *only* thing that talks to the datastore — everything storage-specific hides behind the generic `AuditRepository` interface (`src/auditor/app/repositories/base.py`), implemented today by `OpenSearchAuditRepository` (`repositories/opensearch_repository.py`). The frontend never touches OpenSearch directly either: it gets a short-lived JWT from `django_app`'s `POST /api/audit/token/`, then calls `auditor`'s browse/export routes with it.

`auditor` is built around a pluggable **audit-domain abstraction**
(`app/domains/base.py::AuditDomain`) — `sessions` (`app/domains/sessions/`)
is the only domain today, but nothing under `app/filtering/`,
`app/repositories/`, or `app/services/` is sessions-specific; a domain
supplies its own field cat1alog, computed fields, match-scope expansion, and
OpenSearch mapping. Every route is mounted under `/api/audit/{domain.name}/...`
so a second domain's routes, repository, and export-job storage never collide
with `sessions`'s (see "How to add a new `auditor` route" below). See
`wiki/services/auditor.md` for the full code map — this doc stays
task-oriented (how to actually do things), not a repeat of that map.

```
crew / django_app → AuditClient → POST /api/audit/sessions/events (X-API-Key) → auditor → AuditRepository (OpenSearchAuditRepository) → OpenSearch
frontend → django_app POST /api/audit/token/ (RBAC) → JWT → auditor GET/POST (Bearer)
```

---

## How to change the storage backend (e.g. OpenSearch → something else)

This is the seam the whole `auditor` service is built around — swapping backends should never touch `crew`, `django_app`, or the shared client/model at all.

1. **Write a new repository**: `src/auditor/app/repositories/<newdb>_repository.py`, implementing `AuditRepository` (`repositories/base.py`):
   - `write_batch(events: list[T])` — must be idempotent by `event.id` (re-sending the same id overwrites, never duplicates — this is what makes the client's retry-on-failure path safe).
   - `query(query: dict, cursor, size)` — `query` is a fully-compiled, backend-native query clause (the output of `repositories/compiler.py::QueryCompiler.compile()` plus the always-injected org_id/retention_days scoping); translate it into the new DB's native query shape. Return `(events, next_cursor | None)`.
   - `close()`.
2. **Write a client wrapper**: `src/auditor/app/db/<newdb>_client.py`, mirroring `db/opensearch_client.py` — built during `lifespan` (`app/main.py`), never at import time.
3. **Register it**: add one entry to `_BACKEND_BUILDERS` in `repositories/factory.py`, keyed by whatever value `AUDIT_STORAGE_BACKEND` should be set to.
4. **Replace `index_setup/`** with the new DB's schema-init equivalent (or delete it if the new DB is schemaless) — this runs from `entrypoint.sh` on every boot today (`python -m app.index_setup.runner`), idempotently, looping `app.domains.registry.DOMAINS` and creating one index per domain's `IndexSpec`.
5. **Update compose**: swap the `opensearch` service block for the new DB's in `docker-compose.yaml`/`.dev.yaml`/`.override.yaml`; update the auditor service's env vars.
6. `controllers/{ingest,query,export}_routes.py` need **zero changes** — they only ever call the `AuditRepository` interface (`repositories/base.py`), never a concrete backend class.

Before committing to a new backend, confirm it can do the two things that ruled out earlier candidates:
- **Idempotent upsert-by-id** (needed for the retry-safety guarantee above).
- **Real full-text relevance search** over `input`/`output`/`details` (this is why ClickHouse/StarRocks were rejected — columnar OLAP engines with no native inverted index). If the new DB can't do this natively, you're building a second search layer, not doing a swap.

Also re-derive the type-drift answer for `input`/`output`/`details`: these hold arbitrary, type-drifting user-code payloads, and OpenSearch's `flat_object` was chosen specifically to avoid dynamic-mapping type-lock (see `app/domains/sessions/mappings/README.md`). Whatever the new DB's answer is, it changes what numeric-range filtering on nested keys costs — check that tradeoff explicitly rather than assuming it carries over.

---

## How to change the OpenSearch mapping (while staying on OpenSearch)

- **Adding a field** is additive and safe — extend `app/domains/sessions/mappings/0001_audit_events.json` and issue a plain `PUT audit_events/_mapping` against the live index (the idempotent-create runner won't do this for you; it only creates the index if it's missing).
- **Changing an existing field's type is not a live operation.** OpenSearch cannot reinterpret already-indexed data. You need: a new index with the new mapping → `_reindex` (with a Painless script if the shape changes, not just the type) → alias swap. Never attempt an in-place type change — it's rejected, and the idempotent runner won't notice the drift because the index already exists.
- **No reindex/alias-swap tooling exists yet** in `index_setup/runner.py` (it only does idempotent create-if-missing, once per domain in `app.domains.registry.DOMAINS`). The `flat_object` fix applied earlier in this refactor used a dev-only delete+recreate because there was no real data to preserve — do **not** do that once real data exists; build the reindex+alias-swap path first.
- Full field-format rationale (why `error` is `text`+`wildcard`, why `flat_object` for `input`/`output`/`details`, why `event_time` not `record_time`) lives in `app/domains/sessions/mappings/README.md` — read it before changing any field's type, not just this doc.

---

## How to add a new field to `SessionAuditEvent`

1. Add the field to `src/shared/models/audit/session_audit.py`.
2. Add it to the OpenSearch mapping (`app/domains/sessions/mappings/0001_audit_events.json`) — additive, so a live `PUT _mapping` is enough, no migration needed.
3. Populate it from wherever it's sourced — most likely `SessionAuditWriter` (`src/shared/audit/writers/session_writer.py`) if it's a session/node-level field, or inline at `django_app`'s HITL call site if it's specific to that path.
4. If it should be exportable, it's already covered — `export_routes.py::_to_csv` derives its CSV columns from `SessionAuditEvent.model_fields`, not from the first row, so a new field appears in every export automatically (including an all-empty column on a zero-result export, rather than a broken zero-byte file).

---

## How to add a new filterable field to the browse routes

The whole search/export request body is one `FilterNode` AST (`app/filtering/ast.py`) — `filters` (the AST directly) and `query` (text that parses to the identical AST via `app/filtering/query_language.py`) are two front-ends for the same tree, compiled by `app/repositories/compiler.py::QueryCompiler` against whatever domain's `FieldCatalog` is in play. There is no per-route fixed key list to extend anymore. To add a new filterable field to the `sessions` domain:

1. Add the field to `KNOWN_FIELDS` in `app/domains/sessions/fields.py` (`FieldSpec(allowed_ops, computed=False, allowed_values=None)`), composing the op-sets from `app/filtering/constants.py` (`TEXT_CONDITION_OPS`, `SELECT_OPS`, `RANGE_OPS`, `FLATTENED_OPS`, ...). If it's a deep-filter alias into `details`/`input`/`output` (like `agent` → `details.agent_id`), add it to `DEEP_FILTER_ALIASES` instead/also.
2. If the field needs bespoke OpenSearch DSL beyond the generic structured/flattened handling already in `QueryCompiler` (`repositories/compiler.py`), add a case there — e.g. `_compile_structured_leaf` for a plain indexed field, `_compile_flattened_leaf` for a dotted `input`/`output`/`details` path.
3. If the field targets a dotted path inside `input`/`output`/`details` (the `flat_object` fields), remember: no native numeric range queries there — equality/exists works directly, but `>`/`<` needs the Painless-script runtime filter (`compiler.py::_compile_numeric_runtime_filter`) or promoting that specific key to a real top-level typed field if it's hot enough to be worth a dedicated column.
4. If the field is **computed** (not translatable to OpenSearch DSL at all — `duration` is the only one today), implement a `ComputedField` in `app/domains/sessions/computed.py` instead of steps 2-3, and add it to `SESSIONS_COMPUTED`. It gets split out of the AST by `app/filtering/computed.py::split_computed_leaves` before the remainder reaches the compiler.
5. Update [`Filtering_And_Query_Language.md`](./Filtering_And_Query_Language.md)'s field/op table (and the query-language grammar too, if the new op needs a symbol) and the matching `SEARCH_REQUEST_EXAMPLES`/field description in `src/auditor/app/domains/sessions/docs.py` — hand-maintained references, generated from `KNOWN_FIELDS` only for the field-name list itself (`build_filters_field_description`), not for the op tables or examples.

This is domain-generic machinery — a second domain would follow the same steps against its own `app/domains/<name>/fields.py`/`computed.py`, never touching `app/filtering/` or `app/repositories/compiler.py` unless it needs genuinely new DSL-compilation behavior no existing domain has needed yet.

---

## How the export job lifecycle works

Export is async (`export_routes.py`) because a full-org export can outlive a
single request: `POST /api/audit/{domain.name}/export` only creates a job and
schedules the actual query/write as a `BackgroundTasks` task, returning
`{"job_id": ...}` immediately.

- `POST /api/audit/{domain.name}/export` — same `filters`/`query`/`match_scope`
  body shape as the browse routes (`ExportRequest`, `filters` xor `query`),
  plus `format` (`json`/`csv`, default `json`). Use
  `match_scope.full_session_history` (or `ancestors`/`children`/`rows_before`)
  if the export needs more than just the matched rows — same `MatchScope`
  toggles the search endpoint uses (`app/domains/sessions/expansion.py`),
  there is no separate `detail` param. Gated by
  `require_audit_action(domain, "export")`.
- `GET /api/audit/{domain.name}/export/{job_id}` — poll status; while
  pending/failed returns `{"status": ...}` (`404` if the job isn't found,
  isn't yours, or belongs to a different domain; `500` if it failed). Once
  `completed`, streams the file back as a `FileResponse` (`410` if the file
  already expired off disk). CSV columns come from
  `SessionAuditEvent.model_fields`, not from the first row, so an empty result
  set still produces a valid header-only file rather than a zero-byte one.
- `GET /api/audit/{domain.name}/export` — lists the caller's own jobs
  (pending, completed, or failed) for that domain, scoped to the
  `domain`/`org_id`/`user_id` triple from the token's claims and route. Order
  is **not** guaranteed (backed by a Redis set, not a sorted list).
- `DELETE /api/audit/{domain.name}/export/{job_id}` — deletes the job's file
  (if any) and its Redis bookkeeping immediately, instead of waiting for TTL
  expiry.

All four routes enforce ownership the same way (`_get_owned_job` in
`export_routes.py`): a job is only visible to the `user_id`+`org_id`+`domain`
triple from its own JWT claims and its own route — org and user are checked
together, not `user_id` alone, so a user who lost `AUDIT:export` in org A
can't still reach an org-A job via a token minted for org B; domain is checked
so a job created under one audit domain can never be downloaded/deleted
through another domain's export routes. A non-owner, a wrong-domain job, and a
missing job all get a `404`, never a `403`, so ownership can't be probed from
the outside.

### Redis-backed job tracking

Job state and the async result live in two different places for two different
reasons: Redis is fast to poll and self-expiring (no export ever needs to be
queried, cleaned up otherwise); the actual export file goes straight to disk
(`AUDITOR_EXPORT_DATA_DIR`, default `/app/export_data`) because a multi-GB org export
doesn't belong in a Redis value. `src/shared/audit/export_jobs.py` centralizes
the key shapes so both `auditor` (job service) and `manager` (TTL sweep) stay
in sync — one job keeps **three** Redis keys alive together, staged onto a
caller-supplied pipeline by `register_job`/`deregister_job` so all three are
written or removed atomically:

- `auditor:export_job:{job_id}` — hash: `domain`, `status`, `org_id`,
  `user_id`, `created_at`, `expires_at`, `file_path`, `format` (and `error`
  once failed). TTL'd to `AUDITOR_EXPORT_FILE_TTL_SECONDS` plus a day of
  safety margin, so the hash outlives the file long enough for `GET`/`DELETE`
  to still resolve ownership and return a clean `410` instead of losing the
  job record before the sweep even runs.
- `auditor:export_jobs_by_expiry` — one sorted set, `job_id` scored by
  `expires_at` epoch seconds. This is what the TTL sweep scans
  (`zrangebyscore(..., max=now)`) instead of doing a Redis-wide key scan.
  Shared across domains — the sweep doesn't need to know which domain a job
  belongs to, only its id, and the hash itself carries `domain` for
  deregistration.
- `auditor:export_jobs_by_user:{domain}:{org_id}:{user_id}` — one set per
  (`domain`, `org_id`, `user_id`) triple of that user's own `job_id`s for that
  domain. Namespaced by domain so one domain's job listing never surfaces
  another domain's jobs. This is what backs `GET /api/audit/{domain.name}/export`
  (`get_jobs_by_user` → `SMEMBERS` → batched `HGETALL` pipeline, one round
  trip regardless of job count). TTL'd the same as the job hash — an
  abandoned index key expires on its own even if a sweep or delete is somehow
  missed.

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
2. For each due job: reads `file_path`/`org_id`/`user_id`/`domain` off the job
   hash and **deletes the file first, unconditionally** (falling back to a
   glob on `{job_id}.*` under `AUDITOR_EXPORT_DATA_DIR` if the hash itself
   already expired without `file_path` surviving) — this must never be
   skipped, since leaking the file on disk forever is exactly what the sweep
   exists to prevent. Only *then*, if `org_id`/`user_id`/`domain` are all
   present, calls `deregister_job` to remove the other two keys.

If the job hash is already gone by sweep time (its own TTL fired first, or the
hash somehow lacks `domain`/`org_id`/`user_id`), the sweep still deletes the
file (via the glob fallback) and removes the now-orphaned entry from the
expiry zset so it doesn't get rescanned forever, but can't clean up the
per-user index key in that case (logged, not fatal — that key has its own TTL
and will self-expire).

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

Routes are built by per-domain factory functions in `app/controllers/*.py`
(`build_search_router(domain)`, `build_export_router(domain)`,
`build_ingest_router(domain)`), assembled into one router per domain by
`app/controllers/domain_router.py::build_domain_router(domain)`, mounted in
`app/main.py::create_app` by looping `app.domains.registry.DOMAINS`. A new
route on an *existing* domain's concern goes inside that concern's factory
function; a genuinely new concern gets its own `build_<x>_router(domain)`
factory following the same shape. Pick the right auth dependency:
- Producer-only write path → `Depends(verify_ingest_api_key)` (`app/core/security.py`).
- End-user read/export path → `Depends(require_audit_action(domain, "read"))` or `Depends(require_audit_action(domain, "export"))` — these are independently gated by the token's `actions` claim, so don't reuse one for the other. Always read `org_id`/`retention_days` off `claims`, never from a request parameter — those two must never be client-widenable.
- If you add a new tag/route group, add a matching entry to `OPENAPI_TAGS` in `app/swagger_schemas.py` (imported into `main.py`) so `/docs` documents which auth scheme it uses — that's the single least-obvious thing about this API (two schemes on different route groups).

---

## Key files reference

- `src/shared/models/audit/base.py` — `BaseAuditEvent` (every domain's event model inherits this).
- `src/shared/models/audit/session_audit.py` — `SessionAuditEvent`, the `sessions` domain's event model.
- `src/shared/audit/client.py` — `AuditClient` (batching/retry/drop).
- `src/shared/audit/writers/{base.py,session_writer.py}` — `BaseAuditWriter` (shared `ABC`/`Generic[T]` base) and `SessionAuditWriter` (session/node/event → `SessionAuditEvent` translation, write-once lifecycle).
- `src/crew/services/graph/session_audit_provider.py` — `crew`'s dispatch point.
- `src/django_app/tables/views/audit_token_views.py` — token minting.
- `src/auditor/app/main.py`, `controllers/*.py`, `core/security.py` — the service itself.
- `src/auditor/app/domains/base.py`, `domains/registry.py` — the audit-domain abstraction (`AuditDomain`, `ApiSpec`, `ScopingPolicy`, the per-domain registry; see `wiki/services/auditor.md` for the full code map).
- `src/auditor/app/domains/sessions/` — the `sessions` domain: `fields.py` (field catalog), `computed.py` (`duration`), `expansion.py` (match-scope), `index.py`/`mappings/` (OpenSearch index), `domain.py` (assembles the `AuditDomain`), `docs.py` (sessions-specific swagger content).
- `src/auditor/app/repositories/{base,opensearch_repository,factory}.py` — the backend-swap seam.
- `src/auditor/app/repositories/compiler.py` — `QueryCompiler`: FilterNode AST → OpenSearch DSL.
- `src/auditor/app/filtering/{ast.py,query_language.py,computed.py,constants.py}` — the shared FilterNode AST, its text-query parser (see [`Filtering_And_Query_Language.md`](./Filtering_And_Query_Language.md)), computed-leaf splitting, and shared op-set constants.
- `src/auditor/app/services/search_pipeline.py` — `SearchPipeline`, the shared validate/split/compile/fetch/expand pipeline behind both search and export.
- `src/auditor/app/services/{matching.py,duration_filter.py}` — match-scope expansion orchestration + `filter_matched` flagging, and computed-field (`duration`) over-fetch filtering.
- `src/auditor/app/services/export_job_service.py`, `src/shared/audit/export_jobs.py` — export job Redis bookkeeping (see "How the export job lifecycle works" above).
- `src/manager/services/audit_export_cleanup_service.py` — the TTL sweep that deletes expired export jobs/files.
- `src/auditor/app/index_setup/runner.py` — idempotent per-domain index creation on boot.
