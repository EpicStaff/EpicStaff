#!/usr/bin/env bash
# Checks the plugin login on a running stack with PLUGINS_ENABLED=true, through epicstaff-nginx,
# with curl only, doing what a browser, EpicStaff's pages and a plugin page do:
#
#   - logging in to EpicStaff sets the refresh cookie with the name and attributes of the
#     deployment's mode (HTTPS: __Host-auth.refresh, Path=/, Secure; plain http: auth.refresh,
#     Path=/api/auth/), never with a Domain; a cookie sent twice is no session, and on HTTPS the
#     old name auth.refresh is no session either; login takes JSON only (a form or text/plain is
#     refused with 415 and no cookie);
#   - the authorize endpoint sends a browser without a session to EpicStaff's sign-in page, and
#     one with a session to the plugin host's callback page with a code, setting no cookie;
#   - the plugin page exchanges the code for a token (PKCE) from its own origin, once, in JSON
#     only, with CORS for that origin and never with credentials;
#   - the token opens the plugin's /api/ as the person, and none of EpicStaff's API;
#   - a request from a plugin origin to EpicStaff's API is refused and leaves the session alone,
#     and so is a login, logout or refresh from Origin: null (a sandboxed frame, a data: URL);
#   - logging out ends the session.
#
# With plugins off (PLUGINS_ENABLED=false) it checks only the login cookie, that the plugin API and
# the authorize endpoint are not there (404), and the logout. It notices that by itself, from a
# 404 of /api/plugins/available/ and of the authorize endpoint, or is told with SMOKE_PLUGINS_OFF=1.
#
# Settings, from the environment:
#   SMOKE_BASE_URL      EpicStaff's origin, as in DJANGO_FRONTEND_BASE_URL, e.g. http://epicstaff.localhost
#   SMOKE_PLUGIN        an approved, running plugin with a backend that answers GET /api/whoami
#                       for a signed-in person, e.g. weather (the sample, 0.3.0 or later)
#   SMOKE_EMAIL         a person who may use the plugin in SMOKE_ORG_ID ...
#   SMOKE_PASSWORD      ... and their password (never printed, never on a command line)
#   SMOKE_ORG_ID        that organization's id (not needed with SMOKE_PLUGINS_OFF=1)
#   SMOKE_PLUGINS_OFF   optional: 1 when the stack runs with plugins off
#   SMOKE_LOAD_SECONDS  optional: also time GET /api/whoami with the token for this many seconds
#                       and print p50/p99: with wrk (8 connections) when it is on PATH and the
#                       plugin host resolves, otherwise with curl (one connection)
# Arguments: extra curl options for every request, e.g. --cacert <file> (or -k) for a local CA,
# or --connect-to ::127.0.0.1: to reach nginx without DNS entries.
#
# It sends up to four login requests, of which one may succeed: EpicStaff allows 5 a minute per
# address and email, so leave a minute between two runs. It logs out at the end, also when it
# stops early. Passwords, cookies and tokens go to curl in files, never on its command line.
#
# Usage:
#   SMOKE_BASE_URL=http://epicstaff.localhost SMOKE_PLUGIN=weather SMOKE_EMAIL=ada@example.com \
#   SMOKE_PASSWORD=... SMOKE_ORG_ID=3 bash src/nginx/tests/login_smoke.sh
#   SMOKE_BASE_URL=https://epicstaff.example.com SMOKE_PLUGIN=weather SMOKE_EMAIL=ada@example.com \
#   SMOKE_PASSWORD=... SMOKE_PLUGINS_OFF=1 bash src/nginx/tests/login_smoke.sh
set -euo pipefail

base_url=${SMOKE_BASE_URL:?set SMOKE_BASE_URL, e.g. http://epicstaff.localhost}
plugin=${SMOKE_PLUGIN:?set SMOKE_PLUGIN to an approved plugin with a backend, e.g. weather}
email=${SMOKE_EMAIL:?set SMOKE_EMAIL}
password=${SMOKE_PASSWORD:?set SMOKE_PASSWORD}
plugins_off=${SMOKE_PLUGINS_OFF:-0}
case "$plugins_off" in
  0 | 1) ;;
  *)
    echo "ERROR: SMOKE_PLUGINS_OFF='$plugins_off' is neither 0 nor 1" >&2
    exit 2
    ;;
esac
if [ "$plugins_off" = 1 ]; then
  org_id=${SMOKE_ORG_ID-}
else
  org_id=${SMOKE_ORG_ID:?set SMOKE_ORG_ID, or SMOKE_PLUGINS_OFF=1 for a stack with plugins off}
fi
load_seconds=${SMOKE_LOAD_SECONDS-}
curl_options=("$@")
tests_dir=$(cd "$(dirname "$0")" && pwd)

if ! printf '%s\n' "$plugin" | grep -Eq '^[a-z][a-z0-9-]{0,30}[a-z0-9]$'; then
  echo "ERROR: SMOKE_PLUGIN='$plugin' is not a plugin identifier" >&2
  exit 2
fi
if [ -n "$org_id" ] || [ "$plugins_off" = 0 ]; then
  case "$org_id" in
    '' | *[!0-9]*)
      echo "ERROR: SMOKE_ORG_ID='$org_id' is not an organization id" >&2
      exit 2
      ;;
  esac
fi

scheme=${base_url%%://*}
authority=${base_url#*://}
authority=${authority%%/*}
epicstaff_origin=$scheme://$authority
case "$scheme" in
  https)
    cookie_name=__Host-auth.refresh
    cookie_path=/
    ;;
  http)
    cookie_name=auth.refresh
    cookie_path=/api/auth/
    ;;
  *)
    echo "ERROR: SMOKE_BASE_URL='$base_url' is not an http:// or https:// URL" >&2
    exit 2
    ;;
esac
legacy_cookie_name=auth.refresh
authorize_url=$epicstaff_origin/api/auth/plugin-authorize/
token_url=$epicstaff_origin/api/auth/plugin-token/

work_dir=$(mktemp -d)
chmod 700 "$work_dir"
# Set once logged in: then every way out logs out first, so no session of the smoke account
# outlives the run, whatever stopped it.
signed_in=0
logout_quietly() {
  curl -s -o /dev/null -X POST -H "@$work_dir/session" -H "@$work_dir/access" \
    ${curl_options[@]+"${curl_options[@]}"} "$epicstaff_origin/api/auth/logout/" 2> /dev/null || true
}
finish() {
  if [ "$signed_in" = 1 ]; then logout_quietly; fi
  rm -rf "$work_dir"
}
trap finish EXIT

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

# fetch URL [curl options...]: prints the status code; the response's headers go to
# $work_dir/headers (without carriage returns) and its body to $work_dir/body. A transport
# error prints 000.
fetch() {
  local url=$1 status
  shift
  rm -f "$work_dir/body" "$work_dir/raw-headers"
  : > "$work_dir/body"
  status=$(curl -sS -o "$work_dir/body" -D "$work_dir/raw-headers" -w '%{http_code}' \
    ${curl_options[@]+"${curl_options[@]}"} "$@" "$url" 2> "$work_dir/curl-error" || true)
  tr -d '\r' < "$work_dir/raw-headers" > "$work_dir/headers" 2> /dev/null || : > "$work_dir/headers"
  echo "$status"
}

# Every value of a header of the last response, sorted and joined with |.
header_values() {
  { grep -i "^$1:" "$work_dir/headers" || true; } | cut -d: -f2- | sed 's/^ *//' \
    | LC_ALL=C sort | paste -sd '|' -
}

# The "code" of an error body: what a failure may print, as a body can hold a token.
body_code() { sed -n 's/.*"code" *: *"\([^"]*\)".*/\1/p' "$work_dir/body" | head -n 1; }

# The value of a top-level JSON string field of the last body (the last one of that name).
json_string() { tr -d '\n' < "$work_dir/body" | sed -n "s/.*\"$1\" *: *\"\([^\"]*\)\".*/\1/p"; }

# The members of a JSON object field of the last body, e.g. `"id":3,"name":"Acme"` for "org".
json_object() { tr -d '\n' < "$work_dir/body" | sed -n "s/.*\"$1\":{\([^}]*\)}.*/\1/p"; }

# body_matches EXTENDED-REGEX: the last body, on one line, matches.
body_matches() { tr -d '\n' < "$work_dir/body" | grep -Eq -- "$1"; }

expect_status() { # $1 = description, $2 = expected status, $3 = actual status
  if [ "$3" = "$2" ]; then
    pass "$1"
  else
    fail "$1: status $3, expected $2 [code $(body_code)] $(head -c 200 "$work_dir/curl-error" 2> /dev/null)"
  fi
}

expect_header() { # $1 = description, $2 = header name, $3 = its only value
  if [ "$(header_values "$2")" = "$3" ]; then
    pass "$1"
  else
    fail "$1: $2 is [$(header_values "$2")], expected [$3]"
  fi
}

# Cache-Control includes no-store (Django's never_cache adds more directives; any is fine).
expect_no_store() { # $1 = description
  case ",$(header_values Cache-Control | tr -d ' ')," in
    *,no-store,*) pass "$1" ;;
    *) fail "$1: Cache-Control is [$(header_values Cache-Control)]" ;;
  esac
}

expect_no_header() { # $1 = description, $2 = header name
  if [ -z "$(header_values "$2")" ]; then
    pass "$1"
  else
    fail "$1: unexpected $2"
  fi
}

# Vary of the last response names Origin, in any letter case, alone or in a list.
expect_vary_origin() { # $1 = description
  case ",$(header_values Vary | tr -d ' ' | tr '[:upper:]' '[:lower:]' | tr '|' ',')," in
    *,origin,*) pass "$1" ;;
    *) fail "$1: Vary is [$(header_values Vary)]" ;;
  esac
}

expect_code() { # $1 = description, $2 = expected status, $3 = actual status, $4 = expected code
  if [ "$3" = "$2" ] && [ "$(body_code)" = "$4" ]; then
    pass "$1"
  else
    fail "$1: status $3 code [$(body_code)], expected $2 $4"
  fi
}

# Writes one request header to a file for `curl -H @file`, so its value is never on a command
# line. $1 = file name in $work_dir, $2 = the header line.
header_file() { printf '%s\n' "$2" > "$work_dir/$1"; }

# The Set-Cookie line of the last response for a cookie name, and one of its attributes:
# "set" for a flag, the value for name=value, nothing when absent.
set_cookie_line() {
  { grep -i "^set-cookie: *$1=" "$work_dir/headers" || true; } | sed 's/^[^:]*: *//' | tail -n 1
}
cookie_attribute() { # $1 = Set-Cookie value, $2 = attribute name
  printf '%s\n' "$1" | tr ';' '\n' | sed '1d; s/^ *//; s/ *$//' | awk -F= -v name="$2" '
    tolower($1) == tolower(name) { print (index($0, "=") ? substr($0, index($0, "=") + 1) : "set"); exit }'
}

# A login that should have been refused answered 200 after all: end that session too, from the
# last response's cookie and access token.
log_out_unexpected_session() {
  local stray_cookie stray_access
  stray_cookie=$(set_cookie_line "$cookie_name")
  stray_cookie=${stray_cookie%%;*}
  stray_access=$(json_string access)
  if [ -n "${stray_cookie#*=}" ] && [ -n "$stray_access" ]; then
    header_file stray-session "Cookie: $stray_cookie"
    header_file stray-access "Authorization: Bearer $stray_access"
    curl -s -o /dev/null -X POST -H "@$work_dir/stray-session" -H "@$work_dir/stray-access" \
      ${curl_options[@]+"${curl_options[@]}"} "$epicstaff_origin/api/auth/logout/" 2> /dev/null || true
  fi
}

# After a refresh that answered 200: go on with the rotated cookie and the new access token.
adopt_refreshed_session() {
  local rotated
  rotated=$(set_cookie_line "$cookie_name")
  rotated=${rotated%%;*}
  rotated=${rotated#*=}
  if [ -n "$rotated" ]; then
    refresh_token=$rotated
    header_file session "Cookie: $cookie_name=$refresh_token"
  fi
  if [ -n "$(json_string access)" ]; then
    access_token=$(json_string access)
    header_file access "Authorization: Bearer $access_token"
  fi
}

base64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }
percent_decode() {
  local value=${1//+/ }
  printf '%b' "${value//%/\\x}"
}

echo "# PKCE as the SDK computes it (RFC 7636, appendix B)"
if [ "$(printf '%s' dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk | openssl dgst -sha256 -binary | base64url)" \
  = E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM ]; then
  pass "this machine's openssl computes S256 challenges"
else
  bail_out "openssl does not compute the RFC 7636 S256 challenge"
fi
code_verifier=$(openssl rand 32 | base64url)
code_challenge=$(printf '%s' "$code_verifier" | openssl dgst -sha256 -binary | base64url)
state=$(openssl rand 32 | base64url)

echo "# logging in to EpicStaff $epicstaff_origin ($scheme: $cookie_name, Path=$cookie_path)"

json_escape() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
printf '{"email":"%s","password":"%s"}' "$(json_escape "$email")" "$(json_escape "$password")" \
  > "$work_dir/login.json"
status=$(fetch "$epicstaff_origin/api/auth/login/" -X POST -H 'Content-Type: application/json' \
  --data-binary "@$work_dir/login.json")
[ "$status" = 200 ] || bail_out "login as $email answered $status [code $(body_code)]"
access_token=$(json_string access)
refresh_cookie=$(set_cookie_line "$cookie_name")
refresh_token=${refresh_cookie%%;*}
refresh_token=${refresh_token#*=}
[ -n "$access_token" ] && [ -n "$refresh_token" ] \
  || bail_out "login gave no access token or no $cookie_name cookie (Set-Cookie: $(header_values Set-Cookie | sed 's/=[^;|]*/=…/g'))"
pass "login sets $cookie_name"
problems=""
[ "$(cookie_attribute "$refresh_cookie" Path)" = "$cookie_path" ] \
  || problems="$problems Path [$(cookie_attribute "$refresh_cookie" Path)];"
[ "$(cookie_attribute "$refresh_cookie" HttpOnly)" = set ] || problems="$problems no HttpOnly;"
[ "$(cookie_attribute "$refresh_cookie" SameSite)" = Lax ] \
  || problems="$problems SameSite [$(cookie_attribute "$refresh_cookie" SameSite)];"
[ -z "$(cookie_attribute "$refresh_cookie" Domain)" ] || problems="$problems a Domain;"
if [ "$scheme" = https ]; then
  [ "$(cookie_attribute "$refresh_cookie" Secure)" = set ] || problems="$problems no Secure;"
else
  # A browser would drop a Secure cookie that came over plain http, and the login with it.
  [ -z "$(cookie_attribute "$refresh_cookie" Secure)" ] || problems="$problems Secure over http;"
fi
if [ -z "$problems" ]; then
  pass "$cookie_name is HttpOnly, SameSite=Lax, Path=$cookie_path$([ "$scheme" = https ] && echo ', Secure'), without Domain"
else
  fail "$cookie_name attributes:$problems"
fi
if [ "$scheme" = https ]; then
  legacy_cookie=$(set_cookie_line "$legacy_cookie_name")
  if [ "$(cookie_attribute "$legacy_cookie" Max-Age)" = 0 ] \
    && [ "$(cookie_attribute "$legacy_cookie" Path)" = /api/auth/ ]; then
    pass "login expires the old $legacy_cookie_name cookie (Path=/api/auth/, Max-Age=0)"
  else
    fail "login does not expire the old $legacy_cookie_name cookie: [$(printf '%s' "$legacy_cookie" | sed 's/=[^;]*/=…/')]"
  fi
fi
header_file access "Authorization: Bearer $access_token"
header_file session "Cookie: $cookie_name=$refresh_token"
signed_in=1

echo "# login takes JSON only"

# The right password, so only the media type can refuse them.
printf '%s' "$email" > "$work_dir/email"
printf '%s' "$password" > "$work_dir/password"
status=$(fetch "$epicstaff_origin/api/auth/login/" -X POST \
  --data-urlencode "email@$work_dir/email" --data-urlencode "password@$work_dir/password")
rm -f "$work_dir/email" "$work_dir/password"
expect_code "a form-encoded login is refused" 415 "$status" unsupported_media_type
expect_no_header "... without setting a cookie" Set-Cookie
if [ "$status" = 200 ]; then log_out_unexpected_session; fi
status=$(fetch "$epicstaff_origin/api/auth/login/" -X POST -H 'Content-Type: text/plain' \
  --data-binary "@$work_dir/login.json")
expect_code "a text/plain login is refused" 415 "$status" unsupported_media_type
expect_no_header "... without setting a cookie" Set-Cookie
if [ "$status" = 200 ]; then log_out_unexpected_session; fi

echo "# the refresh cookie is read only under its own name, and only once"

header_file duplicated "Cookie: $cookie_name=$refresh_token; $cookie_name=$refresh_token"
# A refresh that wrongly answers 200 rotates the token; the checks after it go on with the new one.
status=$(fetch "$epicstaff_origin/api/auth/refresh/" -X POST -H "@$work_dir/duplicated")
expect_status "$cookie_name sent twice is no session (refresh 401)" 401 "$status"
if [ "$status" = 200 ]; then adopt_refreshed_session; fi
if [ "$scheme" = https ]; then
  header_file legacy "Cookie: $legacy_cookie_name=$refresh_token"
  status=$(fetch "$epicstaff_origin/api/auth/refresh/" -X POST -H "@$work_dir/legacy")
  expect_status "the old name $legacy_cookie_name alone is no session on HTTPS (refresh 401)" 401 "$status"
  if [ "$status" = 200 ]; then adopt_refreshed_session; fi
fi
# Control: the cookie itself, once, still works.
status=$(fetch "$epicstaff_origin/api/auth/refresh/" -X POST -H "@$work_dir/session")
expect_status "the same cookie, once, refreshes (200)" 200 "$status"
if [ "$status" = 200 ]; then adopt_refreshed_session; fi

# Ends the run: logs out, checks the session is gone, and reports.
log_out_and_report() {
  echo "# logging out"
  status=$(fetch "$epicstaff_origin/api/auth/logout/" -X POST -H "@$work_dir/session" -H "@$work_dir/access")
  expect_status "logout is accepted" 205 "$status"
  if [ "$status" = 205 ]; then signed_in=0; fi
  status=$(fetch "$epicstaff_origin/api/auth/refresh/" -X POST -H "@$work_dir/session")
  expect_status "after logout the cookie is no session (refresh 401)" 401 "$status"
  if [ "$failures" -ne 0 ]; then
    echo "FAILED: $failures check(s)"
    exit 1
  fi
  echo "All login smoke checks passed."
  exit 0
}

organization_header=()
if [ -n "$org_id" ]; then organization_header=(-H "X-Organization-Id: $org_id"); fi
status=$(fetch "$epicstaff_origin/api/plugins/available/" -H "@$work_dir/access" \
  ${organization_header[@]+"${organization_header[@]}"})
if [ "$plugins_off" = 1 ] || [ "$status" = 404 ]; then
  available_status=$status
  status=$(fetch "$authorize_url?plugin=$plugin&state=$state&code_challenge=$code_challenge&code_challenge_method=S256" \
    -H "@$work_dir/session")
  if [ "$plugins_off" = 0 ] && [ "$status" != 404 ]; then
    bail_out "/api/plugins/available/ answered 404, yet the authorize endpoint $status: is $org_id an organization of $email?"
  fi
  echo "# plugins are off"
  expect_status "the plugin API is not there (/api/plugins/available/ 404)" 404 "$available_status"
  expect_status "the authorize endpoint is not there (404), even with a session" 404 "$status"
  expect_no_header "... and sets no cookie" Set-Cookie
  log_out_and_report
fi

echo "# the plugin $plugin in organization $org_id"

# The first frame_origin after this plugin's identifier: its own (a quote inside a string value
# is escaped, so no name or URL can contain either key as written here).
available=$(tr -d '\n' < "$work_dir/body")
plugin_origin=""
after_identifier=${available#*"\"identifier\":\"$plugin\""}
if [ "$after_identifier" != "$available" ]; then
  after_origin_key=${after_identifier#*\"frame_origin\":\"}
  if [ "$after_origin_key" != "$after_identifier" ]; then
    plugin_origin=${after_origin_key%%\"*}
  fi
fi
[ "$status" = 200 ] && [ -n "$plugin_origin" ] \
  || bail_out "$plugin is not among the plugins $email may open in organization $org_id ($status)"
pass "$email may open $plugin in organization $org_id, at $plugin_origin"

status=$(fetch "$plugin_origin/.well-known/epicstaff/config.json")
if [ "$status" = 200 ] && body_matches "\"authorize_url\":\"$authorize_url\"" \
  && body_matches "\"token_url\":\"$token_url\""; then
  pass "the plugin's config names EpicStaff's authorize and token URLs"
else
  fail "the plugin's config.json ($status) does not name $authorize_url and $token_url"
fi

echo "# authorize"

query="plugin=$plugin&state=$state&code_challenge=$code_challenge&code_challenge_method=S256&org=$org_id"
expected_continue="/api/auth/plugin-authorize/?$query"

status=$(fetch "$authorize_url?$query")
location=$(header_values Location)
expect_status "without a session, authorize redirects" 302 "$status"
case "$location" in
  "$epicstaff_origin/plugin-login?continue="*)
    continue_value=$(percent_decode "${location#"$epicstaff_origin/plugin-login?continue="}")
    if [ "$continue_value" = "$expected_continue" ]; then
      pass "... to EpicStaff's /plugin-login, continuing with the same request rebuilt"
    else
      fail "... to /plugin-login, but continue is [$continue_value], expected [$expected_continue]"
    fi
    ;;
  *) fail "... to $epicstaff_origin/plugin-login?continue=, not to [$location]" ;;
esac
expect_no_header "... without setting a cookie" Set-Cookie
expect_no_store "... and is never cached"

status=$(fetch "$authorize_url?$query&prompt=none")
expect_status "without a session, a silent authorize redirects" 302 "$status"
expect_header "... to the silent callback page with login_required" Location \
  "$plugin_origin/.well-known/epicstaff/silent-callback.html#error=login_required&state=$state"

status=$(fetch "$authorize_url?$query" -H "@$work_dir/session")
location=$(header_values Location)
expect_status "with a session, authorize redirects" 302 "$status"
callback_prefix="$plugin_origin/.well-known/epicstaff/callback.html#code="
code=""
case "$location" in
  "$callback_prefix"*"&state=$state")
    code=${location#"$callback_prefix"}
    code=${code%"&state=$state"}
    ;;
esac
if printf '%s\n' "$code" | grep -Eq '^[A-Za-z0-9_-]{43}$'; then
  pass "... to the plugin host's callback page, with a code and the state in the fragment"
else
  fail "... to $callback_prefix<code>&state=<state>, not to [$(printf '%s' "$location" | sed 's/code=[^&]*/code=…/')]"
fi
expect_no_header "... without setting a cookie" Set-Cookie
expect_no_store "... and is never cached"
[ -n "$code" ] || bail_out "no code to exchange"

status=$(fetch "$plugin_origin/.well-known/epicstaff/callback.html")
expect_status "the plugin host serves that callback page" 200 "$status"

echo "# exchanging the code, from the plugin's origin"

status=$(fetch "$token_url" -X OPTIONS -H "Origin: $plugin_origin" \
  -H 'Access-Control-Request-Method: POST' -H 'Access-Control-Request-Headers: content-type')
expect_status "the preflight is answered" 204 "$status"
expect_header "... for exactly the plugin's origin" Access-Control-Allow-Origin "$plugin_origin"
expect_header "... for POST" Access-Control-Allow-Methods POST
expect_header "... with Content-Type" Access-Control-Allow-Headers content-type
expect_vary_origin "... varying by Origin"
expect_no_header "... never with credentials" Access-Control-Allow-Credentials

printf '{"code":"%s","code_verifier":"%s"}' "$code" "$code_verifier" > "$work_dir/exchange.json"
status=$(fetch "$token_url" -X POST -H "Origin: $plugin_origin" -H 'Content-Type: text/plain' \
  --data-binary "@$work_dir/exchange.json")
expect_code "a text/plain exchange is refused" 415 "$status" unsupported_media_type
expect_header "... with CORS for the plugin's origin" Access-Control-Allow-Origin "$plugin_origin"
# The body is checked before the code is looked up, so neither refusal uses the code up.
status=$(fetch "$token_url" -X POST -H "Origin: $plugin_origin" -H 'Content-Type: application/json')
expect_code "an empty JSON exchange is refused" 400 "$status" invalid
printf '{"code":' > "$work_dir/malformed.json"
status=$(fetch "$token_url" -X POST -H "Origin: $plugin_origin" -H 'Content-Type: application/json' \
  --data-binary "@$work_dir/malformed.json")
expect_code "a malformed JSON exchange is refused" 400 "$status" invalid

status=$(fetch "$token_url" -X POST -H "Origin: $plugin_origin" -H 'Content-Type: application/json' \
  --data-binary "@$work_dir/exchange.json")
plugin_token=$(json_string access_token)
expect_status "the JSON exchange, after those refusals, gives a token" 200 "$status"
problems=""
body_matches '"token_type":"Bearer"' || problems="$problems token_type;"
body_matches '"expires_in":900[,}]' || problems="$problems expires_in;"
json_object plugin | grep -Eq "(^|,)\"identifier\":\"$plugin\"(,|$)" || problems="$problems plugin;"
json_object org | grep -Eq "(^|,)\"id\":$org_id(,|$)" || problems="$problems org;"
tr -d '\n' < "$work_dir/body" | grep -iqF "\"email\":\"$email\"" || problems="$problems user;"
body_matches '"plugin_permissions":\[[^]]*"read"' || problems="$problems plugin_permissions;"
[ -n "$plugin_token" ] || problems="$problems access_token;"
if [ -z "$problems" ]; then
  pass "... for $email in organization $org_id, with read among the plugin permissions"
else
  fail "the token response is not as expected:$problems"
fi
expect_header "... with CORS for exactly the plugin's origin" Access-Control-Allow-Origin "$plugin_origin"
expect_vary_origin "... varying by Origin"
expect_no_header "... never with credentials" Access-Control-Allow-Credentials
expect_no_store "... never cached"
expect_no_header "... without setting a cookie" Set-Cookie

status=$(fetch "$token_url" -X POST -H "Origin: $plugin_origin" -H 'Content-Type: application/json' \
  --data-binary "@$work_dir/exchange.json")
expect_code "the same code a second time is refused" 400 "$status" invalid_grant
rm -f "$work_dir/exchange.json"
[ -n "$plugin_token" ] || bail_out "no plugin token to go on with"
header_file plugin-token "Authorization: Bearer $plugin_token"

echo "# the plugin's /api/ with the token"

status=$(fetch "$plugin_origin/api/whoami" -H "@$work_dir/plugin-token")
expect_status "/api/whoami with the token reaches the plugin" 200 "$status"
problems=""
body_matches '"mode":"user"' || problems="$problems mode;"
tr -d '\n' < "$work_dir/body" | grep -iqF "\"email\":\"$email\"" || problems="$problems user;"
json_object org | grep -Eq "(^|,)\"id\":$org_id(,|$)" || problems="$problems org;"
body_matches '"permissions":\[[^]]*"read"' || problems="$problems permissions;"
body_matches '"request":\{"method":"GET","path":"/api/whoami"\}' || problems="$problems request;"
if [ -z "$problems" ]; then
  pass "... with a user context: $email, organization $org_id, read"
else
  fail "the plugin's /api/whoami answer:$problems"
fi
expect_no_header "... and the plugin sets no cookie" Set-Cookie
expect_no_header "... nor looks like a refusal of the gateway's" X-EpicStaff-Gateway-Deny

status=$(fetch "$plugin_origin/api/whoami")
expect_code "/api/whoami without a token is refused by the gateway" 401 "$status" login_required
expect_header "... asking for a bearer token" WWW-Authenticate Bearer
expect_header "... marked as the gateway's, so the page signs in again" X-EpicStaff-Gateway-Deny login
status=$(fetch "$plugin_origin/api/whoami" -H "@$work_dir/access")
expect_code "/api/whoami with an EpicStaff access token is refused" 401 "$status" login_required
expect_header "... marked as the gateway's" X-EpicStaff-Gateway-Deny login

echo "# EpicStaff's API never takes the plugin token"

for path in /api/graphs/ /api/profile/; do
  status=$(fetch "$epicstaff_origin$path" -H "@$work_dir/plugin-token" -H "X-Organization-Id: $org_id")
  expect_status "the plugin token on $path is 401" 401 "$status"
done
status=$(fetch "$epicstaff_origin/api/profile/" -H "@$work_dir/access")
expect_status "control: EpicStaff's own access token on /api/profile/ is 200" 200 "$status"

echo "# a plugin page cannot use EpicStaff's API, even with the person's cookie"

for request in "POST /api/auth/refresh/" "POST /api/auth/logout/" "GET /api/graphs/"; do
  status=$(fetch "$epicstaff_origin${request#* }" -X "${request%% *}" -H "Origin: $plugin_origin" \
    -H "@$work_dir/session" -H "@$work_dir/access" -H "X-Organization-Id: $org_id")
  expect_code "$request from the plugin's origin is refused" 403 "$status" plugin_origin_refused
  if [ "$status" = 403 ] \
    && [ -n "$(header_values Access-Control-Allow-Credentials)$(header_values Set-Cookie)" ]; then
    fail "... yet the refusal allows credentials or sets a cookie"
  fi
done
status=$(fetch "$epicstaff_origin/api/graphs/" -H "Origin: $plugin_origin")
expect_code "GET /api/graphs/ from the plugin's origin is refused without any credentials too" 403 "$status" \
  plugin_origin_refused
# A sandboxed frame or a page from a data: URL sends Origin: null; it may not log in, out or refresh.
status=$(fetch "$epicstaff_origin/api/auth/login/" -X POST -H 'Origin: null' \
  -H 'Content-Type: application/json' --data-binary "@$work_dir/login.json")
expect_code "POST /api/auth/login/ from Origin: null is refused" 403 "$status" plugin_origin_refused
expect_no_header "... without setting a cookie" Set-Cookie
if [ "$status" = 200 ]; then log_out_unexpected_session; fi
for request in "/api/auth/logout/ session access" "/api/auth/refresh/ session"; do
  read -r path credentials <<< "$request"
  headers=()
  for credential in $credentials; do headers+=(-H "@$work_dir/$credential"); done
  status=$(fetch "$epicstaff_origin$path" -X POST -H 'Origin: null' "${headers[@]}")
  expect_code "POST $path from Origin: null is refused" 403 "$status" plugin_origin_refused
  expect_no_header "... without setting a cookie" Set-Cookie
  if [ "$status" = 200 ] && [ "$path" = /api/auth/refresh/ ]; then adopt_refreshed_session; fi
done
status=$(fetch "$epicstaff_origin/api/auth/refresh/" -X POST -H "@$work_dir/session")
expect_status "the session survived them (refresh 200)" 200 "$status"
if [ "$status" = 200 ]; then adopt_refreshed_session; fi

if [ -n "$load_seconds" ]; then
  echo "# GET /api/whoami with the token, for $load_seconds s"
  whoami_url="$plugin_origin/api/whoami"
  if command -v wrk > /dev/null && wrk -t 1 -c 1 -d 1s "$whoami_url" > /dev/null 2>&1; then
    # The token reaches wrk in a file, read by the script, not on its command line.
    cat > "$work_dir/wrk.lua" << LUA
local file = io.open("$work_dir/plugin-token")
local name, value = file:read("*l"):match("^([^:]+): (.*)$")
file:close()
wrk.headers[name] = value
dofile("$tests_dir/gateway/scripts/wrk_report.lua")
LUA
    wrk -t 2 -c 8 -d "${load_seconds}s" -s "$work_dir/wrk.lua" "$whoami_url" > "$work_dir/wrk.out" 2>&1 || true
    if ! grep -E '^(requests|p50)' "$work_dir/wrk.out"; then
      echo "# wrk printed no summary: $(head -n 3 "$work_dir/wrk.out" | tr '\n' ' ')"
    fi
  else
    : > "$work_dir/timings"
    for _ in $(seq 50); do
      printf 'url = "%s"\noutput = "/dev/null"\n' "$whoami_url"
    done > "$work_dir/batch.curl"
    deadline=$((SECONDS + load_seconds))
    while [ "$SECONDS" -lt "$deadline" ]; do
      curl -s -K "$work_dir/batch.curl" -H "@$work_dir/plugin-token" -w '%{http_code} %{time_total}\n' \
        ${curl_options[@]+"${curl_options[@]}"} >> "$work_dir/timings" || true
    done
    other=$(awk '$1 != 200' "$work_dir/timings" | wc -l | tr -d ' ')
    awk '{ print $2 * 1000 }' "$work_dir/timings" | LC_ALL=C sort -n > "$work_dir/sorted"
    awk -v other="$other" '{ times[NR] = $1 }
      END {
        if (NR == 0) { print "no request completed"; exit }
        p50 = times[int((NR - 1) * 0.50) + 1]; p99 = times[int((NR - 1) * 0.99) + 1]
        printf "curl, one connection: %d requests, p50 %.1f ms, p99 %.1f ms, non-200 %d\n", NR, p50, p99, other
      }' "$work_dir/sorted"
  fi
fi

log_out_and_report
