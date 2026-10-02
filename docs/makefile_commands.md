# Makefile Commands Reference

All commands must be run from the **project root directory** (where `Makefile` lives).

The Makefile covers **local backend development only**: uv lockfiles and venvs,
Django management commands, and per-service test suites. Every target runs on the
host with the service's own venv interpreter (`src/<service>/.venv`) and the repo
root on `PYTHONPATH`, so it works regardless of which venv (if any) is active.

The Docker stack is **not** managed through make — run `docker compose` directly
from `src/` (see [Running the Docker stack](#running-the-docker-stack)).

---

## Table of Contents

- [Help](#help)
- [UV Dependency Management](#uv-dependency-management)
- [Local Django Development](#local-django-development)
- [Service Tests](#service-tests)
- [Running the Docker stack](#running-the-docker-stack)
- [User Management](#user-management)

---

## Help

### `make help`

Prints the quick-reference command list from `make_scripts/help.txt`. This is the
default goal, so plain `make` does the same.

```bash
make help
```

---

## UV Dependency Management

### `make uv-sync svc=<service>`

Create or refresh `src/<service>/.venv` from the service's `uv.lock`
(`uv sync --frozen --no-install-project --all-groups` — the same flags the Docker
builders use). `--frozen` makes a `uv.lock` that has drifted from `pyproject.toml`
fail instead of silently resolving to something the Docker build never saw.

Run this once per service before using its test target, and again after the lock
changes. The `svc` parameter is **required**.

| Parameter | Description |
|-----------|-------------|
| `svc` | Service directory under `src/`, e.g. `django_app`, `crew` |

```bash
make uv-sync svc=django_app
```

### `make uv-lock`

Regenerate `uv.lock` for **every** backend service that has a `src/*/pyproject.toml`.
Run after editing any service's dependencies. Does not upgrade pinned versions — it
only brings the lock back in line with `pyproject.toml`.

```bash
make uv-lock
```

### `make uv-lock-<service>`

Regenerate the lock for one service only.

```bash
make uv-lock-crew
```

---

## Local Django Development

Working directory: `src/django_app`

### `make django-makemigrations`

Run `manage.py makemigrations`. Pass extra arguments via `ARGS`.

| Parameter | Description |
|-----------|-------------|
| `ARGS` | Optional arguments forwarded to `makemigrations` |

```bash
# Create migrations for all apps
make django-makemigrations

# Create migrations for a specific app
make django-makemigrations ARGS=tables

# Create an empty migration
make django-makemigrations ARGS="tables --empty"
```

### `make django-migrate`

Run `manage.py migrate`. Pass extra arguments via `ARGS`.

| Parameter | Description |
|-----------|-------------|
| `ARGS` | Optional arguments forwarded to `migrate` |

```bash
# Apply all pending migrations
make django-migrate

# Migrate a specific app
make django-migrate ARGS=tables

# Roll back to a specific migration
make django-migrate ARGS="tables 0010"
```

### `make django-manage CMD=<command>`

Run any arbitrary Django management command via `CMD`.

| Parameter | Description |
|-----------|-------------|
| `CMD` | Full management command string (without `manage.py`) |

```bash
# Open the Django shell
make django-manage CMD=shell

# Create a superuser
make django-manage CMD=createsuperuser

# Collect static files
make django-manage CMD="collectstatic --noinput"
```

### `make django-tests ARGS=<pytest-args>`

Run the Django test suite with `pytest`. **Always** use this instead of running
`pytest` directly (bare `pytest` picks the wrong interpreter and fails on imports).

Requires Postgres to be running (start the stack with `docker compose`).

| Parameter | Description |
|-----------|-------------|
| `ARGS` | Optional pytest args — a test path, `-k <keyword>`, `-q`, `-x`, etc. |

```bash
# Full suite
make django-tests

# A single file
make django-tests ARGS="tests/api_tests/quickstart_test.py -v"

# Filter by keyword
make django-tests ARGS="-k surface"
```

---

## Service Tests

### `make <service>-tests ARGS=<pytest-args>`

Run a service's test suite with `pytest`. A target exists for every uv-managed
service under `src/` except `django_app` (which uses `django-tests`), so a new service
gets one automatically: `crew-tests`, `agent-tests`, `sandbox-tests`,
`knowledge_new-tests`, `realtime-tests`, `webhook-tests`, and so on. Same `ARGS`
convention as `make django-tests`. CI runs `crew-tests`, `agent-tests`, and
`sandbox-tests`.

```bash
make crew-tests
make agent-tests ARGS="-k my_test"
```

---

## Running the Docker stack

There is **one** compose file (`src/docker-compose.yaml`) and **one** env file
(`src/.env`). Run every command from `src/`:

```bash
cd src
docker compose -f docker-compose.yaml --env-file ./.env up -d            # start
docker compose -f docker-compose.yaml --env-file ./.env up -d --build crew  # rebuild one service
docker compose -f docker-compose.yaml --env-file ./.env logs -f django_app  # tail logs
docker compose -f docker-compose.yaml --env-file ./.env down             # stop
```

### External volumes and network

The compose file declares `sandbox_venvs`, `crew_pgdata`, `media_data`, and
`mcp-network` as `external: true`, so Compose will not create them. Create them once
per machine:

```bash
docker volume create sandbox_venvs
docker volume create crew_pgdata
docker volume create media_data
docker network create mcp-network
```

Because `crew_pgdata` is external, `docker compose down -v` does **not** delete the
database. Remove it explicitly with `docker volume rm crew_pgdata` (and recreate it)
if you want a fresh DB.

### `src/.env`

`src/.env` is gitignored, so a fresh clone has none. `src/env.yaml` is the single
source of truth for every variable, and `scripts/envtool.py` renders it into
`src/.env`:

```bash
python scripts/envtool.py --dev   # development defaults (the dev column of src/env.yaml)
python scripts/envtool.py         # production defaults
```

Without Python, copy the tracked template instead: `cp src/.env.example src/.env`.
`src/.env.example` is the **production** template: fill in the `CHANGE ME` lines
(secrets and passwords), and either set `NGINX_SSL_MODE=off` or provide certificates
(see [setup/ssl.md](setup/ssl.md)). A stack left running on the shipped
defaults for `POSTGRES_PASSWORD`, `STORAGE_SECRET_KEY`, or `REDIS_PASSWORD` is running
on credentials published in this repository.

For a public deployment, also change the host-facing values in `src/.env` by hand —
`DOMAIN_NAME`, `API_URL`, `REALTIME_API_URL`, `FRONTEND_BASE_URL`, `ALLOWED_HOSTS`,
`CORS_ALLOWED_ORIGINS` (see [setup/cors.md](setup/cors.md)), `NGINX_SSL_MODE` (see
[setup/ssl.md](setup/ssl.md)), `CREW_SAVEFILES_PATH`, and `EMAIL_HOST` / `EMAIL_PORT`
(see [rbac/password_recovery.md](rbac/password_recovery.md)). Note that the default
`EMAIL_HOST=mailpit` is a development mail catcher with a web UI on port 8025 — left
as shipped, a public deployment sends its password-reset tokens there instead of to
users. Optional voice/tunnelling values (`NGROK_AUTHTOKEN`, `NGROK_DOMAIN`,
`TWILIO_*`, `VOICE_AGENT_ID`, `VOICE_STREAM_URL`) only matter if you use those
features.

---

## User Management

### Reset user (console)

Deletes **all** existing users and API keys, then creates a fresh superuser and a new
`realtime-default` API key. Use this when you are locked out or need to start fresh
without wiping the entire database.

#### Inside Docker

```bash
docker exec -it django_app python manage.py reset_user --username admin --password secret
docker exec -it django_app python manage.py reset_user --username admin --password secret --email admin@example.com
```

#### Locally (outside Docker)

```bash
make django-manage CMD="reset_user --username admin --password secret"
```

The command prints the new API key to stdout — copy it immediately.

> **Warning:** This irreversibly deletes all users and API keys. All active JWT
> tokens and API keys will stop working.

### Reset user (REST API)

`POST /api/auth/reset-user/` — same effect, but requires a valid JWT or API key in
the `Authorization` header.

```bash
curl -X POST http://localhost:8000/api/auth/reset-user/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "secret"}'
```
