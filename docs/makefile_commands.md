# Makefile Commands Reference

All commands must be run from the **project root directory** (where `Makefile` lives).

---

## Table of Contents

- [Help](#help)
- [Development Environment](#development-environment)
- [Production Environment](#production-environment)
- [Branch Switching](#branch-switching)
- [Env File Generation](#env-file-generation)
- [Utilities](#utilities)
- [Local Django Development](#local-django-development)
- [Local Crew Development](#local-crew-development)
- [Typical Workflows](#typical-workflows)

---

## Help

### `make help`

Prints the quick-reference command list from `make_scripts/help.txt`.

```bash
make help
```

---

## Development Environment

Uses `docker-compose.yaml` + `docker-compose.dev.yaml` with env file `.dev.env`.

> **Note:** `src/.dev.env` is generated from `src/env.yaml` and is gitignored. On a fresh clone, run `make gen-env` once before `make dev` to create it.

### `make dev-init`

Create all external Docker volumes and the `mcp-network` required by the dev stack. Idempotent — safe to run when volumes already exist.

Creates: `sandbox_venvs`, `crew_pgdata`, `media_data`, `graph_data`, `mcp-network`.

`make dev`, `make rebuild-dev`, `make dev-voice`, and `make dev-ngrok` all run `dev-init` automatically as a prerequisite, so you rarely need to call this directly.

```bash
make dev-init
```

### `make dev`

Start all development services in detached mode (live-reload, mapped ports).

```bash
make dev
```

### `make dev-down`

Stop all development services.

```bash
make dev-down
```

### `make dev-build`

Build dev images without starting containers.

```bash
make dev-build
```

### `make dev-logs`

Tail logs for **all** dev services.

```bash
make dev-logs
```

### `make dev-restart s=<service>`

Restart a single dev service.

| Parameter | Description |
|-----------|-------------|
| `s` | Name of the Docker Compose service to restart |

```bash
make dev-restart s=redis
```

### `make dev-logs-s s=<service>`

Tail logs for a single dev service.

| Parameter | Description |
|-----------|-------------|
| `s` | Name of the Docker Compose service |

```bash
make dev-logs-s s=django_app
```

### `make dev-rebuild-s s=<service>`

Rebuild and restart a **single** dev service (uses Docker layer cache).

| Parameter | Description |
|-----------|-------------|
| `s` | Name of the Docker Compose service to rebuild |

```bash
make dev-rebuild-s s=crew
```

### `make rebuild-dev`

Rebuild **all** dev services from scratch (`--no-cache`) and start them. Use this when dependencies or Dockerfiles have changed.

```bash
make rebuild-dev
```

---

## Production Environment

Uses `docker-compose.yaml` + `docker-compose.override.yaml` with a single env
file, `src/.env`. There is no separate production env file — `src/.env` is the
whole environment, edited by hand on the deployment host. It is gitignored and
never committed.

### Setting up `src/.env`

Copy the template and fill it in:

```bash
cp src/.env.example src/.env
```

`src/.env.example` is generated from `src/env.yaml` and is a **ready-to-go local
setup**: everything not marked `CHANGE ME` already holds a working value serving
`localhost` over plain HTTP. Fill in the ten `CHANGE ME` lines and the stack
runs.

The README quick-start generates only `SECRET_KEY` and `JWT_SECRET` (with
`openssl`) and rewrites `CREW_SAVEFILES_PATH`. The remaining `CHANGE ME` lines
are yours to fill.

> **Blank does not always fail loudly.** Only `SECRET_KEY`, `JWT_SECRET`,
> `FRONTEND_BASE_URL` and `CORS_ALLOWED_ORIGINS` are declared `${VAR:?...}` in
> `src/docker-compose.yaml`, so compose refuses to start when they are empty.
> The rest degrade quietly if you skip them:
>
> | Left blank | What actually happens |
> |---|---|
> | `POSTGRES_PASSWORD` | compose substitutes `postgres` (`docker-compose.yaml:35`) |
> | `STORAGE_SECRET_KEY` | compose substitutes `minioadmin_secret` (`:51`), paired with the shipped `STORAGE_ACCESS_KEY=minioadmin` |
> | `REDIS_PASSWORD` | `--requirepass` is never passed (`:207-210`) — Redis accepts unauthenticated connections |
> | `DB_*_PASSWORD` (×4) | passed through empty; fails at connection time, not at startup |
>
> So fill in all ten `CHANGE ME` lines. A stack running on the first three of
> those is running on credentials published in this repository.

### What to change for a public deployment

Once `src/.env` works locally, these are the values a real deployment has to
change by hand.

| Variable | Local default | Set it to |
|---|---|---|
| `DOMAIN_NAME` | `localhost` | your domain, e.g. `epicstaff.example.com` |
| `API_URL` | `http://localhost/api/` | `https://<your-domain>/api/` |
| `REALTIME_API_URL` | `http://localhost/realtime/` | `https://<your-domain>/realtime/` |
| `FRONTEND_BASE_URL` | `http://localhost:4200` | `https://<your-domain>` — password-reset emails link here |
| `ALLOWED_HOSTS` | `0.0.0.0,127.0.0.1,localhost,django_app` | add your domain |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:4200,...` | your real origin(s) — see [setup/cors.md](setup/cors.md) |
| `SSL_ENABLE` | `#` (off) | empty string turns SSL **on** in nginx |
| `CREW_SAVEFILES_PATH` | `/c/savefiles` | a real path on the host (that default is a Docker Desktop path, not a Linux one) |
| `EMAIL_HOST` / `EMAIL_PORT` | `mailpit` / `1025` | your real SMTP server — see [rbac/password_recovery.md](rbac/password_recovery.md) |

The `EMAIL_HOST` default deserves a second look: `mailpit` is a development mail
catcher declared in `src/docker-compose.yaml` with **no profile**, publishing a
web UI on port 8025. Left as shipped, a public deployment sends its
password-reset tokens into that UI instead of to users.

`DEBUG` and `LOAD_DEBUG_ENV` are already `False` in `src/.env.example` — those
are only turned on in the generated dev files, so there is nothing to change.

Optional, only if you use those features: `NGROK_AUTHTOKEN` / `NGROK_DOMAIN` for
tunnelling, and `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `VOICE_AGENT_ID` /
`VOICE_STREAM_URL` for voice calls.

### Upgrading from `prod/prod.env`

Earlier versions layered a second env file, `prod/prod.env`, over `src/.env`,
filled in by a `make prod-setup` command. Both are gone: `prod/prod.env` is no
longer read, even if the file is still sitting on the host.

If you are upgrading such a host, before the next `make prod`:

1. Copy every value from `prod/prod.env` into `src/.env`.
2. Pay particular attention to the passwords — if `prod/prod.env` set a database
   password that `src/.env` does not, the services will fail to authenticate
   against a data volume that was initialised with the old value.
3. Run `make prod-build` and check the config resolves before `make prod-up`.
4. Delete `prod/` once you have confirmed the deployment is healthy.

### `make prod` / `make start-prod`

Build and start all production services in detached mode. Both commands are equivalent.

```bash
make prod
# or
make start-prod
```

### `make prod-down`

Stop all production services.

```bash
make prod-down
```

### `make prod-logs`

Tail logs for all production services.

```bash
make prod-logs
```

---

## Branch Switching

These commands help preserve Docker image cache and database volumes when switching branches, enabling fast rebuilds.

### `make switch b=<branch>`

Full one-command branch switch. Runs all steps in order:
1. Tags current Docker images with the current branch name
2. Backs up the current DB volume to a `.tar` file
3. Runs `git checkout <branch>`
4. Loads cached Docker images for the new branch (if any)
5. Restores DB volume for the new branch (if a backup exists)

After this, run `make dev` or `make prod` — the build will use the cache.

| Parameter | Description |
|-----------|-------------|
| `b` | Target branch name |

```bash
make switch b=feature/EST-1234
```

### `make stash-tags`

Tags each local Docker image with the **current branch name**.

Example: `crew` → `crew:feature-EST-1234`

Run this **before** switching branches manually (`git checkout`). Safe to run multiple times.

```bash
make stash-tags
```

### `make apply-tags`

Loads cached images for the **current branch** and retags them back to their default names so Docker can use them as a build cache.

Example: `crew:feature-EST-1234` → `crew`

Run this **after** switching branches manually (`git checkout`). If no cached images exist for this branch, the build starts fresh.

```bash
make apply-tags
```

### `make backup`

Saves the current DB volume to `make_scripts/backups/<current-branch>.tar`. Run this before switching branches to preserve test data.

```bash
make backup
```

### `make apply-backup`

Restores the DB volume from `make_scripts/backups/<current-branch>.tar`. If no backup file exists for the current branch, nothing is restored.

```bash
make apply-backup
```

---

## Env File Generation

`src/env.yaml` is the single source of truth for all three env files. Edit it,
then regenerate. Never hand-edit the generated files — `--check` will catch drift.

| Generated file | Env id | Role |
|---|---|---|
| `src/.dev.env` | `dev` | development stack (`make dev`) |
| `src/.debug.env` | `debug` | services on the host, deps in Docker |
| `src/.env.example` | `example` | template the operator copies to `src/.env` for a real install |

There is no generated production file. Production runs on `src/.env`, which the
operator creates from `src/.env.example` and edits by hand — see
[Production Environment](#production-environment).

A variable with an `envs:` list appears only in those envs; a variable without
one appears in all of them. Secrets carry an `example:` block that blanks the
value and adds a `CHANGE ME` note, so the committed template never ships a
working credential:

```yaml
DB_CREW_PASSWORD:
  default: crew_password_v104
  example:
    value: ""
    comment: "CHANGE ME (postgres role password for crew service)"
```

### `make gen-env`

Regenerate `src/.dev.env`, `src/.debug.env`, and `src/.env.example` from `src/env.yaml`.

```bash
make gen-env
```

### `make check-env`

Compare the three env files on disk to what `src/env.yaml` would generate. Exits 1 with a
unified diff if any file has drifted; exits 0 if all files are clean. Use in CI or as a
pre-commit check. `make check-env` always checks all three files; to check a single file
use the CLI directly (`python scripts/generate_env.py --check --env debug`).

Note that `src/.dev.env` and `src/.debug.env` are gitignored, so on a fresh
clone `--check` reports them `MISSING` and exits 1 before any real drift is
involved. Only `src/.env.example` is committed.

```bash
make check-env
```

You can also target a single file:

```bash
python scripts/generate_env.py --env dev
python scripts/generate_env.py --env debug
python scripts/generate_env.py --env example
python scripts/generate_env.py --check --env debug
```

---

## Utilities

### `make clean`

Stop **all** environments (dev and prod) and **delete all volumes**. Removes orphaned containers too.

> **Warning:** This wipes all database data. Use with care.

```bash
make clean
```

### `make docker-generate-certs`

Generate self-signed SSL certificates for local Nginx. Outputs `privkey.pem` and `fullchain.pem` to `src/nginx/certs/`.

```bash
make docker-generate-certs
```

---

## Local Django Development

These commands run Django management commands **directly on the host** (outside Docker), using the local Python environment. `PYTHONPATH` is automatically set to the project root.

Working directory: `src/django_app`

### `make django-makemigrations`

Run `python manage.py makemigrations`. Pass extra arguments via `ARGS`.

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

Run `python manage.py migrate`. Pass extra arguments via `ARGS`.

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

### `make django-manage`

Run any arbitrary Django management command via `CMD`.

| Parameter | Description |
|-----------|-------------|
| `CMD` | Full management command string (without `python manage.py`) |

```bash
# Open the Django shell
make django-manage CMD=shell

# Create a superuser
make django-manage CMD=createsuperuser

# Show all available management commands
make django-manage CMD=help

# Collect static files
make django-manage CMD="collectstatic --noinput"
```

### `make django-tests`

Run the Django test suite with `pytest`. Uses the django service venv
(`src/django_app/venv`) and sets `PYTHONPATH` to the repo root automatically — so it
works regardless of which venv is active. **Always** use this instead of running
`pytest` directly (bare `pytest` picks the wrong interpreter and fails on imports).

Requires Postgres to be running (the dev stack DB — see `make dev`).

| Parameter | Description |
|-----------|-------------|
| `ARGS` | Optional pytest args — a test path, `-k <keyword>`, `-q`, `-x`, etc. |

```bash
# Full suite
make django-tests

# A single file
make django-tests ARGS="tests/model_tests/surface_test.py -q"

# Filter by keyword
make django-tests ARGS="-k surface"
```

---

## Local Crew Development

### `make crew-tests`

Run the crew service test suite with `pytest`, using the crew venv
(`src/crew/venv`) and repo-root `PYTHONPATH`. Same `ARGS` convention as
`make django-tests`.

```bash
make crew-tests
make crew-tests ARGS="-k my_test"
```

---

## User Management

### Reset user (console)

Deletes **all** existing users and API keys, then creates a fresh superuser and a new `realtime-default` API key. Use this when you are locked out or need to start fresh without wiping the entire database.

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

> **Warning:** This irreversibly deletes all users and API keys. All active JWT tokens and API keys will stop working.

### Reset user (REST API)

`POST /api/auth/reset-user/` — same effect, but requires a valid JWT or API key in the `Authorization` header.

```bash
curl -X POST http://localhost:8000/api/auth/reset-user/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "secret"}'
```

---

## Typical Workflows

### First-time dev setup (fresh clone)

```bash
# Generate src/.dev.env from src/env.yaml (run once, and again after env.yaml changes)
make gen-env

# Create external volumes/network and start all dev services
make dev
```

Open http://localhost (or http://localhost:4200 for the direct live-reload server).

### Start the development environment

```bash
make dev
```

### Start the production environment

```bash
make prod
```

### Switch to another branch (one command)

```bash
make switch b=feature/EST-1234
make dev       # or: make prod
```

### Switch branches manually (step by step)

```bash
make stash-tags
make backup
git checkout feature/EST-1234
make apply-tags
make apply-backup
make dev       # or: make prod
```

### Rebuild a single service without rebuilding everything

```bash
make dev-rebuild-s s=crew
```

### Rebuild everything from scratch

```bash
make rebuild-dev
```

### Run Django database migrations locally

```bash
make django-makemigrations
make django-migrate
```

### Reset all environments and start fresh

```bash
make clean
make dev
```

### Reset user (locked out or fresh credentials needed)

```bash
docker exec -it django_app python manage.py reset_user --username admin --password secret
```
