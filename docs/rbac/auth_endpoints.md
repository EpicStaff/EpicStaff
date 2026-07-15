# RBAC — Auth Endpoints & Operator Guide

Covers the auth surface delivered by EST-2615: first-time
setup, JWT login, current-user, token introspection, API key validation,
user reset (destructive), and the `reset_user` management command. Ends with
a frontend migration checklist.

Base URL in examples: `http://localhost:8000`.

---

## Quick reference

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/auth/first-setup/` | public | Is initial setup needed? |
| POST | `/api/auth/first-setup/` | public | Create first superadmin + default org |
| POST | `/api/auth/login/` | public (throttled) | JWT login (email + password) |
| POST | `/api/auth/refresh/` | public | Exchange refresh → new access + rotated refresh |
| POST | `/api/auth/logout/` | Bearer JWT | Blacklist the caller's refresh token |
| POST | `/api/auth/sse-ticket/` | Bearer JWT | Issue a single-use SSE ticket (30-second TTL) |
| ~~GET~~ | ~~`/api/auth/me/`~~ | — | **REMOVED in Story 6** → use `GET /api/profile/`, see [user_profile.md](user_profile.md) |
| POST | `/api/auth/introspect/` | System ApiKey | Validate a JWT, return claims |
| GET | `/api/auth/api-key/validate/` | ApiKey (any) | Metadata about the calling key |
| POST | `/api/auth/swagger-token/` | public (throttled) | OAuth2 password flow for Swagger |
| POST | `/api/auth/reset-user/` | Bearer JWT or ApiKey (superadmin) | Destructive: wipe users+keys, recreate superadmin — response has no `api_key` |
| POST | `/api/auth/password-reset/request/` | public (throttled) | Start password-recovery flow — see [password_recovery.md](password_recovery.md) |
| POST | `/api/auth/password-reset/confirm/` | public | Consume reset token + set new password |
| ~~POST~~ | ~~`/api/auth/password-change/`~~ | — | **REMOVED in Story 6** → use two-step `/api/profile/password-change/{request,confirm}/`, see [user_profile.md](user_profile.md) § "Two-step password change" |
| POST | `/api/auth/admin/password-reset/` | Bearer JWT (superadmin) | Superadmin resets another user's password |
| GET, POST | `/api/profile/api-keys/` | Bearer JWT only | List / create my own API keys — see [api_keys.md](api_keys.md) |
| DELETE | `/api/profile/api-keys/{id}/` | Bearer JWT only | Hard-delete one of my own API keys |
| POST | `/api/profile/api-keys/{id}/revoke/` | Bearer JWT only | Revoke one of my own API keys (kept for audit) |
| GET | `/api/api-keys/` | Bearer JWT + SECRETS:READ | List API keys of active-org members |
| DELETE | `/api/api-keys/{id}/` | Bearer JWT + SECRETS:DELETE | Hard-delete a member's API key |
| POST | `/api/api-keys/{id}/revoke/` | Bearer JWT + SECRETS:UPDATE | Revoke a member's API key |

**Login/Swagger-token throttle:** `LOGIN_THROTTLE_RATE` env (default `5/min`), bucketed per `<ip>|<email>`. 6th attempt inside the window returns `429` with `Retry-After`.

**Refresh tokens rotate on every use** (`ROTATE_REFRESH_TOKENS=True`). The old refresh is blacklisted — replaying it returns `401`.

**SSE streams** require a ticket obtained from `POST /api/auth/sse-ticket/` and passed as `?ticket=` on the stream URL. See [`sse_auth.md`](./sse_auth.md) for the FE migration flow.

---

## Authentication schemes

Two authentication backends are declared per-view (in whatever order the
view lists them) as `authentication_classes = [JwtAuthentication,
ApiKeyAuthentication]`:

### JWT (primary for end users)

- Header: `Authorization: Bearer <access_token>`
- Obtain via `POST /api/auth/login/` with `{ "email", "password" }`.
- Access token lifetime: `JWT_ACCESS_MINUTES` env (default 15).
- Refresh token lifetime: `JWT_REFRESH_DAYS` env (default 7).
- Token carries custom claims: `user_id`, `email`, `is_superadmin`.

### API key (primary for internal services)

- Header (preferred): `X-Api-Key: <raw_key>`
- Header (alt):       `Authorization: ApiKey <raw_key>`
- `request.auth` is always the resolved `ApiKey` instance, so downstream
  code can check `isinstance(request.auth, ApiKey)` to detect a key caller.
- `request.user` depends on the key's `key_type` (see
  [api_keys.md](api_keys.md) for the full model):
  - **USER** key → `request.user` is the key's `created_by` owner. Behaves
    exactly like that user would with a JWT — same RBAC permissions per
    `X-Organization-Id`.
  - **SYSTEM** key (the singleton seeded from `DJANGO_API_KEY`) →
    `request.user` is a synthetic `SystemServicePrincipal`
    (`is_authenticated=True`, `is_superadmin=True`, no `email`/`pk`). It
    passes `IsAuthenticated` and any superadmin gate, but user-context
    endpoints such as `GET /api/profile/` and `POST
    /api/auth/sse-ticket/` reject it with `403` because it has no user
    identity.

### Unauthenticated 401

```json
{
  "status_code": 401,
  "code": "not_authenticated",
  "message": "Authentication credentials were not provided."
}
```

Shape comes from `utils/exception_handler.custom_exception_handler`.

---

## Active-organization header

The `X-Organization-Id` header carries the **active organization** —
the workspace the caller is currently operating in. It is required for
active-context endpoints (those that need to know which workspace the
caller is operating in): `/api/permissions/me/`, `/api/admin/roles/`
(list and detail), and any future resource endpoint that scopes by
current org. URL-nested admin endpoints
(`/api/admin/organizations/{org_id}/...`) use the URL kwarg instead and
do not need the header.

When the header is missing or contains a non-integer value on a
header-required endpoint, the response is `400` with code
`org_context_required`. When the header points to an org the caller
isn't a member of (and is not superadmin), `403` with code
`org_membership_required`. Superadmin can set any `org_id` and bypasses
the membership check.

`/api/profile/` is the exception — when the header is absent, malformed,
or points to an inaccessible org, both `active_organization_id` and
`active_permissions` are returned as `null` (soft-fail) so the boot
endpoint stays reachable for users with deactivated orgs or no
memberships yet.

See [roles_and_permissions.md](roles_and_permissions.md) for the full
payload shapes of every header-required endpoint.

---

## First-time setup

### GET `/api/auth/first-setup/`

- **Auth:** none.
- **Purpose:** frontend calls this on every app boot to decide whether to
  render the setup screen or the login screen.
- **Response 200:**
  ```json
  { "needs_setup": true }
  ```
- `needs_setup` is `true` iff no `User` row exists in the database.

### POST `/api/auth/first-setup/`

- **Auth:** none.
- **Purpose:** bootstrap the very first Superadmin, their default
  Organization, and an `OrganizationUser` membership with the built-in
  Org Admin role. Also returns JWT tokens so the frontend can drop the user
  straight into the workspace without a second login call.
- **Request body:**
  ```json
  {
    "email": "admin@acme.com",
    "password": "StrongPass123!"
  }
  ```
  - `email` — must be a valid email.
  - `password` — must pass Django's `AUTH_PASSWORD_VALIDATORS` (min length,
    not-too-common, not-all-numeric, not-too-similar-to-email).
  - Organization name is **not** taken from the request body; it comes from
    the `DEFAULT_ORGANIZATION_NAME` setting (env-driven, default
    `"Default Organization"`). Any `organization_name` / `display_name`
    fields passed in the body are silently ignored.
- **Response 201:**
  ```json
  {
    "user": {
      "id": 1,
      "email": "admin@acme.com",
      "display_name": null,
      "is_superadmin": true
    },
    "organization": {
      "id": 1,
      "name": "Default Organization",
      "is_active": true
    },
    "access":  "<jwt-access>",
    "refresh": "<jwt-refresh>"
  }
  ```
- **Errors:**
  - `400` — validation failure. Every failing field is aggregated into a
    structured `errors` list; passwords are redacted as `"***"`:
    ```json
    {
      "status_code": 400,
      "code": "invalid",
      "message": "FormValidationError: Validation failed",
      "errors": [
        { "field": "email",    "value": "not-an-email", "reason": "Enter a valid email address." },
        { "field": "password", "value": "***",          "reason": "This password is too common." },
        { "field": "password", "value": "***",          "reason": "This password is entirely numeric." }
      ]
    }
    ```
  - `409` — `{"detail": "Setup has already been completed"}` when any user
    already exists.

Setup runs inside `transaction.atomic()` — user + org + membership are created
atomically or not at all.

### Bootstrapping via `entrypoint.sh` (optional, off by default)

For CI, staging, or local dev you can have the container bootstrap the first
superadmin automatically instead of going through the UI. This is **off by
default** to avoid conflicts with the `/first-setup/` endpoint (if both
paths ran, the endpoint would then return 409).

Enable by setting in the service environment:

| Env var | Required | Example | Notes |
|---|---|---|---|
| `DJANGO_AUTO_CREATE_ADMIN` | yes | `True` | Accepts only `True`, `true`, `False`, `false`. Anything else → entrypoint aborts (`exit 1`). |
| `DJANGO_ADMIN_EMAIL` | when flag is `True` | `admin@acme.com` | |
| `DJANGO_ADMIN_PASSWORD` | when flag is `True` | `StrongPass123!` | Used exactly as given. The entrypoint **never generates** or rewrites it. |
| `DEFAULT_ORGANIZATION_NAME` | optional | `Acme Inc` | Name for the default Organization. Falls back to `"Default Organization"` when unset. Read from `settings.DEFAULT_ORGANIZATION_NAME` — applies to both the HTTP endpoint and the entrypoint bootstrap. |

`docker-compose.yaml` forwards these vars into the `django_app` container
already. Compose does not pass arbitrary `.env` entries into services — only
what's explicitly listed under `environment:` — so if you add new RBAC env
vars, wire them there too.

When enabled, `entrypoint.sh` calls `FirstSetupService.setup(...)` — the
exact same code path as the endpoint — so the resulting state (User +
Organization + OrganizationUser(Org Admin)) is identical.

Behavior matrix:

| Condition | Action |
|---|---|
| Flag is `False` / `false` | Info log, skip. Create the admin via `POST /api/auth/first-setup/`. |
| Flag is any other non-`True`/`true` value | `exit 1` with an error naming the bad value. |
| Flag is `True`/`true` and any required var is empty | ERROR log naming each missing var, skip bootstrap, point to `POST /api/auth/first-setup/`. Container continues to start. |
| Flag is `True`/`true`, all vars present, **no user exists** | Run `FirstSetupService.setup(...)`. |
| Flag is `True`/`true`, all vars present, **user already exists** | Info log "Superadmin already exists — skipping bootstrap". |

### System API key (`DJANGO_API_KEY`)

`entrypoint.sh` runs `python manage.py seed_system_api_key` on every
container start, which seeds/rotates the singleton `SYSTEM`-type `ApiKey`
row from the `DJANGO_API_KEY` env var.

| Env var | Required | Default | Notes |
|---|---|---|---|
| `DJANGO_API_KEY` | optional | unset | Raw key value. If unset, the command logs a warning and skips seeding entirely — no system key exists, and internal services (realtime) cannot authenticate. |

Behavior (`SystemKeyService.seed_from_env`, invariant: at most one active
`SYSTEM` key exists at a time):

- Env value hashes to an existing, non-revoked `SYSTEM` key → that row is
  reused as-is (no-op).
- Otherwise → any existing active `SYSTEM` key is revoked and a new
  `SYSTEM` key is created from the env value, atomically. This is the
  rotation path: changing `DJANGO_API_KEY` and restarting the container
  revokes the old key and mints a new one with the new value.

The system key has **no owner** (`created_by = NULL`, enforced by the
`api_key_type_invariants` check constraint) and **never expires**. See
[api_keys.md](api_keys.md) for how it resolves at auth time
(`SystemServicePrincipal`) and its visibility rules (never appears in any
API listing; not revocable/deletable over HTTP).

---

## JWT login, refresh, logout

### POST `/api/auth/login/`

Standard simplejwt endpoint, customized to **accept `email` instead of
`username`**. Returns access + refresh tokens.

```bash
curl -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@acme.com","password":"StrongPass123!"}'
```

Response:
```json
{ "access": "<jwt>", "refresh": "<jwt>" }
```

- `400` with a structured `errors` list when `email` or `password` is missing
  or the wrong type. Missing/blank/bad-type failures for both fields are
  aggregated in one response; password values are redacted as `"***"`.
- `401` on invalid credentials — flat envelope with no `errors` array, so the
  caller cannot distinguish which of email/password was wrong (user-enumeration
  protection).
- `429` with `Retry-After` header once the composite `<ip>|<email>` bucket is
  exhausted. Rate comes from `LOGIN_THROTTLE_RATE` (default `5/min`).

### POST `/api/auth/refresh/`

Body: `{ "refresh": "<jwt>" }` → returns a new `{access, refresh}` pair.

- **Refresh-token rotation is on** (`ROTATE_REFRESH_TOKENS=True`,
  `BLACKLIST_AFTER_ROTATION=True`). Every successful refresh issues a **new**
  refresh token and blacklists the one you just sent.
- Replaying an old refresh returns `401`. If your storage was tampered with
  or the network duplicated the request, re-login.

### POST `/api/auth/logout/`

- **Auth:** `IsAuthenticated` via JWT.
- **Body:**
  ```json
  { "refresh": "<jwt-refresh>" }
  ```
- **Success:** `205 Reset Content` with `{ "detail": "Logged out." }`. The
  refresh token is blacklisted so it can no longer be rotated.
- **Error:** `400` with
  ```json
  { "status_code": 400, "code": "invalid_or_expired_refresh",
    "message": "Refresh token is invalid, expired, or already revoked." }
  ```
  on malformed, expired, already-blacklisted, **or third-party** tokens.
  Ownership is enforced — if the refresh token belongs to a different user
  than the JWT access token authenticating the call, it is rejected with the
  same error as a malformed token (so callers cannot distinguish "real but
  not yours" from "garbage"). This stops a leaked refresh token from being
  weaponized to log the owner out.
- The short-lived **access** token continues to work until its own expiry
  (default 15 min). Keep access TTL short; consult `JWT_ACCESS_MINUTES`.

---

## SSE authentication

See the dedicated [`sse_auth.md`](./sse_auth.md) for the complete FE flow.

### POST `/api/auth/sse-ticket/`

- **Auth:** `IsAuthenticated` (JWT or user-owned ApiKey).
- **Body:** none.
- **Response 200:**
  ```json
  { "ticket": "<opaque random>", "expires_in": 30 }
  ```
- Tickets are **single-use** and stored in Redis under
  `rbac:sse_ticket:<token>` keys. TTL is `SSE_TICKET_TTL_SECONDS`
  (hardcoded to 30 seconds in `settings.py`). Consume uses Redis `GETDEL` (6.2+) for
  atomic get-and-delete, so even two simultaneous connects with the same
  ticket cannot both succeed. Reconnects must fetch a fresh ticket.
- SSE endpoints reject missing/invalid/expired tickets with
  ```json
  { "status_code": 401, "code": "invalid_sse_ticket",
    "message": "Invalid or expired SSE ticket." }
  ```

---

## Current user

### GET `/api/auth/me/` — REMOVED in Story 6

Replaced by `GET /api/profile/`. See [user_profile.md](user_profile.md).
The new payload is a strict superset of the old `/me/` response
(adds `is_active`, `created_at`, `updated_at`, `memberships[].id`, and
`memberships[].organization.is_active`; only active-org memberships are
returned).

---

## Token introspection

### POST `/api/auth/introspect/`

Service-to-service JWT validator. Two-layer auth: **the caller authenticates
with an API key**, and **the token in the body is the one being inspected**.

**Why it exists:**
- Internal services / sidecars that should not hold `JWT_SECRET` can verify
  bearer tokens over HTTP instead of decoding locally.
- Gateways or reverse proxies (Nginx + njs, edge auth) can validate incoming
  tokens with their own service API key.
- Operational debugging — confirm a token is still valid and see who owns it
  without decoding claims by hand.

`django_app` signs its own JWTs with `JWT_SECRET` and does not need this
endpoint internally; it is exposed for future internal / edge callers and
for quick health-checks of the login chain.

- **Auth:** `IsAuthenticated` (JWT or ApiKey both authenticate), **and** the
  resolved credential must be a **SYSTEM**-type key. A JWT caller or a
  USER-type key both get rejected — this endpoint is for internal
  services/gateways holding the system key, not for end users.
- **Request body:**
  ```json
  { "token": "<jwt-access-to-check>" }
  ```
- **Response 200 — active token:**
  ```json
  {
    "active":  true,
    "user_id": 1,
    "email":   "admin@acme.com",
    "scopes":  []
  }
  ```
  `scopes` is always `[]` — access tokens carry no scopes claim; the field
  is kept in the response shape for forward compatibility.
- **Response 200 — expired/invalid/tampered token:** `{ "active": false }`
  (deliberately not an HTTP error — introspection is informational).
- **Errors:**
  - `400` — `{"active": false, "error": "token is required"}` when the
    `token` field is missing or blank.
  - `403` — `{"detail": "System API key required"}` when the caller did
    not authenticate with a SYSTEM-type key (covers both a plain JWT and a
    USER-type API key).

### Testing it

You need (1) a JWT to introspect and (2) an API key to authenticate the
call itself.

```bat
REM 1. Get an access token via login
curl.exe -X POST http://localhost:8000/api/auth/login/ ^
  -H "Content-Type: application/json" ^
  -d "{\"email\":\"admin@acme.com\",\"password\":\"StrongPass123!\"}"

REM 2. Introspect it — <raw_api_key> must be the SYSTEM key (from DJANGO_API_KEY)
curl.exe -X POST http://localhost:8000/api/auth/introspect/ ^
  -H "X-Api-Key: <raw_api_key>" ^
  -H "Content-Type: application/json" ^
  -d "{\"token\":\"<paste-access-jwt-here>\"}"
```

Negative tests:
- Call with `Authorization: Bearer <jwt>` instead of `X-Api-Key` → 403.
- Call with a USER-type API key (e.g. one created via
  `POST /api/profile/api-keys/`) → 403 `System API key required`.
- Send a malformed token (`"token":"nope"`) → 200 with `active: false`.
- Omit `token` → 400.
- Wait `JWT_ACCESS_MINUTES` (default 15) and re-introspect the same token →
  200 with `active: false` (expired).

---

## API key validation

### GET `/api/auth/api-key/validate/`

Self-introspection — returns metadata about the key that authenticated the
request.

- **Auth:** must authenticate with an ApiKey — either USER or SYSTEM type
  (JWT callers get 403). Unlike `/api/auth/introspect/`, this endpoint has
  no `DenyApiKeyAuth`-style restriction; any valid key may call it.
- **Response 200:**
  ```json
  {
    "active":        true,
    "name":          "system",
    "prefix":        "es_fnFo21JtA",
    "owner_user_id": null    // null for the SYSTEM key; a user id for a USER key
  }
  ```
  There is no `scopes` field — permissions come from the owning user's
  live RBAC role (or superadmin, for the system key), not a per-key scope
  list.
- **Errors:**
  - `401` (`authentication_failed`, message `"Invalid API key"`) — key hash
    not found, or the key is revoked.
  - `401` (`authentication_failed`, message `"API key has expired"`) — key
    found but `expires_at` is in the past.
  - `403` (`detail: "API key required"`) — caller authenticated with JWT
    instead of an ApiKey.

### Calling it

```powershell
# force real curl
curl.exe http://localhost:8000/api/auth/api-key/validate/ -H "X-Api-Key: <raw_key>"

# native PowerShell
Invoke-RestMethod http://localhost:8000/api/auth/api-key/validate/ `
  -Headers @{ "X-Api-Key" = "<raw_key>" }
```

cmd.exe or real bash are fine with the plain `curl` syntax.

### Swagger UI

The current OpenAPI security scheme only advertises OAuth2 password flow, so
Swagger's Authorize dialog offers a JWT login form only — there's no way to
paste an API key. To test API-key-only endpoints from Swagger, either use
the cURL example box or add an `apiKey` security definition.

---

## User reset (destructive)

Two entry points, same semantics, different callers.

### POST `/api/auth/reset-user/` (web, via JWT)

- **Auth:** `IsAuthenticated` + `IsSuperadmin`. Both JWT and ApiKey
  authentication are accepted (no `DenyApiKeyAuth` here) — the caller just
  needs `is_superadmin=True`, which a superadmin-owned USER key or the
  SYSTEM key both satisfy.
- **Behavior** (atomic):
  1. Delete all `User` rows → cascades `OrganizationUser`,
     `PasswordResetToken`, and every `ApiKey` owned by a deleted user
     (`ApiKey.created_by` is `on_delete=CASCADE`).
  2. The `SYSTEM` API key survives untouched — it has no `created_by`, so
     the cascade never reaches it.
  3. Provision a fresh Superadmin from the supplied credentials, with an
     `OrganizationUser` membership (built-in Superadmin role) in the
     default Organization — the existing default org is reused if one
     exists, otherwise a new one is created.
  4. Issue JWT tokens for the new user.
- No new API key is created by this flow — personal keys come only from
  `POST /api/profile/api-keys/` after logging in as the new superadmin.
- **Request body:**
  ```json
  { "email": "new@acme.com", "password": "AnotherPass123!" }
  ```
- **Response 201:**
  ```json
  {
    "access":  "<jwt-access>",
    "refresh": "<jwt-refresh>"
  }
  ```
- **Errors:** `400` on validation failures, `403` if the caller is not a
  superadmin.

### `python manage.py reset_user` (CLI / docker exec)

Same functional outcome as the web endpoint, intended for operators who lost
access to the UI.

```bash
# From inside the container
docker exec -it django_app python manage.py reset_user --email admin@example.com --password 'StrongPass123!'

# Or via docker compose (run from src/)
docker compose exec django_app python manage.py reset_user --email admin@example.com --password 'StrongPass123!'
```

PowerShell — use double quotes + escape `!` if needed:
```powershell
docker exec django_app python manage.py reset_user `
  --email admin@example.com --password "StrongPass123!"
```

Output:
```
Created superadmin 'admin@example.com'.
```

No API key is printed — the command deletes every user-owned key (they
cascade with their owner) and creates none. The SYSTEM key is unaffected.
Create a personal key afterwards via `POST /api/profile/api-keys/`.

#### Caveats

- Organizations are never deleted; the new Superadmin's membership reuses
  the existing default org if one exists.

---

## API keys

Two key classes exist — `SYSTEM` (the singleton seeded from
`DJANGO_API_KEY`) and `USER` (self-service, created via
`POST /api/profile/api-keys/`, owned by whoever created them). A `USER`
key always has an owner and inherits that owner's live RBAC permissions;
the `SYSTEM` key has no owner and resolves to a superadmin-equivalent
`SystemServicePrincipal`. Header formats: `X-Api-Key: <raw_key>` (preferred)
or `Authorization: ApiKey <raw_key>`.

Full model, self-service + management endpoints, TTL/cap rules, revoke vs.
delete, org-scoped management, and error codes are documented in
[api_keys.md](api_keys.md).

---

## Setup → login → use: end-to-end

```bash
# 1. Setup
curl -s -X POST http://localhost:8000/api/auth/first-setup/ \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@acme.com","password":"StrongPass123!"}' | jq .

# 2. Login
ACCESS=$(curl -s -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@acme.com","password":"StrongPass123!"}' | jq -r .access)

# 3. Current user — Story 6+ uses /api/profile/ (replaces /api/auth/me/)
curl -s http://localhost:8000/api/profile/ -H "Authorization: Bearer $ACCESS" | jq .

# 4. Use any protected endpoint
curl -s http://localhost:8000/api/graphs/ -H "Authorization: Bearer $ACCESS" | jq .
```

---

## Frontend changes required

| Area | Change |
|---|---|
| Login form | Field label must send **`email`** (not `username`) in the request body to `POST /api/auth/login/` (previously `/api/auth/token/`) and `POST /api/auth/swagger-token/`. Field in request JSON is literally `"email"`. |
| Logout flow | New — call `POST /api/auth/logout/` with `{refresh}` before dropping tokens from storage. 205 on success, 400 if the refresh is already dead. |
| Refresh rotation | Each call to `POST /api/auth/refresh/` (renamed from `/api/auth/token/refresh/`) returns a **new** refresh in addition to the access token — overwrite local storage with both values. The previous refresh is blacklisted; replaying it → 401. |
| Login throttling | 6th credential attempt within the bucket window returns `429` with a `Retry-After` header. Surface a "too many attempts, retry in N seconds" message instead of generic error. |
| SSE streams | EventSource can no longer connect directly. Fetch a ticket via `POST /api/auth/sse-ticket/`, then connect with `?ticket=<value>`. On `onerror` / reconnect, fetch a **fresh** ticket first. Full migration guide: [`sse_auth.md`](./sse_auth.md). |
| First-setup screen | Call `GET /api/auth/first-setup/` on boot; if `needs_setup: true`, show the setup form. POST payload is `{ email, password }` — the organization name is sourced from the `DEFAULT_ORGANIZATION_NAME` setting on the server, not the request body. Response returns `access` + `refresh` — persist them and skip the login screen on success. |
| Idempotency | A repeated `POST /api/auth/first-setup/` returns **409** with `{"detail": "Setup has already been completed"}`. Handle this explicitly (e.g. redirect to login). |
| Current-user endpoint | `/api/auth/me/` is **removed**. Use `GET /api/profile/` instead. Response is a strict superset of the old `/me/` payload. See [user_profile.md](user_profile.md) § "Migrating from `/api/auth/me/`". |
| JWT claims | Access token now carries `email` and `is_superadmin` in addition to `user_id`. FE may decode the access token locally to short-circuit UI gating without hitting `/api/profile/`. |
| 401 handling | Unchanged in shape — `{status_code: 401, code: "not_authenticated", message: ...}`. On 401 during a session, prompt re-login. |
| 409 on setup | New status code to handle on the setup flow. |
| `reset_user` web call | Payload is `{ email, password }` (was `{ username, password, email }`). Response returns only `access` + `refresh` — **no** `api_key`. Personal API keys are created separately via `POST /api/profile/api-keys/`, see [api_keys.md](api_keys.md). |
| Token introspection / API key validation | Only used by internal services; the FE typically does not call these. `POST /api/auth/introspect/` requires the SYSTEM API key specifically (JWT and USER keys get 403); `GET /api/auth/api-key/validate/` accepts any API key but not JWT. |
| Admin UI (`/admin/`) | **Removed.** `django.contrib.admin` was dropped because our custom `User` has no `is_staff` field. Anything that linked to `/admin/` must be removed or redirected. |
| Active organization | Not wired up yet. `X-Organization-Id` header + active-org resolution on `/api/profile/` is Story 7. Until then, the FE can pick an org from `memberships[]` and display it, but there's no backend filtering by header. |
| Active org header | `X-Organization-Id` required from this story onward on active-context endpoints. See [`roles_and_permissions.md`](roles_and_permissions.md). |
| Permissions UI | All Story-2 endpoints effectively require `IsAuthenticated`; the bitmask permission checks land in later stories (9 / 13). Until then the FE gates UI actions purely on `is_superadmin` / role name. |
| Personal API keys | New self-service surface: `GET/POST /api/profile/api-keys/`, `DELETE /api/profile/api-keys/{id}/`, `POST /api/profile/api-keys/{id}/revoke/`. JWT-only — calling these with an API key gets 403. The raw key is only ever shown once, in the create response. See [api_keys.md](api_keys.md). |

### Renamed / removed fields the FE must no longer reference

- `username` on User — gone; use `email`.
- `first_name` / `last_name` on User — gone; use `display_name`.
- Graph `OrganizationUser.name` (the anonymous flow end-user name) — the
  entire concept is gone. Flow end-users are now RBAC `User` + org
  membership. Any FE code that displayed a bare string "end-user name" needs
  to be replaced with the authenticated user's email/display_name.

### Endpoint shape summary (before → after)

| Endpoint | Before | After |
|---|---|---|
| `/api/auth/token/` → **`/api/auth/login/`** | `{username, password}` | `{email, password}` (renamed path) |
| `/api/auth/token/refresh/` → **`/api/auth/refresh/`** | returns `{access}` only | returns `{access, refresh}` (rotation on) |
| `/api/auth/logout/` | *did not exist* | new — `{refresh}` → 205 |
| `/api/auth/sse-ticket/` | *did not exist* | new — JWT-authed; returns `{ticket, expires_in}` |
| `/api/auth/first-setup/` POST request | `{username, password, email?}` | `{email, password}` (org name comes from `DEFAULT_ORGANIZATION_NAME`) |
| `/api/auth/first-setup/` POST response | `{access, refresh, api_key}` | `{user, organization, access, refresh}` |
| ~~`/api/auth/me/`~~ | `{id, username, email}` | **Removed** — replaced by `GET /api/profile/`, see [user_profile.md](user_profile.md). |
| `/api/auth/introspect/` response | `{active, user_id, username, scopes}` | `{active, user_id, email, scopes}` |
| `/api/auth/api-key/validate/` response | `{active, name, prefix, scopes}` | `{active, name, prefix, owner_user_id}` (no `scopes`) |
| `/api/auth/reset-user/` request | `{username, password, email?}` | `{email, password}` |
| `/admin/` | Django admin UI | **Removed** |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `401 authentication_failed — "Invalid API key"` | Lookup is an exact match on `key_hash` (SHA-256 of the raw key) — any typo, a truncated paste, or a revoked key all miss. Raw keys are always `es_`-prefixed. | Re-copy the full raw key from where it was issued (it's shown once, at creation). If it was revoked, issue a new one via `POST /api/profile/api-keys/`. See [api_keys.md](api_keys.md). |
| `401 authentication_failed — "API key has expired"` | The key's `expires_at` is in the past. | Issue a new key; the expired one cannot be renewed. |
| `409 Setup has already been completed` | At least one User exists. | Expected. If intentional reset, use `POST /api/auth/reset-user/` or `manage.py reset_user`. |
| FE shows login form but `needs_setup` is `true` | Frontend isn't calling `GET /api/auth/first-setup/` on boot. | Wire the boot check per "Frontend changes required". |
| `/api/auth/login/` returns 401 on what looks like valid creds | Payload uses `username` instead of `email`. | Send `{"email": ..., "password": ...}`. |
| PowerShell's `curl -H` throws "Cannot bind parameter 'Headers'" | PowerShell aliases `curl` to `Invoke-WebRequest`. | Use `curl.exe`, `Invoke-RestMethod -Headers @{...}`, or `Remove-Item Alias:curl`. |
| `ALTER TABLE because it has pending trigger events` during migrate | Postgres deferred FK triggers. | Handled in 0170 with `SET CONSTRAINTS ALL IMMEDIATE`; if you see this on a different migration, add the same. |
| After swapping AUTH_USER_MODEL, `admin.LogEntry.user was declared with a lazy reference to 'tables.user'` | `django.contrib.admin` references the swapped model during state build. | Remove `django.contrib.admin` from `INSTALLED_APPS` |