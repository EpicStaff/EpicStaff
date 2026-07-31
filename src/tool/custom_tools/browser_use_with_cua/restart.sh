#!/bin/sh
set -e

pkill -f x11vnc    || true
pkill -f Xvfb      || true
pkill -f startxfce4 || true

sleep 2

/app/entrypoint.sh "$@" > /dev/null 2>&1 &

echo "Browser-Use restarted in background"
exit 0