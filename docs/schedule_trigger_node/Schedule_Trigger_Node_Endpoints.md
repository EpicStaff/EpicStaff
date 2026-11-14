Schedule Trigger API Endpoints
==============================

HTTP surface for managing Schedule Trigger nodes. The API groups all
schedule-related fields under a single nested `schedule` block on both
request and response. The server internally persists them as flat columns —
you don't need to care about that on the client side.

Common base URL (subject to your deployment): `/api/schedule-trigger-nodes/`.

All requests use `Content-Type: application/json`.

### Datetime convention (read this first)

- All datetime fields inside `schedule` (`start_date_time`, `end.date_time`)
  are **naive ISO 8601 strings** in the node's `timezone`. The server
  localizes input in that tz and stores the value in UTC; on output it
  converts back to the node's tz and renders as a naive ISO string. The
  client gets back the same wall-clock time it sent.
- An aware ISO string (with `±HH:MM` offset or trailing `Z`) is also
  accepted on input and respected as-is — useful for one-off testing or for
  clients that genuinely operate on UTC.
- `timezone` is an **IANA tz name** (e.g. `Europe/Kyiv`,
  `America/New_York`, `UTC`); offsets like `+03:00` are not valid here.

### Drafts

A schedule node can be created without a `schedule` block. It will be
saved with `is_active=false` and all schedule fields `null` — a draft. To
turn the draft into a live schedule, `PATCH` (or `PUT`) the node with the
schedule fields and `is_active=true` in the same request. The server
refuses to set `is_active=true` until the schedule is fully configured
(see §2.3).

---

## 1. List nodes

- **Endpoint**: `GET /api/schedule-trigger-nodes/`
- **Query params** (all optional):
  - `graph` — filter by graph id.
  - `is_active` — `true` / `false`.
  - `run_mode` — `once` / `repeat`.
  - `limit`, `offset` — standard pagination.

### 1.1 Response — `200 OK`

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    { /* full node object, see §2.4 */ }
  ]
}
```

---

## 2. Create a node

- **Endpoint**: `POST /api/schedule-trigger-nodes/`
- **Behavior**: every `POST` creates a new node, even when another node in
  the graph already has the same `node_name` (names may repeat; the node's
  badge number `node_number` tells them apart). A client that retries a
  create must look the node up first and update it by id — the
  `schedule_manager_tool` does exactly that. If `schedule` is omitted, the
  node is created as a draft (`is_active=false`, all schedule fields
  `null`) regardless of the `is_active` value sent by the client.

### 2.1 Request body — fully configured

```js
{
  "node_name": "Schedule Trigger",             // string, free-form label; may repeat within the graph
  "graph": 1,                                  // int, graph id
  "is_active": true,                           // bool; default false
  "metadata": {},                              // object, free-form (UI position, etc.)
  "schedule": {                                // object, optional — omit to create a draft
    "run_mode": "once" | "repeat",
    "timezone": "Europe/Kyiv",                 // IANA tz; default "UTC" if omitted
    "start_date_time": "2026-04-09T12:00:00",  // naive ISO in `timezone` above
    "interval": {                              // object | null (null if run_mode="once")
      "every": 1,                              // int >= 1 (required when run_mode="repeat")
      "unit": "seconds" | "minutes" | "hours" | "days" | "weeks" | "months",
      "weekdays": ["mon","tue","wed","thu","fri","sat","sun"]  // or []
    },
    "end": {                                   // object, ALWAYS present in a configured schedule
      "type": "never" | "on_date" | "after_n_runs",
      "date_time": "2026-12-31T23:59:59",      // naive ISO, required if type="on_date", else null
      "max_runs": 3                            // int >= 1, required if type="after_n_runs", else null
    }
  }
}
```

### 2.1a Request body — draft (no schedule yet)

```json
{
  "node_name": "Schedule Trigger",
  "graph": 1,
  "metadata": { "x": 100, "y": 200 }
}
```

The server will store this as `is_active=false` with `timezone="UTC"`,
`run_mode=null`, `start_date_time=null`, `end_type=null`, etc.

### 2.2 Field descriptions

**Top level**

| Field | Type | Required | Notes |
|---|---|---|---|
| `node_name` | string | yes | Free-form label. May repeat within a graph. |
| `graph` | int | yes | Parent graph id. |
| `is_active` | bool | no (default `false`) | When `false`, the Manager will not register an APScheduler job. Setting `true` requires a fully configured schedule (see §2.3 activation gate). |
| `metadata` | object | no | Free-form (canvas position, icon, color, etc.). |
| `schedule` | object \| null | no | Nested schedule config (see below). Omit on POST to create a draft. Send explicit `null` to **clear** an existing schedule and drop the node back to draft. |

**`schedule`**

| Field | Type | Notes |
|---|---|---|
| `run_mode` | `"once"` \| `"repeat"` \| null | Discriminator. `null` only on drafts. |
| `timezone` | string \| null | IANA tz (e.g. `Europe/Kyiv`). Defaults to `"UTC"`. Validated against `zoneinfo`. |
| `start_date_time` | naive ISO 8601 \| null | Wall-clock first (and only, for `once`) fire time, interpreted in `timezone`. |
| `interval` | object \| null | Recurring settings; `null` for `once` or for drafts. |
| `end` | object \| null | Stop condition. Required for live schedules; `null` allowed on drafts. |

**`schedule.interval`** (only meaningful when `run_mode="repeat"`)

| Field | Type | Notes |
|---|---|---|
| `every` | int ≥ 1 \| null | Interval number. Required when `run_mode="repeat"`. |
| `unit` | choice \| null | `seconds` / `minutes` / `hours` / `days` / `weeks` / `months`. Required when `run_mode="repeat"`. |
| `weekdays` | array of string \| `[]` | Subset of `["mon","tue","wed","thu","fri","sat","sun"]`. Meaningful only for `unit ∈ {days, weeks}`. |

**`schedule.end`**

| Field | Type | Notes |
|---|---|---|
| `type` | `"never"` \| `"on_date"` \| `"after_n_runs"` \| null | Discriminator. `null` only on drafts. |
| `date_time` | naive ISO 8601 \| null | Wall-clock end time in `timezone`. Required when `type="on_date"`, else `null`. |
| `max_runs` | int ≥ 1 \| null | Required when `type="after_n_runs"`, else `null`. |

### 2.3 Cross-field validation rules

**Activation gate** (always evaluated):

- Setting `is_active=true` requires `run_mode`, `start_date_time`, and
  `end_type` to all be non-null in the post-merge state (incoming `attrs`
  overlaid on the existing instance for partial updates). Otherwise the
  server returns:
  ```json
  { "is_active": ["Cannot activate: schedule is not fully configured."] }
  ```

**Schedule-coherence rules** (evaluated whenever schedule fields are
present, including drafts where most fields are simply `null`):

- `timezone` must be a valid IANA tz name (parseable by Python's
  `zoneinfo`). Empty / null defaults to `"UTC"`.
- `run_mode="once"` → `interval` is `null` (equivalently `every`/`unit`/
  `weekdays` are empty) **and** `end.type` must be `"never"`.
- `run_mode="repeat"` → `interval.every >= 1` and `interval.unit` are
  **required**.
- `end.type="never"` → `end.date_time` and `end.max_runs` must both be
  `null`.
- `end.type="on_date"` → `end.date_time` is **required** and must be
  **later than** `schedule.start_date_time`.
- `end.type="after_n_runs"` → `end.max_runs >= 1` is **required**.
- `interval.weekdays` must be a subset of
  `["mon","tue","wed","thu","fri","sat","sun"]` and is only allowed when
  `interval.unit ∈ {"days", "weeks"}`.

A failing rule returns `400 Bad Request` with a structured error (see §8).

### 2.4 Response — `201 Created`

```js
{
  "id": 42,                                    // int, PK (read-only)
  "node_name": "Schedule Trigger",
  "node_number": 3,                            // int, read-only: the node's #N badge in its graph,
                                               // assigned by the server; never sent by clients
  "graph": 1,
  "is_active": true,
  "metadata": {},
  "content_hash": "…",                         // string, read-only
  "created_at": "2026-04-09T12:00:00Z",        // ISO-8601 UTC, read-only
  "updated_at": "2026-04-09T12:00:00Z",        // ISO-8601 UTC, read-only
  "current_runs": 0,                           // int, read-only
                                               // Counter of actual fires. Reset to 0
                                               // on reactivation (is_active: false→true)
                                               // or when max_runs changes.
  "schedule": {
    "run_mode": "once" | "repeat" | null,
    "timezone": "Europe/Kyiv",                 // always present, defaults to "UTC"
    "start_date_time": "2026-04-09T12:00:00",  // naive ISO in `timezone` above
    "interval": {                              // null when run_mode="once" or draft
      "every": 1,
      "unit": "seconds" | "minutes" | "hours" | "days" | "weeks" | "months",
      "weekdays": ["mon", /* … */]             // or [] when unset
    },
    "end": {
      "type": "never" | "on_date" | "after_n_runs" | null,
      "date_time": "2026-12-31T23:59:59",      // naive ISO; null unless type="on_date"
      "max_runs": 3                            // null unless type="after_n_runs"
    }
  }
}
```

A draft response has `is_active: false`, `run_mode: null`,
`start_date_time: null`, `end.type: null`, etc. — `timezone` still defaults
to `"UTC"` and `interval` is rendered as `{"every": null, "unit": null,
"weekdays": []}`.

---

## 3. Retrieve a node

- **Endpoint**: `GET /api/schedule-trigger-nodes/{id}/`
- **Response — `200 OK`**: same object shape as §2.4.

---

## 4. Replace a node (PUT)

- **Endpoint**: `PUT /api/schedule-trigger-nodes/{id}/`
- **Behavior**: full replace. Writable top-level fields are required (per
  DRF semantics). `schedule` is **optional**:
  - Omit `schedule` to leave the existing flat schedule columns untouched.
  - Send `schedule: <object>` to replace it. Only the keys present inside
    `schedule` are written; absent keys preserve current values.
  - Send `schedule: null` to clear the schedule and drop the node back to
    draft (forces `is_active=false`, sets all schedule fields to `null`,
    `timezone` resets to `"UTC"`).
  - The activation gate (§2.3) still applies.
- **Request body**: same as §2.1 / §2.1a.
- **Response — `200 OK`**: same shape as §2.4.

---

## 5. Partially update a node (PATCH)

- **Endpoint**: `PATCH /api/schedule-trigger-nodes/{id}/`
- **Behavior**: updates only the fields you send. `schedule` follows the
  same per-key partial semantics as PUT (above): only the keys present in
  the `schedule` block are written; absent keys preserve current flat
  columns. Inner cross-field rules still apply post-merge.

### 5.1 Example — reactivate and cap at 2 more fires

```json
{
  "is_active": true,
  "schedule": {
    "run_mode": "repeat",
    "timezone": "Europe/Kyiv",
    "start_date_time": "2026-04-22T23:35:00",
    "interval": { "every": 5, "unit": "minutes", "weekdays": [] },
    "end": { "type": "after_n_runs", "date_time": null, "max_runs": 2 }
  }
}
```

Server behavior:

- `is_active: false → true` resets `current_runs` to 0.
- Any change to `max_runs` also resets `current_runs` to 0.

### 5.2 Example — flip off without touching schedule

```json
{ "is_active": false }
```

### 5.3 Example — change only the timezone (re-renders existing wall-clock times in the new tz)

```json
{ "schedule": { "timezone": "America/New_York" } }
```

Note: this does **not** move the underlying instants (`start_date_time` /
`end_date_time` stay the same UTC values). It only changes how they
display on subsequent reads, and the tz APScheduler uses for the next
trigger build.

### 5.4 Example — clear the schedule (back to draft)

```json
{ "schedule": null }
```

Forces `is_active=false`, sets `run_mode`, `start_date_time`, `every`,
`unit`, `weekdays`, `end_type`, `end_date_time`, `max_runs` to `null`, and
resets `timezone` to `"UTC"`.

### 5.5 Response — `200 OK`: same shape as §2.4.

---

## 6. Delete a node

- **Endpoint**: `DELETE /api/schedule-trigger-nodes/{id}/`
- **Response — `204 No Content`**.

Deleting a node also tears down the in-memory APScheduler job on the Manager
side via the `post_delete` signal.

---

## 7. Variations of the `schedule` block

These are concrete examples ready to paste into any request body. All
datetimes are naive ISO strings interpreted in the block's `timezone`.

### 7.1 One-shot run at a specific moment (Kyiv local time)

```json
"schedule": {
  "run_mode": "once",
  "timezone": "Europe/Kyiv",
  "start_date_time": "2026-04-09T12:00:00",
  "interval": null,
  "end": { "type": "never", "date_time": null, "max_runs": null }
}
```

### 7.2 Every N seconds, unbounded (UTC)

```json
"schedule": {
  "run_mode": "repeat",
  "timezone": "UTC",
  "start_date_time": "2026-04-09T12:00:00",
  "interval": { "every": 30, "unit": "seconds", "weekdays": [] },
  "end": { "type": "never", "date_time": null, "max_runs": null }
}
```

Sub-day units are anchored at `start_date_time` (true delta-from-start),
so the first fire is at `12:00:00`, then `12:00:30`, `12:01:00`, …

### 7.3 Every N minutes, capped by runs

```json
"schedule": {
  "run_mode": "repeat",
  "timezone": "Europe/Kyiv",
  "start_date_time": "2026-04-09T19:01:00",
  "interval": { "every": 2, "unit": "minutes", "weekdays": [] },
  "end": { "type": "after_n_runs", "date_time": null, "max_runs": 20 }
}
```

Fires at 19:01, 19:03, 19:05, … (anchored, not snapped to wall clock).

### 7.4 Every N hours, capped by a deadline

```json
"schedule": {
  "run_mode": "repeat",
  "timezone": "Europe/Kyiv",
  "start_date_time": "2026-04-09T09:00:00",
  "interval": { "every": 2, "unit": "hours", "weekdays": [] },
  "end": { "type": "on_date", "date_time": "2026-06-01T00:00:00", "max_runs": null }
}
```

### 7.5 Daily on weekdays at 9:00 local time

```json
"schedule": {
  "run_mode": "repeat",
  "timezone": "Europe/Kyiv",
  "start_date_time": "2026-04-09T09:00:00",
  "interval": {
    "every": 1,
    "unit": "days",
    "weekdays": ["mon", "tue", "wed", "thu", "fri"]
  },
  "end": { "type": "never", "date_time": null, "max_runs": null }
}
```

Calendar-aligned: fires at exactly 09:00 local time on each selected
weekday.

### 7.6 Weekly on selected days

```json
"schedule": {
  "run_mode": "repeat",
  "timezone": "Europe/Kyiv",
  "start_date_time": "2026-04-09T10:00:00",
  "interval": { "every": 1, "unit": "weeks", "weekdays": ["mon", "wed"] },
  "end": { "type": "never", "date_time": null, "max_runs": null }
}
```

### 7.7 Monthly on the start day-of-month

```json
"schedule": {
  "run_mode": "repeat",
  "timezone": "Europe/Kyiv",
  "start_date_time": "2026-04-01T09:00:00",
  "interval": { "every": 1, "unit": "months", "weekdays": [] },
  "end": { "type": "never", "date_time": null, "max_runs": null }
}
```

The day-of-month and the H:M are taken from `start_date_time`.

### 7.8 Every 3 days, anchored

```json
"schedule": {
  "run_mode": "repeat",
  "timezone": "Europe/Kyiv",
  "start_date_time": "2026-04-09T08:00:00",
  "interval": { "every": 3, "unit": "days", "weekdays": [] },
  "end": { "type": "never", "date_time": null, "max_runs": null }
}
```

`days` with `every>1` and no `weekdays` becomes a pure interval anchored at
the start (08:00 every 3rd day from 2026-04-09).

---

## 8. Error responses

Standard DRF / `CustomAPIExeption` error shapes. The two paths render
slightly differently:

- **Activation gate** and DRF field validation errors render with a list
  under each field key:
  ```json
  { "is_active": ["Cannot activate: schedule is not fully configured."] }
  ```
  ```json
  { "schedule": { "end": { "date_time": ["Required for end_type=\"on_date\"."] } } }
  ```
- **`ScheduleTriggerValidator` errors** (timezone / cross-field schedule
  rules) render with a string under the field key:
  ```json
  { "timezone": "Unknown IANA timezone: 'Mars/Olympus'." }
  ```
  ```json
  { "end_date_time": "Must be later than start_date_time." }
  ```
- Non-field-level error:
  ```json
  { "non_field_errors": ["..."] }
  ```
- Model-level conflicts (unique, FK) follow DRF defaults.

Frontends should accept either string or `[string]` under a field key when
parsing this endpoint's errors.

---

## 9. Bulk save integration

Schedule trigger nodes are also part of the graph-wide atomic bulk save
endpoint. See `docs/bulk_save/BULK_SAVE_API.md`.

- **Endpoint**: `POST /api/graphs/{pk}/save/`
- Keys:
  - `schedule_trigger_node_list` — create/update items with the same shape
    as §2.1 (plus optional `id`, and optional `temp_id` for edges in the
    same request). Drafts (no `schedule` block) are accepted.
  - `deleted.schedule_trigger_node_ids` — list of ids to delete.

Use this endpoint when you need to create a schedule node and wire an edge
to another node in the same request; `temp_id` on the schedule node can be
referenced from `edge_list[].start_temp_id` / `end_temp_id`.
