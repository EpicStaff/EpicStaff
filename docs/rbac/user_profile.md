# User Profile — `/api/profile/`

The user-facing profile surface. Replaces the deprecated
`/api/auth/me/` and `/api/auth/password-change/` endpoints (both
removed in Story 6).

**Auth:** every endpoint requires a JWT user context. API keys with
`created_by=None` (env-seeded service keys) get a 403.

---

## Overview

Six endpoints. Read, partial update, avatar upload/delete, and a
two-step password change.

| Method | URL | Purpose |
|---|---|---|
| GET | `/api/profile/` | Read own profile (id, email, display name, avatar URL, memberships). |
| PATCH | `/api/profile/` | Update mutable fields. Today: `display_name`. |
| POST | `/api/profile/avatar/` | Upload or replace avatar (multipart). JPEG / PNG, ≤ 5 MB. |
| DELETE | `/api/profile/avatar/` | Clear avatar. |
| POST | `/api/profile/password-change/request/` | Step 1: verify current password, get a ticket. |
| POST | `/api/profile/password-change/confirm/` | Step 2: consume ticket, set new password, get a fresh JWT pair. |

---

## FE integration flows

### 1. Loading the profile page

`GET /api/profile/` → render name, email, avatar (or default if `avatar_url` is null), and a read-only list of organizations + role.

Memberships are filtered to active organizations only and sorted by `joined_at` ascending.

### 2. Changing display name

`PATCH /api/profile/` with `{"display_name": "Alice Doe"}`. Response is the full updated profile — re-render directly.

To clear: `{"display_name": null}`. Empty string is rejected.

JWT is NOT re-issued — the FE does not need to refresh tokens. Just refetch the profile (or read the response body).

### 3. Uploading or replacing the avatar

`POST /api/profile/avatar/` with `multipart/form-data`; form field name `avatar`. The previous file (if any) is deleted server-side after the DB write commits.

Validation errors come back as 400 with one of these `code` values:

| Code | Meaning | UI guidance |
|---|---|---|
| `invalid` | Field is missing | "Please choose a file." |
| `invalid_avatar` | File is not a valid JPEG or PNG | "Only JPEG or PNG images are allowed." |
| `avatar_too_large` | File exceeds `AVATAR_MAX_BYTES` | Echo the message — it includes the max in MB. |

Response on success: the full updated profile (`avatar_url` now non-null).

### 4. Removing the avatar

`DELETE /api/profile/avatar/` → 204 No Content. Subsequent `GET /api/profile/` returns `avatar_url: null`. FE renders the default avatar (initials / generic icon).

### 5. Two-step password change

This is a deliberate, sequenced UX. Do not collapse into one form submit.

**Step 1 — current password.**

1. Show a form with one field: "Current password."
2. On submit, `POST /api/profile/password-change/request/` with `{"current_password": "..."}`.
3. Response 200 → `{ "ticket": "...", "expires_in": 300 }`. **Store the ticket in component state / memory only.** Never write it to `localStorage`, `sessionStorage`, or a URL.
4. Reveal the "New password" form.

Errors:
- `400 invalid_current_password` → keep the user on step 1; show "Wrong password."
- `400 invalid` → missing field; render the FieldError envelope.
- `429` → "Too many attempts, try again in N seconds" (parse `Retry-After` header).

**Step 2 — new password.**

1. Show "New password" field (and "Confirm new password" if you want FE-side parity check).
2. On submit, `POST /api/profile/password-change/confirm/` with `{"ticket": "...", "new_password": "..."}`.
3. Response 200 → `{ "access": "...", "refresh": "..." }`. **Replace the stored JWT pair with these new ones.** Every other session for this user is now invalid; this device remains logged in.

Errors and recovery:
- `400 invalid_password_change_ticket` → the ticket is unknown, expired (default 5 min), already used, or doesn't belong to this user. UI: "Session timed out, please re-enter your current password." Drop the user back to step 1.
- `400 invalid` with FieldError envelope → weak new password. Keep on step 2. Render messages from `errors[]`.

Submitted password values are redacted (`"value": "***"`) in error responses.

### 6. Migrating from `/api/auth/me/` and `/api/auth/password-change/`

`GET /api/profile/` returns **a strict superset** of the old `/me/` payload, plus `avatar_url` and `is_active`. Drop-in replacement.

| Old `/me/` field | New `/profile/` field | Notes |
|---|---|---|
| `id` | `id` | unchanged |
| `email` | `email` | unchanged |
| `display_name` | `display_name` | unchanged |
| `avatar_url` | `avatar_url` | unchanged |
| `is_superadmin` | `is_superadmin` | unchanged |
| — | `is_active` | new |
| — | `created_at`, `updated_at` | new |
| `memberships[].organization.{id,name}` | `memberships[].organization.{id,name,is_active}` | `is_active` added; only `is_active=true` orgs ever appear |
| `memberships[].role.{id,name}` | `memberships[].role.{id,name}` | unchanged |
| `memberships[].joined_at` | `memberships[].joined_at` | unchanged |
| — | `memberships[].id` | new — the `OrganizationUser` row id |

`POST /api/auth/password-change/` is gone. Replace with the two-step flow described in §5 above.

---

## Reference

### GET `/api/profile/`

**Response 200:**

```json
{
  "id": 4,
  "email": "user1@example.com",
  "display_name": "Alice",
  "avatar_url": "http://host/media/avatars/4/9f2b1e0a8c.png",
  "is_superadmin": false,
  "is_active": true,
  "created_at": "2026-05-06T10:04:42.284563Z",
  "updated_at": "2026-05-11T14:22:00.000000Z",
  "memberships": [
    {
      "id": 4,
      "organization": {"id": 5, "name": "Five id:5", "is_active": true},
      "role": {"id": 2, "name": "Org Admin"},
      "joined_at": "2026-05-06T10:04:42.288373Z"
    }
  ]
}
```

### PATCH `/api/profile/`

**Request:** any subset of editable fields.

```json
{ "display_name": "Alice Doe" }
```

To clear: `{"display_name": null}`. Empty object `{}` is a 200 no-op (returns current profile).

**Response 200:** the full updated profile (same shape as GET).

### POST `/api/profile/avatar/`

`multipart/form-data` with one field: `avatar` (image file).

**Response 200:** the full updated profile (`avatar_url` now non-null).

### DELETE `/api/profile/avatar/`

No body.

**Response 204** No Content.

### POST `/api/profile/password-change/request/`

```json
{ "current_password": "..." }
```

**Response 200:**

```json
{ "ticket": "k7Xq8...", "expires_in": 300 }
```

Throttled by `LoginThrottle` (default 5/min, env `LOGIN_THROTTLE_RATE`).

### POST `/api/profile/password-change/confirm/`

```json
{ "ticket": "k7Xq8...", "new_password": "..." }
```

**Response 200:**

```json
{ "access": "...", "refresh": "..." }
```

This pair is fresh. Every other refresh token for the user is now blacklisted; the previous access token continues working only until its own expiry (≤ `JWT_ACCESS_MINUTES`, default 15).

---

## Active organization

`/api/profile/` accepts an optional `X-Organization-Id` header. When present and the caller is a member of that org (or is superadmin), the response includes:

- `active_organization_id`: int — echoes the header.
- `active_permissions`: object — same shape as `GET /api/permissions/me/` (is_superadmin, role, permissions).

When the header is absent OR points to an org the caller cannot access OR contains a non-integer value, both fields are `null` and the rest of the response is unchanged. The endpoint NEVER returns 403 for this case — it's the FE's boot endpoint and must remain reachable.

## Switching organizations (FE flow)

1. On login, call `GET /api/profile/` (no header). Read `memberships[]`.
2. Pick an active org from `memberships[]` (or remember last choice from local state).
3. Set `X-Organization-Id: <id>` as a default header on every subsequent request via your HTTP interceptor.
4. Refetch `GET /api/profile/` with the header to get `active_permissions`. Cache in FE state.
5. On org switch: update the header, refetch `/profile/`, replace cached state.
6. If a gated endpoint returns 403 `org_membership_required` mid-session (org deactivated, membership removed): clear the header, redirect to org-picker.

See [roles_and_permissions.md](roles_and_permissions.md) for the catalog endpoint, /permissions/me/ details, and the role-list endpoints used by FE pickers.

---

## Errors

Every error follows the project envelope:

```json
{ "detail": "...", "code": "..." }
```

Or, for multi-field validation:

```json
{
  "detail": "Validation failed",
  "code": "invalid",
  "errors": [
    { "field": "new_password", "value": "***", "reason": "This password is too short." }
  ]
}
```

| Status | Code | Meaning |
|---|---|---|
| 400 | `invalid` | One or more fields failed validation. See `errors[]`. |
| 400 | `invalid_current_password` | Step 1 received a wrong current password. |
| 400 | `invalid_password_change_ticket` | Ticket is unknown, expired, already used, or does not belong to the calling user. |
| 400 | `invalid_avatar` | Upload is not a valid JPEG or PNG. |
| 400 | `avatar_too_large` | Upload exceeds `AVATAR_MAX_BYTES`. |
| 401 | (default DRF) | Unauthenticated. |
| 403 | — | Authenticated but lacks user context (e.g., env-seeded API key). |
| 404 | — | URL not registered (defense against stale FE that still calls `/api/auth/me/`). |
| 429 | — | Throttled. Read `Retry-After` header. |

---

## Deployment

- `MEDIA_URL` must be served by the reverse proxy (nginx / Caddy) in production. Django serves `MEDIA_URL` only in DEBUG mode.
- Env vars:
  - `PASSWORD_CHANGE_TICKET_TTL_SECONDS` (default `300`)
  - `AVATAR_MAX_BYTES` (default `5242880` = 5 MB)
  - `AVATAR_ALLOWED_FORMATS` (default `JPEG,PNG`)
  - `LOGIN_THROTTLE_RATE` (already in Story 2; reused for password-change request)
- Redis 6.2+ required (`GETDEL` for atomic ticket consume).
- Pillow is already a Django `ImageField` dependency — no additional install.
