---
status: accepted
date: 2026-10-27
decision-makers: Artur Drohomeretskyi
consulted: backend code review, security review
---

# Each producer owns its sandbox client

## Context and Problem Statement

Four services submit Python executions: crew, agent, realtime and django_app (Test run). Three of them also wait for the result, and now all three need the same behaviour: retry a 503 with backoff, retry safely after a timeout, poll status while waiting, and treat 404 as lost. Crew could not use foundation at all: its image refuses to build source packages (`UV_NO_BUILD=1`), so it carried a copy of foundation's HTTP client.

Where does this behaviour live?

## Decision Drivers

- Foundation is a generic library: it must not know which services exist, so it holds no client, contract or helper for one particular service.
- A service owns the clients it uses to call other services.
- One wire contract between producers and sandbox_new.
- Keep the image build policy: no third-party source builds.
- Pub/sub result listening stays in each service.

## Considered Options

1. A client per producer service, built on foundation's generic `AsyncClient`; the contract and errors in `src/shared`.
2. One sandbox client in foundation, used by every producer.
3. A base sandbox client holding the shared algorithm, in foundation or `src/shared`, that each service subclasses.

## Decision Outcome

Chosen option: **1, a client per producer service**. crew (`clients/sandbox.py`), agent (`app/sandbox/http_client.py`) and realtime (`infrastructure/sandbox/sandbox_client.py`) each have their own client that subclasses `foundation.transport.http.AsyncClient`, the generic HTTP client with typed errors. Each implements the same protocol:

- **`submit(request, on_rejected=None)`:**
  - On 503, waits the larger of `Retry-After` and exponential backoff with full jitter (base 0.5 s, cap 10 s), within a budget of `SANDBOX_QUEUE_TIMEOUT`, then raises `SandboxOverloadedError`.
  - On a timeout, connection error, 502 or 504, retries the same `execution_id`. Intake is idempotent, so this cannot run the job twice.
  - If the budget runs out right after an unanswered attempt, it asks `status()` once; a 200 means the job was accepted after all.
  - Any other error status fails at once with the sandbox's message.
  - `on_rejected(attempt, delay)` lets the caller log each scheduled retry with its session.
- **`wait_for_result(execution_id, result, backstop)`:** awaits the service's own result future. Every 30 s without a result it calls `status()`: 200 keeps waiting, 404 raises `SandboxExecutionLostError` unless the result arrived at the same moment, 3 failures in a row raise `SandboxUnreachableError`, and the backstop raises `SandboxResultTimeoutError`.
- **The contract lives in `src/shared`:** `ExecutionRequest` (`src/shared/models/sandbox_execution.py`) is the submit schema, and sandbox_new's REST schema subclasses it. Secrets and storage credentials are hidden from `repr`. The `Sandbox*Error` types are in `src/shared/sandbox_errors.py`; they are plain exceptions, because `src/shared` does not depend on foundation.
- **Packaging:** crew, agent and realtime depend on foundation for `AsyncClient`, the same way django_app does: a path dependency, foundation added to `UV_NO_BINARY_PACKAGE`, and `COPY ./foundation` before `uv sync`. Crew's copy of foundation's HTTP client was deleted.
- **django_app** keeps its own synchronous submit and does not wait for results. On 503 it stores "The code sandbox is busy; try again in a moment." and does not retry inside the request.

### Consequences

- Good, because foundation stays generic: adding, renaming or removing a service never changes it.
- Good, because each service can change how it calls the sandbox without touching the others.
- Good, because each error type maps to one clear node error: overloaded, lost, unreachable, or timed out.
- Bad, because the retry and polling logic exists in three copies that can drift. Each copy has its own test suite with the same cases; a protocol change, such as a new status code, must be made in all three.
- Bad, because the audited exception to the no-source-build rule now covers three more images. It is first-party, pure Python code; the security review accepted it.
- Bad, because a session stop during a long 503 retry needed extra handling in crew: submit now runs inside the same 0.5 s stop poll as the result wait.

### Validation

A benchmark level above capacity shows `sandbox_rejected` lines and a non-zero `sandbox_retry_s`, with sessions completing after their retries.

## Pros and Cons of the Options

### 1. A client per service

- Good, because responsibility for calling the sandbox sits with the service that calls it.
- Bad, because the protocol is implemented three times.

### 2. One client in foundation

- Good, because the protocol is written and tested once.
- Bad, because foundation would know about one particular service. Code review rejected it: foundation provides generic building blocks, not clients for named services.

### 3. A shared base sandbox client

- Good, because the algorithm is written once and services override only what differs.
- Bad, because it is still sandbox-specific logic in a layer every service shares, with the same objection as option 2.
