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
| `intake_refused` | sandbox_new, once per 503 the intake gives | `reason` (`cap`, `prediction`, `held_cap`, `in_progress`), `retry_after`; no session |
| `exec_published` outcome `hold_timeout` | sandbox_new, for a job held past its hold deadline ([0006](0006-held-jobs-cap-and-hold-deadline.md)) | as before |
| `sandbox_gate` | sandbox_new, every 5 s | `running`, `floor`, `max_concurrent`, `cpu_busy_percent`, `memory_used_percent`, `queued`, `held`, `drain_rate` |

- Worker failure results now carry `session_id` and, for expired jobs, the reason `overloaded`, so every `exec_published` names its session.
- `sandbox_rejected` is logged through the client's `on_rejected` callback ([0007](0007-producer-clients-per-service.md)), so the HTTP client itself stays free of benchmark logging. Producers log it with the session, because the cap guard rejects before the request body, and with it the `session_id`, is read.
- **Instrumentation reads what already exists; it does not shape production APIs.** Every 503 is created in one place, `IntakeGate._refuse()`, and logged right there as `intake_refused`: one line per refusal with its exact time, instead of counters the gate would have to keep for an observer and a destructive "read and reset" method. The benchmark counts refusals per level by time.
- The gate sample is a neutral observer in `common/observability/gate_sampler.py`. It sees each side only through two protocols declared in that module, `IntakeMetrics` (`queued_count`, `held_count`, `drain_rate()`) and `RunGateMetrics` (`snapshot()`, declared on the run gate's port), so the only thing it takes from either side is `RunGateSnapshot`, the return type of that port: no implementation class, and nothing from infrastructure. The composition root (`common/bootstrap/lifespan.py`) only wires it.
- In `sandbox_gate`, `queued` is the registry's count, which includes running jobs; that is the number admission control uses.

### Consequences

- Good, because a benchmark shows rejections by reason, expirations, losses, and the run gate's view of CPU and memory over time.
- Good, because the lines are only written when BENCH is enabled; at the default INFO level nothing changes.
- Bad, because the reader does not use `sandbox_gate` yet; until it learns it, the lines serve manual analysis.
- Neutral: `hold_timeout` and `intake_refused` needed a matching update of the benchmark reader, made together with this contract; `intake_refused` has no session, so the reader attributes it to a level by time.

### Validation

A benchmark run on this branch produces `sandbox_gate` lines every 5 s from sandbox_new, and at overloaded levels `intake_refused` lines with their reasons, plus `sandbox_rejected` and `exec_expired` lines with session ids.

## Pros and Cons of the Options

### 1. Reader checkpoints plus gate sample

- Good, because it explains which limit (cap, prediction, held cap, CPU, memory) shaped throughput.
- Bad, because the sample is one more line every 5 s.

### 2. Reader checkpoints only

- Bad, because the gates' behaviour could not be inspected from a run.

### 3. Producer "unreachable" and "timeout" checkpoints

- Bad, because both are rare, the session already ends as an error with the reason, and the reader does not know them.
