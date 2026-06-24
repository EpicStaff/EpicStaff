# User Management — Superadmin and Org Admin

Eight endpoints managing `User` rows and `OrganizationUser` memberships
for the admin panel surface. Authorization splits two ways:

- `/api/admin/users/...` — superadmin only
- `/api/admin/organizations/{org_id}/users/...` — superadmin globally OR Org Admin of `org_id`

Anonymous → 401; authenticated user without the right role → 403
(`code: permission_denied`).

Base URL in examples: `http://localhost:8000`.

---

## Quick reference

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/admin/users/` | superadmin | List all users (paginated) with their memberships |
| POST | `/api/admin/users/` | superadmin | Create a user; optionally assign to org+role |
| POST | `/api/admin/users/{id}/grant-superadmin/` | superadmin | Set `is_superadmin=True` |
| POST | `/api/admin/users/{id}/revoke-superadmin/` | superadmin | Set `is_superadmin=False` |
| GET | `/api/admin/organizations/{org_id}/users/` | `HasOrgPermission(USERS, READ)` | List members of one organization |
| POST | `/api/admin/organizations/{org_id}/users/` | `HasOrgPermission(USERS, CREATE)` | Create a user and link to organization |
| POST | `/api/admin/organizations/{org_id}/assign-users/` | `HasOrgPermission(USERS, UPDATE)` | Batch-upsert memberships in organization (create or reassign roles) |
| PATCH | `/api/admin/organizations/{org_id}/users/{user_id}/` | `HasOrgPermission(USERS, UPDATE)` | Change a user's role within the organization |
| DELETE | `/api/admin/organizations/{org_id}/users/{user_id}/` | `HasOrgPermission(USERS, DELETE)` | Remove user from organization |

---

## Common response shapes

### `UserResponse` (cross-org)

```json
{
  "id": 42,
  "email": "alice@example.com",
  "display_name": "Alice",
  "is_superadmin": false,
  "is_active": true,
  "created_at": "2026-05-01T10:00:00Z",
  "updated_at": "2026-05-01T10:00:00Z",
  "memberships": [
    {
      "id": 7,
      "organization": {"id": 1, "name": "Acme Inc", "is_active": true},
      "role": {"id": 3, "name": "Member"},
      "joined_at": "2026-05-01T10:00:00Z"
    }
  ]
}
```

### `OrgMemberResponse` (per-org)

```json
{
  "id": 42,
  "email": "alice@example.com",
  "display_name": "Alice",
  "is_superadmin": false,
  "is_active": true,
  "membership": {
    "id": 7,
    "role": {"id": 3, "name": "Member"},
    "joined_at": "2026-05-01T10:00:00Z"
  }
}
```

---

## Common error envelopes

### Validation (`code: invalid`, status 400)

```json
{
  "status_code": 400,
  "code": "invalid",
  "message": "Validation failed",
  "errors": [
    {"field": "email", "value": "not-an-email", "reason": "Enter a valid email address."},
    {"field": "password", "value": "***", "reason": "Password is too short."}
  ]
}
```

### Domain (`code: <typed>`, status 400/404)

```json
{
  "status_code": 400,
  "code": "email_already_exists",
  "message": "A user with this email already exists."
}
```

### Forbidden (`code: permission_denied`, status 403)

```json
{
  "status_code": 403,
  "code": "permission_denied",
  "message": "Superadmin privileges are required for this action."
}
```

The 403 envelope `code` for the `/api/admin/organizations/{org_id}/...`
membership endpoints is now `permission_denied` (previously
`superadmin_or_org_admin_required` — any caller that relied on the
old code must switch). Authorization is resolved through
`HasOrgPermission(USERS, <action>)` and yields the unified
`permission_denied` envelope. See
[roles_and_permissions.md](roles_and_permissions.md) for the
permission resolution model.

---

## Endpoint reference

### `GET /api/admin/users/`

List all users, paginated. Optional filters: `?email=substr&is_superadmin=true|false&organization_id=N`.

```
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/admin/users/?is_superadmin=true&page=1"
```

200 response:
```json
{
  "count": 7,
  "next": "http://localhost:8000/api/admin/users/?page=2",
  "previous": null,
  "results": [ <UserResponse>, ... ]
}
```

Default page size 50, max 200 (`?page_size=200`).

### `POST /api/admin/users/`

Create a User; optionally assign initial org + role.

Request body:
```json
{
  "email": "new@example.com",
  "password": "StrongPass123!",
  "organization_id": 1,
  "role_id": 3
}
```

`organization_id` and `role_id` are optional. If `organization_id` is provided
without `role_id`, the server defaults to the built-in `Member` role.

201 response: `<UserResponse>` (with the new membership reflected in `memberships[]`).

Errors:
- 400 `email_already_exists`
- 400 `invalid_role_assignment`
- 400 `invalid` (validation)
- 404 `organization_not_found`
- 404 `role_not_found`

### `POST /api/admin/users/{id}/grant-superadmin/`

Sets `is_superadmin=True`. Idempotent. Empty body.

200 response: `<UserResponse>` with `is_superadmin: true`.

Errors: 404 `user_not_found`.

### `POST /api/admin/users/{id}/revoke-superadmin/`

Sets `is_superadmin=False`. Idempotent. Empty body. **Last-active-superadmin
guard** — the system requires at least one active superadmin to remain.

200 response: `<UserResponse>` with `is_superadmin: false`.

Errors:
- 400 `last_superadmin` (would leave zero active superadmins)
- 404 `user_not_found`

### `GET /api/admin/organizations/{org_id}/users/`

List members of one org. Optional filters: `?email=substr&role=<role_name>`.

200 response: `[<OrgMemberResponse>, ...]` (unpaginated array).

### `POST /api/admin/organizations/{org_id}/users/`

Create a new User and link them to the organization in one transaction.
For linking already-existing users use the batch
`/assign-users/` endpoint below.

Request body:
```json
{"email": "fresh@example.com", "password": "StrongPass123!", "role_id": 3}
```

`role_id` is optional; defaults to the built-in `Member` role.

201 response: `<OrgMemberResponse>` for the newly created membership.

Errors:
- 400 `email_already_exists`
- 400 `invalid_role_assignment`
- 400 `invalid` (validation: missing fields, weak password, malformed email, …)
- 404 `organization_not_found`, `role_not_found`

### `POST /api/admin/organizations/{org_id}/assign-users/`

Batch-upsert memberships in the organization. For each row:

- No existing `(user_id, org_id)` membership → **create** it with the given role.
- Existing membership, role differs → **update** the role.
- Existing membership, role unchanged → **no-op** (still returned in `updated`).

All-or-nothing in one transaction. Any error rejects the whole batch.

Request body:
```json
{
  "assignments": [
    {"user_id": 1, "role_id": 3},
    {"user_id": 2, "role_id": 2}
  ]
}
```

Rules:
- `assignments` is required, non-empty, at most 100 items.
- Each row requires positive-int `user_id` and `role_id` (no defaults).
- Duplicate `user_id` within the batch is rejected.
- A non-superadmin caller must NOT include their own `user_id`. Superadmin
  bypasses this rule (see "Self-assignment in batch" in behavioral notes).
- The batch must not leave the org with zero Org Admins. The check uses
  the **net effect** across the whole batch — demoting an Org Admin and
  promoting another in the same request is fine.

200 response:
```json
{
  "created": [<OrgMemberResponse>, ...],
  "updated": [<OrgMemberResponse>, ...]
}
```

`created` lists rows whose membership did not exist before this batch.
`updated` lists pre-existing memberships that appeared in the batch
(whether or not the role actually changed). Both arrays preserve
submission order.

Errors:
- 400 `cannot_self_assign` (non-superadmin caller included their own id)
- 400 `last_org_admin` (batch would leave the org with zero Org Admins)
- 400 `invalid_role_assignment` (e.g. global Superadmin role, cross-org custom role)
- 400 `invalid` (validation: empty / >100 / missing fields / duplicate user_id / non-int)
- 400 `membership_already_exists` (race: a parallel writer inserted a `(user, org)`
  row between our pre-check and the batch insert; safe to retry)
- 404 `organization_not_found`, `role_not_found`, `user_not_found`

### `PATCH /api/admin/organizations/{org_id}/users/{user_id}/`

Change a user's role inside an organization.

Request: `{"role_id": 5}`. Idempotent if the new role equals the current role.

**Last-Org-Admin guard**: demoting the only Org Admin in an org is refused.

200 response: `<OrgMemberResponse>` with the new role.

Errors:
- 400 `last_org_admin`
- 400 `invalid_role_assignment`
- 400 `invalid` (validation)
- 404 `user_not_found` (membership doesn't exist), `role_not_found`

### `DELETE /api/admin/organizations/{org_id}/users/{user_id}/`

Remove a user from an organization (delete the membership row; the User row
itself stays).

**Last-Org-Admin guard**: removing the only Org Admin is refused.

204 on success (no body).

Errors:
- 400 `last_org_admin`
- 404 `user_not_found`

---

## Behavioral notes for the FE

| Behavior | Note |
|---|---|
| Default role on create-and-assign | If `role_id` is omitted on `POST /admin/users/` (with `organization_id` set) or on `POST /admin/organizations/{org_id}/users/`, the server defaults to the built-in `Member` role. |
| Pagination | `/admin/users/` is paginated (default 50, max 200). `/admin/organizations/{org_id}/users/` returns an unpaginated array — sort/filter on the client if needed. |
| Self-removal | `DELETE /admin/organizations/{org_id}/users/{user_id}/` is allowed when removing yourself, unless it would trip the last-Org-Admin guard. The FE should still show a confirmation dialog. |
| Self-revoke superadmin | Allowed when not the last active superadmin. FE should warn. |
| Self-assignment in batch | `POST /admin/organizations/{org_id}/assign-users/` rejects an Org Admin caller whose own `user_id` appears in `assignments` (`code: cannot_self_assign`). Superadmin bypasses the rule. For deliberate self-changes use the single-row `PATCH /admin/organizations/{org_id}/users/{user_id}/` endpoint instead. |
| API key authentication | API keys carry exactly the owning user's permissions. A Member-bound API key cannot reach superadmin endpoints. Env-seeded keys (no `created_by`) fail every Story 5 endpoint. |
| Org Admin assigning Org Admin role | Allowed (matches Story 5 D6). Org Admins can promote other members to Org Admin in their own org. |
| 401 vs 403 | 401 = no/expired token (re-login). 403 = valid token but insufficient role. |
| Password redaction | Validation echoes the offending value back, except `password` which is replaced with `***`. |

---

## Future steps

- **Custom roles** — `assert_role_is_assignable` already gates cross-org
  custom roles correctly; the same membership endpoint will accept a custom `role_id`
  once custom-role write endpoints land.
- **Permission cache** — the `PermissionResolver` reserves a cache seam for a
  future Redis layer; the resolver's public API does not change when added.
- **Audit log** — when an audit-log surface lands, drop entries inside
  `UserManagementService` (one place, every flow). Until then, every write
  logs INFO via `loguru` for ops visibility.
