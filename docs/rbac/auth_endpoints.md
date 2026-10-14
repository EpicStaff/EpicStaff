# RBAC — Auth Endpoints & Operator Guide

Covers the auth surface: first-time
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
| POST | `/api/auth/reset-user/` | Bearer JWT (superadmin) | Destructive: wipe users+keys, recreate superadmin — response has no `api_key` |
| POST | `/api/auth/password-reset/request/` | public (throttled) | Start password-recovery flow; a no-op without SMTP (operators use `manage.py reset_password`) — see [password_recovery.md](password_recovery.md) |
| POST | `/api/auth/password-reset/confirm/` | public | Consume reset token + set new password |
| ~~POST~~ | ~~`/api/auth/password-change/`~~ | — | **REMOVED in Story 6** → use two-step `/api/profile/password-change/{request,confirm}/`, see [user_profile.md](user_profile.md) § "Two-step password change" |
| POST | `/api/auth/admin/password-reset/` | Bearer JWT (superadmin) | Superadmin resets another user's password |
| GET, POST | `/api/profile/api-keys/` | Bearer JWT only | List / create my own API keys — see [api_keys.md](api_keys.md) |
| DELETE | `/api/profile/api-keys/{id}/` | Bearer JWT only | Hard-delete one of my own API keys |
| POST | `/api/profile/api-keys/{id}/revoke/` | Bearer JWT only | Revoke one of my own API keys (kept for audit) |
| GET | `/api/admin/api-keys/` | Bearer JWT + api_keys:READ (in ≥1 org) | List API keys of members the caller administers |
| DELETE | `/api/admin/api-keys/{id}/` | Bearer JWT + api_keys:DELETE (in ≥1 shared org) | Hard-delete a member's API key |
| POST | `/api/admin/api-keys/{id}/revoke/` | Bearer JWT + api_keys:DELETE (in ≥1 shared org) | Revoke a member's API key |

**Throttles.** Every anonymous credential-adjacent endpoint is rate limited; exceeding a bucket returns `429` with `Retry-After`.

| Endpoint | Bucket | Env var | Default |
|---|---|---|---|
| `/api/auth/login/`, `/api/auth/swagger-token/` | `<ip>\|<email>` | `DJANGO_LOGIN_THROTTLE_RATE` | `5/min` |
| `/api/auth/login/`, `/api/auth/swagger-token/` | `<ip>` | `DJANGO_LOGIN_IP_THROTTLE_RATE` | `20/min` |
| `/api/auth/password-reset/request/` | `<ip>\|<email>` | `DJANGO_PASSWORD_RESET_REQUEST_THROTTLE_RATE` | `5/hour` |
| `/api/auth/password-reset/request/` | `<ip>` | `DJANGO_PASSWORD_RESET_REQUEST_IP_THROTTLE_RATE` | `20/hour` |
| `/api/auth/password-reset/confirm/` | `<ip>` | `DJANGO_PASSWORD_RESET_CONFIRM_THROTTLE_RATE` | `10/hour` |
| `/api/auth/refresh/` | `<ip>` | `DJANGO_TOKEN_REFRESH_THROTTLE_RATE` | `30/min` |

Login and reset-request each apply two buckets, and a request is refused when either is exhausted. The `<ip>|<email>` bucket limits what one address can do to one account (guesses at its password, reset emails to its mailbox) without one user's attempts using up the allowance of everyone behind the same NAT. It never stops an address that names a new email on each request, since every email is a fresh bucket; the `<ip>` bucket caps that total. The `<ip>` bucket's `429` depends only on the caller's IP, so it reveals nothing about which emails are registered.

Refresh and confirm key on IP alone: neither request carries an identifier to compose with — the refresh token arrives in an HttpOnly cookie, and on confirm the only caller-supplied value is the token being guessed, so bucketing by it would give an attacker a fresh allowance per attempt.

**Login has no account lockout.** Wrong passwords never lock or slow down an account; the two login throttles are the only brake on password guessing. The `<ip>|<email>` bucket limits guessing at one account (credential stuffing, brute force), the `<ip>` bucket limits trying one password across many accounts (password spraying). Both key on the client address, so everything below about that address protects the login endpoint directly. An attacker with many addresses is not stopped by either; that would need a lockout or a proxy-level limit, neither of which exists today.

### Client address and the proxy contract

Every `<ip>` above is DRF's `get_ident()`: the entry `NUM_PROXIES` positions from the end of `X-Forwarded-For`. That is only the caller's real address if each layer keeps its part of this contract:

- **nginx** (`src/nginx/templates/default.conf.template`) sets the forwarding headers itself, per location:
  - `X-Forwarded-Proto`: every location.
  - `X-Forwarded-For` (`$proxy_add_x_forwarded_for`) and `X-Real-IP`: every location except `/static/` and `/media/`, which serve files and run no throttle.
  - `X-Forwarded-Host`: only `/webhooks/`, `/voice/` and `/voice/stream`.
  - `X-Forwarded-Port`: never.

  Every proxying location also includes `strip-underscore-forwarding-headers.snippet`, which drops the spellings of `X-Forwarded-For`, `X-Forwarded-Proto`, `X-Forwarded-Host` and `X-Real-IP` that have an underscore in place of any dash (`X_Forwarded_For`, `X-Forwarded_For`, ...). Django maps a dash and an underscore to the same `META` key and joins the values, so without this a client-sent `X_Forwarded_For` lands after nginx's entry and becomes the throttle identity. A location added later must include the snippet too.
- **Django** drops the same underscore spellings again, in any letter case, plus those of `X-Forwarded-Port`, before `META` is built (`DropUnderscoreForwardingHeadersMiddleware`, wrapped around the whole ASGI application in `django_app/asgi.py`). This covers a regressed nginx config or a different proxy in front. Django reads only `X-Forwarded-For` (through DRF) and `X-Forwarded-Proto` (`SECURE_PROXY_SSL_HEADER`); `USE_X_FORWARDED_HOST` and `USE_X_FORWARDED_PORT` are off, so the dash spellings of `X-Forwarded-Host` and `X-Forwarded-Port` are ignored.
- **`DJANGO_NUM_PROXIES`** (default `1`, the bundled nginx) must equal the number of trusted proxies that append to `X-Forwarded-For` before Django. Set it too high and Django reads an entry the client wrote, so callers choose their own identity. Set it too low and Django reads a proxy's address, so every caller shares one bucket. Put a load balancer in front of nginx and the value becomes `2`, but only if that load balancer appends the client address to `X-Forwarded-For`.

`underscores_in_headers on` stays enabled in nginx. Webhook triggers authenticate with a header whose name the user chooses (`request.headers.get(auth.header_name)` in `src/webhook/app/controllers/webhook_routes.py`), third-party senders often use names with underscores, and nginx drops those by default. That is why the forwarding look-alikes are stripped one by one instead of turning the directive off.

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
- Access token lifetime: `ACCESS_TOKEN_LIFETIME`, env `DJANGO_JWT_ACCESS_LIFETIME` (default `15m`).
- Refresh token lifetime: `REFRESH_TOKEN_LIFETIME`, env `DJANGO_JWT_REFRESH_LIFETIME` (default `7d`).
- Token carries custom claims: `user_id`, `email`, `is_superadmin`, and
  `hash_password` (`CHECK_REVOKE_TOKEN=True`): every token is bound to the
  user's password and is rejected with `401` once the password changes.

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

Which path may create the first superadmin is controlled by
`FIRST_SETUP_MODE`. See [first_setup_operations.md](first_setup_operations.md)
for the full operator runbook (why the gate exists and the `manage.py
create_superadmin` workflow).

| Env var | Default | Notes |
|---|---|---|
| `DJANGO_FIRST_SETUP_MODE` | `cli_only` | `cli_only` refuses `POST /api/auth/first-setup/` with `403 first_setup_disabled`; only `manage.py create_superadmin` can create the first superadmin. `open` allows the HTTP endpoint too. Local dev (`src/.env` from `python scripts/envtool.py --dev`) sets `open`. |
| `DJANGO_LOGIN_THROTTLE_RATE` | `5/min` | Rate for `POST /api/auth/login/` and `/api/auth/swagger-token/`, bucketed per `<ip>\|<email>`. |
| `DJANGO_LOGIN_IP_THROTTLE_RATE` | `20/min` | Second rate for the same two endpoints, bucketed per IP whatever the email. |
| `DJANGO_PASSWORD_RESET_CONFIRM_THROTTLE_RATE` | `10/hour` | Rate for `POST /api/auth/password-reset/confirm/`, bucketed per IP. |
| `DJANGO_TOKEN_REFRESH_THROTTLE_RATE` | `30/min` | Rate for `POST /api/auth/refresh/`, bucketed per IP. |

### GET `/api/auth/first-setup/`

- **Auth:** none.
- **Purpose:** frontend calls this on every app boot to decide whether to
  render the setup screen or the login screen.
- **Response 200:**
  ```json
  { "needs_setup": true, "setup_mode": "cli_only" }
  ```
- `needs_setup` is `true` only when no `User` row exists **and**
  `FIRST_SETUP_MODE` is `open`. Under `cli_only` it is always `false`, even
  before any user exists, so the frontend never offers a setup form it
  cannot submit. `setup_mode` echoes the current `FIRST_SETUP_MODE` value.

### POST `/api/auth/first-setup/`

- **Auth:** none, but refused unless `FIRST_SETUP_MODE=open` (see Errors).
- **Purpose:** bootstrap the very first Superadmin, their default
  Organization, and an `OrganizationUser` membership with the built-in
  Superadmin role. Also returns JWT tokens so the frontend can drop the user
  straight into the workspace without a second login call.
- **Request body:**
  ```json
  {
    "email": "admin@acme.com",
    "password": "StrongPass123!",
    "display_name": "Admin"
  }
  ```
  - `email` — must pass the **new-account email rule**, stricter than the RFC
    check that login and password reset use:
    - only letters, digits and `. _ - +` before the `@`, starting and ending
      with a letter or digit (`---@x.com`, `+john@x.com`, `o'brien@x.com`
      are rejected);
    - at most 64 characters before the `@` and 254 in total;
    - an ASCII domain whose last label is 2+ letters (no `localhost`, no
      non-ASCII domains).

    Accounts created before this rule keep working: only creation applies it.
  - `password` — must pass Django's `AUTH_PASSWORD_VALIDATORS` (min length,
    not-too-common, not-all-numeric, not-too-similar-to-email).
  - `display_name` — optional. Trimmed; must be a non-blank string of at
    most 255 characters. Omit it or send `null` to derive it from the email
    (`john.smith@acme.com` → `"John Smith"`).
  - Organization name is **not** taken from the request body; it comes from
    the `DEFAULT_ORGANIZATION_NAME` setting (env-driven, default
    `"Organization"`). An `organization_name` field passed in the body is
    silently ignored.
- **Response 201:**
  ```json
  {
    "user": {
      "id": 1,
      "email": "admin@acme.com",
      "display_name": "Admin",
      "is_superadmin": true
    },
    "organization": {
      "id": 1,
      "name": "Organization",
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
  - `403` — `code: first_setup_disabled` when `FIRST_SETUP_MODE` is not
    `open` (the default, `cli_only`). Use `manage.py create_superadmin`
    instead — see [first_setup_operations.md](first_setup_operations.md).
  - `409` — `{"detail": "Setup has already been completed"}` when any user
    already exists.

Setup runs inside `transaction.atomic()` — user + org + membership are created
atomically or not at all.

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
- `429` with `Retry-After` header once either bucket is exhausted: the
  composite `<ip>|<email>` bucket (`DJANGO_LOGIN_THROTTLE_RATE`, default
  `5/min`) or the per-IP bucket (`DJANGO_LOGIN_IP_THROTTLE_RATE`, default
  `20/min`).

### POST `/api/auth/refresh/`

Body: `{ "refresh": "<jwt>" }` → returns a new `{access, refresh}` pair.

- **Refresh-token rotation is on** (`ROTATE_REFRESH_TOKENS=True`,
  `BLACKLIST_AFTER_ROTATION=True`). Every successful refresh issues a **new**
  refresh token and blacklists the one you just sent.
- Replaying an old refresh returns `401`. If your storage was tampered with
  or the network duplicated the request, re-login.
- A refresh token minted under a previous password — or before password
  binding was enabled, so it has no `hash_password` claim — returns `401`
  `{"detail": "Token is invalid or expired."}` and clears the refresh
  cookie, the same as an expired token. The same happens when the token's
  user no longer exists. The client must send the user to login.

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
  (`ACCESS_TOKEN_LIFETIME`, env `DJANGO_JWT_ACCESS_LIFETIME`, default `15m`).
  Keep access TTL short.

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
  `rbac:sse_ticket:<sha256-of-token>` keys — only the digest is persisted,
  never the ticket itself. TTL is `SSE_TICKET_TTL`
  (hardcoded to 30 seconds in `django_app/settings/base.py`). Consume uses Redis `GETDEL` (6.2+) for
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
- Wait `ACCESS_TOKEN_LIFETIME` (env `DJANGO_JWT_ACCESS_LIFETIME`, default
  `15m`) and re-introspect the same token → 200 with `active: false` (expired).
- Introspect a token whose user was deactivated or deleted, or whose user's
  password changed since it was minted, or a refresh token → 200 with
  `active: false`. Introspection applies the same checks as Bearer
  authentication.

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
    "prefix":        "es-fnFo21JtA",
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

- **Auth:** `IsAuthenticated` + `DenyApiKeyAuth` + `IsSuperadmin` — JWT
  only. Any API key, including a superadmin-owned USER key and the SYSTEM
  key, gets `403 permission_denied`.
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
  { "email": "new@acme.com", "password": "AnotherPass123!", "display_name": "New Admin" }
  ```
  - `email` — same new-account email rule as first setup.
  - `display_name` — optional. Trimmed; must be a non-blank string of at
    most 255 characters. Omit it or send `null` to derive it from the email
    (`john.smith@acme.com` → `"John Smith"`).
- **Response 201:**
  ```json
  { "access": "<jwt-access>" }
  ```
- **Errors:** `400` on validation failures, `403` if the caller is not a
  superadmin.

### `python manage.py reset_user` (CLI / docker exec)

Same functional outcome as the web endpoint, intended for operators who lost
access to the UI. It runs the same validators before deleting anything, so an
invalid email or password fails the command and leaves every user in place.

Don't use Django's built-in `manage.py createsuperuser`: it skips these
validators and the default-organization membership. Use `create_superadmin`
or `reset_user` instead.

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

Full model, self-service + cross-org admin management (gated on the
`api_keys` resource), TTL/cap rules, revoke vs. delete, and error codes
are documented in [api_keys.md](api_keys.md).

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
| `/api/auth/reset-user/` response | `{access, refresh, api_key}` (the `api_key` field crashed with `NameError` before it could be returned) | `{access}` only |
| `/admin/` | Django admin UI | **Removed** |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `401 authentication_failed — "Invalid API key"` | Lookup is an exact match on `key_hash` (SHA-256 of the raw key) — any typo, a truncated paste, or a revoked key all miss. Raw keys are always `es-`-prefixed. | Re-copy the full raw key from where it was issued (it's shown once, at creation). If it was revoked, issue a new one via `POST /api/profile/api-keys/`. See [api_keys.md](api_keys.md). |
| `401 authentication_failed — "API key has expired"` | The key's `expires_at` is in the past. | Issue a new key; the expired one cannot be renewed. |
| `409 Setup has already been completed` | At least one User exists. | Expected. If intentional reset, use `POST /api/auth/reset-user/` or `manage.py reset_user`. |
| FE shows login form but `needs_setup` is `true` | Frontend isn't calling `GET /api/auth/first-setup/` on boot. | Wire the boot check per "Frontend changes required". |
| `/api/auth/login/` returns 401 on what looks like valid creds | Payload uses `username` instead of `email`. | Send `{"email": ..., "password": ...}`. |
| PowerShell's `curl -H` throws "Cannot bind parameter 'Headers'" | PowerShell aliases `curl` to `Invoke-WebRequest`. | Use `curl.exe`, `Invoke-RestMethod -Headers @{...}`, or `Remove-Item Alias:curl`. |
| `ALTER TABLE because it has pending trigger events` during migrate | Postgres deferred FK triggers. | Handled in 0170 with `SET CONSTRAINTS ALL IMMEDIATE`; if you see this on a different migration, add the same. |
| After swapping AUTH_USER_MODEL, `admin.LogEntry.user was declared with a lazy reference to 'tables.user'` | `django.contrib.admin` references the swapped model during state build. | Remove `django.contrib.admin` from `INSTALLED_APPS` |