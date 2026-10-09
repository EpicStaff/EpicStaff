# EpicStaff session benchmark

One tool that runs real sessions against a running EpicStaff stack, writes flat result files, and compares runs in a browser viewer. Plain Python standard library, Python 3.11 or newer (`tomllib`). It talks to the stack only through `docker` / `docker compose`, the HTTP API, and host files under `/proc` and `/sys/fs/cgroup` (Linux; Docker Desktop falls back to `docker stats`).

## Quick start

Developer check on a laptop, from the repository root, with the stack running.

1. **`src/.env`**, once and after pulling new variables: `make env-update DEV=1`. It appends only the variables your `.env` lacks and never changes existing lines. No `src/.env` yet: `python scripts/envtool.py --dev`. The dev profile is fine on a laptop; pre-flight warns that the numbers include debug overhead.
2. **API key**, once: create an API key for your organization in the UI and put it in `~/.epicstaff-bench.env`, then `chmod 600 ~/.epicstaff-bench.env`:
   ```bash
   export DJANGO_API_KEY=<org API key>
   export BENCH_ORG_ID=1
   ```
3. **Payload flow**, once: build it in the UI (5 Python nodes, no LLM, no RAG), give it the `benchmark` label, export it and save the file as `benchmark/flows/payload.json`. Commit it, so everyone measures the same flow. `dev` imports it by itself on the first run and reuses that flow afterwards; see **Graph ids** below.
4. **Measure**, then compare:
   ```bash
   make bench-dev ARGS='--note "before fix"'
   # ... change code ...
   make bench-dev ARGS='--note "after fix"'
   python benchmark/bench.py compare benchmark/results/<before-run> benchmark/results/<after-run>
   ```
   For charts open `benchmark/viewer.html` and drop the run folders on it (section 7).

## Commands reference

All commands run from the repository root. A case argument is used as a path if that file exists, otherwise looked up under `benchmark/cases/`, so `server` and `server.toml` work from anywhere.

| Command | Options | What it does |
|---|---|---|
| `python benchmark/bench.py dev` | `--case <name-or-path>` (default `dev`), `--graph PHASE=ID`, `--sessions N`, `--concurrency N`, `--note`, `--no-restart`, `--no-build` | Developer check: payload phase only, fixed load (default 100 sessions, 25 in flight), no ladder, no verdict. |
| `python benchmark/bench.py run <case>` | `--graph PHASE=ID` (repeatable), `--variant a,b`, `--set KEY=VALUE` (repeatable), `--ref <git-ref>`, `--note`, `--no-build`, `--no-smoke` | Full run, one run folder per variant. `--set` and `--ref` add an ad-hoc variant named `<variant>-adhoc` on top of the chosen ones. |
| `python benchmark/bench.py smoke <case>` | as `run` | First variant only, ladder cut to its first level, no bisect. |
| `python benchmark/bench.py preflight <case>` | as `run` | Host, `.env` and stack checks without running load. Exit 2 on any error. |
| `python benchmark/bench.py plan <case>` | as `run` | Prints variants, ladder levels per phase and the worst-case duration (every level waiting the full `session_timeout_s` in its finish step; a normal level waits about one session duration). Does not touch the stack and never imports; a payload phase without a graph id is fine as long as its export exists. |
| `python benchmark/bench.py compare <run>...` | | Terminal comparison; the first run is the baseline, the others show Δ %. |
| `python benchmark/bench.py push <run>...` | `--yes` | Copies run folders into the results repo, section 3 step 8. |
| `python benchmark/bench.py flow import` | `--quiet` (print only the id) | Always imports `benchmark/flows/payload.json`, replacing the flow an earlier import created, and prints `payload flow: id <id> (created\|updated) "<name>"`. Exit 2 on an error. A replace recreates the nodes with new ids, so runs before and after it show "different workload". |
| `python scripts/envtool.py` | `--dev` | Writes a new `src/.env` from `src/env.yaml` with production (or `--dev` development) defaults, overwriting the file. |
| `python scripts/envtool.py --update` | `--dev` | Appends the variables `src/.env` lacks, with the chosen profile's defaults, under a dated `# Added by envtool --update` comment. Variables without a default are appended commented out and listed as "needs a value". Never changes or reorders existing lines. |
| `make env-update` | `DEV=1` | `python scripts/envtool.py --update` (`--dev` with `DEV=1`). |
| `make bench-flow` | | `python benchmark/bench.py flow import`. |
| `make bench-dev` | `ARGS='<dev options>'` | `python benchmark/bench.py dev $(ARGS)`. |

The make targets run the host Python (`python3`, `python` on Windows; override with `PYTHON=<interpreter>`); `envtool.py` also needs PyYAML.

**Graph ids** come from the case file or `--graph <phase>=<id>`, for example `--graph payload=17 --graph complex=18`; `--graph` wins. When the `payload` phase has neither and `benchmark/flows/payload.json` exists, `dev`, `run`, `smoke` and `preflight` use the flow imported from that file: `preflight` after its host and `.env` checks, a run once the stack is up. It is imported only when this server and organization do not have it yet, when the file changed, or when the flow was deleted; otherwise the earlier import is reused (printed as `existing`). Re-importing an unchanged file would recreate its nodes with new ids and change the graph hash, so two runs of the same flow would look like different workloads. Which import belongs to which server, organization and file content is kept in `benchmark/.flow-cache.json` (gitignored; deleting it only costs one re-import). Every other phase still needs an id.

**Settings** come from the environment: `DJANGO_API_KEY` (required by every command that talks to the stack, and by `push`), `BENCH_ORG_ID` (default 1), `BENCH_API` (default `http://localhost`), `BENCH_RESULTS_REPO` (for `push`). Any of these four that the environment does not set is read from `~/.epicstaff-bench.env` (`NAME=VALUE` or `export NAME=VALUE` lines; every other name in the file is ignored). An exported value always wins, so an exported `DJANGO_API_KEY` is used while `BENCH_ORG_ID` can still come from the file. On Linux and macOS the tool warns when that file is readable by other users.

Exit codes: 0 ok, 2 case error, flow import error or pre-flight error, 3 smoke failed, 130 Ctrl+C, other non-zero on a crash.

## 1. What it measures

- **Capacity**: how many sessions the server runs at the same time (sustained, within the pass rules) before it breaks, and which resource breaks first.
- **Cost of one session**: CPU-seconds, MB per concurrent session, LLM tokens, time per stage and per node. These are per-session numbers, so they compare across load levels.
- **Better or worse**: did a change improve capacity on the server, or a 1-minute developer check on a laptop. Any set of runs opens in one viewer, which says when two runs did not measure the same thing.

## 2. Server capacity run

```bash
python benchmark/bench.py preflight server
python benchmark/bench.py plan server --graph complex=<id>
python benchmark/bench.py run server --note "after the agent fix"
python benchmark/bench.py compare benchmark/results/<run-a> benchmark/results/<run-b>
python benchmark/bench.py push benchmark/results/<run-a>
```

The `complex` graph id is server-specific: set it in `benchmark/cases/server.toml` or pass `--graph complex=<id>`. The payload flow is imported from `benchmark/flows/payload.json` unless an id is given.

## 3. Server setup

Done once, on the machine that runs the benchmark and pushes results.

1. Deploy key:
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/epicstaff_benchmarks -N "" -C "epicstaff-perfomance benchmarks"
   ```
2. GitHub, `EpicStaff/epicstaff-benchmarks`, Settings, Deploy keys, Add. Paste `~/.ssh/epicstaff_benchmarks.pub` and tick **Allow write access** (needs repo admin).
3. `~/.ssh/config`:
   ```
   Host github-benchmarks
     HostName github.com
     User git
     IdentityFile ~/.ssh/epicstaff_benchmarks
     IdentitiesOnly yes
   ```
   Test with `ssh -T github-benchmarks`. If port 22 is blocked, use `HostName ssh.github.com` and `Port 443`.
4. Clone and set the commit identity:
   ```bash
   git clone github-benchmarks:EpicStaff/epicstaff-benchmarks.git ~/epicstaff-benchmarks
   git -C ~/epicstaff-benchmarks config user.name "EpicStaff Benchmarks"
   git -C ~/epicstaff-benchmarks config user.email "<address>"
   ```
5. `src/.env` with production defaults: `python3 scripts/envtool.py` on a new server, `make env-update` after pulling new variables. Pre-flight warns when `.env` looks like the dev profile, whose debug overhead makes the numbers incomparable.
6. API key and settings: create an API key in the EpicStaff UI for the benchmark organization, write it to `~/.epicstaff-bench.env` and `chmod 600 ~/.epicstaff-bench.env`. The tool reads the file by itself (exported values win), so no `source` is needed:
   ```bash
   export DJANGO_API_KEY=<org API key>
   export BENCH_ORG_ID=<org id>
   export BENCH_RESULTS_REPO=~/epicstaff-benchmarks
   ```
7. Flows: the payload flow is imported from `benchmark/flows/payload.json` (by itself on the first `preflight` or `run`, then reused; `make bench-flow` re-imports it by hand). Build the `complex` flow in the UI: this is the operator's job, on every server, with its LLM config and key, and its RAG collection. Put its graph id into `benchmark/cases/server.toml` (or pass `--graph complex=<id>`). The smoke run proves each flow completes.
8. Run: `python3 benchmark/bench.py preflight server`, then `plan`, then `run --note "..."`, then `push`.

Never put secrets into case files: a copy of the file is stored in every run folder as `case.toml`. Values of `[env]` and variant `env` keys outside the allowlist are replaced by `<redacted>` in that copy; phase `variables` and every other value are stored as written.

The first live run on a server should be watched. The orchestration paths (docker, compose, live API) have no automated tests; only the analysis, ladder, config and env-restore logic do (`python -m unittest discover -s benchmark -p "test_*.py"`).

## 4. Case file reference

TOML. Unknown keys in `[ladder]`, `[pass]`, `[abort]`, `[dev]` are rejected, so typos fail fast. Defaults below are the code defaults; `benchmark/cases/server.toml` overrides some of them (shown in the last column).

### Top level

| Key | Default | Meaning |
|---|---|---|
| `name` | required | Case name, part of the run folder name. |
| `kind` | `"capacity"` | `capacity` (ladder, verdict) or `dev` (one fixed load, no verdict). |

### `[env]`

`.env` overrides applied to `src/.env` for every phase of every variant, and restored afterwards. Values may be strings, numbers or booleans. A variant's `env` is merged on top. Keys that are not in the allowlist (`*_LOG_LEVEL`, `CREW_MAX_CONCURRENT_SESSIONS`, `AGENT_MAX_CONCURRENT_RUNS`, `*_SGI_WORKERS`, `KNOWLEDGE_MAX_PROCESS_WORKERS`, `*_CPUS`, `*_MEM_LIMIT`) keep their name but never their value in `meta.json`.

| Key in `server.toml` | Value | Why |
|---|---|---|
| `CREW_MAX_CONCURRENT_SESSIONS` | `100000` | Otherwise the ladder measures crew's cap (default 25). |
| `AGENT_MAX_CONCURRENT_RUNS` | `100000` | Otherwise agents stall at 10 runs per replica. |
| `DJANGO_LOG_LEVEL`, `CREW_LOG_LEVEL`, `AGENT_LOG_LEVEL`, `SANDBOX_LOG_LEVEL` | `"BENCH"` | Turns the checkpoint lines on (section 8). `dev.toml` sets the four log levels only. |

### `[ladder]`

| Key | Default | `server.toml` | Meaning |
|---|---|---|---|
| `start` | 25 | 25 | First concurrency level (sessions held in flight). |
| `factor` | 2.0 | 2 | Next level = `round(level x factor)` (at least +1). Must be > 1. |
| `max` | 20000 | 20000 | Hard ceiling. Must be >= `start`. |
| `hold_s` | 180 | 180 | Measured window per level: sessions sent in it are measured. The level then keeps its load until those sessions have ended (the *finish* wait, at most `session_timeout_s`) and only then gets its verdict. Fewer than 10 measured sessions make the level `invalid`. |
| `settle_s` | 30 | 30 | Excluded from stats after each level change. Raised automatically to the smoke run's p95 session time (not when `--no-smoke`). |
| `baseline_s` | 20 | 20 | Baseline sampling before load. |
| `cooldown_s` | 120 | 120 | Sampling after drain. `dev.toml`: 10. |
| `bisect_steps` | 2 | 2 | Refinement probes between last pass and first fail. |
| `session_timeout_s` | 900 | 900 | A session older than this is stopped and counted as failed `timeout`. This also caps a level's finish wait. `dev.toml`: 300. |

### `[pass]` (all must hold in the measured window)

| Key | Default | `server.toml` | Meaning |
|---|---|---|---|
| `p95_e2e_s` | none (rule off) | 120 | p95 end-to-end seconds. |
| `p95_queue_wait_s` | none (rule off) | 5 | p95 seconds waiting for a crew slot. |
| `max_error_rate` | 0.01 | 0.01 | Failed share of measured sessions. |

A `[[phase]]` can override any of these with `pass = { ... }`.

### `[abort]` (any one stops the level at once)

| Key | Default | Meaning |
|---|---|---|
| `error_rate_30s` | 0.05 | Error rate over the last 30 s (needs 20 finished sessions; not used in fallback mode). |
| `host_min_available_ram_pct` | 5 | Host available RAM floor. |
| `container_restart` | true | Any container restart or OOM kill. |
| `generator_lag_p99_ms` | 500 | p99 of `sent_ts - intended_ts`. Above it the level is `invalid` ("generator-limited"), the ladder stops, and no server verdict is given for it. |

### `[dev]`

| Key | Default | Meaning |
|---|---|---|
| `sessions` | 100 | Sessions to start (`--sessions` overrides). |
| `concurrency` | 25 | Sessions in flight (`--concurrency` overrides). |

### `[[phase]]` (at least one; names unique)

| Key | Default | Meaning |
|---|---|---|
| `name` | required | Phase name. `--graph <name>=<id>` refers to it. |
| `graph_id` | required (case file or `--graph`) | Positive integer. Server-specific. The `payload` phase falls back to importing `benchmark/flows/payload.json` (Commands reference). |
| `variables` | none | Table sent as the session's start variables. |
| `pass` | `{}` | Per-phase override of `[pass]`. |

`server.toml` has two sequential phases with separate verdicts: `payload` (a big payload through 5 Python nodes, no LLM) and `complex` (start-node variables only; the flow calls agents, RAG and so on; `pass = { p95_e2e_s = 300 }`). `dev.toml` has `payload` only.

### `[[variant]]` (one run per variant; default is a single `default`)

| Key | Default | Meaning |
|---|---|---|
| `name` | required | Part of the run folder name. |
| `env` | `{}` | Extra `.env` overrides for this variant. |
| `ref` | none | Git ref to build in a temporary worktree. |

### Case hash and graph hash

- **Case hash** = SHA-256 of the parsed TOML without `[[variant]]` and without the phases' `graph_id`, so all variants of one case share it and a server-specific graph id does not matter. It hashes what is in the file, not the effective values: writing a default explicitly (for example `factor = 2.0` where the file had nothing) changes the hash and makes two runs look like different workloads.
- **Graph hash** is recorded per phase: the runner reads `GET /api/graphs/<id>/` and hashes the response without timestamps and `save_version`. A UI edit between two runs changes it and the viewer shows "different workload".

## 5. How a run works

`run` executes this per variant:

1. **Pre-flight.** Errors stop the run, warnings are printed. Host checks: docker reachable, no leftover `src/.env.bench-backup`, load1 not above half the vCPUs, at least 20 % RAM available (the load and RAM checks need `/proc`, so they are Linux-only). `.env` checks, before anything is written: `src/.env` exists, and it sets every `${VAR:?}` variable of the `docker-compose.yaml` being built (a variable set only by the case or variant `env`, or exported in the shell, counts as set; an empty value does not). Only that compose file is scanned (`src/docker-compose.yaml`, or the worktree's for a `--ref` run); other compose files and `${VAR}` without `:?` are not checked. A missing one is an error that names it and says `run: python scripts/envtool.py --update (or make env-update)`. A warning when the settings in effect look like the dev profile (`DJANGO_DEBUG` true, or any `*_LOG_LEVEL` at `DEBUG`/`TRACE` after the case overrides): the numbers then include debug overhead. After the build: containers healthy, each phase graph readable (this is also where a wrong id, org or rejected API key shows up), no leftover `pending`/`run` sessions on the phase graphs, container log driver `json-file` or `local`. Warnings: BENCH not active on a service, `CREW_MAX_CONCURRENT_SESSIONS` or `AGENT_MAX_CONCURRENT_RUNS` below `ladder.max`, no container memory limits (a break can then take the host down; the host-RAM abort guard is the only protection).
2. **Env and build.** `src/.env` is backed up to `src/.env.bench-backup`, the overrides are written, and `docker compose up -d --build` runs (`--no-build` skips the build and labels the run `build-unverified`). If a previous run crashed hard and left the backup behind, the next run refuses to start and prints `mv src/.env.bench-backup src/.env`; check the file, then do that.
3. **Resolve graphs** and record the graph hash per phase. A payload phase without a graph id first gets the flow of `benchmark/flows/payload.json`, imported only if this server does not have it yet (Commands reference, **Graph ids**).
4. **Smoke** (skip with `--no-smoke`): per phase, concurrency 2 for 60 s. The run stops with exit 3 if no session ends with `end`, any session fails, or a checkpoint is missing from a service that has BENCH active. The reason is printed, for example a missing LLM key or RAG collection on this server.
5. **Per phase**, one *segment* for the ladder and one for every bisect probe. Each segment: restart `django_app crew agent sandbox knowledge_new` and wait healthy, one cold session (recorded with `cold=1`, excluded from aggregates), baseline sampling, the ladder levels, drain (wait for in-flight sessions up to `session_timeout_s`, then stop the rest), cooldown sampling. Each level (a bisect probe too) runs in three steps at the same concurrency:
   - **settle** (`settle_s`): sessions sent now are not measured;
   - **hold** (`hold_s`): sessions sent now are the level's measured sessions;
   - **finish**: the load continues until every measured session has ended, so the verdict uses true durations, not times so far. Sessions sent now get kind `finish` and are never measured. The wait is capped by `session_timeout_s`: a measured session still running then is stopped as a failed `timeout`, a real overload signal.

   The level is judged at the end of the finish step, and the ladder stops at the first level that is not a pass. The final analysis uses the same window, so the live and the final verdict normally agree.
6. **Bisect.** Between the last passing level P and the first failing level F, probe `(P + F) // 2`, up to `bisect_steps`, and stop early when `(F - P) / P` is 10 % or less. Every probe starts with the restart, cold session and baseline above.
7. **Cleanup.** The phase's sessions are deleted through the API (batches of 500).
8. **Always** (also on Ctrl+C or a crash): stop load and log followers, restore `src/.env` from the backup, write what was collected, analyze, print `Run folder: ...`, then run `docker compose up -d` from the main checkout to apply the original settings. The run folder is written before that last step because it can take minutes, and a second Ctrl+C there must not lose the measurements.

### Ctrl+C and crashes

- **Ctrl+C**: stops load, stops in-flight sessions, analyzes what was measured, prints the run folder, skips the remaining variants, exits 130. The run is labelled `interrupted`. The sessions the runner stopped get status `interrupted`: not a failure, and their duration is unknown (see Definitions). In fallback mode the runner does not know session ids, so it asks the sessions API which of the phase's sessions are still `pending` or `run` and stops those before cleanup deletes them.
- **Crash**: analyzed the same way, labelled `crashed:<ExceptionType>`, traceback printed, non-zero exit.

### `--ref` runs

`--ref <git-ref>` (or a variant `ref`) builds that ref in a temporary `git worktree`; `src/nginx/certs` is copied into it because it is gitignored. The worktree is removed afterwards, but the stack keeps that ref's images under the main compose file until the next `--build`. To get back to your checkout's code:

```bash
cd <your checkout>/src && docker compose up -d --build
```

### Fallback mode (branches without BENCH lines)

If crew produces no `session_end` line (an old branch, or `CREW_LOG_LEVEL` not BENCH), the run does not fail. In-flight counts come from the API (`GET /api/sessions/statuses/`, once per second) and end times from the sessions list (every 5 s during a level's finish step, and after each level). Such a phase is labelled `fallback-control:<phase>`. Limits: stuck sessions cannot be identified while the load runs, so `session_timeout_s` is enforced only at the end of a finish step (measured sessions the sessions list still shows as running are stopped as `timeout`), and `error_rate_30s` is not used; an API that stays unreachable for 10 s or more while counting fails the level. Per-node and per-stage timings are empty without BENCH lines.

### Definitions

| Term | Meaning |
|---|---|
| **Measured session** | A session sent during a level's hold, after its `settle_s` and before the hold ends (cold and `finish` sessions never count). The level verdict and the level's statistics use only these. |
| **Finish session** | Kind `finish` in `sessions.csv`: sent after the hold, while the level kept its load until its measured sessions ended. It keeps the concurrency honest and is in the timeline, but is not measured. |
| **Unfinished session** | A measured session with no known end when the level is judged. After the finish step this happens only on an interrupt (`interrupted`) or when end times are missing (fallback mode with the sessions API unreachable). Its time so far is a lower bound of its duration (`censored` in `sessions.csv`). For `p95_queue_wait_s`, a session still queued is unfinished. |
| **Level verdict** | `fail` when a rule fails even with every unfinished session counted at its lower bound. Otherwise `invalid` when fewer than 10 measured sessions ended ("raise ladder.hold_s"), or when more than 5 % of them are unfinished: those could be the slowest 5 %, so the p95 is unknown. Otherwise `pass` or `fail` on the p95 of the ended sessions. |
| **Interrupted** | Status of a session the runner stopped because the run itself was stopped (Ctrl+C or a crash). Not a failure: it counts in the `interrupted` column of `steps.csv`, apart from `failed` and the error rate. A session that outlives `session_timeout_s` is stopped as `timeout` and is a failure. |
| **Throughput** | Sessions finished with status `end` per minute during the measured window of a level (`throughput_per_min`). |
| **Platform overhead** | `platform_overhead_s` = session end-to-end time minus time spent in LLM calls. It is the number that compares branches when the LLM is noisy. |
| **Bottleneck** | Set at the first failing level. First match wins: container restart/OOM, host RAM under the guard, host CPU at 90 % or more, a container at 90 % of its CPU limit, crew slots full with sessions queued, agent queue wait growing (p95 more than double the previous level and above 1 s), Postgres connections at 90 % of `max_connections`, otherwise "no saturated resource found". |
| **Capacity estimate** | At the highest passing level, the smallest of these bounds, with the limiting one named: `cpu` = vCPU x p50 e2e / CPU-seconds per session; `ram` = baseline available host RAM / MB per concurrent session; `CREW_MAX_CONCURRENT_SESSIONS`; `AGENT_MAX_CONCURRENT_RUNS` (only when the phase made LLM calls). |
| **MB per concurrent session** | Slope of container RAM against running sessions over the phase. The headline sums only containers whose fit has r² of at least 0.5; weaker fits are noise and stay out of it (they remain in `container_phases.csv`). |
| **Cold session** | The first session after the restart; reported separately in `meta.json`. |

Resource costs are means (total / finished sessions, because capacity is additive); durations are percentiles with the mean alongside. A verdict that changes between the live ladder decision and the final analysis is labelled `verdict-revised:<phase>:<level>`.

## 6. Output files

Each run is one flat folder in `benchmark/results/`, named `<YYYY-MM-DD_HHMM>_<host>_<ref-slug>_<sha7>_<case>-<variant>`. The file schema is version 1; the column lists are the `*_COLUMNS` constants in `analyze.py`.

| File | One row per | Contents |
|---|---|---|
| `meta.json` | run | `schema_version`, `tool_version`, `run_id`, `created_at`, `note`, `kind`, `case` (name, hash, variant, overrides), `git` (ref, sha, dirty, built), `images`, `host` (hostname, vcpu, ram_mb, kernel, docker, virtualization), `container_limits`, `env` (allowlist only), `labels`, `smoke`, `phases` (per phase: graph id, name and hash, variables hash, verdict, provider health, capacity estimate, cold session). |
| `case.toml` | - | The exact case file used, unless an `[env]` or variant `env` value is outside the allowlist: then the parsed case written back as TOML with those values replaced by `<redacted>` (comments and layout are not kept). `meta.json` `case.hash` is always the hash of the original file, so re-hashing a redacted copy gives a different value. |
| `sessions.csv.gz` | session | `phase, segment, level, kind` (ladder, bisect, dev, cold, smoke, or `finish`: sent during a level's finish step, not measured), `cold, session_id`, send timing (`intended_ts, sent_ts, gen_lag_ms, api_ms, http_status`), checkpoint times (`arrival_ts, received_ts, slot_ts, end_ts`), `status` (crew's status, or the runner's `http_error`, `timeout`, `interrupted`), `censored` (true for an `interrupted` session: its durations are lower bounds), `error_reason`, durations (`e2e_s, dispatch_s, queue_wait_s, run_s, llm_s, agent_queue_s, python_s, other_s, platform_overhead_s`), `llm_calls, tokens, cost_usd`. |
| `steps.csv` | phase x level | `phase, segment, level, kind` (ladder, bisect, dev), `target, inflight_mean, running_mean, steady_s, sent, completed, failed, interrupted, throughput_per_min, error_rate` (failed / sent; `interrupted` is not failed), `p50/p90/p95/p99/max/mean` of `e2e_s, queue_wait_s, run_s, llm_s, platform_overhead_s`, `cpu_s_per_session, mb_per_concurrent, gen_lag_p99_ms, verdict` (pass, fail, invalid), `live_verdict, fail_reasons, bottleneck`. |
| `containers.csv` | phase x level x container | `cpu_s, cpu_s_per_session, cpu_pct_mean, cpu_pct_max, mem_mean_mb, mem_peak_mb, restarts, oom_kills`. |
| `container_phases.csv` | phase x container | `baseline_mb, mb_per_concurrent` (slope), `r2, retained_mb_after_cooldown`. |
| `nodes.csv` | phase x level x node | `node_name, node_type, count, p50_s, p95_s, mean_s, max_s, error_count`. |
| `timeline.csv` | sample (every 2 s) | `ts, rel_s, phase, segment, level, target, inflight, running, queued, completed, failed, host_cpu_pct, host_mem_avail_mb, host_mem_avail_pct, load1, pg_connections, pg_max_connections, redis_used_mb, runner_cpu_pct`. |
| `container_timeline.csv` | sample x container | `ts, rel_s, phase, segment, level, container, cpu_pct, mem_mb, restarts, oom_kills`. |
| `events_sample.csv` | checkpoint | `session_id, service, checkpoint, ts, node_name, extra_json` for a sample of sessions: 100 fastest, 100 around the median, 100 slowest, up to 150 failures, the cold ones. |
| `events_full.csv.gz` | checkpoint | Same columns, every checkpoint. Never pushed (size); stays on the machine. |

Resource sampling is every 2 s: CPU and memory from the host's cgroup v2 counters on Linux (exact CPU, sampled memory), `docker stats` on Docker Desktop. Peak memory is the sampled maximum in the window.

`bench compare` prints, per phase, the headline numbers at each run's highest passing level (a dev run's single level): max passing concurrency, throughput, p50 and p95 e2e, p95 platform overhead, p95 queue wait, error rate, CPU-seconds per session, MB per concurrent session, and p50 per node. The first run is the baseline; the others show Δ %. It lists differing metadata and prints `!! different workload` when the case or graph hashes differ.

## 7. Viewer

`benchmark/viewer.html` is one static page (Chart.js from cdnjs, no build, no backend). `bench push` copies it to the results repo as `index.html`.

- **Served mode** (the results repo): from the repo root run `python3 -m http.server`, open `http://localhost:8000/`. The page reads `benchmarks/index.json` (button "Load index.json" if it does not load by itself). It also works from GitHub Pages if the repo is public.
- **Local mode** (dev runs, anything not pushed): open `benchmark/viewer.html` from disk, press "Open run folders..." or drop folders on the page. It accepts one run folder or a parent folder of runs (for example `benchmark/results/`). Both modes can be mixed. Opened from disk the page cannot fetch `index.json`; that is expected, use local mode.
- **Run list**: run number (`#N` from the index, `local` for unpushed), date, kind, case and variant, ref, sha, host, note, labels. Tick runs to select them; the first selected is the baseline, change it with the radio button.
- **Comparing runs**: tabs Verdicts, Curves, Time breakdown, Timeline, Nodes, Containers, Waterfall. A table lists every `meta.json` field that differs between the selected runs. Δ vs the baseline is shown only between runs of the same kind (green better, red worse). The LLM phase shows the provider-health flag next to the deltas.
- **"Different workload - not comparable" banner**: shown when the case hash or any phase's graph differs between the selected runs, for example after a flow was edited in the UI, or after an explicit default was added to the case file. The comparison stays visible; read the numbers with that in mind.
- A run with an unknown `schema_version` is refused with a message.

## 8. Product side

The benchmark relies on **BENCH checkpoints** in the product code: loguru records at custom level `BENCH` (15, between DEBUG and INFO), registered in `src/shared/bench_log.py`. Each is written as one compact JSON line on stdout, `{"bench":1,"ts":<epoch>,"checkpoint":"...", ...}`; the runner follows `docker logs -f` of the four instrumented containers and reads these lines.

Turn them on with `<SERVICE>_LOG_LEVEL=BENCH` in `src/.env` for `crew`, `sandbox`, `agent` and `django_app` (`CREW_LOG_LEVEL`, `SANDBOX_LOG_LEVEL`, `AGENT_LOG_LEVEL`, `DJANGO_LOG_LEVEL`). `DEBUG` and `TRACE` also show them. The case files set BENCH through their `[env]` and the runner applies and restores `src/.env`, so you normally never edit it by hand. The other services do not accept `BENCH`: webhook passes its level to uvicorn, which has no such level, and realtime and knowledge_new are not instrumented.

**At the default `INFO` level the checkpoints are not printed and not evaluated: INFO hides everything**, so production behaviour is unchanged. At BENCH the normal log lines are unchanged and the checkpoints are not duplicated into them.

| Service | Checkpoints | Fields |
|---|---|---|
| django_app | `request_received`, `session_created`, `published` | `session_id`; `arrival_ts` (real arrival time); `received_n` (listeners that got the session) |
| crew | `received`, `slot_acquired`, `compiled` | `session_id` |
| crew | `session_end` | `session_id`, `status` (`end`, `cancelled`, ...), `reason` |
| crew | `node_start`, `node_end` | `session_id`, `node_name`, `node_type`; `ok` on end |
| crew | `agent_dispatched` | `correlation_id` (session id comes from the log context) |
| crew | `sandbox_dispatched` | `session_id`, `execution_id` |
| agent | `request_consumed`, `result_published` | `correlation_id`; `ok` on result |
| agent | `llm_start`, `llm_end` | `correlation_id`, `model`; token usage, `ok`, `error_type` on end (provider errors, including 429 after retries, are counted) |
| agent | `sandbox_dispatched` | `session_id`, `execution_id` |
| sandbox | `exec_start`, `exec_end` | `session_id`, `execution_id`; `returncode` on end |

## 9. Known limits

- **No container CPU/RAM limits yet.** They come with a separate ticket. Until then a break test can push the host into OOM; the host-RAM abort guard (default 5 %) and the pre-flight warning are the only protection, and hardware presets (variants that set limit variables) are not available. Do not run a high ladder on a machine you cannot afford to lose.
- **No repeats.** One run per configuration. Run-to-run noise is not measured; the provider-health line (LLM p95 more than 2x the smoke run's p95 sets `slow_provider`) is the only noise signal.
- **LLM noise in `complex`.** Real provider latency and rate limits move the numbers. Compare branches on platform overhead and on the `payload` phase, which has no LLM.
- **Generator ceiling.** The load generator is stdlib Python (64 sender threads, 30 s HTTP timeout) on the same host. When it cannot keep up, `sent_ts - intended_ts` grows; a level whose p99 lag exceeds `generator_lag_p99_ms` is marked `invalid` with "generator-limited", the ladder stops there, and no server verdict is given. The runner's own CPU is in `timeline.csv` (`runner_cpu_pct`).
- **Linux server assumed.** Exact CPU needs the host cgroup tree; on Docker Desktop CPU comes from `docker stats` and is coarser. Host load and RAM pre-flight checks are skipped without `/proc`.
- **Demo data.** `python benchmark/fixtures.py <dir>` writes three synthetic run folders (two capacity runs, one dev run) for trying the viewer. They are fake numbers, never push them.

## Tests

```bash
python -m unittest discover -s benchmark -p "test_*.py" -v
python -m unittest scripts/test_envtool.py -v     # envtool --update; needs PyYAML
```

## Security notes

- The API key is read from `DJANGO_API_KEY`, or from `~/.epicstaff-bench.env` when that is not exported; never from `src/.env`. It is never written to a result file. `bench push` refuses a run folder that contains the key string (it scans every file in the folder and its subfolders except `events_full.csv.gz`, the same set it copies), so it needs the key. It also needs `BENCH_RESULTS_REPO`. The scan looks for that one key only; other secrets are kept out by the allowlists below.
- `bench push` requires a clean results clone, runs `git pull --ff-only`, prints the exact `git add`, `git commit`, `git push` commands, and runs them only after you answer `y` (or pass `--yes`). It copies each run folder without `events_full.csv.gz` and rebuilds `benchmarks/index.json` (existing run numbers are kept, new runs get the next number).
- `meta.json` keeps environment values only for the allowlist; the stored `case.toml` replaces `[env]` and variant `env` values outside it with `<redacted>`; error reasons are truncated to 300 characters.
