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
             ├── PasswordResetDispatcher        (runs the request's account work on a background pool)
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
  and only used when the relay requires AUTH), the request does a fixed
  amount of work for every email: it queues a job on
  `PasswordResetDispatcher` and returns. It does not look the account up,
  so neither the body nor the response time depends on whether the email
  is registered. See [Asynchronous delivery](#asynchronous-delivery).
* The job (`PasswordRecoveryService.deliver_reset`) runs on a worker
  thread. If the email resolves to a user (case-insensitively), every
  prior grant for that user is deleted and a new `PasswordResetToken` is
  created, in a single transaction. Only the most recent link works. After
  the commit the reset email is sent through `django.core.mail`. If the
  email does not resolve to a user, the job does nothing.
* `PasswordResetEmailSender` checks `SmtpConfigService` as well and drops
  the message without rendering it when SMTP is not configured, so no
  other caller can route a reset link to the console backend either.

Throttling: two throttles apply, and a request must pass both. A
throttled request gets `429` before the view runs, so no job is queued.

* `PasswordResetRequestThrottle`, bucket `ip|email`, rate
  `DJANGO_PASSWORD_RESET_REQUEST_THROTTLE_RATE` (default `5/hour`). Keeps one
  mailbox from being flooded with reset emails.
* `PasswordResetRequestIpThrottle`, bucket **IP only**, rate
  `DJANGO_PASSWORD_RESET_REQUEST_IP_THROTTLE_RATE` (default `20/hour`). An IP
  rotating emails gets a fresh `ip|email` bucket for every email, so
  without this cap one client could queue jobs faster than the two workers
  clear them, keep the backlog full and get every legitimate reset dropped.
  20 leaves room for several people behind one NAT, who need one or two
  requests each. The `429` depends only on the caller's IP, so it reveals
  nothing about accounts.

#### Asynchronous delivery

A request that did the account lookup, the token write and the SMTP round
trip itself took measurably longer for a registered email than for an
unknown one: 71 ms against 35 ms median, with no overlap, measured against a
local mailpit relay under `runserver`. A remote relay with TLS would widen
the gap further (an estimate; not measured). The `ip|email` throttle does
not help, because each guessed email gets a bucket of its own. So all of
that work runs off the request thread, and the request's own work no longer
depends on the account (6-7 ms median for both, overlapping, after the
change, same setup). Background jobs still compete with later requests for the GIL and
the database, so a loaded server is not perfectly uniform, but that noise
is not tied to the email in the request.

* One module-level `default_dispatcher` per Django worker process owns a
  pool of **2 threads** (named `password-reset-*`) and the backlog bound
  together. `PasswordRecoveryService` uses it unless a dispatcher is
  injected. Each job runs on a database connection of its own: stale
  connections are closed when the job starts and the thread's connections
  are closed when it ends.
* At most **50 jobs** are in flight (running or queued) per process. The
  bound caps delivery latency, not memory: at about 300 ms per send on two
  threads, the last queued job waits about 7.5 s. A request that finds the
  backlog full is still answered `200`; its job is dropped, and
  `password_reset_job_dropped_backlog_full` is logged at most once a minute
  per process. The check is an in-process semaphore, so the request does no
  network I/O that depends on the state of the queue, and it never waits
  for a slot. A job the pool refuses (it is shutting down) is dropped the
  same way and logged as `password_reset_job_not_queued`.
* `EMAIL_TIMEOUT` is **10 s** (a constant in `settings/email.py`, not an
  env var). Django's default is no timeout, which would let a relay that
  accepts the connection and never answers hang both threads for good and
  stop every reset email until the process restarts.
* Delivery is **best-effort**. On a graceful worker exit, including
  `--max-requests` recycling, the queued jobs run before the process ends.
  Only a SIGKILL, or a drain that outlasts gunicorn's graceful timeout,
  loses them. A lost or dropped job sends nothing; the user sees the same
  "if the email is registered" message either way and simply asks again.
* Two jobs for the same email (two quick requests) run one after the
  other: the job locks the account row (`SELECT ... FOR UPDATE`) for the
  transaction that replaces the grant, so the second deletes the first
  one's grant and only the newest link works.
* A job that raises is swallowed and logged as
  `password_reset_job_failed`, with the exception type and the line it
  was raised at only. An SMTP failure inside the sender (a timeout
  included) is logged the same way as `password_reset_email_send_failed`,
  with the user id. Neither log carries the exception message or a
  traceback with variable values: both can contain the email address or
  the raw token.
* Running I/O on threads departs from the backend convention on purpose:
  the view is synchronous Django, there is no task queue in the project,
  and the pool is tiny and bounded. It is an in-process pool, not a
  durable queue.
* **Residual risk: a distributed flood.** The per-IP cap stops one client
  from filling the backlog, not many. Enough IPs, each under its cap, can
  still keep the backlog full, and legitimate resets are then silently
  delayed or dropped behind the usual "link has been sent" answer.
  Operators see it as `password_reset_job_dropped_backlog_full` in the log
  (at most once a minute per process). The structural fix is a durable
  task queue with its own capacity, which the project does not have yet.

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
| `DJANGO_PASSWORD_RESET_TOKEN_TTL` | `15m` | Token lifetime. |
| `DJANGO_PASSWORD_RESET_REQUEST_THROTTLE_RATE` | `5/hour` | Throttle on the request endpoint, bucketed per `ip\|email`. |
| `DJANGO_PASSWORD_RESET_REQUEST_IP_THROTTLE_RATE` | `20/hour` | Second throttle on the request endpoint, bucketed per **IP only**, whatever the email. |
| `DJANGO_PASSWORD_RESET_CONFIRM_THROTTLE_RATE` | `10/hour` | Throttle on the confirm endpoint, bucketed per **IP only** — see Security invariants. |
| `DJANGO_EMAIL_HOST` | `none` (dev: `mailpit`) | SMTP host (Django's `EMAIL_HOST`). Blank or `none` → console backend, and self-service password reset is disabled (use `manage.py reset_password`). |
| `DJANGO_EMAIL_PORT` | `1025` | SMTP port. |
| `DJANGO_EMAIL_USER` | `none` | SMTP user (Django's `EMAIL_HOST_USER`). Leave blank for relays that do not require AUTH (mailpit, local Postfix). |
| `DJANGO_EMAIL_PASSWORD` | `none` | SMTP password (Django's `EMAIL_HOST_PASSWORD`). Leave blank for relays that do not require AUTH. |
| `DJANGO_EMAIL_USE_TLS` | `true` | |
| `DJANGO_EMAIL_USE_SSL` | `false` | |
| `EMAIL_TIMEOUT` | `10` | Seconds to wait on the SMTP relay. A settings constant, not an env var. |
| `DJANGO_DEFAULT_FROM_EMAIL` | `no-reply@epicstaff.local` | `From:` header on reset emails. |
| `DJANGO_FRONTEND_BASE_URL` | none in prod, required (dev: `http://localhost:4200`) | Base of the reset link. |
| `DJANGO_FRONTEND_PASSWORD_RESET_PATH` | `/reset-password` | Path segment; token appended as `?token=<opaque string>`. |

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

* **No enumeration.** Request endpoint always returns 200. With SMTP
  configured the request's own work does not depend on the account — it
  queues a job and returns — so its timing does not reveal a registered
  email either (background jobs add only load-dependent noise).
  Confirm endpoint uses a single opaque 400 for unknown / used / expired.
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
* **Both endpoints throttled.** Request: `5/hour` per `ip|email` and
  `20/hour` per IP alone, the second so that rotating emails cannot fill
  the job backlog from one client.
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
* **Fail-silent email.** The email is sent after the response, on a
  worker thread, so SMTP errors cannot reach the client. They are logged
  by exception type and location only, never with the message or the
  variable values, which would carry the email address and the link.
* **No reset link without SMTP.** With SMTP off the request endpoint
  issues no token and the sender refuses to send, so a live link never
  reaches the console backend and, through it, the application log.

## Out of scope (future stories)

* HTML email templates.
* Per-organization admin reset (only global `is_superadmin` today).
* Audit log entries — no audit surface exists yet.
