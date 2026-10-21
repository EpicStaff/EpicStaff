#!/usr/bin/env bash
# Checks the plugin platform's nginx routes on a running stack with PLUGINS_ENABLED=true and at
# least one approved plugin, through epicstaff-nginx, the way a browser reaches them:
#
#   - the plugin host serves the plugin's SPA with the security headers, every index.html with
#     Cache-Control: no-cache, the platform config from Django, the platform's login callback
#     pages (only GET and HEAD) with their own policy, and 404 for the platform's other paths;
#   - its /api/ goes through the gateway: a declared public path reaches the plugin's backend with
#     a public context, any other path is 401 login_required, paths that are not canonical and
#     /_epicstaff/ never reach it, a context a client forges never counts, and the gateway's own
#     refusals carry X-EpicStaff-Gateway-Deny while the plugin's answers never do;
#   - a host name that is not a valid plugin host reaches EpicStaff's own server;
#   - EpicStaff's sign-in pages for plugins (/plugin-login, /plugin-choose-org) may be framed by
#     EpicStaff itself, inside a plugin's frame (X-Frame-Options: SAMEORIGIN, never DENY);
#   - EpicStaff's server frames plugin hosts (frame-src), refuses a package upload without a
#     SuperAdmin's login before reading it, and takes a SuperAdmin's upload above its usual 50 MB
#     limit, up to PLUGINS_MAX_PACKAGE_MB.
#
# Settings, from the environment:
#   EPICSTAFF_URL           EpicStaff's origin, as in DJANGO_FRONTEND_BASE_URL, e.g. http://epicstaff.localhost
#   PLUGINS_BASE_DOMAIN     e.g. plugins.epicstaff.localhost
#   PLUGIN_IDENTIFIER       an approved plugin with a backend, running, e.g. weather (the sample:
#                           public path GET /api/ping, which answers its context's mode)
#   PLUGINS_MAX_PACKAGE_MB  the stack's upload limit, e.g. 300
#   PUBLIC_PATH             optional, default /api/ping: a public GET path of the plugin that
#                           answers 200 with "mode": "public"
#   GATEWAY_LOAD_SECONDS    optional: also measure the gateway check under load for this many
#                           whole seconds, print its p50/p99, and fail on any answer other than
#                           the expected 401 (login refused) or 200 (public path)
#   SMOKE_ADMIN_TOKEN       optional: a SuperAdmin's access token. Adds the checks that need a
#                           login: the upload route takes 51 MiB, and a real 51 MiB upload that
#                           Django must read to the end and refuse as an invalid package.
# Arguments: extra curl options for every request, the load included, e.g. --cacert ca.pem (or
# --insecure) for a local certificate, or --connect-to ::127.0.0.1:8080 to reach nginx at another
# address without DNS entries.
#
# Usage:
#   EPICSTAFF_URL=http://epicstaff.localhost PLUGINS_BASE_DOMAIN=plugins.epicstaff.localhost \
#   PLUGIN_IDENTIFIER=weather PLUGINS_MAX_PACKAGE_MB=300 bash src/nginx/tests/plugins_smoke.sh
set -euo pipefail

epicstaff_url=${EPICSTAFF_URL:?set EPICSTAFF_URL, e.g. http://epicstaff.localhost}
base_domain=${PLUGINS_BASE_DOMAIN:?set PLUGINS_BASE_DOMAIN, e.g. plugins.epicstaff.localhost}
plugin=${PLUGIN_IDENTIFIER:?set PLUGIN_IDENTIFIER to an approved plugin, e.g. weather}
max_package_megabytes=${PLUGINS_MAX_PACKAGE_MB:?set PLUGINS_MAX_PACKAGE_MB, e.g. 300}
admin_token=${SMOKE_ADMIN_TOKEN-}
public_path=${PUBLIC_PATH:-/api/ping}
load_seconds=${GATEWAY_LOAD_SECONDS-}
case "$load_seconds" in
  *[!0-9]*)
    echo "GATEWAY_LOAD_SECONDS must be a whole number of seconds, not [$load_seconds]" >&2
    exit 2
    ;;
esac
curl_options=("$@")

scheme=${epicstaff_url%%://*}
authority=${epicstaff_url#*://}
authority=${authority%%/*}
port_suffix=""
case "$authority" in
  *:*) port_suffix=:${authority#*:} ;;
esac
epicstaff_origin=$scheme://$authority
plugin_origin=$scheme://$plugin.$base_domain$port_suffix
unknown_plugin_origin=$scheme://smoke-no-such-plugin.$base_domain$port_suffix
# 33 characters: one more than an identifier may have, so no plugin server matches it.
invalid_label_origin=$scheme://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.$base_domain$port_suffix

work_dir=$(mktemp -d)
failures=0
load_pids=()
summary_printed=false
# Whatever stops the script, it ends with a summary line, and stopping early is a failure.
finish() {
  local status=$?
  if [ ${#load_pids[@]} -gt 0 ]; then
    kill "${load_pids[@]}" 2> /dev/null || true
  fi
  rm -rf "$work_dir"
  if [ "$summary_printed" = false ]; then
    # macOS's bash 3.2 leaves $? at 0 after a failed expansion in an assignment.
    [ "$status" -ne 0 ] || status=1
    echo "FAILED: stopped early (exit status $status), $failures check(s) failed before that"
    exit "$status"
  fi
}
trap finish EXIT

pass() { echo "ok - $1"; }
fail() {
  echo "not ok - $1"
  failures=$((failures + 1))
}

# fetch URL [curl options...]: prints the final status code; the response's headers go to
# $work_dir/headers and its body to $work_dir/body. A transport error prints 000.
fetch() {
  local url=$1
  shift
  curl -sS -o "$work_dir/body" -D "$work_dir/headers" -w '%{http_code}' \
    ${curl_options[@]+"${curl_options[@]}"} "$@" "$url" 2> "$work_dir/curl-error" || true
}

# The value of a header of the last response, without the trailing carriage return.
header() {
  grep -i "^$1:" "$work_dir/headers" | tail -n 1 | cut -d: -f2- | sed 's/^ *//; s/\r$//' || true
}

# Every value of a header of the last response, sorted and joined with |.
header_values() {
  { grep -i "^$1:" "$work_dir/headers" || true; } | cut -d: -f2- | sed 's/^ *//; s/\r$//' \
    | LC_ALL=C sort | paste -sd '|' -
}

expect_status() { # $1 = description, $2 = expected status, $3 = actual status
  if [ "$3" = "$2" ]; then
    pass "$1"
  else
    fail "$1: status $3, expected $2 $(head -c 200 "$work_dir/curl-error" 2> /dev/null)"
  fi
}

expect_header() { # $1 = description, $2 = header name, $3 = exact expected value
  local value
  value=$(header "$2")
  if [ "$value" = "$3" ]; then
    pass "$1"
  else
    fail "$1: $2 is [$value], expected [$3]"
  fi
}

expect_no_header() { # $1 = description, $2 = header name
  if grep -qi "^$2:" "$work_dir/headers"; then
    fail "$1: unexpected $2: $(header "$2")"
  else
    pass "$1"
  fi
}

expect_header_values() { # $1 = description, $2 = header name, $3... = every value it must have
  local description=$1 name=$2 expected
  shift 2
  expected=$(printf '%s\n' "$@" | LC_ALL=C sort | paste -sd '|' -)
  if [ "$(header_values "$name")" = "$expected" ]; then
    pass "$description"
  else
    fail "$description: $name is [$(header_values "$name")], expected [$expected]"
  fi
}

expect_body() { # $1 = description, $2 = text the body must contain
  if grep -qF -- "$2" "$work_dir/body"; then
    pass "$1"
  else
    fail "$1: body has no [$2]: $(head -c 200 "$work_dir/body")"
  fi
}

# The headers every plugin host response carries, whatever its status. A response may add a
# policy of its own (the callback pages do), so frame-ancestors is one of the policies sent.
expect_plugin_security_headers() { # $1 = what was requested
  case "|$(header_values Content-Security-Policy)|" in
    *"|frame-ancestors 'self' $epicstaff_origin|"*) pass "$1: frame-ancestors" ;;
    *) fail "$1: frame-ancestors: Content-Security-Policy is [$(header_values Content-Security-Policy)]" ;;
  esac
  expect_header "$1: nosniff" X-Content-Type-Options nosniff
  expect_header "$1: Referrer-Policy" Referrer-Policy strict-origin-when-cross-origin
  expect_header "$1: Origin-Agent-Cluster" Origin-Agent-Cluster "?1"
  expect_no_header "$1: no X-Frame-Options" X-Frame-Options
  if [ "$scheme" = https ]; then
    expect_header "$1: HSTS" Strict-Transport-Security "max-age=31536000; includeSubDomains"
  fi
}

# POSTs only the headers of an upload of the given size. nginx decides on the size before it reads
# any of the body: 100 Continue means it would take the body, 413 that it refuses it.
# nginx reads an upload's body only after Django has accepted the caller's login, so this sends
# SMOKE_ADMIN_TOKEN when there is one.
upload_decision() { # $1 = path on EpicStaff's server, $2 = Content-Length
  curl -sS -o /dev/null -D "$work_dir/headers" --max-time 3 -X POST \
    -H "Authorization: Bearer ${admin_token:-not-a-token}" \
    -H "Content-Type: multipart/form-data; boundary=smoke" -H "Content-Length: $2" \
    -H "Expect: 100-continue" ${curl_options[@]+"${curl_options[@]}"} \
    "$epicstaff_url$1" > /dev/null 2>&1 || true
  awk '/^HTTP\// { print $2; exit }' "$work_dir/headers"
}

echo "# plugin host $plugin_origin"

status=$(fetch "$plugin_origin/")
expect_status "/ serves the SPA" 200 "$status"
expect_header "/ is index.html, revalidated on every load" Cache-Control no-cache
expect_plugin_security_headers "/"

status=$(fetch "$plugin_origin/index.html")
expect_status "/index.html is served" 200 "$status"
expect_header "/index.html is revalidated on every load" Cache-Control no-cache

status=$(fetch "$plugin_origin/smoke/client-side/route?tab=1")
expect_status "a client-side route falls back to index.html" 200 "$status"
expect_header "the fallback index.html is revalidated on every load" Cache-Control no-cache
case "$(header Content-Type)" in
  text/html*) pass "the fallback is HTML" ;;
  *) fail "the fallback is HTML: Content-Type is [$(header Content-Type)]" ;;
esac

for path in /_epicstaff/x /.well-known/epicstaff/x /.well-known/epicstaff/other.html; do
  status=$(fetch "$plugin_origin$path")
  expect_status "$path is 404" 404 "$status"
  expect_plugin_security_headers "$path"
done

echo "# the platform's login callback pages"

# EpicStaff's authorize endpoint redirects a plugin page to these, on its own host.
page_policy="default-src 'none'; script-src 'self'; base-uri 'none'; form-action 'none'"
for page in callback.html silent-callback.html; do
  status=$(fetch "$plugin_origin/.well-known/epicstaff/$page")
  expect_status "$page is served" 200 "$status"
  expect_header "$page is HTML" Content-Type text/html
  expect_header "$page is revalidated on every load" Cache-Control no-cache
  expect_header_values "$page runs only this host's scripts, framed only by EpicStaff and the plugin" \
    Content-Security-Policy "$page_policy" "frame-ancestors 'self' $epicstaff_origin"
  expect_body "$page loads callback.js" '/.well-known/epicstaff/callback.js'
  expect_no_header "$page sets no cookie" Set-Cookie
  expect_plugin_security_headers "$page"
done
status=$(fetch "$plugin_origin/.well-known/epicstaff/callback.js")
expect_status "callback.js is served" 200 "$status"
expect_header "callback.js is JavaScript" Content-Type application/javascript
expect_header "callback.js is revalidated on every load" Cache-Control no-cache
expect_plugin_security_headers "callback.js"
status=$(fetch "$plugin_origin/.well-known/epicstaff/callback.html" -X POST --data x)
expect_status "a POST to callback.html is refused" 403 "$status"

echo "# the plugin's API, through the gateway"

status=$(fetch "$plugin_origin$public_path")
expect_status "the public path $public_path reaches the plugin" 200 "$status"
expect_body "the plugin got a verified public context" '"mode":"public"'
expect_no_header "the plugin's response sets no cookie" Set-Cookie
expect_no_header "the plugin's response is not marked as the gateway's" X-EpicStaff-Gateway-Deny
expect_plugin_security_headers "$public_path"

# Every spelling of the context header a client might send: the plugin's SDK would refuse the
# request (401) if any of them reached it next to, or instead of, the gateway's.
status=$(fetch "$plugin_origin$public_path" -H 'X-EpicStaff-Plugin-Context: forged' \
  -H 'X_EpicStaff_Plugin_Context: forged' -H 'X-EpicStaff-Plugin_Context: forged')
expect_status "a context the client forges never reaches the plugin" 200 "$status"
expect_body "the forged request still has the gateway's public context" '"mode":"public"'

status=$(fetch "$plugin_origin/api/x")
expect_status "/api/x, which is not public, is 401" 401 "$status"
expect_header "/api/x answers JSON" Content-Type application/json
expect_body "/api/x has EpicStaff's error shape" '"code":"login_required"'
expect_header "/api/x asks for a bearer token" WWW-Authenticate Bearer
expect_header "/api/x is marked as the gateway's refusal" X-EpicStaff-Gateway-Deny login
expect_plugin_security_headers "/api/x"

for path in /api/%2e%2e/_epicstaff/health /api/public/../x /api/..%2f_epicstaff/health \
  /api/%252e%252e/_epicstaff/health "$public_path/../x"; do
  status=$(fetch "$plugin_origin$path" --path-as-is)
  expect_status "$path never reaches the plugin" 404 "$status"
done

status=$(fetch "$unknown_plugin_origin$public_path")
expect_status "an unknown plugin's API is 404" 404 "$status"
expect_body "an unknown plugin's API has EpicStaff's error shape" '"code":"not_found"'
expect_header "an unknown plugin's API is marked as the gateway's refusal" X-EpicStaff-Gateway-Deny not_found

status=$(fetch "$plugin_origin/.well-known/epicstaff/config.json")
expect_status "config.json is proxied to Django" 200 "$status"
case "$(header Content-Type)" in
  application/json*) pass "config.json is JSON" ;;
  *) fail "config.json is JSON: Content-Type is [$(header Content-Type)]" ;;
esac
expect_body "config.json is this plugin's" "\"$plugin\""
expect_body "config.json names the frame protocol" '"frame_protocol"'
expect_no_header "config.json sets no cookie" Set-Cookie
expect_plugin_security_headers "config.json"

echo "# a plugin that is not installed, and a host that is not a plugin host"

status=$(fetch "$unknown_plugin_origin/")
expect_status "an unknown plugin's host has no SPA" 404 "$status"
status=$(fetch "$unknown_plugin_origin/.well-known/epicstaff/config.json")
expect_status "an unknown plugin has no config" 404 "$status"

# --insecure for this request only: EpicStaff's server answers with its own certificate, and only
# the routing is checked here.
status=$(fetch "$invalid_label_origin/" --insecure)
if [ "$status" != 000 ] && [ "$(header X-Frame-Options)" = SAMEORIGIN ] \
  && ! grep -qi '^Origin-Agent-Cluster:' "$work_dir/headers"; then
  pass "a host name that is not a plugin host reaches EpicStaff's server"
else
  fail "a host name that is not a plugin host reaches EpicStaff's server: status $status, X-Frame-Options [$(header X-Frame-Options)]"
fi

echo "# EpicStaff $epicstaff_url"

status=$(fetch "$epicstaff_url/")
case "$(header Content-Security-Policy-Report-Only)" in
  *"frame-src 'self' $scheme://*.$base_domain$port_suffix;"*) pass "EpicStaff frames the plugin hosts (frame-src)" ;;
  *) fail "EpicStaff frames the plugin hosts (frame-src): [$(header Content-Security-Policy-Report-Only)]" ;;
esac

# The sign-in pages open inside the plugin's frame, whose only ancestor is EpicStaff's own page:
# EpicStaff must be able to frame them, so one X-Frame-Options, SAMEORIGIN.
for path in "/plugin-login?continue=%2Fsmoke" "/plugin-choose-org?continue=%2Fsmoke"; do
  status=$(fetch "$epicstaff_url$path")
  expect_status "${path%%\?*} is served" 200 "$status"
  expect_header_values "${path%%\?*} may be framed by EpicStaff itself, never DENY" X-Frame-Options SAMEORIGIN
done

status=$(fetch "$epicstaff_url/api/plugin-gateway/check/")
expect_status "/api/plugin-gateway/ is not reachable" 404 "$status"
status=$(fetch "$epicstaff_url/api/plugin-nodes/self/desired-state/")
expect_status "the plugin node's API is not reachable from outside" 404 "$status"

mebibyte=1048576
over_default_limit=$((51 * mebibyte))
# nginx allows one MiB above the package cap for the multipart framing.
over_package_limit=$(((max_package_megabytes + 2) * mebibyte))
status=$(fetch "$epicstaff_url/api/admin/plugins/packages/" -X POST \
  -H "Authorization: Bearer not-a-token" -F "file=@/dev/null;filename=x.esplugin")
expect_status "an upload with a made-up token is refused before its body is read" 401 "$status"
expect_body "the refusal is Django's JSON envelope" '"code":"not_authenticated"'
status=$(fetch "$epicstaff_url/api/admin/plugins/packages/upload-permission/")
expect_status "Django's upload permission check is not reachable from outside" 404 "$status"

if [ "$max_package_megabytes" -le 51 ]; then
  echo "# PLUGINS_MAX_PACKAGE_MB=$max_package_megabytes is not above 51: skipping the 51 MiB upload checks"
else
  # Only the headers, above the server's usual 50 MB: the permission check must still answer.
  status=$(fetch "$epicstaff_url/api/admin/plugins/packages/" -X POST --max-time 3 \
    -H "Authorization: Bearer not-a-token" -H "Content-Type: multipart/form-data; boundary=smoke" \
    -H "Content-Length: $over_default_limit")
  expect_status "a 51 MiB upload with a made-up token is refused before its body is read" 401 "$status"
  expect_body "that refusal is Django's JSON envelope" '"code":"not_authenticated"'
  if [ -n "$admin_token" ]; then
    expect_status "the package upload takes 51 MiB" 100 \
      "$(upload_decision /api/admin/plugins/packages/ "$over_default_limit")"
  else
    echo "# SMOKE_ADMIN_TOKEN not set: skipping the check that the upload route takes 51 MiB"
  fi
  expect_status "other API routes keep the 50 MB limit" 413 \
    "$(upload_decision /api/admin/plugins/packages/1/approve/ "$over_default_limit")"
fi
expect_status "the package upload refuses more than PLUGINS_MAX_PACKAGE_MB" 413 \
  "$(upload_decision /api/admin/plugins/packages/ "$over_package_limit")"

if [ -n "$admin_token" ] && [ "$max_package_megabytes" -gt 51 ]; then
  dd if=/dev/zero of="$work_dir/package.esplugin" bs="$mebibyte" count=51 2> /dev/null
  status=$(fetch "$epicstaff_url/api/admin/plugins/packages/" -X POST --max-time 300 \
    -H "Authorization: Bearer $admin_token" -F "file=@$work_dir/package.esplugin")
  expect_status "a 51 MiB upload is streamed to Django, which refuses it as no package" 400 "$status"
  expect_body "Django's refusal names the problem" '"code":"invalid_plugin"'
else
  echo "# SMOKE_ADMIN_TOKEN not set: skipping the streamed 51 MiB upload"
fi

# requests_until URL DEADLINE OUTPUT BATCH PAUSE: GETs URL until DEADLINE (seconds since the
# epoch), BATCH requests per curl run over one connection, then PAUSE seconds. Appends a line per
# request to OUTPUT, "<status> <ms>", the time from sending the request to the end of the answer
# (connecting and the TLS handshake are left out); curl's errors go to OUTPUT.errors. It runs curl
# with the script's options, so the load reaches nginx exactly as the checks above do.
requests_until() {
  local url=$1 deadline=$2 output=$3 batch_size=$4 pause=$5 batch=()
  for _ in $(seq "$batch_size"); do
    batch+=(-o /dev/null "$url")
  done
  while [ "$(date +%s)" -lt "$deadline" ]; do
    curl -sS --max-time 10 -w '%{http_code} %{time_pretransfer} %{time_total}\n' \
      ${curl_options[@]+"${curl_options[@]}"} "${batch[@]}" 2>> "$output.errors" \
      | LC_ALL=C awk '{ printf "%s %.3f\n", $1, ($3 - $2) * 1000 }' >> "$output" || true
    sleep "$pause"
  done
}

# load_summary DESCRIPTION EXPECTED_STATUS OUTPUT: prints the count, p50 and p99 (nearest rank) of
# the answered requests in OUTPUT, and passes when every request was answered with
# EXPECTED_STATUS.
load_summary() {
  local description=$1 expected=$2 output=$3 requests answered unexpected statuses first_error
  requests=$(wc -l < "$output" | tr -d ' ')
  answered=$(awk '$1 != "000"' "$output" | wc -l | tr -d ' ')
  if [ "$answered" -eq 0 ]; then
    fail "$description: none of $requests request(s) was answered: $(head -n 1 "$output.errors")"
    return
  fi
  awk '$1 != "000" { print $2 }' "$output" | LC_ALL=C sort -n | LC_ALL=C awk -v description="$description" \
    -v requests="$requests" '
    { latency[NR] = $1 }
    END {
      printf "%s: %d requests, p50 %.1f ms, p99 %.1f ms", description, requests,
        latency[int((NR * 50 + 99) / 100)], latency[int((NR * 99 + 99) / 100)]
    }'
  unexpected=$(awk -v expected="$expected" '$1 != expected' "$output" | wc -l | tr -d ' ')
  echo ", unexpected statuses $unexpected"
  if [ "$unexpected" -eq 0 ]; then
    pass "$description: every request got $expected"
  else
    statuses=$(awk -v expected="$expected" '
      $1 != expected { count[$1]++ }
      END { for (status in count) { printf "%s %d got %s", separator, count[status], status; separator = "," } }' \
      "$output")
    first_error=$(head -n 1 "$output.errors")
    fail "$description: $unexpected request(s) did not get $expected:$statuses${first_error:+ ($first_error)}"
  fi
}

if [ -n "$load_seconds" ]; then
  echo "# the gateway check under load ($load_seconds s, 8 connections)"
  # The login refusal runs the whole check but the signing; the public path, limited by its
  # rate, is sampled once a second for the signed answer.
  : > "$work_dir/load-public"
  deadline=$(($(date +%s) + load_seconds))
  for worker in 1 2 3 4 5 6 7 8; do
    : > "$work_dir/load-refused.$worker"
    requests_until "$plugin_origin/api/x" "$deadline" "$work_dir/load-refused.$worker" 50 0 &
    load_pids+=("$!")
  done
  requests_until "$plugin_origin$public_path" "$deadline" "$work_dir/load-public" 1 1
  wait "${load_pids[@]}" || true
  load_pids=()
  cat "$work_dir"/load-refused.? > "$work_dir/load-refused"
  cat "$work_dir"/load-refused.?.errors > "$work_dir/load-refused.errors" 2> /dev/null || true
  load_summary "401 login_required under load" 401 "$work_dir/load-refused"
  load_summary "200 public path (signed context), sampled" 200 "$work_dir/load-public"
fi

summary_printed=true
if [ "$failures" -ne 0 ]; then
  echo "FAILED: $failures check(s)"
  exit 1
fi
echo "All plugin smoke checks passed."
