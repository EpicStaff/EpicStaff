---
status: accepted
date: 2026-10-26
decision-makers: Artur Drohomeretskyi
consulted: backend code review, security review
---

# Admit work by predicted queue wait, with a run cap

## Context and Problem Statement

The run queue between manager and worker had no bound. Under load, jobs of about 600 KB each piled up inside a container limited to 2 GB, until the out-of-memory killer ended the process and every in-memory job with it. A queue also only helps if a job can start before its producer gives up: a job that will wait past its queue deadline should be refused up front, when the producer can still retry.

When may a new job enter the queue, and how is the producer told when it may not?

## Decision Drivers

- Bound memory: queued payloads must fit the container.
- Absorb short bursts; refuse only work that would expire anyway.
- Tell the producer when to come back.
- CPU belongs to the run gate ([0004](0004-run-gate-on-measured-cpu-and-memory.md)), not to intake.
- Rejecting must be cheap: decoding a 600 KB body only to refuse it wastes the CPU we are short of.

## Considered Options

1. Predicted queue wait plus a fixed run cap.
2. A fixed count cap only.
3. A CPU threshold at intake.

## Decision Outcome

Chosen option: **1, predicted queue wait plus a run cap**, because it asks the question that matters ("will this job start before its queue timeout?") and lets the queue grow or shrink with the workload.

`IntakeGate.admit` (`manager/application/intake.py`) decides, in this order:

1. **Run cap:** queued and running executions, not counting the caller's own reservation (`admit` receives its `execution_id` and asks the registry for `active_count_excluding`), at `SANDBOX_MAX_ACCEPTED_EXECUTIONS` → refuse.
2. **Free slot:** if the run gate could start a job right now → accept.
3. **Cold start:** fewer than 5 real executions recorded (`MIN_DRAIN_SAMPLES`) → accept; the cap alone applies.
4. **Prediction:** `drain_rate` = completions / (now − oldest of the last 20 real completions) (`DRAIN_SAMPLE_SIZE`). Predicted wait = (queued + 1) / drain_rate. Accept if it is at most `SANDBOX_QUEUE_TIMEOUT`, else refuse.

Only real executions count towards the drain rate. Skipped, expired and pre-run failures finish instantly; counting them would make the queue look fastest exactly during an overload. Measuring up to *now* makes the rate decay when nothing finishes, so a stall leads to refusal instead of switching the prediction off.

A refusal raises `SandboxOverloadedError` and, at that same point, logs one `intake_refused` BENCH checkpoint with its reason ([0009](0009-benchmark-checkpoints.md)). The REST layer answers **503** with `Retry-After` = predicted wait − queue timeout, clamped to 1–30 s (5 s when there is no prediction). A guard (`manager/presentation/rest/guards.py`) checks the run cap **before** the request body is decoded; Litestar runs guards before reading the body. The guard cannot see `execution_id`, so it checks only the cap; the prediction runs after decoding.

Jobs that will wait for a venv build are not judged by this rule; see [0006](0006-held-jobs-cap-and-hold-deadline.md).

### Consequences

- Good, because the producer gets an honest `Retry-After` and retries ([0007](0007-producer-clients-per-service.md)).
- Good, because the effective queue length follows the workload: long with short jobs, short with long ones.
- Good, because a full sandbox rejects without decoding the request body.
- Bad, because `queued` includes running jobs (there is no `running` state), so the prediction is high by about one average run time. Accepted: about 2 s of 120 s for short jobs.
- Bad, because the estimate lags sudden changes and averages mixed job lengths. The queue-deadline skip ([0005](0005-queue-deadlines-owned-by-the-sandbox.md)) is the backstop.
- Bad, because `SANDBOX_MAX_ACCEPTED_EXECUTIONS` (300) is a placeholder. It has to come from the measured memory per queued job.

### Validation

At levels above capacity, the benchmark counts `intake_refused` lines by reason (`cap`, `prediction`), sessions fail on latency or an "overloaded" answer rather than on timeouts, and memory stays under the container limit.

## Pros and Cons of the Options

### 1. Predicted wait plus cap

- Good, because it is CPU-aware without measuring CPU: a saturated CPU lowers the drain rate, which shrinks the accepted queue.
- Bad, because the estimate needs history; a cold start relies on the cap alone.

### 2. Fixed count cap only

- Good, because it is simple and predictable.
- Bad, because one number is too small for 1-second jobs and too large for 60-second jobs.

### 3. CPU threshold at intake

- Bad, because 90–95 % CPU is the normal state of a busy, healthy host. Jobs that would start within seconds would be refused.
- Bad, because CPU swings from second to second, so intake would flip between accepting and refusing, and every refused retry costs a body decode: a feedback loop.
- Bad, because CPU does not say how long a new job will wait.

## More Information

This is admission control by predicted queueing delay (Little's law), the same family of techniques as CoDel-style request queues.
