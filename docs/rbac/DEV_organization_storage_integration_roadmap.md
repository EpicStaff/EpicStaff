# Organization × Storage / File-Manager Integration Roadmap

This document is a **planning artifact**, not runtime code. It tracks every
old-organization-ish surface still alive in the codebase, what it currently
does, and which RBAC story takes it over.

The aim is a single grep target for "what touches `Organization` /
`OrganizationUser` / `GraphOrganization` that we still owe work on" so
future stories don't have to re-discover the inventory.

Last updated: Story 4 — 2026-04-29.

---

## Inventory

### `tables/services/storage_service/db_sync.py`

Four inline `Organization.objects.get(id=...)` lookups in functions that
propagate file ops to the DB. Inline imports (violates `feedback_imports.md`).

Owner: **Story 7** (storage refactor) — convert inline to top-level imports;
the lookups themselves become unnecessary once `_resolve_context` returns the
org id from the request.

### `tables/services/storage_service/manager.py`

- Top-level `OrganizationUser` import.
- Line 105: `if not OrganizationUser.objects.filter(org_id=org_id).exists()`
  — any-membership-passes existence check. **Security gap**: a user with no
  membership in the org passes this gate as long as *anyone* has a membership.
- Line 111: `# Future: role = OrganizationUser.objects.get(...).role` TODO.

Owner: **Story 7** for the `(user=request.user, org_id=org_id)` tightening.
**Story 9 / 13** for the role-based access checks.

### `tables/views/storage_views.py:_resolve_context`

Returns hardcoded `(MOCK_USERNAME, default_org.id)`. Two TODOs in the source:
"Refactor! get org_id from request" and "link to User model".

Owner: **Story 7** (active-org switching). `_resolve_context` reads
`X-Organization-Id`, validates the calling user's membership, returns
`(request.user.id, org_id)`. Single-membership users transparently default
to their only org.

> Note: this resolves the default org by name. The canonical anchor is now
> `Organization.is_default` (see the bootstrap/backfill change). When Story 7
> lands it switches to the caller's active org (org id from the request). If
> Story 7 slips, a one-line `filter(is_default=True)` swap hardens it against
> rename in the meantime.

### `tables/views/model_view_sets.py:801` and `tables/import_export/strategies/graph.py:85`

Both `Organization.objects.get(name=DEFAULT_ORGANIZATION_NAME)` lookups for
assigning newly-imported objects to the default org.

Owner: **Story 8** (resource scoping). When Flow / Agent / Tool gain `org_id`
FK, the import flow gets the org from the calling user's active org instead
of guessing the default.

> Note: these resolve the default org by name. The canonical anchor is now
> `Organization.is_default` (see the bootstrap/backfill change). When Story 8
> lands they switch to the caller's active org. If Story 8 slips, a one-line
> `filter(is_default=True)` swap hardens them against rename in the meantime.

### `tables/constants/organization_constants.py`

Exports `DEFAULT_ORGANIZATION_NAME` (still used by `entrypoint.sh`,
`first_setup_service`, `superadmin_bootstrap`) and `MOCK_USERNAME` (used only
by `storage_views._resolve_context`).

Owner: `MOCK_USERNAME` is dropped in **Story 7** when its last consumer goes
away. `DEFAULT_ORGANIZATION_NAME` remains as bootstrap config.

### `tables/views/views.py:RunSession` and `tables/services/session_manager_service.py`

Already migrated in Story 0 to derive membership from `request.user`. The
`RunSession` payload still accepts a `username` field interpreted as email —
to be removed in **Story 8** when payloads align with authenticated context.

### `tables/signals/graph_signals.py`

`post_save` / `post_delete` signals on `GraphOrganization` propagate
user-variable changes; reference `OrganizationUser`. Signal logic is correct
and continues to work as-is. **No story owes work here.**

---

## Concept map

After Story 0, the data model is:

- `Organization` (RBAC, tenant) — ground truth. One row per workspace.
- `OrganizationUser` (RBAC, M2M-with-role) — user × org × role.
- `GraphOrganization` — per-flow, per-org persistent variables and
  user-variable seed template. FK → RBAC `Organization`.
- `GraphOrganizationUser` — per-flow, per-membership user variables. FK →
  RBAC `OrganizationUser`.
- `StorageFile` — per-org file storage. FK → RBAC `Organization`. Currently
  keyed on `(MOCK_USERNAME, default_org.id)` instead of the authenticated
  user / active org.

---

## Migration steps by story

| Step | Owning story | What changes |
|---|---|---|
| Drop `MOCK_USERNAME` from `_resolve_context`; replace with `request.user.id` | Story 7 | Read `X-Organization-Id`, validate membership, return `(request.user.id, org_id)`. |
| Tighten `manager.py:105` membership check | Story 7 | `.filter(user=request.user, org_id=org_id).exists()` instead of `.filter(org_id=org_id).exists()`. Closes the any-membership-passes gap. |
| Convert inline imports in `db_sync.py` to top-level | Story 7 | Per `feedback_imports.md`. Touched anyway during the refactor. |
| Replace `Organization.objects.get(name=DEFAULT_ORGANIZATION_NAME)` in `model_view_sets.py:801` and `import_export/strategies/graph.py:85` | Story 8 | Use the calling user's active org. |
| Add role-based access checks in `manager.py` (TODO at line 111) | Story 9 / 13 | Once `RolePermission` enforcement is wired, `storage_service` gates ops by `(role, resource_type=files, action=READ/WRITE/DOWNLOAD/DELETE)`. |
| Drop legacy `/api/organization-users/` endpoint | Story 5 | Replaced by `/api/admin/users/{id}/memberships/...` with proper RBAC gates. |
| Drop `MOCK_USERNAME` constant entirely | Story 7 | Last consumer goes away. |

---

## Why Story 4 doesn't fix this

- Storage migration depends on `X-Organization-Id` resolution (Story 7),
  which itself depends on a stable RBAC foundation that this story is part
  of.
- Tightening membership checks before Story 5 finalizes user-management
  semantics risks rework.
- Story 4 explicitly limits its blast radius to the org-management surface +
  Bug 1.

---

## Risk callouts for the FE / ops team

- **Storage isolation:** the `MOCK_USERNAME` shortcut means **all storage
  operations today are effectively shared across users in the same org**.
  Files written by one user are visible to all members. Known short-term
  posture; closed in Story 7.
- **Default-org assignment on imports:** Imports / Quickstart create new
  objects in the `DEFAULT_ORGANIZATION_NAME` org regardless of who triggered
  them. Closed in Story 8.
