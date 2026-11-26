🛠️ Auditor Developer Guide
This guide is task-oriented: how to actually do things in the audit-trail system, not a status summary. If you just need to understand the shape of the data, read `src/auditor/app/domains/sessions/mappings/README.md` (mapping/field decisions) first — this doc assumes you've seen it. For the code map (the audit-domain abstraction, file-by-file roles, cross-layer contracts), see `wiki/services/auditor.md`. For the search request body's field/operator/query-language reference (what you actually type into `filters`/`query`), see [`Filtering_And_Query_Language.md`](./Filtering_And_Query_Language.md).

## Architecture in one paragraph

`crew` emits `SessionAuditEvent`s and `django_app` emits `UserActionEvent`s via the shared `AuditClient` (`src/shared/audit/client.py`), which batches and `POST`s to `auditor`'s ingest route. Django captures user actions in `src/django_app/user_audit/` in three layers: the last-edit tracker (`rbac/authorship/last_edit.py`, real changes with detail), explicit hooks (recycle bin, graph-save deletes, auth, governance), and a fallback middleware (`user_audit/middleware.py`) that records one generic action from the route when neither of the others ran for the request. `auditor` is the *only* thing that talks to the datastore — everything storage-specific hides behind the generic `AuditRepository` interface (`src/auditor/app/repositories/base.py`), implemented today by `OpenSearchAuditRepository` (`repositories/opensearch_repository.py`). The frontend never touches OpenSearch directly either: it gets a short-lived JWT from `django_app`'s `POST /api/audit/token/`, then calls `auditor`'s browse/export routes with it.

`auditor` is built around a pluggable **audit-domain abstraction**
(`app/domains/base.py::AuditDomain`) — `sessions` (`app/domains/sessions/`)
and `user_actions` (`app/domains/user_actions/`) today, but nothing under `app/filtering/`,
`app/repositories/`, or `app/services/` is sessions-specific; a domain
supplies its own field catalog, computed fields, match-scope expansion, and
OpenSearch mapping. Every route is mounted under `/api/audit/{domain.name}/...`
so each domain's routes, repository, and export-job storage never collide (see "How to add a new `auditor` route" below). See
`wiki/services/auditor.md` for the full code map — this doc stays
task-oriented (how to actually do things), not a repeat of that map.

```
crew (sessions) / django_app (user_actions) → AuditClient → POST /api/audit/{domain}/events (X-API-Key) → auditor → AuditRepository (OpenSearchAuditRepository) → OpenSearch
frontend → django_app POST /api/audit/token/ (RBAC) → JWT → auditor GET/POST (Bearer)
```

**Switches.** `SESSION_AUDIT_TRAIL_ENABLED` (read by `crew`) and `USER_AUDIT_TRAIL_ENABLED` (read by `django_app`) are independent. `auditor` and `opensearch` start when either is on, and each domain registers (routes, indices) only when its own switch is on, so the other domain's routes answer 404.

**Permission.** Sessions are gated by resource `audit` / token claim `AUDIT`; user actions by resource `user_audit` / claim `USER_AUDIT` (actions `read`, `export`). `POST /api/audit/token/` mints both claims, and refuses only a viewer with neither.

**Adding a domain.** Add the event model under `src/shared/models/audit/`, then a package under `app/domains/<name>/` (`domain.py`, `index.py`, `fields.py`, `schemas.py`, `docs.py`, `mappings/`) and register it in `app/domains/registry.py` behind its own switch. `app/domains/user_actions/` is the flat example (no computed fields, no match-scope); `sessions` is the one with expansion.

---

## How to change the storage backend (e.g. OpenSearch → something else)

This is the seam the whole `auditor` service is built around — swapping backends should never touch `crew`, `django_app`, or the shared client/model at all.

1. **Write a new repository**: `src/auditor/app/repositories/<newdb>_repository.py`, implementing `AuditRepository` (`repositories/base.py`):
   - `write_batch(events: list[T])` — must be idempotent by `event.id` (re-sending the same id overwrites, never duplicates — this is what makes the client's retry-on-failure path safe). On OpenSearch this holds within one receive month: a retry received after midnight UTC on the 1st lands in the next month's index, next to the first copy (see "Cross-month retry duplicates" below).
   - `query(query: dict, cursor, size)` — `query` is a fully-compiled, backend-native query clause (the output of `repositories/compiler.py::QueryCompiler.compile()` plus the always-injected org_id/retention_days scoping); translate it into the new DB's native query shape. Return `(events, next_cursor | None)`.
   - `distinct_values(query: dict, field: str, limit: int)` — the distinct non-empty values of `field` among the events matching the same kind of scoped `query`, ascending, at most `limit` (the first `limit` in that order). Backs the value-list route; on OpenSearch it is one `terms` aggregation ordered by `_key` with `size: 0` hits.
   - `close()`.
2. **Write a client wrapper**: `src/auditor/app/db/<newdb>_client.py`, mirroring `db/opensearch_client.py` — built during `lifespan` (`app/main.py`), never at import time.
3. **Register it**: add one entry to `_BACKEND_BUILDERS` in `repositories/factory.py`, keyed by whatever value `AUDIT_STORAGE_BACKEND` should be set to.
4. **Replace `index_setup/`** with the new DB's schema-init equivalent (or delete it if the new DB is schemaless) — this runs from `entrypoint.sh` on every boot today (`python -m app.index_setup.runner`), idempotently: it installs the ISM retention policies, puts the `audit_events` index template, and drops the legacy single index (see "How audit events are stored and expired" below). The new DB needs its own answer to per-tier expiry, not just schema init.
5. **Update compose**: swap the `opensearch` service block for the new DB's in `docker-compose.yaml`/`.dev.yaml`/`.override.yaml`; update the auditor service's env vars.
6. `controllers/{ingest,query,export}_routes.py` need **zero changes** — they only ever call the `AuditRepository` interface (`repositories/base.py`), never a concrete backend class.

Before committing to a new backend, confirm it can do the two things that ruled out earlier candidates:
- **Idempotent upsert-by-id** (needed for the retry-safety guarantee above).
- **Real full-text relevance search** over `input`/`output`/`details` (this is why ClickHouse/StarRocks were rejected — columnar OLAP engines with no native inverted index). If the new DB can't do this natively, you're building a second search layer, not doing a swap.

Also re-derive the type-drift answer for `input`/`output`/`details`: these hold arbitrary, type-drifting user-code payloads, and OpenSearch's `flat_object` was chosen specifically to avoid dynamic-mapping type-lock (see `app/domains/sessions/mappings/README.md`). Whatever the new DB's answer is, it changes what numeric-range filtering on nested keys costs — check that tradeoff explicitly rather than assuming it carries over.

---

## How audit events are stored and expired

- **Per-tier monthly indices.** Every event is written to `audit_events-{tier}-{yyyy.mm}`, e.g. `audit_events-90d-2026.10` or `audit_events-unlimited-2026.10`. The tier is the event's `retention_days` (stamped by `crew` from the organization's effective audit retention): `30d`, `90d`, `180d`, `365d`, or `unlimited` for 0. A value outside those choices is stored as `unlimited` and logged — never in a shorter tier.
- **Receive-time routing.** The month is when `auditor` received the event, in UTC — the same instant stamped as `record_time` — never `event_time`. A sender's clock skew or a late delivery therefore cannot route an event into a month that is already read-only. Routing lives in `app/repositories/index_routing.py::index_name_for(index, event, received_at)`; `OpenSearchAuditRepository.write_batch` calls it per event with its domain's `IndexSpec`.
- **Read pattern.** Every search and export reads `audit_events-*` (`IndexSpec.read_pattern`) and still filters on `event_time`. The pattern needs the hyphen, so it never matches the legacy `audit_events`.
- **ISM policies.** One policy per tier, `audit-retention-{tier}`, attached through its `ism_template` to `audit_events-{tier}-*`. An index stays `open` (writable) for 33 days from creation, then goes `read_only` (writes blocked, still searchable — deliberately not *closed*, which would make it unsearchable), then is deleted at `retention + 33` days (`30d` → 63d, `90d` → 123d, `180d` → 213d, `365d` → 398d). `unlimited` has no delete state and stays `read_only` forever. A whole month expires at once, so an event can outlive its tier by up to about a month.
- **Runner order** (`app/index_setup/runner.py::setup_indices`, every boot, once per domain in `app.domains.registry.DOMAINS`; each domain's `IndexSpec` supplies the index prefix, the mapping and the ISM policy id prefix): (1) ISM policies — first, because an `ism_template` only attaches to indices created after the policy exists; an unchanged policy is left alone, a changed one is re-PUT with `if_seq_no`/`if_primary_term`; (2) the composable index template `audit_events` over `audit_events-*`, built from `app/domains/sessions/mappings/0001_audit_events.json`; (3) the legacy single index `audit_events` is deleted if it still exists (logged as a warning with its doc count; an alias of that name is left alone). Indices are never pre-created: the first write of a month auto-creates that month's index from the template, so `action.auto_create_index` must stay enabled for `audit_events-*`. During a rolling deploy, a replica still on the old version can recreate `audit_events` (its boot-time runner creates it, and its writes go there); the next boot of a new replica drops it again, and the events written there in the meantime are lost with it.
- **Replicas booting together.** Every step tolerates another replica doing the same work at the same moment: a policy written between our GET and conditional PUT is a 409 that is accepted, the template PUT simply overwrites with the same body, and the legacy index vanishing at any point of the exists/get/count/delete sequence counts as dropped. Replicas of *different* versions are not converged: during a rolling deploy they overwrite each other's ISM policy on every boot until all run the new version, and an index created in that window attaches whichever policy version was stored then — move it afterwards with `change_policy`.
- **Changing a policy.** Bump `_POLICY_REVISION` in `app/index_setup/retention.py` with every change to the policy body: the runner compares only the keys it sends, so a change that only removes a key is otherwise never detected.
- **Changing a policy does not touch existing indices.** The runner updates the stored policy, but every managed index keeps the version it started with; move existing ones with `POST _plugins/_ism/change_policy/audit_events-<tier>-*` and `{"policy_id": "audit-retention-<tier>"}`.

- **Cross-month retry duplicates.** A re-send of an event received in a later month than the first copy (a retry across midnight UTC on the 1st) is written to that month's index, so the event is stored twice with the same `id`. A search can return both copies, and because both have the same sort values (`event_time`, `id`), `search_after` paging can skip one of them at a page boundary. Export de-duplicates by `id`, so an export file contains one copy.

---

## How to change the OpenSearch mapping (while staying on OpenSearch)

- **Adding a field** is additive and safe — extend `app/domains/sessions/mappings/0001_audit_events.json`. The template change reaches only indices created after the next boot; for the existing monthly indices issue a plain `PUT audit_events-*/_mapping` (the runner won't do this for you).
- **Changing an existing field's type is not a live operation.** OpenSearch cannot reinterpret already-indexed data. Indices created after the template change get the new type, but existing months keep the old one, and a search over `audit_events-*` then sees one field with two types. Fixing existing months needs a `_reindex` into new indices (with a Painless script if the shape changes, not just the type). Never attempt an in-place type change — it's rejected.
- **No reindex tooling exists yet** in `index_setup/`. The `flat_object` fix applied earlier in this refactor used a dev-only delete+recreate because there was no real data to preserve — do **not** do that once real data exists; build the reindex path first.
- Full field-format rationale (why `error` is `text`+`wildcard`, why `flat_object` for `input`/`output`/`details`, why `event_time` not `record_time`, why one shard) lives in `app/domains/sessions/mappings/README.md` — read it before changing any field's type, not just this doc.

---

## How to add a new field to `SessionAuditEvent`

1. Add the field to `src/shared/models/audit/session_audit.py`.
2. Add it to the OpenSearch mapping (`app/domains/sessions/mappings/0001_audit_events.json`) — additive, so no migration is needed: new monthly indices pick it up from the template, and a `PUT audit_events-*/_mapping` adds it to the existing ones.
3. Populate it from wherever it's sourced — most likely `SessionAuditWriter` (`src/shared/audit/writers/session_writer.py`) if it's a session/node-level field, or, for a user action, `UserActionEvent` (`src/shared/models/audit/user_action_audit.py`) built in `src/django_app/user_audit/recorder.py`.
4. If it should be exportable, it's already covered — `app/services/export_write_service.py` derives its CSV columns from `SessionAuditEvent.model_fields`, not from the first row, so a new field appears in every export automatically (including an all-empty column on a zero-result export, rather than a broken zero-byte file).

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

## How to list a field's values (filter options)

`GET /api/audit/{domain.name}/values/{field}` returns the distinct values a field holds, so a filter's option list comes from the data and nobody maintains it:

```
GET /auditor/api/audit/user_actions/values/target_type
Authorization: Bearer <token with "USER_AUDIT": ["read"]>

200 {"field": "target_type", "values": ["agent", "flow", "python node"]}
```

- **Which fields.** Only those a domain declares in `AuditDomain.value_fields` (`user_actions`: `target_type`; `sessions`: none, so it has no such route at all). Any other field answers `404`. `AuditDomain.__post_init__` rejects, at import time, a value field that is not a keyword select field of the domain's catalog (unknown, analyzed text, numeric, computed, aliased, or a flattened path): a `terms` aggregation on any of those fails or returns nothing useful.
- **Auth and scope.** Exactly as search: `require_audit_action(domain, "read")`, then `domain.scoping` with the token's `org_id` and `retention_days`, so another org's values and values recorded only before the retention window never appear.
- **Shape.** Distinct non-empty values, sorted ascending, no counts, at most `MAX_LISTED_VALUES` (200, `app/controllers/query_routes.py`). Past the cap the first 200 in sorted order are returned, without a truncation flag.
- **Adding a field.** Add it to the domain's `value_fields` in `app/domains/<name>/domain.py`. The route is mounted by `build_values_router(domain)` only when that set is non-empty.

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

Both session and node ids are **deterministic** — you can compute the expected id locally and look it up with an `ids` query, sidestepping any search-relevance ambiguity:

```bash
# session identity doc id
python -c "import uuid; ns = uuid.UUID('c6e6a7c0-6b3b-4c2b-9f2e-8e6a2a2b6b3a'); print(str(uuid.uuid5(ns, '<session_id>')))"

# node wrapper doc id
python -c "import uuid; ns = uuid.UUID('c6e6a7c0-6b3b-4c2b-9f2e-8e6a2a2b6b3a'); print(str(uuid.uuid5(ns, '<session_id>:<node_name>:<execution_order>')))"

# the month (and tier) of the doc is not known up front, so search the pattern by id
curl -u admin:<password> "https://localhost:9200/audit_events-*/_search" -H 'content-type: application/json' -d '{"query": {"ids": {"values": ["<id>"]}}}'
```

Then range-scan everything else in that session/node with `parent_id`/`session_id`:

```bash
curl -u admin:<password> "https://localhost:9200/audit_events-*/_search" -H 'content-type: application/json' -d '{"query": {"term": {"parent_id": "<node_or_session_id>"}}}'
```

Remember `kind="session"`/`kind="node"` wrapper docs always have `status: null` — that's permanent, not a sign anything's stuck. The real outcome is on the sibling `kind="event"` row ("Finish"/"Error"/"Session End").

---

## How to run the dev stack locally

`opensearch` + `auditor` are gated behind the `auditor` compose profile, so a bare `docker compose up -d` skips them. Name them explicitly:

```bash
docker compose -f docker-compose.yaml --env-file ./.env up -d --build auditor opensearch
```

**If OpenSearch calls start 401-ing**, don't trust the literal value in `.env` — an unescaped `$` in a password (e.g. `OPENSEARCH_PASSWORD=Q7$mR2!vK9@xP4`) gets partially stripped by compose's variable interpolation, so the real runtime value differs from the file. Get the actual value from inside the container before debugging further:

```bash
docker compose exec auditor sh -lc 'echo $OPENSEARCH_PASSWORD'
```

Use *that* value for manual `curl`s. (Fix at the source by escaping as `$$` in `.env` if this keeps biting you.)

There is no `opensearch-dashboards` service in compose. To browse the indices ad-hoc, run the image directly against the compose project's `backend-network`, mounting `src/auditor/dev/opensearch_dashboards.yml` as its config. Pass `OPENSEARCH_USERNAME=admin` and the `OPENSEARCH_PASSWORD` value: `admin` is the only OpenSearch user. `src/auditor/opensearch-entrypoint.sh` replaces the security plugin's demo users (`kibanaserver`, `readall`, …, each with its user name as password) with that one user on every start.

A data volume the demo configuration set up holds the demo users in its security index, together with anything a holder of the demo admin certificate wrote there (see the upgrade note below). So while `opensearch_data` lacks the flag file `.epicstaff-security-config-reset`, the node binds to loopback only and no other container can reach it, and the entrypoint pushes the **whole** security configuration over the index: the image's default `config.yml`, `roles.yml`, `roles_mapping.yml`, `action_groups.yml`, `tenants.yml`, `nodes_dn.yml`, `allowlist.yml`, `whitelist.yml` (the older name of `allowlist.yml`) and `audit.yml`, plus an `internal_users.yml` holding only `admin`, and then clears the SSL dual mode cluster settings `plugins.security_config.ssl_dual_mode_enabled` and its legacy name `opendistro_security_config.ssl_dual_mode_enabled` (see the upgrade note). Once both succeed it writes the flag and restarts OpenSearch inside the container, now on all interfaces; the container itself keeps running. A new data volume takes the same path, so the first start of any install includes that one restart (about a minute longer). Later starts push only `internal_users.yml` and clear SSL dual mode again, so a changed `OPENSEARCH_PASSWORD` takes effect while roles or mappings an operator changed as `admin` stay. Pushing `internal_users.yml` replaces the whole user list, so **every start removes any internal user other than `admin`**, including one an operator created as `admin`. That is by design: EpicStaff needs no other user, and a user it does not know of is how the demo users stayed. A user that has to persist belongs in `write_internal_users` in the entrypoint. The auditor starts as soon as the `opensearch` container does and waits up to 5 minutes for the cluster to report healthy, counted from the `opensearch` container's start; on a slow first start that wait can run out, the auditor exits once, and its `unless-stopped` restart policy starts it again to connect to the restarted node. If a push keeps failing (a full disk makes the security index read-only, for example), the entrypoint retries it, logs an `ERROR` every 240 s, and the healthcheck reports unhealthy; before the reset the node stays on loopback all that time. After the reset, a failing push only leaves a changed `OPENSEARCH_PASSWORD` out of effect.

**Upgrade note for installs that ran before EpicStaff's own security setup.** Until then OpenSearch ran the security plugin's public demo configuration: anyone who could reach it on `backend-network` could log in as a demo user, or use the public `kirk.pem` certificate as a super-admin. The first start after the upgrade **resets the security index** (users, roles, role mappings, tenants, action groups, authentication settings, audit settings) to the defaults above, which undoes anything written there, such as anonymous access, an extra role mapping or a foreign JWT or proxy authentication domain. It also clears the persistent and transient cluster settings `plugins.security_config.ssl_dual_mode_enabled` and `opendistro_security_config.ssl_dual_mode_enabled` (the legacy name, which the security plugin still honours while the new one is unset); either would otherwise keep the transport port 9300 accepting plaintext. Every later start clears both again.

**Rolling back and upgrading again.** The reset runs once per data volume: when it finishes it writes `/usr/share/opensearch/data/.epicstaff-security-config-reset`, and later starts skip it. A version from before this setup ignores that file and runs the demo configuration again, so while it runs `kirk.pem` is a super-admin once more and anything written to the security index then survives the next upgrade (anything written elsewhere does too: review the items listed below). If you start an older version on this data volume, or restore a volume backup taken while one ran, delete the file before starting the current version again, so the reset runs again. From `src/`, with the same `--env-file` you start the stack with: `docker compose run --rm --no-deps --entrypoint rm opensearch -f /usr/share/opensearch/data/.epicstaff-security-config-reset`.

The reset also undoes **legitimate** changes an operator made to the security configuration as `admin` (roles, role mappings, tenants, authentication settings). To keep them, back them up **before** upgrading, while the old container still runs, either with the old admin certificate, `docker compose exec opensearch bash plugins/opensearch-security/tools/securityadmin.sh -backup /tmp/security-backup -icl -nhnv -cacert config/root-ca.pem -cert config/kirk.pem -key config/kirk-key.pem` (then copy it out of the container to a directory outside the repository checkout, since it holds the users' password hashes, and remove it from the container: `docker compose cp opensearch:/tmp/security-backup ~/opensearch-security-backup-$(date +%Y%m%d%H%M%S)` (a new directory each time, so the files are not copied one level down into an existing one), `chmod -R go= ~/opensearch-security-backup-*` and `docker compose exec opensearch rm -rf /tmp/security-backup`), or through the REST API as `admin`: `GET _plugins/_security/api/roles`, `.../rolesmapping`, `.../tenants`, `.../actiongroups`, `.../securityconfig`. After the upgrade, re-apply only entries you recognise as your own, one at a time, through the REST API as `admin`. The backup also holds the demo users and anything a holder of the demo admin certificate wrote, such as an extra role mapping, anonymous access or a JWT or proxy authentication domain in `config`: never push it back with `securityadmin`, and do not copy `config` from it wholesale. Delete the backup once you have re-applied what you need; it holds the users' password hashes.

The reset rewrites only the security index and those two settings. Whatever else a demo-admin holder could have planted stays, so if such an install was reachable by anything you do not trust, review it as `admin` after the upgrade (or, if you suspect a compromise, start from a fresh `opensearch_data` volume):

- Persistent and transient cluster settings: `GET _cluster/settings?flat_settings=true`. Legacy `opendistro_*` keys count too: the plugins still read many of them as fallbacks for the `plugins.*` names
- Ingest and search pipelines, and the indices that run them: `GET _ingest/pipeline`, `GET _search/pipeline`, `GET audit_*/_settings/index.default_pipeline,index.final_pipeline,index.search.default_pipeline?flat_settings=true` (EpicStaff sets none of these)
- Stored scripts: `GET _cluster/state/metadata?filter_path=metadata.stored_scripts`
- Snapshot repositories and snapshots: `GET _snapshot`, `GET _snapshot/<repository>/_all`
- ISM policies (EpicStaff's own are `audit-retention-*` and `audit-user-actions-retention-*`): `GET _plugins/_ism/policies`
- ML connectors (can send data out): `POST _plugins/_ml/connectors/_search` with `{"query":{"match_all":{}}}`
- Alerting monitors and notification channels (can send data out): `GET _plugins/_alerting/monitors/_search`, `GET _plugins/_notifications/configs`
- Index templates, indices and aliases: `GET _index_template`, `GET _cat/indices?v`, `GET _cat/aliases?v`

OpenSearch does not use the security plugin's demo certificates either: those ship in every OpenSearch image, and their `kirk.pem` admin certificate would let any container on `backend-network` read the audit trail without a password. On every start `opensearch-entrypoint.sh` generates a new root CA, node certificate and admin certificate into `/usr/share/opensearch/config/tls`, a tmpfs that only the `opensearch` container mounts, and trusts nothing else. The keys live in memory only: they never reach a disk or a volume and are gone once the container stops. The CA's private key is deleted right after it signs the other two, so no further certificate can be issued from it. Because the set changes on every start, no client can pin the CA: the auditor and OpenSearch Dashboards connect without verifying it. To verify the node from inside the container, use `curl --cacert /usr/share/opensearch/config/tls/root-ca.pem`.

---

## How to add a new `auditor` route

Routes are built by per-domain factory functions in `app/controllers/*.py`
(`build_search_router(domain)`, `build_values_router(domain)`,
`build_export_router(domain)`, `build_ingest_router(domain)`), assembled into one router per domain by
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
- `src/django_app/user_audit/` — `django_app`'s user-action emitter: `sender.py` (background-loop `AuditClient`), `recorder.py`, `actor.py`, `targets.py`, `context.py`, `middleware.py` (fallback layer).
- `src/shared/models/audit/user_action_audit.py` — `UserActionEvent`, the `user_actions` domain's event model.
- `src/auditor/app/domains/user_actions/` — the `user_actions` domain (flat example for a new domain).
- `src/django_app/tables/views/audit_token_views.py` — token minting.
- `src/auditor/app/main.py`, `controllers/*.py`, `core/security.py` — the service itself.
- `src/auditor/app/domains/base.py`, `domains/registry.py` — the audit-domain abstraction (`AuditDomain`, `ApiSpec`, `ScopingPolicy`, the per-domain registry; see `wiki/services/auditor.md` for the full code map).
- `src/auditor/app/domains/sessions/` — the `sessions` domain: `fields.py` (field catalog), `computed.py` (`duration`), `expansion.py` (match-scope), `index.py`/`mappings/` (OpenSearch index family and template mapping), `domain.py` (assembles the `AuditDomain`), `docs.py` (sessions-specific swagger content).
- `src/auditor/app/repositories/{base,opensearch_repository,factory}.py` — the backend-swap seam.
- `src/auditor/app/repositories/compiler.py` — `QueryCompiler`: FilterNode AST → OpenSearch DSL.
- `src/auditor/app/filtering/{ast.py,query_language.py,computed.py,constants.py}` — the shared FilterNode AST, its text-query parser (see [`Filtering_And_Query_Language.md`](./Filtering_And_Query_Language.md)), computed-leaf splitting, and shared op-set constants.
- `src/auditor/app/services/search_pipeline.py` — `SearchPipeline`, the shared validate/split/compile/fetch/expand pipeline behind both search and export.
- `src/auditor/app/services/{matching.py,duration_filter.py}` — match-scope expansion orchestration + `filter_matched` flagging, and computed-field (`duration`) over-fetch filtering.
- `src/auditor/app/services/export_job_service.py`, `src/shared/audit/export_jobs.py` — export job Redis bookkeeping (see "How the export job lifecycle works" above).
- `src/manager/services/audit_export_cleanup_service.py` — the TTL sweep that deletes expired export jobs/files.
- `src/auditor/app/index_setup/runner.py` — boot-time index setup: ISM policies, then the index template, then the legacy-index drop.
- `src/auditor/app/index_setup/retention.py` — the per-tier ISM policies and the index template of a domain's `IndexSpec`.
- `src/auditor/app/repositories/index_routing.py` — `index_name_for`: which tiered monthly index an event is written to.
