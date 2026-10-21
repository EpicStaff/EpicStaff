#!/usr/bin/env bash
# Checks a plugin's service account on a running stack with PLUGINS_ENABLED=true, as its backend
# uses it: with the key from the plugin's runtime file, from a throwaway curl container on the
# plugins network, through nginx's internal API listener:
#
#   - the key works there (GET /api/plugin-runtime/me/ answers for the plugin and the
#     organization), and the same key gets 401 on EpicStaff's public address, where nginx sends
#     Django no network secret;
#   - the people endpoint answers for a person who may use the plugin in the organization, with
#     their plugin and EpicStaff permissions, and 404 for a person who is not a member;
#   - on behalf of that person `me` names them; on behalf of a member without View on the
#     plugin it is 403 on_behalf_of_not_allowed, and a malformed person id is 400;
#   - a person-only endpoint (the flow assistant's) refuses the key with 403.
#
# Settings, from the environment:
#   SMOKE_BASE_URL       EpicStaff's origin, as in DJANGO_FRONTEND_BASE_URL, e.g. http://epicstaff.localhost
#   SMOKE_PLUGIN         an approved, running plugin with a backend, granted to SMOKE_ORG_ID (its
#                        grant active or still installing), e.g. weather
#   SMOKE_ORG_ID         that organization's id
#   SMOKE_PERSON_ID      the user id of a member of it whose role gives View on the plugin
#   SMOKE_OUTSIDER_ID    the user id of a person who is not a member of it
#   SMOKE_NO_VIEW_ID     the user id of a member of it whose role gives no View on the plugin
#   SMOKE_NODE_CONTAINER optional: the plugin node's container, default es_plugins
# Arguments: extra curl options for the request to SMOKE_BASE_URL, e.g. --cacert <file> (or -k)
# for a local CA, or --connect-to ::127.0.0.1: to reach nginx without DNS entries.
#
# Needs Docker (it reads the runtime file as root in the node's container and runs curl in a
# container of src/docker-compose.yaml's pinned curl image) and python3. The key is never printed
# and never on a command line: it goes to curl as a header file or on its standard input.
#
# Usage:
#   SMOKE_BASE_URL=http://epicstaff.localhost SMOKE_PLUGIN=weather SMOKE_ORG_ID=3 \
#   SMOKE_PERSON_ID=11 SMOKE_OUTSIDER_ID=12 SMOKE_NO_VIEW_ID=13 \
#   bash src/nginx/tests/service_account_smoke.sh
set -euo pipefail

base_url=${SMOKE_BASE_URL:?set SMOKE_BASE_URL, e.g. http://epicstaff.localhost}
plugin=${SMOKE_PLUGIN:?set SMOKE_PLUGIN to an approved plugin with a backend, e.g. weather}
org_id=${SMOKE_ORG_ID:?set SMOKE_ORG_ID}
person_id=${SMOKE_PERSON_ID:?set SMOKE_PERSON_ID to a member who may use the plugin}
outsider_id=${SMOKE_OUTSIDER_ID:?set SMOKE_OUTSIDER_ID to a person who is not a member}
no_view_id=${SMOKE_NO_VIEW_ID:?set SMOKE_NO_VIEW_ID to a member without View on the plugin}
node=${SMOKE_NODE_CONTAINER:-es_plugins}
public_options=("$@")
tests_dir=$(cd "$(dirname "$0")" && pwd)
compose_file="$tests_dir/../../docker-compose.yaml"

if ! printf '%s\n' "$plugin" | grep -Eq '^[a-z][a-z0-9-]{0,30}[a-z0-9]$'; then
  echo "ERROR: SMOKE_PLUGIN='$plugin' is not a plugin identifier" >&2
  exit 2
fi
for setting in "SMOKE_ORG_ID=$org_id" "SMOKE_PERSON_ID=$person_id" \
  "SMOKE_OUTSIDER_ID=$outsider_id" "SMOKE_NO_VIEW_ID=$no_view_id"; do
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
trap 'rm -rf "$work_dir"' EXIT

failures=0
pass() { echo "ok - $1"; }
fail() {
  echo "not ok - $1"
  failures=$((failures + 1))
}
# Stops when a later check could only fail for the same reason.
bail_out() {
  echo "Bail out! $1"
  echo "FAILED: $((failures + 1)) check(s)"
  exit 1
}

echo "# the service account's key, from the runtime file of $plugin"

if ! docker exec -u root "$node" cat "/run/es_plugins/$plugin/runtime.json" > "$work_dir/runtime.json" \
  2> "$work_dir/docker-error"; then
  bail_out "cannot read the runtime file of $plugin in $node: $(head -c 200 "$work_dir/docker-error")"
fi
# Writes the curl header line with the organization's key, and prints the internal API URL.
# Prints nothing of the key, also when it fails.
if ! api_url=$(python3 - "$work_dir/runtime.json" "$org_id" "$work_dir/authorization" << 'PYTHON'
import json, os, re, sys

runtime_path, org_id, header_path = sys.argv[1:]
try:
    with open(runtime_path, encoding="utf-8") as runtime_file:
        runtime = json.load(runtime_file)
    api_url = runtime["epicstaff_api_url"].rstrip("/")
    entry = runtime["service_accounts"].get(org_id)
except (OSError, ValueError, KeyError, TypeError, AttributeError):
    # Never a traceback: it could quote the file.
    sys.exit("the runtime file is not a runtime file")
if not isinstance(entry, dict):
    sys.exit(f"the runtime file has no service account for organization {org_id}")
key = entry.get("key", "")
if not re.fullmatch(r"esp-[A-Za-z0-9_-]{43}", key):
    sys.exit(f"the service account of organization {org_id} has no key of the expected shape")
descriptor = os.open(header_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="ascii") as header_file:
    header_file.write(f"Authorization: PluginKey {key}\n")
print(api_url)
PYTHON
); then
  bail_out "no usable service-account key for organization $org_id in the runtime file of $plugin"
fi
rm -f "$work_dir/runtime.json"
pass "the runtime file holds a key for organization $org_id"

network=$(docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' "$node" \
  | grep -E '(^|_)plugins-network$' | head -n 1 || true)
if [ -z "$network" ]; then
  bail_out "$node is on no plugins-network"
fi

# internal PATH [curl arguments...]: a request from the plugins network with the key, through
# the internal API listener. Prints the status code; the body goes to $work_dir/body.
internal() {
  local path=$1 output
  shift
  output=$(docker run --rm -i --network "$network" "$curl_image" \
    -sS --max-time 20 -H @- -H "X-Organization-Id: $org_id" -H 'Accept: application/json' \
    -w '\n%{http_code}' "$@" "$api_url$path" < "$work_dir/authorization" 2> "$work_dir/curl-error" || true)
  printf '%s' "${output%$'\n'*}" > "$work_dir/body"
  if [ "$output" = "${output%$'\n'*}" ]; then
    echo 000
  else
    echo "${output##*$'\n'}"
  fi
}

# json_is EXPRESSION: true when the Python expression holds for the last body, parsed as `body`.
json_is() {
  python3 -c '
import json, sys
try:
    body = json.load(open(sys.argv[1], encoding="utf-8"))
except ValueError:
    sys.exit(1)
sys.exit(0 if eval(sys.argv[2]) else 1)' "$work_dir/body" "$1"
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

echo "# through the internal API listener, from $network"

status=$(internal /plugin-runtime/me/)
expect "the key authenticates through the internal listener" 200 "$status" \
  "body['plugin']['identifier'] == '$plugin' and body['organization']['id'] == $org_id and body['on_behalf_of'] is None"
if [ "$status" != 200 ]; then
  bail_out "the key does not work through the internal listener; the other checks need it"
fi

status=$(internal "/plugin-runtime/people/$person_id/")
expect "the people endpoint answers for a member who may use the plugin" 200 "$status" \
  "body['user']['id'] == $person_id and 'read' in body['plugin_permissions'] and isinstance(body['epicstaff_permissions'], dict) and body['epicstaff_permissions']"

status=$(internal "/plugin-runtime/people/$outsider_id/")
expect "the people endpoint answers 404 for a person who is not a member" 404 "$status" \
  "body['code'] == 'person_not_found'"

status=$(internal /plugin-runtime/me/ -H "X-EpicStaff-On-Behalf-Of: $person_id")
expect "on behalf of a member who may use the plugin, me names them" 200 "$status" \
  "body['on_behalf_of']['id'] == $person_id"

status=$(internal /plugin-runtime/me/ -H "X-EpicStaff-On-Behalf-Of: $no_view_id")
expect "on behalf of a member without View is refused" 403 "$status" \
  "body['code'] == 'on_behalf_of_not_allowed'"

status=$(internal /plugin-runtime/me/ -H "X-EpicStaff-On-Behalf-Of: not-a-person")
expect "a malformed on-behalf-of header is refused" 400 "$status" "body['code'] == 'invalid_on_behalf_of'"

# Refused by its permission class before any lookup, so any flow id will do.
status=$(internal /flow-assistants/1/)
expect "a person-only endpoint (the flow assistant) refuses the key" 403 "$status" \
  "body['code'] == 'permission_denied'"

echo "# on EpicStaff's public address, $base_url"

status=$(curl -sS -o "$work_dir/body" -w '%{http_code}' --max-time 20 -H @"$work_dir/authorization" \
  -H "X-Organization-Id: $org_id" -H 'Accept: application/json' \
  ${public_options[@]+"${public_options[@]}"} "$base_url/api/plugin-runtime/me/" 2> "$work_dir/curl-error" || true)
expect "the same key is refused on EpicStaff's public address" 401 "$status" \
  "body['code'] == 'service_account_not_authenticated'"

if [ "$failures" -ne 0 ]; then
  echo "FAILED: $failures check(s)"
  exit 1
fi
echo "All service-account smoke checks passed."
