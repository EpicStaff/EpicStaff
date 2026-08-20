# Signing keys

`django_app` signs tokens and sessions with two environment variables:

| Variable | Used for | Required |
| --- | --- | --- |
| `SECRET_KEY` | Django's signing key — sessions, password-reset tokens, CSRF | Yes |
| `JWT_SECRET` | Signing key for access and refresh tokens | Falls back to `SECRET_KEY` |

`SECRET_KEY` has no default. It is read through `_require_env` in
`django_app/settings.py`, which raises `ImproperlyConfigured` naming the variable
when it is missing or blank, and `src/docker-compose.yaml` enforces the same
requirement one layer earlier with `${SECRET_KEY:?…}` — so a blank value fails
before a container is created.

`JWT_SECRET` is optional in code: when unset it reuses `SECRET_KEY`, which is also
`djangorestframework-simplejwt`'s own default. Set it explicitly if you want tokens
signed with a key distinct from Django's.

Two caveats worth knowing:

- `src/docker-compose.yaml` currently still requires `JWT_SECRET` via `${JWT_SECRET:?…}`,
  so deployments started through that file must set it even though the code would
  otherwise fall back.
- The code fallback fires only when `JWT_SECRET` is **unset**, not when it is set to an
  empty string. Outside compose — running Django directly, or with an env file
  containing a bare `JWT_SECRET=` — an empty value is used as-is. Leave the variable
  out entirely rather than blank.

## Generating a key

```bash
openssl rand -base64 48 | tr -d '=+/'
```

Any random string of 50+ characters works. Avoid `$` (Docker Compose treats it as
interpolation) and `#` (env files treat it as a comment).

## Generate once, then keep it

**Do not rotate these values casually.** Changing `SECRET_KEY` invalidates every
existing session and every outstanding password-reset token, and it makes any data
encrypted with a key derived from it permanently unreadable. Changing `JWT_SECRET`
invalidates every issued access and refresh token.

Generate each value once when you first set up a deployment, store it with your other
deployment secrets, and reuse it. If you regenerate `src/.env` from
`src/.env.example`, carry the existing keys across rather than making new ones.

## Where each deployment path gets its keys

| Path | Source |
| --- | --- |
| `make dev`, `make dev-*` | `src/.dev.env`, generated from `src/env.yaml` (development placeholder values) |
| `make prod-*` | `src/.env`, supplied by the operator |
| Manual `docker compose up` in `src/` | `src/.env`, created by copying `src/.env.example` — see the Quick Start in the README |

`src/.env` is gitignored. Keep it out of version control and out of image builds.

Note that `src/.env` is read for *interpolation*, and `src/docker-compose.yaml`
declares no `env_file:` entries, so the keys are injected into `django_app` only —
no other service receives them.
