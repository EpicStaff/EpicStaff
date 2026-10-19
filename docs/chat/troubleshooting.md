# Chat service troubleshooting

Logs, from `src/`: `docker compose logs chat` for the chat service, and `logs epicstaff-nginx` /
`logs django_app` for the rest of the stack. Settings are described in
[configuration.md](configuration.md).

## The service refuses to start

- **`required variable X is missing a value`** from compose: `X` is missing or empty in
  `src/.env`. Copy it from `src/.env.example` or regenerate the file with `scripts/envtool.py`;
  use `none` where a value is optional. Compose checks the chat variables even when the `chat`
  profile is off.
- **The container exits with `EnvironmentNotFoundError`** (a variable is missing) or
  **`EnvironmentBlankError`** (`CHAT_DB_PASSWORD` or `DJANGO_API_KEY` is empty or `none`).
- **The container exits with a pydantic `ValidationError`** naming the variable. The checks in
  `src/chat/settings.py`:
  - `CHAT_DJANGO_URL`: must be `http(s)://host[:port]` with no path, query or fragment and a
    valid port. Plain http is allowed only for a single-label host (`django_app`, `localhost`)
    or a private or loopback IP.
  - `CHAT_TRUSTED_PROXIES`: comma-separated CIDRs or bare addresses.
  - Durations: whole seconds where required, greater than 0 (`CHAT_RECONCILE_INTERVAL` may be 0).
    Rates must be `<count>/<unit>`.
  - `CHAT_UNCONFIRMED_START_RELEASE` must be longer than `CHAT_DJANGO_TIMEOUT`.
  - Token budgets: 1 to 2147483647, and each `…_DEFAULT` no larger than its `…_MAX`.
  - Conversation lifecycle durations (`CHAT_RESPONSE_TIME_*`, `CHAT_CLOSE_AFTER_*`): whole
    seconds from 60 to 2147483647, and each `…_DEFAULT` no larger than its `…_MAX`.
- **Migration failure in the log**: `alembic upgrade head` runs before uvicorn. Check that
  `CHAT_DB_*` match the `chatdb` container and that `chatdb` is healthy.
- **`Can't locate revision identified by '0002'`** (or `'0003'`, `'0004'`), or **`column … does
  not exist`** right after an upgrade: the database was created by an earlier development build.
  Its migrations were folded into a single `0001` twice, the second time for the conversation
  lifecycle (closed conversations, desk styles and inactivity rules), so a database at `0001`
  or `0002` from before either fold is stamped current but has an older schema. No production
  database used those schemas, so nothing in them is worth keeping: empty the database and
  restart `chat`, which creates the schema again.

  ```bash
  docker compose exec chatdb sh -c 'dropdb -U "$POSTGRES_USER" --force "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
  docker compose restart chat
  ```

## 502 on `/chat/…`

EpicStaff's nginx cannot reach `CHAT_UPSTREAM_URL`. Its log names the cause.

- **The `chat` container is not running.** Most often `COMPOSE_PROFILES` in `src/.env` lacks
  `chat` while `CHAT_ENABLED=true`. nginx resolves `chat` at request time through Docker's DNS,
  so it starts fine but answers 502. Add `chat` to `COMPOSE_PROFILES` and run
  `docker compose up -d` again.
- **`CHAT_UPSTREAM_URL` points at a chat service outside this compose project**:
  - The upstream name does not resolve from the nginx container: nginx uses Docker's resolver
    `127.0.0.11`, which forwards to the host's DNS.
  - The port is not reachable.
  - "upstream SSL certificate verify error": the upstream's certificate does not chain to a
    public CA, or the chain is incomplete.

## Operator API (EpicStaff UI chat pages) errors

| Status / code | Cause |
|---|---|
| 401 `invalid_token` | Django's `/api/auth/introspect/` says the JWT is not active (expired or revoked). Sign in again. |
| 400 | No numeric `X-Organization-Id` header. |
| 404 on every call | The user is not a member of that organization (introspection `org_ids`), or `/api/permissions/me/` answered 403/404. Cross-org access is reported as 404 on purpose. |
| 403 `forbidden`, "chats:… is required" | The user's role lacks that `chats` action, or `/api/permissions/me/` answered 401. Role changes take up to `CHAT_IDENTITY_CACHE_TTL` to apply. The `chats` resource exists in EpicStaff only with `CHAT_ENABLED=true`. |
| 503 `upstream_unavailable` | Django was unreachable, timed out (`CHAT_DJANGO_TIMEOUT`), or answered an unexpected status. A wrong `DJANGO_API_KEY` shows up here, because introspection is a system-key call. The chat log names the path and status. |

## Replies never arrive

1. **The run never started.** The visitor sees "The flow could not be started." and the chat log
   shows `run-session failed for conversation … HTTP 400: …`. If the body says
   "Host is not an allowed callback target", add the host of `CHAT_CALLBACK_URL` to EpicStaff's
   `DJANGO_SESSION_CALLBACK_ALLOWED_HOSTS` (host only, no port) and restart `django_app`.
2. **The callback is not delivered.** Ask Django for the session:
   ```bash
   curl -H "X-Api-Key: $DJANGO_API_KEY" -H "X-Organization-Id: <org id>" <EpicStaff origin>/api/sessions/<session id>/
   ```
   `callback_status` is one of:
   - `delivered`: the callback arrived; look further in the chat log.
   - `pending`: Django is still retrying.
   - `failed`: Django gave up.

   For `pending` or `failed`, check that `CHAT_CALLBACK_URL` is reachable from the
   `django_app` container: DNS, firewall, a trusted certificate, and no redirect.
3. **The callback is rejected with 401 `invalid_signature`.** The signed timestamp differs from
   the chat host's clock by more than `CHAT_CALLBACK_MAX_SKEW`. Sync both hosts with NTP.

A lost callback is not fatal. After `CHAT_STALE_RUN_AFTER` the reconcile loop asks Django for
the run's status and applies the result. Replies that keep arriving about that much late mean
callbacks are failing.

## Every visitor is rate-limited together

All visitors get 429 `rate_limited` at once: the service sees one client IP for everyone.

- **The peer is not in `CHAT_TRUSTED_PROXIES`**, so the peer address is used.
- **A TLS terminator in front of EpicStaff appends to `X-Forwarded-For`**, so the last entry is EpicStaff's nginx. Forward
  the header unchanged (`proxy_set_header X-Forwarded-For $http_x_forwarded_for;`).

## Conversations return to the bot or close on their own

That is a desk's inactivity rules (Settings → Inactivity in the EpicStaff UI), applied by the
reconcile loop:

- A visitor who waited for a person longer than the desk's response time goes back to the bot,
  which posts the desk's notice (none when the notice is empty), if the desk is set to hand back.
- A Support desk closes a conversation silent for its close-after time (reason `inactive`).
  Ongoing desks never close on their own.

Neither touches test conversations, and the close never touches a conversation without
messages or one whose bot is still answering. With `CHAT_RECONCILE_INTERVAL=0` nothing applies
the rules. A message to a closed conversation answers 409 `conversation_closed`; the widget then
starts a new conversation.

A change to a desk's style or rules applies to all of its conversations on the next passes, not
only to new ones:

- Switching a desk to Support, or shortening its close-after time, closes every conversation
  already silent for longer than that, at up to 500 per pass.
- Switching it to hand back, or shortening its response time, hands back every visitor already
  waiting for longer, however long ago they wrote, each with the notice.
