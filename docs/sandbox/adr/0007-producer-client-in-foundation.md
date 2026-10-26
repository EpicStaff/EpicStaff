---
status: accepted
date: 2026-10-26
decision-makers: Artur Drohomeretskyi
consulted: backend code review, security review
---

# One producer client in foundation

## Context and Problem Statement

Four services submit Python executions: crew, agent, realtime and django_app (Test run). Each had its own copy of the submit code. Three of them also wait for the result, and now all three need the same behaviour: retry a 503 with backoff, retry safely after a timeout, poll status while waiting, and treat 404 as lost. Crew could not use foundation at all: its image refuses to build source packages (`UV_NO_BUILD=1`), so it carried a copy of foundation's HTTP client.

Where does this behaviour live?

## Decision Drivers

- One implementation of the submit and wait protocol, not three.
- Foundation is the shared layer for communication between services; it must not depend on EpicStaff service code or logging.
- Keep the image build policy: no third-party source builds.
- Pub/sub result listening stays in each service.

## Considered Options

1. A sandbox client in foundation, with crew, agent and realtime depending on foundation.
2. A client in `src/shared`, which every producer can already import.
3. Keep a copy per service.

## Decision Outcome

Chosen option: **1, `foundation.clients.sandbox.SandboxClient`**, built in the style of `foundation.transport.http`: a thin `httpx` subclass with typed errors, no abstract base.

- **`submit(request, on_rejected=None)`:**
  - On 503, waits the larger of `Retry-After` and exponential backoff with full jitter (base 0.5 s, cap 10 s), within a budget of `SANDBOX_QUEUE_TIMEOUT`, then raises `SandboxOverloadedError`.
  - On a timeout, connection error, 502 or 504, retries the same `execution_id`. Intake is idempotent, so this cannot run the job twice.
  - If the budget runs out right after an unanswered attempt, it asks `status()` once; a 200 means the job was accepted after all.
  - Any other error status fails at once with the sandbox's message.
  - `on_rejected(attempt, delay)` lets the caller log each scheduled retry; foundation itself logs nothing.
- **`wait_for_result(execution_id, result, backstop)`:** awaits the service's own result future. Every 30 s without a result it calls `status()`: 200 keeps waiting, 404 raises `SandboxExecutionLostError` unless the result arrived at the same moment, 3 failures in a row raise `SandboxUnreachableError`, and the backstop raises `SandboxResultTimeoutError`.
- **`ExecutionRequest`** is the shared submit schema; sandbox_new's REST schema subclasses it. Secrets and storage credentials are hidden from `repr`.
- **Packaging:** crew, agent and realtime depend on foundation the same way django_app does: a path dependency, foundation added to `UV_NO_BINARY_PACKAGE`, and `COPY ./foundation` before `uv sync`. Their copied clients were deleted.
- **django_app** keeps its own synchronous submit and does not wait for results. On 503 it stores "The code sandbox is busy; try again in a moment." and does not retry inside the request.

### Consequences

- Good, because the protocol is written and tested once.
- Good, because each error type maps to one clear node error: overloaded, lost, unreachable, or timed out.
- Bad, because the audited exception to the no-source-build rule now covers three more images. It is first-party, pure Python code; the security review accepted it.
- Bad, because a session stop during a long 503 retry needed extra handling in crew: submit now runs inside the same 0.5 s stop poll as the result wait.

### Validation

A benchmark level above capacity shows `sandbox_rejected` lines and a non-zero `sandbox_retry_s`, with sessions completing after their retries.

## Pros and Cons of the Options

### 1. Foundation

- Good, because it is the layer meant for communication between services.
- Bad, because it changes three images' packaging.

### 2. `src/shared`

- Good, because no packaging change is needed.
- Bad, because it puts a transport client next to unrelated shared models, and duplicates foundation's HTTP client and error types.

### 3. A copy per service

- Bad, because three copies of retry and polling logic will drift.
