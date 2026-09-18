# Makefile Commands Reference

All commands must be run from the **project root directory** (where `Makefile` lives).

Every service target runs a single Docker Compose stack:

```
docker compose -f docker-compose.yaml --env-file ./.env ...
```

invoked from `src/`. There is **one** compose file (`src/docker-compose.yaml`) and
**one** env file (`src/.env`). The previous split into dev/prod stacks
(the old per-environment compose overlays) and per-environment env
files (the old per-environment `dev`/`debug` dotenv overlays) is gone.

---

## Table of Contents

- [Help](#help)
- [Environment](#environment)
- [Branch Switching](#branch-switching)
- [Utilities](#utilities)
- [Local Django Development](#local-django-development)
- [Local Crew/Agent Development](#local-crewagent-development)
- [User Management](#user-management)
- [Typical Workflows](#typical-workflows)

---

## Help

### `make help`

Prints the quick-reference command list from `make_scripts/help.txt`.

```bash
make help
```

---

## Environment

One unified set of targets manages the single Docker Compose stack. There are no
longer separate `dev-*` / `prod-*` families — use these for every environment.

### `src/.env`

Every target that starts containers depends on an `ensure-env` step. On first run,
if `src/.env` is missing, `ensure-env` creates it by copying the tracked template:

```bash
cp src/.env.example src/.env
```

`src/.env` is gitignored, so a fresh clone has none — the operator fills in real
values by hand. The targets that run `ensure-env` are `up`, `build`, `rebuild`,
and `rebuild-s`.

`src/.env.example` is a ready-to-go local setup: everything not marked `CHANGE ME`
already holds a working value serving `localhost` over plain HTTP. Fill in the
`CHANGE ME` lines (secrets and passwords) and the stack runs. A stack left running
on the shipped defaults for `POSTGRES_PASSWORD`, `STORAGE_SECRET_KEY`, or
`REDIS_PASSWORD` is running on credentials published in this repository.

For a public deployment, also change the host-facing values in `src/.env` by hand —
`DOMAIN_NAME`, `API_URL`, `REALTIME_API_URL`, `FRONTEND_BASE_URL`, `ALLOWED_HOSTS`,
`CORS_ALLOWED_ORIGINS` (see [setup/cors.md](setup/cors.md)), `SSL_ENABLE`,
`CREW_SAVEFILES_PATH`, and `EMAIL_HOST` / `EMAIL_PORT` (see
[rbac/password_recovery.md](rbac/password_recovery.md)). Note that the default
`EMAIL_HOST=mailpit` is a development mail catcher with a web UI on port 8025 — left
as shipped, a public deployment sends its password-reset tokens there instead of to
users. Optional voice/tunnelling values (`NGROK_AUTHTOKEN`, `NGROK_DOMAIN`,
`TWILIO_*`, `VOICE_AGENT_ID`, `VOICE_STREAM_URL`) only matter if you use those
features.

> **Generating `src/.env` from source.** `src/env.yaml` is the single source of truth for
> every variable. `scripts/envtool.py` renders it into `src/.env`: run
> `python scripts/envtool.py` for production defaults or `python scripts/envtool.py --dev`
> for development defaults (the dev column of `src/env.yaml`). `ensure-env` is the
> no-Python fallback — it copies `src/.env.example` to `src/.env` when the file is missing.

### `make up`

Start all services in detached mode. Runs `init` and `ensure-env` first, then
`docker compose up -d`.

```bash
make up
```

### `make down`

Stop all services (`docker compose down`).

```bash
make down
```

### `make build`

Build images without starting containers. Runs `init` and `ensure-env` first.

```bash
make build
```

### `make rebuild`

Rebuild **all** services from scratch (`--no-cache`) and start them. Use this when
dependencies or Dockerfiles have changed.

```bash
make rebuild
```

### `make rebuild-s s=<service>`

Rebuild and restart a **single** service (uses Docker layer cache). Runs
`docker compose up --build -d <service>`.

| Parameter | Description |
|-----------|-------------|
| `s` | Name of the Docker Compose service to rebuild |

```bash
make rebuild-s s=crew
```

### `make restart s=<service>`

Restart a single service (`docker compose restart <service>`).

| Parameter | Description |
|-----------|-------------|
| `s` | Name of the Docker Compose service to restart |

```bash
make restart s=manager
```

### `make logs`

Tail logs for **all** services (`docker compose logs -f`).

```bash
make logs
```

### `make logs-s s=<service>`

Tail logs for a single service.

| Parameter | Description |
|-----------|-------------|
| `s` | Name of the Docker Compose service |

```bash
make logs-s s=django_app
```

### `make init`

Create the external Docker volumes and network the stack needs, idempotently
(`|| true` on each). Creates volumes `sandbox_venvs`, `crew_pgdata`, `media_data`,
`graph_data`, and network `mcp-network`.

`up`, `build`, and `rebuild` all run `init` as a prerequisite, so
you rarely need to call it directly.

```bash
make init
```

---

## Branch Switching

These commands preserve the Docker image cache and database volumes across branch
switches, enabling fast rebuilds.

### `make switch b=<branch>`

Full one-command branch switch. Runs all steps in order:
1. Tags current Docker images with the current branch name
2. Backs up the current DB volume to a `.tar` file
3. Runs `git checkout <branch>`
4. Loads cached Docker images for the new branch (if any)
5. Restores DB volume for the new branch (if a backup exists)

After this, run `make up` — the build will use the cache.

| Parameter | Description |
|-----------|-------------|
| `b` | Target branch name |

```bash
make switch b=feature/EST-1234
```

### `make stash-tags`

Tags each local Docker image with the **current branch name**.

Example: `crew` → `crew:feature-EST-1234`

Run this **before** switching branches manually (`git checkout`). Safe to run
multiple times.

```bash
make stash-tags
```

### `make apply-tags`

Loads cached images for the **current branch** and retags them back to their default
names so Docker can use them as a build cache.

Example: `crew:feature-EST-1234` → `crew`

Run this **after** switching branches manually (`git checkout`). If no cached images
exist for this branch, the build starts fresh.

```bash
make apply-tags
```

### `make backup`

Saves the current DB volume to `make_scripts/backups/<current-branch>.tar`. Run this
before switching branches to preserve test data.

```bash
make backup
```

### `make apply-backup`

Restores the DB volume from `make_scripts/backups/<current-branch>.tar`. If no backup
file exists for the current branch, nothing is restored.

```bash
make apply-backup
```

---

## Utilities

### `make clean`

Stop all services and **delete all volumes** (`docker compose down -v
--remove-orphans`). Removes orphaned containers too.

> **Warning:** This wipes all database data. Use with care.

```bash
make clean
```

### `make docker-generate-certs domain=<domain>`

Generate a self-signed SSL certificate for local Nginx. Outputs `privkey.pem` and
`fullchain.pem` to `src/nginx/certs/`. The `domain` parameter is **required** — the
target exits with an error if it is missing.

| Parameter | Description |
|-----------|-------------|
| `domain` | Common name for the certificate, e.g. `example.com` |

```bash
make docker-generate-certs domain=example.com
```

---

## Local Django Development

These commands run Django management commands **directly on the host** (outside
Docker), using each service's own venv interpreter (`src/django_app/venv`).
`PYTHONPATH` is automatically set to the project root, so they work regardless of
which venv is currently active.

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

Run the Django test suite with `pytest`, using the django service venv
(`src/django_app/venv`) and repo-root `PYTHONPATH` automatically — so it works
regardless of which venv is active. **Always** use this instead of running `pytest`
directly (bare `pytest` picks the wrong interpreter and fails on imports).

Requires Postgres to be running (start the stack with `make up`).

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

## Local Crew/Agent Development

Like the Django test target, these run on the host using each service's own venv and
repo-root `PYTHONPATH`.

### `make crew-tests ARGS=<pytest-args>`

Run the crew service test suite with `pytest`, using the crew venv (`src/crew/venv`).
Same `ARGS` convention as `make django-tests`.

```bash
make crew-tests
make crew-tests ARGS="-k my_test"
```

### `make agent-tests ARGS=<pytest-args>`

Run the agent service test suite with `pytest`, using the agent venv
(`src/agent/venv`). Same `ARGS` convention.

```bash
make agent-tests
make agent-tests ARGS="-k my_test"
```

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

---

## Typical Workflows

### First-time setup (fresh clone)

```bash
# Create external volumes/network, create src/.env from the template, start services
make up
```

`make up` copies `src/.env.example` to `src/.env` on first run. Edit `src/.env` to
fill in the `CHANGE ME` values, then re-run `make up` (or `make down && make up`).

Open http://localhost.

### Start the environment

```bash
make up
```

### Switch to another branch (one command)

```bash
make switch b=feature/EST-1234
make up
```

### Switch branches manually (step by step)

```bash
make stash-tags
make backup
git checkout feature/EST-1234
make apply-tags
make apply-backup
make up
```

### Rebuild a single service without rebuilding everything

```bash
make rebuild-s s=crew
```

### Rebuild everything from scratch

```bash
make rebuild
```

### Run Django database migrations locally

```bash
make django-makemigrations
make django-migrate
```

### Reset the environment and start fresh

```bash
make clean
make up
```

### Reset user (locked out or fresh credentials needed)

```bash
docker exec -it django_app python manage.py reset_user --username admin --password secret
```
