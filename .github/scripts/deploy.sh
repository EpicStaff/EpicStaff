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
CRASHED=$($DC ps --status exited --format json \
  | python3 -c "import sys,json; services=[c['Service'] for c in json.load(sys.stdin) if c['Service'] != 'storage-init']; print('\n'.join(services))" 2>/dev/null || true)
if [ -n "$CRASHED" ]; then
  echo "Crashed services: $CRASHED"
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
