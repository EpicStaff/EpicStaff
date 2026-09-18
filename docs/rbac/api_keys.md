# API Keys

Covers the API key model, self-service key management (`/api/profile/api-keys/`),
cross-org admin management (`/api/admin/api-keys/`), the singleton system key, and
how keys interact with introspection, SSE tickets, and org-scoped RBAC.

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
| Expiry | never (`expires_at` forced `NULL` by the same constraint) | optional — default 90 days, or `null` for no expiry, or an explicit day count |
| Resolves to (`request.user`) | synthetic `SystemServicePrincipal` (`is_authenticated=True`, `is_superadmin=True`, no `email`/`pk`) | the owning `User` — same live RBAC permissions that user would have with a JWT |
| How many can exist | one active at a time (singleton — seeding revokes any previous active `SYSTEM` key) | up to 5 active (non-revoked, non-expired) per user |
| Visible in `GET /api/admin/api-keys/` or `GET /api/profile/api-keys/` | never | yes, to its owner, and to any caller holding `api_keys` read in an organization the owner belongs to (or to a superadmin, always) |
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

---

## Self-service: `/api/profile/api-keys/`

JWT-only. Every endpoint below has `permission_classes = [IsAuthenticated,
DenyApiKeyAuth]` — an API-key-authenticated caller (including the SYSTEM
key) gets:

```json
{
  "status_code": 403,
  "code": "permission_denied",
  "message": "PermissionDenied: API keys cannot be used to manage API keys. Authenticate with a user session (JWT)."
}
```

This is intentional defense-in-depth: a leaked API key must not be usable
to mint or destroy other credentials.

### POST `/api/profile/api-keys/` — create a key

Request:

```json
{ "name": "laptop-cli", "expires_in_days": 30 }
```

- `name` — required, non-blank, max 255 characters.
- `expires_in_days` — optional:
  - **absent** → defaults to **90 days**.
  - **`null`** → never expires.
  - **integer** → must be `1..3650`; anything else (float, bool, 0, out of
    range) is rejected.

Response `201`:

```json
{
  "id": 12,
  "name": "laptop-cli",
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

- `400 api_key_limit_exceeded` — the caller already has 5 active keys
  (revoked and expired keys don't count toward the cap):
  ```json
  {
    "status_code": 400,
    "code": "api_key_limit_exceeded",
    "message": "ApiKeyLimitExceededError: Maximum number of active API keys reached (5). Revoke or delete an existing key first."
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
      { "field": "expires_in_days", "value": 0, "reason": "Must be null (no expiry) or an integer between 1 and 3650." }
    ]
  }
  ```

### GET `/api/profile/api-keys/` — list my keys

Returns the caller's own `USER` keys, newest first (`-created_at`). Never
includes the raw key or `key_hash`:

```json
[
  {
    "id": 12,
    "name": "laptop-cli",
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

### Scope: no header, ownership-derived

There is no `X-Organization-Id` on this surface — organization is data,
selected through the `?org_ids=` query param, never an implicit active
context. A key carries no organization of its own; its scope is the set
of organizations **its owner** belongs to:

- A caller **sees** a key in the list if they hold `api_keys` `READ` in
  at least one organization the owner belongs to.
- A caller may **revoke or delete** a key if they hold `api_keys`
  `DELETE` in at least one organization the owner belongs to.
- A key the caller can neither read nor retire anywhere in that set is
  **not visible**: revoke and delete answer `404 api_key_not_found`, the
  same as an unknown id, rather than a `403` that would confirm the key
  exists. A `403` is returned only when the caller holds `api_keys`
  `READ` in a shared organization — they can see the key in their list —
  but not `DELETE`.

A superadmin bypasses both checks and sees and retires every `USER` key,
including keys owned by other superadmins. Nobody else can see or reach a
superadmin-owned key at all — it is absent from their list and a revoke
or delete against its id returns `404 api_key_not_found`, identical to an
unknown id.

### Filters and ordering (`GET /api/admin/api-keys/`)

| Query param | Behavior |
|---|---|
| `?org_ids=1,2` | Comma-separated org ids; restricts the list to keys owned by members of those orgs. An id the caller cannot `api_keys` `READ` in (and isn't superadmin) fails the whole request with `403`. A non-integer value → `400 org_context_required`. Omitted → every org the caller can read. |
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
      "owner": { "id": 7, "email": "dev@acme.com", "display_name": "Dev User", "avatar_url": null },
      "org_ids": [10, 20]
    }
  ]
}
```

`org_ids` is the owner's organization memberships **intersected with the
organizations the caller can read** — it reports where the key's owner
works without widening what the caller is allowed to see. It never
indicates that the owner belongs to further organizations outside the
caller's view.

### Revoke / delete a member's key

Same semantics as self-service revoke/delete (idempotent revoke, hard
delete), authorized by the ownership-derived scope above. An id that
doesn't exist, is the SYSTEM key, belongs to an owner who shares no
organization with the caller, or belongs to an owner whose shared
organizations grant the caller neither `api_keys` `READ` nor `DELETE`,
returns `404 api_key_not_found` — the same non-enumerating 404 as
self-service.

### Cross-org revocation caveat

**API keys are not tied to any organization.** A `USER` key authenticates
its owner everywhere that owner is a member. Consequently:

> Revoking or deleting a member's key kills that key **everywhere** —
> including in every other organization the key's owner belongs to, even
> ones the acting administrator cannot see and does not know exist.
> There is no way to revoke a key "for this org only."

---

## MCP-style usage (API key + active org)

An external tool (an MCP server, a CI job, a script) authenticates as a
`USER` key plus an `X-Organization-Id` header and gets exactly the
permissions its owner has in that org — no separate scope system to
configure:

```bash
curl -s http://localhost:8000/api/admin/roles/ \
  -H "X-Api-Key: es-kR3f9s1n1qz8vY0aB2cD4eF6gH8iJ0kLmNoPqRsTuVw" \
  -H "X-Organization-Id: 3"
```

```powershell
Invoke-RestMethod http://localhost:8000/api/admin/roles/ `
  -Headers @{ "X-Api-Key" = "es-kR3f9s1n1qz8..."; "X-Organization-Id" = "3" }
```

- If the owner is a member of org `3`, the request is evaluated with that
  membership's role/permissions — identical to what the owner would get
  authenticating with a JWT and the same header.
- If the owner is **not** a member of org `3`, the request fails with:
  ```json
  { "status_code": 403, "code": "org_membership_required", "message": "OrgMembershipRequiredError: You are not a member of this organization." }
  ```
  (this also fires if the org exists but is inactive)
- If `X-Organization-Id` is missing or not an integer on an endpoint that
  requires it:
  ```json
  { "status_code": 400, "code": "org_context_required", "message": "OrgContextRequiredError: X-Organization-Id header is required for this endpoint." }
  ```

---

## SSE tickets with an API key

`POST /api/auth/sse-ticket/` accepts either JWT or API-key authentication
(`authentication_classes = [JwtAuthentication, ApiKeyAuthentication]`,
`permission_classes = [IsAuthenticated]`) — but it needs a real user
identity to bind the ticket to:

- A **`USER`** key works: the ticket is issued for the key's owner, same
  as if that owner had logged in with a JWT.
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
| `api_key_limit_exceeded` | 400 | Self-service create, at 5 active keys |
| `invalid` | 400 | Self-service create (bad `name`/`expires_in_days`); management `?status=`/`?user=` filters |
| `api_key_not_found` | 404 | Self-service revoke/delete on a foreign/unknown id; management revoke/delete on an unknown id, a SYSTEM key's id, a superadmin-owned key seen by a non-superadmin, or a key the caller cannot see — its owner shares no organization with them, or the shared organizations grant neither `api_keys` `READ` nor `DELETE` |
| `authentication_failed` | 401 | Any request authenticating with a raw key that doesn't match a non-revoked key (`"Invalid API key"`), matches an expired one (`"API key has expired"`), or matches a key whose owner's account is deactivated (`"API key owner is inactive"`) |
| `permission_denied` | 403 | `DenyApiKeyAuth` (API key used against a key-management endpoint), the `api_keys` door gate, a forbidden `?org_ids=` entry on the management list, or a revoke/delete on a key the caller can **see** (holds `api_keys` `READ` in a shared organization) but not retire |
| `org_membership_required` | 403 | Caller (JWT or API key) sends `X-Organization-Id` pointing to an org they are not a member of — applies to ordinary org-scoped endpoints; the admin API-key surface has no header and never raises this |
| `org_context_required` | 400 | `X-Organization-Id` missing or not an integer on a header-required endpoint; on the admin API-key list, a non-integer `?org_ids=` value |
| `not_authenticated` | 401 | No credential supplied at all |

See [auth_endpoints.md](auth_endpoints.md) for the rest of the auth
surface, and [roles_and_permissions.md](roles_and_permissions.md) for the
full `api_keys` / RBAC permission model.
