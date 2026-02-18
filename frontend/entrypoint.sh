#!/bin/sh
set -e

CONFIG_PATH="/usr/share/nginx/html/config.json"

# If a config file is already mounted, keep it and avoid overwriting.
if [ -f "$CONFIG_PATH" ] && [ -s "$CONFIG_PATH" ]; then
  echo "Existing config.json found; skipping generation."
else
  echo "Generating config.json..."
  cat <<EOF > $CONFIG_PATH
{
  "apiUrl": "${API_URL:-http://127.0.0.1/api/}",
  "realtimeApiUrl": "${REALTIME_API_URL:-http://127.0.0.1/realtime/}"
}
EOF
  echo "Config generated:"
  cat $CONFIG_PATH
fi

exec "$@"
