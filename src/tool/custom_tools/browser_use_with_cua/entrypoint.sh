#!/bin/sh
set -e

: "${DISPLAY:=:99}"
: "${VNC_GEOMETRY:=1600x900}"
: "${VNC_PASS:=secret}"
: "${MCP_HOST:=0.0.0.0}"
: "${MCP_PORT:=8080}"

Xvfb "$DISPLAY" -screen 0 "${VNC_GEOMETRY}x24" -listen tcp -ac &

for i in {1..20}; do
  if xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
    break
  fi
  sleep 0.3
done

startxfce4 >/dev/null 2>&1 &

xset -display "$DISPLAY" s off -dpms || true

x11vnc -display "$DISPLAY" \
  -rfbport 5900 \
  -rfbauth /root/.vncpass \
  -forever -shared -noxdamage -nolookup -repeat \
  -listen 0.0.0.0 \
  -o /tmp/x11vnc.log &

exec "$@"