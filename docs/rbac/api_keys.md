# API Keys

Covers the API key model, self-service key management (`/api/profile/api-keys/`),
cross-org admin management (`/api/admin/api-keys/`), the singleton system key, and
how keys interact with introspection, SSE tickets, and org-scoped RBAC.

A personal (`USER`) key belongs to **one organization**. It works only in that
organization. To work in several organizations, create one key per organization.

> **Upgrade note.** The release that bound keys to an organization deleted
> **every existing personal key** (migration `rbac/0012_api_key_org`). There was
> no safe way to pick an organization for an old key, because its owner can belong
> to several. Create new keys, one per organization. The `SYSTEM` key is kept.
> Past sessions started with a deleted key keep their user and email; only their
> link to the key (`SessionPrincipal.api_key`) becomes empty.

See [auth_endpoints.md](auth_endpoints.md) for the rest of the auth surface
(JWT login, first-setup, token introspection, user reset). Base URL in
examples: `http://localhost:8000`.

---

## Key format

A raw key looks like:

```
es-kR3f9s1n1qz8vY0aB2cD4eF6gH8iJ0kLmNoPqRsTuVw
```

- `es-` prefix (the `ApiKeyGenerator.KEY_PREFIX`) so leaked keys are
  recognizable to humans and secret scanners.
- The rest is `secrets.token_urlsafe(32)` — 256 bits of entropy.
- The **raw key is shown exactly once**, in the response body of
  `POST /api/profile/api-keys/`. It is never stored — only a SHA-256 hash
  (`key_hash`, unique) is persisted, plus the first 12 characters of the
  raw key as `prefix` for display/search. If you lose the raw value, there
  is no way to recover it; issue a new key. (The system key has no
  self-service creation response — its raw value is whatever the operator
  set in the `DJANGO_API_KEY` env var.)
- Lookup at auth time is an exact match on `key_hash` (`ApiKey.objects.filter(key_hash=..., revoked_at__isnull=True)`) — one indexed query, no prefix scanning.

---

## Two key classes

| | `SYSTEM` | `USER` |
|---|---|---|
| Created by | `python manage.py seed_system_api_key` (from `DJANGO_API_KEY` env), run at container start by `entrypoint.sh` | `POST /api/profile/api-keys/` (self-service, JWT-only) |
| Owner (`created_by`) | always `NULL` | always set (DB `CheckConstraint api_key_type_invariants`) |
| Organization (`org`) | always `NULL` | always set (same constraint) — chosen at creation, never changes |
| Expiry | never (`expires_at` forced `NULL` by the same constraint) | optional — default 90 days, or `null` for no expiry, or an explicit day count |
| Resolves to (`request.user`) | synthetic `SystemServicePrincipal` (`is_authenticated=True`, `is_superadmin=True`, no `email`/`pk`) | the owning `User` — with the live RBAC permissions that user has **in the key's organization** |
| Active organization | from `X-Organization-Id`, like a JWT | always the key's organization; `X-Organization-Id` is ignored |
| How many can exist | one active at a time (singleton — seeding revokes any previous active `SYSTEM` key) | up to 5 active (non-revoked, non-expired) per user **per organization** |
| Visible in `GET /api/admin/api-keys/` or `GET /api/profile/api-keys/` | never | yes, to its owner, and to any caller holding `api_keys` read in **the key's organization** (or to a superadmin, always) |
| Revocable/deletable over HTTP | no — both management endpoints only ever operate on `key_type=USER` rows; a `SYSTEM` key's id returns `404 api_key_not_found` | yes |
| Authenticates while the owner's account is deactivated | n/a — no owner | no — a deactivated owner's key stops authenticating immediately, even though the row itself is untouched |

Both classes authenticate the same way — header `X-Api-Key: <raw_key>`
(preferred) or `Authorization: ApiKey <raw_key>` — and both update
`last_used_at` on successful auth, throttled to at most one write per key
per 60 seconds so hot keys don't turn every request into a row write.

A key that fails lookup or is revoked returns `401` with
`{"code": "authentication_failed", "message": "AuthenticationFailed: Invalid API key"}`.
A key that is found but past `expires_at` returns `401` with
`{"code": "authentication_failed", "message": "AuthenticationFailed: API key has expired"}`.
A `USER` key whose organization is inactive (whoever owns it, a superadmin
too), or whose owner is not a superadmin and is no longer a member of the
key's organization, returns `401` with
`{"code": "authentication_failed", "message": "API key is no longer valid for its organization"}`.
The check runs at authentication, so it covers every endpoint the key can
reach, including those that do not otherwise look at the organization
(profile, stream tickets, the admin surface, a superadmin's runs).

---

## Self-service: `/api/profile/api-keys/`

JWT-only. Every endpoint below has `permission_classes = [IsAuthenticated,
DenyApiKeyAuth]` — an API-key-authenticated caller (including the SYSTEM
key) gets:

```json
{
  "status_code": 403,
  "code": "permission_denied",
  "message": "API keys cannot be used on this endpoint. Authenticate with a user session (JWT)."
}
```

This is intentional defense-in-depth: a leaked API key must not be usable
to mint or destroy other credentials.

### POST `/api/profile/api-keys/` — create a key

Request:

```json
{ "name": "laptop-cli", "org_id": 3, "expires_in_days": 30 }
```

- `name` — required, non-blank, max 255 characters.
- `org_id` — required, positive integer. The organization the key belongs to.
  The caller must be a member of it, and it must be active. A superadmin may
  pick any active organization.
- `expires_in_days` — optional:
  - **absent** → defaults to **90 days**.
  - **`null`** → never expires.
  - **integer** → must be `1..3650`; anything else (float, bool, 0, out of
    range) is rejected.

Creation locks the owner's user row and re-checks that the caller's JWT is
still bound to the current password; a session whose password changed in the
meantime gets `401` `password_changed` and no key is created. Membership in
`org_id` and the key cap are checked under the same lock.

Response `201`:

```json
{
  "id": 12,
  "name": "laptop-cli",
  "org_id": 3,
  "org_name": "Acme",
  "prefix": "es-kR3f9s1n1",
  "created_at": "2026-07-14T10:00:00Z",
  "expires_at": "2026-08-13T10:00:00Z",
  "last_used_at": null,
  "revoked_at": null,
  "status": "active",
  "api_key": "es-kR3f9s1n1qz8vY0aB2cD4eF6gH8iJ0kLmNoPqRsTuVw"
}
```

`api_key` (the raw value) is present **only** in this create response —
every other response (list, revoke) omits both the raw key and the hash.

Errors:

- `400 api_key_limit_exceeded` — the caller already has 5 active keys in
  this organization (keys in other organizations, and revoked and expired
  keys, don't count toward the cap):
  ```json
  {
    "status_code": 400,
    "code": "api_key_limit_exceeded",
    "message": "ApiKeyLimitExceededError: Maximum number of active API keys in this organization reached (5). Revoke or delete an existing key first."
  }
  ```
- `400 invalid` — structured validation errors, e.g.:
  ```json
  {
    "status_code": 400,
    "code": "invalid",
    "message": "FormValidationError: Validation failed",
    "errors": [
      { "field": "name", "value": "", "reason": "Name is required." },
      { "field": "expires_in_days", "value": 0, "reason": "Must be null (no expiry) or an integer between 1 and 3650." },
      { "field": "org_id", "value": null, "reason": "Organization is required." }
    ]
  }
  ```
- `403 org_membership_required` — the caller is not a member of `org_id`,
  or the organization is inactive (also for a superadmin):
  ```json
  { "status_code": 403, "code": "org_membership_required", "message": "OrgMembershipRequiredError: You are not a member of this organization." }
  ```
- `404 organization_not_found` — a superadmin named an organization that
  does not exist. (A non-superadmin gets the `403` above instead, so the
  error does not reveal which ids exist.)

### GET `/api/profile/api-keys/` — list my keys

Returns the caller's own `USER` keys in every organization, newest first
(`-created_at`). Never includes the raw key or `key_hash`:

```json
[
  {
    "id": 12,
    "name": "laptop-cli",
    "org_id": 3,
    "org_name": "Acme",
    "prefix": "es-kR3f9s1n1",
    "created_at": "2026-07-14T10:00:00Z",
    "expires_at": "2026-08-13T10:00:00Z",
    "last_used_at": "2026-07-15T09:30:00Z",
    "revoked_at": null,
    "status": "active"
  }
]
```

`status` is computed, not stored: `"revoked"` if `revoked_at` is set,
else `"expired"` if `expires_at` is in the past, else `"active"`.

### POST `/api/profile/api-keys/{id}/revoke/` — revoke my key

Sets `revoked_at` to now (idempotent — calling it again on an
already-revoked key is a no-op, still `200`). The row is **kept** for
audit; it still appears in `GET` with `status: "revoked"`. Response
`200` returns the same shape as the list, with the updated `status`.

Once revoked, the key fails authentication **immediately** — any request
already using it gets `401 Invalid API key` on its very next call.

### DELETE `/api/profile/api-keys/{id}/` — delete my key

Hard delete — the row is gone, `204` on success. Unlike revoke, this is
not reversible and the key stops appearing anywhere, including admin
audit listings.

Both `revoke` and `delete` scope to the caller's own keys only
(`created_by=request.user`). An id that doesn't exist, belongs to someone
else, or belongs to the SYSTEM key returns:

```json
{ "status_code": 404, "code": "api_key_not_found", "message": "ApiKeyNotFoundError: API key not found." }
```

— the same 404 in every case, so a caller cannot use the error to probe
which ids exist.

---

## Password set revokes every key

Whenever a user's password is set — reset link
(`POST /api/auth/password-reset/confirm/`), superadmin reset
(`POST /api/auth/admin/password-reset/`), the `reset_password` CLI, or the
self-service change (`POST /api/profile/password-change/confirm/`) — **all
of that user's non-revoked `USER` keys are revoked** (`revoked_at` set to
now), in the same transaction as the password write. Already-expired keys
are revoked too, so their `status` becomes `"revoked"`. Keys of other users
and the `SYSTEM` key are untouched.

This covers keys that exist when the password is set: a key minted with a
stolen password — possibly non-expiring — would otherwise keep working after
the real owner resets it. Rows are kept, so the owner sees the revoked keys
in their list and creates new ones as needed.

No session survives to mint a replacement: every JWT is bound to the
password it was issued under, so access and refresh tokens from before the
password set are rejected from the moment it commits (see
[password_recovery.md](password_recovery.md) → Security invariants). Creating
a new key needs a fresh login with the new password. The one exception is the
self-service change: its confirm step returns a fresh token pair minted under
the new password, so the caller who made the change stays logged in and can
create keys with it.

---

## Revoke vs. delete, summarized

|  | Revoke | Delete |
|---|---|---|
| Row survives | yes (`revoked_at` set) | no (hard delete) |
| Reversible | no (no "un-revoke") | no |
| Shows up in listings afterward | yes, `status: "revoked"` | no |
| Auth effect | immediate `401` | immediate `401` (row is gone) |
| Use case | keep an audit trail of "this credential existed and was retired" | remove clutter / GDPR-style purge |

---

## Management: `/api/admin/api-keys/`

Lets a privileged caller inspect and retire the `USER` keys of people they
administer — for incident response ("this laptop was stolen, kill its
keys") without needing DB access. Only ever operates on `USER` keys;
`SYSTEM` keys are invisible here.

```
GET    /api/admin/api-keys/            ?org_ids= &user= &status= &search= &page= &page_size=
POST   /api/admin/api-keys/{id}/revoke/
DELETE /api/admin/api-keys/{id}/
```

Auth: `permission_classes = [IsAuthenticated, DenyApiKeyAuth,
HasResourcePermissionAnywhere]` — JWT only (same `DenyApiKeyAuth` rule as
self-service), gated on the `api_keys` resource:

| Action | Required `api_keys` permission bit |
|---|---|
| `GET /api/admin/api-keys/` (list) | `READ` |
| `POST /api/admin/api-keys/{id}/revoke/` | `DELETE` |
| `DELETE /api/admin/api-keys/{id}/` | `DELETE` |

The built-in **Org Admin** role holds `api_keys` `READ|DELETE`, so it can
list and retire keys. **Member** and **Viewer** hold neither bit, so `GET
/api/admin/api-keys/` returns `403` for them and both write actions do
too.

### Scope: the key's own organization

There is no `X-Organization-Id` on this surface — organization is data,
selected through the `?org_ids=` query param, never an implicit active
context. Each key belongs to one organization (`org_id`), and only that
organization governs it. The other organizations of the key's owner give
no rights over the key:

- A caller **sees** a key in the list if they hold `api_keys` `READ` in
  the key's organization.
- A caller may **revoke or delete** a key if they hold `api_keys`
  `DELETE` in the key's organization.
- A key the caller can neither read nor retire in its organization is
  **not visible**: revoke and delete answer `404 api_key_not_found`, the
  same as an unknown id, rather than a `403` that would confirm the key
  exists. A `403` is returned only when the caller holds `api_keys`
  `READ` in the key's organization — they can see the key in their list —
  but not `DELETE`.

A superadmin bypasses both checks and sees and retires every `USER` key,
including keys owned by other superadmins. Nobody else can see or reach a
superadmin-owned key at all — it is absent from their list and a revoke
or delete against its id returns `404 api_key_not_found`, identical to an
unknown id.

### Filters and ordering (`GET /api/admin/api-keys/`)

| Query param | Behavior |
|---|---|
| `?org_ids=1,2` | Comma-separated org ids; restricts the list to keys that belong to those orgs. An id the caller cannot `api_keys` `READ` in (and isn't superadmin) fails the whole request with `403`. A non-integer value → `400 org_context_required`. Omitted → every org the caller can read. |
| `?user=<id>` | Only keys owned by that user id. Non-integer → `400 invalid`. |
| `?status=active\|expired\|revoked` | Any other value → `400 invalid`. |
| `?search=<text>` | Case-insensitive substring match on `name` OR `prefix`. |

Ordering is fixed (no `?ordering=` param): `last_used_at` descending with
nulls last, then `created_at` descending, then `id` — most-recently-active
keys first, never-used keys last, with `id` breaking ties so pagination
stays stable across pages.

**Response 200** — a paginated envelope (default page size 50, max 200):

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 12,
      "name": "laptop-cli",
      "prefix": "es-kR3f9s1n1",
      "created_at": "2026-07-14T10:00:00Z",
      "expires_at": "2026-08-13T10:00:00Z",
      "last_used_at": "2026-07-15T09:30:00Z",
      "revoked_at": null,
      "status": "active",
      "owner": { "id": 7, "email": "dev@acme.com", "display_name": "Dev User", "avatar_url": null }
    }
  ]
}
```

Each item also has `org_id` and `org_name` — the organization the key
belongs to (shown in the self-service example above). The list says
nothing about the owner's other organizations.

### Revoke / delete a member's key

Same semantics as self-service revoke/delete (idempotent revoke, hard
delete), authorized by the key's organization (scope above). An id that
doesn't exist, is the SYSTEM key, belongs to an organization where the
caller is not a member, or belongs to an organization that grants the
caller neither `api_keys` `READ` nor `DELETE`, returns `404
api_key_not_found` — the same non-enumerating 404 as self-service.

Because a key works in one organization only, revoking or deleting it
affects only that organization. The owner's keys in other organizations
keep working.

---

## Lifecycle

What happens to `USER` keys when their owner or organization changes:

| Event | Effect on keys |
|---|---|
| Owner removed from the organization (`DELETE /api/admin/memberships/{id}/`) | The owner's keys in **that** organization are deleted, in the same transaction. Their keys in other organizations stay. |
| Organization deactivated | Keys are **not** deleted. Requests get `401 authentication_failed` ("API key is no longer valid for its organization") until the organization is reactivated; then the keys work again. This applies to a superadmin's keys too. |
| Owner made a superadmin | Keys are **not** deleted, but all of the owner's memberships are. A superadmin needs no membership, so the keys keep working in their organizations. |
| Superadmin rights revoked | The user's keys in every organization they are not a member of are deleted, in the same transaction. Granting superadmin removed all their memberships, and a superadmin cannot be added to an organization, so in practice **all** of their keys are deleted. |
| Organization deleted | Keys of that organization are deleted (`ApiKey.org` is `on_delete=CASCADE`). |
| Owner account deleted | All of the owner's keys are deleted (`ApiKey.created_by` is `on_delete=CASCADE`). |
| Owner account deactivated | Keys are kept but stop authenticating (`401`, see [Two key classes](#two-key-classes)). |
| Password set | All of the owner's keys, in every organization, are revoked (see [below](#password-set-revokes-every-key)). |

---

## Governance writes are JWT-only; the system key is rejected on the admin surface

The cross-org governance surface — `/api/admin/roles/`,
`/api/admin/memberships/`, `/api/admin/organizations/`,
`/api/admin/users/` and `/api/admin/api-keys/` — runs the
`RestrictApiKeyToUserKeyReads` gate on every action:

| Caller | Safe methods (`GET`/`HEAD`/`OPTIONS`) | Writes (`POST`/`PUT`/`PATCH`/`DELETE`, incl. custom actions such as `deactivate`, `grant-superadmin`) |
|---|---|---|
| JWT | normal RBAC | normal RBAC |
| `USER` key | the owner's live RBAC in **the key's organization only**[^admin-api-keys-list] (see [Admin pages with an API key](#admin-pages-with-an-api-key)) | `403` |
| `SYSTEM` key | `403` | `403` |

So creating/deleting roles, adding or changing memberships,
creating/deactivating/reactivating/deleting organizations and every user
management action (create, grant/revoke superadmin, deactivate, reactivate,
delete) need a user session. The gate is prepended, first, by the
`get_permissions` of `CrossOrgAdminViewSet` and of `UserAdminViewSet`, so
every subclass inherits it — including any action later added to a
subclass's `superadmin_actions` — and neither a subclass's
`permission_classes` nor an `@action(permission_classes=...)` can drop it.

[^admin-api-keys-list]: Not on `/api/admin/api-keys/`: it also carries
    `DenyApiKeyAuth`, so a `USER` key cannot even list there and gets the
    JWT-only message shown under [Self-service](#self-service-apiprofileapi-keys).

The `SYSTEM` key resolves to a superadmin-equivalent principal, so it is
rejected on reads too: otherwise whoever holds `DJANGO_API_KEY` could read
every organization's governance data. Rejections return `403
permission_denied`:

```json
{ "status_code": 403, "code": "permission_denied", "message": "The system API key cannot be used on the admin surface. Authenticate with a user session (JWT)." }
```

```json
{ "status_code": 403, "code": "permission_denied", "message": "API keys cannot be used to change organizations, users, roles, memberships or API keys. Authenticate with a user session (JWT)." }
```

`POST /api/auth/reset-user/` and `POST /api/auth/admin/password-reset/`
are JWT-only as well (`DenyApiKeyAuth`, any key type).

### Admin pages with an API key

A `USER` key — also a superadmin's — reads the admin pages **only in its own
organization**. `limit_org_ids_to_api_key` (`rbac/access/principals.py`) replaces the
organizations a read asks for (`?org_ids=`, `?organization_id=`,
`?assignable_org_ids=`, or none) with the key's organization. This applies to
roles, memberships (including `assignable-users`), organizations (including
`{id}/retention/`), users, and plugin role permissions.

- A list returns only rows of the key's organization, whatever `?org_ids=` says.
  A different id in `?org_ids=` is not an error — it is replaced.
- Reading one row by id outside the key's organization returns `404`, as if the
  row did not exist. Built-in roles stay visible.
- `/api/admin/api-keys/` is not covered: it rejects every API key (see above).

---

## MCP-style usage (API key in its organization)

An external tool (an MCP server, a CI job, a script) authenticates with a
`USER` key alone and gets exactly the permissions its owner has in the
key's organization — no separate scope system to configure, and no
organization header:

```bash
curl -s http://localhost:8000/api/graphs/ \
  -H "X-Api-Key: es-kR3f9s1n1qz8vY0aB2cD4eF6gH8iJ0kLmNoPqRsTuVw"
```

```powershell
Invoke-RestMethod http://localhost:8000/api/graphs/ `
  -Headers @{ "X-Api-Key" = "es-kR3f9s1n1qz8..." }
```

- The request is evaluated with the owner's role and permissions in the
  key's organization — identical to what the owner would get with a JWT
  and that organization in `X-Organization-Id`. On the `/api/admin/*`
  governance surface this holds for reads only; writes there are JWT-only
  (see above).
- `X-Organization-Id` is **ignored** with a `USER` key — never read, never an
  error. A request that names another organization still runs in the key's
  organization. The same is true for an `org_id` in the URL of a nested
  admin endpoint. `GET /api/profile/` reports the key's organization as
  `active_organization_id`. To work in another organization, use a key of
  that organization.
- Endpoints that list the caller's organizations show the key's organization
  alone, also for a superadmin's key: `memberships` in `GET /api/profile/`
  (and in the profile returned by `PATCH /api/profile/`, the avatar upload and
  the tour completion), `GET /api/permissions/me/orgs/` (always the `orgs`
  form, never the superadmin `permissions: "*"` short form; `is_superadmin`
  still tells whether the owner is one) and
  `GET /api/plugins/{identifier}/login-organizations/`.
- Run sessions belong to the organization of their flow. A key runs
  (`POST /api/run-session/`), stops (`POST /api/sessions/{id}/stop/`) and reads
  the status of (`GET /api/sessions/{id}/get-updates/`) sessions of its own
  organization only. A flow or session of any other organization answers `404`,
  the same as a missing one, even when the owner is a member there or a
  superadmin.
- Platform actions that span organizations refuse every API key, a
  superadmin's too, with `403 permission_denied`: the Flow Assistant audit log
  (`GET /api/flow-assistants/audit/conversations/`) and a storage `move` /
  `copy` across organizations (`source_org_id` / `destination_org_id`). A
  storage transfer within the key's organization works as usual.
- If the owner (not a superadmin) is no longer a member of the key's
  organization, or the organization is inactive (any owner, a superadmin
  too), the key no longer authenticates, on every endpoint:
  ```json
  { "status_code": 401, "code": "authentication_failed", "message": "API key is no longer valid for its organization" }
  ```
- A `USER` key never gets `400 org_context_required`: it always has an
  organization.
- `GET /api/auth/api-key/validate/` returns the key's organization as `org_id`
  (`null` for the `SYSTEM` key), so a tool can tell where its key acts.
- A superadmin's key can still change platform-wide settings that belong to no
  organization: the providers catalog, the default configs, and the ngrok
  configuration of webhook triggers. These are not tied to an organization, so
  the key's organization does not limit them. This is existing superadmin
  behaviour, kept on purpose.

---

## SSE tickets with an API key

`POST /api/auth/sse-ticket/` accepts either JWT or API-key authentication
(`authentication_classes = [JwtAuthentication, ApiKeyAuthentication]`,
`permission_classes = [IsAuthenticated]`) — but it needs a real user
identity to bind the ticket to:

- A **`USER`** key works: the ticket is issued for the key's owner and also
  records the key's organization. The stream opened with it serves only rows
  of that organization: a run session, a Flow Assistant conversation or a
  graph (co-editing websocket, `POST /api/auth/ws-ticket/`) of any other
  organization is refused exactly like a missing one (`404`, websocket close
  `4404`), even when the owner is a member there or a superadmin. A ticket
  issued with a JWT carries no organization and is limited only by the
  owner's memberships.
- The **`SYSTEM`** key does not: `SystemServicePrincipal` has no `email`,
  and the view explicitly checks `hasattr(request.user, "email")` before
  issuing a ticket. A system-key caller gets:
  ```json
  { "detail": "This endpoint requires a user context." }
  ```
  with `403`.

```bash
curl -s -X POST http://localhost:8000/api/auth/sse-ticket/ \
  -H "X-Api-Key: es-kR3f9s1n1qz8vY0aB2cD4eF6gH8iJ0kLmNoPqRsTuVw"
```

---

## The system key

- **Seeding:** `python manage.py seed_system_api_key` reads `DJANGO_API_KEY`
  from the environment and hands it to `SystemKeyService.seed_from_env`.
  `entrypoint.sh` runs this command on every container start.
- **Unset env:** the command logs a warning and does nothing — no
  `SYSTEM` key exists, and internal services (e.g. `realtime`, which
  authenticates to `django_app` with `X-API-Key: DJANGO_API_KEY`) cannot
  authenticate until it's set.
- **Singleton + rotation:** at most one active `SYSTEM` key exists. If the
  env value hashes to the currently-active `SYSTEM` key, seeding is a
  no-op. Otherwise the current active `SYSTEM` key (if any) is revoked and
  a brand-new one is created from the new value — atomically. This is how
  you rotate the system key: change `DJANGO_API_KEY` and restart the
  container.
- **Invisible everywhere:** neither `GET /api/profile/api-keys/` nor `GET
  /api/admin/api-keys/` ever return `SYSTEM` keys (both filter on
  `key_type="user"`). It also cannot be revoked or deleted through either
  HTTP management surface — those endpoints scope every lookup to
  `key_type="user"`, so a `SYSTEM` key's id simply isn't found (`404
  api_key_not_found`).
- **Used by:** internal services holding `DJANGO_API_KEY` — currently
  `realtime` (see `src/realtime/utils/auth.py`). It is also the only
  credential type accepted by `POST /api/auth/introspect/`.

---

## Error envelope reference

All errors share the shape produced by `custom_exception_handler`:
`{"status_code": N, "code": "...", "message": "..."}`, with an `errors`
list added for field-level validation failures. Codes relevant to API
keys:

| Code | Status | Where |
|---|---|---|
| `api_key_limit_exceeded` | 400 | Self-service create, at 5 active keys of the caller in that organization |
| `invalid` | 400 | Self-service create (bad `name`/`expires_in_days`, missing or bad `org_id`); management `?status=`/`?user=` filters |
| `api_key_not_found` | 404 | Self-service revoke/delete on a foreign/unknown id; management revoke/delete on an unknown id, a SYSTEM key's id, a superadmin-owned key seen by a non-superadmin, or a key the caller cannot see — the caller is not a member of the key's organization, or that organization grants neither `api_keys` `READ` nor `DELETE` |
| `organization_not_found` | 404 | Self-service create by a superadmin with an `org_id` that does not exist; an admin read by id of an organization outside the `USER` key's organization |
| `authentication_failed` | 401 | Any request authenticating with a raw key that doesn't match a non-revoked key (`"Invalid API key"`), matches an expired one (`"API key has expired"`), matches a key whose owner's account is deactivated (`"API key owner is inactive"`), or matches a `USER` key whose organization is inactive or whose non-superadmin owner is no longer a member there (`"API key is no longer valid for its organization"`) |
| `permission_denied` | 403 | `DenyApiKeyAuth` (API key used against a key-management endpoint, reset-user or admin password reset), `RestrictApiKeyToUserKeyReads` (an API-key write, or any `SYSTEM`-key request, on `/api/admin/*`), the `api_keys` door gate, a forbidden `?org_ids=` entry on the management list, or a revoke/delete on a key the caller can **see** (holds `api_keys` `READ` in the key's organization) but not retire |
| `org_membership_required` | 403 | Self-service create with an `org_id` the caller is not a member of, or an inactive one; a JWT caller whose `X-Organization-Id` names an org they are not a member of. A `USER` key in that situation gets `401 authentication_failed` instead (see above). The admin API-key surface never raises this |
| `org_context_required` | 400 | JWT caller: `X-Organization-Id` missing or not an integer on a header-required endpoint (never for a `USER` key). On the admin API-key list, a non-integer `?org_ids=` value |
| `not_authenticated` | 401 | No credential supplied at all |

See [auth_endpoints.md](auth_endpoints.md) for the rest of the auth
surface, and [roles_and_permissions.md](roles_and_permissions.md) for the
full `api_keys` / RBAC permission model.
