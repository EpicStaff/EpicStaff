#!/usr/bin/env bash
# Checks plugin development mode on a running stack started with PLUGINS_DEV_MODE=true and
# docker-compose.plugins-dev.yaml, as a SuperAdmin uses it through EpicStaff's API, with two
# stand-in servers on this machine in place of a developer's backend and frontend development
# server:
#
#   1. the plugin's Development endpoint reports the mode on, and the address django_app resolves
#      for host.docker.internal;
#   2. with both ports set, within 15 s the plugin's public path answers from the stand-in backend
#      without its cookie, and its pages from the stand-in page server (which, like esbuild's,
#      refuses any Host but localhost) with the platform's frame-ancestors, while its platform
#      config and login callback page stay the platform's;
#   3. the development runtime file holds a key for SMOKE_ORG_ID, which works on the development
#      API listener (127.0.0.1:SMOKE_DEV_API_PORT) and is refused (401) through the internal
#      listener from the plugins network; the node key is refused (401) on the development
#      listener; a caller on the plugins network is refused (403) by the development listener,
#      whose /api/admin/ is 404; and nothing of EpicStaff answers on this machine's LAN address;
#   4. a second download stops the first file's key (401), and its new key works;
#   5. after Stop development, within 15 s the public path and the pages are the installed
#      plugin's again, and the development key is refused (401).
#
# It leaves the plugin's development ports as it found them: it sets them back, or stops
# development when none were set. Downloading a runtime file stops the keys of every file
# downloaded before it, so a developer whose file this run replaced downloads one again.
#
# Settings, from the environment:
#   SMOKE_BASE_URL            EpicStaff's origin, as in DJANGO_FRONTEND_BASE_URL, e.g. http://epicstaff.localhost
#   SMOKE_PLUGINS_BASE_DOMAIN PLUGINS_BASE_DOMAIN, e.g. plugins.epicstaff.localhost
#   SMOKE_PLUGIN              an installed, running plugin with a backend, a page and the public path
#                             GET /api/ping, active in SMOKE_ORG_ID, e.g. weather
#   SMOKE_ORG_ID              that organization's id
#   SMOKE_SUPERADMIN_EMAIL    a SuperAdmin ...
#   SMOKE_SUPERADMIN_PASSWORD ... and their password (never printed, never on a command line)
#   SMOKE_DEV_API_PORT        PLUGINS_DEV_API_PORT, e.g. 8082
#   SMOKE_NODE_KEY            PLUGINS_NODE_KEY (never printed, never on a command line)
#   SMOKE_NODE_CONTAINER      optional: the plugin node's container, default es_plugins
#
# Needs Docker (curl containers on the plugins network, of src/docker-compose.yaml's pinned curl
# image), python3 (the stand-ins) and curl. The stand-ins listen on this machine at the address
# django_app resolves for host.docker.internal; with Docker Desktop (macOS), on 127.0.0.1. No key,
# token or password is printed or put on a command line: they go to curl in files or on its
# standard input, and keys are compared by sha256 digest.
#
# Usage:
#   SMOKE_BASE_URL=http://epicstaff.localhost SMOKE_PLUGINS_BASE_DOMAIN=plugins.epicstaff.localhost \
#   SMOKE_PLUGIN=weather SMOKE_ORG_ID=3 SMOKE_SUPERADMIN_EMAIL=root@example.com \
#   SMOKE_SUPERADMIN_PASSWORD=... SMOKE_DEV_API_PORT=8082 SMOKE_NODE_KEY=... \
#   bash src/nginx/tests/development_smoke.sh
set -euo pipefail

base_url=${SMOKE_BASE_URL:?set SMOKE_BASE_URL, e.g. http://epicstaff.localhost}
plugins_base_domain=${SMOKE_PLUGINS_BASE_DOMAIN:?set SMOKE_PLUGINS_BASE_DOMAIN, e.g. plugins.epicstaff.localhost}
plugin=${SMOKE_PLUGIN:?set SMOKE_PLUGIN to an installed plugin with a backend and a page, e.g. weather}
org_id=${SMOKE_ORG_ID:?set SMOKE_ORG_ID}
: "${SMOKE_SUPERADMIN_EMAIL:?set SMOKE_SUPERADMIN_EMAIL}"
: "${SMOKE_SUPERADMIN_PASSWORD:?set SMOKE_SUPERADMIN_PASSWORD}"
api_port=${SMOKE_DEV_API_PORT:?set SMOKE_DEV_API_PORT to PLUGINS_DEV_API_PORT, e.g. 8082}
: "${SMOKE_NODE_KEY:?set SMOKE_NODE_KEY to PLUGINS_NODE_KEY}"
node=${SMOKE_NODE_CONTAINER:-es_plugins}
tests_dir=$(cd "$(dirname "$0")" && pwd)
compose_file="$tests_dir/../../docker-compose.yaml"

if ! printf '%s\n' "$plugin" | grep -Eq '^[a-z][a-z0-9-]{0,30}[a-z0-9]$'; then
  echo "ERROR: SMOKE_PLUGIN='$plugin' is not a plugin identifier" >&2
  exit 2
fi
for setting in "SMOKE_ORG_ID=$org_id" "SMOKE_DEV_API_PORT=$api_port"; do
  case "${setting#*=}" in
    '' | 0* | *[!0-9]*)
      echo "ERROR: ${setting%%=*}='${setting#*=}' is not a whole number" >&2
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
# The plugin's own origin: EpicStaff's scheme and port, on the plugin's host.
authority=${base_url#*://}
port_suffix=""
case "$authority" in *:*) port_suffix=":${authority#*:}" ;; esac
plugin_url="${base_url%%://*}://$plugin.$plugins_base_domain$port_suffix"
frame_ancestors="frame-ancestors 'self' $base_url"
development_api="http://127.0.0.1:$api_port"

curl_image=$(grep -Eo 'curlimages/curl:[^[:space:]]+' "$compose_file" | head -n 1)
if [ -z "$curl_image" ]; then
  echo "ERROR: no curlimages/curl image found in $compose_file" >&2
  exit 2
fi

umask 077
work_dir=$(mktemp -d)
failures=0
signed_in=0
changed=0
downloaded=0
stand_ins_pid=""
saved_backend_port=""
saved_spa_port=""

pass() { echo "ok - $1"; }
fail() {
  echo "not ok - $1"
  failures=$((failures + 1))
}
skip() { echo "ok - $1 # SKIP $2"; }

# api METHOD PATH [curl arguments...]: a request to SMOKE_BASE_URL as the SuperAdmin. Prints the
# status code; the body goes to $work_dir/body, the headers to $work_dir/headers. A transport
# error prints 000.
api() {
  local method=$1 path=$2
  shift 2
  : > "$work_dir/body"
  curl -sS -o "$work_dir/body" -D "$work_dir/headers" -w '%{http_code}' --max-time 30 -X "$method" \
    -H "@$work_dir/superadmin-access" -H 'Accept: application/json' -b "$work_dir/superadmin-cookies" \
    "$@" "$base_url$path" 2> "$work_dir/curl-error" || true
}

# plugin_host PATH [curl arguments...]: a request to the plugin's own host, as a browser makes it.
# Prints the status code; the body and headers go to $work_dir.
plugin_host() {
  local path=$1
  shift
  : > "$work_dir/body"
  curl -sS -o "$work_dir/body" -D "$work_dir/headers" -w '%{http_code}' --max-time 30 \
    "$@" "$plugin_url$path" 2> "$work_dir/curl-error" || true
}

# development_listener HEADER_FILE PATH: a request to the development API listener on this
# machine with the Authorization line of the file. Prints the status code; the body goes to
# $work_dir/body.
development_listener() {
  : > "$work_dir/body"
  curl -sS -o "$work_dir/body" -w '%{http_code}' --max-time 30 -H "@$1" -H "X-Organization-Id: $org_id" \
    -H 'Accept: application/json' "$development_api$2" 2> "$work_dir/curl-error" || true
}

header() { tr -d '\r' < "$work_dir/headers" | grep -i "^$1:" | tail -n 1 | cut -d: -f2- | sed 's/^ *//'; }

# json_is CHECK: whether the Python expression CHECK is true of the last body (`body`). A check
# may start on a line of its own: it is stripped first. One that cannot be evaluated (the body is
# not JSON, or the check raises) is false, and leaves the reason in $work_dir/check-error.
json_is() {
  python3 -c '
import json, sys
try:
    body = json.load(open(sys.argv[1], encoding="utf-8"))
except (OSError, ValueError) as error:
    sys.exit(f"the body is not JSON: {error}")
try:
    result = eval(sys.argv[2].strip())
except Exception as error:
    sys.exit(f"the check raised {type(error).__name__}: {error}")
sys.exit(0 if result else 1)' "$work_dir/body" "$1" 2> "$work_dir/check-error"
}

wait_for() { # seconds, then a command; returns once the command succeeds
  local deadline=$((SECONDS + $1))
  shift
  until "$@" > /dev/null 2>&1; do
    if [ "$SECONDS" -ge "$deadline" ]; then
      return 1
    fi
    sleep 1
  done
}

json_escape() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

# Puts the plugin's development ports back as they were, stops the stand-ins and logs out.
finish() {
  local status=$?
  set +e
  if [ "$changed" = 1 ] && [ -f "$work_dir/superadmin-access" ]; then
    if [ -n "$saved_backend_port$saved_spa_port" ]; then
      echo "# cleanup: setting the development ports back"
      printf '{"backend_port": %s, "spa_port": %s}' "${saved_backend_port:-null}" "${saved_spa_port:-null}" \
        > "$work_dir/ports.json"
      restored=$(api PUT "/api/admin/plugins/$plugin/development/" -H 'Content-Type: application/json' \
        --data-binary "@$work_dir/ports.json")
    else
      echo "# cleanup: stopping development"
      restored=$(api DELETE "/api/admin/plugins/$plugin/development/")
    fi
    case "$restored" in
      200 | 204) echo "the development ports are as they were before this run" ;;
      *) echo "WARNING: could not put the development ports of $plugin back ($restored); check its Development tab" >&2 ;;
    esac
  fi
  if [ "$downloaded" = 1 ]; then
    echo "# development runtime files downloaded before this run no longer work: download one again"
  fi
  if [ -n "$stand_ins_pid" ]; then
    kill "$stand_ins_pid" 2> /dev/null
    wait "$stand_ins_pid" 2> /dev/null
  fi
  if [ "$signed_in" = 1 ]; then
    curl -s -o /dev/null -X POST -H "@$work_dir/superadmin-access" -b "$work_dir/superadmin-cookies" \
      "$base_url/api/auth/logout/" 2> /dev/null
  fi
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
    if [ -s "$work_dir/check-error" ]; then
      fail "$1: $(head -c 300 "$work_dir/check-error"); body $(head -c 300 "$work_dir/body")"
    else
      fail "$1: unexpected body $(head -c 300 "$work_dir/body")"
    fi
  else
    pass "$1"
  fi
}

# read_development_key FILE: reads the organization's development key from the downloaded runtime
# file, writes the curl header line with it to FILE, and prints its sha256 digest. Never prints
# the key. Exits non-zero when the organization has no key of the expected shape.
read_development_key() {
  python3 - "$work_dir/runtime.json" "$org_id" "$1" << 'PYTHON'
import hashlib, json, os, re, sys

runtime_path, org_id, header_path = sys.argv[1:]
try:
    with open(runtime_path, encoding="utf-8") as runtime_file:
        entry = json.load(runtime_file)["service_accounts"].get(org_id)
    key = entry["key"]
except (OSError, ValueError, KeyError, TypeError, AttributeError):
    # Never a traceback: it could quote the file.
    sys.exit(1)
if not isinstance(key, str) or not re.fullmatch(r"esp-[A-Za-z0-9_-]{43}", key):
    sys.exit(1)
if os.path.exists(header_path):
    os.remove(header_path)
descriptor = os.open(header_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="ascii") as header_file:
    header_file.write(f"Authorization: PluginKey {key}\n")
print(hashlib.sha256(key.encode()).hexdigest())
PYTHON
}

# download_runtime_file: the development runtime file, as the Development tab downloads it; kept
# in the work directory only. Prints the status code. It runs in a command substitution, so the
# caller sets `downloaded` itself.
download_runtime_file() {
  local status
  status=$(api POST "/api/admin/plugins/$plugin/development/runtime-file/")
  mv "$work_dir/body" "$work_dir/runtime.json"
  : > "$work_dir/body"
  echo "$status"
}

echo "# signing in, and the plugin's Development endpoint"

printf '{"email":"%s","password":"%s"}' "$(json_escape "$SMOKE_SUPERADMIN_EMAIL")" \
  "$(json_escape "$SMOKE_SUPERADMIN_PASSWORD")" > "$work_dir/login.json"
status=$(curl -sS -o "$work_dir/body" -w '%{http_code}' --max-time 30 -X POST \
  -H 'Content-Type: application/json' -c "$work_dir/superadmin-cookies" \
  --data-binary "@$work_dir/login.json" "$base_url/api/auth/login/" 2> "$work_dir/curl-error" || true)
rm -f "$work_dir/login.json"
[ "$status" = 200 ] || bail_out "login as the SuperAdmin answered $status $(head -c 200 "$work_dir/curl-error")"
signed_in=1
python3 - "$work_dir/body" "$work_dir/superadmin-access" << 'PYTHON' || bail_out "login as the SuperAdmin gave no access token"
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

status=$(api GET "/api/admin/plugins/$plugin/development/")
expect "the Development endpoint reports development mode on and the address of host.docker.internal" 200 "$status" \
  "body['development_mode'] is True and body['host'] == 'host.docker.internal' and body['host_address'] and body['can_use_backend'] and body['can_use_spa']"
[ "$status" = 200 ] && json_is "body['development_mode'] is True and body['host_address']" \
  || bail_out "development mode is not on, or host.docker.internal does not resolve in django_app; start EpicStaff with PLUGINS_DEV_MODE=true and docker-compose.plugins-dev.yaml"
host_address=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["host_address"])' "$work_dir/body")
# "<backend>|<page>", either empty: a bare space would let a page port alone read as the backend's.
IFS='|' read -r saved_backend_port saved_spa_port < <(python3 -c '
import json, sys
target = json.load(open(sys.argv[1]))["target"] or {}
print(str(target.get("backend_port") or "") + "|" + str(target.get("spa_port") or ""))' "$work_dir/body") || true
if [ -n "$saved_backend_port$saved_spa_port" ]; then
  echo "# development ports set before this run (backend ${saved_backend_port:-none}, page ${saved_spa_port:-none}): set back at the end"
fi

echo "# two stand-ins on this machine"

# Docker Desktop forwards host.docker.internal to this machine's loopback; on Linux the name is the
# Docker bridge's address on this machine (host-gateway), where the stand-ins must listen.
bind_address=$host_address
if [ "$(uname -s)" = Darwin ]; then
  bind_address=127.0.0.1
fi
cat > "$work_dir/stand_ins.py" << 'PYTHON'
import http.server, os, sys, threading

address, ports_path = sys.argv[1:]
PAGE = b"<!doctype html><title>development-smoke</title><p>development-smoke page</p>\n"


def is_local_host(host):
    name, separator, port = host.rpartition(":")
    if not separator or not port.isdigit():
        name = host
    return name in ("localhost", "127.0.0.1")


class Backend(http.server.BaseHTTPRequestHandler):
    """A development backend: the same JSON for every request, and a cookie nginx must drop."""

    def answer(self):
        body = b'{"served_by":"development-smoke"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Set-Cookie", "development-smoke=1; Path=/")
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = do_PUT = do_DELETE = answer

    def log_message(self, *arguments):
        pass


class Page(http.server.BaseHTTPRequestHandler):
    """A frontend development server: the same page for every path. Like esbuild's, it refuses
    any Host but localhost or 127.0.0.1 (any port): nginx must not send it the plugin's host."""

    def do_GET(self):
        host = self.headers.get("Host", "")
        status, body = (200, PAGE) if is_local_host(host) else (403, b"The host is not allowed.\n")
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *arguments):
        pass


servers = [http.server.ThreadingHTTPServer((address, 0), handler) for handler in (Backend, Page)]
with open(ports_path + ".partial", "w", encoding="ascii") as ports_file:
    ports_file.write(" ".join(str(server.server_address[1]) for server in servers) + "\n")
os.replace(ports_path + ".partial", ports_path)
for server in servers:
    threading.Thread(target=server.serve_forever, daemon=True).start()
threading.Event().wait()
PYTHON
python3 "$work_dir/stand_ins.py" "$bind_address" "$work_dir/ports" 2> "$work_dir/stand-ins-error" &
stand_ins_pid=$!
wait_for 10 test -s "$work_dir/ports" \
  || bail_out "the stand-ins could not listen on $bind_address: $(head -c 200 "$work_dir/stand-ins-error")"
read -r backend_port page_port < "$work_dir/ports"
pass "the stand-in backend (port $backend_port) and page server (port $page_port) listen on $bind_address"

echo "# development ports set: the plugin is served from this machine"

printf '{"backend_port": %s, "spa_port": %s}' "$backend_port" "$page_port" > "$work_dir/ports.json"
status=$(api PUT "/api/admin/plugins/$plugin/development/" -H 'Content-Type: application/json' \
  --data-binary "@$work_dir/ports.json")
changed=1
expect "both development ports are stored" 200 "$status" \
  "body['target']['backend_port'] == $backend_port and body['target']['spa_port'] == $page_port"

from_stand_in_backend() {
  [ "$(plugin_host /api/ping)" = 200 ] && json_is "body == {'served_by': 'development-smoke'}"
}
if wait_for 15 from_stand_in_backend; then
  plugin_host /api/ping > /dev/null
  if [ -z "$(header Set-Cookie)" ]; then
    pass "within 15 s the public path /api/ping answers from the stand-in backend, without its cookie"
  else
    fail "the stand-in backend's Set-Cookie reached the browser"
  fi
else
  fail "the public path /api/ping did not answer from the stand-in backend within 15 s: $(head -c 200 "$work_dir/body")"
fi
from_stand_in_page() {
  [ "$(plugin_host "$1")" = 200 ] && grep -qF 'development-smoke page' "$work_dir/body"
}
for page_path in / /a/route; do
  if wait_for 15 from_stand_in_page "$page_path" && [ "$(header Content-Security-Policy)" = "$frame_ancestors" ]; then
    pass "$page_path is the stand-in page server's page, with the platform's frame-ancestors"
  else
    fail "$page_path did not come from the stand-in page server with [$frame_ancestors]: $(head -c 120 "$work_dir/body") [$(header Content-Security-Policy)]"
  fi
done
status=$(plugin_host /.well-known/epicstaff/config.json)
if [ "$status" = 200 ] && grep -qF "\"$plugin\"" "$work_dir/body" && grep -qF '"frame_protocol"' "$work_dir/body"; then
  pass "/.well-known/epicstaff/config.json is still Django's"
else
  fail "/.well-known/epicstaff/config.json: $status $(head -c 160 "$work_dir/body")"
fi
status=$(plugin_host /.well-known/epicstaff/callback.html)
if [ "$status" = 200 ] && cmp -s "$work_dir/body" "$tests_dir/../plugin-platform/callback.html"; then
  pass "/.well-known/epicstaff/callback.html is still the platform's page"
else
  fail "/.well-known/epicstaff/callback.html: $status, not the platform's page"
fi

echo "# the development runtime file and its keys"

downloaded=1
status=$(download_runtime_file)
if [ "$status" != 200 ]; then
  bail_out "the runtime file download answered $status $(head -c 200 "$work_dir/runtime.json")"
fi
first_digest=$(read_development_key "$work_dir/first-key") \
  || bail_out "the development runtime file holds no key for organization $org_id"
pass "the development runtime file holds a key for organization $org_id"

status=$(development_listener "$work_dir/first-key" /api/plugin-runtime/me/)
expect "the development key works on the development API listener, $development_api" 200 "$status" \
  "body['plugin']['identifier'] == '$plugin' and body['organization']['id'] == $org_id"

network=$(docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' "$node" \
  | grep -E '(^|_)plugins-network$' | head -n 1 || true)
internal_api=$(docker exec "$node" printenv PLUGINS_INTERNAL_API_URL 2> /dev/null || true)
internal_api=${internal_api%/}
internal_api=${internal_api%/api}
if [ -z "$network" ] || [ -z "$internal_api" ]; then
  bail_out "$node is on no plugins-network, or has no PLUGINS_INTERNAL_API_URL"
fi
internal_host=${internal_api#*://}
internal_host=${internal_host%%:*}
# from_plugins_network URL [curl arguments...]: a request from a throwaway container on the plugins
# network, with the header line on its standard input. Prints the status code.
from_plugins_network() {
  local url=$1
  shift
  docker run --rm -i --network "$network" "$curl_image" -s -o /dev/null -w '%{http_code}' --max-time 20 \
    -H @- -H "X-Organization-Id: $org_id" "$@" "$url" 2> /dev/null || echo 000
}
status=$(from_plugins_network "$internal_api/api/plugin-runtime/me/" < "$work_dir/first-key")
[ "$status" = 401 ] && pass "the same key is refused through the internal API listener, from $network (401)" \
  || fail "the development key through the internal API listener: $status, expected 401"

SMOKE_NODE_KEY_FILE="$work_dir/node-key" python3 -c '
import os
descriptor = os.open(os.environ["SMOKE_NODE_KEY_FILE"], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="ascii") as header_file:
    header_file.write("Authorization: PluginNodeKey " + os.environ["SMOKE_NODE_KEY"] + "\n")'
status=$(development_listener "$work_dir/node-key" /api/plugin-nodes/self/desired-state/)
[ "$status" = 401 ] && pass "the node key is refused on the development API listener (401)" \
  || fail "the node key on the development API listener: $status, expected 401"

status=$(from_plugins_network "http://$internal_host:8082/api/plugin-runtime/me/" < "$work_dir/first-key")
[ "$status" = 403 ] && pass "a caller on the plugins network is refused by the development API listener (403)" \
  || fail "the development API listener from the plugins network: $status, expected 403"

status=$(development_listener "$work_dir/first-key" /api/admin/plugins/)
[ "$status" = 404 ] && pass "/api/admin/ on the development API listener is 404" \
  || fail "/api/admin/ on the development API listener: $status, expected 404"

# This machine's address on its network (the one its default route leaves from), where nothing of
# EpicStaff may answer while development ports are set: docker-compose.plugins-dev.yaml publishes
# 80, 443 and the development API on 127.0.0.1 only.
lan_address=""
if [ "$(uname -s)" = Darwin ]; then
  interface=$(route -n get default 2> /dev/null | awk '/interface:/ { print $2 }')
  [ -n "$interface" ] && lan_address=$(ipconfig getifaddr "$interface" 2> /dev/null || true)
else
  lan_address=$(ip -4 route get 1.1.1.1 2> /dev/null | awk '{ for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1) }')
fi
if [ -z "$lan_address" ]; then
  skip "nothing of EpicStaff answers on this machine's LAN address" "this machine has no LAN address"
else
  answered=""
  for target in "80 $plugin.$plugins_base_domain" "443 $plugin.$plugins_base_domain" "$api_port localhost"; do
    read -r port host_name <<< "$target"
    # 7: the connection was refused; 28: it timed out (a firewall). Anything else reached a server.
    code=0
    curl -s -o /dev/null --max-time 5 -H "Host: $host_name" "http://$lan_address:$port/api/ping" || code=$?
    case "$code" in
      7 | 28) ;;
      *) answered="$answered $port" ;;
    esac
  done
  [ -z "$answered" ] && pass "nothing of EpicStaff answers on this machine's LAN address $lan_address (80, 443, $api_port)" \
    || fail "EpicStaff answers on this machine's LAN address $lan_address, ports:$answered"
fi

status=$(download_runtime_file)
second_digest=$(read_development_key "$work_dir/second-key") \
  || bail_out "the second runtime file holds no key for organization $org_id ($status)"
if [ "$status" = 200 ] && [ "$second_digest" != "$first_digest" ]; then
  pass "a second download holds a new key for organization $org_id"
else
  fail "the second download: status $status, a new key: $([ "$second_digest" != "$first_digest" ] && echo yes || echo no)"
fi
status=$(development_listener "$work_dir/first-key" /api/plugin-runtime/me/)
[ "$status" = 401 ] && pass "the first file's key is refused after the second download (401)" \
  || fail "the first file's key after the second download: $status, expected 401"
status=$(development_listener "$work_dir/second-key" /api/plugin-runtime/me/)
expect "the second file's key works" 200 "$status" "body['organization']['id'] == $org_id"

echo "# Stop development: the installed plugin again"

status=$(api DELETE "/api/admin/plugins/$plugin/development/")
expect "Stop development answers 204" 204 "$status"
from_installed_backend() {
  [ "$(plugin_host /api/ping)" = 200 ] && json_is "'served_by' not in body and body.get('mode') == 'public'"
}
wait_for 15 from_installed_backend \
  && pass "within 15 s the public path answers from the installed backend" \
  || fail "the public path did not answer from the installed backend within 15 s: $(head -c 200 "$work_dir/body")"
from_published_page() {
  [ "$(plugin_host /)" = 200 ] && ! grep -qF 'development-smoke page' "$work_dir/body"
}
wait_for 15 from_published_page && pass "within 15 s / is the published page again" \
  || fail "/ was not the published page within 15 s: $(head -c 120 "$work_dir/body")"
status=$(development_listener "$work_dir/second-key" /api/plugin-runtime/me/)
[ "$status" = 401 ] && pass "the development key is refused after Stop development (401)" \
  || fail "the development key after Stop development: $status, expected 401"

if [ "$failures" -ne 0 ]; then
  echo "FAILED: $failures check(s)"
  exit 1
fi
echo "All development smoke checks passed."
