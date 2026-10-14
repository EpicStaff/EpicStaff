# Benchmark runbook

Step-by-step instructions for running the session benchmark. Part A is a developer laptop, part B is the benchmark server. What the numbers mean is in [METRICS.md](METRICS.md); the command and case-file reference is in [../README.md](../README.md).

Every command runs from the repository root (the folder that contains `benchmark/` and `src/`).

- [Smoke step, `smoke` command and a real run](#smoke-step-smoke-command-and-a-real-run)
- [Why containers restart during a run](#why-containers-restart-during-a-run)
- [A. Developer laptop](#a-developer-laptop)
- [B. Benchmark server (Linux)](#b-benchmark-server-linux)

## Smoke step, `smoke` command and a real run

Three different things:

| | What runs | Run folder | Use it for |
|---|---|---|---|
| **Smoke step** (inside `run` and `smoke`, skipped with `--no-smoke`) | Per phase: 2 sessions in flight for 60 s, no restart, then waits until those sessions end. Fails the run with exit 3 if no session ends with status `end`, if any session ends otherwise, or if a service that has BENCH on is missing a checkpoint (`django_app`: `request_received`; `crew`: `received`, `slot_acquired`, `session_end`; `agent`: `llm_start`, `llm_end` when crew dispatched to an agent; `sandbox`: `exec_start`, `exec_end`). | None. Its result is stored in the next run's `meta.json` → `smoke`. | Proving that every flow completes on this server before the long ladder starts. It also raises `settle_s` to the slowest phase's p95 session time. |
| **`bench.py smoke <case>`** | A full run of the first variant (smoke step included) with the ladder cut to its first level (`ladder.start`) and no bisect. | Yes. | A short real measurement at one level. On a case with `start = 625` this is 625 sessions in flight, not a small test. |
| **`bench.py run <case>`** | Every variant, the full ladder until the first non-passing level, then bisect. | One per variant. | Capacity numbers. |

`bench.py dev` is a fourth mode: one fixed load (sessions and concurrency), first phase only, never a smoke step, no ladder.

## Why containers restart during a run

- **Env override recreates containers.** The case's `[env]` (and a variant's `env`) are written into `src/.env` for the run (the original is kept as `src/.env.bench-backup`), then `docker compose up -d` runs. Compose recreates every container whose settings changed. After the run the original `src/.env` is restored and `docker compose up -d` runs again, which recreates them back. If `src/.env` already has the case's values, nothing is recreated.
- **Restart before each segment.** Before the ladder and before every bisect probe the runner restarts `django_app crew agent sandbox knowledge_new` and waits until they are healthy, so each segment starts from a clean memory and connection baseline. `dev --no-restart` skips this.
- **Results before the final re-apply.** At the end the order is: stop load, restore `src/.env`, analyze, print `Run folder: ...`, then `docker compose up -d` to apply the original settings. That last step can take minutes; the results are already on disk, so a second Ctrl+C there loses nothing. If it fails, the tool prints the exact command to run.
- **nginx after every `up`.** nginx resolves its upstream containers once, at start. A recreated container can come back with a new IP and nginx would keep proxying to the old one (HTTP 502). The tool restarts `epicstaff-nginx` after every `docker compose up` it runs; do the same after every `up` you run by hand.

---

## A. Developer laptop

Use this for before/after checks of a code change. Laptop numbers are only comparable with other runs on the same laptop.

### A1. Prerequisites

- Docker Desktop, running.
- Python 3.11 or newer on the host (`python --version` on Windows, `python3 --version` on Linux/macOS). The benchmark itself needs only the standard library.
- PyYAML for `scripts/envtool.py`:

  ```powershell
  python -m pip install pyyaml          # Windows
  ```
  ```bash
  python3 -m pip install pyyaml         # Linux / macOS
  ```

`make` targets exist (`make env-update DEV=1`, `make bench-flow`, `make bench-dev ARGS='...'`), but this runbook uses the Python commands because Windows usually has no `make`.

### A2. `src/.env`

Existing `src/.env` (adds only the variables it lacks; existing lines are never changed):

```powershell
python scripts/envtool.py --update --dev
```

No `src/.env` yet: `python scripts/envtool.py --dev` (this overwrites the file).

Then:

1. Read the `needs a value:` list it prints. Fill every variable from that list that compose requires. `--update` appends them as commented placeholders (`# NAME=<enter your value>`): uncomment the line and set a value. With the dev profile almost everything has a default (the auditor's `AUDITOR_INGEST_API_KEY` and `AUDIT_JWT_SECRET`, and `OPENSEARCH_PASSWORD` get dev values), but a variable that was already in your `.env` with an empty value stays empty. `CREW_PORT` is always listed and is unused; ignore it.
2. The dev profile sets `SANDBOX_REQUIRE_SIGNAL_ISOLATION=false`. Docker Desktop's WSL2 kernel is older than 6.12 (no Landlock ABI 6), and with `true` the sandbox refuses every Python node. Keep `false` on a laptop.
3. Optional, recommended: in `src/.env` set the four log levels to `BENCH`:

   ```
   DJANGO_LOG_LEVEL=BENCH
   CREW_LOG_LEVEL=BENCH
   AGENT_LOG_LEVEL=BENCH
   SANDBOX_LOG_LEVEL=BENCH
   ```

   The `dev` case sets exactly these through its `[env]`. When `src/.env` already has them, the run changes nothing and no container is recreated at the start and end of each run.

### A3. Start the stack

```powershell
cd src
docker compose up -d --build
docker compose restart epicstaff-nginx
cd ..
```

Open the UI (`http://localhost`) and log in.

### A4. API key and `~/.epicstaff-bench.env`

1. In the UI, open your profile → **API keys** and create a key. The key belongs to your user; the benchmark sends it together with an organization id.
2. Write it to `~/.epicstaff-bench.env`. The tool reads `BENCH_API_KEY`, `BENCH_ORG_ID`, `BENCH_API` and `BENCH_RESULTS_REPO` from that file when they are not exported; every other name in it is ignored.

   PowerShell (Windows PowerShell 5.1 writes a BOM with `-Encoding utf8`, which breaks the first variable name, so use ASCII):

   ```powershell
   Set-Content -Encoding ascii -Path "$HOME\.epicstaff-bench.env" -Value 'BENCH_API_KEY=<your API key>'
   ```

   Linux / macOS:

   ```bash
   printf 'BENCH_API_KEY=%s\n' '<your API key>' > ~/.epicstaff-bench.env
   chmod 600 ~/.epicstaff-bench.env
   ```

3. Organization: without `BENCH_ORG_ID` the tool uses the stack's default organization (read from Postgres) and prints `organization: id <N> (default)`. Add `BENCH_ORG_ID=<org id>` as a second line only when your key's user is not a member of the default organization.

### A5. Payload flow

```powershell
python benchmark/bench.py flow import
```

Expected output: `payload flow: id <id> (created) "<name>"`. It imports the committed export `benchmark/flows/payload.json`: 6 Python nodes, the first generates a 300 KB payload and the others pass it on (no LLM, no RAG). You need this once; `dev`, `run`, `smoke` and `preflight` import it by themselves when it is missing and reuse it otherwise (`benchmark/.flow-cache.json`). Running `flow import` again replaces the flow with new node ids, and runs before and after that show "different workload".

### A6. Quick check

```powershell
python benchmark/bench.py dev --sessions 20 --concurrency 5 --note "quick check"
```

Options:

| Option | Effect |
|---|---|
| `--sessions N` | Sessions to start (default 100 from `benchmark/cases/dev.toml`). |
| `--concurrency N` | Sessions in flight at once (default 25). |
| `--no-build` | Skip `docker compose up --build`'s build. Faster, but your code change may not be in the images; the run gets the label `build-unverified`. |
| `--no-restart` | Do not restart `django_app crew agent sandbox knowledge_new` before measuring. Faster, less clean baseline. |
| `--note "..."` | Free text stored in `meta.json`; write what you changed. |
| `--graph payload=<id>` | Use an existing flow instead of the imported one. |

The tool prints a status line every 2 s and ends with `Run folder: benchmark/results/<folder>`. Pre-flight prints `⚠ src/.env looks like the dev profile (...)`: expected on a laptop, see troubleshooting.

### A7. Before/after comparison

```powershell
python benchmark/bench.py dev --note "before: <what>"
# change the code
python benchmark/bench.py dev --note "after: <what>"
python benchmark/bench.py compare benchmark/results/<before-folder> benchmark/results/<after-folder>
```

Keep the build on for the "after" run (no `--no-build`), or the containers still run the old code. The newest folders:

```powershell
Get-ChildItem benchmark\results -Directory | Sort-Object Name | Select-Object -Last 2 -ExpandProperty Name
```
```bash
ls -1 benchmark/results | tail -2
```

`compare` treats the first folder as the baseline and prints Δ % for the others. `!! different workload` means the case or a graph hash differs (see METRICS.md); the numbers are then not comparable.

### A8. Comparing with an older branch

```powershell
python benchmark/bench.py run dev --ref <branch> --no-smoke --note "baseline: <branch>"
```

The runner checks `<branch>` out in a temporary git worktree, builds and starts its images, and names the variant `default-adhoc`. `--no-smoke` skips the smoke step, which adds minutes and fails on a branch without BENCH checkpoints. Things to know:

- A branch without checkpoints runs in fallback mode (label `fallback-control:payload`): no per-node or per-stage times, only end-to-end.
- Pre-flight checks `src/.env` against that branch's `docker-compose.yaml`; it names any variable the branch requires that your `.env` lacks.
- The graph hash comes from that branch's API answer; if the API changed between branches the hash differs and the runs show "different workload" even for the same flow.
- If importing the payload flow fails on the old branch, pass an existing flow with `--graph payload=<id>`.
- Afterwards the stack still runs the branch's images. Go back to your code:

  ```powershell
  cd src
  docker compose up -d --build
  docker compose restart epicstaff-nginx
  cd ..
  ```

### A9. Viewing

Open `benchmark/viewer.html` in a browser (double-click the file). Press **Open run folders…** and pick one run folder or `benchmark/results/` itself, or drop folders on the "or drop run folders here" box. Tick the runs to compare; the first ticked run is the baseline, change it with the **Baseline** radio button. Opened from disk the page cannot load `index.json`; the message about it is expected.

### A10. What to check

- `steps.csv`: one row. `completed` should equal `--sessions`, `failed` and `interrupted` should be 0. `e2e_s_p50` / `e2e_s_p95` are the session times.

  ```powershell
  Import-Csv benchmark\results\<folder>\steps.csv | Format-List
  ```
- `nodes.csv`: per node `count`, `p50_s`, `p95_s`, `error_count`. A node whose p50 moved between before and after is where your change acted.

  ```powershell
  Import-Csv benchmark\results\<folder>\nodes.csv | Format-Table node_name,count,p50_s,p95_s,error_count
  ```
- `meta.json` → `labels`: `build-unverified`, `dirty-tree`, `fallback-control:*` explain why two runs may differ.

On a laptop, read differences below about 10 % as noise unless they repeat.

### A11. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `BENCH_API_KEY is not set: ...` | No key exported and none in `~/.epicstaff-bench.env`. Create the file (A4). On Windows check it has no BOM: write it with `Set-Content -Encoding ascii`. |
| `set BENCH_API_KEY to your org API key ...; DJANGO_API_KEY is Django's system key and is not read` | The key is stored under the old name `DJANGO_API_KEY` (exported or in the file). Rename it to `BENCH_API_KEY`. |
| `HTTP 403: the API key's owner is not a member of the default organization <N>; set BENCH_ORG_ID ...` | The key's user is not in the default organization. Add `BENCH_ORG_ID=<your org id>` to `~/.epicstaff-bench.env`. |
| `no default organization: run ... create_superadmin or set BENCH_ORG_ID` / `could not read the default organization from Postgres` | Fresh database, or `crewdb` is not running. Start the stack, create the admin, or set `BENCH_ORG_ID`. |
| `src/.env.bench-backup exists: a previous run did not restore .env` | A run was killed hard before restoring `src/.env`. Compare the two files, then move the backup back: `Move-Item -Force src\.env.bench-backup src\.env` (bash: `mv src/.env.bench-backup src/.env`). |
| `src/.env does not set X, Y, which docker-compose.yaml requires` | Run `python scripts/envtool.py --update --dev` and fill the listed variables (A2). |
| Preflight or `preflight` command exits with code 2 | Every `✗` line is an error; fix each one. Host errors (docker not reachable, leftover backup) and `.env` errors stop before the stack is checked. |
| `smoke failed: payload: N of M sessions did not end cleanly` and the Python node's error mentions `Sandbox signal isolation unavailable` | `SANDBOX_REQUIRE_SIGNAL_ISOLATION=true` on a kernel older than 6.12. Set it to `false` in `src/.env` (laptop only), then `docker compose up -d` in `src` and restart nginx. |
| HTTP 502 from the UI or `HTTP 502` in the tool | nginx proxies to an old container IP. `docker compose restart epicstaff-nginx` (in `src`). |
| `⚠ src/.env looks like the dev profile (DJANGO_DEBUG=true, ...)` | Warning, not an error. The numbers include debug overhead (Django debug mode, debug logging). Fine for before/after on the same laptop; never compare them with server runs. |
| `⚠ BENCH not active on <service>` | That service's log level is not `BENCH`, `DEBUG` or `TRACE`; its checkpoints are missing from the run. |
| `phase payload: N sessions still pending/run — wait or stop them` | Sessions of that flow are still running from an earlier run. Wait, or stop them in the UI. |

---

## B. Benchmark server (Linux)

The server run measures capacity: how many sessions run at once before the pass rules break, and what breaks first. Watch the first run on a new server.

### B1. Prerequisites

```bash
sudo apt-get install -y python3 python3-yaml tmux git     # Debian/Ubuntu; python3 must be >= 3.11
python3 --version
sudo usermod -aG docker "$USER"                            # then log out and back in
docker info >/dev/null && echo docker ok
```

Clone EpicStaff and check out the branch to measure.

### B2. Kernel and sandbox signal isolation

```bash
uname -r
```

After the stack is up (B4), check the Landlock ABI the sandbox sees:

```bash
cd src
docker compose exec sandbox python -c "import ctypes; print(ctypes.CDLL(None, use_errno=True).syscall(444,0,0,1))"
cd ..
```

| Output | Setting in `src/.env` |
|---|---|
| `6` or higher (kernel 6.12+) | Keep `SANDBOX_REQUIRE_SIGNAL_ISOLATION=true`. |
| Lower than 6, or `-1` (no Landlock) | `SANDBOX_REQUIRE_SIGNAL_ISOLATION=false`, otherwise every Python node is refused. Executions can then signal each other: the server must not hold real data. |

### B3. `src/.env`

New server: `python3 scripts/envtool.py` (production profile). Existing `.env`: `python3 scripts/envtool.py --update`. Never `--dev` on a server: debug overhead makes the numbers incomparable, and pre-flight warns about it.

1. Check `DJANGO_DEBUG=False` (the production default is `false`; either spelling is read as false).
2. Fill every variable listed under `needs a value:` that compose requires (uncomment the `# NAME=<enter your value>` line). `CREW_PORT` is unused; ignore it. Generate secrets with:

   ```bash
   openssl rand -hex 32
   ```

   Use that for keys, passwords and user names alike (`DJANGO_SECRET_KEY`, `DB_PASSWORD`, `AUDITOR_INGEST_API_KEY`, `AUDIT_JWT_SECRET`, ...). `OPENSEARCH_PASSWORD` must contain upper case, lower case, a digit and a symbol, for example:

   ```bash
   echo "OPENSEARCH_PASSWORD=Aa1-$(openssl rand -hex 16)"
   ```
3. Set `SANDBOX_REQUIRE_SIGNAL_ISOLATION` as B2 says.
4. The production profile sets `NGINX_SSL_MODE="on"`: nginx then needs certificates in `src/nginx/certs/` (`docs/setup/ssl.md`) and redirects HTTP to HTTPS. The tool talks to `BENCH_API` (default `http://localhost`); see the note under B5.
5. `chmod 600 src/.env`

### B4. Start the stack

```bash
cd src
docker compose up -d --build
docker compose restart epicstaff-nginx
cd ..
```

Then run the B2 check.

### B5. API key and `~/.epicstaff-bench.env`

Create an API key in the UI (profile → **API keys**) for a user who is a member of the benchmark organization.

```bash
cat > ~/.epicstaff-bench.env <<'EOF'
BENCH_API_KEY=<API key>
BENCH_RESULTS_REPO=~/epicstaff-benchmarks
EOF
chmod 600 ~/.epicstaff-bench.env
```

- Add `BENCH_ORG_ID=<org id>` only when the benchmark organization is not the server's default organization.
- Add `BENCH_API=<base URL>` when the API is not reachable at `http://localhost`. With `NGINX_SSL_MODE="on"`, `http://localhost` answers with a redirect to HTTPS; point `BENCH_API` at the HTTPS name the certificate is valid for. (Not verified end to end: if the tool's requests fail against HTTPS with a self-signed certificate, a benchmark-only server can run with `NGINX_SSL_MODE="off"`; write that into `--note`.)

The tool warns when this file is readable by other users.

### B6. Results repository (once)

`bench push` commits run folders to `EpicStaff/epicstaff-benchmarks` through a deploy key that only this server has.

1. Key:

   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/epicstaff_benchmarks -N "" -C "epicstaff benchmarks"
   cat ~/.ssh/epicstaff_benchmarks.pub
   ```
2. GitHub → `EpicStaff/epicstaff-benchmarks` → **Settings** → **Deploy keys** → **Add deploy key**. Paste the public key and tick **Allow write access** (needs repo admin).
3. `~/.ssh/config`:

   ```
   Host github-benchmarks
     HostName github.com
     User git
     IdentityFile ~/.ssh/epicstaff_benchmarks
     IdentitiesOnly yes
   ```

   Test: `ssh -T github-benchmarks` (answers with a "successfully authenticated" line). If port 22 is blocked use `HostName ssh.github.com` and `Port 443`.
4. Clone and set the commit identity:

   ```bash
   git clone github-benchmarks:EpicStaff/epicstaff-benchmarks.git ~/epicstaff-benchmarks
   git -C ~/epicstaff-benchmarks config user.name "EpicStaff Benchmarks"
   git -C ~/epicstaff-benchmarks config user.email "<address>"
   ```
5. **Empty repository only:** `bench push` starts with `git pull --ff-only`, which fails on a repository without commits. Make one initial commit on `main` first:

   ```bash
   cd ~/epicstaff-benchmarks
   git symbolic-ref HEAD refs/heads/main
   cp <path to the results-repo README> README.md      # or any small file
   git add README.md
   git commit -m "docs: results repository readme"
   git push -u origin main
   cd -
   ```

### B7. Flows

- **Payload flow:** `python3 benchmark/bench.py flow import` once (or let the first `preflight` / `run` import it). It prints the flow id.
- **Agent flow (phase `complex`):** build it in the UI on this server: agents, its LLM config with a working provider key, and its RAG collection. Note its graph id (the number in the flow's URL). Pass it on every command with `--graph complex=<id>`, or write it into your copy of the case:

  ```toml
  [[phase]]
  name = "complex"
  graph_id = 18
  pass = { p95_e2e_s = 300 }
  ```

  The graph id is not part of the case hash, so setting it does not make runs incomparable. Editing the flow in the UI does: the graph hash changes and the viewer shows "different workload".

Without a `complex` id, `run`, `smoke` and `dev` on `server.toml` stop with `case error: ... phase 'complex' needs a positive integer graph_id`. `plan` and `preflight` still work: `plan` prints `phase complex: graph id: set with --graph complex=<id>` in place of an id, and `preflight` reports that line as an error (`✗`, exit 2) but still runs every other check, for the payload phase too, so you can fix the stack before you have the agent flow.

### B8. A payload-only case and the ladder

To measure only the payload flow, copy the case outside the repository and delete the whole `complex` `[[phase]]` block (the `[[phase]]` line, `name = "complex"`, `graph_id`, `pass`):

```bash
mkdir -p ~/bench-cases
cp benchmark/cases/server.toml ~/bench-cases/server-payload.toml
nano ~/bench-cases/server-payload.toml
```

A case argument that is an existing file is used as a path, so pass `~/bench-cases/server-payload.toml` to every command. Its case hash differs from `server.toml`: compare payload-only runs with payload-only runs.

**Ladder.** A level is the number of sessions **in flight at the same time**, not a total. The runner keeps exactly that many running: when one ends, it starts the next. The total sessions per level is roughly throughput × (settle + hold + finish time).

| Key | Meaning |
|---|---|
| `start` | First level. |
| `factor` | Next level = `round(level × factor)`. |
| `max` | No level above this. |
| `bisect_steps` | After the first non-passing level, up to this many probes halfway between the last pass and the first fail (stops early when the gap is 10 % or less). |

Example: skip the low levels on a large server and probe 625, 1250, 2500, 5000:

```toml
[ladder]
start = 625
factor = 2
max = 5000
bisect_steps = 2
```

Changing the ladder changes the case hash. Check the levels and the worst-case duration before running:

```bash
python3 benchmark/bench.py plan ~/bench-cases/server-payload.toml
```

### B9. Full run order

```bash
python3 benchmark/bench.py preflight server --graph complex=<id>
python3 benchmark/bench.py plan server --graph complex=<id>
tmux new -s bench
python3 benchmark/bench.py run server --graph complex=<id> --note "<branch>: <what this run is for>"
```

(For the payload-only case use `~/bench-cases/server-payload.toml` instead of `server` and drop `--graph`.)

1. **preflight**: host, `.env` and stack checks, no load. Exit 0 and `preflight ok` (or only `⚠` warnings) before you continue. The `no container memory limit` warning means a container has no memory limit (see B10).
2. **plan**: prints the levels per phase and the worst-case duration. Make sure you can leave the server alone that long.
3. **run** inside tmux. The run order per variant: pre-flight, `.env` override and `docker compose up -d --build`, flow import if needed, the smoke step, then per phase the ladder and bisect, cleanup, analysis, `Run folder: ...`, and the final re-apply.
   - Detach: `Ctrl+B`, then `D`. The run continues.
   - Re-attach: `tmux attach -t bench`.
   - Optional log file: run it as `python3 -u benchmark/bench.py run ... 2>&1 | tee -i ~/bench-$(date +%F_%H%M).log` (`-u` so lines are not buffered, `-i` so Ctrl+C reaches only the benchmark, not `tee`).
4. **Ctrl+C** (once): stops sending, stops in-flight sessions (status `interrupted`), deletes the phase's sessions, restores `src/.env`, writes and prints the run folder with the label `interrupted`, skips remaining variants, runs the final re-apply and exits 130. A second Ctrl+C during the final re-apply leaves the stack on the run's settings: run `docker compose up -d` and restart nginx in `src` by hand. Exit 3 means the smoke step failed (no run folder; the reason is printed).

### B10. Safety

- **The compose file sets no container limits** (only the sandbox has 2 GB). Without the two layers below, a level that overloads the stack can push the whole host into OOM, and the kernel may kill anything, including Docker or sshd.
  - **Cap Docker as a whole** with a systemd slice, so the kernel kills containers, never sshd or the OS. Create `/etc/systemd/system/docker-limited.slice` with `[Slice]` `MemoryMax=40G` (`MemoryHigh` a little lower, `CPUQuota` one core below the host's), set `"cgroup-parent": "docker-limited.slice"` in `/etc/docker/daemon.json`, then `sudo systemctl daemon-reload && sudo systemctl restart docker` and `docker compose up -d`. Size it to leave the OS a few GB and one core.
  - **Cap each container** in `src/docker-compose.override.yaml` (gitignored, host-specific): `services: <name>: mem_limit: 4g`. Plain `docker compose` loads that file on its own and the benchmark adds it to every compose call, so both run with the same limits; the run's `meta.json` records them under `container_limits`. Use memory limits only: a CPU limit changes what the run measures (the bottleneck becomes the limit).
- **Host-RAM guard.** If available host RAM drops below `abort.host_min_available_ram_pct` (5 %) during a level, the level stops sending and fails. Sessions already running continue until they end or hit `session_timeout_s` (900 s) in the drain; the guard does not kill them. Other aborts: any container restart or OOM kill, and an error rate of 5 % or more over 30 s.
- Check limits (0 = no limit):

  ```bash
  docker inspect -f '{{.Name}} mem={{.HostConfig.Memory}} cpus={{.HostConfig.NanoCpus}}' $(docker ps -q)
  ```
- Watch from a second tmux window (`Ctrl+B`, `C`):

  ```bash
  docker stats
  free -h
  sudo dmesg -T | grep -i oom
  ```

### B11. Optional: more Postgres connections

When runs fail with the bottleneck `Postgres connections at 9x% of max`, raise the limit. This changes the system under test: write it into `--note` of every run that uses it.

```bash
cd src
docker compose exec crewdb sh -c 'psql -U "$POSTGRES_USER" -d postgres -c "ALTER SYSTEM SET max_connections = 300"'
docker compose restart crewdb
docker compose restart
docker compose restart epicstaff-nginx
docker compose exec crewdb sh -c 'psql -U "$POSTGRES_USER" -d postgres -tAc "show max_connections"'
cd ..
```

The setting lives in the database volume and survives container recreation. Undo with `ALTER SYSTEM RESET max_connections` and the same restarts.

### B12. After the run

1. **Compare** with an earlier run (first folder = baseline):

   ```bash
   python3 benchmark/bench.py compare benchmark/results/<baseline> benchmark/results/<new>
   ```
2. **Inspect** the levels:

   ```bash
   column -s, -t < benchmark/results/<new>/steps.csv | less -S
   ```

   Arrow keys scroll sideways, `q` quits. `column` can shift cells when a value is empty or contains a comma; the viewer shows the same data exactly. Read `verdict`, `fail_reasons` and `bottleneck` of the first non-passing row.

   In the viewer start with **Findings** at the top of the Verdicts tab (`findings.csv`; rules in docs/METRICS.md). Critical first: timed-out sessions with the checkpoint where they hung, aborts, container restarts. Then warnings: a throughput plateau (the level where adding sessions stopped adding throughput), one stage taking most of the session time, memory not released after cooldown, invalid levels. Select a finding to open its tab; a Timeline finding moves the crosshair to its moment, where the in-flight-by-stage chart shows where the sessions were.
3. **Push** to the results repository:

   ```bash
   python3 benchmark/bench.py push benchmark/results/<new>
   ```

   It refuses a run folder that contains the API key, requires a clean clone, runs `git pull --ff-only`, prints the run numbers and the exact `git add` / `git commit` / `git push` commands, and runs them only after you answer `y`. `events_full.csv.gz` is never pushed.
4. **View**, on any machine with read access:

   ```bash
   git clone git@github.com:EpicStaff/epicstaff-benchmarks.git
   cd epicstaff-benchmarks
   python3 -m http.server 8000
   ```

   Open `http://localhost:8000/`. The run list loads by itself (press **Load index.json** if it does not). Tick runs to compare; the first ticked is the baseline, change it with the **Baseline** radio button.

### B13. Comparing branches on the server

```bash
python3 benchmark/bench.py run server --graph complex=<id> --ref <branch-or-sha> --note "baseline: <branch>"
```

The ref is built in a temporary worktree, the variant is named `default-adhoc`, and `meta.json` records that ref and sha. The A8 notes apply (fallback mode on branches without checkpoints, `.env` checked against that branch's compose file, graph hash from that branch's API). Measure both branches on the same server, with the same case file and the same Postgres settings, close together in time. Afterwards return the stack to the checkout's code with `docker compose up -d --build` and `docker compose restart epicstaff-nginx` in `src`.
