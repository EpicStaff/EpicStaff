#!/bin/sh
set -e

CONFIG_PATH="/usr/share/nginx/html/config.json"

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

# If a config file is already mounted, keep it and avoid overwriting.
if [ -f "$CONFIG_PATH" ] && [ -s "$CONFIG_PATH" ]; then
  echo "Existing config.json found; skipping generation."
else
  echo "Generating config.json..."
  # Read by the same rule as nginx (src/nginx/docker-entrypoint.d/15-normalize-chat-enabled.envsh),
  # so the UI offers the chat pages exactly when nginx routes /chat/.
  if env_bool CHAT_ENABLED false; then
    chat_enabled=true
  else
    chat_enabled=false
  fi
  # Parsed by the same rule as the auditor's own entrypoint (src/auditor/entrypoint.sh),
  # so the UI never offers the audit page while the auditor exits. Written as a JSON
  # literal: the shared .env uses Python-style True/False, which would make config.json
  # invalid and silently drop the frontend back to its build-time defaults.
  if env_bool AUDIT_TRAIL_ENABLED false; then
    audit_trail_enabled=true
  else
    audit_trail_enabled=false
  fi
  cat <<EOF > $CONFIG_PATH
{
  "apiUrl": "${API_URL}",
  "realtimeApiUrl": "${REALTIME_API_URL}",
  "auditorUrl": "${AUDITOR_API_URL}",
  "isChatEnabled": ${chat_enabled},
  "chatApiUrl": "${CHAT_API_URL:-/chat/}",
  "isAuditTrailEnabled": ${audit_trail_enabled}
}
EOF
  echo "Config generated:"
  cat $CONFIG_PATH
fi

exec "$@"
