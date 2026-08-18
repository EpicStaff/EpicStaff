# User & Membership Management

Two surfaces manage people:

- **Memberships** — `/api/admin/memberships/` — permission-driven, cross-org.
  Manage who belongs to an organization and what role they hold, in every org
  where you hold the `USERS` permission. A custom role carrying `USERS`
  permission opens this surface, not only the built-in Org Admin role.
- **User accounts** — `/api/admin/users/` — **superadmin only**. The global
  account entity: create accounts, grant/revoke superadmin, deactivate/reactivate.

Anonymous → 401. Authenticated without the required permission → 403
(`code: permission_denied`). Base URL in examples: `http://localhost:8000`.

---

## Memberships — `/api/admin/memberships/`

Org is **data** (in the body on create, derived from the membership row on
write) — these endpoints do not use the `X-Organization-Id` header, and the
list is cross-org.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/admin/memberships/` | `USERS.READ` in ≥1 org | Cross-org member list |
| POST | `/api/admin/memberships/` | `USERS.CREATE` in the target org | Add an existing user to an org |
| PATCH | `/api/admin/memberships/{id}/` | `USERS.UPDATE` in the row's org | Change a member's role |
| DELETE | `/api/admin/memberships/{id}/` | `USERS.DELETE` in the row's org | Remove a member |

The door gate (`HasResourcePermissionAnywhere(USERS)`) is coarse — it passes if
you hold the action in at least one org. The precise per-org check runs in the
service; a membership in an org you can't access is **404** (indistinguishable
from missing — no existence leak).

### Membership row shape

```json
{
  "id": 55,
  "org": {"id": 10, "name": "Acme"},
  "user": {"id": 42, "email": "bob@acme.com", "display_name": "Bob", "avatar_url": null, "is_active": true},
  "role": {"id": 3, "name": "Member"},
  "joined_at": "2026-08-13T10:00:00Z"
}
```

### GET `/api/admin/memberships/`

Paginated (`count/next/previous/results`, page size 50, max 200). One row per
`(user, org, role)` — a user in three of your orgs is three rows.

**Query params:** `org_ids` (comma-separated; a forbidden id → **403 fail-loud**
for the whole request; omitted → every org you can read members in; superadmin →
all), `search` (case-insensitive on email or display_name), `role_id` (exact
role; a built-in role id spans orgs), `status` (`active` | `inactive` on the
member's account), `ordering` (`email` | `joined_at` | `role` | `org`, prefix
`-` for descending; default `org, email`). Invalid `role_id`/`status` → **400
`invalid`**.

### POST `/api/admin/memberships/`

Links an **existing** account to an org. Account creation is not here — it is a
superadmin operation on `/api/admin/users/`.

```json
{"org_id": 10, "email": "bob@acme.com", "role_id": 3}
```

Provide **exactly one** of `email` or `user_id`, plus `org_id` and `role_id`.

- Unknown email/user_id → **404 `user_not_found`**.
- Already a member → **400 `membership_already_exists`**.
- Non-assignable role (the global Superadmin role, or a custom role from another
  org) → **400 `invalid_role_assignment`**.
- Target org you can't access → **404** (no existence leak).

**201** → the membership row.

### PATCH `/api/admin/memberships/{id}/`

`{"role_id": 2}`. Assigns any existing assignable role. There is **no assignment
ceiling** — holding `USERS.UPDATE` lets you assign any existing role to others,
including promoting to Org Admin. A non-superadmin **cannot change their own
membership** → **403 `cannot_modify_self_membership`**. **200** → the row.

### DELETE `/api/admin/memberships/{id}/`

Removes the membership (the account stays). A non-superadmin **cannot remove
their own membership** → **403 `cannot_modify_self_membership`**. There is no
last-org-admin guard — a superadmin is the recovery path if an org loses its
last delegated admin. **204**.

---

## User accounts — `/api/admin/users/` (superadmin only)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/admin/users/` | List all users (paginated) with their memberships |
| POST | `/api/admin/users/` | Create an account; optionally assign an initial org + role |
| POST | `/api/admin/users/{id}/grant-superadmin/` | Set `is_superadmin=true` |
| POST | `/api/admin/users/{id}/revoke-superadmin/` | Set `is_superadmin=false` (last-active-superadmin guard) |
| POST | `/api/admin/users/{id}/deactivate/` | Set `is_active=false` (last-active-superadmin guard) |
| POST | `/api/admin/users/{id}/reactivate/` | Set `is_active=true` |

### GET `/api/admin/users/`

Paginated (default 50, max 200). Filters: `?email=substr&is_superadmin=true|false&organization_id=N`.
Returns `UserResponse` (id, email, display_name, avatar_url, is_superadmin,
is_active, created_at, updated_at, `memberships[]`).

### POST `/api/admin/users/`

```json
{"email": "new@example.com", "password": "StrongPass123!", "organization_id": 1, "role_id": 3}
```

`organization_id` and `role_id` are optional; with `organization_id` and no
`role_id` the server assigns the built-in **Member** role. **201** →
`UserResponse`. Errors: `400 email_already_exists`, `400 invalid_role_assignment`,
`400 invalid`, `404 organization_not_found`, `404 role_not_found`.

### grant/revoke-superadmin, deactivate/reactivate

Idempotent, empty body, return `UserResponse`. `revoke-superadmin` and
`deactivate` refuse to remove the **last active superadmin** →
**400 `last_superadmin`**. Unknown id → **404 `user_not_found`**; non-numeric id
→ **404** from the URL resolver.

---

## Behavioral notes for the FE

| Behavior | Note |
|---|---|
| Adding a member | Reference an existing account by exact email (or user_id). If the email has no account, the caller gets a 404 — a superadmin must create the account first on `/api/admin/users/`. |
| Assigning roles | Populating the role picker needs `ROLES.read` in the org (to list options) plus `USERS.update` to assign. A `USERS`-only admin without `ROLES.read` can still add/remove members and default them to Member. |
| Self-management | You cannot change or remove your own membership; another admin or a superadmin does it. |
| Deactivated orgs | Drop out of a delegated admin's scope; only a superadmin manages members in an inactive org. |
| Superadmin memberships | Ordinary rows; the superadmin bypass is unaffected by them. A superadmin with no membership row simply isn't listed as a member of that org. |
| 401 vs 403 | 401 = no/expired credential. 403 = valid credential but insufficient permission. |
| Password redaction | Validation echoes the offending value back, except `password`, replaced with `***`. |
