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

`opensearch` + `auditor` are gated behind the `audit` compose profile. Bring them up with the **full explicit chain** — a bare `docker compose up -d --build <service>` silently drops the dev override (port exposure, hot-reload mounts):

```bash
docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.dev.env up -d --build auditor opensearch
```

**If OpenSearch calls start 401-ing**, don't trust the literal value in `.dev.env` — an unescaped `$` in a password (e.g. `OPENSEARCH_PASSWORD=Q7$mR2!vK9@xP4`) gets partially stripped by compose's variable interpolation, so the real runtime value differs from the file. Get the actual value from inside the container before debugging further:

```bash
docker compose exec auditor sh -lc 'echo $OPENSEARCH_PASSWORD'
```

Use *that* value for manual `curl`s. (Fix at the source by escaping as `$$` in `.dev.env` if this keeps biting you.)

A dev-only table browser (`opensearch-dashboards`, pgAdmin-equivalent, port `OPENSEARCH_DASHBOARDS_PORT` default 5601) is available under the same `audit` profile via `docker-compose.dev.yaml` — not present in prod.

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
- `src/auditor/app/index_setup/` — mapping file, idempotent runner, field-decision README.
