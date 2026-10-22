#!/usr/bin/env bash
set -euo pipefail

# >>> env_bool
# Strict boolean environment flag, accepting exactly the values Env.bool accepts
# (src/shared/envtools.py). Copied verbatim into every script that needs it;
# .github/scripts/check_env_conventions.py fails CI if the copies or the values drift.
# Usage: if env_bool NAME [DEFAULT]; then ...; fi
# Returns 0 for true and 1 for false. DEFAULT applies only when NAME is unset.
# An unset NAME without DEFAULT, or any other value, exits the script with 64.
env_bool() {
  eval "env_bool_is_set=\${$1+set}"
  if [ -n "$env_bool_is_set" ]; then
    eval "env_bool_value=\${$1}"
  elif [ $# -ge 2 ]; then
    env_bool_value=$2
  else
    echo "ERROR: environment variable $1 is not set." >&2
    exit 64
  fi
  case "$(printf '%s' "$env_bool_value" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | tr '[:upper:]' '[:lower:]')" in
    1|on|t|true|y|yes) return 0 ;;
    0|f|false|n|no|off) return 1 ;;
  esac
  echo "ERROR: environment variable $1='$env_bool_value' is not a boolean. Use one of 1, on, t, true, y, yes for true or 0, f, false, n, no, off for false (case-insensitive)." >&2
  exit 64
}
# <<< env_bool


APP_DIR="/home/developer/EpicStaff"
COMPOSE_DIR="$APP_DIR/src"
COMPOSE_FILE="docker-compose.yaml"
NUKE_DB=${NUKE_DB:-false}
REGENERATE_ENV=${REGENERATE_ENV:-true}
IMAGE_TAG=${IMAGE_TAG:-latest}

# Parsed up front, before anything is stopped: an unrecognised value fails the
# deploy here rather than halfway through, and never resets the database.
if env_bool NUKE_DB; then nuke_db=true; else nuke_db=false; fi
if env_bool REGENERATE_ENV; then regenerate_env=true; else regenerate_env=false; fi

export IMAGE_TAG

echo ">> deploy from current checkout"
echo ">> repo dir: $APP_DIR"
echo ">> image tag: $IMAGE_TAG"
echo ">> nuke database: $NUKE_DB"
echo ">> regenerate .env: $REGENERATE_ENV"

cd "$COMPOSE_DIR"

if [ "$regenerate_env" = true ]; then
  echo ">> regenerate .env from env.yaml"
  python3 "$APP_DIR/scripts/envtool.py" --dev
else
  echo ">> Skipping .env regeneration."
fi

# deploy.env stays last so the server's overrides win. envtool.py --dev turns the chat service
# and the audit trail on (COMPOSE_PROFILES=dev,chat,auditor, CHAT_ENABLED=true,
# AUDIT_TRAIL_ENABLED=true); override the profile and its flag in deploy.env to turn one off.
# With chat on, set CHAT_PUBLIC_BASE_URL in deploy.env too: its dev default is http://localhost.
DC="docker compose --env-file .env --env-file deploy.env -f $COMPOSE_FILE"

echo ">> docker compose down"
$DC down --remove-orphans

if [ "$nuke_db" = true ]; then
  echo "⚠️  NUKE_DB is set to true. Resetting database volumes..."
  if [ -f "./nuke_db.sh" ]; then
    bash ./nuke_db.sh
  else
    docker volume rm crew_pgdata || true
    docker volume create crew_pgdata
  fi
else
  echo ">> Skipping database reset (data preserved)."
fi

echo ">> docker compose pull"
$DC pull

failed=0

echo ">> ensuring external volumes exist"
docker volume inspect opensearch_data >/dev/null 2>&1 || docker volume create opensearch_data

echo ">> docker compose up"
$DC up -d --remove-orphans || failed=1

sleep 60

echo ">> checking for crashed containers"
# A crash-looping container (restart: always) is "restarting", not "exited", and a
# failing healthcheck shows only in Health, so both count as crashed. Compose prints
# one JSON object per line (older versions: one array); read both. A parse failure or
# an empty list fails the deploy instead of passing it as "no crashes". storage-init
# is one-shot: only its clean exit is expected.
read -r -d '' CRASH_CHECK <<'PY' || true
import json
import sys

text = sys.stdin.read().strip()
if text.startswith("["):
    containers = json.loads(text)
else:
    containers = [json.loads(line) for line in text.splitlines() if line.strip()]
if not containers:
    sys.exit("no containers found")
for container in containers:
    service, state, health = container["Service"], container["State"], container.get("Health")
    if service == "storage-init" and state == "exited" and container.get("ExitCode") == 0:
        continue
    if state in ("exited", "restarting", "dead") or health == "unhealthy":
        print(f"{service} (state={state}, health={health or 'none'})")
PY
if ! CRASHED=$($DC ps --all --format json | python3 -c "$CRASH_CHECK"); then
  echo "Could not read container states"
  failed=1
elif [ -n "$CRASHED" ]; then
  echo "Crashed services:"
  echo "$CRASHED"
  failed=1
fi

echo ">> last logs"
$DC logs --tail=50 --no-color || true

echo ">> docker compose ps"
$DC ps || true

if [ "$failed" = "1" ]; then
  echo "Deploy failed"
  exit 1
fi

echo ">> docker image prune"
docker image prune -f || true

echo "Deploy succeeded"
