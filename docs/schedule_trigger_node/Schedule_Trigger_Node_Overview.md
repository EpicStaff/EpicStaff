Schedule Trigger Node Overview
==============================

The Schedule Trigger feature allows a graph to start its own execution on a
time-based schedule — either as a one-shot at a specific moment, or as a
recurring run (every N seconds/minutes/hours/days/weeks/months, optionally
restricted to specific weekdays, optionally capped by `end_date_time` or
`max_runs`). Each node carries its own IANA timezone; a node can also be
saved as a **draft** (no schedule yet) and activated later.

The system is split across two services:

- **Django** — persistence, HTTP/API, business guards, `current_runs`
  accounting, signal publishing.
- **Manager** (asyncio worker + APScheduler) — in-memory scheduler of jobs, consumes
  Redis updates, fires callbacks, publishes back to Django.

The two services communicate over a single Redis pub/sub channel whose
name is read from the `SCHEDULE_CHANNEL` env var (default:
`schedule_channel`). There is **no HTTP call** from Manager to Django.

Channel directionality (enforced by code, documented for sanity):

- **Django → Manager**: `node_update` (every `post_save`/`post_delete` echo).
- **Manager → Django**: `run_session` (job fired) and `deactivate` (once-mode
  fired or APScheduler auto-removed the job, e.g. `end_date` reached).

Each side ignores the actions intended for the other direction (Django skips
its own `node_update` echoes; Manager only listens to `node_update`).

1. Data Model
-------------

### ScheduleTriggerNode

Persisted in Django (`tables_scheduletriggernode`). One row per node.

| Column | Type | Notes |
|---|---|---|
| `id` | bigint | PK. Part of the global node sequence. |
| `graph_id` | FK | Graph this node belongs to. `related_name="schedule_trigger_node_list"`. |
| `node_name` | varchar(255) | Unique per graph. |
| `is_active` | bool, default **`False`** | Master on/off switch. Manager only registers jobs for active nodes. New nodes are inactive by default; activation requires a fully configured schedule (see §3). |
| `timezone` | varchar(64), default `"UTC"` | IANA tz name (e.g. `Europe/Kyiv`, `America/New_York`). Per-node — there is **no** server-wide timezone for schedules. All datetime columns are stored in UTC; this field is the rendering / wall-clock context for the API and APScheduler trigger building. |
| `run_mode` | choice, **nullable** | `once` or `repeat`. `null` on drafts. |
| `start_date_time` | datetime, **nullable** | First fire time (UTC). For `once`, the only fire time. `null` on drafts. |
| `every` | int, nullable | Interval number (used only for `repeat`). |
| `unit` | choice, nullable | `seconds` \| `minutes` \| `hours` \| `days` \| `weeks` \| `months`. |
| `weekdays` | JSON array, nullable | Subset of `["mon","tue","wed","thu","fri","sat","sun"]`. Relevant only for `unit in {days, weeks}`. |
| `end_type` | choice, **nullable** | `never` \| `on_date` \| `after_n_runs`. `null` on drafts. |
| `end_date_time` | datetime, nullable | Required when `end_type="on_date"`. Stored in UTC. |
| `max_runs` | int, nullable | Required when `end_type="after_n_runs"`. |
| `current_runs` | int | Read-only counter maintained by the service. Reset to 0 on reactivation or `max_runs` change. Excluded from `content_hash` so runtime increments don't invalidate client-held hashes. |

The model exposes `RunMode`, `TimeUnit`, and `EndType` as `TextChoices`.

### Draft vs configured

A node is a **draft** when `is_active=False` and at least one of `run_mode`,
`start_date_time`, `end_type` is `null`. A draft is persisted and visible via
the API but is **never registered with APScheduler** — Manager skips inactive
nodes outright. To turn a draft into a live schedule, the client sends the
missing schedule fields together with `is_active=true`; the activation gate
(§3) refuses to flip `is_active=true` while the schedule is incomplete.

### Datetime semantics

The wire protocol uses **naive ISO 8601 strings interpreted in the node's
`timezone`** — i.e. wall-clock time. The DB stores all datetimes in UTC.
Translation:

- **Input** (`to_internal_value`): a naive ISO string → localized in the
  node's tz → converted to UTC for storage. An aware ISO string (with offset
  or `Z`) is respected as-is and converted to UTC.
- **Output** (`to_representation`): the stored UTC datetime → converted into
  the node's tz → rendered as a **naive** ISO string (no offset, no `Z`).
  The client gets back the same wall-clock time it sent.

This means changing `timezone` on a node changes how `start_date_time` and
`end_date_time` are *displayed*, but the underlying instants stay the same
unless the client also re-sends the datetime fields.

2. Public API Shape
-------------------

The HTTP serializer intentionally groups all schedule-related columns under a
single nested `schedule` block (with its own `timezone`, `start_date_time`,
`interval`, `end`), while the DB keeps the flat columns. The serializer
translates both directions:

- **Input**: `to_internal_value` pops `schedule`, validates it against
  `_ScheduleConfigInputSerializer`, then flattens `run_mode`, `timezone`,
  `start_date_time`, `every`, `unit`, `weekdays`, `end_type`, `end_date_time`,
  `max_runs` onto the validated data before hitting `ModelSerializer.create`/
  `update`. Per-key partial semantics: only keys actually present in the
  payload's `schedule` block are written; absent keys preserve existing flat
  columns. `schedule: null` clears all flat columns and forces draft.
  Datetime parsing is delegated to
  `tables.services.schedule_trigger_service.parse_naive_to_utc`.
- **Output**: `_ScheduleConfigInputSerializer.to_representation` builds the
  nested block from the flat model columns (via DRF `source="*"`), rendering
  datetimes via
  `tables.services.schedule_trigger_service.format_utc_to_local_naive_iso`.

See `docs/schedule_trigger_node/Schedule_Trigger_Node_Endpoints.md` for the
exact request/response JSON shape and per-endpoint rules.

3. Cross-field Validation
-------------------------

Validation is split between the activation gate (in the serializer's
`validate()`) and `ScheduleTriggerValidator` (DB-bound rules).

### Activation gate

If the request results in `is_active=true`, the node must already have
`run_mode`, `start_date_time`, and `end_type` set (after merging incoming
`attrs` with the existing instance for partial updates). Otherwise the
serializer returns `400` with:

```json
{ "is_active": ["Cannot activate: schedule is not fully configured."] }
```

The gate looks at `self.initial_data["is_active"]` first to distinguish "the
client explicitly set `is_active=true`" from "the client didn't touch it" —
the latter falls through to the instance's current value (or `True` for
brand-new nodes when `schedule` is also provided).

### Schedule-coherence rules (`ScheduleTriggerValidator`)

Enforced before any DB write, on any payload that touches schedule fields
(including drafts, where most fields are simply `null`):

- `timezone` must be a valid IANA tz name (`zoneinfo.ZoneInfo` parseable);
  empty/null is allowed (defaults to `"UTC"`).
- `run_mode="once"` → `every`, `unit`, and `weekdays` must be empty
  (equivalently, `interval` is `null` in the API shape), and `end_type`
  must be `"never"`.
- `run_mode="repeat"` → `every >= 1` is mandatory and `unit` is required.
- `end_type="never"` → `end_date_time` and `max_runs` must both be `null`.
- `end_type="on_date"` → `end_date_time` is mandatory and must be **later
  than** `start_date_time`.
- `end_type="after_n_runs"` → `max_runs >= 1` is mandatory.
- `weekdays` must be a subset of `{mon, tue, wed, thu, fri, sat, sun}` and
  is only allowed when `unit ∈ {days, weeks}`.

4. Service Layer
----------------

### 4.1 Django — `ScheduleTriggerNodeViewSet`

Standard `ModelViewSet` exposing full CRUD at `/api/schedule-trigger-nodes/`.
Filters: `graph`, `is_active`, `run_mode`. Uses
`IdempotentNodeCreateMixin` (upsert on `(graph, node_name)` duplicates) and
`ContentHashPreconditionMixin` (optimistic concurrency via `content_hash`).

### 4.2 Django — `schedule_trigger_post_save_handler` / `schedule_trigger_post_delete_handler`

Django `post_save` / `post_delete` signal handlers on `ScheduleTriggerNode`.
After every commit they build a **flat wire-protocol payload** via
`_flat_schedule_payload(instance)` and publish a message to Redis
`schedule_channel`:

```json
{"action": "node_update", "data": {"action": "create" | "update" | "delete", "node": {...}}}
```

Flat payload keys (in order):

```
id, node_name, graph, is_active, timezone, run_mode, start_date_time,
every, unit, weekdays, end_type, end_date_time, max_runs, current_runs
```

Datetimes are emitted as ISO strings in **UTC** (`isoformat()` on the
stored aware datetime). `timezone` carries the IANA name so Manager can
build APScheduler triggers in the right wall-clock context. The flat
projection is the inter-service contract with Manager — Manager consumers
read these keys directly from the dict; they do not parse the nested HTTP
JSON. `_flat_schedule_payload` must stay in sync with
`ScheduleTriggerNodeRepository.get_all_active_schedule_nodes()` in Manager.

### 4.3 Manager — `ScheduleService`

Manager-side APScheduler service. On startup:

1. `load_schedules_from_django()` — initial sync: reads all active nodes
   directly from the DB via `ScheduleTriggerNodeRepository`
   (`SELECT id, node_name, graph_id, is_active, timezone, run_mode,
   start_date_time, every, unit, weekdays, end_type, end_date_time,
   max_runs, current_runs FROM tables_scheduletriggernode WHERE is_active
   = true`) and registers an APScheduler job for each. Retries indefinitely
   on DB error (repository returns `None`); an empty list is a valid
   terminal state.
2. `scheduler.start()` — starts `AsyncIOScheduler` with `MemoryJobStore`.
3. `_start_redis_listener()` — subscribes to `schedule_channel` (async).

The scheduler has a global `EVENT_JOB_REMOVED` listener: `_on_job_removed`
(see 4.6).

### 4.4 Manager — Trigger building (`_build_trigger`)

Each node's tz is resolved via `_resolve_tz(node_data["timezone"])` (falls
back to the server tz on unknown name, with a log warning). The trigger is
built in that tz so a CronTrigger's "9am" means 9am of the node's wall
clock, and an IntervalTrigger's `start_date` is anchored at the node's
local time.

Two semantics, picked per `(unit, weekdays, every)`:

- **Pure interval** (`IntervalTrigger`, anchored at `start_date_time`):
  - `unit` ∈ `{seconds, minutes, hours}` — for any `every`.
  - `unit ∈ {days}` with `every > 1` and no `weekdays`.
  - `unit == "weeks"` with `every > 1` is implemented as `CronTrigger` with
    `week=*/N` (so it picks every Nth ISO week aligned to the start day),
    not `IntervalTrigger`.

  Example: "every 2 minutes from 19:01" fires at 19:01, 19:03, 19:05 …
  (true delta-from-start; it does **not** snap to the wall clock).

- **Calendar-aligned** (`CronTrigger`, wall-clock H:M of `start_date_time`):
  - `unit == "days"` with `every == 1`.
  - `unit == "days"` with `weekdays` set.
  - `unit == "weeks"` with `every == 1` (with optional `weekdays`; if no
    weekdays, derived from the start date's weekday).
  - `unit == "weeks"` with `every > 1` (cron + `week=*/N`).
  - `unit == "months"` (cron + `month=*/N`, day = start day).

  Example: "Mon at 9am" or "every day at 9am" fires at exactly that
  wall-clock time in the node's tz.

`run_mode == "once"` always uses `DateTrigger(run_date=start_date_time,
timezone=node_tz)`. Returns `None` on missing/invalid config (logged).

### 4.5 Manager — `ScheduleTriggerNodeRepository`

Raw SQL access to `tables_scheduletriggernode` via SQLAlchemy async. Manager
runs under a restricted DB user (`manager_user`, SELECT/UPDATE only) — no
Django ORM is available on this side. The SELECT includes `timezone` so the
trigger builder always has it.

### 4.6 Manager — `self.schedule_nodes` and `self._manual_removals`

Two in-memory structures inside `ScheduleService`:

- `self.schedule_nodes: dict[int, str]` — `node_id → job_id` (where
  `job_id = f"schedule_{node_id}"`). Used to:
  - Find `job_id` by `node_id` in `remove_schedule`.
  - Detect **create vs update** (`node_id in self.schedule_nodes` → update).
  - Reverse-lookup `job_id → node_id` in `_on_job_removed` when
    APScheduler auto-removes a job.

- `self._manual_removals: set[str]` — one-shot flag set. The
  `EVENT_JOB_REMOVED` listener fires on **every** job removal — including
  APScheduler's own `replace_existing=True` path, which removes the old job
  before installing the new one. If we didn't flag these manual removals,
  `_on_job_removed` would publish `deactivate` for a node we just updated.
  Before any known-manual removal (`remove_schedule`, or `replace_existing`
  when the job already exists) we add the `job_id` to `_manual_removals`;
  `_on_job_removed` pops it and exits without publishing.

5. End-to-End Lifecycles
------------------------

### 5.1 Create / Update a schedule node

```
POST|PUT|PATCH /api/schedule-trigger-nodes/…
        │
        ▼
ScheduleTriggerNodeViewSet
        │
        ▼
ScheduleTriggerNodeSerializer (nested `schedule` → flat columns;
                               naive ISO in node tz → UTC)
        │
        ▼
Activation gate + ScheduleTriggerValidator (cross-field rules)
        │
        ▼
Model.save()   →   post_save signal
                         │
                         ▼
       _flat_schedule_payload(instance) →  Redis `schedule_channel`
                                           {"action": "node_update",
                                            "data": {"action": "create"|"update",
                                                     "node": {...flat..., timezone}}}
        │
        ▼ (Manager side, _start_redis_listener)
Listener filters: only `node_update` is consumed (everything else dropped).
Branch on payload:
        │
        ├─ is_active = False  → remove_schedule(node_id)
        │                          (pops from self.schedule_nodes,
        │                           flags job_id in _manual_removals,
        │                           scheduler.remove_job; idempotent if
        │                           already gone)
        │
        └─ is_active = True   → add_schedule(node_data):
                                  • _resolve_tz(node_data["timezone"])
                                  • _build_trigger(node_data, node_tz) picks
                                    DateTrigger / IntervalTrigger /
                                    CronTrigger per §4.4
                                  • if node_id ALREADY in self.schedule_nodes
                                    → add job_id to _manual_removals
                                    (so the replace_existing-driven
                                     EVENT_JOB_REMOVED is ignored)
                                  • self.schedule_nodes[node_id] = job_id
                                  • scheduler.add_job(
                                        id=f"schedule_{node_id}",
                                        replace_existing=True,
                                        …)
```

### 5.2 A job fires (APScheduler callback)

```
APScheduler timer reaches run_date
        │
        ▼ (Manager side)
execute_schedule(node_data):
    • Redis publish {"action": "run_session", "node_id": N}
    • if run_mode == "once":
        Redis publish {"action": "deactivate", "node_id": N}
        (also: APScheduler auto-removes the DateTrigger job, which
         eventually fires _on_job_removed — but the deactivate publish
         here is the authoritative one)
        │
        ▼ (Django side)
schedule_channel_handler (Django pubsub)
        │
        ├─ action=="run_session"  → ScheduleTriggerService.handle_schedule_trigger(node_id)
        │                           (see 5.3)
        │
        ├─ action=="deactivate"   → ScheduleTriggerService.deactivate_node:
        │                           ScheduleTriggerNode.is_active=False via .save()
        │                           → post_save fires
        │                           → Redis node_update{is_active:false}
        │                           → Manager remove_schedule(node_id)
        │                              (idempotent if job already gone)
        │
        └─ action=="node_update"  → skipped (Django→Manager echo of our own publish)
```

### 5.3 `handle_schedule_trigger` (Django, transactional)

Wrapped in `@transaction.atomic`:

1. `SELECT … FOR UPDATE SKIP LOCKED` on `(id=node_id, is_active=True)`.
   Concurrent workers race for the fired node; only one wins, others exit
   silently (row is locked or node is inactive).
2. **Pre-fire guards**:
   - `end_type == "on_date"` and `end_date_time <= now` → flip `is_active`
     to `False` via `.save(update_fields=["is_active", "updated_at"])` and
     exit. The post_save echo carries `is_active=false` to Manager which
     drops the job.
   - `end_type == "after_n_runs"` and `current_runs >= max_runs` → exit
     (the post-fire branch below already handled the actual transition the
     previous time).
3. Start a session:
   `session_manager_service.run_session(graph_id, variables={}, entrypoint=<node_name>)`.
4. Atomically increment `current_runs` via `UPDATE … SET current_runs =
   current_runs + 1` (`F("current_runs") + 1`) — safe under concurrent
   increments.
5. `refresh_from_db()` and check the post-increment limit:
   - If `end_type == "after_n_runs"` and `current_runs >= max_runs` → flip
     `is_active=False` via `.save()` (same as the pre-fire guard). The
     post_save echo to Manager removes the job.

Note: terminal-condition deactivation is intentionally done via
`.save()` (not by publishing `deactivate` directly) so the channel
direction rule (Manager → Django for `deactivate`) is preserved. Manager
sees the `node_update{is_active:false}` echo and drops the job there.

### 5.4 Auto-deactivation at `end_date_time`

For a `repeat` node with `end_type="on_date"`, APScheduler's trigger
eventually returns `None` on the next fire attempt, and APScheduler removes
the job itself. The global `EVENT_JOB_REMOVED` listener
(`_on_job_removed`) fires:

1. If `job_id` is in `self._manual_removals` → pop and return (it was our own
   replace/remove).
2. Otherwise reverse-lookup `job_id → node_id` via `self.schedule_nodes`,
   pop the entry, and publish `{"action": "deactivate", "node_id": N}`.
3. Django receives `deactivate`, sets `is_active=False` via `.save()`, the
   resulting `post_save` re-enters Manager — but since the job is already
   gone and `node_id` was removed from `self.schedule_nodes`,
   `remove_schedule` logs a debug message and exits idempotently.

This is the only path where Manager itself initiates the `is_active=False`
write — all others are initiated by Django.

6. Invariants
-------------

- All datetime columns (`start_date_time`, `end_date_time`) are stored in
  **UTC**. Naive-string handling lives only at the API boundary (serializer
  helpers `parse_naive_to_utc` / `format_utc_to_local_naive_iso` in
  `schedule_trigger_service`). Inside the service layer, datetimes are
  always tz-aware UTC.
- `timezone` is a **per-node display/scheduling context**, not a storage
  format. Changing it does not move the underlying instants — only how they
  render and how Manager builds the next trigger.
- `is_active=true` is permitted only on a fully configured node
  (`run_mode`, `start_date_time`, `end_type` all set). The activation gate
  enforces this on every write that could turn the flag on.
- `self.schedule_nodes` in Manager is **the source of truth for currently
  scheduled jobs** from Manager's perspective. It must be kept in sync with
  APScheduler's internal job store: populated by `add_schedule`, drained by
  `remove_schedule` and `_on_job_removed`.
- `_manual_removals` is a **one-shot** set: every flag pushed in must be
  popped on the next matching `EVENT_JOB_REMOVED`. If you add a flag but
  never triggered a removal (e.g. `scheduler.add_job` raised), discard the
  flag (`add_schedule` does this in its `except` branch).
- `current_runs` is written **only** by Django, and always via
  `UPDATE … SET current_runs = F('current_runs') + 1` or by the serializer's
  custom `update()` (which resets it to 0 on reactivation or `max_runs`
  change). Never mutate it from Python attribute assignment.
- The wire-protocol payload to Redis must stay flat. Manager is not aware of
  the nested HTTP `schedule` block; changing the flat keys requires
  coordinated changes in both `_flat_schedule_payload` (Django) and
  `ScheduleTriggerNodeRepository.get_all_active_schedule_nodes()` (Manager).
- Channel direction is enforced: `node_update` is Django→Manager only,
  `deactivate` and `run_session` are Manager→Django only. Django's
  `redis_pubsub` skips its own `node_update` echo; Manager's listener
  ignores anything that isn't `node_update`.
- `handle_schedule_trigger` must run under `@transaction.atomic` with
  `SELECT FOR UPDATE SKIP LOCKED` — without it, two Django workers
  consuming the same Redis message would double-run the session and
  double-increment `current_runs`.

7. Related Files
----------------

Django:
- `tables/models/graph_models.py` — `ScheduleTriggerNode` model.
- `tables/migrations/0171_scheduletriggernode_timezone_and_more.py` — adds
  `timezone` and makes `run_mode`/`start_date_time`/`end_type` nullable.
- `tables/migrations/0172_alter_scheduletriggernode_is_active.py` — flips
  `is_active` default to `False` for draft semantics.
- `tables/serializers/model_serializers.py` — `ScheduleTriggerNodeSerializer`,
  `_ScheduleConfigInputSerializer`, `_ScheduleIntervalInputSerializer`,
  `_ScheduleEndInputSerializer`.
- `tables/validators/schedule_trigger_validator.py` — `ScheduleTriggerValidator`.
- `tables/views/model_view_sets.py` — `ScheduleTriggerNodeViewSet`.
- `tables/signals/schedule_signals.py` — `_flat_schedule_payload`,
  `schedule_trigger_post_save_handler`,
  `schedule_trigger_post_delete_handler`.
- `tables/services/schedule_trigger_service.py` — `ScheduleTriggerService`,
  `handle_schedule_trigger`, plus the module-level helpers
  `parse_naive_to_utc` and `format_utc_to_local_naive_iso` used by the
  serializer.
- `tables/services/redis_pubsub.py` — Redis listener that routes
  `schedule_channel` messages into `ScheduleTriggerService`.
- `tables/services/graph_bulk_save_service/registry.py` — bulk-save
  registration of the node type.

Manager:
- `services/schedule_service.py` — `ScheduleService`, `add_schedule`,
  `remove_schedule`, `execute_schedule`, `_resolve_tz`, `_build_trigger`,
  `_make_cron`, `_local_start`, `_on_job_removed`, `_start_redis_listener`.
- `repositories/schedule_trigger_repository.py` —
  `ScheduleTriggerNodeRepository.get_all_active_schedule_nodes` (SELECT
  includes `timezone`).
