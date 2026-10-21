#!/usr/bin/env bash
# Checks deleting a plugin's data in one organization, uninstalling and reinstalling it, and then
# deleting the plugin for good, on a running stack with PLUGINS_ENABLED=true, as a SuperAdmin does
# it through EpicStaff's API. IT DELETES THE PLUGIN: it refuses to run without --yes.
#
#   1. the grant purge preview answers 200 and names the phrase purge-<plugin>-<organization>; a
#      DELETE with a wrong phrase is 400 invalid_purge_phrase and leaves the grant as it was;
#   2. a DELETE with the phrase is 202 `purging`; within 180 s the grant is gone and the
#      organization's organization removed hook job is `succeeded`;
#   3. after a new grant, uninstall is 200 `uninstalling`; within 30 s no process of the plugin's
#      user id runs on the node, and the gateway answers 404 for a declared public path;
#   4. reinstall brings the plugin back to `running` within 60 s;
#   5. after uninstalling again, the plugin DELETE with the phrase purge-<plugin> is 202; within
#      300 s the plugin's detail answers 404;
#   6. the node keeps nothing of it under data/, plugins/, venvs/, logs/ and /run/es_plugins/, and
#      no process of its user id;
#   7. plugins_db has no database of its owner and none of its three roles, and plugins_admin
#      holds no INHERIT membership it granted itself;
#   8. the egress proxy's hosts.json does not list it;
#   9. its host answers 404;
#  10. its admin activity still answers, and lists plugin_purged.
#
# Settings, from the environment:
#   SMOKE_BASE_URL            EpicStaff's origin, as in DJANGO_FRONTEND_BASE_URL, e.g. http://epicstaff.localhost
#   SMOKE_PLUGINS_BASE_DOMAIN PLUGINS_BASE_DOMAIN, e.g. plugins.epicstaff.localhost
#   SMOKE_PLUGIN              a running plugin with a backend, a database and a declared public path,
#                             granted to SMOKE_ORG_ID, e.g. weather
#   SMOKE_ORG_ID              that organization's id
#   SMOKE_ORG_NAME            and its name, as EpicStaff shows it
#   SMOKE_SUPERADMIN_EMAIL    a SuperAdmin ...
#   SMOKE_SUPERADMIN_PASSWORD ... and their password (never printed, never on a command line)
#   SMOKE_NODE_CONTAINER      optional: the plugin node's container, default es_plugins
#   SMOKE_DB_CONTAINER        optional: the plugin database server's container, default plugins_db
# Arguments: --yes, then extra curl options for every request, e.g. --cacert <file> (or -k) for a
# local CA, or --connect-to ::127.0.0.1: to reach nginx without DNS entries.
#
# It logs in once (EpicStaff allows 5 logins a minute per address and email), refreshes the access
# token through the login cookie when it expires, and logs out at the end. Needs Docker (it reads
# the node's and the database server's state in their containers) and python3. No password, token
# or key is printed or put on a command line: they go to curl in files.
#
# Usage:
#   SMOKE_BASE_URL=http://epicstaff.localhost SMOKE_PLUGINS_BASE_DOMAIN=plugins.epicstaff.localhost \
#   SMOKE_PLUGIN=weather SMOKE_ORG_ID=3 SMOKE_ORG_NAME=Acme \
#   SMOKE_SUPERADMIN_EMAIL=root@example.com SMOKE_SUPERADMIN_PASSWORD=... \
#   bash src/nginx/tests/purge_smoke.sh --yes
set -euo pipefail

if [ "${1-}" != --yes ]; then
  echo "ERROR: this deletes the plugin SMOKE_PLUGIN for good; run it with --yes" >&2
  exit 2
fi
shift

base_url=${SMOKE_BASE_URL:?set SMOKE_BASE_URL, e.g. http://epicstaff.localhost}
base_domain=${SMOKE_PLUGINS_BASE_DOMAIN:?set SMOKE_PLUGINS_BASE_DOMAIN, e.g. plugins.epicstaff.localhost}
plugin=${SMOKE_PLUGIN:?set SMOKE_PLUGIN to a running plugin with a database, e.g. weather}
org_id=${SMOKE_ORG_ID:?set SMOKE_ORG_ID}
org_name=${SMOKE_ORG_NAME:?set SMOKE_ORG_NAME}
superadmin_email=${SMOKE_SUPERADMIN_EMAIL:?set SMOKE_SUPERADMIN_EMAIL}
superadmin_password=${SMOKE_SUPERADMIN_PASSWORD:?set SMOKE_SUPERADMIN_PASSWORD}
node=${SMOKE_NODE_CONTAINER:-es_plugins}
database_server=${SMOKE_DB_CONTAINER:-plugins_db}
curl_options=("$@")

if ! printf '%s\n' "$plugin" | grep -Eq '^[a-z][a-z0-9-]{0,30}[a-z0-9]$'; then
  echo "ERROR: SMOKE_PLUGIN='$plugin' is not a plugin identifier" >&2
  exit 2
fi
case "$org_id" in
  '' | 0* | *[!0-9]*)
    echo "ERROR: SMOKE_ORG_ID='$org_id' is not an id" >&2
    exit 2
    ;;
esac
case "$base_url" in
  http://* | https://*) ;;
  *)
    echo "ERROR: SMOKE_BASE_URL='$base_url' is not an http:// or https:// URL" >&2
    exit 2
    ;;
esac
base_url=${base_url%/}
plugin_origin="${base_url%%://*}://$plugin.$base_domain"
# The plugin's database and role names: its identifier with `-` turned into `_`.
stem=${plugin//-/_}

work_dir=$(mktemp -d)
chmod 700 "$work_dir"

failures=0
pass() { echo "ok - $1"; }
fail() {
  echo "not ok - $1"
  failures=$((failures + 1))
}
signed_in=0

refresh_access() {
  : > "$work_dir/body"
  local status
  status=$(curl -sS -o "$work_dir/body" -w '%{http_code}' --max-time 30 -X POST \
    -b "$work_dir/cookies" -c "$work_dir/cookies" \
    ${curl_options[@]+"${curl_options[@]}"} "$base_url/api/auth/refresh/" 2> "$work_dir/curl-error" || true)
  [ "$status" = 200 ] && write_access_header
}

# api METHOD PATH [curl arguments...]: a request as the SuperAdmin. Prints the status code; the body
# goes to $work_dir/body. An expired access token is refreshed once. A transport error prints 000.
api() {
  local method=$1 path=$2 status attempt
  shift 2
  for attempt in first retry; do
    : > "$work_dir/body"
    status=$(curl -sS -o "$work_dir/body" -w '%{http_code}' --max-time 30 -X "$method" \
      -H "@$work_dir/access" -H 'Accept: application/json' -b "$work_dir/cookies" \
      ${curl_options[@]+"${curl_options[@]}"} "$@" "$base_url$path" 2> "$work_dir/curl-error" || true)
    if [ "$status" != 401 ] || [ "$attempt" = retry ] || ! refresh_access; then
      break
    fi
  done
  echo "$status"
}

# fetch URL: a GET without credentials. Prints the status code.
fetch() {
  curl -sS -o /dev/null -w '%{http_code}' --max-time 30 \
    ${curl_options[@]+"${curl_options[@]}"} "$1" 2> /dev/null || echo 000
}

# json PYTHON-EXPRESSION: prints the expression's value for the last body, parsed as `body`.
json() {
  python3 -c '
import json, sys
try:
    body = json.load(open(sys.argv[1], encoding="utf-8"))
    value = eval(sys.argv[2])
except (ValueError, KeyError, TypeError, IndexError, AttributeError, StopIteration):
    sys.exit(1)
print(value if not isinstance(value, (dict, list)) else json.dumps(value))' "$work_dir/body" "$1"
}
json_is() { [ "$(json "$1" 2> /dev/null)" = True ]; }

expect() { # $1 = description, $2 = expected status, $3 = actual status, $4 = Python check of the body
  if [ "$3" != "$2" ]; then
    fail "$1: status $3, expected $2 $(head -c 200 "$work_dir/curl-error" 2> /dev/null) $(head -c 200 "$work_dir/body")"
  elif [ -n "${4-}" ] && ! json_is "$4"; then
    fail "$1: unexpected body $(head -c 300 "$work_dir/body")"
  else
    pass "$1"
  fi
}

bail_out() {
  echo "Bail out! $1"
  echo "FAILED: $((failures + 1)) check(s)"
  exit 1
}

wait_for() { # seconds, then a command; returns once the command succeeds
  local deadline=$((SECONDS + $1))
  shift
  until "$@" > /dev/null 2>&1; do
    [ "$SECONDS" -lt "$deadline" ] || return 1
    sleep 2
  done
}

finish() {
  local status=$?
  set +e
  if [ "$signed_in" = 1 ]; then
    curl -s -o /dev/null -X POST -H "@$work_dir/access" -b "$work_dir/cookies" \
      ${curl_options[@]+"${curl_options[@]}"} "$base_url/api/auth/logout/" 2> /dev/null
  fi
  rm -rf "$work_dir"
  exit "$status"
}
trap finish EXIT
trap 'exit 130' INT TERM

json_escape() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

# Writes the access token of the last body to the header file; prints nothing of it.
write_access_header() {
  python3 - "$work_dir/body" "$work_dir/access" << 'PYTHON'
import json, os, sys

body_path, header_path = sys.argv[1:]
try:
    with open(body_path, encoding="utf-8") as body_file:
        token = json.load(body_file)["access"]
except (OSError, ValueError, KeyError, TypeError):
    sys.exit(1)
if not isinstance(token, str) or not token:
    sys.exit(1)
if os.path.exists(header_path):
    os.unlink(header_path)
descriptor = os.open(header_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="ascii") as header_file:
    header_file.write(f"Authorization: Bearer {token}\n")
PYTHON
  local status=$?
  : > "$work_dir/body"
  return "$status"
}

log_in() {
  local status
  printf '{"email":"%s","password":"%s"}' "$(json_escape "$superadmin_email")" "$(json_escape "$superadmin_password")" \
    > "$work_dir/login.json"
  status=$(curl -sS -o "$work_dir/body" -w '%{http_code}' --max-time 30 -X POST \
    -H 'Content-Type: application/json' -c "$work_dir/cookies" --data-binary "@$work_dir/login.json" \
    ${curl_options[@]+"${curl_options[@]}"} "$base_url/api/auth/login/" 2> "$work_dir/curl-error" || true)
  rm -f "$work_dir/login.json"
  [ "$status" = 200 ] || bail_out "login as the SuperAdmin answered $status $(head -c 200 "$work_dir/curl-error")"
  signed_in=1
  write_access_header || bail_out "login as the SuperAdmin gave no access token"
}

# phrase_body PHRASE: the purge request body, in a file.
phrase_body() {
  printf '{"verification_phrase":"%s"}' "$(json_escape "$1")" > "$work_dir/phrase.json"
}

grant_of_org() { # prints the grant id of SMOKE_ORG_ID, or nothing
  [ "$(api GET "/api/admin/plugins/$plugin/grants/?page_size=200")" = 200 ] || return 1
  json "next(grant['id'] for grant in body['results'] if grant['organization']['id'] == $org_id)" 2> /dev/null || true
}
grant_state() { # grant id: prints its state, or "gone"
  [ "$(api GET "/api/admin/plugins/$plugin/grants/?page_size=200")" = 200 ] || return 1
  json "next((grant['state'] for grant in body['results'] if grant['id'] == $1), 'gone')"
}
grant_is_gone() { [ "$(grant_state "$1")" = gone ]; }
org_removed_job_succeeded() {
  [ "$(api GET "/api/admin/plugins/$plugin/org-removed-jobs/?state=all&page_size=100")" = 200 ] &&
    json_is "any(job['organization']['id'] == $org_id and job['state'] == 'succeeded' for job in body['results'])"
}
plugin_state() {
  [ "$(api GET "/api/admin/plugins/$plugin/")" = 200 ] && json "body['state']"
}
plugin_is() { [ "$(plugin_state)" = "$1" ]; }
plugin_is_gone() { [ "$(api GET "/api/admin/plugins/$plugin/")" = 404 ]; }
# The processes of a user id in the node: there is no ps in its image, so /proc is read directly.
processes_of_uid() {
  docker exec -u root "$node" sh -c "stat -c %u /proc/[0-9]* 2> /dev/null | grep -c '^$1\$'" 2> /dev/null || true
}
no_process_of_uid() { [ "$(processes_of_uid "$1")" = 0 ]; }
database_count() { # SQL that counts something: prints the count
  docker exec -u postgres "$database_server" psql -X -At -v ON_ERROR_STOP=1 -c "$1" 2> /dev/null
}

echo "# setup"
log_in
status=$(api GET "/api/admin/plugins/$plugin/")
[ "$status" = 200 ] || bail_out "the plugin $plugin answered $status"
[ "$(json "body['state']")" = running ] || bail_out "the plugin $plugin is $(json "body['state']" || echo unknown), not running"
public_path=$(json "body['current_package']['public_paths'][0]['path']" 2> /dev/null) ||
  bail_out "the plugin $plugin declares no public path for the gateway check"
[ "$(api GET "/api/admin/plugins/$plugin/runtime/")" = 200 ] || bail_out "the plugin's runtime did not answer"
plugin_uid=$(json "body['placement']['unix_uid']") || bail_out "the plugin has no placement on the node"
grant_id=$(grant_of_org)
[ -n "$grant_id" ] || bail_out "the plugin is not granted to organization $org_id"
echo "# $plugin: user id $plugin_uid, public path $public_path, grant $grant_id in organization $org_id"

echo "# 1. the grant purge preview, and a wrong phrase"
expected_phrase="purge-$plugin-$org_name"
status=$(api GET "/api/admin/plugins/$plugin/grants/$grant_id/purge-preview/")
expect "the grant purge preview answers and names the phrase" 200 "$status" \
  "body['verification_phrase'] == $(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$expected_phrase")"
state_before=$(grant_state "$grant_id")
phrase_body "${expected_phrase} "
status=$(api DELETE "/api/admin/plugins/$plugin/grants/$grant_id/" -H 'Content-Type: application/json' \
  --data-binary "@$work_dir/phrase.json")
expect "a DELETE with a wrong phrase is refused" 400 "$status" "body['code'] == 'invalid_purge_phrase'"
if [ "$(grant_state "$grant_id")" = "$state_before" ]; then
  pass "the refused DELETE left the grant $state_before"
else
  fail "the refused DELETE changed the grant from $state_before"
fi

echo "# 2. deleting the grant's data"
phrase_body "$expected_phrase"
status=$(api DELETE "/api/admin/plugins/$plugin/grants/$grant_id/" -H 'Content-Type: application/json' \
  --data-binary "@$work_dir/phrase.json")
expect "a DELETE with the phrase starts the purge" 202 "$status" "body['state'] == 'purging'"
if wait_for 180 grant_is_gone "$grant_id"; then
  pass "within 180 s the grant is gone"
else
  fail "the grant is still $(grant_state "$grant_id") after 180 s"
fi
if wait_for 30 org_removed_job_succeeded; then
  pass "the organization's organization removed hook job succeeded"
else
  fail "no succeeded organization removed hook job for organization $org_id: $(head -c 300 "$work_dir/body")"
fi

echo "# 3. uninstalling"
printf '{"organization_id":%s}' "$org_id" > "$work_dir/grant.json"
status=$(api POST "/api/admin/plugins/$plugin/grants/" -H 'Content-Type: application/json' \
  --data-binary "@$work_dir/grant.json")
case "$status" in
  200 | 201) pass "the plugin is granted to organization $org_id again" ;;
  *) fail "granting the plugin again answered $status $(head -c 200 "$work_dir/body")" ;;
esac
status=$(api POST "/api/admin/plugins/$plugin/uninstall/")
expect "uninstall answers with the plugin uninstalling" 200 "$status" "body['state'] == 'uninstalling'"
if wait_for 30 no_process_of_uid "$plugin_uid"; then
  pass "within 30 s no process of user id $plugin_uid runs on the node"
else
  fail "user id $plugin_uid still runs $(processes_of_uid "$plugin_uid") process(es) on the node"
fi
status=$(fetch "$plugin_origin$public_path")
if [ "$status" = 404 ]; then
  pass "the gateway answers 404 for the public path $public_path"
else
  fail "the public path $public_path of the uninstalled plugin answered $status"
fi

echo "# 4. reinstalling"
status=$(api POST "/api/admin/plugins/$plugin/reinstall/")
expect "reinstall answers" 200 "$status"
if wait_for 60 plugin_is running; then
  pass "within 60 s the plugin is running"
else
  fail "the plugin is $(plugin_state || echo unknown) 60 s after reinstall"
fi

echo "# 5. deleting the plugin"
status=$(api POST "/api/admin/plugins/$plugin/uninstall/")
expect "uninstall again" 200 "$status" "body['state'] == 'uninstalling'"
phrase_body "purge-$plugin"
status=$(api DELETE "/api/admin/plugins/$plugin/" -H 'Content-Type: application/json' \
  --data-binary "@$work_dir/phrase.json")
expect "the plugin DELETE with the phrase starts deleting it" 202 "$status" "body['state'] == 'purging'"
if wait_for 300 plugin_is_gone; then
  pass "within 300 s the plugin's detail answers 404"
else
  bail_out "the plugin is still $(plugin_state || echo unknown) after 300 s"
fi

echo "# 6. the node"
left=$(docker exec -u root "$node" ls -A /var/lib/es_plugins/data /var/lib/es_plugins/plugins \
  /var/lib/es_plugins/venvs /run/es_plugins 2> /dev/null || true)
# logs/ is the agent's own, closed to root without CAP_DAC_OVERRIDE.
left_logs=$(docker exec --user 10000:10000 "$node" ls -A /var/lib/es_plugins/logs 2> /dev/null || true)
if printf '%s\n%s\n' "$left" "$left_logs" | grep -qx "$plugin"; then
  fail "the node still keeps something named $plugin"
else
  pass "nothing named $plugin under data/, plugins/, venvs/, logs/ or /run/es_plugins/"
fi
if no_process_of_uid "$plugin_uid"; then
  pass "no process of user id $plugin_uid"
else
  fail "user id $plugin_uid runs $(processes_of_uid "$plugin_uid") process(es)"
fi

echo "# 7. plugins_db"
count=$(database_count "SELECT count(*) FROM pg_database WHERE datname = 'plugin_$stem' OR datdba = (SELECT oid FROM pg_roles WHERE rolname = '${stem}_owner')")
if [ "$count" = 0 ]; then pass "no database of the plugin is left"; else fail "$count database(s) of the plugin are left"; fi
count=$(database_count "SELECT count(*) FROM pg_roles WHERE rolname IN ('${stem}_owner', '${stem}_app', '${stem}_job')")
if [ "$count" = 0 ]; then pass "none of its three roles is left"; else fail "$count of its roles are left"; fi
count=$(database_count "SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member WHERE r.rolname = 'plugins_admin' AND m.inherit_option AND m.grantor = m.member")
if [ "$count" = 0 ]; then
  pass "plugins_admin holds no INHERIT membership it granted itself"
else
  fail "plugins_admin holds $count INHERIT membership(s) it granted itself"
fi

echo "# 8. the egress policy"
docker exec -u root "$node" cat /var/lib/es_plugins_egress/policy/hosts.json > "$work_dir/body" 2> /dev/null || : > "$work_dir/body"
if json_is "'$plugin' not in body"; then
  pass "hosts.json does not list $plugin"
else
  fail "hosts.json still lists $plugin, or could not be read"
fi

echo "# 9. the plugin's host"
status=$(fetch "$plugin_origin/")
if [ "$status" = 404 ]; then pass "$plugin_origin/ answers 404"; else fail "$plugin_origin/ answered $status"; fi

echo "# 10. the activity"
status=$(api GET "/api/admin/plugins/$plugin/activity/?page_size=100")
expect "the deleted plugin's activity still answers and lists plugin_purged" 200 "$status" \
  "any(event['action'] == 'plugin_purged' for event in body['results'])"

if [ "$failures" -ne 0 ]; then
  echo "FAILED: $failures check(s)"
  exit 1
fi
echo "All purge checks passed."
