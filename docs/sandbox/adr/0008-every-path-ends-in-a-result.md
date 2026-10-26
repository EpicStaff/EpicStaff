---
status: accepted
date: 2026-10-26
decision-makers: Artur Drohomeretskyi
consulted: backend code review, security review
---

# Every path ends in a result; a dead runner restarts the process

## Context and Problem Statement

The execution pipeline itself turns a failing step into a failed result. Around it, three gaps could leave an accepted job without any result. The registry would then keep it `queued` forever, and its producer would wait for the backstop:

1. An exception after the pipeline, while building the result (secret scrubbing, validation) or handing it to the result queue.
2. An exception while taking the next job, such as a message that cannot be decoded. This ended the job consumer's loop, so the worker never ran another job.
3. A background runner (job consumer, result consumer, held-job releaser, gate sampler) ending with an exception. Nobody noticed, and the process kept answering 202 and 200.

How do we guarantee an outcome for every accepted job?

## Decision Drivers

- No accepted job may be left without a result or a 404.
- Error handling must never leak secrets: exception text may quote user code, output or credentials.
- Prefer a known clean state over repairing an unknown one.

## Considered Options

1. Close gaps 1 and 2 where they occur; for gap 3, stop the process and let Docker restart it.
2. For gap 3, restart the dead runner inside the process.
3. Leave gap 3 to the producers' backstop.

## Decision Outcome

Chosen option: **1, fail jobs where they break, and let a dead runner crash the process**.

- **Gap 1:** `JobConsumer._run` catches the exception, logs only the execution id and exception type, and sends "Sandbox failed to run the job." through `ExecutionOrchestrator.fail`. That result is built from constants, so it cannot hit the same error. The run slot is released in `finally`.
- **Gap 2:** each turn of the consumer loop has its own `try/except`. A message that cannot be decoded is failed by its `execution_id` (and `session_id` when readable), and the loop continues.
- **Gap 3:** each runtime task gets a done-callback. If a runner ever ends, by exception or by returning, it logs CRITICAL and stops the process gracefully. `restart: unless-stopped` in `docker-compose.yaml` brings it back with an empty registry, and producers get 404 within about 30 s ([0002](0002-execution-registry-and-status-endpoint.md)).
- Errors are logged by type only everywhere on these paths; loguru's `diagnose` is off in every service.

### Consequences

- Good, because a broken job or message no longer takes the worker down.
- Good, because a dead runner becomes a visible restart and clear node errors, not a sandbox that accepts work and never runs it.
- Bad, because a runner crash drops every in-flight job, all of which fail as "lost". Every runner loop catches per-item errors, so this should not happen in practice; the security review found no way for user input to trigger it.
- Bad, because without the restart policy a crash would leave the sandbox down. The policy is part of this decision.

### Validation

Tests cover each gap: a raising run gets a failed result and frees its slot, an undecodable message is failed and the loop continues, and a runner ending triggers the stop hook (cancellation does not).

## Pros and Cons of the Options

### 1. Fail where it breaks; crash on a dead runner

- Good, because a fresh process has known state, and the status protocol already turns a restart into clear errors.
- Bad, because one dead runner costs all in-flight work.

### 2. Restart the runner in place

- Good, because other in-flight jobs survive.
- Bad, because a runner that died leaves unknown state behind, such as a leaked slot or a half-processed item, and restarting it carries that state forward.

### 3. Rely on the backstop

- Bad, because every affected node would wait 35 minutes.

## More Information

This is the "let it crash" approach: supervision restarts a component from a clean state instead of repairing it in place.
