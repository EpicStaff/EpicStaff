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
| GET | `/api/auth/me/` | Bearer JWT (or user-owned ApiKey) | Current user + memberships |
| POST | `/api/auth/introspect/` | ApiKey | Validate a JWT, return claims |
| GET | `/api/auth/api-key/validate/` | ApiKey | Metadata about the calling key |
| POST | `/api/auth/swagger-token/` | public (throttled) | OAuth2 password flow for Swagger |
| POST | `/api/auth/reset-user/` | Bearer JWT or ApiKey | Destructive: wipe users+keys, recreate superadmin |

**Login/Swagger-token throttle:** `LOGIN_THROTTLE_RATE` env (default `5/min`), bucketed per `<ip>|<email>`. 6th attempt inside the window returns `429` with `Retry-After`.

**Refresh tokens rotate on every use** (`ROTATE_REFRESH_TOKENS=True`). The old refresh is blacklisted — replaying it returns `401`.

**SSE streams** require a ticket obtained from `POST /api/auth/sse-ticket/` and passed as `?ticket=` on the stream URL. See [`sse_auth.md`](./sse_auth.md) for the FE migration flow.

---

## Authentication schemes

Two authentication backends are composed in `JwtOrApiKeyAuthentication`:

### JWT (primary for end users)

- Header: `Authorization: Bearer <access_token>`
- Obtain via `POST /api/auth/login/` with `{ "email", "password" }`.
- Access token lifetime: `JWT_ACCESS_MINUTES` env (default 15).
- Refresh token lifetime: `JWT_REFRESH_DAYS` env (default 7).
- Token carries custom claims: `user_id`, `email`, `is_superadmin`.

### API key (primary for internal services)

- Header (preferred): `X-Api-Key: <raw_key>`
- Header (alt):       `Authorization: ApiKey <raw_key>`
- The backend resolves `request.user` to the key's `created_by` owner, and
  `request.auth` to the `ApiKey` instance.
- If `created_by` is `NULL` (env-seeded system key), `request.user` becomes
  `AnonymousUser`. This **fails `IsAuthenticated`** on every DRF endpoint
  using the default permission class. Make sure every key you need to use
  interactively has an owner (see "API keys" section below).

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

`entrypoint.sh` seeds a system-wide ApiKey from `DJANGO_API_KEY` and
round-trips `check_key()` to prove the raw value actually authenticates
against what's stored.

| Env var | Required | Default | Notes |
|---|---|---|---|
| `DJANGO_API_KEY` | optional | unset | Raw key value. If unset, the seeding block is skipped entirely. |
| `DJANGO_API_KEY_NAME` | optional | `system` | Display name for the created ApiKey row. |

Behavior:

- `DJANGO_API_KEY` unset → block skipped.
- Key with the same 8-char prefix already exists and matches → info log
  "already seeded and valid", skip.
- Key with the same prefix already exists but **does not** match
  `DJANGO_API_KEY` → `exit 1`. Env and DB are out of sync; silent auth
  failures would follow otherwise.
- No existing key → create, then re-fetch and `check_key()` against the raw
  value. If the round-trip fails, `exit 1`.

The seeded key has **no owner** (`created_by = NULL`). See
[API keys — lifecycle](#api-keys) for the consequences (env-seeded keys
resolve to `AnonymousUser` and don't pass `IsAuthenticated`).

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

### GET `/api/auth/me/`

- **Auth:** `IsAuthenticated`. JWT works. A user-owned ApiKey works. A null-owner
  ApiKey (`AnonymousUser`) is rejected with 403 because `/me/` requires a
  real user context.
- **Response 200:**
  ```json
  {
    "id": 1,
    "email": "admin@acme.com",
    "display_name": "Admin",
    "avatar_url": "http://host/media/avatars/...",   // null if not set
    "is_superadmin": true,
    "memberships": [
      {
        "organization": { "id": 1, "name": "Acme Inc" },
        "role":         { "id": 2, "name": "Org Admin" },
        "joined_at":    "2026-04-17T18:00:00Z"
      }
    ]
  }
  ```
- **403** when called with a null-owner ApiKey:
  ```json
  { "detail": "This endpoint requires a user context." }
  ```

Active-org resolution from the `X-Organization-Id` header is **not**
implemented in Story 2 — that lands in Story 7.

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

- **Auth:** `IsAuthenticated` + `isinstance(request.auth, ApiKey)` check.
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
- **Response 200 — expired/invalid/tampered token:** `{ "active": false }`
  (deliberately not an HTTP error — introspection is informational).
- **Errors:**
  - `400` — `{"active": false, "error": "token is required"}` when the
    `token` field is missing or blank.
  - `403` — `{"detail": "API key required"}` when the caller authenticated
    with JWT instead of an ApiKey.

### Testing it

You need (1) a JWT to introspect and (2) an API key to authenticate the
call itself.

```bat
REM 1. Get an access token via login
curl.exe -X POST http://localhost:8000/api/auth/login/ ^
  -H "Content-Type: application/json" ^
  -d "{\"email\":\"admin@acme.com\",\"password\":\"StrongPass123!\"}"

REM 2. Introspect it
curl.exe -X POST http://localhost:8000/api/auth/introspect/ ^
  -H "X-Api-Key: <raw_api_key>" ^
  -H "Content-Type: application/json" ^
  -d "{\"token\":\"<paste-access-jwt-here>\"}"
```

Negative tests:
- Call with `Authorization: Bearer <jwt>` instead of `X-Api-Key` → 403.
- Send a malformed token (`"token":"nope"`) → 200 with `active: false`.
- Omit `token` → 400.
- Wait `JWT_ACCESS_MINUTES` (default 15) and re-introspect the same token →
  200 with `active: false` (expired).

---

## API key validation

### GET `/api/auth/api-key/validate/`

Self-introspection — returns metadata about the key that authenticated the
request.

- **Auth:** must authenticate with an ApiKey (JWT callers get 403).
- **Response 200:**
  ```json
  {
    "active":        true,
    "name":          "realtime-default",
    "prefix":        "fnFo21Jt",
    "scopes":        [],
    "owner_user_id": 1    // null for env-seeded system keys
  }
  ```
- **Errors:**
  - `403` (`authentication_failed`) — key not found or revoked.
  - `403` (`permission_denied`) — **your key has `created_by=NULL`**, so
    `request.user` is `AnonymousUser` and `IsAuthenticated` blocks the
    request. Give the key an owner (see "API keys" section).

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

- **Auth:** `IsAuthenticated` (bearer JWT or owner-linked ApiKey).
- **Behavior** (atomic):
  1. Delete all `User` rows → cascades `OrganizationUser`,
     `PasswordResetToken`; sets `ApiKey.created_by` to NULL (`SET_NULL`).
  2. Delete all `ApiKey` rows.
  3. Create a new Superadmin from the supplied credentials.
  4. Create a fresh `realtime-default` ApiKey owned by the new Superadmin.
  5. Issue JWT tokens for the new user.
- **Organizations are not touched** — Superadmin bypasses permission checks
  via `is_superadmin`, so no automatic membership is created.
- **Request body:**
  ```json
  { "email": "new@acme.com", "password": "AnotherPass123!" }
  ```
- **Response 201:**
  ```json
  {
    "access":  "<jwt-access>",
    "refresh": "<jwt-refresh>",
    "api_key": "<raw key — copy it now, it is not retrievable again>"
  }
  ```
- **Errors:** `400` on validation failures.

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
Deleted <N> user(s) and <M> API key(s).
Created superuser 'admin@example.com'.
API key: <raw-key>
```

Copy the raw API key from the last line — it is not recoverable.

#### Caveats

- Organizations survive; the new Superadmin has no auto-membership.

---

## API keys

### Lifecycle

| Source | `created_by` | Auth behavior |
|---|---|---|
| `POST /api/auth/reset-user/` (web) | Owner = the new Superadmin | `request.user` = owner → `IsAuthenticated` passes |
| `python manage.py reset_user` | Owner = the new Superadmin | `request.user` = owner → `IsAuthenticated` passes |
| `entrypoint.sh` bootstrap (`DJANGO_API_KEY` env) | `NULL` | `request.user` = `AnonymousUser` → `IsAuthenticated` **fails** |
| Legacy keys created before this story | `NULL` | As above |

**If you need the env-seeded `DJANGO_API_KEY` (for internal services like
crew, realtime, webhook) to pass `IsAuthenticated`,** either:

1. Give the key an owner via DB shell (`ApiKey.objects.filter(prefix=...).update(created_by=<some user>)`)

### Header formats

```
X-Api-Key: <raw_key>
Authorization: ApiKey <raw_key>
```

Do **not** use `Authorization: Bearer <raw_key>` — that's reserved for JWT.

### Revoking

Mark `ApiKey.revoked_at = <timestamp>` (column on the model). The auth
backend filters `revoked_at__isnull=True`, so revoked keys start returning
`401 Invalid API key` immediately.

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

# 3. Current user
curl -s http://localhost:8000/api/auth/me/ -H "Authorization: Bearer $ACCESS" | jq .

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
| `/me` response shape | Changed. New fields: `display_name`, `avatar_url`, `is_superadmin`, `memberships[]`. Removed: `username`. FE should render email (not username) in the profile menu, and use `memberships` to populate the org/role sidebar. |
| JWT claims | Access token now carries `email` and `is_superadmin` in addition to `user_id`. FE may decode the access token locally to short-circuit UI gating without hitting `/me`. |
| 401 handling | Unchanged in shape — `{status_code: 401, code: "not_authenticated", message: ...}`. On 401 during a session, prompt re-login. |
| 409 on setup | New status code to handle on the setup flow. |
| `reset_user` web call | Payload is `{ email, password }` (was `{ username, password, email }`). Response still returns `access`, `refresh`, `api_key`. Consider masking/displaying the API key only once — it cannot be retrieved again. |
| Token introspection / API key validation | Only used by internal services; the FE typically does not call these. If it does, the endpoints require `X-Api-Key` now — JWT will get 403. |
| Admin UI (`/admin/`) | **Removed.** `django.contrib.admin` was dropped because our custom `User` has no `is_staff` field. Anything that linked to `/admin/` must be removed or redirected. |
| Active organization | Not wired up yet. `X-Organization-Id` header + `/me/` `active_org` block is Story 7. Until then, the FE can pick an org from `memberships[]` and display it, but there's no backend filtering by header. |
| Permissions UI | All Story-2 endpoints effectively require `IsAuthenticated`; the bitmask permission checks land in later stories (9 / 13). Until then the FE gates UI actions purely on `is_superadmin` / role name. |
| Env-seeded API key flows | If any FE flow uses `DJANGO_API_KEY` directly (unlikely — that's internal), those calls now need an owning user OR the FE must switch to JWT. |

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
| `/api/auth/me/` response | `{id, username, email}` | `{id, email, display_name, avatar_url, is_superadmin, memberships[]}` |
| `/api/auth/introspect/` response | `{active, user_id, username, scopes}` | `{active, user_id, email, scopes}` |
| `/api/auth/api-key/validate/` response | `{active, name, prefix, scopes}` | `{active, name, prefix, scopes, owner_user_id}` |
| `/api/auth/reset-user/` request | `{username, password, email?}` | `{email, password}` |
| `/admin/` | Django admin UI | **Removed** |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `authentication_failed / Invalid API key` | Wrong raw key, or key revoked, or key pasted partially (`prefix` must match first 8 chars of raw). | Check `ApiKey.objects.filter(prefix=<first-8>, revoked_at__isnull=True)`. |
| `permission_denied` with a valid API key | Key has `created_by=NULL` → `AnonymousUser` → `IsAuthenticated` fails. | Backfill owner or use a user-owned key. See "User reset" caveats. |
| `409 Setup has already been completed` | At least one User exists. | Expected. If intentional reset, use `POST /api/auth/reset-user/` or `manage.py reset_user`. |
| FE shows login form but `needs_setup` is `true` | Frontend isn't calling `GET /api/auth/first-setup/` on boot. | Wire the boot check per "Frontend changes required". |
| `/api/auth/login/` returns 401 on what looks like valid creds | Payload uses `username` instead of `email`. | Send `{"email": ..., "password": ...}`. |
| PowerShell's `curl -H` throws "Cannot bind parameter 'Headers'" | PowerShell aliases `curl` to `Invoke-WebRequest`. | Use `curl.exe`, `Invoke-RestMethod -Headers @{...}`, or `Remove-Item Alias:curl`. |
| `ALTER TABLE because it has pending trigger events` during migrate | Postgres deferred FK triggers. | Handled in 0170 with `SET CONSTRAINTS ALL IMMEDIATE`; if you see this on a different migration, add the same. |
| After swapping AUTH_USER_MODEL, `admin.LogEntry.user was declared with a lazy reference to 'tables.user'` | `django.contrib.admin` references the swapped model during state build. | Remove `django.contrib.admin` from `INSTALLED_APPS` |