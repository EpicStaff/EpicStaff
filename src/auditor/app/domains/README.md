# Adding a new audit domain

An "audit domain" is one event type the `auditor` service knows how to ingest,
search, and export (today: `sessions`). Adding a new one should never require
touching `app/filtering/`, `app/repositories/`, or `app/services/` — those
packages are generic over `AuditDomain` (`app/domains/base.py`). Everything
domain-specific lives under `app/domains/<name>/`.

Use `app/domains/sessions/` as the worked example throughout — every file
below cites its real counterpart there.

## The 5 files a new domain needs

1. **`fields.py`** — the domain's `FieldCatalog` (see the `FieldCatalog`
   Protocol in `app/domains/base.py`): which fields are filterable, what ops
   each allows, and (if the domain has dotted/flattened blob fields like
   sessions' `input`/`output`/`details`) alias resolution.
   Worked example: `app/domains/sessions/fields.py` —
   `KNOWN_FIELDS: dict[str, FieldSpec]`, `DEEP_FILTER_ALIASES`, and
   `SessionFieldCatalog` implementing `is_flattened_path` / `resolve_alias` /
   `field_spec` / `computed_field_names`.

2. **`computed.py`** — any fields that exist only as a derived value, never
   as an indexed column (sessions has exactly one: `duration`, computed from
   paired Start/Finish event timestamps — see
   `app/domains/sessions/computed.py`). Implement the domain's own
   `ComputedField` (Protocol in `app/domains/base.py`) per such field.
   **If the domain has no computed fields, skip this file and pass an empty
   tuple `()` as `AuditDomain.computed`** — nothing else needs it.

3. **`expansion.py`** — match-scope expansion logic: how a matched row
   pulls in related rows (ancestors/children/rows-before/full-history, in
   the sessions case — see `app/domains/sessions/expansion.py`'s
   `SessionTreeExpander`). Implement the domain's own `MatchExpander`
   (Protocol in `app/domains/base.py`).
   **If the domain has no expansion concept, skip this file and use
   `NullExpander()` (from `app/domains/base.py`) as `AuditDomain.expander`**
   — it's a no-op `MatchExpander` built for exactly this case.

4. **`index.py`** — the domain's `IndexSpec`: index name, path to its
   OpenSearch mapping JSON, and sort keys. Worked example:
   `app/domains/sessions/index.py` — `SESSIONS_INDEX`, mapping at
   `app/domains/sessions/mappings/0001_audit_events.json`. Put the new
   domain's own mapping file(s) + a README under
   `app/domains/<name>/mappings/` next to `index.py`, mirroring
   `app/domains/sessions/mappings/`.

5. **`domain.py`** — assembles everything above into one `AuditDomain`
   instance (frozen dataclass, `app/domains/base.py`). Worked example:
   `app/domains/sessions/domain.py` — `SESSIONS = AuditDomain(name="sessions",
   event_model=SessionAuditEvent, index=SESSIONS_INDEX, fields=SESSIONS_FIELDS,
   scoping=DEFAULT_SCOPING, computed=SESSIONS_COMPUTED,
   expander=SessionTreeExpander(), resource="AUDIT")`.
   - `event_model` is the domain's own Pydantic event model, inheriting from
     `BaseAuditEvent` (`src/shared/models/audit/base.py`) — e.g.
     `SessionAuditEvent` (`src/shared/models/audit/session_audit.py`).
   - `scoping` can reuse `DEFAULT_SCOPING` (`app/domains/base.py`) unless the
     domain needs org/retention scoping to behave differently.
   - `resource` is the RBAC resource string checked by
     `app/core/security.py::require_audit_action` (sessions uses `"AUDIT"`).

If the domain also needs its own swagger/OpenAPI documentation content (field
list description, request examples, endpoint descriptions), add
`app/domains/<name>/docs.py` — see `app/domains/sessions/docs.py` for the
pattern (`app/swagger_schemas.py` only holds domain-free content: tags, the
generic AST/query-language grammar).

## Wiring it into the registry

Add one entry to `app/domains/registry.py`:

```python
from app.domains.<name>.domain import <NAME>

DOMAINS: dict[str, AuditDomain] = {
    SESSIONS.name: SESSIONS,
    <NAME>.name: <NAME>,
}
```

That's it. `app/main.py` loops `DOMAINS.values()` to mount each domain's
search/export/ingest routes (`app/controllers/domain_router.py`) and
`app/index_setup/runner.py` loops the same registry to create each domain's
OpenSearch index on boot — neither file needs a new domain-specific branch.
