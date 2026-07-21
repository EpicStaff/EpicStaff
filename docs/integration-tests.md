# Integration Tests

All commands must be run from the **`integration_tests/`** directory.

---

## Prerequisites

### 1. Build all service Docker images

The test environment uses the same images as dev/prod. Before running tests, ensure all images are built:

```bash
# from project root
make dev-build
```

### 2. Create the external Docker network

Required once per machine. If it already exists, the command is a no-op.

```bash
docker network create mcp-network
```

### 3. Create `.env` file

Create `integration_tests/.env` with the following variables:

```env
OPENAI_KEY=<your key>
DJANGO_ADMIN_EMAIL=admin@example.com
DJANGO_ADMIN_PASSWORD=AdminPass123!
REDIS_PASSWORD=redis_password
```

---

## Running the tests

> **Note:** If you are re-running tests, always run `docker compose down -v --remove-orphans` first. Skipping this causes container name conflicts on the next `up`.

```bash
cd integration_tests
docker compose up --build --abort-on-container-exit --exit-code-from test_runner
```

Docker Compose will:
1. Spin up all services (`crewdb`, `redis`, `django_app`, `manager`, `crew`, `realtime`, `sandbox`, `knowledge`)
2. Wait for each service to become healthy
3. Start `test_runner` and run `pytest integration_test.py -v`
4. Shut everything down once `test_runner` exits

Exit code mirrors pytest: `0` = all passed, `1` = failures.

### Watching test output live

In a separate terminal while the stack is running:

```bash
docker logs test_runner --follow
```

Or wait for completion and print the last 30 lines:

```bash
docker wait test_runner; docker logs test_runner --tail 30
```

---

## Cleanup

After tests finish (or if something went wrong mid-run):

```bash
docker compose down -v --remove-orphans
```

The `-v` flag removes all volumes (including the PostgreSQL data volume), so the next run starts from a clean state.

---

## Services started by the test stack

| Container | Role | Port |
|---|---|---|
| `crewdb` | PostgreSQL | 5432 |
| `redis` | Queue / pub-sub | 6379 |
| `django_app` | Main REST API | 8000 |
| `manager_container` | Agent manager | 8001 |
| `crew` | CrewAI orchestration | 8002 |
| `realtime` | SSE / realtime | 8050 |
| `sandbox` | Code execution | — |
| `knowledge` | RAG service | — |
| `test_runner` | pytest runner | — |

---

## Troubleshooting

### Container name conflict

```
Error: Conflict. The container name "/crewdb" is already in use
```

Old containers from a previous run are still present. Remove them all:

```bash
docker compose down -v --remove-orphans
docker container prune -f
```

Then re-run the tests.

### `test_runner` exits immediately with code 0

Caused by stale volumes from a previous run. Full reset:

```bash
docker compose down -v --remove-orphans
docker volume prune -f
docker network rm mcp-network; docker network create mcp-network
docker compose up --build --abort-on-container-exit --exit-code-from test_runner
```

### Service health check failing

Check logs for the failing service:

```bash
docker logs crewdb
docker logs django_app
```

`django_app` health check polls `GET /ht/` every 30 s with up to 12 retries (6 minutes total). If it still fails, check that the `crewdb` container started correctly first.
