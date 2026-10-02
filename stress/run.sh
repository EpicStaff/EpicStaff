#!/usr/bin/env bash
# Stress benchmark runner (see stress/README.md). Run from anywhere on the server host.
#
#   bash stress/run.sh prepare                    once per deploy: bench log files + permissions
#   bash stress/run.sh single <graph-id> [args]   one message per session at fixed rates (bench.py)
#   bash stress/run.sh chat   <graph-id> [args]   multi-turn conversations (conversation.py)
#   bash stress/run.sh all    <graph-id>          single, then chat
#
# [args] are passed through and override the defaults below, e.g. a dry run:
#   bash stress/run.sh single 42 --rates 2 --step-minutes 2 --cooldown-minutes 1
# Needs DJANGO_API_KEY in the environment. Every run is analyzed as soon as it ends.
set -euo pipefail
cd "$(dirname "$0")/.."

LOGS=src/bench_logs
BIG_MESSAGE=stress/chat/big_message.json
CONVERSATION=stress/chat/conversation.json
SINGLE_DEFAULTS=(--rates 10,25,50 --step-minutes 5 --cooldown-minutes 5)
CHAT_DEFAULTS=(--users 20 --users-per-minute 10 --cooldown-minutes 5)

usage() { sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
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
  single)
    need_key; need_graph "${2:-}"; graph=$2; shift 2
    variables=()
    if [ -f "$BIG_MESSAGE" ]; then
      variables=(--variables-file "$BIG_MESSAGE")
    else
      echo "note: $BIG_MESSAGE not found, sessions use the start node's default context"
    fi
    python3 stress/bench.py --graph-id "$graph" "${variables[@]}" "${SINGLE_DEFAULTS[@]}" "$@"
    analyze_latest
    ;;
  chat)
    need_key; need_graph "${2:-}"; graph=$2; shift 2
    [ -f "$CONVERSATION" ] || { echo "missing $CONVERSATION: copy stress/chat/ to the server (it is not in git)"; exit 1; }
    python3 stress/conversation.py --graph-id "$graph" "${CHAT_DEFAULTS[@]}" "$@"
    analyze_latest
    ;;
  all)
    need_graph "${2:-}"
    bash "$0" single "$2"
    bash "$0" chat "$2"
    ;;
  *)
    usage
    ;;
esac
