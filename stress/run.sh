#!/usr/bin/env bash
# Stress benchmark runner (see stress/README.md). Run from anywhere on the server host.
#
#   bash stress/run.sh prepare                                once per deploy: bench log files + permissions
#   bash stress/run.sh memory <label> <graph-id> <rate> [args]  RAM per session (restart services yourself first)
#   bash stress/run.sh single <graph-id> [args]               fixed rates 10,25,50/min (bench.py)
#   bash stress/run.sh chat   <graph-id> [args]               multi-turn conversations (conversation.py)
#
# [args] are passed through and override the defaults, e.g.
#   bash stress/run.sh memory flow17-simple 17 250
#   bash stress/run.sh memory flow16-chat 16 50 --cooldown-minutes 15 --variables-file stress/chat/big_message.json
# Needs DJANGO_API_KEY (and BENCH_ORG_ID if your org is not 1). Every run is analyzed as soon as it ends.
set -euo pipefail
cd "$(dirname "$0")/.."

LOGS=src/bench_logs
CONVERSATION=stress/chat/conversation.json
MEMORY_DEFAULTS=(--step-minutes 2 --cooldown-minutes 5 --warmup)
SINGLE_DEFAULTS=(--rates 10,25,50 --step-minutes 5 --cooldown-minutes 5)
CHAT_DEFAULTS=(--users 20 --users-per-minute 10 --cooldown-minutes 5)

usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
need_key() {
  [ -n "${DJANGO_API_KEY:-}" ] || { echo "DJANGO_API_KEY is not set: export DJANGO_API_KEY='<org API key>'"; exit 1; }
}
need_graph() { [[ "${1:-}" =~ ^[0-9]+$ ]] || usage; }
analyze_latest() { python3 stress/analyze.py "$(ls -td stress/runs/*/ | head -1)"; }

case "${1:-}" in
  prepare)
    if ! { mkdir -p "$LOGS" && touch "$LOGS"/{django,crew,agent,sandbox}.jsonl \
           && chmod 777 "$LOGS" && chmod 666 "$LOGS"/*.jsonl; } 2>/dev/null; then
      echo "permission denied on $LOGS (docker created it as root): run  sudo bash stress/run.sh prepare"
      exit 1
    fi
    echo "ok: $LOGS is writable by every service (agent runs as uid 1000, the rest as root)"
    ;;
  memory)
    need_key
    label=${2:-}; graph=${3:-}; rate=${4:-}
    [[ "$label" =~ ^[A-Za-z0-9._-]+$ && "$rate" =~ ^[0-9]+([.][0-9]+)?$ ]] || usage
    need_graph "$graph"; shift 4
    python3 stress/bench.py --graph-id "$graph" --rates "$rate" --label "$label" "${MEMORY_DEFAULTS[@]}" "$@"
    analyze_latest
    ;;
  single)
    need_key; need_graph "${2:-}"; graph=$2; shift 2
    python3 stress/bench.py --graph-id "$graph" "${SINGLE_DEFAULTS[@]}" "$@"
    analyze_latest
    ;;
  chat)
    need_key; need_graph "${2:-}"; graph=$2; shift 2
    [ -f "$CONVERSATION" ] || { echo "missing $CONVERSATION: copy stress/chat/ to the server (it is not in git)"; exit 1; }
    python3 stress/conversation.py --graph-id "$graph" "${CHAT_DEFAULTS[@]}" "$@"
    analyze_latest
    ;;
  *)
    usage
    ;;
esac
