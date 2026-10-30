---
status: accepted
date: 2026-10-26
decision-makers: Artur Drohomeretskyi
consulted: backend code review, security review
---

# Keep HTTP intake and pub/sub results; no Redis task queue

## Context and Problem Statement

Python executions used to reach the sandbox as messages on a Redis pub/sub channel. Under load the sandbox read them more slowly than producers published them. Once a subscriber's buffered messages passed the pub/sub output-buffer limit (`client-output-buffer-limit pubsub 64mb` in `src/redis.conf`), Redis disconnected it and discarded everything buffered. In a load test about 330 of 5,000 sessions hung, some for 30 minutes, because their tasks were silently gone. A local reproduction with a 1 MB limit lost 182 of 200 messages; the same flood through a Redis list lost none.

The sandbox was then rebuilt as `sandbox_new`. Producers now submit with `POST /executions` and get `202 Accepted`; results still return over Redis pub/sub. That removes the dropped-task path, but executions could still hang: the in-memory queue had no bound, a restart lost everything in memory, and producers had no way to learn that the sandbox had lost an execution.

Which transport should carry tasks and results while we fix the hangs?

## Decision Drivers

- Every accepted execution must end with a result or a clear error; no session may hang.
- No noticeable extra CPU: the host is already CPU-bound at about 215 sessions/min on the payload flow.
- Job payloads carry plaintext secrets and storage credentials. They must not be written to Redis or disk (the rule stated in `common/contracts.py`).
- Keep the venv-manager's hexagonal design (`AbstractJobDispatcher`, `AbstractJobSource`) intact.
- The simplest change that is enough.

## Considered Options

1. Keep HTTP intake and the in-memory queue; bound it and make losses detectable ([0002](0002-execution-registry-and-status-endpoint.md)–[0006](0006-held-jobs-cap-and-hold-deadline.md)).
2. Replace the in-memory queue between manager and worker with a Redis Stream and a consumer group, with idempotent redelivery.
3. Have producers push tasks to a Redis List (`LPUSH` / `BRPOP`) instead of HTTP.
4. Raise the pub/sub output-buffer limit.

## Decision Outcome

Chosen option: **1, keep HTTP intake and pub/sub results**, because it fixes every remaining hang cause without new infrastructure, keeps secrets in RAM and adds no measurable CPU.

### Consequences

- Good, because the transport does not change for any producer.
- Good, because job payloads never leave the sandbox process's memory.
- Bad, because queued jobs do not survive a sandbox restart. They now fail within about 30–90 s instead of hanging ([0002](0002-execution-registry-and-status-endpoint.md)), but they are not re-run.
- Bad, because results are still at-most-once pub/sub. A lost result is detected through the status endpoint, not prevented.
- Bad, because the design requires exactly one sandbox process. Scaling workers out needs a shared queue first, and then option 2 becomes the right choice.

### Validation

The benchmark (same server and flow as before the change) shows no session ending as `timeout` and no `output buffer` lines in the Redis log for the sandbox.

## Pros and Cons of the Options

### 1. HTTP intake and in-memory queue, bounded and observable

- Good, because the request is validated synchronously (venv not found → 404) before the producer is told it was accepted.
- Good, because no serialization step is added between manager and worker; the job is handed over as a Python object.
- Bad, because in-memory state dies with the process.

### 2. Redis Stream with a consumer group between manager and worker

- Good, because queued jobs survive a restart, and a job that was running when the process died can be detected and failed quickly.
- Good, because it is the natural step when workers move into their own containers.
- Bad, because job payloads, secrets included, would sit in Redis for the whole execution, and Redis writes disk snapshots.
- Bad, because every job gains a JSON encode, a round trip and a decode of about 600 KB (*estimate*: a few ms of CPU).
- Bad, because redelivery without idempotency re-runs user code, so side effects (HTTP calls, emails, storage writes) can happen twice. With idempotency, the result is still "fail fast", which option 1 also gives.

### 3. Producers push to a Redis List

- Good, because a slow consumer only makes the queue longer; nothing is dropped.
- Bad, because it bypasses the HTTP intake's validation and venv holding.
- Bad, because payloads with secrets sit in Redis while queued.

### 4. Raise the pub/sub buffer limit

- Good, because it is a one-line change.
- Bad, because it only moves the threshold, and it applies to every pub/sub subscriber, including browsers' event streams.

## More Information

- The reconnect after a buffer overflow is not silent: redis-py 5.3.1 re-raises the `ConnectionError` because our clients set `retry` but not `retry_on_error`. This was verified against its source and by local reproduction.
- The output-buffer limit in `src/redis.conf` stays as it is: it still protects the session event streams.
