---
status: accepted
date: 2026-10-26
decision-makers: Artur Drohomeretskyi
---

# BENCH checkpoints and a gate-state sample

## Context and Problem Statement

The benchmark tool reads BENCH checkpoint lines: one JSON line per event, logged at level 15 and only when a service's log level lets BENCH through. The contract is listed in `src/shared/bench_log.py`, and a checkpoint is changed only together with its reader. sandbox_new already logs the execution life cycle: `exec_received`, `exec_held`, `exec_queued`, `exec_start`, `exec_launched`, `exec_exited`, `exec_end`, `exec_published`. The reader also understands three admission-control checkpoints that nothing logged yet.

What must admission control log so that a benchmark can show whether, and how, it worked?

## Decision Drivers

- Log what the reader already understands, with exactly the names and fields it expects.
- Be able to explain throughput, not just measure it: which limit held work back?
- Every execution checkpoint carries `session_id` and `execution_id`.
- Foundation does not depend on EpicStaff's logging.
- Trivial cost.

## Considered Options

1. The reader's checkpoints plus a periodic gate-state sample.
2. Only the checkpoints the reader already understands.
3. Also log producer-side "unreachable" and "backstop timeout" events.

## Decision Outcome

Chosen option: **1, the reader's checkpoints plus a gate sample**.

| Checkpoint | Logged by | Fields |
| --- | --- | --- |
| `exec_expired` | sandbox_new, when a job waited past its queue deadline | `session_id`, `execution_id`, `waited_s` |
| `exec_published` outcome `overloaded` | sandbox_new, for that skipped job | as before |
| `sandbox_rejected` | crew and agent, on each 503 that will be retried | `session_id`, `execution_id`, `attempt`, `retry_after_s` |
| `sandbox_lost` | crew and agent, when the status check answers 404 | `session_id`, `execution_id` |
| `sandbox_gate` | sandbox_new, every 5 s | `running`, `floor`, `max_concurrent`, `cpu_busy_percent`, `memory_used_percent`, `queued`, `held`, `drain_rate`, `refused_cap`, `refused_prediction`, `refused_held_cap`, `refused_in_progress` |

- Worker failure results now carry `session_id` and, for expired jobs, the reason `overloaded`, so every `exec_published` names its session.
- `sandbox_rejected` is logged through the client's `on_rejected` callback ([0007](0007-producer-client-in-foundation.md)): the retries happen inside foundation, which must not import the BENCH logger. Producers log it, not the sandbox, because the cap guard rejects before the request body, and with it the `session_id`, is read.
- All 503s are raised in one place, `IntakeGate`, which counts them by reason. The gate sample reads and resets those counters, reads the registry counts, and takes the run gate's `snapshot()`. It lives in the composition root (`common/bootstrap/gate_sampler.py`), so manager code imports nothing from the worker.
- In `sandbox_gate`, `queued` is the registry's count, which includes running jobs; that is the number admission control uses.

### Consequences

- Good, because a benchmark shows rejections by reason, expirations, losses, and the run gate's view of CPU and memory over time.
- Good, because the lines are only written when BENCH is enabled; at the default INFO level nothing changes.
- Bad, because the reader does not use `sandbox_gate` yet; until it learns it, the lines serve manual analysis.
- Neutral: hold timeouts publish outcome `venv_failed`, a value the reader already ranks, rather than a new value it would not know.

### Validation

A benchmark run on this branch produces `sandbox_gate` lines every 5 s from sandbox_new, and at overloaded levels `sandbox_rejected` and `exec_expired` lines with session ids.

## Pros and Cons of the Options

### 1. Reader checkpoints plus gate sample

- Good, because it explains which limit (cap, prediction, held cap, CPU, memory) shaped throughput.
- Bad, because the sample is one more line every 5 s.

### 2. Reader checkpoints only

- Bad, because the gates' behaviour could not be inspected from a run.

### 3. Producer "unreachable" and "timeout" checkpoints

- Bad, because both are rare, the session already ends as an error with the reason, and the reader does not know them.
