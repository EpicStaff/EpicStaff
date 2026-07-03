# Organization Management — Superadmin

Five endpoints for managing `Organization` rows from the superadmin admin
panel. All endpoints require `is_superadmin=True`. Anonymous → 401;
authenticated non-superadmin → 403 (`code: permission_denied`).

Base URL in examples: `http://localhost:8000`.

---

## Quick reference

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/admin/organizations/` | List all organizations with member counts |
| POST | `/api/admin/organizations/` | Create an organization |
| PATCH | `/api/admin/organizations/{id}/` | Rename an organization |
| POST | `/api/admin/organizations/{id}/deactivate/` | Soft-deactivate an organization |
| POST | `/api/admin/organizations/{id}/reactivate/` | Re-activate a deactivated organization |

---

## Common response shape

Every endpoint returns the same payload (single object or list):

```json
{
  "id": 7,
  "name": "Acme Inc",
  "is_active": true,
  "member_count": 12,
  "created_at": "2026-04-29T10:00:00Z",
  "updated_at": "2026-04-29T10:00:00Z"
}
```

The list endpoint (`GET /api/admin/organizations/`) returns this same shape **plus** an `admins` array. The single-org endpoints (create / rename / deactivate / reactivate) keep the shape above unchanged.

`member_count` reflects the count of `OrganizationUser` rows for the org,
across all roles, regardless of `user.is_active`. Story 5 may introduce
`active_member_count` later as a separate field.

## Common error envelopes

Validation envelope (FormValidationError):

```json
{
  "status_code": 400,
  "code": "invalid",
  "message": "FormValidationError: Validation failed",
  "errors": [
    {"field": "name", "value": "", "reason": "This field is required."}
  ]
}
```

Domain-error envelope:

```json
{
  "status_code": 400,
  "code": "organization_name_conflict",
  "message": "OrganizationNameConflictError: An organization with this name already exists."
}
```

Authorization 403 (non-superadmin):

```json
{
  "status_code": 403,
  "code": "permission_denied",
  "message": "Superadmin privileges are required for this action."
}
```

---

## GET `/api/admin/organizations/`

List all organizations. Default returns active and inactive both, ordered
`is_active` desc then `name` asc.

**Query params:**

| Param | Values | Default |
|---|---|---|
| `is_active` | `true` / `false` | unset → returns all |

**curl:**

```bash
curl http://localhost:8000/api/admin/organizations/ \
  -H "Authorization: Bearer $ACCESS"
```

**200:**

```json
[
  {
    "id": 1,
    "name": "Default Organization",
    "is_active": true,
    "member_count": 1,
    "created_at": "...",
    "updated_at": "...",
    "admins": [
      {
        "id": 1,
        "email": "email@a.com",
        "display_name": "John Doe",
        "avatar_url": "http://host/media/avatars/1/abc.png"
      }
    ]
  },
  {
    "id": 7,
    "name": "Acme Inc",
    "is_active": true,
    "member_count": 12,
    "created_at": "...",
    "updated_at": "...",
    "admins": [
      {
        "id": 4,
        "email": "boss@acme.com",
        "display_name": "Acme Boss",
        "avatar_url": null
      }
    ]
  }
]
```

---

## POST `/api/admin/organizations/`

Create an organization.

**Body:** `{"name": "Acme Inc"}`. Trimmed; max 255 chars; must be non-blank.

**curl:**

```bash
curl -X POST http://localhost:8000/api/admin/organizations/ \
  -H "Authorization: Bearer $ACCESS" \
  -H "Content-Type: application/json" \
  -d '{"name":"Acme Inc"}'
```

**201:** the new organization payload (with `member_count: 0`).

**Errors:**

- `400 invalid` — empty / whitespace-only / wrong type → `errors[]` envelope.
- `400 organization_name_conflict` — case-insensitive duplicate.

---

## PATCH `/api/admin/organizations/{id}/`

Rename an organization. Only the `name` field is accepted; `is_active` changes
go through the dedicated deactivate/reactivate endpoints.

**Body:** `{"name": "Acme International"}`.

**200:** the updated organization payload. No-op (no `updated_at` change) if
the new name equals the current name (case-sensitive).

**Errors:** same as POST plus `404` for unknown id.

---

## POST `/api/admin/organizations/{id}/deactivate/`

Soft-deactivate. Sets `is_active=false`. **Memberships are preserved** —
`OrganizationUser` rows stay intact. Reactivation restores access exactly as
it was.

**Body:** none.

**200:** organization payload with `is_active: false`.

**Idempotent:** already-inactive orgs return 200 with the unchanged payload.

**Errors:**

- `400 last_active_organization` — would leave zero active orgs in the system.
- `404` — unknown id.

---

## POST `/api/admin/organizations/{id}/reactivate/`

Inverse of deactivate. No guards — always succeeds for an existing org.

**Body:** none.

**200:** organization payload with `is_active: true`. Idempotent on already-active.

**Errors:** `404` — unknown id.

---

## Behavioral notes for the FE

| Behavior | Note |
|---|---|
| Default org name | The default org is identified by the internal `is_default` flag, **not** by its name. `DEFAULT_ORGANIZATION_NAME` only seeds the org's *initial* name at bootstrap. Renaming is fully safe: the flag (and every resource FK) is unaffected. The default org is still otherwise unprivileged for management ops (rename / deactivate / reactivate), subject only to the last-active-org guard. |
| Inactive orgs in the org switcher | `/api/profile/` filters inactive-org memberships out of `memberships[]` server-side. The user never sees deactivated orgs in their own profile. Admin endpoints still show every membership unchanged. |
| Superadmin org switcher | A superadmin's `/api/profile/` returns every **active** organization in `memberships[]` (each with the `Superadmin` role), so the switcher can reach any org. This list is computed on read from the `Organization` table — the extra entries are **not** `OrganizationUser` rows and do **not** affect `member_count`, which counts stored memberships only. |
| Renaming behavior | Surrounding whitespace is trimmed. Empty / whitespace-only is rejected. Case-insensitive uniqueness — `"Acme"` and `"acme"` collide. |
| 401 vs 403 | 401 = no/expired token (re-login). 403 = valid JWT but `is_superadmin: false` (redirect away from admin panel). |
| `admins[]` in list | Only the list endpoint includes `admins[]`. Items are users with role `Org Admin` for that org, ordered by `joined_at, id`. If an org has zero Org Admins, the field falls back to a single-item list containing the **oldest active superadmin** in the system. The same superadmin may appear under multiple orgs. If no active superadmin exists, the array is `[]`. |

---

## First-setup → name your organization (FE flow)

`POST /api/auth/first-setup/` creates the org with the configured default name
and returns it in the 201 body as `organization.id`. To let the new superadmin
choose a name, the FE calls `PATCH /api/admin/organizations/{organization.id}/`
with `{"name": "..."}`, authenticated with the `access` token from the same
response. If the first-setup response was lost (reload), the id is recoverable
from `GET /api/profile/` → `memberships[]`. No dedicated endpoint exists or is
needed.

---

## Bug 1 fix — `/api/auth/reset-user/` post-condition

After Story 4, a successful `POST /api/auth/reset-user/` always leaves
exactly one `OrganizationUser` row for the new superadmin in the
`DEFAULT_ORGANIZATION_NAME`-named org with role `Superadmin`. If no such org
exists at the time of reset, one is created. `GET /api/profile/` returns
`memberships[]` with that one entry.

This restores the Bug 1 reproduction's expected end state.
