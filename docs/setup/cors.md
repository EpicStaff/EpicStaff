# CORS setup (Django, realtime, webhook)

## What you need to do

Before you expose EpicStaff on a real domain, set `CORS_ALLOWED_ORIGINS` in
your `.env` to the origin(s) your users' browsers will
actually load the frontend from:

```
CORS_ALLOWED_ORIGINS=https://app.example.com
```

More than one trusted origin (comma-separated, no spaces):

```
CORS_ALLOWED_ORIGINS=https://app.example.com,https://admin.example.com
```

`src/.env.example` ships this pre-filled with the local-dev value
(`http://localhost:4200,http://localhost,https://localhost`) so
**actually replace the value** when you copy `.env.example` to a real `.env`.
If you don't, django_app/realtime/webhook won't crash (the value is present,
just wrong) — your real frontend domain will silently get CORS-rejected
instead. If you leave it out of `.env` entirely, `docker compose up` refuses
to start *anything* — see [If it won't start](#if-it-wont-start) below.

**Never set `CORS_ALLOWED_ORIGINS=*`.** For webhook/realtime (Starlette
`CORSMiddleware`) that's read as "trust every origin", and combined with
credentialed requests it reopens the exact vulnerability described below.

### Related: also set `FRONTEND_BASE_URL`

While you're editing `.env` for `CORS_ALLOWED_ORIGINS`, also make sure
`FRONTEND_BASE_URL` is set. It's unrelated to CORS but declared right next
to it in `.env.example`/`env.yaml`, and it's required for password-reset
emails. `docker-compose` also requires it.

## If it won't start

| You see | Cause | Fix |
| --- | --- | --- |
| `docker compose up` (or `config`) fails immediately, before any container starts, with `required variable CORS_ALLOWED_ORIGINS is missing a value: CORS_ALLOWED_ORIGINS must be set` | `.env` is missing `CORS_ALLOWED_ORIGINS` (blank or absent). All three services declare it as required in `src/docker-compose.yaml` (`${CORS_ALLOWED_ORIGINS:?CORS_ALLOWED_ORIGINS must be set}`), so compose won't bring up *any* service — not just the ones that need it — until it's set. Most likely an existing deployment upgrading past this change, whose `.env` predates the variable. | Add `CORS_ALLOWED_ORIGINS` to `.env` with your trusted origin(s), then rerun. |
| Same, but `FRONTEND_BASE_URL must be set` | `.env` is missing `FRONTEND_BASE_URL`. Only `django_app` requires it, same `${VAR:?...}` mechanism. | Add `FRONTEND_BASE_URL` to `.env`, then rerun. |
| No crash anywhere, but the frontend gets CORS-rejected in the browser console | Either `CORS_ALLOWED_ORIGINS` is set but doesn't include the origin the browser is actually loading the frontend from, or django_app/realtime/webhook are running **outside docker-compose** (bare `manage.py`, bare `uvicorn`, etc.) with the var unset — the `:?` requirement is enforced by docker-compose/the shell, not by Python, so nothing catches a blank value at that point; you just silently get an empty allow-list. | Check the exact origin (scheme + host + port) in your browser's address bar / devtools and add it to the list; if running outside compose, set `CORS_ALLOWED_ORIGINS` yourself before starting the process. |

## Why this exists

Django (`django-cors-headers`) and Starlette's `CORSMiddleware` (realtime,
webhook) don't send a literal `*` when `allow_credentials`/
`CORS_ALLOW_CREDENTIALS` is enabled — they **reflect the request's `Origin`
header back**. Combined with a wildcard origin config, that let any website a
logged-in user visited make authenticated cross-origin requests using that
user's session and read the response. Security review finding #44 flagged
this on all three services; all three are now fixed by trusting only an
explicit allow-list instead.

---

## For maintainers

### How it's read

`CORS_ALLOWED_ORIGINS` is a single comma-separated env var, read
independently by all three services. **None of the three validates it in
Python anymore** — enforcement lives entirely in `src/docker-compose.yaml`,
via the shell/compose required-variable syntax `${VAR:?error message}`:
if the variable is unset or blank when compose interpolates the file, it
fails with that message before any container is created, for the whole
stack, not just the service that declared it. `FRONTEND_BASE_URL` gets the
same treatment, but only in `django_app`'s block (its only consumer).

| Service | Python-level check | Enforced by | `allow_credentials` | Consumed in |
| --- | --- | --- | --- | --- |
| Django (`django_app`) | None | `docker-compose`: `${CORS_ALLOWED_ORIGINS:?...}` | `True` | `src/django_app/django_app/settings.py` |
| realtime | None | `docker-compose`: `${CORS_ALLOWED_ORIGINS:?...}` | `True` | `src/realtime/core/config.py`, consumed in `src/realtime/api/main.py` |
| webhook | None | `docker-compose`: `${CORS_ALLOWED_ORIGINS:?...}` | `False` | `src/webhook/app/core/settings.py`, consumed in `src/webhook/app/main.py` |

`realtime` and `webhook` also wait for `django_app` to report healthy before
starting (`depends_on: django_app: condition: service_healthy` in
`src/docker-compose.yaml`) — but that's regular startup ordering, not what
protects `CORS_ALLOWED_ORIGINS`: the `:?` check already blocks the whole
stack earlier if the variable is missing, before ordering even comes into
play. Webhook is the one service with `allow_credentials=False` — it has no
cookie-based auth (no session), so there's nothing credentialed CORS would
protect there.

### Running a service outside docker-compose

If you ever start `django_app`, `realtime`, or `webhook` directly — bare
`manage.py`, bare `uvicorn`, a debugger, a one-off script — the `${VAR:?...}`
check does not apply; it's evaluated by docker-compose/the shell, not by
Python. An unset `CORS_ALLOWED_ORIGINS` is simply read as blank, the service
starts with an empty allow-list, and every cross-origin request gets
silently rejected with no error printed anywhere.

**Recommendation:** export `CORS_ALLOWED_ORIGINS` (and `FRONTEND_BASE_URL`
for `django_app`) explicitly in that shell before starting the process, and
confirm with a real cross-origin request that CORS actually works — don't
rely on the process simply starting as proof it's configured.

`src/env.yaml` defines the only non-empty default
(`http://localhost:4200,http://localhost,https://localhost`), used purely to
generate `.dev.env`/`.debug.env`/`.env.example` for local development. A real
deployment's hand-created `.env` gets no default — set the variable
explicitly, or `docker compose up` refuses to start.

`CORS_ALLOWED_ORIGINS` and `FRONTEND_BASE_URL` are passed through explicitly
in the relevant services' `environment:` blocks in `src/docker-compose.yaml`
(neither is in the shared `x-common-env` anchor, since other services in the
compose file don't need them).

### Do not reintroduce the wildcard

If a future change needs to widen CORS, do not go back to
`CORS_ALLOW_ALL_ORIGINS = True` / `allow_origins=["*"]` in code — that's
exactly the reflected-origin behavior this fix closes. Add the new trusted
origin to `CORS_ALLOWED_ORIGINS` instead.
