# Organization Management

Managing `Organization` rows from the admin panel. The surface is **adaptive**:
list / read / rename are permission-driven per org; creating and
(de)activating an organization are platform-level and stay superadmin-only.

Anonymous → 401. Authenticated without the required permission → 403
(`code: permission_denied`). Base URL in examples: `http://localhost:8000`.

---

## Quick reference

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/admin/organizations/` | `ORGANIZATIONS.READ` in ≥1 org (superadmin → all) | List organizations |
| GET | `/api/admin/organizations/{id}/` | `ORGANIZATIONS.READ` in that org, or superadmin | Read one org's settings |
| PATCH | `/api/admin/organizations/{id}/` | `ORGANIZATIONS.UPDATE` in that org, or superadmin | Rename / settings |
| POST | `/api/admin/organizations/` | **superadmin** | Create an organization |
| POST | `/api/admin/organizations/{id}/deactivate/` | **superadmin** | Soft-deactivate |
| POST | `/api/admin/organizations/{id}/reactivate/` | **superadmin** | Re-activate |
| DELETE | `/api/admin/organizations/{id}/` | **superadmin**, JWT only | Permanently delete an organization |

`ORGANIZATIONS.READ` gates only this **admin/settings surface**. Seeing which
orgs you belong to (the org switcher, `/api/profile/` `memberships[]`) comes
from membership and needs no permission. The built-in **Org Admin** role holds
`ORGANIZATIONS` READ + UPDATE for its own org; Members and Viewers hold neither.

---

## Response shape

```json
{
  "id": 7, "name": "Acme Inc", "is_active": true,
  "member_count": 12,
  "created_at": "…", "updated_at": "…",
  "admins": [{"id": 4, "email": "boss@acme.com", "display_name": "Acme Boss", "avatar_url": null}]
}
```

`admins[]` (list endpoint only) is the users holding the built-in **Org Admin**
role in that org, ordered by `joined_at, id`. When an org has zero Org Admins,
**superadmin** viewers see a fallback of the oldest active superadmin (so the
column is never empty for them); delegated admins never see that fallback. The
single-org endpoints (retrieve / create / rename / deactivate / reactivate) omit
`admins`.

---

## GET `/api/admin/organizations/`

**Permission-aware & paginated** (`count/next/previous/results`, page size 50,
max 200). A superadmin sees every org; anyone else sees only the orgs where they
hold `ORGANIZATIONS.READ`.

**Query params:** `is_active` (`true`/`false`; unset → all), `search`
(case-insensitive on name), `org_ids` (comma-separated; a forbidden id →
**403 fail-loud**), `ordering` (`name` | `created_at` | `member_count`, prefix
`-` for descending; default active-first then name), `page` / `page_size`.

`member_count` counts `OrganizationUser` rows across all roles.

## GET `/api/admin/organizations/{id}/`

Read one org's settings. Requires `ORGANIZATIONS.READ` in that org (or
superadmin). An org you can't access → **404 `organization_not_found`** (no
existence leak) — both an org you don't belong to and one where you hold no
`ORGANIZATIONS.READ`.

## PATCH `/api/admin/organizations/{id}/`

Rename / edit settings. Requires `ORGANIZATIONS.UPDATE` in that org (or
superadmin). Body: `{"name": "Acme International"}` (only `name` today; the
payload is shaped to accept future settings). No-op if the name is unchanged.
An org you cannot see → **404** (no existence leak): one you're not a member of,
or one where you hold neither `ORGANIZATIONS.READ` nor `ORGANIZATIONS.UPDATE`. A
member who can see the org (holds `ORGANIZATIONS.READ`) but lacks
`ORGANIZATIONS.UPDATE` → **403**, so a 403 never confirms an org the list won't
show you.

- `400 organization_name_conflict` — case-insensitive duplicate.
- `400 invalid` — empty / whitespace-only / wrong type.

## POST `/api/admin/organizations/` (superadmin)

Body `{"name": "Acme Inc"}` (trimmed; ≤255; non-blank). **201** → the org
(`member_count: 0`). `400 organization_name_conflict` on a case-insensitive
duplicate.

## POST `/api/admin/organizations/{id}/deactivate|reactivate/` (superadmin)

Soft (de)activation; memberships are preserved. Idempotent. Deactivate refuses
to leave the system with zero active organizations → **400
`last_active_organization`**. Unknown id → **404**.

Deactivating an org removes it from delegated admins' scope — only a superadmin
can manage or reactivate an inactive org.

## DELETE `/api/admin/organizations/{id}/` (superadmin)

Permanently removes an organization **and everything it owns**. Irreversible,
and far larger in blast radius than `deactivate` — every flow, session,
agent, crew, tool, LLM and embedding config, secret, knowledge collection,
storage entry, custom role and membership in that organization is destroyed,
along with its files in object storage. Nothing is transferable to another
organization.

Superadmin only, and **JWT only**: API keys are refused (403).

**Query params:** `dry_run` (`true`/`1` → preview and delete nothing;
anything else, including absent, → perform the delete).

Returns **200** in both modes:

```json
{
  "organization_id": 7,
  "affected_resources": {
    "sessions": 340,
    "flow": 12,
    "storage_files": 219
  }
}
```

`affected_resources` maps a short resource name to how many of that
resource the delete removed (or would remove, under a preview). Only
nonzero resources appear. The organization row itself is not listed — it
is identified by `organization_id`. Most of the report is built from
Django's own deletion collector, which counts exactly what the real call
removes for every model it can reach by walking foreign keys from the
organization. Four kinds of rows sit outside that walk and are swept
separately, before the cascade runs: knowledge collection content
(`SourceCollection`, its documents, and any `DocumentContent` left
unreferenced elsewhere — the collector can see the first two but never the
content, since that FK points the other way) and deprecated, non-org-scoped
`Task`/`TemplateAgent`/`RealtimeAgentChat` rows currently linked to the
organization (rather than left behind with their FKs nulled, which is what
the collector alone would do). Their counts are folded into
`affected_resources` identically whether `dry_run` is `true` or `false`, so
for the resources these sweeps cover, a preview and the real delete always
agree. `storage_files` is a single
combined count: the MinIO objects under the organization's storage prefix,
plus the `ConversationRecording` audio files orphaned by the swept
`RealtimeAgentChat` rows.

Running sessions in the organization are asked to stop via the same
best-effort, fire-and-forget mechanism used elsewhere in the platform (Redis
pub/sub, no delivery confirmation); a session owned by a crew replica other
than the one currently listening for it may keep running until that
replica's own reconciliation catches up. This delete does not wait for or
verify that sessions actually stopped, and there is no need to deactivate
the organization first.

- `400 default_organization_not_deletable` — the org carries the
  `is_default` flag. Promote another organization to default first.
- `400 last_organization` — would leave the platform with no active organizations.
- `404 organization_not_found` — unknown id.

Platform-wide default configs are global, not org-scoped. If a superadmin
pointed a default (agent LLM, memory embedding, voice model, …) at a config
owned by this organization, that default is reset to null and must be set
again.

Blockers apply in **both** modes, so `dry_run=true` is a safe pre-flight
check.

Built-in roles are global (`org=NULL`) and survive; only the organization's
own custom roles are removed.

---

## Notes for the FE

| Behavior | Note |
|---|---|
| Organizations tab visibility | Show it where the caller holds `ORGANIZATIONS.READ` (or is superadmin). Plain members don't see it, but still see their orgs in the switcher. |
| Rename button | Enable per row where the caller holds `ORGANIZATIONS.UPDATE`. |
| Create / deactivate | Superadmin-only — hide for everyone else. |
| Delete button | Superadmin-only — hide for everyone else. Always call with `?dry_run=true` first and show the user the row counts before the real call. |
| Delete vs deactivate | Deactivate is reversible and preserves everything. Delete is permanent and destroys all org content. Do not present them as neighbouring actions. |
| Default org | Identified by an internal `is_default` flag, not by name; renaming is safe. |
| 401 vs 403 | 401 = no/expired credential. 403 = valid credential, insufficient permission. |
