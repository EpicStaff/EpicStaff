# Signing keys

`django_app` requires two environment variables and will not start without them:

| Variable | Used for |
| --- | --- |
| `SECRET_KEY` | Django's signing key — sessions, password-reset tokens, CSRF |
| `JWT_SECRET` | Signing key for access and refresh tokens |

There is no built-in default for either. Both are read through `_require_env` in
`django_app/settings.py`, which raises `ImproperlyConfigured` naming the missing
variable, and `src/docker-compose.yaml` enforces the same requirement one layer
earlier with `${SECRET_KEY:?…}` — so a missing or blank value fails before a
container is created.

`JWT_SECRET` does not fall back to `SECRET_KEY`. Set both.

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
