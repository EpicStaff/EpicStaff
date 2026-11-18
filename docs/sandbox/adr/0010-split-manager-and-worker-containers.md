---
status: accepted
date: 2026-11-11
decision-makers: Bogdan Timchenko
consulted: refinement session for the container split and the worker network perimeter
---

# Split the manager and the worker into two containers; the worker pulls jobs over HTTP

## Context and Problem Statement

sandbox_new runs as one process holding both halves: the manager (REST intake, the execution registry, held jobs, venv builds, result publishing) and the worker (the resource-gated pipeline that runs untrusted user code). One process means one container, so user code executes inside a container that sits on `backend-network` and carries the manager's environment (database, Redis and storage credentials). The planned network perimeter around user code needs the worker in its own network with an egress firewall, while the venv API keeps talking to Postgres and Redis. That is impossible while both halves share one container.

Once the halves are separate containers, the in-memory `asyncio.Queue` seam is gone. Which transport carries jobs and results between them?

## Decision Drivers

- Job payloads carry plaintext secrets and storage credentials. They must not be written to Redis or disk ([0001](0001-http-intake-and-pubsub-results.md)).
- Job duration is unknown by design: a legitimate run may take hours, and users bound their own code with the per-job execution timeout. A lost worker must therefore be detected from the worker's liveness, never from how long a job has been running.
- The worker container must be easy to isolate: the smallest reachable surface, ideally no listening socket in the container that runs user code.
- Every accepted execution still ends in a result, even when one of the two containers dies ([0008](0008-every-path-ends-in-a-result.md)).
- The producer protocol does not change: crew, agent, realtime and django clients stay as they are ([0007](0007-producer-clients-per-service.md)).
- The simplest change that is enough: one worker container for now, but the transport should survive more workers later.

## Considered Options

1. The worker pulls jobs from the manager over HTTP (long-poll) and posts results back.
2. The manager pushes jobs to an HTTP endpoint on the worker.
3. A Redis Stream with a consumer group between the manager and the worker.

## Decision Outcome

Chosen option: **1, the worker pulls over HTTP**, because it leaves the worker with no listening socket at all, gives backpressure for free (a long-poll waiting under the live boot id IS a free slot, which is what the intake's free-slot probe now counts), keeps secrets in RAM and in flight on the internal Docker network only, and scales to several workers later without a transport change.

How the seam works:

- The worker takes a run-gate slot FIRST and only then long-polls `GET /worker/jobs`: the pull itself is the capacity signal, so a handed-out job always has a slot waiting and is never parked in the worker against its queue deadline. The manager answers with one `ExecutionJobMessage` (the `common/contracts.py` wire model, already free of process-local values) or 204 after about 25 s of nothing.
- Handing out a job marks it **assigned** to the pulling boot id in the execution registry. There is no per-job deadline of any kind (see the duration driver above). `GET /executions/{execution_id}` keeps reporting `queued` for assigned jobs, so producers see no new state.
- The worker posts `ExecutionResultMessage` (with storage mutations) to `POST /worker/results`. Delivery settles the assignment first, which makes it exactly-once on the manager's side: a retried POST the manager already accepted, or a result arriving after the job was failed as worker-lost, finds no assignment and is dropped. The result consumer publishes to Redis exactly as before.
- Every `/worker` endpoint requires `Authorization: Bearer <SANDBOX_INTERNAL_TOKEN>`. The pull hands out payloads with plaintext secrets; without the token any container on the network could drain other tenants' jobs.
- The worker generates a **boot id** (a UUID at process start), carried on every request. A new boot id supersedes the old one: the manager immediately fails every job assigned to the old run (a restarted worker surfaces its lost jobs within seconds), and a request still arriving under a superseded id -- a zombie long-poll whose connection died -- is never handed a job. Superseded ids are remembered by age (60 s, outliving any zombie), not by count, so a crash loop cannot push one out of memory early.
- The worker also beats `POST /worker/heartbeat` every 10 s, reporting the execution ids it actually holds: a saturated worker neither pulls nor, during a long run, posts anything, and the beat is its only sign of life. Any authenticated contact counts. The report also closes the lost-response path: an assignment of a live run missing from two consecutive reports (and older than a short grace -- one late beat composed before the pull response arrived is forgiven) had its pull response lost on the way, and the manager releases it -- nothing else ever would, since the run never goes silent. A sweeper fails the assigned jobs of a boot id silent for over 60 s; when no worker at all has made contact for that long it drains the dispatch queue and fails every queued job; and on every pass it fails queued jobs past their `SANDBOX_QUEUE_TIMEOUT` as overloaded, because a saturated slot-first worker never looks at the queue (this keeps the queue-deadline promise of ADR 0005 on the manager's side). Nothing waits for the producers' 40-minute backstop. All these failures carry the fixed text "Sandbox worker was lost; the job may not have finished." with `not_run_reason = worker_lost`.
- The result sink guarantees an outcome for every finished run: the result is delivered, a small fixed replacement failure is delivered when the manager refuses the body (a 4xx; resending the same bytes cannot help), or the worker process takes itself down -- on 401/403 (a rotated token must be visible, not hidden behind a retry loop) and when the manager stays unreachable past a retry budget that deliberately outlasts the 60 s silence threshold, so a stall the liveness model tolerates never kills running work. The restart's new boot id then lets the manager fail the stranded jobs fast.
- The registry, held jobs and intake stay in the manager. The worker keeps the run gate, the pipeline and the isolation launcher.

### Consequences

- Good, because the planned network perimeter can now put the worker on its own network behind an egress firewall while the manager keeps Postgres, Redis and `backend-network`.
- Good, because the manager container drops the sandbox capability set (SETUID, CHOWN, KILL, ...): no user code runs there. Venv builds and executions stop competing for one `mem_limit`.
- Good, because more workers later is a deployment change plus registry hardening, not a new transport.
- Bad, because a new secret (`SANDBOX_INTERNAL_TOKEN`) must be provisioned to both containers.
- Bad, because a network split longer than the 60 s silence threshold has the worker's jobs failed while their side effects keep happening; a result arriving after that is dropped, so the producer never sees two outcomes, but the work itself was done. Detection without this trade-off would need two-phase coordination the seam deliberately avoids.
- Bad, because the worker carries two more loops (heartbeat, and the staleness bookkeeping in the manager) than a single process needed.
- Bad, because every job now costs one HTTP round trip on the internal network; negligible against executions that run for seconds to minutes.

### Validation

- The integration test drives submit, pull, run and result over real HTTP in one test process.
- Killing the worker container mid-job on a live stack must fail the session's node with the worker-lost text within seconds of the worker's restart, never hang.

## Pros and Cons of the Options

### 1. Worker pulls over HTTP

- Good, because the worker has no listening socket next to user code, and firewall rules reduce to outbound-only.
- Good, because capacity signalling is implicit: no slot, no pull.
- Good, because the manager stays the only owner of registry and holding state.
- Bad, because job loss on a dead worker needs the boot id, heartbeat and settlement machinery described above.

### 2. Manager pushes to the worker

- Good, because dispatch stays synchronous, as it is in one process today.
- Bad, because the worker must listen next to user code: with `SANDBOX_BLOCK_NETWORK=false` (the default) user code can reach `127.0.0.1` in its own container, so the port needs its own authentication just to exist.
- Bad, because the manager needs a separate capacity channel to replace `FreeSlotProbe`.
- Bad, because several workers later mean service discovery and balancing in the manager.

### 3. Redis Stream with a consumer group

- Good, because queued jobs would survive a manager restart and several workers are natural.
- Bad, because job payloads with plaintext secrets would be written to Redis, breaking the stated driver from [0001](0001-http-intake-and-pubsub-results.md).
- Bad, because the worker would need Redis credentials and a route to Redis, reopening the network hole the split exists to close.
