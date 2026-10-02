# Stress benchmark

Open-loop session load + per-checkpoint timing logs + container memory sampling for one flow.
Design: `docs/superpowers/specs/2026-10-02-stress-test-benchmark-design.md` (local only).

## Prerequisites (server host)

- Stack up from this branch: compose bind-mounts `src/bench_logs` into django, crew, agent, sandbox.
- `python3` (3.12, standard library only) and `docker stats` access (`docker` group).
- `export DJANGO_API_KEY='<org API key>'` in the shell. Never write it into a file.
- Flow-specific data in `stress/chat/` (gitignored, copy it to the server by hand):
  - `big_message.json`: `{"context": {...}}` sent as run-session `variables` (deep-merged over the start node).
  - `conversation.json`: `{"turns": ["Hi", "...", ...]}` played by every user, one session per message.

## Run

    bash stress/run.sh prepare                    # once per deploy (sudo if docker created src/bench_logs)
    bash stress/run.sh single <graph-id>          # 10, 25, 50 sessions/min, 5 min each, 5 min cooldown
    bash stress/run.sh chat   <graph-id>          # 20 users, 10 new users/min, every user plays all turns
    bash stress/run.sh all    <graph-id>          # single, then chat

Extra arguments override the defaults. Dry run first:

    bash stress/run.sh single <graph-id> --rates 2 --step-minutes 2 --cooldown-minutes 1
    bash stress/run.sh chat   <graph-id> --users 2 --cooldown-minutes 1

Ctrl+C stops the load early and still saves and analyzes everything. Let sessions drain before the next run.

## Output

Each run lands in `stress/runs/<YYYYmmdd-HHMMSS>/`:
`config.json`, `fired.jsonl` (one line per session started), `memory.csv` (every 2 s per container),
`services/*.jsonl` (checkpoint logs), `turns.jsonl` (chat runs only) and `summary.json`.

`summary.json` is self-contained and is the only file the results page needs. Re-create it any time:

    python3 stress/analyze.py stress/runs/<dir>
    python3 stress/analyze.py --self-test

Key fields per step: `queue_wait_s` (waiting for a crew slot, cap `CREW_MAX_CONCURRENT_SESSIONS`),
`agent_queue_wait_s` (waiting for the agent service to pick the request up), `run_time_s`,
`llm_time_share`, `tokens_per_session`, `failed_reasons`; per container: `mb_per_session`, `r2`,
`peak_mb`, `leak_mb`. Fixed-rate runs get `verdict.max_sustained_rate`; chat runs get `conversation`
(users finished, where they stopped, turn time vs history length) instead.
