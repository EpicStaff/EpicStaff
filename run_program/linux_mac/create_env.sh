#!/bin/bash
set -euo pipefail

RUN_DIR="$(dirname "$0")/.."
ENV_FILE="$RUN_DIR/.env"
SIGNING_FILE="$RUN_DIR/.signing.env"

echo "CREW_SAVEFILES_PATH=\"$(pwd)/savefiles/\"" > "$ENV_FILE"

grep -E '^(SECRET_KEY|JWT_SECRET)=.' "$SIGNING_FILE" > "$SIGNING_FILE.new" 2>/dev/null || true

# Generate whichever key is still missing.
grep -q '^SECRET_KEY=' "$SIGNING_FILE.new" || echo "SECRET_KEY=$(openssl rand -base64 48 | tr -d '=+/')" >> "$SIGNING_FILE.new"
grep -q '^JWT_SECRET=' "$SIGNING_FILE.new" || echo "JWT_SECRET=$(openssl rand -base64 48 | tr -d '=+/')" >> "$SIGNING_FILE.new"

mv "$SIGNING_FILE.new" "$SIGNING_FILE"
chmod 600 "$SIGNING_FILE" 2>/dev/null || true

echo "Environment written to $ENV_FILE"
echo "Signing keys kept in $SIGNING_FILE (generated once, reused afterwards)"
