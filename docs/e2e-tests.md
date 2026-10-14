# End-to-end tests

Black-box tests that run against a complete EpicStaff stack through nginx (`http://localhost`),
the same way the frontend and API users reach it. They live in `tests/e2e/` and run on the
host; nothing from the suite is shipped in a service image.

---

## Table of Contents

- [What the suite is](#what-the-suite-is)
- [Prerequisites](#prerequisites)
- [Running locally](#running-locally)
- [What each file covers](#what-each-file-covers)
- [Outputs](#outputs)
- [Running part of the suite](#running-part-of-the-suite)
- [Environment variables](#environment-variables)
- [Troubleshooting](#troubleshooting)
- [Known issues](#known-issues)
- [Later: CI](#later-ci)

---

## What the suite is

- **Real stack.** `src/docker-compose.yaml` plus the override `tests/e2e/docker-compose.e2e.yaml`,
  started under its own compose project (`-p epicstaff-e2e`).
- **Isolated data.** The override turns the four volumes the main file declares as external
  (`crew_pgdata`, `sandbox_venvs`, `media_data`, `opensearch_data`) into project-local
  `e2e_*` volumes. `down -v` removes them, and an e2e run never touches the dev database.
  `tests/e2e/e2e.env` also points the sandbox's saved-files folder at `tests/e2e/savefiles`.
- **Mock LLM.** The override adds `mock-llm` (`tests/e2e/mock_llm/server.py`, stdlib only, run
  from the pinned `python:3.12.10-slim` image). It answers OpenAI-compatible chat completions
  and embeddings deterministically: an agent with a `search_*` tool calls it once, then answers
  `ANSWER: <tool result>`; embeddings are a fixed vector. Its call log is readable at
  `http://localhost:18080/__calls`.
- **Black box.** Tests talk HTTP to nginx only. Bootstrap: first-setup creates the superadmin,
  then a custom role, a user, the user's login and an API key. From then on every request
  uses `X-Api-Key` + `X-Organization-Id`.
- **One-shot.** First-setup works once per database, so **every run needs a freshly created
  stack** (`down -v`, then `up -d`).

## Prerequisites

| Tool | Notes |
|---|---|
| Docker with Compose v2 | Images are built from this checkout, or pulled with `IMAGE_TAG`. |
| [uv](https://docs.astral.sh/uv/) | Creates the suite's own venv from `tests/e2e/uv.lock`. |
| Python 3.12.10 | uv picks it up or downloads it. |
| bash | On Windows, use Git Bash or WSL for the commands below. |

Free ports: 80 (nginx), 18080 (mock-llm), plus the dev stack's published ports. The containers
have fixed names, so stop the dev stack first.

## Running locally

From the repository root:

```bash
python scripts/envtool.py --dev        # writes src/.env (gitignored)
docker network inspect mcp-network >/dev/null 2>&1 || docker network create mcp-network
                                       # declared external in compose

DC="docker compose -p epicstaff-e2e --env-file src/.env --env-file tests/e2e/e2e.env \
  -f src/docker-compose.yaml -f tests/e2e/docker-compose.e2e.yaml"

$DC up -d                              # ~5.5 min on a fresh database (migrations)
uv run --project tests/e2e python tests/e2e/scripts/wait_for_stack.py
uv run --project tests/e2e pytest tests/e2e -v --junitxml=tests/e2e/.timings/junit.xml
$DC down -v --remove-orphans           # fresh database for the next run
```

- `tests/e2e/e2e.env` is for the test stack only: never pass it to a real deployment. It
  lengthens the JWT lifetime, keeps first-setup open and turns SSL off.
- `e2e.env` comes **after** `src/.env`, so its values win:
  - the mock LLM's embedding URL;
  - no compose profiles (no mailpit);
  - a 2 h access-token lifetime: the suite logs in once per user because login is throttled;
  - first-setup over HTTP;
  - plain HTTP;
  - the e2e saved-files folder.
- `up -d` returns once Django is healthy; `wait_for_stack.py` then also checks
  first-setup and mock-llm.
- A full run takes about 3 minutes on a fresh stack.

## What each file covers

| File | Covers |
|---|---|
| `test_auth_rbac.py` | Each bootstrap step (status codes and response shape), first-setup closed afterwards (`409 setup_already_completed`), superadmin login. |
| `test_llm_config.py` | Quickstart with the API key, a custom model pointing at mock-llm, an LLM config bound to the quickstart secret. |
| `test_storage.py` | Streamed raw-body upload through nginx, list, info, byte-exact download. |
| `test_rag.py` | Collection, document upload, naive RAG with the character chunker, indexing via mock embeddings, chunks contain the run's token. |
| `test_agent.py` | Knowledge surface, agent definition on the mock LLM, the legacy `instructions` field is refused. |
| `test_flow_python.py` | Flow A (Start → Python `a + b` → End): save, run, final state, session messages. |
| `test_flow_agent_rag.py` | Flow B (Start → Knowledge → Task with the RAG tool → End): retrieval, agent answer from the tool, mock-llm received the tool result. |
| `test_sse.py` | Runtime delivery of a flow B run: subscribed while the run is going, the knowledge and task nodes' `finish`, `graph_end` and the `end` status arrive live (after the replay's initial status), node finishes in run order and before the completion events; prompt first event; replay of an ended flow A run; ticket refusals; another org's session. |
| `test_rbac_negative.py` | API keys refused on JWT-only endpoints, missing org header, other-org access, Viewer cannot create. |
| `test_concurrency.py` | Ten parallel flow A runs (marker `load`). |

Shared resources are session fixtures:
- `conftest.py`: bootstrap chain, warm-up run, clients.
- `fixtures/llm.py`, `fixtures/knowledge.py`, `fixtures/agents.py`, `fixtures/orgs.py`.

Every file therefore runs on its own. Helpers live in `helpers/`:
- `api.py`: client, logging, error envelope.
- `polling.py`, `flows.py`, `sse.py`, `payloads.py`, `mock_llm.py`.
- `redaction.py`, `timings.py`.

## Outputs

- **`tests/e2e/.timings/timings.json`** (gitignored). It merges `stack_ready.json` from
  `wait_for_stack.py` with:
  - `bootstrap_seconds`, `warm_up_seconds`;
  - `flow_python_run_seconds`, `flow_agent_rag_run_seconds`;
  - `rag_indexing_seconds`, `sse_first_event_seconds`;
  - `sse_live_attempts` (runs the live SSE check needed, normally 1);
  - `sse_post_to_initial_status_seconds`, `sse_post_to_end_seconds` (the margin the live SSE
    check has: run-session POST to the replay's initial status, and to the live `end`);
  - `concurrency_wall_seconds`, `concurrency_run_p50_seconds`, `concurrency_run_p95_seconds`.
- **JUnit** with `--junitxml=<path>`. Under `tests/e2e/.timings/` it is gitignored.
- **Diagnostics on failure.**
  - Every request is logged (method, URL, status, duration) and shown with a failing test.
  - An unexpected status shows the response body.
  - A failed run shows the session status, `status_data` and its messages.
  - Bootstrap failures name the step.
- **Secret redaction.** Credentials the suite creates (passwords, JWTs, API keys, SSE
  tickets) are scrubbed from log lines and assertion messages, and the suite's own variables
  holding them print as `<redacted>`. Under `--showlocals`, library frames are not scrubbed:
  httpx / httpcore / h11 request objects can show the raw `X-Api-Key` header or an SSE ticket
  in a URL. Do not share `--showlocals` output from a run against a stack with real data.

## Running part of the suite

```bash
uv run --project tests/e2e pytest tests/e2e/test_rag.py -v      # one file (still needs a fresh stack)
uv run --project tests/e2e pytest tests/e2e -m "not load" -v    # skip the concurrency test
```

Each pytest invocation runs the bootstrap again, so reset the stack between invocations.

## Environment variables

| Variable | Default | Used by |
|---|---|---|
| `E2E_BASE_URL` | `http://localhost` | suite, `wait_for_stack.py` |
| `E2E_MOCK_LLM_URL` | `http://localhost:18080` | suite, `wait_for_stack.py` |
| `E2E_STACK_TIMEOUT` | `600` (seconds) | `wait_for_stack.py` |
| `E2E_TIMINGS_DIR` | `tests/e2e/.timings` | suite, `wait_for_stack.py` |

## Troubleshooting

- **`bootstrap step 1 (readiness): ... DB is not fresh`**: first-setup was already used. Run
  `$DC down -v --remove-orphans` and `$DC up -d`. If the message says first-setup over HTTP is
  closed, `DJANGO_FIRST_SETUP_MODE` is not `open`; check that `e2e.env` is passed second.
- **Every python run ends in `error` on Linux.** Kernels before 6.12 (Landlock ABI below 6)
  cannot provide the sandbox's signal isolation, and the sandbox refuses to run code. Add
  `SANDBOX_REQUIRE_SIGNAL_ISOLATION=false` to `tests/e2e/e2e.env` locally (never with real
  data).
- **Container name already in use.** All containers have fixed names: stop the dev stack
  before `up`.
- **Cannot delete `tests/e2e/savefiles` on Linux.** Docker creates it as root and the sandbox
  hands it to uid 1000; remove it with `sudo`.
- **Port 18080 in use.** mock-llm publishes `127.0.0.1:18080:8080`; free the port, or
  change the mapping in the override and set `E2E_MOCK_LLM_URL`.

## Known issues

- **The sandbox has a parallel venv creation race.** It builds one venv per library set with
  no lock per venv path (`src/sandbox/dynamic_venv_executor_chain.py`). When parallel runs need
  a venv that does not exist yet, they all build it in the same directory at once and corrupt
  each other's pip install; while that happens the API can also stop answering for more than
  30 s. In a full run the concurrency batch runs last on an already-built venv, so it does not hit the race
  and does **not** exercise it. To reproduce it, run the batch alone on a fresh stack
  (`$DC down -v --remove-orphans`, `$DC up -d`, `wait_for_stack.py`), then
  `uv run --project tests/e2e pytest tests/e2e/test_concurrency.py -v`:
  `test_every_parallel_run_ends` fails and the sandbox log shows ten
  `Creating virtual environment at <same path>` lines within a second.
- **The live SSE check may start up to three runs.** Subscribing needs the session id that
  the run-session POST returns, so the run's earliest asserted event (the knowledge node's
  `finish`) can precede the subscription. That is a harness race and the only retried case:
  the replay's status is already `end`, or the run is still going but that `finish` was
  already replayed. `test_sse.py` detects it as soon as the status event arrives, then
  starts a fresh run with a fresh ticket (at most three attempts, counted in
  `sse_live_attempts`, with a warning when above one). Any other problem (an error status,
  missing live events, wrong order, timeouts) fails on the first attempt.
- **The SSE stream can deliver the `end` status before `graph_end`.** The status reaches the stream
  in one Redis hop (crew to the status channel), messages in two (crew to Django to the update
  channel), so a client may see `end` before the run's last messages. `test_sse.py` therefore
  does not assert the order between `graph_end` and `end`.
- **`load` tests run last.** A hook in `conftest.py` moves them to the end, because the parallel
  batch can leave the shared sandbox venv broken for every later python run (the race above).
  `--ff` / `--nf` reorder after the hook, and xdist (`-n`) breaks "last"; do not use them.
- **The first two python runs after a reset each build a venv** (about 35 s each). Installing
  the shared local libraries changes their content fingerprint, so the second run computes a
  new venv hash. Later runs reuse that venv and take about 1–2 s.

## Later: CI

A manually triggered workflow will run exactly the commands above on a runner and keep
`timings.json` and the JUnit report as artifacts. Running it on pull requests, and making it a
required check, is a later step: add a `pull_request` trigger to that workflow, then mark the
job as required in the branch protection rules.
