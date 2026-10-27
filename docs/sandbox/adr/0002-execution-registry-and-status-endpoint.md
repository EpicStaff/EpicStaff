---
status: accepted
date: 2026-10-26
decision-makers: Artur Drohomeretskyi
consulted: backend code review, security review
---

# An in-memory execution registry and a status endpoint

## Context and Problem Statement

After `POST /executions` returns 202, a producer only waits for a result on Redis pub/sub. If the sandbox restarts, crashes, or its result is dropped, the producer cannot tell. Crew waited 30 minutes; agent and realtime waited forever.

How does a producer find out, quickly and cheaply, that the sandbox no longer has its execution?

## Decision Drivers

- A lost execution must become a clear error within about a minute, not a hang.
- Normal runs must pay nothing extra.
- No new infrastructure, and no secrets outside the sandbox's memory ([0001](0001-http-intake-and-pubsub-results.md)).
- A producer that retries a submission after a timeout must not get the job run twice.

## Considered Options

1. An in-memory registry in the sandbox plus `GET /executions/{id}`; producers poll it while they wait.
2. A heartbeat lease in Redis, refreshed by the sandbox while a job runs.
3. Producers compute a deadline (queue + execution + grace) and give up when it passes.

## Decision Outcome

Chosen option: **1, an execution registry and a status endpoint**, because one small in-memory structure gives intake bounding, idempotent re-POST, status and lost-result detection at once.

`ExecutionRegistry` (`manager/application/registry.py`) keeps ids, states and timestamps only, never payloads:

- **States:** `held` (waiting for a venv build), `queued` (handed to the worker and not finished; this includes running), `done`.
- **Tombstone:** a finished id stays `done` for 60 s (`TOMBSTONE_SECONDS`), then is forgotten.
- **Reservation:** an id is reserved synchronously before the first `await` in `JobOrchestrator.submit`, so a concurrent duplicate cannot also pass. A refused or interrupted submission forgets its id.
- **Idempotent re-POST:** a known id is not enqueued again; the producer gets its current status. A re-POST while the first is still being admitted gets 503 with `Retry-After: 1` ([0003](0003-intake-admission-by-predicted-queue-wait.md)).
- **Order:** `ResultConsumer` publishes the result first, then calls `finish(id)`, also when publishing failed.

`GET /executions/{execution_id}` answers 200 `{execution_id, status}`, or 404 when the id is unknown. After a restart the registry is empty, so every waiting producer gets 404. After the tombstone expires, a producer still waiting gets 404, which means its result was published and never arrived.

### Consequences

- Good, because a restart or a dropped result fails the node in about 30–90 s with "The sandbox lost the execution…".
- Good, because a node faster than 30 s never sends a status request.
- Good, because a retry with the same `execution_id` after an HTTP timeout is safe.
- Bad, because everything depends on one process: a second uvicorn worker or replica would split the registry and answer false 404s. `entrypoint.sh` pins `--workers 1`.
- Bad, because the tombstone length is a trade-off: too short gives a false "lost" when a producer is slow to read a result it already received; too long delays detection.
- Neutral: there is no `running` state. `queued` covers running jobs, which affects the wait prediction ([0003](0003-intake-admission-by-predicted-queue-wait.md)).

### Validation

`docker restart sandbox_new` during a benchmark level fails the affected nodes with "The sandbox lost the execution…" within about 90 s, and no session ends as `timeout`.

## Pros and Cons of the Options

### 1. Registry and status endpoint

- Good, because it reuses the HTTP channel producers already use, and holds no payloads.
- Bad, because it is lost with the process, which is exactly the case it detects.

### 2. Heartbeat lease in Redis

- Good, because it would survive a sandbox restart and detect a dead worker within one lease period.
- Bad, because it adds a Redis write per running job every few seconds, and only answers "running or not", not "queued".

### 3. Producer-side deadline arithmetic

- Good, because no sandbox change is needed.
- Bad, because every producer duplicates the sandbox's timing, and the deadline must cover library installation, so detection takes minutes. See [0005](0005-queue-deadlines-owned-by-the-sandbox.md).

## More Information

- Producers poll through their sandbox clients ([0007](0007-producer-clients-per-service.md)): every 30 s, 404 means lost, three failed requests in a row mean unreachable.
- Each producer keeps a 35-minute backstop for anything the protocol does not catch.
