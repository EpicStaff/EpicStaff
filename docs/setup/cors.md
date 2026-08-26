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
(`http://localhost:4200,http://localhost,https://localhost`) and a
`CHANGE ME` marker — the marker is just a comment, nothing enforces it, so
**actually replace the value** when you copy `.env.example` to a real `.env`.
If you don't, django_app/realtime/webhook won't crash (the value is present,
just wrong) — your real frontend domain will silently get CORS-rejected
instead.

**Never set `CORS_ALLOWED_ORIGINS=*`.** For webhook/realtime (Starlette
`CORSMiddleware`) that's read as "trust every origin", and combined with
credentialed requests it reopens the exact vulnerability described below.

### Related: also set `FRONTEND_BASE_URL`

While you're editing `.env` for `CORS_ALLOWED_ORIGINS`, also make sure
`FRONTEND_BASE_URL` is set. It's unrelated to CORS but declared right next
to it in `.env.example`/`env.yaml`, and it's required for password-reset
emails. If it's left unset, Django currently crashes with a raw
`AttributeError: 'NoneType' object has no attribute 'rstrip'` instead of a
clean error message — a pre-existing gap outside this CORS fix, flagged here
only so you don't hit it while you're already editing this file.

## If it won't start

| You see | Cause | Fix |
| --- | --- | --- |
| Django: `ImproperlyConfigured: CORS_ALLOWED_ORIGINS is not set` | `.env` is missing `CORS_ALLOWED_ORIGINS` (blank or absent). Most likely an existing deployment upgrading past this change — its `.env` predates the variable. | Add `CORS_ALLOWED_ORIGINS` to `.env` with your trusted origin(s), then restart. |
| `realtime`/`webhook` never start (stuck waiting, or restart-looping) | They only start once `django_app` is healthy (`depends_on: django_app: condition: service_healthy` in `src/docker-compose.yaml`) — if Django crashed on the missing var above, these two never get a chance to. | Fix `django_app` first (see row above); `realtime`/`webhook` come up once it's healthy. |
| No crash anywhere, but the frontend gets CORS-rejected in the browser console | `CORS_ALLOWED_ORIGINS` is set but doesn't include the origin the browser is actually loading the frontend from (e.g. still the `CHANGE ME` local-dev placeholder), or `realtime`/`webhook` are running outside docker-compose (bypassing the `django_app` health gate) without `CORS_ALLOWED_ORIGINS` set at all — they don't validate it themselves, see below. | Check the exact origin (scheme + host + port) in your browser's address bar / devtools and add it to the list. |

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
independently by all three services. Only Django enforces it at the Python
level — `realtime`/`webhook` deliberately don't duplicate that check:

| Service | Requires `CORS_ALLOWED_ORIGINS` in Python | `allow_credentials` | Consumed in |
| --- | --- | --- | --- |
| Django (`django_app`) | Yes — raises `ImproperlyConfigured` if blank | `True` | `src/django_app/django_app/settings.py` |
| realtime | No — plain `Settings.CORS_ALLOWED_ORIGINS: str = ""`, no validator | `True` | `src/realtime/core/config.py`, consumed in `src/realtime/api/main.py` |
| webhook | No — same, no validator | `False` | `src/webhook/app/core/settings.py`, consumed in `src/webhook/app/main.py` |

- Django: `src/django_app/django_app/settings.py` — checked inline (same
  `ImproperlyConfigured`-on-blank pattern as `_require_env`/`SECRET_KEY`,
  just not routed through that exact function since it's secret-specific).
- realtime/webhook: no validation at all. This is intentional, not an
  oversight — both have `depends_on: django_app: condition: service_healthy`
  in `src/docker-compose.yaml`, so in the normal docker-compose path they
  never even start unless Django already came up healthy, which means Django
  already confirmed `CORS_ALLOWED_ORIGINS` is set. Duplicating the check in
  three places was judged not worth the extra code. The gap this leaves:
  running `realtime`/`webhook` directly, outside docker-compose (bypassing
  the `depends_on` gate), with `CORS_ALLOWED_ORIGINS` unset gives an empty
  `cors_allowed_origins_list` — CORS silently rejects every origin, no error.
  Unlike Django, webhook also sets `allow_credentials=False` — it has no
  cookie-based auth at all (no session, nothing to protect with credentialed
  CORS), so allowing credentials would have protected nothing while widening
  the attack surface for no benefit.

`docker-compose` itself never supplies a fallback either — every service's
`environment:` block passes `CORS_ALLOWED_ORIGINS: ${CORS_ALLOWED_ORIGINS:-}`
(blank if the shell/`.env` doesn't have it). The only place a real default
lives is `src/env.yaml` (`http://localhost:4200,http://localhost,
https://localhost`, used to generate `.dev.env`/`.debug.env`/`.env.example`)
— for `realtime`/`webhook` that default reaches them purely through the
generated `.env` file docker-compose reads from, not through any code.

`CORS_ALLOWED_ORIGINS` is passed through explicitly in each of the
`django_app`, `realtime`, and `webhook` services' `environment:` blocks in
`src/docker-compose.yaml` (it is not in the shared `x-common-env` anchor,
since other services in the compose file don't need it).

### Do not reintroduce the wildcard

If a future change needs to widen CORS, do not go back to
`CORS_ALLOW_ALL_ORIGINS = True` / `allow_origins=["*"]` in code — that's
exactly the reflected-origin behavior this fix closes. Add the new trusted
origin to `CORS_ALLOWED_ORIGINS` instead.
