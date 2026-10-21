#!/usr/bin/env bash
# Checks the plugin platform's nginx routes on a running stack with PLUGINS_ENABLED=true and at
# least one approved plugin, through epicstaff-nginx, the way a browser reaches them:
#
#   - the plugin host serves the plugin's SPA with the security headers, every index.html with
#     Cache-Control: no-cache, the platform config from Django, and 404 for the platform's paths;
#   - its /api/ goes through the gateway: a declared public path reaches the plugin's backend with
#     a public context, any other path is 401 login_required, paths that are not canonical and
#     /_epicstaff/ never reach it, and a context a client forges never counts;
#   - a host name that is not a valid plugin host reaches EpicStaff's own server;
#   - EpicStaff's server frames plugin hosts (frame-src), refuses a package upload without a
#     SuperAdmin's login before reading it, and takes a SuperAdmin's upload above its usual 50 MB
#     limit, up to PLUGINS_MAX_PACKAGE_MB.
#
# Settings, from the environment:
#   EPICSTAFF_URL           EpicStaff's origin, as in DJANGO_FRONTEND_BASE_URL, e.g. http://epicstaff.localhost
#   PLUGINS_BASE_DOMAIN     e.g. plugins.epicstaff.localhost
#   PLUGIN_IDENTIFIER       an approved plugin with a backend, running, e.g. weather (the sample
#                           at 0.2.0: public path GET /api/ping, which answers its context's mode)
#   PLUGINS_MAX_PACKAGE_MB  the stack's upload limit, e.g. 300
#   PUBLIC_PATH             optional, default /api/ping: a public GET path of the plugin that
#                           answers 200 with "mode": "public"
#   GATEWAY_LOAD_SECONDS    optional: also measure the gateway check under load for this many
#                           seconds and print its p50/p99 (needs python3)
#   SMOKE_ADMIN_TOKEN       optional: a SuperAdmin's access token. Adds the checks that need a
#                           login: the upload route takes 51 MiB, and a real 51 MiB upload that
#                           Django must read to the end and refuse as an invalid package.
# Arguments: extra curl options for every request, e.g. --insecure for a self-signed certificate,
# or --connect-to ::127.0.0.1:8080 to reach nginx at another address without DNS entries.
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
trap 'rm -rf "$work_dir"' EXIT

failures=0
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

expect_body() { # $1 = description, $2 = text the body must contain
  if grep -qF -- "$2" "$work_dir/body"; then
    pass "$1"
  else
    fail "$1: body has no [$2]: $(head -c 200 "$work_dir/body")"
  fi
}

# The headers every plugin host response carries, whatever its status.
expect_plugin_security_headers() { # $1 = what was requested
  expect_header "$1: frame-ancestors" Content-Security-Policy "frame-ancestors 'self' $epicstaff_origin"
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

for path in /_epicstaff/x /.well-known/epicstaff/x; do
  status=$(fetch "$plugin_origin$path")
  expect_status "$path is 404" 404 "$status"
  expect_plugin_security_headers "$path"
done

echo "# the plugin's API, through the gateway"

status=$(fetch "$plugin_origin$public_path")
expect_status "the public path $public_path reaches the plugin" 200 "$status"
expect_body "the plugin got a verified public context" '"mode":"public"'
expect_no_header "the plugin's response sets no cookie" Set-Cookie
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
expect_plugin_security_headers "/api/x"

for path in /api/%2e%2e/_epicstaff/health /api/public/../x /api/..%2f_epicstaff/health \
  /api/%252e%252e/_epicstaff/health "$public_path/../x"; do
  status=$(fetch "$plugin_origin$path" --path-as-is)
  expect_status "$path never reaches the plugin" 404 "$status"
done

status=$(fetch "$unknown_plugin_origin$public_path")
expect_status "an unknown plugin's API is 404" 404 "$status"
expect_body "an unknown plugin's API has EpicStaff's error shape" '"code":"not_found"'

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

if [ -n "$load_seconds" ]; then
  echo "# the gateway check under load ($load_seconds s, 8 connections)"
  # The login refusal runs the whole check but the signing; the public path, limited by its
  # rate, is sampled once a second for the signed answer.
  python3 - "$plugin_origin/api/x" "$plugin_origin$public_path" "$load_seconds" \
    ${curl_options[@]+"${curl_options[@]}"} <<'PYTHON'
import http.client, ssl, statistics, sys, threading, time, urllib.parse

refused_url, public_url, seconds = sys.argv[1], sys.argv[2], float(sys.argv[3])
insecure = "--insecure" in sys.argv[4:]


def connection(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https":
        context = ssl._create_unverified_context() if insecure else ssl.create_default_context()
        return http.client.HTTPSConnection(parts.netloc, context=context, timeout=10), parts.path
    return http.client.HTTPConnection(parts.netloc, timeout=10), parts.path


def timed(client, path, expected, samples, failures):
    started = time.perf_counter()
    client.request("GET", path)
    response = client.getresponse()
    response.read()
    samples.append((time.perf_counter() - started) * 1000)
    if response.status != expected:
        failures.append(response.status)


def hammer(samples, failures, deadline):
    client, path = connection(refused_url)
    while time.monotonic() < deadline:
        timed(client, path, 401, samples, failures)


def percentiles(name, samples, failures):
    quantiles = statistics.quantiles(samples, n=100)
    print(f"{name}: {len(samples)} requests, p50 {quantiles[49]:.1f} ms, p99 {quantiles[98]:.1f} ms,"
          f" unexpected statuses {len(failures)}")


deadline = time.monotonic() + seconds
refused, refused_failures, public, public_failures = [], [], [], []
workers = [threading.Thread(target=hammer, args=(refused, refused_failures, deadline)) for _ in range(8)]
for worker in workers:
    worker.start()
client, path = connection(public_url)
while time.monotonic() < deadline:
    timed(client, path, 200, public, public_failures)
    time.sleep(1)
for worker in workers:
    worker.join()
percentiles("401 login_required under load", refused, refused_failures)
percentiles("200 public path (signed context), sampled", public, public_failures)
PYTHON
fi

if [ "$failures" -ne 0 ]; then
  echo "FAILED: $failures check(s)"
  exit 1
fi
echo "All plugin smoke checks passed."
