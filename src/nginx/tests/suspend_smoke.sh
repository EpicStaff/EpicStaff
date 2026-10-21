#!/usr/bin/env bash
# Checks suspending and resuming a plugin in one organization on a running stack with
# PLUGINS_ENABLED=true, as a SuperAdmin and an Org Admin do it through EpicStaff's API:
#
#   1. the organization's service-account key from the plugin's runtime file works, from a
#      throwaway curl container on the plugins network (GET /api/plugin-runtime/me/ answers 200);
#   2. suspending the plugin's grant answers 200 and the grant is `suspended`;
#   3. within 30 seconds the runtime file no longer lists the organization, and the old key gets 401;
#   4. an Org Admin's run of the plugin's flow (POST /api/run-session/) is refused with 409
#      `plugin_suspended`, naming the plugin;
#   5. resuming answers 200 and the grant is `active`;
#   6. within 30 seconds the runtime file lists the organization again with a different key, which
#      answers 200, and the old key still gets 401;
#   7. the Org Admin's run now starts (201).
#
# The grant is left active whatever happens: a failed check, an interrupt or an error ends in a
# resume if the grant is still suspended. Resuming rotates the organization's key, as any resume does.
#
# Settings, from the environment:
#   SMOKE_BASE_URL            EpicStaff's origin, as in DJANGO_FRONTEND_BASE_URL, e.g. http://epicstaff.localhost
#   SMOKE_PLUGIN              an approved, running plugin with a backend, granted to SMOKE_ORG_ID with
#                             an active grant, e.g. weather
#   SMOKE_ORG_ID              that organization's id
#   SMOKE_PLUGIN_FLOW_ID      the id of a flow of that organization that uses something the plugin
#                             owns (the sample weather creates one when it is installed)
#   SMOKE_SUPERADMIN_EMAIL    a SuperAdmin ...
#   SMOKE_SUPERADMIN_PASSWORD ... and their password (never printed, never on a command line)
#   SMOKE_ORG_ADMIN_EMAIL     an Org Admin of SMOKE_ORG_ID ...
#   SMOKE_ORG_ADMIN_PASSWORD  ... and their password
#   SMOKE_NODE_CONTAINER      optional: the plugin node's container, default es_plugins
# Arguments: extra curl options for every request to SMOKE_BASE_URL, e.g. --cacert <file> (or -k)
# for a local CA, or --connect-to ::127.0.0.1: to reach nginx without DNS entries.
#
# It sends one login request per account (EpicStaff allows 5 a minute per address and email),
# starts one session of the flow (step 7: it runs, with whatever the flow does, and is stopped at
# the end), and logs both accounts out at the end, also when it stops early.
#
# Needs Docker (it reads the runtime file as root in the node's container and runs curl in a
# container of src/docker-compose.yaml's pinned curl image) and python3. A key is never printed and
# never on a command line: it goes to curl as a header file or on its standard input, and the
# script compares sha256 digests of keys. Passwords and tokens go to curl in files.
#
# Usage:
#   SMOKE_BASE_URL=http://epicstaff.localhost SMOKE_PLUGIN=weather SMOKE_ORG_ID=3 \
#   SMOKE_PLUGIN_FLOW_ID=41 SMOKE_SUPERADMIN_EMAIL=root@example.com SMOKE_SUPERADMIN_PASSWORD=... \
#   SMOKE_ORG_ADMIN_EMAIL=ada@example.com SMOKE_ORG_ADMIN_PASSWORD=... \
#   bash src/nginx/tests/suspend_smoke.sh
set -euo pipefail

base_url=${SMOKE_BASE_URL:?set SMOKE_BASE_URL, e.g. http://epicstaff.localhost}
plugin=${SMOKE_PLUGIN:?set SMOKE_PLUGIN to an approved plugin with a backend, e.g. weather}
org_id=${SMOKE_ORG_ID:?set SMOKE_ORG_ID}
flow_id=${SMOKE_PLUGIN_FLOW_ID:?set SMOKE_PLUGIN_FLOW_ID to a flow that uses what the plugin owns}
superadmin_email=${SMOKE_SUPERADMIN_EMAIL:?set SMOKE_SUPERADMIN_EMAIL}
superadmin_password=${SMOKE_SUPERADMIN_PASSWORD:?set SMOKE_SUPERADMIN_PASSWORD}
org_admin_email=${SMOKE_ORG_ADMIN_EMAIL:?set SMOKE_ORG_ADMIN_EMAIL}
org_admin_password=${SMOKE_ORG_ADMIN_PASSWORD:?set SMOKE_ORG_ADMIN_PASSWORD}
node=${SMOKE_NODE_CONTAINER:-es_plugins}
curl_options=("$@")
tests_dir=$(cd "$(dirname "$0")" && pwd)
compose_file="$tests_dir/../../docker-compose.yaml"
wait_seconds=30

if ! printf '%s\n' "$plugin" | grep -Eq '^[a-z][a-z0-9-]{0,30}[a-z0-9]$'; then
  echo "ERROR: SMOKE_PLUGIN='$plugin' is not a plugin identifier" >&2
  exit 2
fi
for setting in "SMOKE_ORG_ID=$org_id" "SMOKE_PLUGIN_FLOW_ID=$flow_id"; do
  case "${setting#*=}" in
    '' | 0* | *[!0-9]*)
      echo "ERROR: ${setting%%=*}='${setting#*=}' is not an id" >&2
      exit 2
      ;;
  esac
done
case "$base_url" in
  http://* | https://*) ;;
  *)
    echo "ERROR: SMOKE_BASE_URL='$base_url' is not an http:// or https:// URL" >&2
    exit 2
    ;;
esac
base_url=${base_url%/}

curl_image=$(grep -Eo 'curlimages/curl:[^[:space:]]+' "$compose_file" | head -n 1)
if [ -z "$curl_image" ]; then
  echo "ERROR: no curlimages/curl image found in $compose_file" >&2
  exit 2
fi

work_dir=$(mktemp -d)
chmod 700 "$work_dir"

failures=0
pass() { echo "ok - $1"; }
fail() {
  echo "not ok - $1"
  failures=$((failures + 1))
}

# What the cleanup has to undo: set before the suspend request, so a request that failed after it
# took effect is still resumed; cleared by a resume that worked.
may_be_suspended=0
grant_id=""
session_id=""
signed_in=""

# api ACCOUNT METHOD PATH [curl arguments...]: a request to SMOKE_BASE_URL as superadmin or
# org_admin. Prints the status code; the body goes to $work_dir/body. A transport error prints 000.
api() {
  local account=$1 method=$2 path=$3 status
  shift 3
  : > "$work_dir/body"
  status=$(curl -sS -o "$work_dir/body" -w '%{http_code}' --max-time 30 -X "$method" \
    -H "@$work_dir/$account-access" -H "X-Organization-Id: $org_id" -H 'Accept: application/json' \
    -b "$work_dir/$account-cookies" \
    ${curl_options[@]+"${curl_options[@]}"} "$@" "$base_url$path" 2> "$work_dir/curl-error" || true)
  echo "$status"
}

# json_is EXPRESSION: true when the Python expression holds for the last body, parsed as `body`.
json_is() {
  python3 -c '
import json, sys
try:
    body = json.load(open(sys.argv[1], encoding="utf-8"))
    sys.exit(0 if eval(sys.argv[2]) else 1)
except (ValueError, KeyError, TypeError, IndexError, AttributeError):
    sys.exit(1)' "$work_dir/body" "$1"
}

logout_quietly() {
  local account=$1
  curl -s -o /dev/null -X POST -H "@$work_dir/$account-access" -b "$work_dir/$account-cookies" \
    ${curl_options[@]+"${curl_options[@]}"} "$base_url/api/auth/logout/" 2> /dev/null || true
}

# Leaves the grant active, stops the session this script started, and logs out.
finish() {
  local status=$?
  set +e
  if [ "$may_be_suspended" = 1 ] && [ -n "$grant_id" ] && [ -f "$work_dir/superadmin-access" ]; then
    echo "# cleanup: resuming the grant"
    if [ "$(api superadmin POST "/api/admin/plugins/$plugin/grants/$grant_id/resume/")" = 200 ]; then
      echo "the grant is active again"
    else
      echo "WARNING: could not resume grant $grant_id of $plugin; resume it by hand" >&2
    fi
  fi
  if [ -n "$session_id" ] && [ -f "$work_dir/org_admin-access" ]; then
    api org_admin POST "/api/sessions/$session_id/stop/" > /dev/null
  fi
  for account in $signed_in; do logout_quietly "$account"; done
  rm -rf "$work_dir"
  exit "$status"
}
trap finish EXIT
trap 'exit 130' INT TERM

# Stops when a later check could only fail for the same reason.
bail_out() {
  echo "Bail out! $1"
  echo "FAILED: $((failures + 1)) check(s)"
  exit 1
}

expect() { # $1 = description, $2 = expected status, $3 = actual status, $4 = Python check of the body
  if [ "$3" != "$2" ]; then
    fail "$1: status $3, expected $2 $(head -c 200 "$work_dir/curl-error" 2> /dev/null) $(head -c 200 "$work_dir/body")"
  elif [ -n "${4-}" ] && ! json_is "$4"; then
    fail "$1: unexpected body $(head -c 300 "$work_dir/body")"
  else
    pass "$1"
  fi
}

json_escape() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

# log_in ACCOUNT EMAIL PASSWORD: leaves the account's header file with its access token and its
# cookie jar in the work directory.
log_in() {
  local account=$1 email=$2 password=$3 status
  printf '{"email":"%s","password":"%s"}' "$(json_escape "$email")" "$(json_escape "$password")" \
    > "$work_dir/login.json"
  : > "$work_dir/body"
  status=$(curl -sS -o "$work_dir/body" -w '%{http_code}' --max-time 30 -X POST \
    -H 'Content-Type: application/json' -c "$work_dir/$account-cookies" \
    --data-binary "@$work_dir/login.json" \
    ${curl_options[@]+"${curl_options[@]}"} "$base_url/api/auth/login/" 2> "$work_dir/curl-error" || true)
  rm -f "$work_dir/login.json"
  [ "$status" = 200 ] || bail_out "login as the $account answered $status $(head -c 200 "$work_dir/curl-error")"
  signed_in="$signed_in $account"
  # Writes the header file; prints nothing of the token, also when it fails.
  python3 - "$work_dir/body" "$work_dir/$account-access" << 'PYTHON' || bail_out "login as the $account gave no access token"
import json, os, sys

body_path, header_path = sys.argv[1:]
try:
    with open(body_path, encoding="utf-8") as body_file:
        token = json.load(body_file)["access"]
except (OSError, ValueError, KeyError, TypeError):
    sys.exit(1)
if not isinstance(token, str) or not token:
    sys.exit(1)
descriptor = os.open(header_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="ascii") as header_file:
    header_file.write(f"Authorization: Bearer {token}\n")
PYTHON
  : > "$work_dir/body"
}

# read_key FILE: reads the organization's entry of the plugin's runtime file, as root in the node's
# container. Writes the curl header line with the key to FILE (replacing it), prints the key's
# sha256 digest and the internal API URL, one per line. Never prints the key. Exits 3 when the
# organization has no entry, 1 when the file cannot be read or is not a runtime file.
read_key() {
  local header_file=$1
  docker exec -u root "$node" cat "/run/es_plugins/$plugin/runtime.json" > "$work_dir/runtime.json" \
    2> "$work_dir/docker-error" || {
    echo "cannot read the runtime file of $plugin in $node: $(head -c 200 "$work_dir/docker-error")" >&2
    return 1
  }
  python3 - "$work_dir/runtime.json" "$org_id" "$header_file" << 'PYTHON'
import hashlib, json, os, re, sys

runtime_path, org_id, header_path = sys.argv[1:]
try:
    with open(runtime_path, encoding="utf-8") as runtime_file:
        runtime = json.load(runtime_file)
    api_url = runtime["epicstaff_api_url"].rstrip("/")
    entry = runtime["service_accounts"].get(org_id)
except (OSError, ValueError, KeyError, TypeError, AttributeError):
    # Never a traceback: it could quote the file.
    print("the runtime file is not a runtime file", file=sys.stderr)
    sys.exit(1)
if not isinstance(entry, dict):
    sys.exit(3)
key = entry.get("key", "")
if not re.fullmatch(r"esp-[A-Za-z0-9_-]{43}", key):
    print("the service account has no key of the expected shape", file=sys.stderr)
    sys.exit(1)
if os.path.exists(header_path):
    os.unlink(header_path)
descriptor = os.open(header_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="ascii") as header_file:
    header_file.write(f"Authorization: PluginKey {key}\n")
print(hashlib.sha256(key.encode("ascii")).hexdigest())
print(api_url)
PYTHON
  local status=$?
  rm -f "$work_dir/runtime.json"
  return "$status"
}

# internal HEADER_FILE: GET /plugin-runtime/me/ from the plugins network with the key in the
# header file, through the internal API listener. Prints the status code.
internal() {
  local output
  output=$(docker run --rm -i --network "$network" "$curl_image" \
    -sS --max-time 20 -H @- -H "X-Organization-Id: $org_id" -H 'Accept: application/json' \
    -o /dev/null -w '%{http_code}' "$api_url/plugin-runtime/me/" < "$1" 2> /dev/null || true)
  echo "${output:-000}"
}

# wait_for_runtime_file PREDICATE: polls until the check (a function name) holds, for up to
# $wait_seconds. Returns its result.
wait_for() {
  local waited=0
  while [ "$waited" -lt "$wait_seconds" ]; do
    if "$1"; then return 0; fi
    sleep 2
    waited=$((waited + 2))
  done
  "$1"
}

organization_left_runtime_file() {
  local status=0
  read_key "$work_dir/probe" > /dev/null 2>&1 || status=$?
  [ "$status" = 3 ]
}

# The new key differs from the old one and is the one in the file now.
new_key_listed() {
  local output status=0
  output=$(read_key "$work_dir/key-b" 2> /dev/null) || status=$?
  [ "$status" = 0 ] && [ "$(printf '%s\n' "$output" | head -n 1)" != "$digest_a" ]
}

echo "# logging in"
log_in superadmin "$superadmin_email" "$superadmin_password"
log_in org_admin "$org_admin_email" "$org_admin_password"
pass "both accounts are signed in"

status=$(api superadmin GET "/api/admin/plugins/$plugin/grants/?page_size=200")
[ "$status" = 200 ] || bail_out "listing the grants of $plugin answered $status"
grant_id=$(python3 -c '
import json, sys
with open(sys.argv[1], encoding="utf-8") as body_file:
    body = json.load(body_file)
rows = body["results"] if isinstance(body, dict) else body
print(next((row["id"] for row in rows if str(row["organization"]["id"]) == sys.argv[2]), ""))' \
  "$work_dir/body" "$org_id" 2> /dev/null || true)
[ -n "$grant_id" ] || bail_out "$plugin has no grant for organization $org_id"
grant_state=$(python3 -c '
import json, sys
with open(sys.argv[1], encoding="utf-8") as body_file:
    body = json.load(body_file)
rows = body["results"] if isinstance(body, dict) else body
print(next(row["state"] for row in rows if str(row["id"]) == sys.argv[2]))' "$work_dir/body" "$grant_id")
[ "$grant_state" = active ] || bail_out "the grant of $plugin in organization $org_id is $grant_state, not active"
pass "grant $grant_id of $plugin is active in organization $org_id"

echo "# 1. the key from the runtime file works"
status=0
output=$(read_key "$work_dir/key-a") || status=$?
[ "$status" = 0 ] || bail_out "no usable key for organization $org_id in the runtime file of $plugin"
digest_a=$(printf '%s\n' "$output" | sed -n 1p)
api_url=$(printf '%s\n' "$output" | sed -n 2p)
network=$(docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' "$node" \
  | grep -E '(^|_)plugins-network$' | head -n 1 || true)
[ -n "$network" ] || bail_out "$node is on no plugins-network"
if [ "$(internal "$work_dir/key-a")" = 200 ]; then
  pass "the key (sha256 ${digest_a%"${digest_a#????????????}"}...) answers 200 from $network"
else
  bail_out "the key does not work through the internal listener; the other checks need it"
fi

echo "# 2. suspend"
may_be_suspended=1
status=$(api superadmin POST "/api/admin/plugins/$plugin/grants/$grant_id/suspend/")
expect "suspending the grant answers 200 and the grant is suspended" 200 "$status" \
  "body['state'] == 'suspended' and 'resume' in body['allowed_actions']"

echo "# 3. the key stops working"
if wait_for organization_left_runtime_file; then
  pass "the runtime file no longer lists organization $org_id (within ${wait_seconds} s)"
else
  fail "the runtime file still lists organization $org_id after ${wait_seconds} s"
fi
if [ "$(internal "$work_dir/key-a")" = 401 ]; then
  pass "the old key answers 401"
else
  fail "the old key does not answer 401 after the suspension"
fi

echo "# 4. a run of the plugin's flow is refused"
status=$(api org_admin POST /api/run-session/ -H 'Content-Type: application/json' \
  --data "{\"graph_id\": $flow_id}")
if [ "$status" = 201 ]; then
  session_id=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("session_id", ""))' \
    "$work_dir/body" 2> /dev/null || true)
fi
expect "the Org Admin's run is refused with 409 plugin_suspended" 409 "$status" \
  "body['code'] == 'plugin_suspended' and body['plugin']['identifier'] == '$plugin'"

echo "# 5. resume"
status=$(api superadmin POST "/api/admin/plugins/$plugin/grants/$grant_id/resume/")
expect "resuming the grant answers 200 and the grant is active" 200 "$status" "body['state'] == 'active'"
if [ "$status" = 200 ]; then may_be_suspended=0; fi

echo "# 6. a new key"
if wait_for new_key_listed; then
  pass "the runtime file lists organization $org_id again with a different key (within ${wait_seconds} s)"
  if [ "$(internal "$work_dir/key-b")" = 200 ]; then
    pass "the new key answers 200"
  else
    fail "the new key does not answer 200"
  fi
else
  fail "the runtime file has no new key for organization $org_id after ${wait_seconds} s"
fi
if [ "$(internal "$work_dir/key-a")" = 401 ]; then
  pass "the old key still answers 401"
else
  fail "the old key does not answer 401 after the resume"
fi

echo "# 7. a run starts again"
status=$(api org_admin POST /api/run-session/ -H 'Content-Type: application/json' \
  --data "{\"graph_id\": $flow_id}")
if [ "$status" = 201 ]; then
  session_id=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("session_id", ""))' \
    "$work_dir/body" 2> /dev/null || true)
fi
expect "the Org Admin's run starts (201)" 201 "$status"

if [ "$failures" -ne 0 ]; then
  echo "FAILED: $failures check(s)"
  exit 1
fi
echo "All suspend smoke checks passed."
