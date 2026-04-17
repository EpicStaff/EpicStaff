# Makefile Commands Reference

All commands must be run from the **project root directory** (where `Makefile` lives).

---

## Table of Contents

- [Help](#help)
- [Development Environment](#development-environment)
- [Production Environment](#production-environment)
- [Branch Switching](#branch-switching)
- [Utilities](#utilities)
- [Local Django Development](#local-django-development)
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

Uses `docker-compose.yaml` + `docker-compose.dev.yaml` with env files `.env` and `dev/dev.env`.

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

Uses `docker-compose.yaml` + `docker-compose.override.yaml` with env file `.env`.

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

---

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
