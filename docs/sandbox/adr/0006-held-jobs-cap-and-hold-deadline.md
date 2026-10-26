---
status: accepted
date: 2026-10-26
decision-makers: Artur Drohomeretskyi
consulted: security review
---

# Jobs waiting for a venv build have their own cap and deadline

## Context and Problem Statement

A job whose venv is still building is **held**: it waits in `JobHoldingRegistry` until the build finishes, then enters the run queue. In the first version of admission control, held jobs counted towards the run cap and had no deadline.

The security review found a cross-organization lockout. A member of one organization could make their venv rebuild, or declare one whose build hangs, then submit about 300 runs. Every slot of the global cap would fill with held jobs, and every organization's submissions would get 503 until the build finished, possibly never. The same could happen without an attacker: a venv left in PROCESSING by a restart is never rebuilt, and jobs waiting for it would stay held.

How are held jobs bounded so that they cannot block other work?

## Decision Drivers

- One tenant must not be able to block other tenants' work.
- A held job must not wait forever.
- Normal runs on built venvs, which is almost all work, must not depend on the state of venv builds.

## Considered Options

1. A separate held cap plus a hold deadline.
2. A hold deadline only, still counted in the run cap.
3. A separate held cap only, with no deadline.

## Decision Outcome

Chosen option: **1, a separate held cap and a hold deadline**.

- Held jobs no longer count towards `SANDBOX_MAX_ACCEPTED_EXECUTIONS`. They have their own limit, `SANDBOX_MAX_HELD_EXECUTIONS` (100). A submission that would be held beyond it gets 503 with `Retry-After: 30`, because held jobs drain at venv-build speed.
- Every held job gets a deadline: `SANDBOX_HOLD_TIMEOUT` (30 minutes, kept below the producers' 35-minute backstop). The held-job releaser runs every 2 s and fails overdue jobs first, whatever their venv's status, with "The execution environment did not finish building in time; the job was not run." Their published outcome is `venv_failed`.
- A released job is dispatched even when the run cap is full: it was already admitted and has waited. The run gate still bounds what runs at once, and its queue deadline still bounds its wait. The worst case is run cap + held cap accepted jobs.

### Consequences

- Good, because a tenant filling the held cap cannot affect submissions to built venvs.
- Good, because a stuck build fails its jobs within 30 minutes instead of holding them forever.
- Bad, because one tenant can still keep the held cap full. Other organizations then get 503 only for submissions to venvs that are themselves still building. A per-venv cap would close this.
- Bad, because the worst-case accepted total is now 400 jobs; their memory has to be checked against the container limit.
- Neutral: the guard that rejects before reading the body still checks only the run cap, because it cannot know whether a job will be held.

### Validation

A test with the run cap full of queued jobs still accepts a held submission, and with the held cap full still accepts a built-venv submission.

## Pros and Cons of the Options

### 1. Separate cap and deadline

- Good, because held and running work are bounded independently.
- Bad, because there are two more settings to tune.

### 2. Deadline only

- Bad, because one tenant could still block everyone for up to the hold timeout.

### 3. Separate cap only

- Bad, because a stuck build would keep its held jobs until the next restart.

## More Information

Two causes live in the venv-build code itself and are left as follow-ups for its owner: the uv build has no timeout, and a venv left in PROCESSING after a restart is never rebuilt. With this decision they can no longer affect anything outside their own venv.
