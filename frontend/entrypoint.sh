#!/bin/sh
set -e

CONFIG_PATH="/usr/share/nginx/html/config.json"

# If a config file is already mounted, keep it and avoid overwriting.
if [ -f "$CONFIG_PATH" ] && [ -s "$CONFIG_PATH" ]; then
  echo "Existing config.json found; skipping generation."
else
  # config.json takes CHAT_ENABLED unquoted, so it must be exactly `true` or `false`.
  # Accepts what Django's env.bool reads as true, plus the matching false words; anything
  # else stops the container instead of serving invalid JSON.
  # Keep in step with src/nginx/docker-entrypoint.d/15-normalize-chat-enabled.envsh.
  chat_enabled_normalized=$(printf '%s' "${CHAT_ENABLED:-false}" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' | tr '[:upper:]' '[:lower:]')
  case "$chat_enabled_normalized" in
    1 | y | yes | true | on) CHAT_ENABLED=true ;;
    0 | n | no | false | off) CHAT_ENABLED=false ;;
    *)
      echo "CHAT_ENABLED='${CHAT_ENABLED}' is not a boolean. Use true or false (also accepted, any case: 1/0, yes/no, y/n, on/off)." >&2
      exit 1
      ;;
  esac
  echo "Generating config.json..."
  cat <<EOF > $CONFIG_PATH
{
  "apiUrl": "${API_URL}",
  "realtimeApiUrl": "${REALTIME_API_URL}",
  "auditorUrl": "${AUDITOR_API_URL}",
  "isEpicChatEnabled": ${EPIC_CHAT_ENABLED:-true},
  "isChatEnabled": ${CHAT_ENABLED},
  "chatApiUrl": "${CHAT_API_URL:-/chat/}"
}
EOF
  echo "Config generated:"
  cat $CONFIG_PATH
fi

exec "$@"
