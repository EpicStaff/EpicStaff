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
# The lab's nginx runs with NGINX_HSTS_ENABLED=true (compose.yaml), over plain http.
hsts="max-age=31536000; includeSubDomains"
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
# Every value of a header the answer repeats, sorted and |-joined.
header_values() {
  grep -i "^$1:" "$work/headers" | cut -d: -f2- | sed 's/^ *//; s/\r$//' | LC_ALL=C sort | paste -sd '|' -
}
code_of_body() { jq -r '.code // empty' "$work/body" 2> /dev/null; }
backend_header() { jq -r --arg name "$1" '[.headers[] | select(.[0] | ascii_downcase == $name) | .[1]] | join("|")' "$work/body"; }
decision_entry() { grep -F "$1" /evidence/decision.log | tail -n 1; }
# The X-Forwarded-Proto values "Django" got for the request with that probe, |-joined.
django_forwarded_proto() {
  decision_entry "$1" | jq -r '[.headers[] | select(.[0] | ascii_downcase == "x-forwarded-proto") | .[1]] | join("|")'
}
expect_django_forwarded_proto() { # description, probe, expected value
  local seen
  seen=$(django_forwarded_proto "$2")
  if [ "$seen" = "$3" ]; then
    pass "$1"
  else
    fail "$1: Django got X-Forwarded-Proto [$seen], expected [$3]"
  fi
}

# The reason in X-EpicStaff-Gateway-Deny for each code the gateway answers with.
deny_reason_of_code() {
  case "$1" in
    login_required) echo login ;;
    request_too_large) echo too_large ;;
    plugin_unavailable) echo unavailable ;;
    plugin_maintenance) echo maintenance ;;
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
    || [ "$(header Origin-Agent-Cluster)" != "?1" ] || [ "$(header_values Strict-Transport-Security)" != "$hsts" ]; then
    fail "$description: the plugin host's security headers are missing (Strict-Transport-Security [$(header_values Strict-Transport-Security)])"
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
request down.plugins.epicstaff.test /api/ping
expect_refusal "an unavailable plugin is 503 plugin_unavailable" 503 plugin_unavailable "Retry-After=30"
# The check refuses every path of a plugin being upgraded, public or not, with one reason.
maintenance_json='{"status_code":503,"code":"plugin_maintenance","message":"The plugin is being updated. Try again in a few minutes."}'
for path in /api/ping /api/private; do
  request updating.plugins.epicstaff.test "$path"
  if [ "$(cat "$work/body")" != "$maintenance_json" ] || [ "$(header Content-Type)" != application/json ]; then
    fail "a plugin being upgraded, $path: [$(head -c 200 "$work/body")] as [$(header Content-Type)]"
  else
    expect_refusal "a plugin being upgraded is 503 plugin_maintenance on $path, as JSON" 503 plugin_maintenance \
      "Retry-After=30" "WWW-Authenticate="
  fi
done
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

echo "# the maintenance flag: the SPA paths answer with the platform's page"

flag=/srv/plugin-spa/alpha/maintenance
page=/lab/plugin-platform/maintenance.html
page_policies=$(printf '%s\n' "frame-ancestors 'self' https://epicstaff.test" \
  "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'" | LC_ALL=C sort | paste -sd '|' -)
# As django_app writes it: an empty file next to "current", made under another name and renamed
# into place.
set_maintenance_flag() {
  local temporary
  temporary=$(mktemp /srv/plugin-spa/alpha/.maintenance.XXXXXX) && chmod 0644 "$temporary" \
    && mv -f "$temporary" "$flag"
}
expect_spa() { # description, path, text of the SPA's file
  request "$alpha" "$2"
  if [ "$status" = 200 ] && grep -qF "$3" "$work/body" && [ -z "$(header X-EpicStaff-Gateway-Deny)" ] \
    && [ "$(header_values Strict-Transport-Security)" = "$hsts" ]; then
    pass "$1"
  else
    fail "$1: got $status $(head -c 120 "$work/body")"
  fi
}
expect_maintenance_page() { # path
  local problems=""
  request "$alpha" "$1"
  [ "$status" = 503 ] || problems="$problems status $status;"
  cmp -s "$work/body" "$page" || problems="$problems not the committed page;"
  [ "$(header_values Content-Type)" = text/html ] || problems="$problems Content-Type [$(header_values Content-Type)];"
  [ "$(header_values Retry-After)" = 30 ] || problems="$problems Retry-After [$(header_values Retry-After)];"
  [ "$(header_values Cache-Control)" = no-store ] || problems="$problems Cache-Control [$(header_values Cache-Control)];"
  [ "$(header_values X-EpicStaff-Gateway-Deny)" = maintenance ] \
    || problems="$problems X-EpicStaff-Gateway-Deny [$(header_values X-EpicStaff-Gateway-Deny)];"
  [ "$(header_values Content-Security-Policy)" = "$page_policies" ] \
    || problems="$problems Content-Security-Policy [$(header_values Content-Security-Policy)];"
  [ "$(header_values X-Content-Type-Options)" = nosniff ] || problems="$problems no nosniff;"
  [ "$(header_values Origin-Agent-Cluster)" = '?1' ] || problems="$problems no Origin-Agent-Cluster;"
  [ "$(header_values Strict-Transport-Security)" = "$hsts" ] \
    || problems="$problems Strict-Transport-Security [$(header_values Strict-Transport-Security)];"
  [ -z "$(header_values Set-Cookie)$(header_values X-Frame-Options)" ] || problems="$problems Set-Cookie or X-Frame-Options;"
  if [ -z "$problems" ]; then
    pass "with the flag, $1 is 503 with the maintenance page and its headers"
  else
    fail "with the flag, $1:$problems"
  fi
}
post_status() { curl -s -o /dev/null -w '%{http_code}' -X POST -H "Host: $alpha" "$gateway/" || true; }

rm -f "$flag"
expect_spa "without the flag, / is the plugin's SPA" / SPA-ALPHA-INDEX
expect_spa "without the flag, an asset is the plugin's" /assets/app.css SPA-ALPHA-ASSET
post_without_flag=$(post_status)
set_maintenance_flag
for path in / /index.html /assets/app.css /places/lisbon; do
  expect_maintenance_page "$path"
done
request "$alpha" / --head
if [ "$status" = 503 ] && [ "$(header X-EpicStaff-Gateway-Deny)" = maintenance ] \
  && [ "$(header Content-Length)" = "$(wc -c < "$page" | tr -d ' ')" ]; then
  pass "with the flag, HEAD / is 503 with the page's headers"
else
  fail "with the flag, HEAD /: got $status, deny [$(header X-EpicStaff-Gateway-Deny)], length [$(header Content-Length)]"
fi
# nginx serves static files to GET and HEAD only, with or without the flag.
post_with_flag=$(post_status)
if [ "$post_with_flag" = 405 ] && [ "$post_without_flag" = 405 ]; then
  pass "a POST to an SPA path is 405, with the flag as without it"
else
  fail "a POST to an SPA path: $post_without_flag without the flag, $post_with_flag with it"
fi
request "$alpha" /.well-known/epicstaff/config.json
if [ "$status" = 200 ] && [ "$(jq -r .path "$work/body")" = /api/plugin-public/alpha/config/ ]; then
  pass "with the flag, the platform config is still Django's"
else
  fail "with the flag, the platform config: got $status $(head -c 120 "$work/body")"
fi
request "$alpha" /api/ping
if [ "$status" = 200 ] && [ "$(jq -r .backend "$work/body")" = alpha ]; then
  pass "with the flag, /api/ still follows the gateway check (the flag is for the SPA paths)"
else
  fail "with the flag, /api/ping: got $status $(head -c 120 "$work/body")"
fi
rm -f "$flag"
expect_spa "the flag removed, / is the SPA again at once (no reload, no cache)" / SPA-ALPHA-INDEX
expect_spa "the flag removed, the asset is served again" /assets/app.css SPA-ALPHA-ASSET

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

echo "# X-Forwarded-Proto: the load balancer's (NGINX_TRUSTED_PROXIES), nobody else's"

# The lab's nginx trusts only the load balancer (compose.yaml), which ends TLS and sends https. A
# client that reaches nginx directly, as this container also does, gets nginx's own scheme, http,
# whatever it claims. Django builds its absolute URLs (avatars, the flow assistant's stream) from
# what arrives here.
load_balancer=https://lb
curl -sk -o /dev/null -H "Host: $main_host" "$load_balancer/api/forwarded/?probe=proto-through-lb"
expect_django_forwarded_proto "through the TLS-ending load balancer, Django is told https" \
  probe=proto-through-lb https
curl -s -o /dev/null -H "Host: $main_host" "$gateway/api/forwarded/?probe=proto-direct"
expect_django_forwarded_proto "a client that reaches nginx directly: Django is told nginx's own scheme, http" \
  probe=proto-direct http
curl -s -o /dev/null -H "Host: $main_host" -H 'X-Forwarded-Proto: https' \
  "$gateway/api/forwarded/?probe=proto-spoofed"
expect_django_forwarded_proto "a client that reaches nginx directly and claims https: Django is still told http" \
  probe=proto-spoofed http
curl -sk -o "$work/body" -H "Host: $alpha" "$load_balancer/api/public/echo?probe=proto-plugin-lb"
if [ "$(backend_header x-forwarded-proto)" = https ]; then
  pass "through the load balancer, a plugin backend is told https"
else
  fail "through the load balancer, a plugin backend is told [$(backend_header x-forwarded-proto)], not https"
fi
request "$alpha" '/api/public/echo?probe=proto-plugin-spoofed' -H 'X-Forwarded-Proto: https'
if [ "$(backend_header x-forwarded-proto)" = http ]; then
  pass "a client that reaches a plugin host directly and claims https: the plugin is told http"
else
  fail "directly, claiming https, a plugin backend is told [$(backend_header x-forwarded-proto)], not http"
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
if [ "$status" = 200 ] && [ "$(jq -r .backend "$work/body" 2> /dev/null)" = alpha ] \
  && [ -z "$(header Set-Cookie)" ] && [ -z "$(header Clear-Site-Data)" ] \
  && [ -z "$(header X-Frame-Options)" ] && [ -z "$(header X-EpicStaff-Gateway-Deny)" ]; then
  pass "the plugin's Set-Cookie, Clear-Site-Data, X-Frame-Options and X-EpicStaff-Gateway-Deny never reach the browser"
else
  fail "plugin response headers leaked ($status): Set-Cookie [$(header Set-Cookie)] Clear-Site-Data [$(header Clear-Site-Data)] X-Frame-Options [$(header X-Frame-Options)] X-EpicStaff-Gateway-Deny [$(header X-EpicStaff-Gateway-Deny)]"
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
if [ "$(header_values Strict-Transport-Security)" = "$hsts" ]; then
  pass "EpicStaff's own server sends the same Strict-Transport-Security as the plugin hosts"
else
  fail "EpicStaff's own server: Strict-Transport-Security [$(header_values Strict-Transport-Security)]"
fi
status=$(curl -s -o /dev/null -w '%{http_code}' -H 'X-Plugin-Identifier: alpha' http://decision:8000/api/plugin-gateway/check/)
[ "$status" = 404 ] && pass "the check itself answers 404 without the shared secret" \
  || fail "the check without the secret: $status"

echo "# the internal API listener refuses everything off the plugins network"

# /nginx-health too: the health server answers only on nginx's own 127.0.0.1.
for path in /api/plugin-nodes/self/desired-state/ /api/other/ / /nginx-health; do
  status=$(curl -s -o /dev/null -w '%{http_code}' "http://nginx:8081$path")
  [ "$status" = 403 ] && pass "8081 from outside the plugins network: $path is 403" \
    || fail "8081 from outside the plugins network: $path got $status"
done

fi

if [ "$side" = inside ]; then
echo "# the internal API listener (epicstaff-api:8081 on plugins-network)"

# /nginx-health is the internal listener's own 404 here: the health server answers only on
# nginx's 127.0.0.1, which shares the port.
for path in /api/auth/token/ /api/admin/plugins/ /api/plugin-gateway/check/ / /admin/ /nginx-health; do
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

# No load balancer is ever in front of this listener: whatever a plugin backend claims, Django is
# told nginx's own scheme.
curl -s -o /dev/null -H 'X-Forwarded-Proto: https' -H 'Authorization: PluginNodeKey lab-node-key' \
  "$internal_api/api/plugin-nodes/self/desired-state/?probe=proto-internal"
expect_django_forwarded_proto "the internal listener: a plugin backend that claims https, Django is told http" \
  probe=proto-internal http

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
