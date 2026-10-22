#!/usr/bin/env bash
# Checks upgrading a plugin, on a running stack with PLUGINS_ENABLED=true, as a SuperAdmin does it
# through EpicStaff's API. IT INSTALLS TWO THROWAWAY VERSIONS of the plugin above the installed one
# (V), and leaves the plugin running the second: it refuses to run without --yes.
#
#   1. an upload of V again is 409 plugin_version_not_newer;
#   2. V+1 (the next patch version) adds a valid migration and one that fails (SELECT 1 / 0); its
#      approval without reviewed_against_package_id is 409 review_outdated, with it 202;
#   3. within 180 s the upgrade has failed while migrating, with the database changed. Meanwhile
#      the plugin's pages answer 503 with the maintenance page and Retry-After: 30, its API 503
#      with X-EpicStaff-Gateway-Deny: maintenance, the organization's available list shows it in
#      maintenance, and Cancel is 409 upgrade_not_cancellable;
#   4. V+2 keeps the valid migration unchanged and replaces the failing one with a valid one; its
#      review needs no backup (this upgrade took one); approved, within 180 s the plugin runs V+2,
#      and the migration ledger lists every file but the one that failed;
#   5. exactly one pre_upgrade backup belongs to this upgrade, and the plugin's user id cannot
#      enter the node's backups directory;
#   6. within 120 s every grant that was active is active again, at V+2;
#   7. the node's log holds neither the backup password nor the word PGPASSWORD;
#   8. the plugin's activity lists plugin_upgrade_started twice (once with replaced_version),
#      plugin_upgrade_failed and plugin_upgraded.
#
# Settings, from the environment:
#   SMOKE_BASE_URL            EpicStaff's origin, as in DJANGO_FRONTEND_BASE_URL, e.g. http://epicstaff.localhost
#   SMOKE_PLUGINS_BASE_DOMAIN PLUGINS_BASE_DOMAIN, e.g. plugins.epicstaff.localhost
#   SMOKE_PLUGIN              a running plugin with a backend and a database, granted to SMOKE_ORG_ID, e.g. weather
#   SMOKE_ORG_ID              an organization the plugin is active in
#   SMOKE_SAMPLE_DIR          the plugin's sample directory at the installed version, e.g. plugin-samples/weather
#   SMOKE_SDK_WHEEL           the epicstaff-plugin wheel the packages are packed with
#   SMOKE_PLUGIN_UID          the plugin's user id on the node (its Runtime tab shows it)
#   SMOKE_SUPERADMIN_EMAIL    a SuperAdmin ...
#   SMOKE_SUPERADMIN_PASSWORD ... and their password
#   SMOKE_MEMBER_EMAIL        a member of SMOKE_ORG_ID who may use the plugin ...
#   SMOKE_MEMBER_PASSWORD     ... and their password (no password is printed or put on a command line)
#   SMOKE_SPA_DIR             optional: the built SPA, default SMOKE_SAMPLE_DIR/spa/dist
#   SMOKE_NODE_CONTAINER      optional: the plugin node's container, default es_plugins
#   SMOKE_DB_CONTAINER        optional: the plugin database server's container, default plugins_db
# Arguments: --yes, then extra curl options for every request, e.g. --cacert <file> (or -k) for a
# local CA, or --connect-to ::127.0.0.1: to reach nginx without DNS entries.
#
# Needs Docker (it reads the node's and the database server's state in their containers), python3,
# uv and network access (packing downloads the backend's wheels). No password, token or key is
# printed or put on a command line: they go to curl in files, and the backup password is compared
# inside a file, counted only.
#
# Usage:
#   SMOKE_BASE_URL=http://epicstaff.localhost SMOKE_PLUGINS_BASE_DOMAIN=plugins.epicstaff.localhost \
#   SMOKE_PLUGIN=weather SMOKE_ORG_ID=3 SMOKE_SAMPLE_DIR=plugin-samples/weather \
#   SMOKE_SDK_WHEEL=/tmp/epicstaff-plugin-dist/epicstaff_plugin-0.7.0-py3-none-any.whl SMOKE_PLUGIN_UID=20001 \
#   SMOKE_SUPERADMIN_EMAIL=root@example.com SMOKE_SUPERADMIN_PASSWORD=... \
#   SMOKE_MEMBER_EMAIL=ada@example.com SMOKE_MEMBER_PASSWORD=... \
#   bash src/nginx/tests/upgrade_smoke.sh --yes
set -euo pipefail

if [ "${1-}" != --yes ]; then
  echo "ERROR: this installs two throwaway versions of SMOKE_PLUGIN; run it with --yes" >&2
  exit 2
fi
shift

repository=$(cd "$(dirname "$0")/../../.." && pwd)
base_url=${SMOKE_BASE_URL:?set SMOKE_BASE_URL, e.g. http://epicstaff.localhost}
base_domain=${SMOKE_PLUGINS_BASE_DOMAIN:?set SMOKE_PLUGINS_BASE_DOMAIN, e.g. plugins.epicstaff.localhost}
plugin=${SMOKE_PLUGIN:?set SMOKE_PLUGIN to a running plugin with a database, e.g. weather}
org_id=${SMOKE_ORG_ID:?set SMOKE_ORG_ID}
sample_dir=${SMOKE_SAMPLE_DIR:?set SMOKE_SAMPLE_DIR to the sample directory of the plugin}
sdk_wheel=${SMOKE_SDK_WHEEL:?set SMOKE_SDK_WHEEL to the epicstaff-plugin wheel}
plugin_uid=${SMOKE_PLUGIN_UID:?set SMOKE_PLUGIN_UID to the user id of the plugin on the node}
superadmin_email=${SMOKE_SUPERADMIN_EMAIL:?set SMOKE_SUPERADMIN_EMAIL}
superadmin_password=${SMOKE_SUPERADMIN_PASSWORD:?set SMOKE_SUPERADMIN_PASSWORD}
member_email=${SMOKE_MEMBER_EMAIL:?set SMOKE_MEMBER_EMAIL to a member of SMOKE_ORG_ID}
member_password=${SMOKE_MEMBER_PASSWORD:?set SMOKE_MEMBER_PASSWORD}
spa_dir=${SMOKE_SPA_DIR:-$sample_dir/spa/dist}
node=${SMOKE_NODE_CONTAINER:-es_plugins}
database_server=${SMOKE_DB_CONTAINER:-plugins_db}
curl_options=("$@")

if ! printf '%s\n' "$plugin" | grep -Eq '^[a-z][a-z0-9-]{0,30}[a-z0-9]$'; then
  echo "ERROR: SMOKE_PLUGIN='$plugin' is not a plugin identifier" >&2
  exit 2
fi
for number in "$org_id" "$plugin_uid"; do
  case "$number" in
    '' | 0* | *[!0-9]*)
      echo "ERROR: '$number' is not an id (SMOKE_ORG_ID, SMOKE_PLUGIN_UID)" >&2
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
for path in "$sample_dir/manifest.json" "$sample_dir/database/migrations" "$sdk_wheel" "$spa_dir"; do
  [ -e "$path" ] || { echo "ERROR: $path does not exist" >&2; exit 2; }
done
base_url=${base_url%/}
plugin_origin="${base_url%%://*}://$plugin.$base_domain"
database="plugin_${plugin//-/_}"

work_dir=$(mktemp -d)
chmod 700 "$work_dir"

failures=0
pass() { echo "ok - $1"; }
fail() {
  echo "not ok - $1"
  failures=$((failures + 1))
}
signed_in=""

bail_out() {
  echo "Bail out! $1"
  echo "FAILED: $((failures + 1)) check(s)"
  exit 1
}

finish() {
  local status=$?
  set +e
  for who in $signed_in; do
    curl -s -o /dev/null -X POST -H "@$work_dir/$who.access" -b "$work_dir/$who.cookies" \
      ${curl_options[@]+"${curl_options[@]}"} "$base_url/api/auth/logout/" 2> /dev/null
  done
  rm -rf "$work_dir"
  exit "$status"
}
trap finish EXIT
trap 'exit 130' INT TERM

json_escape() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

# Writes the access token of the last body to WHO's header file; prints nothing of it.
write_access_header() { # who
  python3 - "$work_dir/body" "$work_dir/$1.access" << 'PYTHON'
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

log_in() { # who, email, password
  local status
  printf '{"email":"%s","password":"%s"}' "$(json_escape "$2")" "$(json_escape "$3")" > "$work_dir/login.json"
  status=$(curl -sS -o "$work_dir/body" -w '%{http_code}' --max-time 30 -X POST \
    -H 'Content-Type: application/json' -c "$work_dir/$1.cookies" --data-binary "@$work_dir/login.json" \
    ${curl_options[@]+"${curl_options[@]}"} "$base_url/api/auth/login/" 2> "$work_dir/curl-error" || true)
  rm -f "$work_dir/login.json"
  [ "$status" = 200 ] || bail_out "login as the $1 answered $status $(head -c 200 "$work_dir/curl-error")"
  signed_in="$signed_in $1"
  write_access_header "$1" || bail_out "login as the $1 gave no access token"
}

refresh_access() { # who
  : > "$work_dir/body"
  local status
  status=$(curl -sS -o "$work_dir/body" -w '%{http_code}' --max-time 30 -X POST \
    -b "$work_dir/$1.cookies" -c "$work_dir/$1.cookies" \
    ${curl_options[@]+"${curl_options[@]}"} "$base_url/api/auth/refresh/" 2> "$work_dir/curl-error" || true)
  [ "$status" = 200 ] && write_access_header "$1"
}

# call WHO METHOD PATH [curl arguments...]: a request as WHO. Prints the status code; the body goes
# to $work_dir/body. An expired access token is refreshed once. A transport error prints 000.
call() {
  local who=$1 method=$2 path=$3 status attempt
  shift 3
  for attempt in first retry; do
    : > "$work_dir/body"
    status=$(curl -sS -o "$work_dir/body" -w '%{http_code}' --max-time 300 -X "$method" \
      -H "@$work_dir/$who.access" -H 'Accept: application/json' -b "$work_dir/$who.cookies" \
      ${curl_options[@]+"${curl_options[@]}"} "$@" "$base_url$path" 2> "$work_dir/curl-error" || true)
    if [ "$status" != 401 ] || [ "$attempt" = retry ] || ! refresh_access "$who"; then
      break
    fi
  done
  echo "$status"
}
api() { call superadmin "$@"; }

# json PYTHON-EXPRESSION: prints the expression's value for the last body, parsed as `body`, as
# JSON for a dict or a list. The expression is stripped first, so it may start on a line of its
# own. When the body is not JSON or the expression raises, prints nothing, gives the reason on
# standard error and fails.
json() {
  python3 -c '
import json, sys
try:
    body = json.load(open(sys.argv[1], encoding="utf-8"))
except (OSError, ValueError) as error:
    sys.exit(f"the body is not JSON: {error}")
try:
    value = eval(sys.argv[2].strip())
except Exception as error:
    sys.exit(f"the check raised {type(error).__name__}: {error}")
print(value if not isinstance(value, (dict, list)) else json.dumps(value))' "$work_dir/body" "$1"
}
# json_is CHECK: whether CHECK is True of the last body. One that cannot be evaluated is false,
# and leaves the reason in $work_dir/check-error.
json_is() { [ "$(json "$1" 2> "$work_dir/check-error")" = True ]; }

expect() { # $1 = description, $2 = expected status, $3 = actual status, $4 = Python check of the body
  if [ "$3" != "$2" ]; then
    fail "$1: status $3, expected $2 $(head -c 200 "$work_dir/curl-error" 2> /dev/null) $(head -c 300 "$work_dir/body")"
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

wait_for() { # seconds, then a command; returns once the command succeeds
  local deadline=$((SECONDS + $1))
  shift
  until "$@" > /dev/null 2>&1; do
    [ "$SECONDS" -lt "$deadline" ] || return 1
    sleep 3
  done
}

# pack VERSION MIGRATION-NAME=SQL...: a package of the sample at VERSION, with these migrations
# added; prints its path.
pack() {
  local version=$1 directory="$work_dir/package-$1"
  shift
  rm -rf "$directory"
  mkdir -p "$directory"
  cp -R "$sample_dir/manifest.json" "$sample_dir/icon.svg" "$sample_dir/backend" "$sample_dir/database" "$directory/"
  python3 - "$directory/manifest.json" "$version" << 'PYTHON'
import json, pathlib, sys

path = pathlib.Path(sys.argv[1])
manifest = json.loads(path.read_text())
manifest["version"] = sys.argv[2]
path.write_text(json.dumps(manifest, indent=4) + "\n")
PYTHON
  local migration
  for migration in "$@"; do
    printf '%s\n' "${migration#*=}" > "$directory/database/migrations/${migration%%=*}"
  done
  (cd "$repository" && uv run --frozen --project src/plugin_sdk epicstaff-plugin pack "$directory" \
    --spa-dir "$spa_dir" --download-wheels --local-wheel "$sdk_wheel" --out "$directory.esplugin") \
    > "$work_dir/pack-$version.log" 2>&1 || {
    # In a command substitution: the message goes to stderr, and the script stops.
    echo "Bail out! packing $version failed: $(tail -n 5 "$work_dir/pack-$version.log")" >&2
    exit 1
  }
  echo "$directory.esplugin"
}

upload() { # package path: prints the status
  api POST /api/admin/plugins/packages/ -F "file=@$1"
}

plugin_detail() { [ "$(api GET "/api/admin/plugins/$plugin/")" = 200 ]; }
upgrade_failed_in_migrating_with_changes() {
  plugin_detail && json_is "body['open_upgrade'] is not None and body['open_upgrade']['stage'] == 'migrating' \
    and body['open_upgrade']['failed'] and body['open_upgrade']['database_changed']"
}
runs_version() { # version
  plugin_detail && json_is "body['state'] == 'running' and body['current_version'] == '$1' and body['open_upgrade'] is None"
}
# The ledger of the plugin's database, names only, read over the server's own socket.
ledger_names() {
  docker exec -u postgres "$database_server" psql -X -At -v ON_ERROR_STOP=1 -d "$database" \
    -c "SELECT name FROM _epicstaff.migrations ORDER BY name" 2> /dev/null
}
# The response headers of a GET without credentials.
headers_of() { # URL
  curl -sS -o "$work_dir/page" -D "$work_dir/headers" --max-time 30 \
    ${curl_options[@]+"${curl_options[@]}"} "$1" 2> /dev/null || true
  tr -d '\r' < "$work_dir/headers"
}
next_patch() { # version: the next patch version of X.Y.Z
  python3 -c 'import sys; major, minor, patch = sys.argv[1].split("+")[0].split("-")[0].split("."); print(f"{major}.{minor}.{int(patch) + 1}")' "$1"
}

echo "# setup"
log_in superadmin "$superadmin_email" "$superadmin_password"
log_in member "$member_email" "$member_password"
plugin_detail || bail_out "the plugin $plugin did not answer"
installed=$(json "body['current_version']") || bail_out "the plugin $plugin has no current version"
[ "$(json "body['state']")" = running ] || bail_out "the plugin $plugin is not running"
json_is "body['open_upgrade'] is None" || bail_out "the plugin $plugin has an upgrade open already"
first=$(next_patch "$installed")
second=$(next_patch "$first")
sample_version=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["version"])' "$sample_dir/manifest.json")
[ "$sample_version" = "$installed" ] || bail_out "the sample is version $sample_version, the plugin runs $installed"
sample_migrations=()
for path in "$sample_dir"/database/migrations/[0-9][0-9][0-9]_*.sql; do
  [ -e "$path" ] && sample_migrations+=("$(basename "$path")")
done
[ "${#sample_migrations[@]}" -gt 0 ] || bail_out "the sample has no migrations"
highest=$(printf '%s\n' "${sample_migrations[@]}" | sort | tail -n 1 | cut -c1-3)
notes=$(printf '%03d_smoke_notes.sql' $((10#$highest + 1)))
broken=$(printf '%03d_smoke_broken.sql' $((10#$highest + 2)))
fixed=$(printf '%03d_smoke_fixed.sql' $((10#$highest + 2)))
[ "$(api GET "/api/admin/plugins/$plugin/grants/?page_size=200")" = 200 ] || bail_out "the grants did not answer"
active_grants=$(json "sorted(grant['id'] for grant in body['results'] if grant['state'] == 'active')")
echo "# $plugin runs $installed; the smoke installs $first, then $second; active grants $active_grants"

echo "# 1. a version that is not newer"
same=$(pack "$installed")
status=$(upload "$same")
expect "an upload of $installed again is refused" 409 "$status" "body['code'] == 'plugin_version_not_newer'"

echo "# 2. $first: a migration that applies, then one that fails"
package=$(pack "$first" "$notes=CREATE TABLE public.smoke_notes (note text);" "$broken=SELECT 1 / 0;")
status=$(upload "$package")
expect "$first is uploaded for review" 201 "$status" "body['version'] == '$first' and body['upgrade'] is not None"
first_package=$(json "body['id']")
baseline=$(json "body['upgrade']['baseline_package_id']")
printf '{"untrusted_acknowledged": true}' > "$work_dir/approve.json"
status=$(api POST "/api/admin/plugins/packages/$first_package/approve/" -H 'Content-Type: application/json' \
  --data-binary "@$work_dir/approve.json")
expect "approving without the reviewed baseline is refused" 409 "$status" "body['code'] == 'review_outdated'"
printf '{"untrusted_acknowledged": true, "reviewed_against_package_id": %s}' "$baseline" > "$work_dir/approve.json"
status=$(api POST "/api/admin/plugins/packages/$first_package/approve/" -H 'Content-Type: application/json' \
  --data-binary "@$work_dir/approve.json")
expect "approving against the reviewed baseline starts the upgrade" 202 "$status" \
  "body['open_upgrade'] is not None and body['open_upgrade']['to_version'] == '$first'"
upgrade_id=$(json "body['open_upgrade']['id']" || echo "")

echo "# 3. the upgrade fails while migrating, and the plugin is in maintenance"
if wait_for 180 upgrade_failed_in_migrating_with_changes; then
  pass "within 180 s the upgrade failed while migrating, with the database changed ($(json "body['open_upgrade']['last_error']" | head -c 160))"
else
  bail_out "the upgrade did not fail while migrating in 180 s: $(head -c 400 "$work_dir/body")"
fi
page_headers=$(headers_of "$plugin_origin/")
if printf '%s\n' "$page_headers" | head -n 1 | grep -q ' 503' \
  && printf '%s\n' "$page_headers" | grep -qi '^retry-after: 30$' && grep -qi 'being updated' "$work_dir/page"; then
  pass "the plugin's page answers 503 with the maintenance page and Retry-After: 30"
else
  fail "the plugin's page during maintenance: $(printf '%s' "$page_headers" | head -c 300)"
fi
api_headers=$(headers_of "$plugin_origin/api/ping")
if printf '%s\n' "$api_headers" | head -n 1 | grep -q ' 503' \
  && printf '%s\n' "$api_headers" | grep -qi '^x-epicstaff-gateway-deny: maintenance$'; then
  pass "the plugin's API answers 503 with X-EpicStaff-Gateway-Deny: maintenance"
else
  fail "the plugin's API during maintenance: $(printf '%s' "$api_headers" | head -c 300)"
fi
status=$(call member GET /api/plugins/available/ -H "X-Organization-Id: $org_id")
expect "the organization's available list shows the plugin in maintenance" 200 "$status" \
  "any(item['identifier'] == '$plugin' and item['availability'] == 'maintenance' for item in (body if isinstance(body, list) else body.get('results', [])))"
status=$(api POST "/api/admin/plugins/$plugin/upgrade/cancel/")
expect "Cancel is refused: the database holds a change of $first" 409 "$status" "body['code'] == 'upgrade_not_cancellable'"

echo "# 4. $second keeps the applied file and fixes the other"
package=$(pack "$second" "$notes=CREATE TABLE public.smoke_notes (note text);" "$fixed=SELECT 1;")
status=$(upload "$package")
expect "$second is uploaded for review, and needs no backup (this upgrade took one)" 201 "$status" \
  "body['version'] == '$second' and body['upgrade']['backup']['required'] is False"
second_package=$(json "body['id']")
baseline=$(json "body['upgrade']['baseline_package_id']")
printf '{"untrusted_acknowledged": true, "reviewed_against_package_id": %s}' "$baseline" > "$work_dir/approve.json"
status=$(api POST "/api/admin/plugins/packages/$second_package/approve/" -H 'Content-Type: application/json' \
  --data-binary "@$work_dir/approve.json")
expect "approving $second replaces the failed target" 202 "$status"
if wait_for 180 runs_version "$second"; then
  pass "within 180 s the plugin runs $second"
else
  fail "the plugin does not run $second after 180 s: $(head -c 400 "$work_dir/body")"
fi
expected_ledger=$(printf '%s\n' "${sample_migrations[@]}" "$notes" "$fixed" | sort | tr '\n' ' ')
actual_ledger=$(ledger_names | sort | tr '\n' ' ')
if [ "$actual_ledger" = "$expected_ledger" ]; then
  pass "the ledger lists every file but the one that failed"
else
  fail "the ledger: $actual_ledger, expected $expected_ledger"
fi

echo "# 5. the backup"
status=$(api GET "/api/admin/plugins/$plugin/backups/")
expect "exactly one pre_upgrade backup belongs to this upgrade" 200 "$status" \
  "len([backup for backup in body['backups'] if backup['reason'] == 'pre_upgrade' and (backup['upgrade'] or {}).get('id') == ${upgrade_id:-0}]) == 1"
if ! docker exec -u "$plugin_uid:$plugin_uid" "$node" ls /var/lib/es_plugins/backups > /dev/null 2> "$work_dir/denied" \
  && grep -q 'Permission denied' "$work_dir/denied"; then
  pass "the plugin's user id cannot enter the node's backups directory"
else
  fail "the plugin's user id reached the backups directory: $(head -c 200 "$work_dir/denied")"
fi

echo "# 6. the organizations"
grants_upgraded() {
  [ "$(api GET "/api/admin/plugins/$plugin/grants/?page_size=200")" = 200 ] && json_is "all(
    grant['state'] == 'active' and grant['installed_version'] == '$second'
    for grant in body['results'] if grant['id'] in $active_grants)"
}
if wait_for 120 grants_upgraded; then
  pass "within 120 s every grant that was active is active at $second"
else
  fail "grants after the upgrade: $(json "[(grant['id'], grant['state'], grant['installed_version']) for grant in body['results']]" 2> /dev/null)"
fi

echo "# 7. secrets"
docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$node" \
  | sed -n 's/^PLUGINS_DB_BACKUP_PASSWORD=//p' > "$work_dir/backup-password"
chmod 600 "$work_dir/backup-password"
[ -s "$work_dir/backup-password" ] || bail_out "the node's environment has no PLUGINS_DB_BACKUP_PASSWORD"
docker logs "$node" > "$work_dir/node.log" 2>&1
leaks=$(grep -c -F -f "$work_dir/backup-password" "$work_dir/node.log" || true)
mentions=$(grep -c 'PGPASSWORD' "$work_dir/node.log" || true)
if [ "$leaks" = 0 ] && [ "$mentions" = 0 ]; then
  pass "the node's log holds neither the backup password nor PGPASSWORD"
else
  fail "the node's log: $leaks line(s) with the backup password, $mentions with PGPASSWORD"
fi
rm -f "$work_dir/backup-password" "$work_dir/node.log"

echo "# 8. activity"
status=$(api GET "/api/admin/plugins/$plugin/activity/?page_size=100")
expect "the activity lists both starts (one replacing $first), the failure and the upgrade" 200 "$status" "
  (lambda events: len([event for event in events if event['action'] == 'plugin_upgrade_started'
                       and event['detail'].get('to_version') in ('$first', '$second')]) == 2
    and any(event['action'] == 'plugin_upgrade_started' and event['detail'].get('replaced_version') == '$first' for event in events)
    and any(event['action'] == 'plugin_upgrade_failed' and event['detail'].get('to_version') == '$first' for event in events)
    and any(event['action'] == 'plugin_upgraded' and event['detail'].get('to_version') == '$second' for event in events)
  )(body['results'])"

if [ "$failures" -ne 0 ]; then
  echo "FAILED: $failures check(s)"
  exit 1
fi
echo "All upgrade smoke checks passed; $plugin runs $second."
