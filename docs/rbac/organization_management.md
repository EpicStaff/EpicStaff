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
existence leak).

## PATCH `/api/admin/organizations/{id}/`

Rename / edit settings. Requires `ORGANIZATIONS.UPDATE` in that org (or
superadmin). Body: `{"name": "Acme International"}` (only `name` today; the
payload is shaped to accept future settings). No-op if the name is unchanged.
An org you're not a member of → **404** (no existence leak); a member lacking
`ORGANIZATIONS.UPDATE` → **403**.

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

---

## Notes for the FE

| Behavior | Note |
|---|---|
| Organizations tab visibility | Show it where the caller holds `ORGANIZATIONS.READ` (or is superadmin). Plain members don't see it, but still see their orgs in the switcher. |
| Rename button | Enable per row where the caller holds `ORGANIZATIONS.UPDATE`. |
| Create / deactivate | Superadmin-only — hide for everyone else. |
| Default org | Identified by an internal `is_default` flag, not by name; renaming is safe. |
| 401 vs 403 | 401 = no/expired credential. 403 = valid credential, insufficient permission. |
