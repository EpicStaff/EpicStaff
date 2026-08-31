# User & Membership Management

Two surfaces manage people, and the split matters:

- **Memberships** — `/api/admin/memberships/` — permission-driven and cross-org.
  Who belongs to an organization and what role they hold, in every org where you
  hold the `MEMBERSHIPS` permission. Any custom role carrying that permission
  opens this surface, not only the built-in Org Admin role.
- **User accounts** — `/api/admin/users/` — **superadmin only**. The global
  account entity: create accounts, grant/revoke superadmin, deactivate/reactivate.

Adding someone to your organization is a *membership* operation on an account that
already exists. Creating the account itself is a superadmin operation. The two are
never combined.

Anonymous → 401. Authenticated without the required permission → 403
(`code: permission_denied`). Base URL in examples: `http://localhost:8000`.

---

## Memberships — `/api/admin/memberships/`

Org is **data** — in the body on create, taken from the membership row on every
other write. These endpoints do not use the `X-Organization-Id` header, and the
list spans organizations.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/admin/memberships/` | `MEMBERSHIPS.READ` in ≥1 org | Cross-org member list |
| GET | `/api/admin/memberships/assignable-users/` | `MEMBERSHIPS.CREATE` in ≥1 org | Accounts you may add |
| POST | `/api/admin/memberships/` | `MEMBERSHIPS.CREATE` in the target org | Add an existing user to an org |
| PATCH | `/api/admin/memberships/{id}/` | `MEMBERSHIPS.UPDATE` in the row's org | Change a member's role |
| DELETE | `/api/admin/memberships/{id}/` | `MEMBERSHIPS.DELETE` in the row's org | Remove a member |

The door gate is coarse — it passes if you hold the action in at least one org.
The precise per-org check runs behind it; a membership in an org you can't access
is **404**, indistinguishable from one that doesn't exist.

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

### GET `/api/admin/memberships/assignable-users/`

The accounts you may add to an organization — the list behind the person picker.

You see active, non-superadmin accounts that already belong to at least one
organization where you can read members. In other words: the people you can
already see, and nobody else. A superadmin sees every active non-superadmin
account, including those that belong to no organization yet.

Paginated (page size 50, max 200). **Query params:** `search`
(case-insensitive on email or display name), `page`, `page_size`.

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 42,
      "email": "bob@acme.com",
      "display_name": "Bob",
      "avatar_url": null,
      "org_ids": [10]
    }
  ]
}
```

`org_ids` is where that person already belongs, limited to the organizations you
can read — use it to mark those organizations as already-joined instead of
attempting an add that would be rejected.

If someone you need is not in the list, they belong to no organization you can
see. Add them by email (below), or ask a superadmin.

### POST `/api/admin/memberships/`

Links an **existing** account to an organization.

```json
{"org_id": 10, "user_id": 42, "role_id": 3}
```

Provide `org_id`, `role_id`, and **exactly one** of `user_id` or `email`. Pick
`user_id` from the assignable-users list; use `email` to reach an account outside
that list.

- Unknown email/user_id → **404 `user_not_found`**.
- Already a member → **400 `membership_already_exists`**.
- Target is a superadmin → **400 `superadmin_not_assignable`**.
- Target account is deactivated → **400 `user_not_active`**.
- Non-assignable role (the global Superadmin role, or a custom role from another
  org) → **400 `invalid_role_assignment`**.
- Target org you can't access → **404** (no existence leak).

**201** → the membership row.

### PATCH `/api/admin/memberships/{id}/`

`{"role_id": 2}`. Assigns any existing assignable role. There is **no assignment
ceiling** — holding `MEMBERSHIPS.UPDATE` lets you assign any existing role to
others, including promoting to Org Admin. A non-superadmin **cannot change their
own membership** → **403 `cannot_modify_self_membership`**. A membership held by
a superadmin cannot be re-roled → **400 `superadmin_not_assignable`**. **200** →
the row.

### DELETE `/api/admin/memberships/{id}/`

Removes the membership; the account stays. A non-superadmin **cannot remove their
own membership** → **403 `cannot_modify_self_membership`**. There is no
last-org-admin guard — a superadmin is the recovery path if an org loses its last
delegated admin. **204**.

---

## Superadmins are not organization members

A superadmin already reaches every organization and holds every permission there,
so a membership row would grant them nothing. The rule follows from that:

- A superadmin **cannot be added** to an organization → `400 superadmin_not_assignable`.
- A superadmin's membership **cannot be re-roled** → same error. You cannot make a
  superadmin a Viewer in your org; they are a superadmin everywhere.
- **Granting superadmin removes that person's organization roles.** If Bob is Org
  Admin of Acme and Member of Beta, granting him superadmin drops both rows — he
  no longer needs them.
- **Revoking superadmin does not bring them back.** Bob lands with no
  organizations and must be added again by an admin. Warn before granting.
- Removing a superadmin's membership is still allowed, and is how a leftover row
  is cleaned up.

Superadmins remain fully visible in user listings; they are simply never listed as
members of an organization.

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

Setting `organization_id` matters more than it looks: an account created without
one belongs to no organization, so it appears in no delegated admin's
assignable-users list. Placing a new account in its first organization is part of
creating it.

### grant/revoke-superadmin, deactivate/reactivate

Idempotent, empty body, return `UserResponse`. `revoke-superadmin` and
`deactivate` refuse to remove the **last active superadmin** →
**400 `last_superadmin`**. Unknown id → **404 `user_not_found`**; non-numeric id
→ **404** from the URL resolver.

`grant-superadmin` also clears the target's memberships — see "Superadmins are not
organization members" above.

---

## Behavioral notes

| Behavior | Note |
|---|---|
| Adding a member | Pick from the assignable-users list, or supply an exact email. If the email has no account, you get a 404 — a superadmin creates the account first on `/api/admin/users/`. |
| Who the picker shows | People already visible to you through an org where you can read members. Superadmins and deactivated accounts never appear. |
| Assigning roles | Populating the role picker needs `ROLES.read` in the org (to list options) plus `MEMBERSHIPS.update` to assign. A `MEMBERSHIPS`-only admin without `ROLES.read` can still add/remove members and default them to Member. |
| Self-management | You cannot change or remove your own membership; another admin or a superadmin does it. |
| Deactivated orgs | Drop out of a delegated admin's scope; only a superadmin manages members in an inactive org. |
| 401 vs 403 | 401 = no/expired credential. 403 = valid credential but insufficient permission. |
| Password redaction | Validation echoes the offending value back, except `password`, replaced with `***`. |

## Error reference

| Code | Status | Meaning |
|---|---|---|
| `user_not_found` | 404 | No account for that email or id |
| `membership_already_exists` | 400 | Already a member of that organization |
| `superadmin_not_assignable` | 400 | Target is a superadmin — cannot be added or re-roled |
| `user_not_active` | 400 | Target account is deactivated |
| `invalid_role_assignment` | 400 | Global Superadmin role, or a custom role from another org |
| `cannot_modify_self_membership` | 403 | You cannot change or remove your own membership |
| `membership_not_found` | 404 | No such membership, or it is in an org you cannot access |
| `organization_not_found` | 404 | No such organization, or you cannot access it |
| `email_already_exists` | 400 | An account with that email exists |
| `last_superadmin` | 400 | At least one active superadmin must remain |
| `permission_denied` | 403 | You lack the required `MEMBERSHIPS` permission |
| `invalid` | 400 | Field validation, or a bad list filter |
