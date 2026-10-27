# Chat service configuration

`src/env.yaml` is the source of truth: each variable's full description sits there, and
`scripts/envtool.py` renders it into `src/.env`. This table mirrors it in one line per variable.
When you change one, change the other.

- **Compose**: `src/docker-compose.yaml` references every variable as `${VAR:?}`, so a missing or
  empty value stops `docker compose`, even with the `chat` profile off. Use `none` where a value
  is optional.
- **No code defaults**: `src/chat/settings.py` reads every variable through the shared
  `src.shared.envtools.Env`; a missing one stops startup with `EnvironmentNotFoundError`, and
  `CHAT_DB_PASSWORD` or `DJANGO_API_KEY` empty or `none` with `EnvironmentBlankError`.
- **Default**: the `src/env.yaml` default; "dev only" means production has none and must set it.

The service runs only when `COMPOSE_PROFILES` includes `chat`; set `CHAT_ENABLED=true` too, so
nginx routes `/chat/` and the UI shows the chat pages.

Duration values: seconds, or `<n>s|m|h|d`. Rate values: `<count>/<s|m|h|d>`.

## Service

| Variable | Default | Meaning |
|---|---|---|
| `CHAT_PORT` | `8200` | Port the service listens on in the container. |
| `CHAT_LOG_LEVEL` | `INFO` | Minimum loguru level written to stderr. |
| `CHAT_WORKERS` | `1` | Uvicorn workers; each holds up to 15 DB connections and runs its own reconcile loop (the inactivity rules lock each conversation with SKIP LOCKED, so two workers never act on one twice). |

## Database and Redis

| Variable | Default | Meaning |
|---|---|---|
| `CHAT_DB_HOST` | `chatdb` | Host of the chat Postgres. |
| `CHAT_DB_PORT` | `5432` | Its port. |
| `CHAT_DB_NAME` | `chat` | Database name. Tests use `<name>_test`. |
| `CHAT_DB_USER` | `chat` | Owner, created by the postgres image on first start. |
| `CHAT_DB_PASSWORD` | `chat` (dev only) | Password of `CHAT_DB_USER`. |
| `CHAT_REDIS_DB` | `2` | Redis logical DB for SSE fan-out, rate counters and stream tickets. |
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_USER`, `REDIS_PASSWORD` | shared | The stack's Redis connection, the same variables every service reads. |

## EpicStaff connection

| Variable | Default | Meaning |
|---|---|---|
| `CHAT_DJANGO_URL` | `http://django_app:8000` | Where Django is reached: `scheme://host[:port]`, no path. http only for a single-label host or a private or loopback IP. |
| `CHAT_DJANGO_HOST_HEADER` | `localhost` | Host header override for Django's `ALLOWED_HOSTS`; `none` sends the URL's host. |
| `DJANGO_API_KEY` | shared | EpicStaff's system API key, the same variable Django seeds it from; empty or `none` is refused. |
| `CHAT_DJANGO_TIMEOUT` | `10s` | Overall limit for one Django call (fractional allowed). |
| `CHAT_PUBLIC_BASE_URL` | `http://localhost` (dev only) | Public origin printed in the widget embed snippet, no trailing slash. |
| `CHAT_WIDGET_URL` | `https://epicstaffchat.pages.dev/embed.js` | Script the embed snippet loads: the EpicChat widget on its CDN (the latest release). Pin a version, e.g. `https://v3-0-0.epicstaffchat.pages.dev/embed.js`, to upgrade the widget only on purpose. An absolute https URL (http only for an internal host), no quotes, angle brackets or whitespace. |
| `CHAT_CALLBACK_URL` | `http://chat:8200/chat/internal/v1/session-callbacks` | Where Django posts run results (`/<run id>` appended); its host must be in `DJANGO_SESSION_CALLBACK_ALLOWED_HOSTS`. |
| `CHAT_TRUSTED_PROXIES` | RFC 1918 ranges | CIDRs whose `X-Forwarded-For` is trusted (last entry is used). |

## Limits, runs and streams

| Variable | Default | Meaning |
|---|---|---|
| `CHAT_IP_MESSAGE_RATE` | `30/m` | Widget messages per client IP (IPv6 per /64), fixed UTC-aligned window. |
| `CHAT_IP_CONVERSATION_RATE` | `20/h` | New widget conversations per client IP, same windowing. |
| `CHAT_RECONCILE_INTERVAL` | `1m` | Pause between reconcile passes, which also apply the desks' inactivity rules; `0` turns the loop off, and the rules with it. |
| `CHAT_STALE_RUN_AFTER` | `5m` | A run still in progress this long is checked against Django (lost callback). |
| `CHAT_UNCONFIRMED_START_RELEASE` | `1m` | A start Django never confirmed is released after this; must exceed `CHAT_DJANGO_TIMEOUT`. |
| `CHAT_RUN_TIMEOUT` | `30m` | A run still running after this is stopped. |
| `CHAT_EVENT_RETENTION` | `7d` | Conversation events older than this are pruned. |
| `CHAT_CALLBACK_MAX_SKEW` | `5m` | Largest accepted clock difference on a signed callback. |
| `CHAT_IDENTITY_CACHE_TTL` | `1m` | Operator identity cache; a revoked membership works until it expires. |
| `CHAT_VISITOR_TOKEN_IDLE_TTL` | `30d` | An unused visitor token expires after this. |
| `CHAT_TICKET_TTL` | `1m` | Validity of a single-use stream ticket. |
| `CHAT_STREAM_MAX_LIFETIME` | `30m` | An SSE stream is closed after this; the client reconnects. |
| `CHAT_STREAM_PING_INTERVAL` | `15s` | SSE keep-alive; keep it below any proxy idle timeout. |

Whole seconds and greater than 0 unless the description in `src/env.yaml` says fractional or
allows 0.

## Token budgets

| Variable | Default | Meaning |
|---|---|---|
| `CHAT_CONVERSATION_TOKEN_BUDGET_DEFAULT` | `200000` | Per-conversation daily budget for a binding created without one; at most the max. |
| `CHAT_CONVERSATION_TOKEN_BUDGET_MAX` | `1000000` | Largest per-conversation budget a binding may set (≤ 2147483647). |
| `CHAT_DAILY_TOKEN_BUDGET_DEFAULT` | `1000000` | Binding-wide daily budget for a binding created without one; at most the max. |
| `CHAT_DAILY_TOKEN_BUDGET_MAX` | `50000000` | Largest binding-wide daily budget (≤ 2147483647). |

## Conversation lifecycle

Each desk's inactivity rules: a response time, after which an unanswered visitor is handed back
to the bot, marked overdue or kept waiting (the desk's choice), and, on Support desks, a
close-after time of silence that closes the conversation. The reconcile loop applies them, so
they act up to `CHAT_RECONCILE_INTERVAL` late.

| Variable | Default | Meaning |
|---|---|---|
| `CHAT_RESPONSE_TIME_DEFAULT` | `10m` | Response time of a desk created without one; at least `1m`, at most the max. |
| `CHAT_RESPONSE_TIME_MAX` | `1d` | Longest response time a desk may set (≤ 2147483647 s). |
| `CHAT_CLOSE_AFTER_DEFAULT` | `24h` | Close-after time of a desk created without one; at least `1m`, at most the max. |
| `CHAT_CLOSE_AFTER_MAX` | `30d` | Longest close-after time a desk may set (≤ 2147483647 s). |

Whole seconds. Lowering a max does not change desks already above it.

## Widget messages

What a visitor message may carry beyond its desk's own limits; the same on every desk. The
widget reads them from the conversation state (`action_max_bytes`, `extra_data_max_bytes`).
Plain byte counts, no units.

| Variable | Default | Meaning |
|---|---|---|
| `CHAT_ACTION_MAX_BYTES` | `262144` | Largest `action` (e.g. an edited table sent back), as compact UTF-8 JSON; larger is 400 `validation_error`. A message is a JSON body held to 1 MiB, text included: keep this well below that. |
| `CHAT_EXTRA_DATA_MAX_BYTES` | `8192` | Largest `chat_extra_data`, as compact UTF-8 JSON; larger is 400 `validation_error`. |

## Set by compose, not by `.env`

| Variable | Meaning |
|---|---|
| `RUN_IN_DOCKER` | `1` in compose. When it is unset, `src/chat/settings.py` reads `src/.env`. |

## EpicStaff settings for the chat feature

`COMPOSE_PROFILES` (add `chat`), `CHAT_ENABLED`, `CHAT_UPSTREAM_URL`, `CHAT_API_URL` and
`DJANGO_SESSION_CALLBACK_ALLOWED_HOSTS`. `CHAT_UPSTREAM_URL` defaults to the `chat` container;
point it at another URL only to use a chat service run outside this compose project.
