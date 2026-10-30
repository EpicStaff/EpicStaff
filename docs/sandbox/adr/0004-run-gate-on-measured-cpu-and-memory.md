---
status: accepted
date: 2026-10-26
decision-makers: Artur Drohomeretskyi
consulted: backend code review
---

# Start executions by measured CPU and memory, not a fixed count

## Context and Problem Statement

The worker ran at most 4 executions at once (`Semaphore(SANDBOX_WORKER_CONCURRENCY)`). On a 12-vCPU host that left most cores idle for CPU-bound flows. A fixed count is also wrong for sleeping or I/O-bound code: 4 jobs calling `time.sleep(200)` would hold every slot while using no CPU, and a 2-second job would wait behind them. The earlier sandbox had no limit at all and used over 900 % CPU, partly by thrashing.

When may a queued job start?

## Decision Drivers

- Use every core the container may use, without thrashing.
- Sleeping or I/O-bound jobs should not block CPU-bound ones while resources are free.
- Stay inside the container's 2 GB memory limit: an out-of-memory kill loses every in-flight job.
- Work on cgroup v1 (Docker Desktop on WSL2) and cgroup v2 (current Linux servers).
- Cheap to measure.

## Considered Options

1. A run gate with a floor, a CPU check, a memory check, a hard cap and a burst limit.
2. A fixed concurrency (`SANDBOX_WORKER_CONCURRENCY`).
3. A fixed count ceiling derived from memory, plus a CPU check.
4. Linux CPU-pressure stall information (PSI) as the signal.

## Decision Outcome

Chosen option: **1, a run gate on measured CPU and memory**, because it starts work as long as the resources that actually limit us are free.

`ResourceAdmissionGate` (`worker/application/resource_gate.py`), behind the `AbstractAdmissionGate` port, starts a job when:

| Limit | Rule |
| --- | --- |
| Floor | Fewer than *floor* running → always start. Floor = `SANDBOX_MIN_CONCURRENT_EXECUTIONS`, or when 0, the CPUs the container may use: cgroup CPU quota, else CPU affinity, else `os.cpu_count()`. |
| CPU | Above the floor, only while host CPU busy is below `SANDBOX_CPU_ADMIT_THRESHOLD` (85 %), from `/proc/stat` deltas. |
| Memory | And only while the container's working set (usage minus inactive file cache) is below `SANDBOX_MEMORY_ADMIT_THRESHOLD` (80 %) of its cgroup limit. |
| Hard cap | Never more than `SANDBOX_MAX_CONCURRENT_EXECUTIONS` (256) running. |
| Burst | At most *floor* new starts above the floor per 0.5 s tick, because both measurements lag process start-up. |

A metric that cannot be read does not block; the gate then falls back to floor plus cap, and logs that once at startup together with the resolved values.

**Policy and mechanics are separate layers.** The rule above is a decision, so the gate lives in the worker's application layer. Reading `/proc/stat` and the cgroup files is mechanics: `HostMetrics` in `worker/infrastructure/admission/` implements the `AbstractHostMetrics` port (`floor()`, `sample()`) that the gate depends on. The policy can thus change, and be tested, without touching the files it reads; and anything that observes it (the gate sampler, [0009](0009-benchmark-checkpoints.md)) reads `snapshot()`, declared on the port, without importing infrastructure.

### Consequences

- Good, because CPU-bound flows use all cores (about 1,000–1,100 % on 12 vCPU, *estimate*) without the earlier thrashing.
- Good, because sleeping jobs no longer block fast ones until memory is actually full.
- Bad, because `/proc/stat` inside a container reads the whole host: when crew or Django are busy, the sandbox stops growing above its floor. The floor still always runs.
- Bad, because a floor equal to all host cores lets the sandbox compete with crew for CPU. If crew latency suffers, lower `SANDBOX_MIN_CONCURRENT_EXECUTIONS`.
- Bad, because the floor ignores memory: 12 jobs always start even if memory is high. Accepted; to be checked with the measured memory per job.
- Bad, because the 85 % and 80 % thresholds are tuning knobs, set from the benchmark.

### Validation

On the CPU-bound payload flow, sandbox CPU at saturation is well above the old 4–5 cores and throughput is not lower than before. The `sandbox_gate` samples show which limit held work back.

## Pros and Cons of the Options

### 1. Measured run gate

- Good, because the signals are cheap (two small file reads every 0.5 s) and available on cgroup v1 and v2.
- Bad, because measurements lag, so bursts need the burst limit.

### 2. Fixed concurrency

- Good, because it is predictable.
- Bad, because 4 leaves cores idle, and any fixed number either thrashes CPU-bound work or blocks sleeping work.

### 3. Count ceiling plus CPU check

- Bad, because a guessed number of about 30 MB per interpreter is the wrong ceiling when sleeping processes use far less. Measuring the working set gives the real limit.

### 4. PSI

- Good, because stall time is a better signal of contention than utilisation.
- Bad, because `/proc/pressure` is absent on cgroup v1 hosts, including Docker Desktop on WSL2.

## More Information

Per-job memory (about 1–3 MB per queued job, about 20–40 MB per running interpreter) is an *estimate*; measure it with `docker stats` during the benchmark.
