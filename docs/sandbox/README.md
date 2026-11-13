# Sandbox admission control

Every Python execution a producer hands to `sandbox_new` ends in one of three ways: a result, an explicit "overloaded" answer, or the sandbox no longer knowing it (404). Producers detect the third case within about 30–90 s. No session waits forever for a result that will never come.

This folder records how that works and why it was built this way. The decisions are in [`adr/`](adr/), one per file; this page shows how they fit together.

## How to read these records

- Start with this page for the whole picture, then open the ADR for the part you are changing.
- Each ADR follows [MADR](https://adr.github.io/madr/). Read **Context and Problem Statement** and **Decision Outcome** to learn what was decided. Read **Considered Options** and **Consequences** before you argue for a different approach: most alternatives were weighed and rejected for a stated reason.
- An accepted ADR is not edited to change its decision. A new ADR supersedes it, and the old one's status says "Superseded by NNNN". Facts may still be added to **Validation**, for example benchmark results.
- Numbers marked *estimate* were not measured when the decision was made. Treat them as assumptions to check.

## Decisions

| ADR | Decision |
| --- | --- |
| [0001](adr/0001-http-intake-and-pubsub-results.md) | Keep HTTP intake and pub/sub results; no Redis task queue |
| [0002](adr/0002-execution-registry-and-status-endpoint.md) | An in-memory execution registry and a status endpoint |
| [0003](adr/0003-intake-admission-by-predicted-queue-wait.md) | Admit work by predicted queue wait, with a run cap |
| [0004](adr/0004-run-gate-on-measured-cpu-and-memory.md) | Start executions by measured CPU and memory, not a fixed count |
| [0005](adr/0005-queue-deadlines-owned-by-the-sandbox.md) | The sandbox owns queue deadlines; stale jobs are not run |
| [0006](adr/0006-held-jobs-cap-and-hold-deadline.md) | Jobs waiting for a venv build have their own cap and deadline |
| [0007](adr/0007-producer-clients-per-service.md) | Each producer owns its sandbox client |
| [0008](adr/0008-every-path-ends-in-a-result.md) | Every path ends in a result; a dead runner restarts the process |
| [0009](adr/0009-benchmark-checkpoints.md) | BENCH checkpoints and a gate-state sample |
| [0010](adr/0010-split-manager-and-worker-containers.md) | Manager and worker in two containers; the worker pulls jobs over HTTP |

## The request path

```mermaid
flowchart LR
    P["Producer<br/>crew, agent, realtime<br/>(SandboxClient)"]
    subgraph S["sandbox_new (manager container)"]
        G["Intake gate<br/>run cap, free slot,<br/>predicted wait"]
        R["Execution registry<br/>held, queued, assigned, done 60 s"]
        H["Held jobs<br/>own cap, hold deadline"]
        Q["Run queue<br/>queue deadline"]
        C["Result consumer<br/>publish, then finish"]
    end
    subgraph WK["sandbox_worker container"]
        W["Run gate<br/>floor, CPU, memory"]
        X["Execution pipeline"]
    end
    B["Redis pub/sub<br/>result channel"]

    P -- "POST /executions" --> G
    G -- "503 + Retry-After" --> P
    G --> R
    G -- "venv building" --> H
    G -- "venv built" --> Q
    H -- "venv built" --> Q
    W -. "GET /worker/jobs<br/>long-poll, bearer token + boot id" .-> Q
    W --> X
    X -. "POST /worker/results" .-> C
    WK -. "POST /worker/heartbeat<br/>every 10 s" .-> R
    C --> B --> P
    C -- "finish(id)" --> R
    P -. "GET /executions/{id}<br/>every 30 s" .-> R
```

- **Intake** ([0003](adr/0003-intake-admission-by-predicted-queue-wait.md), [0006](adr/0006-held-jobs-cap-and-hold-deadline.md)) decides whether a job may wait in line at all. A refused job gets 503 with `Retry-After`, and the producer retries with backoff.
- **The run gate** ([0004](adr/0004-run-gate-on-measured-cpu-and-memory.md)) decides when a queued job may start.
- **The registry** ([0002](adr/0002-execution-registry-and-status-endpoint.md)) knows every accepted job until 60 s after its result is published. A producer that is still waiting when the registry no longer knows its job treats the job as lost.

## Normal load

```mermaid
sequenceDiagram
    participant P as Producer
    participant S as sandbox_new
    participant B as Redis pub/sub
    P->>S: POST /executions
    S-->>P: 202 queued
    Note over S: run gate has a free slot: starts at once
    S->>B: result
    B-->>P: result
    Note over P: a node faster than 30 s sends no status request
```

## Heavy load

```mermaid
sequenceDiagram
    participant P as Producer
    participant S as sandbox_new
    participant B as Redis pub/sub
    P->>S: POST /executions
    S-->>P: 503, Retry-After: 4
    Note over P: backoff with jitter, honours Retry-After,<br/>within SANDBOX_QUEUE_TIMEOUT
    P->>S: POST /executions (same execution_id)
    S-->>P: 202 queued
    loop every 30 s while waiting
        P->>S: GET /executions/{id}
        S-->>P: 200 queued
    end
    alt started before its queue deadline
        S->>B: result
    else waited past the queue deadline
        S->>B: "Sandbox overloaded: ... not run"
    end
    B-->>P: result or overloaded answer
```

Under overload, users first see slower runs, then a clear "overloaded" error. Nothing waits without a limit.

## Crash, restart or lost result

```mermaid
sequenceDiagram
    participant P as Producer
    participant S as sandbox_new
    P->>S: POST /executions
    S-->>P: 202 queued
    Note over S: manager dies (or its result is dropped on pub/sub)
    Note over S: Docker restarts it with an empty registry
    P->>S: GET /executions/{id}
    S-->>P: 404
    Note over P: node fails: "The sandbox lost the execution"
```

When the worker container dies instead, the manager keeps its registry: the restarted worker's new boot id makes the manager fail every job assigned to the old run within seconds. A worker that hangs, or never comes back, is caught by silence: it heartbeats every 10 s (any authenticated contact counts), and a sweeper fails the assigned jobs of a run silent for over 60 s -- and, when no worker at all has made contact for that long, drains and fails the dispatch queue too. Jobs are never timed against their own duration: a legitimate run may take hours. Every one of these paths publishes a failed result with "Sandbox worker was lost; the job may not have finished." ([0010](adr/0010-split-manager-and-worker-containers.md)).

## Settings

All are set in `src/env.yaml`, which generates `src/.env.example`.

| Setting | Default | Read by | Meaning |
| --- | --- | --- | --- |
| `SANDBOX_QUEUE_TIMEOUT` | 120s | sandbox_new, sandbox_worker, crew, agent, realtime | How long a job may wait in the run queue (enforced by the manager's sweeper and on the worker's pull); the intake prediction limit; the producers' 503 retry budget |
| `SANDBOX_MAX_ACCEPTED_EXECUTIONS` | 1000 | sandbox_new | Queued or running executions accepted at once (set from the benchmark) |
| `SANDBOX_MAX_HELD_EXECUTIONS` | 100 | sandbox_new | Executions waiting for a venv build |
| `SANDBOX_HOLD_TIMEOUT` | 30m | sandbox_new | How long an execution may wait for its venv build |
| `SANDBOX_MIN_CONCURRENT_EXECUTIONS` | 0 | sandbox_worker | Run floor; 0 means the CPUs the container may use |
| `SANDBOX_MAX_CONCURRENT_EXECUTIONS` | 256 | sandbox_worker | Hard cap on running executions |
| `SANDBOX_CPU_ADMIT_THRESHOLD` | 85 | sandbox_worker | Host CPU % above which nothing starts beyond the floor |
| `SANDBOX_MEMORY_ADMIT_THRESHOLD` | 80 | sandbox_worker | Container memory % above which nothing starts beyond the floor |
| `CREW_CODE_RESULT_TIMEOUT`, `AGENT_CODE_RESULT_TIMEOUT`, `REALTIME_CODE_RESULT_TIMEOUT` | 40m | crew, agent, realtime | Backstop: the longest a producer waits for a result |
| `SANDBOX_INTERNAL_TOKEN` | generated | sandbox_new, sandbox_worker | Shared secret the worker presents on `/worker/*`; job payloads carry plaintext secrets, so the pull endpoint must not be open |

## Invariants

- **Exactly one manager process and one worker process.** The run queue, the execution registry and held jobs live in the manager's memory. `entrypoint.sh` runs uvicorn with `--workers 1`, and the worker container runs one pull loop; never add replicas of either without first replacing this state (see [0001](adr/0001-http-intake-and-pubsub-results.md), [0010](adr/0010-split-manager-and-worker-containers.md)).
- **No process-local value crosses the seam.** The manager and the worker are separate containers, so messages in `common/contracts.py` carry no process-local values. The queue time travels as `queued_at`, a wall-clock timestamp, never as a monotonic reading ([0005](adr/0005-queue-deadlines-owned-by-the-sandbox.md)).
- **Secrets stay in RAM.** Job payloads carry plaintext secrets and storage credentials. They are never written to Redis or disk, and logs carry ids and exception types only.

## Layers

sandbox_new follows a hexagonal layout: decisions live in `application`, the outside world in `infrastructure`, and the composition root in `common/bootstrap` wires them. These rules are enforced by import-linter contracts in `src/sandbox_new/pyproject.toml`, checked in CI:

- `manager.infrastructure` imports from `manager.application` only its `ports`.
- `worker.infrastructure` imports from `worker.application` only its `ports` and `context`.
- `common` imports no `infrastructure` module, except `common.bootstrap`, the composition root.
- `manager` and `worker` never import each other; only `common.bootstrap` connects them.

| Concern | Where it lives |
| --- | --- |
| Admission policy (intake gate, run gate) | `manager/application/intake.py`, `worker/application/resource_gate.py` |
| Reading CPU and memory | `worker/infrastructure/admission/host_metrics.py`, behind the `AbstractHostMetrics` port |
| Loops that push the application (result consumer, held-job releaser, worker-loss sweeper) | `manager/presentation/` |
| Gate-state sampling for the benchmark | `manager/presentation/intake_sampler.py` (`sandbox_intake`) and `worker/presentation/run_gate_sampler.py` (`sandbox_gate`), each typed on protocols |
| Wiring and runner supervision | `manager/bootstrap/runtime.py` (manager), `worker/main.py` (worker), `common/runner.py` (supervision) |
