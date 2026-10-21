#!/usr/bin/env bash
# The gateway lab's checks, run by run.sh: `checks.sh outside` in the tools container (a browser's
# view), `checks.sh inside` in the inside container (on the plugins network, as a plugin backend
# or the node). One `ok -` or `not ok -` line per check; exits non-zero when any fails.
set -u
side=${1:?usage: checks.sh outside|inside}

gateway=http://nginx
alpha=alpha.plugins.epicstaff.test
main_host=epicstaff.test
internal_api=http://epicstaff-api:8081
work=$(mktemp -d)
failures=0

pass() { echo "ok - $1"; }
fail() {
  echo "not ok - $1"
  failures=$((failures + 1))
}

# request HOST PATH [curl args...]: the status goes to $status, headers and body to files.
request() {
  local host=$1 path=$2
  shift 2
  status=$(curl -s --path-as-is -o "$work/body" -D "$work/headers" -w '%{http_code}' \
    -H "Host: $host" "$@" "$gateway$path" || true)
}
header() { grep -i "^$1:" "$work/headers" | tail -n 1 | cut -d: -f2- | sed 's/^ *//; s/\r$//'; }
code_of_body() { jq -r '.code // empty' "$work/body" 2> /dev/null; }
backend_header() { jq -r --arg name "$1" '[.headers[] | select(.[0] | ascii_downcase == $name) | .[1]] | join("|")' "$work/body"; }
decision_entry() { grep -F "$1" /evidence/decision.log | tail -n 1; }

# The reason in X-EpicStaff-Gateway-Deny for each code the gateway answers with.
deny_reason_of_code() {
  case "$1" in
    login_required) echo login ;;
    request_too_large) echo too_large ;;
    plugin_unavailable) echo unavailable ;;
    *) echo "$1" ;;
  esac
}

expect_refusal() { # description, status, code, [header=value...]; uses the last request
  local description=$1 expected_status=$2 expected_code=$3
  shift 3
  if [ "$status" != "$expected_status" ] || [ "$(code_of_body)" != "$expected_code" ]; then
    fail "$description: got $status $(head -c 160 "$work/body")"
    return
  fi
  # Every answer the gateway gives itself names its reason, so a page can tell it from the
  # plugin's own 401 or 403.
  set -- "X-EpicStaff-Gateway-Deny=$(deny_reason_of_code "$expected_code")" "$@"
  local pair
  for pair in "$@"; do
    if [ "$(header "${pair%%=*}")" != "${pair#*=}" ]; then
      fail "$description: ${pair%%=*} is [$(header "${pair%%=*}")], expected [${pair#*=}]"
      return
    fi
  done
  if [ "$(header Content-Security-Policy)" != "frame-ancestors 'self' https://epicstaff.test" ] \
    || [ "$(header Origin-Agent-Cluster)" != "?1" ]; then
    fail "$description: the plugin host's security headers are missing"
    return
  fi
  pass "$description"
}

if [ "$side" = outside ]; then
echo "# refusals: the check's reason becomes EpicStaff's JSON error"

request "$alpha" /api/private
expect_refusal "a path that is not public, without login, is 401 login_required" 401 login_required \
  "WWW-Authenticate=Bearer"
request ghost.plugins.epicstaff.test /api/ping
expect_refusal "an unknown plugin is 404 not_found" 404 not_found
for _ in 1 2 3; do request "$alpha" /api/limited; done
request "$alpha" /api/limited
expect_refusal "a public path over its rate is 429 rate_limited" 429 rate_limited "Retry-After=60"
head -c 2000 /dev/zero > "$work/two-kilobytes"
request "$alpha" /api/upload --data-binary @"$work/two-kilobytes"
expect_refusal "a body above the public path's cap is 413 request_too_large" 413 request_too_large
request "$alpha" /api/upload -H 'Transfer-Encoding: chunked' --data-binary @"$work/two-kilobytes"
expect_refusal "a chunked body (no length) on a capped public path is 413" 413 request_too_large
head -c 1100000 /dev/zero > "$work/above-the-platform-cap"
request "$alpha" /api/public/echo --data-binary @"$work/above-the-platform-cap"
expect_refusal "a body above PLUGINS_MAX_REQUEST_BODY_MB is nginx's 413, as JSON" 413 request_too_large
request maint.plugins.epicstaff.test /api/ping
expect_refusal "an unavailable plugin is 503 plugin_unavailable" 503 plugin_unavailable "Retry-After=30"
request closed.plugins.epicstaff.test /api/ping
expect_refusal "a forbidden caller is 403 forbidden" 403 forbidden
request bogus.plugins.epicstaff.test /api/ping
expect_refusal "a reason nginx does not know fails closed as 503" 503 plugin_unavailable "Retry-After=30"
request emptydeny.plugins.epicstaff.test /api/ping
expect_refusal "a refusal without a reason fails closed as 503" 503 plugin_unavailable
request gone.plugins.epicstaff.test /api/ping
expect_refusal "a plugin process nginx cannot reach is 503 plugin_unavailable" 503 plugin_unavailable \
  "Retry-After=30"
request noupstream.plugins.epicstaff.test /api/ping
expect_refusal "a 200 without X-Plugin-Upstream fails closed as 503" 503 plugin_unavailable "Retry-After=30"
request checkerror.plugins.epicstaff.test /api/ping
expect_refusal "a check that django_app answers with an error fails closed as 503" 503 plugin_unavailable \
  "Retry-After=30"
request checkdown.plugins.epicstaff.test /api/ping
expect_refusal "a check whose connection django_app drops fails closed as 503" 503 plugin_unavailable \
  "Retry-After=30"

echo "# forwarding"

request "$alpha" /api/ping
if [ "$status" = 200 ] && [ "$(jq -r .backend "$work/body")" = alpha ] \
  && [ "$(backend_header x-epicstaff-plugin-context)" = "lab-context;alpha;public;GET;/api/ping" ] \
  && ! grep -qi '^x-epicstaff-gateway-deny:' "$work/headers"; then
  pass "a public path reaches the plugin (upstream plugin_alpha) with the gateway's context"
else
  fail "a public path: got $status $(head -c 200 "$work/body")"
fi
request "$alpha" '/api/public/echo?probe=post-method' --data-binary @"$work/two-kilobytes"
if [ "$(jq -r .body_bytes "$work/body")" = 2000 ] && [ "$(jq -r .method "$work/body")" = POST ] \
  && decision_entry 'probe=post-method' | jq -e '[.headers[] | select(.[0] == "X-Original-Method")][0][1] == "POST"' > /dev/null \
  && decision_entry 'probe=post-method' | jq -e '[.headers[] | select(.[0] == "X-Original-Content-Length")][0][1] == "2000"' > /dev/null; then
  pass "a POST body reaches the plugin; the check sees the method and length, not the body"
else
  fail "a POST through the gateway: $(head -c 200 "$work/body")"
fi

echo "# what reaches the plugin and the check"

request "$alpha" '/api/public/echo?probe=cookies' -H 'Cookie: sessionid=s3cret' -H 'Cookie: csrftoken=abc' \
  -H 'Authorization: Bearer plugin-own-token'
if [ -z "$(backend_header cookie)" ] && [ "$(backend_header authorization)" = "Bearer plugin-own-token" ]; then
  pass "on a public path Cookie is dropped and the plugin's own Authorization is forwarded"
else
  fail "public path headers: cookie [$(backend_header cookie)] authorization [$(backend_header authorization)]"
fi
if decision_entry 'probe=cookies' | jq -e '[.headers[] | select(.[0] | ascii_downcase == "cookie")] | length == 0' > /dev/null; then
  pass "the check never sees the client's Cookie"
else
  fail "the check saw a Cookie: $(decision_entry 'probe=cookies' | head -c 300)"
fi
request "$alpha" '/api/public/echo?probe=api-key' -H 'X-API-Key: epicstaff-key' -H 'X_API_Key: epicstaff-key'
if [ "$status" = 200 ] && [ -z "$(backend_header x-api-key)" ] && [ -z "$(backend_header x_api_key)" ]; then
  pass "an EpicStaff API key, in either spelling, never reaches the plugin"
else
  fail "API key at the plugin: [$(backend_header x-api-key)] [$(backend_header x_api_key)]"
fi
request "$alpha" /api/private -H 'Authorization: Bearer lab-login'
if [ "$status" = 200 ] && [ -z "$(backend_header authorization)" ]; then
  pass "on a path that is not public Authorization never reaches the plugin"
else
  fail "a non-public path: got $status, authorization [$(backend_header authorization)]"
fi
request "$alpha" /api/public/echo -H 'X_EpicStaff_Plugin_Context: FORGED-1' \
  -H 'X-EpicStaff-Plugin_Context: FORGED-2' -H 'X-EpicStaff-Plugin-Context: FORGED-3' \
  -H 'x-epicstaff-plugin-context: FORGED-4' -H 'X_EpicStaff-Plugin-Context: FORGED-5'
contexts=$(jq -r '[.headers[] | select(.[0] | ascii_downcase | gsub("_"; "-") == "x-epicstaff-plugin-context") | .[1]] | join("|")' "$work/body")
if [ "$contexts" = "lab-context;alpha;public;POST;/api/public/echo" ] || [ "$contexts" = "lab-context;alpha;public;GET;/api/public/echo" ]; then
  pass "a client cannot add a context in any spelling: the plugin sees only the gateway's"
else
  fail "context headers at the plugin: [$contexts]"
fi
request "$alpha" '/api/private?probe=steer' -H 'X-Plugin-Identifier: bravo' -H 'X_Plugin_Identifier: bravo' \
  -H 'X-Original-URI: /api/ping' -H 'X-Original-Normalized-Path: /api/ping' -H 'X-Original-Method: GET' \
  -H 'X-Plugin-Gateway-Secret: guess'
seen=$(decision_entry 'probe=steer')
if [ "$status" = 401 ] \
  && echo "$seen" | jq -e '[.headers[] | select(.[0] == "X-Plugin-Identifier")] | map(.[1]) == ["alpha"]' > /dev/null \
  && echo "$seen" | jq -e '[.headers[] | select(.[0] == "X-Original-Normalized-Path")] | map(.[1]) == ["/api/private"]' > /dev/null \
  && echo "$seen" | jq -e --arg secret "$PLUGINS_GATEWAY_SECRET" '[.headers[] | select(.[0] == "X-Plugin-Gateway-Secret")] | map(.[1]) == [$secret]' > /dev/null \
  && ! echo "$seen" | grep -q 'X_Plugin_Identifier'; then
  pass "a client cannot steer the check with forged X-Plugin-* or X-Original-* headers"
else
  fail "forged check inputs: status $status, check saw $(echo "$seen" | head -c 400)"
fi
if echo "$seen" | jq -e '[.headers[] | select(.[0] == "Host")] | map(.[1]) == ["localhost"]' > /dev/null; then
  pass "the check is asked with Host: localhost"
else
  fail "the check's Host: $(echo "$seen" | jq -c '[.headers[] | select(.[0] == "Host")]')"
fi
request "$alpha" /api/public/echo
if [ -z "$(header Set-Cookie)" ] && [ -z "$(header X-Frame-Options)" ] \
  && [ -z "$(header X-EpicStaff-Gateway-Deny)" ]; then
  pass "the plugin's Set-Cookie, X-Frame-Options and X-EpicStaff-Gateway-Deny never reach the browser"
else
  fail "plugin response headers leaked: Set-Cookie [$(header Set-Cookie)] X-Frame-Options [$(header X-Frame-Options)] X-EpicStaff-Gateway-Deny [$(header X-EpicStaff-Gateway-Deny)]"
fi
# The plugin's own 401, dressed as the gateway's: it reaches the page as the plugin's, unmarked.
request "$alpha" /api/public/denied
if [ "$status" = 401 ] && [ "$(code_of_body)" = login_required ] \
  && ! grep -qi '^x-epicstaff-gateway-deny:' "$work/headers"; then
  pass "a plugin's own 401 reaches the page without X-EpicStaff-Gateway-Deny, in any letter case"
else
  fail "a plugin's own 401: got $status, X-EpicStaff-Gateway-Deny [$(header X-EpicStaff-Gateway-Deny)]"
fi
request "$alpha" /api/public/accel
if [ "$(cat "$work/body")" = BACKEND-BODY ] && ! grep -qi '^x-plugin-' "$work/headers"; then
  pass "the plugin's X-Accel-Redirect is ignored"
else
  fail "X-Accel-Redirect: $(grep -i '^x-plugin-' "$work/headers" | tr -d '\r') $(head -c 100 "$work/body")"
fi

echo "# streams"

python3 /lab/scripts/stream_clients.py && pass "SSE arrives unbuffered and WebSocket upgrades (101) through the check" \
  || fail "SSE or WebSocket through the check (see above)"

echo "# paths the plugin must never get"

for path in /_epicstaff/health /api/../_epicstaff/health /api/%2e%2e/_epicstaff/health \
  /api/..%2f_epicstaff/health /api/%2E%2E%2F_epicstaff/health //_epicstaff/health \
  /api/x/../../_epicstaff/health /api/%252e%252e/_epicstaff/health /api/.%2e/_epicstaff/health \
  /api/public/../../_epicstaff/health /api/public/%2e%2e/%2e%2e/_epicstaff/health; do
  request "$alpha" "$path"
  if [ "$status" != 404 ]; then
    fail "$path: got $status"
  fi
done
if grep -q REACHED-EPICSTAFF /evidence/backend.log 2> /dev/null; then
  fail "a plugin received a /_epicstaff path: $(grep REACHED-EPICSTAFF /evidence/backend.log | head -n 3)"
else
  pass "no /_epicstaff path, encoded or not, reaches a plugin (all 404)"
fi
for path in /api/public/../private /api/public/%2e%2e/private /api/public/%2E%2E/private /api/public//private; do
  request "$alpha" "$path"
  if [ "$status" = 404 ] && [ "$(code_of_body)" = not_found ] \
    && [ "$(header X-EpicStaff-Gateway-Deny)" = not_found ]; then
    pass "a path that is not canonical is not_found: $path"
  else
    fail "a path that is not canonical: $path got $status"
  fi
done
request "$alpha" /_plugin_gateway_check
[ "$status" = 404 ] && pass "/_plugin_gateway_check is not reachable from outside" \
  || fail "/_plugin_gateway_check from outside: $status"
for path in /api/plugin-gateway/check/ /api//plugin-gateway/check/ /api/%70lugin-gateway/check/ \
  /api/plugin-nodes/self/desired-state/; do
  request "$main_host" "$path"
  [ "$status" = 404 ] && pass "EpicStaff's own server refuses $path" \
    || fail "EpicStaff's own server: $path got $status"
done
request "$main_host" /api/other/
[ "$status" = 200 ] && pass "control: EpicStaff's own server still proxies /api/" \
  || fail "control: /api/other/ got $status"
status=$(curl -s -o /dev/null -w '%{http_code}' -H 'X-Plugin-Identifier: alpha' http://decision:8000/api/plugin-gateway/check/)
[ "$status" = 404 ] && pass "the check itself answers 404 without the shared secret" \
  || fail "the check without the secret: $status"

echo "# the internal API listener refuses everything off the plugins network"

for path in /api/plugin-nodes/self/desired-state/ /api/other/ /; do
  status=$(curl -s -o /dev/null -w '%{http_code}' "http://nginx:8081$path")
  [ "$status" = 403 ] && pass "8081 from outside the plugins network: $path is 403" \
    || fail "8081 from outside the plugins network: $path got $status"
done

fi

if [ "$side" = inside ]; then
echo "# the internal API listener (epicstaff-api:8081 on plugins-network)"

for path in /api/auth/token/ /api/admin/plugins/ /api/plugin-gateway/check/ / /admin/; do
  probe="probe=refused${path//\//-}"
  status=$(curl -s -o /dev/null -w '%{http_code}' --path-as-is "$internal_api$path?$probe")
  if [ "$status" = 404 ] && ! grep -qF -- "$probe" /evidence/decision.log; then
    pass "the internal listener refuses $path"
  else
    fail "the internal listener: $path got $status"
  fi
done
curl -s -o "$work/body" "$internal_api/api/plugin-nodes/self/desired-state/?probe=internal" \
  -H 'Authorization: PluginNodeKey lab-node-key' -H 'If-None-Match: "abc"' -H 'X-Organization-Id: 3' \
  -H 'Cookie: sessionid=s3cret' -H 'X-API-Key: some-key' -H 'X_Forwarded_For: 6.6.6.6'
seen=$(decision_entry 'probe=internal')
if echo "$seen" | jq -e '
  ([.headers[] | .[0] | ascii_downcase] | (index("cookie") == null and index("x-api-key") == null))
  and ([.headers[] | select(.[0] == "Authorization")][0][1] == "PluginNodeKey lab-node-key")
  and ([.headers[] | select(.[0] == "If-None-Match")][0][1] == "\"abc\"")
  and ([.headers[] | select(.[0] == "X-Organization-Id")][0][1] == "3")
  and ([.headers[] | select(.[0] == "Host")][0][1] == "localhost")
  and ([.headers[] | select(.[0] == "X-Forwarded-For")][0][1] | test("6.6.6.6") | not)' > /dev/null; then
  pass "the internal listener passes Authorization, If-None-Match, X-Organization-Id; drops Cookie and X-API-Key"
else
  fail "the internal listener's headers: $(echo "$seen" | head -c 500)"
fi
curl -s -o "$work/body" -X POST "$internal_api/api/plugin-nodes/self/reports/?probe=report" \
  -H 'Content-Type: application/json' --data '{"format":1}'
seen=$(decision_entry 'probe=report')
if echo "$seen" | jq -e '.body_bytes == 12 and ([.headers[] | select(.[0] == "Content-Type")][0][1] == "application/json")' > /dev/null; then
  pass "the internal listener carries a JSON body and its Content-Type"
else
  fail "a POST through the internal listener: $(echo "$seen" | head -c 300)"
fi

echo "# a plugin backend cannot use EpicStaff's site or the plugin hosts (80/443)"

# Requests reach "Django" (the check or its API) and the plugins only as lines in the evidence.
evidence_lines() { cat /evidence/decision.log /evidence/backend.log 2> /dev/null | wc -l; }
evidence_before=$(evidence_lines)
for target in "$main_host /" "$main_host /api/other/" "$main_host /api/admin/plugins/packages/" \
  "$alpha /api/ping" "$alpha /api/public/echo" "$alpha /" "$alpha /.well-known/epicstaff/config.json"; do
  host=${target% *} path=${target#* }
  refused_everywhere=yes
  for address in http://nginx http://epicstaff-api; do
    status=$(curl -s --path-as-is -o /dev/null -w '%{http_code}' -H "Host: $host" "$address$path" || true)
    if [ "$status" != 403 ]; then
      fail "from the plugins network, $address $host$path answered $status, not 403"
      refused_everywhere=no
    fi
  done
  if [ "$refused_everywhere" = yes ]; then
    pass "from the plugins network, $host$path is refused (403)"
  fi
done
if [ "$(evidence_lines)" = "$evidence_before" ]; then
  pass "none of those requests reached the check, Django or a plugin"
else
  fail "a request from the plugins network reached the check, Django or a plugin"
fi

fi

rm -rf "$work"
if [ "$failures" -ne 0 ]; then
  echo "FAILED: $failures check(s)"
  exit 1
fi
echo "All gateway checks passed."
