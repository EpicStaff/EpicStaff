# Benchmark metrics

What every number, file and label of a benchmark run means. Definitions follow the code: `benchmark/analyze.py` (all result files), `benchmark/runner.py` (run flow), `benchmark/load.py` (load controller), `benchmark/sample.py` (resource sampling). How to run the tool is in [RUNBOOK.md](RUNBOOK.md).

- [Core concepts](#core-concepts)
- [Verdict](#verdict)
- [Bottleneck](#bottleneck)
- [Capacity estimate](#capacity-estimate)
- [Labels](#labels)
- [Statistics](#statistics)
- [Session time and its parts](#session-time-and-its-parts)
- [Resource costs](#resource-costs)
- [Run folder files](#run-folder-files)
- [meta.json](#metajson)
- [Viewer](#viewer)
- [How to interpret a run](#how-to-interpret-a-run)

## Core concepts

| Term | Meaning |
|---|---|
| **Level** | A concurrency target: the number of sessions the load controller keeps **in flight at the same time**. When one ends it starts another. Not a total number of sessions. |
| **In flight** | Sessions the runner started (HTTP request sent or pending) that have not ended. Includes sessions still queued in crew. |
| **Segment** | One stretch of load inside a phase: restart of `django_app crew agent sandbox knowledge_new` (not in the smoke step or with `dev --no-restart`), one cold session, baseline sampling (`baseline_s`), one or more levels, drain, cooldown sampling (`cooldown_s`). Segment 1 of a phase is the ladder; every bisect probe is its own segment (2, 3, ...). |
| **Settle window** | The first `settle_s` seconds of a level. Sessions sent then run at the new load but are not measured. `settle_s` is raised to the smoke step's highest per-phase p95 session time, so that settle sessions have ended before measuring starts. Dev runs have no settle window. |
| **Hold window** | The `hold_s` seconds after settle. Sessions whose intended start falls in it are the level's **measured sessions**. |
| **Finish step** | After the hold, the level keeps its load until every measured session has ended, so the verdict uses true durations. It is capped by `session_timeout_s`: a measured session still running then is stopped and counted as failed `timeout`. Sessions started during the finish step have kind `finish` and are never measured. Dev runs and aborted levels have no finish step. |
| **Measured session** | A session of the level's phase, segment, level and kind whose `intended_ts` lies between the end of settle and the end of hold. Only these feed the verdict and the duration statistics of the level. |
| **Cold session** | The first session of every segment, started alone after the restart (`kind = cold`, `cold = 1`). Never in aggregates; the first one per phase is reported in `meta.json` → `phases[].cold`. It shows start-up cost (imports, caches, connections). |
| **Finish sessions** | Kind `finish`: they keep the concurrency at the level while measured sessions end. In the timeline and in `sessions.csv.gz`, never measured. |
| **Unfinished / censored** | A measured session without a known end when the level is judged. After the finish step this happens only after an interrupt or when end times are missing (fallback mode with the sessions API unreachable). Its time so far is a lower bound of its duration. `censored = True` in `sessions.csv.gz` for a session still running at the live verdict or stopped as `interrupted`. |
| **Interrupted** | Status of a session the runner stopped because the run itself was stopped (Ctrl+C, crash). Not a failure: counted in `steps.csv` → `interrupted`, not in `failed` or `error_rate`. |
| **Timeout** | Status of a session the runner stopped because it was older than `session_timeout_s`. A failure. |
| **http_error** | The start request failed (non-2xx, network error, or no `session_id` in the answer). A failure; `http_status` and `error_reason` say why. |
| **Drain** | After the last level of a segment: wait for in-flight sessions up to `session_timeout_s`, wait up to 35 s for unanswered start requests, then stop what still runs (`timeout`, or `interrupted` when the run is being stopped). |
| **Bisect** | After the first non-passing level F with last pass P: probe `(P + F) // 2` in a new segment; a pass moves P up, a fail moves F down, an `invalid` stops. At most `bisect_steps` probes; stops early when `(F - P) / P <= 10 %`. No bisect when the ladder ended on `invalid` or never failed. |
| **Fallback-control mode** | Crew wrote no `session_end` checkpoint during the cold session (a branch without checkpoints, or `CREW_LOG_LEVEL` not BENCH/DEBUG/TRACE). In-flight counts then come from `GET /api/sessions/statuses/` and end times from the sessions list (every 5 s during the finish step and after each level). Limits: `running` is always 0 (so `queued` = `inflight`), sessions cannot be timed out by id while the load runs (only at the end of the finish step), `error_rate_30s` is off, an API unreachable for 10 s or more fails the level, and there are no per-node or per-stage times. Labelled `fallback-control:<phase>`. |
| **Live vs final verdict** | The **live verdict** is computed right after the finish step from what the runner knows at that moment; it decides whether the ladder continues (`live_verdict` in `steps.csv`). The **final verdict** (`verdict`) is computed by the analysis from all collected events with the same rules and window. They differ only when late events changed the data; then the run gets the `verdict-revised` label. |
| **Case hash** | SHA-256 (first 16 hex digits) of the parsed case file without `[[variant]]` and without the phases' `graph_id`. All variants of a case share it, a server-specific graph id does not change it. It hashes what is written, not effective values: adding `factor = 2.0` where the default was used changes the hash. A copy of `server.toml` with another ladder has another hash. |
| **Graph hash** | Per phase: SHA-256 (16 hex digits) of `GET /api/graphs/<id>/` without `created_at`, `updated_at`, `save_version`. Any edit of the flow in the UI, a re-import (new node ids), or a different API answer shape on another branch changes it. |
| **Different workload** | The case hash or any phase's graph hash differs between the compared runs. `bench compare` prints `!! different workload — not comparable`; the viewer shows a red banner. The numbers are still shown; they do not measure the same thing. |
| **Provider health / `slow_provider`** | Per phase in `meta.json`: LLM call count, p50/p95 call time, errors by type, tokens, cost. `slow_provider` is true when the phase's LLM call p95 is more than twice the smoke step's LLM p95 for that phase (always false with `--no-smoke` or without LLM calls). Then latency and throughput reflect the provider, not EpicStaff. |

## Verdict

Each level (and bisect probe) gets `pass`, `fail` or `invalid` from its measured sessions. Rules in order (`judge()` in `analyze.py`):

1. **Generator lag** — if the p99 of `gen_lag_ms` over the measured sessions exceeds `abort.generator_lag_p99_ms` (500): `invalid`, reason `generator-limited: lag p99 <N> ms`. The load generator could not start sessions on time, so the server was not loaded as intended. The ladder stops; no server verdict for that level.
2. **Abort** — if the level was aborted: `fail` with the abort reason. Abort reasons (checked every 0.25 s while the level runs): a container's restart or OOM counter rose since the segment's load started (`container restart/OOM: ...`, when `abort.container_restart`); host available RAM below `abort.host_min_available_ram_pct` (5 %); error rate of 5 % or more (`abort.error_rate_30s`) among sessions that ended in the last 30 s, once at least 20 ended (not in fallback mode); in fallback mode, the sessions API failing for 10 s or more.
3. **p95 rules** — for each enabled rule (`pass.p95_e2e_s`, `pass.p95_queue_wait_s`; a rule without a value is off, and a rule with no data, e.g. no checkpoints, is skipped):
   - **proven fail**: at least 10 values (`MIN_MEASURED`) and the p95 of the ended values plus the lower bounds of unfinished sessions is above the limit. Holds even if unfinished sessions end later: they can only get slower.
   - **unknown**: otherwise, if more than 5 % (`UNFINISHED_LIMIT`) of the measured sessions are unfinished for that rule. They could be the slowest 5 %, so the p95 is not known.
   - **estimated fail**: otherwise, the p95 of the ended sessions is above the limit.

   For e2e, ended = status `end`. For queue wait, every session with a known queue wait counts; a session still queued at judging is unfinished.
4. **Too few** — fewer than 10 measured sessions ended (not censored, end before the verdict time): `fail` if a proven fail exists, otherwise `invalid` with `too few measured sessions ended (N); raise ladder.hold_s`.
5. **Error rate** — failed / measured above `pass.max_error_rate` (1 %): fail reason `error rate X% > 1.0%`.
6. Any error-rate, proven or estimated reason: `fail` (all reasons joined with `; ` in `fail_reasons`). Otherwise any unknown: `invalid`. Otherwise `pass`.

The ladder continues only on `pass`. **Max passing concurrency** is the highest level with a final `pass` (ladder or bisect). **First failing level** is the lowest `fail`.

A dev run is judged with the same function (dev case: only `max_error_rate` applies, as `dev.toml` has no `[pass]`), but its verdict is not a capacity statement; the Verdicts tab does not show it (the Curves point is still filled or hollow by it).

## Bottleneck

Computed for every failing level from the samples in its measured window; the phase's headline bottleneck is the one of its lowest failing level. First match wins:

| # | Rule | Text |
|---|---|---|
| 1 | A container's restart or OOM counter rose during the level | `container restart/OOM: <containers>` |
| 2 | Lowest host available RAM % in the window below the RAM guard (5 %) | `host RAM (available N%)` |
| 3 | Mean host CPU in the window ≥ 90 % | `host CPU N%` |
| 4 | A container's mean CPU ≥ 90 % of its CPU limit (only containers with a limit; none today) | `container CPU limit: <containers>` |
| 5 | `CREW_MAX_CONCURRENT_SESSIONS` known, mean `running` ≥ 95 % of it and mean `queued` > 0 | `crew slots full (N) with sessions queued` |
| 6 | p95 of `agent_queue_s` (sessions with agent calls) more than double the previous level's and above 1 s | `agent queue growing (p95 N s)` |
| 7 | Peak Postgres connections ≥ 90 % of `max_connections` | `Postgres connections at N% of max` |
| 8 | None of the above | `no saturated resource found` |

"No saturated resource found" means the failure came from latency or errors without one of these resources at its limit: look at the Time breakdown and Nodes tabs and at `error_reason` in `sessions.csv.gz`.

## Capacity estimate

`meta.json` → `phases[].capacity_estimate`, computed at the highest passing level (needs its CPU-seconds per session and p50 e2e). Each bound is a concurrency; the estimate is the smallest, and `limit` names it.

| Bound | Formula | Meaning |
|---|---|---|
| `cpu` | `vCPU × p50 e2e / CPU-seconds per session` | Little's law: the host can finish at most `vCPU / CPU-s per session` sessions per second; times the session duration gives the concurrency the CPUs carry. `vCPU` is the CPU count of the host running the tool. |
| `ram` | `mean available host MB during the phase's baselines / MB per concurrent session (headline)` | How many concurrent sessions fit into the RAM that was free before load. Needs `/proc` (Linux) and a positive headline MB slope. |
| `CREW_MAX_CONCURRENT_SESSIONS` | the value in effect | Crew's slot cap. `server.toml` sets 100000, so it is not limiting there. |
| `AGENT_MAX_CONCURRENT_RUNS` | the value in effect | Only when the phase made LLM calls. |

It is an extrapolation from one level, assuming cost per session stays linear. Trust it less the further it is above the measured max passing concurrency. On Docker Desktop `vCPU` is the Windows/macOS host's count, not the VM's, and there is no `ram` bound.

## Labels

`meta.json` → `labels`. Every label the code can emit:

| Label | Meaning |
|---|---|
| `interrupted` | Ctrl+C during a phase. Remaining phases and variants were skipped. |
| `crashed:<ExceptionType>` | A phase crashed; what was measured until then is analyzed. |
| `fallback-control:<phase>` | That phase ran in fallback-control mode. |
| `dirty-tree` | The measured checkout had uncommitted changes to tracked files (`git status --porcelain --untracked-files=no`). For a `--ref` run, the temporary worktree is checked, so it is normally absent. |
| `build-unverified` | `--no-build`: the images were not rebuilt; they may not match the recorded sha. |
| `verdict-revised:<phase>:<level>[,<phase>:<level>...]` | One label listing every level whose final verdict differs from its live verdict. |

## Statistics

| Statistic | Meaning here | Read it for |
|---|---|---|
| `p50` | Median: half the sessions were faster. Linear interpolation between ranks. | Typical cost; the most stable number for comparing branches. |
| `p90` | 90 % were faster. | Tail trend with less noise than p95/p99. |
| `p95` | 95 % were faster. | The pass rules use it. What most users see as "slow". |
| `p99` | 99 % were faster. With fewer than ~100 sessions it is close to `max`. | Stragglers; only meaningful with many sessions. |
| `max` | The slowest session. | Outliers, timeouts. One session; never compare runs on it. |
| `mean` | Arithmetic mean. | Additive costs (time breakdown sums to the mean e2e); sensitive to outliers. |

Duration statistics in `steps.csv` are over the level's measured sessions with status `end` only; failed and unfinished sessions are excluded (they affect the verdict through the rules above).

| Metric | Definition |
|---|---|
| `throughput_per_min` | Sessions of the phase that ended with status `end` between the end of settle and the end of hold, divided by that window's length, × 60. It counts every session of the phase ending in the window (including ones started before it), so it is the server's completion rate at that load. For a dev run the window is the whole run including the ramp-down. |
| `error_rate` | `failed / sent` over measured sessions. `failed` = ended with any status other than `end`, excluding `interrupted` and unfinished sessions. |
| `gen_lag_ms` | `sent_ts − intended_ts` of one session: how late the load generator actually sent it (64 sender threads, 30 s HTTP timeout, on the same host). `gen_lag_p99_ms` in `steps.csv` is the p99 over measured sessions. |
| `runner_cpu_pct` | CPU used by the benchmark process itself between two samples, % of one core (can exceed 100). High values with a rising generator lag mean the tool, not the server, is the limit. |

## Session time and its parts

Per session in `sessions.csv.gz`. Timestamps: `sent_ts` is taken by the runner just before the start request; the others come from BENCH checkpoint lines (first occurrence per service and checkpoint; `request_received` carries the real arrival time). All clocks are the host's clock; on Docker Desktop the VM clock can be slightly off, which shifts `dispatch_s`.

| Column | From → to | What it contains |
|---|---|---|
| `e2e_s` | `sent_ts` → crew `session_end` (or the runner's end time for `timeout`, `http_error`, `interrupted`, or the API's `finished_at` in fallback mode) | Whole session as a client sees it. |
| `dispatch_s` | `sent_ts` → crew `received` | HTTP request, Django creating and publishing the session, Redis delivery to crew. |
| `queue_wait_s` | crew `received` → crew `slot_acquired` | Waiting for a crew slot (`CREW_MAX_CONCURRENT_SESSIONS`). |
| `run_s` | crew `slot_acquired` → session end | Executing the flow. |
| `llm_s` | Σ agent `llm_start` → `llm_end`, paired by correlation id | Time inside LLM provider calls. Summed, so parallel calls can exceed wall time. |
| `llm_calls`, `tokens`, `cost_usd` | from `llm_end` | Call count, total tokens, cost as reported by the agent. |
| `agent_queue_s` | Σ crew `agent_dispatched` → agent `request_consumed` | Waiting for an agent worker to pick up a request (Redis stream backlog). |
| `python_s` | Σ sandbox `exec_start` → `exec_end`, paired by execution id | Time executing Python node code in the sandbox. |
| `other_s` | `max(0, run_s − llm_s − python_s − agent_queue_s)` | Everything else inside the run: crew orchestration, node bookkeeping, Redis hops, RAG search, agent work outside LLM calls. Clamped at 0 when parallel spans overlap. |
| `platform_overhead_s` | `e2e_s − llm_s` | Everything that is not the LLM provider. The number to compare branches with when LLM latency is noisy. |

`e2e_s = dispatch_s + queue_wait_s + run_s`, and `run_s ≈ llm_s + python_s + agent_queue_s + other_s` when nothing runs in parallel. Without checkpoints (fallback mode) only `e2e_s` and `platform_overhead_s` (= `e2e_s`) are filled.

## Resource costs

Resources are sampled every 2 s. Linux: per-container CPU and memory from the host's cgroup v2 files (`cpu.stat`, `memory.current`, `memory.events`), host CPU, RAM and load from `/proc`. Docker Desktop: per-container values from `docker stats`, no host values. `memory.current` includes the page cache, `docker stats` does not, so memory numbers from a laptop and a Linux server differ by design.

| Metric | Definition |
|---|---|
| `cpu_pct` (container) | CPU use between two samples, % of one core (100 = one full core). |
| `host_cpu_pct` | Busy share of all host cores (0–100). |
| CPU-seconds per session (`cpu_s_per_session` in `steps.csv`) | For every sampled container (all running containers of the stack, including Postgres, Redis, OpenSearch, nginx): time-weighted mean `cpu_pct` over the window between end of settle and end of hold × window length = CPU-seconds; the sum over containers divided by the sessions of the phase that ended with `end` in that window. Includes idle background CPU, so it reads high at low load. `containers.csv` has the same per container. |
| MB per concurrent session, **headline** (`mb_per_concurrent_total` in `meta.json`, Verdicts tab) | Per container: least-squares line of the container's memory (MB) against the `running` session count over the first segment's load (samples from the first level to the last), giving a slope (MB per running session), and `r²`. The headline is the sum of the slopes of containers with `r² ≥ 0.5`. A weak fit means that container's memory does not follow the session count (noise, a cache, a stepwise worker spawn); it stays in `container_phases.csv` but out of the headline. |
| `baseline_mb` | Mean container memory during the phase's first baseline window (before load). The intercept the slope is added to. |
| `r²` | Share of the memory variance the line explains (1 = perfect line, 0 = none; empty when memory or `running` did not vary). |
| MB per concurrent session, **per level** (`mb_per_concurrent` in `steps.csv`, `bench compare`, Curves tab) | A different number: Σ over containers of (mean memory in the level's window − `baseline_mb`) / mean `running` in the window. It includes fixed growth (warmed caches, spawned workers), so it reads high at low levels and falls with load. Use it for trends across levels; use the headline slope for the cost of one session. |
| `retained_mb_after_cooldown` | Mean container memory in the last 60 s of the phase's last cooldown minus `baseline_mb`. Memory not returned after the load ended: caches, fragmentation, or a leak. Compare it across runs; a value growing with the number of sessions is suspicious. |

## Run folder files

Folder name: `<YYYY-MM-DD_HHMM>_<host>_<ref>_<sha7>_<case>-<variant>` under `benchmark/results/` (UTC time). Schema version 1. Smoke-step sessions are not in any file; only their summary is in `meta.json` → `smoke`.

| File | One row per | Pushed |
|---|---|---|
| `meta.json` | run | yes |
| `case.toml` | — the case file used (values of `[env]` / variant `env` keys outside the allowlist replaced by `<redacted>`; then comments are lost) | yes |
| `sessions.csv.gz` | session (all kinds except smoke) | yes |
| `steps.csv` | level (ladder, bisect, dev) | yes |
| `containers.csv` | level × container | yes |
| `container_phases.csv` | phase × container | yes |
| `nodes.csv` | level × node | yes |
| `timeline.csv` | 2-second sample | yes |
| `container_timeline.csv` | 2-second sample × container | yes |
| `events_sample.csv` | checkpoint event of a sampled session | yes |
| `events_full.csv.gz` | every checkpoint event | no (size) |

### `sessions.csv.gz`

| Column | Meaning |
|---|---|
| `phase`, `segment`, `level` | Where the session was started (`level` 0 for cold sessions). |
| `kind` | `ladder`, `bisect`, `dev`, `cold`, or `finish` (started during a finish step, never measured). |
| `cold` | 1 for the cold session of a segment. |
| `session_id` | EpicStaff session id (empty when the start request failed). |
| `intended_ts` | When the controller decided to start it (epoch seconds). Decides whether it is measured. |
| `sent_ts` | When the request was actually sent. |
| `gen_lag_ms` | `sent_ts − intended_ts` in ms. |
| `api_ms` | Duration of the start request. |
| `http_status` | HTTP status of the start request. |
| `arrival_ts` | Django `request_received` (real arrival time). |
| `received_ts` | Crew `received`. |
| `slot_ts` | Crew `slot_acquired`. |
| `end_ts` | Session end (see `e2e_s`). |
| `status` | Crew's final status (`end`, `error`, `stop`, `cancelled`), or the runner's `http_error`, `timeout`, `interrupted`. Empty: no end known. |
| `censored` | True when the duration is only a lower bound (`interrupted`). |
| `error_reason` | For a status other than `end`: the request error or crew's `reason`, at most 300 characters. |
| `e2e_s` … `platform_overhead_s` | See [Session time and its parts](#session-time-and-its-parts). |

### `steps.csv`

| Column | Meaning |
|---|---|
| `phase`, `segment`, `level`, `kind` | The level (`kind`: `ladder`, `bisect`, `dev`). |
| `target` | Concurrency target (= `level`). |
| `inflight_mean` | Mean in-flight sessions in the window (should be close to `target`; lower means the generator or the API could not keep up). |
| `running_mean` | Mean sessions crew was executing (slot acquired, not ended). 0 in fallback mode. |
| `steady_s` | Window length between end of settle and end of hold, seconds. |
| `sent` | Measured sessions. |
| `completed` | Measured sessions with status `end`. |
| `failed` | Measured sessions with another final status (not `interrupted`, not unfinished). |
| `interrupted` | Measured sessions stopped by an interrupt. |
| `throughput_per_min` | See [Statistics](#statistics). |
| `error_rate` | `failed / sent`. |
| `e2e_s_*`, `queue_wait_s_*`, `run_s_*`, `llm_s_*`, `platform_overhead_s_*` | `p50`, `p90`, `p95`, `p99`, `max`, `mean` of that duration over completed measured sessions. |
| `cpu_s_per_session` | See [Resource costs](#resource-costs). |
| `mb_per_concurrent` | Per-level MB per concurrent session (not the headline slope). |
| `gen_lag_p99_ms` | p99 generator lag of the measured sessions. |
| `verdict` | Final verdict: `pass`, `fail`, `invalid`. |
| `live_verdict` | Verdict the runner decided on during the run. |
| `fail_reasons` | Reasons for `fail` or `invalid`, joined with `; `. |
| `bottleneck` | For `fail` levels; see [Bottleneck](#bottleneck). |

### `containers.csv`

| Column | Meaning |
|---|---|
| `phase`, `segment`, `level`, `kind` | The level. |
| `container` | Container name. |
| `cpu_s` | CPU-seconds the container used in the level's window. |
| `cpu_s_per_session` | `cpu_s` / sessions of the phase that ended `end` in the window. |
| `cpu_pct_mean`, `cpu_pct_max` | Mean and highest sampled CPU, % of one core. |
| `mem_mean_mb`, `mem_peak_mb` | Mean and highest sampled memory. Peak is the highest 2-second sample, not a true peak. |
| `restarts`, `oom_kills` | Rise of the container's restart count and OOM-kill counter during the window. |

### `container_phases.csv`

| Column | Meaning |
|---|---|
| `phase`, `container` | |
| `baseline_mb` | Mean memory before load (first baseline window of the phase). |
| `mb_per_concurrent` | Slope of memory against running sessions over the first segment's load. |
| `r2` | Fit quality; `< 0.5` is excluded from the headline. |
| `retained_mb_after_cooldown` | Memory left above baseline at the end of the last cooldown. |

### `nodes.csv`

From `node_start` / `node_end` checkpoints of the level's measured sessions (all statuses).

| Column | Meaning |
|---|---|
| `phase`, `segment`, `level`, `kind` | The level. |
| `node_name`, `node_type` | Node as named in the flow. |
| `count` | Node executions. |
| `p50_s`, `p95_s`, `mean_s`, `max_s` | Node execution time. |
| `error_count` | Executions whose `node_end` reported `ok = false`. |

### `timeline.csv`

| Column | Meaning |
|---|---|
| `ts`, `rel_s` | Sample time (epoch) and seconds since the segment's sampler started. |
| `phase`, `segment`, `level`, `target` | Context; `level`/`target` 0 outside levels (cold session, baseline, drain, cooldown). |
| `inflight` | Sessions in flight. |
| `running` | Sessions executing in crew. |
| `queued` | `inflight − running` (waiting for a slot, or not yet received by crew). |
| `completed`, `failed` | Cumulative counts in the segment (`failed` excludes `interrupted`). |
| `host_cpu_pct` | Host CPU, all cores. |
| `host_mem_avail_mb`, `host_mem_avail_pct` | Host `MemAvailable`. |
| `load1` | Host 1-minute load average. |
| `pg_connections`, `pg_max_connections` | Rows in `pg_stat_activity` (includes Postgres background processes) and `max_connections`. |
| `redis_used_mb` | Redis `used_memory`. |
| `runner_cpu_pct` | The benchmark process's CPU, % of one core. |

### `container_timeline.csv`

`ts`, `rel_s`, `phase`, `segment`, `level`, `container`, `cpu_pct` (% of one core), `mem_mb`, `restarts` (Docker restart count), `oom_kills` (cgroup OOM-kill counter on Linux; Docker's 0/1 OOMKilled flag otherwise).

### `events_sample.csv` and `events_full.csv.gz`

One row per checkpoint: `session_id`, `service` (`django_app`, `crew`, `agent`, `sandbox`), `checkpoint`, `ts`, `node_name`, `extra_json` (every other field of the line, e.g. `status`, `correlation_id`, `execution_id`, `model`, token counts, `ok`). The sample keeps all events of: the 100 fastest, the 100 around the median and the 100 slowest sessions with status `end` (cold excluded), the first 150 failed sessions, and the cold sessions. The full file has every event and stays on the machine. Checkpoints per service are listed in `benchmark/README.md` → Product side.

## meta.json

| Field | Meaning |
|---|---|
| `schema_version`, `tool_version` | File schema (1) and tool version. |
| `run_id` | The folder name. |
| `created_at`, `analyzed_at` | Run start and analysis time (UTC). |
| `note` | `--note`. |
| `kind` | `capacity` or `dev`. |
| `org_id`, `org_source` | Organization used; `env` (BENCH_ORG_ID) or `default` (the stack's default organization). |
| `case` | `name`, `hash` (case hash), `variant`, `overrides` (case and variant env; values outside the allowlist shown as `<set>`). |
| `git` | `ref`, `sha`, `dirty`, `built` (false with `--no-build`). For `--ref` runs the ref given. |
| `images` | Image id per container (shortened). |
| `host` | `hostname`, `vcpu`, `ram_mb`, `kernel`, `os`, `docker` (server version), `virtualization`. |
| `container_limits` | Per container `cpus` and `mem_mb` (null = no limit). |
| `env` | Allowlisted settings in effect: `*_LOG_LEVEL`, `CREW_MAX_CONCURRENT_SESSIONS`, `AGENT_MAX_CONCURRENT_RUNS`, `*_SGI_WORKERS`, `KNOWLEDGE_MAX_PROCESS_WORKERS`, `*_CPUS`, `*_MEM_LIMIT`. Nothing else from `.env` is stored. |
| `labels` | See [Labels](#labels). |
| `smoke` | `ran`, `passed`, `details`, `e2e_p95_s` and `llm_p95_s` per phase. |
| `events_unattributed` | Checkpoint lines that could not be matched to a session (should be near 0). |
| `phases[]` | Per phase: `name`, `graph_id`, `graph_name`, `graph_hash` (or `error`), `variables_hash`, `verdict`, `provider_health`, `capacity_estimate`, `cold`. |
| `phases[].verdict` (capacity) | `max_pass_concurrency`, `first_fail_level`, and at the highest passing level `throughput_per_min_at_max`, `p50_e2e_s_at_max`, `p95_e2e_s_at_max`, `p95_platform_overhead_s_at_max`, `cpu_s_per_session_at_max`; `mb_per_concurrent_total` (headline slope); `bottleneck` and `fail_reasons` of the lowest failing level. |
| `phases[].verdict` (dev) | `level`, `throughput_per_min`, `p50_e2e_s`, `p95_e2e_s`, `cpu_s_per_session`, plus `mb_per_concurrent_total`. |
| `phases[].provider_health` | `llm_calls`, `llm_p50_s`, `llm_p95_s`, `errors` (count by error type), `tokens`, `cost_usd`, `slow_provider`. Over all sessions of the phase. |
| `phases[].capacity_estimate` | `bounds`, `limit`, `concurrency`; null when there is no passing level. |
| `phases[].cold` | `e2e_s`, `queue_wait_s`, `run_s`, `status` of the phase's first cold session. |

## Viewer

`benchmark/viewer.html`, copied to the results repository as `index.html`.

**Run list.** `#N` = number in the results repository, `L1`, `L2`, ... with a `local` chip = folders opened from disk. **Result** column: capacity runs show max passing concurrency per phase, dev runs p95 e2e. Filters by kind, case, ref, host and free text (note, label, sha, folder). Tick runs to select; the first selected is the baseline; the **Baseline** radio changes it.

**What's different.** With two or more runs selected: every field that differs among `git.ref`, `git.sha`, `git.dirty`, `case.hash`, `case.variant`, `case.overrides`, each `env.*`, `host.hostname`, `host.vcpu`, `host.ram_mb`, `labels`, and per phase `graph_hash` and `slow_provider`. The red banner **Different workload — not comparable** appears when the case hash or a phase's graph hash differs.

**Δ %.** `(value − baseline) / baseline`, only between runs of the same kind (capacity with capacity, dev with dev). Green = better, red = worse (higher is better for concurrency and throughput, lower for latency, CPU and memory), grey = within 0.05 % or no direction. No % when the baseline value is 0 or negative, or the value itself is negative (a noisy slope).

| Tab | Shows |
|---|---|
| **Verdicts** | Per phase, one row per run. Capacity: max passing concurrency, first failing level, throughput, p95 e2e, p95 platform overhead and CPU-s/session at the highest passing level, headline MB per concurrent session, capacity estimate with its limit (bounds in the tooltip), bottleneck and fail reasons. Dev: concurrency, throughput, p50 and p95 e2e, CPU-s/session. ⚠ marks `slow_provider`. |
| **Curves** | One chart per phase: a metric from `steps.csv` against concurrency level (ladder, bisect and dev rows), one line per run. Metrics: throughput, p50/p95 e2e, p95 queue wait, p95 platform overhead, error rate, CPU-s per session, per-level MB per concurrent session. Filled point = pass, hollow = fail, cross = invalid. Log scale for the level axis is optional. |
| **Time breakdown** | Stacked bars of mean seconds per completed session at each run's headline level (capacity: highest passing; dev: its level): dispatch, queue wait, agent queue, LLM, Python, other; mean e2e in the table. Uses that level's sessions with status `end`, cold and finish sessions excluded. |
| **Timeline** | One run (pick it with **Run**). Sessions chart: target, in flight, running, queued over time, with host CPU % or the top-5 containers' CPU % on the right axis; vertical lines where each measured level starts (green pass, red fail, grey invalid). Memory per container (the 5 with the highest peak). Postgres connections vs max. Redis memory. The x axis is `rel_s`, which restarts at 0 in every segment, so with bisect probes or two phases the segments are drawn over each other. |
| **Nodes** | Per node at each run's headline level: count, p50, p95, errors, Δ p50 against the same node in the baseline. |
| **Containers** | Per container: baseline MB, MB per concurrent session (slope) with Δ, r², retained MB after cooldown, and at the headline level CPU-s/session and peak memory with Δ. |
| **Waterfall** | One session from `events_sample.csv`: fastest, median, slowest (among sampled sessions with status `end`, whole run), a failed one, or the cold one. Bars from Django receiving the request: session, queue, each node, each LLM call, each Python execution. |

A run with a `schema_version` other than 1 is refused with a message.

## How to interpret a run

1. **Check that the run is valid.** Labels: `interrupted`, `crashed:*`, `build-unverified`, `dirty-tree`, `fallback-control:*` each limit what you can conclude. The smoke step passed (`meta.json` → `smoke.passed`). No "different workload" banner when comparing.
2. **Find capacity.** Max passing concurrency per phase is the measured capacity under the pass rules; the true limit lies between it and the first failing level (bisect narrows that to about 10 %). If the ladder stopped on `invalid`, there is no capacity statement: `generator-limited` means the load tool was the limit (lower `start`, or run the generator elsewhere in future); `too few measured sessions ended` means `hold_s` is too short for the session duration.
3. **Read why it failed.** `fail_reasons` says which rule broke (p95 e2e, p95 queue wait, error rate, or an abort). `bottleneck` says which resource was saturated. Fix in this order:
   - `container restart/OOM` or `host RAM`: memory. Look at the headline MB per concurrent session and the Containers tab for the container with the largest slope; `retained_mb_after_cooldown` growing hints at a leak.
   - `host CPU`: CPU-seconds per session and the per-container `cpu_s_per_session` show who burns it.
   - `crew slots full`: the configured cap, not the hardware (raise `CREW_MAX_CONCURRENT_SESSIONS` for the test).
   - `agent queue growing`: too few agent workers for the LLM work.
   - `Postgres connections`: the connection limit (RUNBOOK B11) or connection usage per session.
   - `no saturated resource found`: latency grew without a saturated resource. Check the Time breakdown (which part grew between levels), Nodes, and `error_reason` of failed sessions.
4. **Compare branches on stable numbers.** Prefer p50 e2e and p95 platform overhead, the payload phase (no LLM), CPU-seconds per session and the headline MB slope. Throughput at different levels is not comparable; compare at the same level or compare max passing concurrency.
5. **Know what is noise.** One run per configuration, no repeats: differences under about 5–10 % in latency are within run-to-run noise, more on a laptop. `max` and `p99` with few sessions are single sessions. A slope with `r² < 0.5` is noise. `slow_provider` means LLM latency moved, not EpicStaff. The capacity estimate is an extrapolation; the measured max passing concurrency is the fact.
