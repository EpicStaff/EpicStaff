# Password Recovery

Three endpoints plus a CLI fallback, all sharing a single orchestrator
(`PasswordRecoveryService`) that composes small single-purpose
collaborators. Views are thin — they call the validator for shape
checks, hand the cleaned payload to the service, and wrap the return in
a DRF `Response`. All business rules and security invariants live in
the service layer.

> **Authenticated self-service password change** lives at
> `/api/profile/password-change/{request,confirm}/` and is owned by
> `UserProfileService`. See [user_profile.md](user_profile.md) §
> "Two-step password change".

## Layering

```
View  ──▶  AuthValidationService.validate_*()  (shape + strength)
  │
  └────▶  PasswordRecoveryService               (orchestrator)
             │
             ├── SmtpConfigService              (is SMTP configured?)
             ├── PasswordResetTokenRepository   (generate/hash, lookup, delete)
             ├── PasswordResetEmailSender       (render + send, fail-silent, never without SMTP)
             ├── PasswordWriter                 (validate against the account, set_password + save)
             └── CredentialRevocationService    (blacklist refresh tokens, revoke API keys)
```

Every collaborator is injected via the orchestrator's constructor so
tests can swap in fakes without monkey-patching.

## Endpoints

### `POST /api/auth/password-reset/request/` — anonymous

Body: `{ "email": "<email>" }`.

Always returns **200**. The body depends only on whether SMTP is
configured, never on whether the email exists. With SMTP:

```json
{ "detail": "If the email is registered, a reset link has been sent.", "smtp_configured": true }
```

Without SMTP (the text matches the frontend's "Reset unavailable" page):

```json
{ "detail": "Password reset by email isn't available on this server. Ask your administrator to reset your password.", "smtp_configured": false }
```

Behavior:

* If SMTP is **not** configured (`SmtpConfigService.is_configured()` is
  false, i.e. `DJANGO_EMAIL_HOST` is blank or `none` — the shipped prod
  default), **self-service reset is disabled**. The request is ignored
  before the account is looked up: no token is created, pending tokens
  are left alone, nothing is sent, and the response carries
  `smtp_configured: false` for every email. One warning,
  `password_reset_request_ignored_smtp_not_configured`, tells operators to
  use [`manage.py reset_password`](#cli-fallback); it names no email and is
  logged at most once per 5 minutes across all workers, so anonymous
  traffic cannot flood the log. Without SMTP Django's backend is the
  console one, which would print the reset link into the application
  log — anyone with log access could take over the account.
* If SMTP is configured (`EMAIL_HOST` set — credentials are optional
  and only used when the relay requires AUTH) and the email resolves to
  a user, inside a single transaction every prior grant for that user is
  deleted and a new `PasswordResetToken` is created. Only the most recent
  link works. The reset email is then dispatched through
  `django.core.mail`. Delivery is fail-silent — a send error never changes
  the HTTP response.
* If SMTP is configured and the email does not resolve to a user, no
  token is created and no email is sent, but the response body is
  identical.
* `PasswordResetEmailSender` checks `SmtpConfigService` as well and drops
  the message without rendering it when SMTP is not configured, so no
  other caller can route a reset link to the console backend either.

Throttling: `PasswordResetRequestThrottle`, bucket `ip|email`, rate
`PASSWORD_RESET_REQUEST_THROTTLE_RATE` (default `5/hour`).

### `POST /api/auth/password-reset/confirm/` — anonymous

Body: `{ "token": "<opaque string>", "new_password": "<pw>" }`.

* The token is the URL-safe value from the emailed link. It is opaque —
  there is no format to validate, so a malformed value and an unknown
  one are indistinguishable and produce the same generic error. Only a
  blank/missing `token` is reported as a field error.
* Looks the token up **by hash**; if it is unknown, already used, or past
  `PASSWORD_RESET_TOKEN_TTL` (default **900 s / 15 min**), returns a
  single generic **400**
  (`Reset token is invalid, expired, or already used.`) — the response
  body does not distinguish the three cases.
* Runs the same `AUTH_PASSWORD_VALIDATORS` as first-setup. Weak
  passwords return 400 with per-field errors in the standard
  `FormValidationError` shape. The account is known only once the token
  is looked up, so the not-too-similar-to-email check runs at that point
  (in `PasswordWriter`), with the same 400 on `new_password`. A rejected
  password leaves the token unspent, so the same link can be retried.
* On success: password is written, token is marked used, and **every
  personal API key of that user is revoked** — all in one transaction.
  Every access and refresh token issued before the change stops working
  at once, because tokens are bound to the password (see Security
  invariants).

### Self-service password change — moved

The single-step `POST /api/auth/password-change/` endpoint was replaced
by a two-step flow under `/api/profile/`. See
[user_profile.md](user_profile.md) for details:

* `POST /api/profile/password-change/request/` — verify current
  password, receive a single-use ticket.
* `POST /api/profile/password-change/confirm/` — consume ticket, set
  new password, receive a fresh JWT pair.

### `POST /api/auth/admin/password-reset/` — superadmin only

Body: `{ "user_id": <int>, "new_password": "<pw>" }`.

* JWT only: any API key (including the SYSTEM key) gets 403
  (`DenyApiKeyAuth`).
* Gate: `actor.is_superadmin` — non-superadmins get 403
  (`superadmin_required`). The gate lives in the service so the CLI
  and the HTTP surface share one authorization path.
* Target user not found → 404.
* Weak password → 400 (same validators as everywhere else).
* On success: writes the new password, invalidates any pending reset
  tokens for the target, blacklists all of the target's refresh
  tokens and revokes all of the target's personal API keys, in one
  transaction. Returns **204**. No password is echoed — the admin supplied
  it.

## CLI fallback

This is the recovery path when SMTP is not configured — the anonymous
request endpoint is disabled then (see above). Run it inside the
`django_app` container, e.g.
`docker compose exec django_app python manage.py reset_password <email> --generate`.

```
python manage.py reset_password <email> [--generate | --password <pw>]
```

* No flag → prompts twice with `getpass` and confirms.
* `--password <pw>` → non-interactive (use with care; logs in shell
  history).
* `--generate` → generates a strong random password via
  `secrets.token_urlsafe(16)` and prints it once to stdout.
* The new password is validated against the same
  `AUTH_PASSWORD_VALIDATORS` as every other password-setting entry point
  (min length, not-too-common, not-all-numeric, not-too-similar-to-email).
* Does **not** verify the account's current password or any token — shell
  access to run `manage.py` is the authorization for this command.
* Goes through `PasswordRecoveryService.cli_reset`, so the same
  post-conditions apply: password written, reset tokens invalidated,
  refresh tokens blacklisted, personal API keys revoked.

Unknown email → non-zero exit with `CommandError`.

## Configuration

All env vars land in `src/.env` and are forwarded through
`src/docker-compose.yaml` to the `django_app` container.

| Variable | Default | Meaning |
|---|---|---|
| `PASSWORD_RESET_TOKEN_TTL` | `900` | Token lifetime, seconds. |
| `PASSWORD_RESET_REQUEST_THROTTLE_RATE` | `5/hour` | Throttle on the request endpoint, bucketed per `ip\|email`. |
| `PASSWORD_RESET_CONFIRM_THROTTLE_RATE` | `10/hour` | Throttle on the confirm endpoint, bucketed per **IP only** — see Security invariants. |
| `EMAIL_HOST` | *(empty)* | SMTP host. Empty → console backend, and self-service password reset is disabled (use `manage.py reset_password`). |
| `EMAIL_PORT` | `587` | SMTP port. |
| `EMAIL_HOST_USER` | *(empty)* | SMTP user. Leave blank for relays that do not require AUTH (mailpit, local Postfix). |
| `EMAIL_HOST_PASSWORD` | *(empty)* | SMTP password. Leave blank for relays that do not require AUTH. |
| `EMAIL_USE_TLS` | `True` | |
| `EMAIL_USE_SSL` | `False` | |
| `DEFAULT_FROM_EMAIL` | `no-reply@epicstaff.local` | `From:` header on reset emails. |
| `FRONTEND_BASE_URL` | `http://localhost:4200` | Base of the reset link. |
| `FRONTEND_PASSWORD_RESET_PATH` | `/reset-password` | Path segment; token appended as `?token=<opaque string>`. |

`EMAIL_BACKEND` is resolved at import time: SMTP when `EMAIL_HOST` is
set, else console. Whether Django authenticates against that host is
independent and keyed on `EMAIL_HOST_USER` + `EMAIL_HOST_PASSWORD` —
both blank = no AUTH attempted (required for mailpit and other
unauthenticated relays; setting creds against a server that does not
implement SMTP AUTH raises `SMTPNotSupportedError`).
`SmtpConfigService.is_configured()` is the source of truth for "should
we tell the user an email is coming?" and "may a reset link be sent at
all?" — inspect it, not `EMAIL_BACKEND`. The console backend writes every
message to the application log, so no reset token is issued or sent
without SMTP; operators use `manage.py reset_password` instead.

## Security invariants

* **No enumeration.** Request endpoint always returns 200. Confirm
  endpoint uses a single opaque 400 for unknown / used / expired.
* **Single-use tokens.** Consuming a reset **deletes** the row. Single-use
  therefore holds because the grant is gone, not because a flag says so —
  a replayed token is the same lookup miss as an unknown one, and gets the
  same generic answer. Nothing accumulates: the table holds only live
  grants.
* **Stored hashed, never in plaintext.** The token is
  `secrets.token_urlsafe(32)`, and only its SHA-256 hash is persisted
  (`rbac_password_reset_token.token_hash`). The raw value exists once, in
  the emailed link. A read of the table — from a leaked backup, a
  replica, or a query log — yields verifiers, not usable tokens, so it
  cannot be replayed against the confirm endpoint. The model's `__str__`
  omits the hash as well, to keep it out of logs.
  Plain SHA-256 with no salt or pepper is deliberate: the input is 32
  bytes of `secrets` entropy, so there is nothing to brute-force and
  nothing to precompute, and staying independent of `SECRET_KEY` means
  rotating that key does not invalidate in-flight links.
* **Only the latest link works.** Prior grants for a user are deleted every
  time a new reset is requested.
* **Time-bound.** `PASSWORD_RESET_TOKEN_TTL` (default 15 min).
* **Both endpoints throttled.** Request: `5/hour` per `ip|email`.
  Confirm: `10/hour` per **IP alone** — the only caller-supplied value on
  that request is the token itself, and keying on it would give an
  attacker a fresh bucket per guess.
* **Credential kill on every password change.** Reset, admin reset, CLI
  reset (all here) and self-service change (via `UserProfileService`)
  all go through `CredentialRevocationService`, which blacklists every
  live refresh token for the user **and** revokes every personal (`USER`)
  API key that exists at the moment the password is set — including
  non-expiring ones. The `SYSTEM` key is never touched. The revocation
  runs inside the same transaction as the password write: either both
  commit or neither does.
* **Every JWT is bound to the password.** With `CHECK_REVOKE_TOKEN`
  enabled, each access and refresh token carries a `hash_password` claim
  (an MD5 of the stored password hash). Bearer authentication,
  `POST /api/auth/refresh/` and `POST /api/auth/introspect/` reject a
  token whose claim does not match the user's current password, so every
  token minted before a password set dies the moment the password
  changes — including refresh tokens rotated since login, which have no
  blacklist row. No access-token window remains in which a stolen session
  could mint a new API key. The self-service change returns a fresh pair
  minted under the new password, so only the caller's own session
  continues. Blacklisting stays as defence in depth.
  **Deploy note:** tokens issued before this binding was enabled carry
  no claim and are rejected, so every user is forced to log in once
  after the upgrade.
  **Any rewrite of the stored password hash ends the user's sessions**,
  not only a password change. In particular, after a Django upgrade that
  changes the preferred hasher or its iteration count, the first
  successful `check_password` (a login, or step 1 of the self-service
  change) re-hashes the password. That invalidates every token minted
  under the old hash — including the bearer token of the very caller who
  just ran step 1 of the self-service change, whose step 2 then returns
  `401` and who has to log in again.
* **Open connections are not closed.** WebSocket and SSE connections
  already open when the password changes stay open: the graph-collab
  WebSocket and SSE streams authenticate once with a single-use ticket,
  and the realtime service calls `POST /api/auth/introspect/` only at
  connect time. Only new connections are refused.
* **Strength enforced uniformly.** Every entry point runs Django's
  `AUTH_PASSWORD_VALIDATORS`, via the same
  `AuthValidationService._validate_password_field`. Request validators
  run before the account is resolved, so they cannot compare the password
  with the account's email; `PasswordWriter.set` repeats the check
  against the real account before writing, for reset confirm, admin
  reset, CLI reset and self-service change alike. A rejection there
  raises before anything is written: the password, reset tokens and
  credentials are left as they were.
* **Alphabet restricted.** Passwords must consist only of printable
  ASCII excluding whitespace (bytes 0x21–0x7E): Latin letters, digits,
  and standard symbols `!"#$%&'()*+,-./:;<=>?@[\]^_` `` ` `` `{|}~`.
  Enforced uniformly by `PrintableAsciiPasswordValidator` plugged into
  `AUTH_PASSWORD_VALIDATORS`. Email fields likewise reject any
  whitespace character.
* **Admin gate enforced at TWO layers.** `IsSuperadmin` permission class on
  `AdminPasswordResetView` rejects non-superadmin callers with the
  project-standard 403 envelope (`code: permission_denied`) before the
  service is reached. The in-service `actor.is_superadmin` check inside
  `PasswordRecoveryService.admin_reset` stays as defense-in-depth — it
  would only fire on a programming error or a future non-HTTP caller
  forgetting to gate. Either gate alone would be sufficient; both
  together are deliberate.
* **Fail-silent email.** SMTP errors are logged, never surfaced, so the
  HTTP response stays uniform (no side-channel).
* **No reset link without SMTP.** With SMTP off the request endpoint
  issues no token and the sender refuses to send, so a live link never
  reaches the console backend and, through it, the application log.

## Out of scope (future stories)

* HTML email templates.
* Per-organization admin reset (only global `is_superadmin` today).
* Audit log entries — no audit surface exists yet.
