#!/bin/sh
set -e

CONFIG_PATH="/usr/share/nginx/html/config.json"

# Normalize an env flag to a JSON boolean. The shared .env uses Python-style
# values (True/False), which would make config.json invalid JSON and silently
# drop the frontend back to its build-time defaults for every field.
# Only "true" (any case) counts as on - the same rule src/auditor/entrypoint.sh
# uses to decide whether the auditor starts, so the UI never offers a dead page.
to_json_boolean() {
  case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
    true) echo true ;;
    *) echo false ;;
  esac
}

# If a config file is already mounted, keep it and avoid overwriting.
if [ -f "$CONFIG_PATH" ] && [ -s "$CONFIG_PATH" ]; then
  echo "Existing config.json found; skipping generation."
else
  echo "Generating config.json..."
  cat <<EOF > $CONFIG_PATH
{
  "apiUrl": "${API_URL}",
  "realtimeApiUrl": "${REALTIME_API_URL}",
  "auditorUrl": "${AUDITOR_API_URL}",
  "isEpicChatEnabled": $(to_json_boolean "${EPIC_CHAT_ENABLED:-true}"),
  "isAuditTrailEnabled": $(to_json_boolean "${AUDIT_TRAIL_ENABLED:-false}")
}
EOF
  echo "Config generated:"
  cat $CONFIG_PATH
fi

exec "$@"
