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
| **Finish step** | After the hold, the level keeps its load until every measured session has ended, so the verdict uses true durations. It is capped by `session_timeout_s`: a measured session still running then is stopped and counted as failed `timeout`. Sessions started during the finish step have kind `finish` and are never measured. When the level measured no session, it waits for the sessions of its settle window instead (see Verdict, rule 4). Dev runs and aborted levels have no finish step. |
| **Measured session** | A session of the level's phase, segment, level and kind whose `intended_ts` lies between the end of settle and the end of hold. Only these feed the verdict and the duration statistics of the level. |
| **Cold session** | The first session of every segment, started alone after the restart (`kind = cold`, `cold = 1`). Never in aggregates; the first one per phase is reported in `meta.json` → `phases[].cold`. It shows start-up cost (imports, caches, connections). |
| **Finish sessions** | Kind `finish`: they keep the concurrency at the level while measured sessions end. In the timeline and in `sessions.csv.gz`, never measured. |
| **Unfinished / censored** | A measured session without a known end when the level is judged. After the finish step this happens only after an interrupt or when end times are missing (fallback mode with the sessions API unreachable). Its time so far is a lower bound of its duration. `censored = True` in `sessions.csv.gz` for a session still running at the live verdict or stopped as `interrupted`. |
| **Interrupted** | Status of a session the runner stopped because the run itself was stopped (Ctrl+C, crash). Not a failure: counted in `steps.csv` → `interrupted`, not in `failed` or `error_rate`. |
| **Timeout** | Status of a session the runner stopped because it was older than `session_timeout_s`. A failure. |
| **http_error** | The start request failed (non-2xx, network error, or no `session_id` in the answer). A failure; `http_status` and `error_reason` say why. |
| **Drain** | After the last level of a segment: wait for in-flight sessions up to `session_timeout_s`, stopping each one as `timeout` as soon as it is `session_timeout_s` old (counted from its `sent_ts`, as during a level), wait up to 35 s for unanswered start requests, then stop what still runs (`timeout`, or `interrupted` when the run is being stopped). |
| **Bisect** | After the first non-passing level F with last pass P: probe `(P + F) // 2` in a new segment; a pass moves P up, a fail moves F down, an `invalid` stops. At most `bisect_steps` probes; stops early when `(F - P) / P <= 10 %`. No bisect when the ladder ended on `invalid` or never failed. |
| **Fallback-control mode** | Crew wrote no `session_end` checkpoint during the cold session (a branch without checkpoints, or `CREW_LOG_LEVEL` not BENCH/DEBUG/TRACE). In-flight counts then come from `GET /api/sessions/statuses/` and end times from the sessions list (every 5 s during the finish step and after each level). Limits: `running` is always 0 (so `queued` = `inflight`), sessions cannot be timed out by id while the load runs (only at the end of the finish step), `error_rate_30s` is off, an API unreachable for 10 s or more fails the level, and there are no per-node or per-stage times. Labelled `fallback-control:<phase>`. |
| **Live vs final verdict** | The **live verdict** is computed right after the finish step from what the runner knows at that moment; it decides whether the ladder continues (`live_verdict` in `steps.csv`). The **final verdict** (`verdict`) is computed by the analysis from all collected events with the same rules and window. They differ only when late events changed the data; then the run gets the `verdict-revised` label. |
| **Case hash** | SHA-256 (first 16 hex digits) of the parsed case file without `[[variant]]` and without the phases' `graph_id`. All variants of a case share it, a server-specific graph id does not change it. It hashes what is written, not effective values: adding `factor = 2.0` where the default was used changes the hash. A copy of `server.toml` with another ladder has another hash. |
| **Graph hash** | Per phase: SHA-256 (16 hex digits) of `GET /api/graphs/<id>/` without `created_at`, `updated_at`, `save_version`. Any edit of the flow in the UI, a re-import (new node ids), or a different API answer shape on another branch changes it. |
| **Different workload** | The case hash or any phase's graph hash differs between the compared runs. `bench compare` prints `!! different workload — not comparable`; the viewer shows a red banner. The numbers are still shown; they do not measure the same thing. |
| **Provider health / `slow_provider`** | Per phase in `meta.json`: LLM call count, p50/p95 call time, errors by type, tokens, cost. `slow_provider` is true when the phase's LLM call p95 is more than twice (`SLOW_LLM_FACTOR`) the smoke step's LLM p95 for that phase (always false with `--no-smoke` or without LLM calls), unless every level whose LLM calls were that slow ran with the host CPU at 90 % or more: then the calls most likely waited for CPU on this host, and the finding `llm_slowed_by_host` says so instead. Then latency and throughput reflect the provider, not EpicStaff. |

## Verdict

Each level (and bisect probe) gets `pass`, `fail` or `invalid` from its measured sessions. Rules in order (`judge_level()` and `judge()` in `analyze.py`):

1. **Generator lag** — if the p99 of `gen_lag_ms` over the measured sessions exceeds `abort.generator_lag_p99_ms` (500): `invalid`, reason `generator-limited: lag p99 <N> ms`. The load generator could not start sessions on time, so the server was not loaded as intended. The ladder stops; no server verdict for that level.
2. **Abort** — if the level was aborted: `fail` with the abort reason. Abort reasons (checked every 0.25 s while the level runs): a container's restart or OOM counter rose since the segment's load started (`container restart/OOM: ...`, when `abort.container_restart`); host available RAM below `abort.host_min_available_ram_pct` (5 %); error rate of 5 % or more (`abort.error_rate_30s`) among sessions that ended in the last 30 s, once at least 20 ended (not in fallback mode); in fallback mode, the sessions API failing for 10 s or more.
3. **p95 rules** — for each enabled rule (`pass.p95_e2e_s`, `pass.p95_queue_wait_s`; a rule without a value is off, and a rule with no data, e.g. no checkpoints, is skipped):
   - **proven fail**: at least 10 values (`MIN_MEASURED`) and the p95 of the ended values plus the lower bounds of unfinished sessions is above the limit. Holds even if unfinished sessions end later: they can only get slower.
   - **unknown**: otherwise, if more than 5 % (`UNFINISHED_LIMIT`) of the measured sessions are unfinished for that rule. They could be the slowest 5 %, so the p95 is not known.
   - **estimated fail**: otherwise, the p95 of the ended sessions is above the limit.

   For e2e, ended = status `end`. For queue wait, every session with a known queue wait counts; a session still queued at judging is unfinished.
4. **Stalled in settle** — the level measured no session at all, and sessions it sent in its settle window ended as `timeout` by the verdict time: `fail`, reason `N settle sessions timed out (last checkpoint: <service> <checkpoint> (count))`. This is the stack stalling before a session could be measured: nothing ended, so the hold started no new session. Without this rule the level would be `invalid` ("raise ladder.hold_s"), which blames the hold and stops the bisect. To make the live and the final verdict agree, the runner's finish step waits for these settle sessions (up to `session_timeout_s`) when the level measured none (`judge_level` in `analyze.py`, `_finish_measured` in `runner.py`).
5. **Too few** — fewer than 10 measured sessions ended (not censored, end before the verdict time): `fail` if a proven fail exists, otherwise `invalid` with `too few measured sessions ended (N); raise ladder.hold_s`.
6. **Error rate** — failed / measured above `pass.max_error_rate` (1 %): fail reason `error rate X% > 1.0%`.
7. Any error-rate, proven or estimated reason: `fail` (all reasons joined with `; ` in `fail_reasons`). Otherwise any unknown: `invalid`. Otherwise `pass`.

The ladder continues only on `pass`. **Max passing concurrency** is the highest level with a final `pass` (ladder or bisect). **First failing level** is the lowest `fail`.

A dev run is judged with the same function (dev case: only `max_error_rate` applies, as `dev.toml` has no `[pass]`), but its verdict is not a capacity statement; the Verdicts tab does not show it (the Curves point is still filled or hollow by it).

## Bottleneck

Computed for every failing level from the samples in its measured window and the sessions the level started; the phase's headline bottleneck is the one of its lowest failing level. First match wins:

| # | Rule | Text |
|---|---|---|
| 1 | A container's restart or OOM counter rose during the level | `container restart/OOM: <containers>` |
| 1a | The level failed on the error rate (rule or abort) or on the settle-timeout rule, and at least half (`HTTP_ERROR_MAJORITY`) of its failed sessions are failed start requests (`http_error`). Its failed sessions are those of the level (settle, measured and finish) that ended by the verdict time, plus measured start requests that failed after it (sent before an abort, they time out up to the API client's 30 s later); a session the drain stopped after the verdict, as `timeout`, does not count | `N start requests failed (<most common error>; API p95 S s)`: the error up to its first colon (`TimeoutError`, `HTTP 502`) and the p95 start-request time of every session the level started |
| 1b | Otherwise, the same failure rules, and the same sessions (ended by the verdict time, or measured failed start requests) include some that ended as `timeout`: a finish session or a measured session stopped later, in the drain, does not count | `N timed out; last checkpoint: <service> <checkpoint> (count)[, <second most common> (count)]`: the last checkpoint each reached before the runner stopped it (crew's later `session_end` answering the stop is ignored; `no checkpoint` when it logged none) |
| 2 | Lowest host available RAM % in the window below the RAM guard (5 %) | `host RAM (available N%)` |
| 3 | A one-process service at its cores: mean CPU in the window ≥ 85 % (`PROCESS_SATURATED_SHARE`) of 100 % per process. crew and agent run one Python process; django_app runs `DJANGO_SGI_WORKERS` (from `meta.json` → `env`; 1 when it is not set; when it is set but not a whole number above 0 the worker count is unknown and django_app is not judged). The dev profile's `DJANGO_SGI_RELOAD=1` makes `src/django_app/entrypoint.sh` run one worker whatever `DJANGO_SGI_WORKERS` says; the rule reads the variable, so do not judge django_app on a dev-profile run | `crew at one core (one process, 86 % CPU)`, `django_app at its 1 worker (124 % CPU)`; with `; host CPU N%` appended when the host is also at ≥ 90 % |
| 4 | Mean host CPU in the window ≥ 90 % (`HOST_CPU_SATURATED_PCT`) | `host CPU N%` |
| 5 | A container's mean CPU ≥ 90 % of its CPU limit (only containers with a limit; none today) | `container CPU limit: <containers>` |
| 6 | `CREW_MAX_CONCURRENT_SESSIONS` known, mean `running` ≥ 95 % of it and mean `queued` > 0 | `crew slots full (N) with sessions queued` |
| 7 | p95 of `agent_queue_s` (sessions with agent calls) more than double the previous level's and above 1 s | `agent queue growing (p95 N s)` |
| 8 | Peak Postgres connections ≥ 90 % of `max_connections` | `Postgres connections at N% of max` |
| 9 | None of the above | `no saturated resource found` |

When failed sessions explain the failure, rules 1a/1b come before the resource rules because they say what failed: which start requests, or where the stuck sessions are (`crew sandbox_dispatched` means the code was handed to the sandbox and never started there). A one-process service at its cores is appended (`16 start requests failed (TimeoutError; API p95 27.1 s); django_app at its 1 worker (124 % CPU)`), as it is usually why. The runner prints the same failure text on its live verdict line of a failed level.

Rule 3 comes before host CPU because a Python process cannot use more than one core: such a service caps throughput even while the host has idle cores, and adding host CPU would not help. When the host is saturated as well, both are named in one text. It comes after host RAM, which is the more urgent limit (the RAM guard aborts the run).

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
| `gen_lag_ms` | `sent_ts − intended_ts` of one session: how late the load generator actually sent it (30 s HTTP timeout, on the same host). The controller keeps at least as many sender threads as the level's target (64 at least): a start request blocks its sender until the API answers, and pending requests count as in flight, so a slow API never queues a send behind the senders and cannot show up as generator lag. `gen_lag_p99_ms` in `steps.csv` is the p99 over measured sessions. |
| `runner_cpu_pct` | CPU used by the benchmark process itself between two samples, % of one core (can exceed 100). High values with a rising generator lag mean the tool, not the server, is the limit. |

## Session time and its parts

Per session in `sessions.csv.gz`. Timestamps: `sent_ts` is taken by the runner just before the start request; the others come from BENCH checkpoint lines (first occurrence per service and checkpoint; `request_received` carries the real arrival time). All clocks are the host's clock; on Docker Desktop the VM clock can be slightly off, which shifts `dispatch_s`.

| Column | From → to | What it contains |
|---|---|---|
| `e2e_s` | `sent_ts` → crew `session_end` (or the runner's end time for `timeout`, `http_error`, `interrupted`, or the API's `finished_at` in fallback mode) | Whole session as a client sees it. For a session the runner ended, crew's `session_end` only answers the runner's stop (it can come much later, e.g. at the next stack restart) and is ignored. |
| `dispatch_s` | `sent_ts` → crew `received` | HTTP request, Django creating and publishing the session, Redis delivery to crew. |
| `queue_wait_s` | crew `received` → crew `slot_acquired` | Waiting for a crew slot (`CREW_MAX_CONCURRENT_SESSIONS`). |
| `run_s` | crew `slot_acquired` → session end | Executing the flow. |
| `llm_s` | Σ agent `llm_start` → `llm_end`, paired by correlation id | Time inside LLM provider calls. Summed, so parallel calls can exceed wall time. |
| `llm_calls`, `tokens`, `cost_usd` | from `llm_end` | Call count, total tokens, cost as reported by the agent. |
| `agent_queue_s` | Σ crew `agent_dispatched` → agent `request_consumed` | Waiting for an agent worker to pick up a request (Redis stream backlog). |
| `python_s` | Σ sandbox `exec_start` → `exec_end`, paired by execution id | Time executing Python node code in the sandbox. |
| `sandbox_wait_s` | Σ crew or agent `sandbox_dispatched` → sandbox `exec_start`, paired by execution id | Code handed to the sandbox but not running yet (sandbox queue, Redis delivery, worker start). An execution that never started adds nothing; such a session ends as `timeout`. A **lower bound**: crew and agent log `sandbox_dispatched` after publishing the execution, so at low load the sandbox's `exec_start` can come first; that execution's wait then counts as 0 (and its time stays in crew overhead). |
| `other_s` (**crew overhead**) | `max(0, run_s − llm_s − python_s − agent_queue_s − sandbox_wait_s)` | Everything else inside the run: crew orchestration, node bookkeeping, Redis hops, RAG search, agent work outside LLM calls. Clamped at 0 when parallel spans overlap. In run folders analyzed before `sandbox_wait_s` existed it still contains the sandbox wait (the viewer says so). |
| `platform_overhead_s` | `e2e_s − llm_s` | Everything that is not the LLM provider. The number to compare branches with when LLM latency is noisy. |

`e2e_s = dispatch_s + queue_wait_s + run_s`, and `run_s ≈ llm_s + python_s + agent_queue_s + sandbox_wait_s + other_s` when nothing runs in parallel. Without checkpoints (fallback mode) only `e2e_s` and `platform_overhead_s` (= `e2e_s`) are filled.

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
| `inflight_stages.csv` | 2-second sample × stage with sessions in it | yes |
| `findings.csv` | finding (what to look at first) | yes |
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
| `e2e_s` … `platform_overhead_s` | See [Session time and its parts](#session-time-and-its-parts) (includes `sandbox_wait_s`). |

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
| `e2e_s_*`, `queue_wait_s_*`, `run_s_*`, `llm_s_*`, `platform_overhead_s_*`, `sandbox_wait_s_*` | `p50`, `p90`, `p95`, `p99`, `max`, `mean` of that duration over completed measured sessions. |
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
| `phase_peak_mb` | Highest memory sample of the container over the whole phase: every segment and level, including the failing one, drain and cooldown. The same on every row of the phase. `mem_peak_mb` covers one level's measured window only, so after a failure the real peak is often only here. |
| `phase_peak_level` | Level of that sample; `0` = taken outside a level (cold session, baseline, drain or cooldown), shown as "outside a level" in the viewer. |

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
| `ts`, `rel_s` | Sample time (epoch) and seconds since the segment's sampler started (restarts at 0 in every segment). |
| `run_rel_s` | Seconds since the run's first sample, continuous across segments and phases: the viewer's time axis. |
| `throughput_per_min` | Sessions that ended with `end` in the 60 s before the sample (a rolling rate; not the level value of `steps.csv`). |
| `e2e_p95_60s` | p95 `e2e_s` of those sessions; empty when none ended. |
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

### `inflight_stages.csv`

At every timeline sample, the sessions in flight (sent, not ended) counted by the stage of the last checkpoint they had reached at that moment, from all checkpoint events. Columns `ts`, `run_rel_s`, `phase`, `segment` (of the sample), `stage`, `count`; a stage with no session at a sample has no row (count 0).

| Stage | Last checkpoint |
|---|---|
| `waiting for crew` | none yet, Django's checkpoints, or crew `received` (queued for a slot) |
| `crew` | crew `slot_acquired`, `compiled`, `node_start`, `node_end` or any other crew checkpoint; agent `result_published` |
| `agent queue` | crew `agent_dispatched` |
| `agent` | agent `request_consumed`, `llm_end` (agent work outside an LLM call) |
| `LLM` | agent `llm_start` |
| `waiting for sandbox` | crew or agent `sandbox_dispatched` (no `exec_start` yet; a `sandbox_dispatched` logged after its execution's `exec_start` is skipped, the session is then in `python`) |
| `python` | sandbox `exec_start` |
| `result return` | sandbox `exec_end` (crew has not logged its `node_end` yet) |

A session that hangs stays at its stage until the runner stops it, so a growing band shows where sessions pile up. A session with no known end counts until its segment's end (cooldown end), never into the next segment; an end that another container's clock puts before the send counts as the send, so no count is negative.

### `findings.csv`

What to look at first, from simple rules over the run. Columns: `phase`, `severity` (`critical`, `warning`, `info`), `kind`, `message`, `ts` and `run_rel_s` (the moment, for findings that have one; drawn as markers on the viewer's Timeline), `tab` (the viewer tab to read on), `container` (when the finding is about one). Sorted by severity, then time. The thresholds are named constants at the top of `analyze.py`.

| Kind | Severity | Rule |
|---|---|---|
| `timeouts` | critical | Per level: sessions that ended as `timeout`, with the last checkpoint they reached (as in the bottleneck text). Moment: the first runner stop. |
| `abort` | critical | A level was aborted, with the abort reason. Moment: end of the hold. |
| `container_restart` | critical | A container's known restart or OOM counter rose within a segment. Moment: the first sample showing it. |
| `cpu_limit` | warning | A container's mean CPU in a level's measured window is at least 90 % of its CPU limit (only containers with a limit); once per container and phase, at the first such level. |
| `http_errors` | critical, warning or info | Per level: start requests that failed, by error (`TimeoutError: 16`), out of the sessions the level started, with the level's API p95. Critical when they failed the level (bottleneck rule 1a). Otherwise graded by the phase: warning when the phase's failed start requests are above 1 % of its sessions (`HTTP_ERROR_WARN_SHARE`), info below; a level holds a few dozen sessions, so one stray failure would always be over 1 % of its own level. Moment: the first one. |
| `single_process_saturated` | warning | crew, agent or django_app at its cores (bottleneck rule 3) in a level's measured window; once per container and phase, at the first such level. |
| `llm_slowed_by_host` | warning | Some levels' LLM call p95 exceeded twice the reference (the smoke step's p95, else the phase's first level), and the host CPU was at 90 % or more in every one of them: `LLM call time rose A s → B s while host CPU was N %: likely CPU contention, not the provider` (call p50 at the first level and at the last slow level). `slow_provider` is then false. Moment: the first slow level's start. |
| `invalid_level` | warning | A level with verdict `invalid`, with its reason. Moment: level start. |
| `throughput_plateau` | warning | Among passing ladder levels only: the first one after which the next passing level raised throughput by less than 10 % (`PLATEAU_GROWTH`): `throughput stopped growing at level N (~T/min); passing level M only added latency`. A failed or invalid level is never compared. |
| `dominant_stage` | warning (info for LLM) | At the headline level (highest pass, else the first level) one part of the session time (dispatch, queue wait, agent queue, LLM, Python, sandbox wait, crew overhead) is more than 50 % (`DOMINANT_STAGE_SHARE`) of the mean e2e of the completed measured sessions. LLM is info: an agent flow is expected to spend its time there. The share is capped at 100 %: parallel LLM calls can sum to more than the session's time. |
| `memory_retained` | warning | `retained_mb_after_cooldown` above the larger of 50 MB (`RETAINED_MIN_MB`) and 10 % of the container's `baseline_mb` (`RETAINED_SHARE`). |

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
| **Verdicts** | First the **Findings** of each run (`findings.csv`), grouped by severity; selecting one opens its tab, and on the Timeline moves the crosshair to its moment. Run folders without `findings.csv` show no panel. Then per phase, one row per run. Capacity: max passing concurrency, first failing level, throughput, p95 e2e, p95 platform overhead and CPU-s/session at the highest passing level, headline MB per concurrent session, capacity estimate with its limit (bounds in the tooltip), bottleneck and fail reasons. Dev: concurrency, throughput, p50 and p95 e2e, CPU-s/session. ⚠ marks `slow_provider`. |
| **Curves** | One chart per phase: a metric from `steps.csv` against concurrency level (ladder, bisect and dev rows), one line per run. Metrics: throughput, p50/p95 e2e, p95 queue wait, p95 platform overhead, error rate, CPU-s per session, per-level MB per concurrent session. Filled point = pass, hollow = fail, cross = invalid. Log scale for the level axis is optional. |
| **Time breakdown** | Stacked bars of mean seconds per completed session at every measured level of every run, side by side (levels where nothing completed are left out): dispatch, crew overhead, agent queue, queue wait, LLM, sandbox wait, Python; level, kind, verdict and mean e2e in the table. Uses each level's sessions of its kind with status `end`, cold and finish sessions excluded. Each stage keeps one colour, the same as the matching stage of the Timeline's in-flight chart. For runs analyzed before `sandbox_wait_s` existed the sandbox wait is empty and Crew overhead still contains it (the old "Other"); a note names those runs. |
| **Timeline** | One run (pick it with **Run**). All charts share one time axis, elapsed since the run's first sample (`run_rel_s`, continuous across segments; computed from `ts` for older folders), labelled h:mm, or m:ss when less than 10 minutes are visible, at round intervals; tooltips give the elapsed time and the UTC clock time. **Zoom:** a slim overview of the whole run (sessions in flight) sits on top; drag across it or across any chart to show that range in every chart (the overview's brush marks it), the mouse wheel over a chart zooms around the pointer, Shift+drag pans, **Reset zoom** shows the whole run. With a chart focused: arrow keys move the crosshair, Shift+arrows pan, + / − zoom, 0 resets, Escape clears. The zoom is kept when the theme changes. **Buckets:** samples are averaged into time buckets sized to the visible range (about one per 3 pixels, from the raw 2 s samples when zoomed in to minutes for a long run), so each line is the bucket mean and a light band of the same colour its min–max; the stacked in-flight areas share one bucket grid. One crosshair: hovering a chart shows the values at that moment in all of them. Lines break between segments, and a dashed `restart · <next segment>` marker marks each stack restart. Charts, top to bottom: sessions (target, in flight, running, queued), in flight by stage (`inflight_stages.csv`, stacked areas, with a peak-per-stage table), throughput per minute and p95 e2e over the last 60 s, host CPU %. Then one full-width row per container on the same time scale: memory (MB) and CPU (% of one core) as two charts; containers a finding names (memory not released, CPU limit, restart) come first with a status border, glyph and the finding's text, then by peak memory. Then Postgres connections and Redis memory. Every chart has titled axes with units. Vertical lines: each measured level's start (green pass, red fail, grey invalid) and findings with a moment (✖ critical, ▲ warning, labelled). Selecting a Timeline finding opens the Timeline zoomed to ± 5 minutes around its moment with the crosshair on it. A chart whose data an older run folder lacks says so. |
| **Nodes** | Per node at each run's headline level: count, p50, p95, errors, Δ p50 against the same node in the baseline. |
| **Containers** | Per container: baseline MB, MB per concurrent session (slope) with Δ, r², retained MB after cooldown, phase peak MB with the level it was taken at ("outside a level" for level 0), and at the headline level CPU-s/session and peak memory with Δ. |
| **Waterfall** | One session from `events_sample.csv`: fastest, median, slowest (among sampled sessions with status `end`, whole run), a failed one, or the cold one. Bars from Django receiving the request: session, queue, each node, each LLM call, each Python execution. |

The **Theme** control in the header (Auto, Light, Dark) switches every chart at once; Auto follows the system setting, and the choice is kept in the browser's local storage when it allows that.

Every table header has a one-line definition (the viewer's `DEFINITIONS`, consistent with this file), shown on hover and on keyboard focus and announced to screen readers; a unit test checks that every column the analyzer writes has one.

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
   - `N start requests failed (<error>; API p95 S s)`: the API did not answer the start requests in time (`TimeoutError` = the client's 30 s timeout). Look at the service named after it, e.g. `django_app at its 1 worker`: raise `DJANGO_SGI_WORKERS`.
   - `<service> at one core (one process, N % CPU)` / `django_app at its N workers`: a Python service used all the cores its processes can; more host CPU will not help, more processes (workers, replicas) would.
   - `N timed out; last checkpoint: ...`: sessions hung at that checkpoint. `crew sandbox_dispatched` means the sandbox never started the code; the Timeline's in-flight chart shows when they piled up there.
   - `no saturated resource found`: latency grew without a saturated resource. Check the Time breakdown (which part grew between levels), Nodes, and `error_reason` of failed sessions.
4. **Compare branches on stable numbers.** Prefer p50 e2e and p95 platform overhead, the payload phase (no LLM), CPU-seconds per session and the headline MB slope. Throughput at different levels is not comparable; compare at the same level or compare max passing concurrency.
5. **Know what is noise.** One run per configuration, no repeats: differences under about 5–10 % in latency are within run-to-run noise, more on a laptop. `max` and `p99` with few sessions are single sessions. A slope with `r² < 0.5` is noise. `slow_provider` means LLM latency moved, not EpicStaff. The capacity estimate is an extrapolation; the measured max passing concurrency is the fact.
