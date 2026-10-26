---
status: accepted
date: 2026-10-26
decision-makers: Artur Drohomeretskyi
consulted: backend code review
---

# The sandbox owns queue deadlines; stale jobs are not run

## Context and Problem Statement

Under overload a job can wait in the run queue until its producer has given up. Running it then spends CPU on a result nobody reads, which delays the fresh jobs behind it, so the backlog keeps growing. Something has to bound how long a job may wait in line, and every waiting producer has to know how long to wait.

Who sets that limit, and what happens to a job that exceeds it?

## Decision Drivers

- Never spend CPU on work nobody waits for.
- One source of truth for timing, so it cannot drift between services.
- No clock comparisons across containers.
- Time spent waiting for a venv build is not queue time.

## Considered Options

1. The manager stamps a queue deadline when a job enters the run queue; the worker skips expired jobs.
2. Producers stamp a deadline and compute their own wait: queue + execution timeout + grace (`SANDBOX_RESULT_GRACE`).
3. No deadline; stale jobs run anyway.

## Decision Outcome

Chosen option: **1, sandbox-owned queue deadlines**, because the sandbox is the information expert on its own queue: it knows when a job was queued, and it enforces both the queue timeout and the execution timeout itself.

- `JobOrchestrator._dispatch` sets `queue_deadline = monotonic now + SANDBOX_QUEUE_TIMEOUT` when the job enters the run queue: at submission for a built venv, or at release for a held job. Never while held ([0006](0006-held-jobs-cap-and-hold-deadline.md)).
- `JobConsumer` takes a job and, if the deadline has passed, sends "Sandbox overloaded: the job waited N s in the queue and was not run." without taking a run slot. Otherwise it waits for the run gate, but no longer than the deadline, and checks again after admission.
- Producers do no deadline arithmetic. They wait for the result, check status every 30 s ([0002](0002-execution-registry-and-status-endpoint.md)), and keep a 35-minute backstop. The previously planned `SANDBOX_RESULT_GRACE` setting was dropped.

### Consequences

- Good, because expired jobs cost no CPU, and because the queue is in deadline order, they are answered as soon as they reach the head.
- Good, because the wait at the gate is bounded by the deadline, so one long-running job cannot delay every expired job behind it.
- Good, because the monotonic clock of one process avoids clock skew. This is valid only while there is one sandbox process.
- Bad, because a job released from a venv hold near the end of its hold window can still queue and run past the producer's 35-minute backstop. The producer then reports a timeout. Rare; accepted.

### Validation

At levels above capacity, the benchmark counts `exec_expired` lines, and those sessions end with outcome `overloaded` instead of a timeout.

## Pros and Cons of the Options

### 1. Sandbox-owned deadlines

- Good, because a single component owns the timing.
- Bad, because producers only learn about expiry through the result, not in advance.

### 2. Producer-side deadlines and a grace period

- Bad, because every producer duplicates the arithmetic and must stay in sync with the sandbox's timeouts.
- Bad, because the grace must cover library installation, which can take minutes, so lost jobs are detected late.
- Bad, because comparing a producer's clock with the sandbox's adds clock skew.

### 3. No deadline

- Bad, because during overload the sandbox wastes CPU on abandoned work, and the backlog feeds on itself.
