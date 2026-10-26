#!/usr/bin/env bash
# The development lab's checks, run by run.sh. One `ok -` or `not ok -` line per check; exits
# non-zero when any fails.
#   checks.sh outside  in the tools container: a browser's view of the plugin host with development
#                      mode on, and the developer machine's view of the development API listener;
#   checks.sh inside   in the inside container, on the plugins network: a plugin backend's view;
#   checks.sh off      in the tools container, against nginx-off (development mode off).
set -u
side=${1:?usage: checks.sh outside|inside|off}

plugin_host=alpha.plugins.epicstaff.localhost
decision=http://decision:8000
spa=/lab/spa/alpha/current
work=$(mktemp -d)
failures=0
unreachable_body="The development server for this plugin cannot be reached."

pass() { echo "ok - $1"; }
fail() {
  echo "not ok - $1"
  failures=$((failures + 1))
}

# request URL [curl args...]: the status goes to $status, headers and body to files.
request() {
  local url=$1
  shift
  status=$(curl -s --path-as-is -o "$work/body" -D "$work/headers" -w '%{http_code}' "$@" "$url" || true)
}
header() { grep -i "^$1:" "$work/headers" | tail -n 1 | cut -d: -f2- | sed 's/^ *//; s/\r$//'; }
header_count() { grep -ci "^$1:" "$work/headers" || true; }
# The names of the headers the last echoed request carried, lower case, "_" read as "-" (as
# Django folds them), one per line.
echoed_names() { jq -r '.headers[][0] | ascii_downcase | gsub("_"; "-")' "$work/body" 2> /dev/null; }
# Every value of one header (folded name) the last echoed request carried, |-joined.
echoed_values() {
  jq -r --arg name "$1" '[.headers[] | select(.[0] | ascii_downcase | gsub("_"; "-") == $name) | .[1]] | join("|")' \
    "$work/body" 2> /dev/null
}
set_decision() {
  curl -s -o /dev/null -X POST -H 'Content-Type: application/json' --data "$1" "$decision/lab/page-decision"
}
decisions() { curl -s "$decision/lab/page-decisions" | jq -r .count; }

case "$side" in
outside)
  gateway=http://nginx

  echo "# page decision 204: the published files"
  set_decision '{"answer": "published"}'
  before=$(decisions)
  request "$gateway/" -H "Host: $plugin_host" -H 'Cookie: sessionid=s3cret' -H 'Authorization: Bearer person'
  # The lab's nginx runs with NGINX_HSTS_ENABLED=false (compose.yaml): no Strict-Transport-Security.
  if [ "$status" = 200 ] && cmp -s "$work/body" "$spa/index.html" && [ "$(header Cache-Control)" = no-cache ] \
    && [ "$(header_count Strict-Transport-Security)" = 0 ]; then
    pass "/ is the published index.html, with no-cache and, with NGINX_HSTS_ENABLED=false, no Strict-Transport-Security"
  else
    fail "/ with the published files: $status, Cache-Control [$(header Cache-Control)], Strict-Transport-Security [$(header Strict-Transport-Security)]"
  fi
  last_decision=$(curl -s "$decision/lab/page-decisions")
  decision_names=$(jq -r '[.last_headers[][0] | ascii_downcase] | sort | join(" ")' <<< "$last_decision")
  if [ "$(jq -r .count <<< "$last_decision")" -gt "$before" ] \
    && [ "$(jq -r '[.last_headers[] | select(.[0] | ascii_downcase == "x-plugin-identifier") | .[1]] | join("|")' <<< "$last_decision")" = alpha ] \
    && [ "$decision_names" = "host x-plugin-gateway-secret x-plugin-identifier" ]; then
    pass "the page decision was asked, with the secret and the identifier and none of the browser's headers ($decision_names)"
  else
    fail "the page decision request: count $(jq -r .count <<< "$last_decision") after $before, headers [$decision_names]"
  fi
  request "$gateway/assets/app.css" -H "Host: $plugin_host"
  if [ "$status" = 200 ] && cmp -s "$work/body" "$spa/assets/app.css"; then
    pass "an asset is the published file"
  else
    fail "/assets/app.css with the published files: $status"
  fi
  request "$gateway/places/lisbon" -H "Host: $plugin_host"
  if [ "$status" = 200 ] && cmp -s "$work/body" "$spa/index.html"; then
    pass "a client route is the published index.html"
  else
    fail "/places/lisbon with the published files: $status"
  fi

  echo "# page decision 403 with X-Plugin-Spa-Upstream: the development server"
  # The stand-in refuses the plugin's host, as esbuild does: the lab tests the page proxy against
  # a development server nobody configured.
  request http://author:5173/ -H "Host: $plugin_host"
  if [ "$status" = 403 ] && grep -qF 'is not allowed' "$work/body"; then
    pass "the stand-in development server refuses the plugin's host (403), as esbuild does"
  else
    fail "the stand-in development server, asked for the plugin's host directly: $status $(head -c 120 "$work/body")"
  fi
  set_decision '{"answer": "development", "port": 5173}'
  request "$gateway/some/route?x=1&y=two" -H "Host: $plugin_host"
  if [ "$status" = 200 ] && [ "$(jq -r '.author' "$work/body" 2> /dev/null)" = true ] \
    && [ "$(jq -r '.raw_path' "$work/body")" = "/some/route?x=1&y=two" ]; then
    pass "a page request reaches the development server, path and query preserved"
  else
    fail "a page request with a development server: $status $(head -c 200 "$work/body")"
  fi
  request "$gateway/index.html" -H "Host: $plugin_host"
  if [ "$status" = 200 ] && [ "$(jq -r '.raw_path' "$work/body" 2> /dev/null)" = /index.html ]; then
    pass "/index.html comes from the development server too"
  else
    fail "/index.html with a development server: $status $(head -c 200 "$work/body")"
  fi
  request "$gateway/" -H "Host: $plugin_host"
  problems=""
  for name in Set-Cookie X-Frame-Options Clear-Site-Data X-EpicStaff-Gateway-Deny; do
    [ "$(header_count "$name")" = 0 ] || problems="$problems $name passed through;"
  done
  [ "$(header_count Content-Security-Policy)" = 1 ] \
    && [ "$(header Content-Security-Policy)" = "frame-ancestors 'self' http://epicstaff.localhost" ] \
    || problems="$problems Content-Security-Policy [$(header Content-Security-Policy)];"
  [ "$(header X-Content-Type-Options)" = nosniff ] || problems="$problems no nosniff;"
  [ "$(header Referrer-Policy)" = strict-origin-when-cross-origin ] || problems="$problems no Referrer-Policy;"
  [ "$(header Origin-Agent-Cluster)" = '?1' ] || problems="$problems no Origin-Agent-Cluster;"
  [ "$(header Cache-Control)" = max-age=60 ] || problems="$problems Cache-Control [$(header Cache-Control)];"
  [ "$(header_count Strict-Transport-Security)" = 0 ] \
    || problems="$problems Strict-Transport-Security with NGINX_HSTS_ENABLED=false;"
  if [ -z "$problems" ]; then
    pass "the development server's cookie, framing rule, policy, Clear-Site-Data and marker are hidden; the platform's headers are added, its caching header is kept"
  else
    fail "the development server's answer:$problems"
  fi

  request "$gateway/" -H "Host: $plugin_host" -H 'Cookie: sessionid=s3cret' -H 'Authorization: Bearer person' \
    -H 'X-API-Key: key-a' -H 'X_API_Key: key-b' -H 'X-API_Key: key-c' -H 'X_API-Key: key-d' \
    -H 'X-EpicStaff-Plugin-Context: forged' -H 'X_EpicStaff_Plugin_Context: forged' \
    -H 'X-EpicStaff_Plugin-Context: forged' -H 'X_Forwarded_For: 203.0.113.9'
  leaked=$(echoed_names | grep -xE 'cookie|authorization|x-api-key|x-epicstaff-plugin-context' | sort -u | paste -sd ' ' -)
  if [ "$status" = 200 ] && [ -z "$leaked" ] && [ "$(echoed_values host)" = localhost:5173 ] \
    && [ "$(echoed_values x-forwarded-host)" = "$plugin_host" ] \
    && ! echoed_values x-forwarded-for | grep -q 203.0.113.9; then
    pass "a browser's Cookie, Authorization, API key and plugin context never reach the development server, in any spelling; it is asked for localhost:5173, with the plugin's host in X-Forwarded-Host"
  else
    fail "what reached the development server: status $status, leaked [$leaked], Host [$(echoed_values host)], X-Forwarded-Host [$(echoed_values x-forwarded-host)], X-Forwarded-For [$(echoed_values x-forwarded-for)]"
  fi

  if python3 /lab/scripts/stream_clients.py; then
    pass "live reload works through the page proxy: an event stream asked for with Accept: text/event-stream arrives unbuffered, a WebSocket upgrades (101) and echoes"
  else
    fail "server-sent events or the WebSocket through the page proxy"
  fi

  echo "# a development server that cannot be reached"
  # expect_unreachable DESCRIPTION DECISION
  expect_unreachable() {
    set_decision "$2"
    request "$gateway/" -H "Host: $plugin_host"
    if [ "$status" = 503 ] && [ "$(cat "$work/body")" = "$unreachable_body" ] \
      && [ "$(header Content-Type)" = text/html ] && [ "$(header X-EpicStaff-Gateway-Deny)" = unavailable ] \
      && [ "$(header Content-Security-Policy)" = "frame-ancestors 'self' http://epicstaff.localhost" ] \
      && [ "$(header_count Strict-Transport-Security)" = 0 ]; then
      pass "$1: 503 text/html, the one sentence, marked unavailable"
    else
      fail "$1: $status [$(header Content-Type)] [$(header X-EpicStaff-Gateway-Deny)] $(head -c 120 "$work/body")"
    fi
  }
  expect_unreachable "403 without an upstream (host.docker.internal does not resolve)" '{"answer": "unresolved"}'
  expect_unreachable "nothing listens on the development server's port" '{"answer": "development", "port": 5999}'
  expect_unreachable "the page decision fails (500)" '{"answer": "error"}'
  expect_unreachable "the page decision does not answer" '{"answer": "drop"}'

  echo "# the paths development mode does not change"
  set_decision '{"answer": "development", "port": 5173}'
  before=$(decisions)
  request "$gateway/.well-known/epicstaff/config.json" -H "Host: $plugin_host"
  if [ "$status" = 200 ] && [ "$(jq -r '.path' "$work/body" 2> /dev/null)" = /api/plugin-public/alpha/config/ ]; then
    pass "/.well-known/epicstaff/config.json is still Django's"
  else
    fail "/.well-known/epicstaff/config.json: $status $(head -c 160 "$work/body")"
  fi
  request "$gateway/.well-known/epicstaff/callback.html" -H "Host: $plugin_host"
  if [ "$status" = 200 ] && cmp -s "$work/body" /lab/plugin-platform/callback.html; then
    pass "/.well-known/epicstaff/callback.html is still the platform's page"
  else
    fail "/.well-known/epicstaff/callback.html: $status"
  fi
  wrong=""
  for path in /_epicstaff/x /_plugin_development_page_check /_plugin_gateway_check; do
    request "$gateway$path" -H "Host: $plugin_host"
    [ "$status" = 404 ] || wrong="$wrong [$path: $status]"
  done
  if [ -z "$wrong" ]; then
    pass "/_epicstaff/ and both internal checks answer 404"
  else
    fail "paths that must answer 404:$wrong"
  fi
  request "$gateway/api/ping" -H "Host: $plugin_host"
  if [ "$status" = 200 ] && [ "$(jq -r '.backend' "$work/body" 2> /dev/null)" = alpha ]; then
    pass "/api/ still goes through the gateway check to the plugin's backend"
  else
    fail "/api/ping: $status $(head -c 160 "$work/body")"
  fi
  if [ "$(decisions)" = "$before" ]; then
    pass "none of these paths asked the page decision"
  else
    fail "the page decision was asked $(($(decisions) - before)) time(s) for paths development mode does not change"
  fi
  touch /srv/plugin-spa/alpha/maintenance
  before=$(decisions)
  request "$gateway/" -H "Host: $plugin_host"
  if [ "$status" = 503 ] && [ "$(header X-EpicStaff-Gateway-Deny)" = maintenance ] && [ "$(decisions)" = "$before" ]; then
    pass "while the plugin is being upgraded its page is the maintenance page, and the page decision is not asked"
  else
    fail "with the maintenance flag: $status [$(header X-EpicStaff-Gateway-Deny)], decisions $before then $(decisions)"
  fi
  rm -f /srv/plugin-spa/alpha/maintenance

  echo "# the development API listener, from outside the plugins network"
  listener=http://nginx:8082
  request "$listener/api/plugin-runtime/me/" -H 'Authorization: PluginKey esp-lab' -H 'X-Organization-Id: 3' \
    -H 'X-EpicStaff-On-Behalf-Of: 7' -H 'Cookie: sessionid=s3cret' -H 'X-API-Key: key-a' \
    -H 'X-Plugin-Network-Secret: forged' -H 'X_Plugin_Network_Secret: forged' -H 'X-Plugin_Network-Secret: forged' \
    -H 'X-Plugin-Development-Listener: 0' -H 'X_Plugin_Development_Listener: 0' \
    -H 'X-Plugin_Development-Listener: forged'
  secret_values=$(echoed_values x-plugin-network-secret)
  if [ "$status" = 200 ] && [ "$(jq -r .django "$work/body" 2> /dev/null)" = true ] \
    && [ "$secret_values" = "$PLUGINS_GATEWAY_SECRET" ] \
    && [ "$(echoed_values x-plugin-development-listener)" = 1 ] \
    && [ "$(echoed_values authorization)" = "PluginKey esp-lab" ] \
    && [ "$(echoed_values x-organization-id)" = 3 ] && [ "$(echoed_values x-epicstaff-on-behalf-of)" = 7 ] \
    && [ -z "$(echoed_names | grep -xE 'cookie|x-api-key')" ]; then
    pass "the development listener sends Django the environment's network secret and X-Plugin-Development-Listener: 1, never the caller's copies, and no cookie or API key"
  else
    # Never print the secret values: on a failure they may hold it.
    fail "the development listener: status $status, development header [$(echoed_values x-plugin-development-listener)], secret $([ "$secret_values" = "$PLUGINS_GATEWAY_SECRET" ] && echo right || echo wrong)"
  fi
  wrong=""
  for path in /api/auth/token/ /api/admin/plugins/ /api/plugin-gateway/check/ /api/plugin-gateway/development-spa/ /; do
    request "$listener$path" -H 'Authorization: PluginKey esp-lab'
    if [ "$status" != 404 ] || [ "$(jq -r .code "$work/body" 2> /dev/null)" != not_found ]; then
      wrong="$wrong [$path: $status]"
    fi
  done
  if [ -z "$wrong" ]; then
    pass "the development listener answers 404 itself for /api/auth/, /api/admin/, /api/plugin-gateway/ and anything outside /api/"
  else
    fail "the development listener's refused paths:$wrong"
  fi
  request http://nginx:8081/api/plugin-runtime/me/
  if [ "$status" = 403 ]; then
    pass "the internal API listener still refuses a caller outside the plugins network"
  else
    fail "the internal API listener from outside the plugins network: $status"
  fi
  ;;

inside)
  wrong=""
  for path in /api/plugin-runtime/me/ /api/auth/token/ /; do
    request "http://epicstaff-api:8082$path" -H 'Authorization: PluginKey esp-lab'
    [ "$status" = 403 ] || wrong="$wrong [$path: $status]"
  done
  if [ -z "$wrong" ]; then
    pass "a caller on the plugins network gets 403 from the development listener"
  else
    fail "the development listener from the plugins network:$wrong"
  fi
  request http://epicstaff-api:8081/api/plugin-runtime/me/ -H 'Authorization: PluginKey esp-lab' \
    -H 'X-Plugin-Development-Listener: 1' -H 'X_Plugin_Development_Listener: 1' -H 'X-Plugin_Development-Listener: 1'
  if [ "$status" = 200 ] && [ -n "$(echoed_values x-plugin-network-secret)" ] \
    && [ -z "$(echoed_names | grep -x x-plugin-development-listener)" ]; then
    pass "the internal listener sends Django its network secret and no X-Plugin-Development-Listener, whatever the caller sends"
  else
    fail "the internal listener with a forged development header: status $status, development header [$(echoed_values x-plugin-development-listener)]"
  fi
  ;;

off)
  gateway=http://nginx-off
  set_decision '{"answer": "development", "port": 5173}'
  before=$(decisions)
  wrong=""
  for path in / /index.html /places/lisbon; do
    request "$gateway$path" -H "Host: $plugin_host"
    if [ "$status" != 200 ] || ! cmp -s "$work/body" "$spa/index.html"; then
      wrong="$wrong [$path: $status]"
    fi
  done
  if [ -z "$wrong" ] && [ "$(decisions)" = "$before" ]; then
    pass "with development mode off, page requests get the published files and the page decision counter stays at $before"
  else
    fail "with development mode off:$wrong, decisions $before then $(decisions)"
  fi
  if curl -s -o /dev/null --max-time 5 http://nginx-off:8082/; then
    fail "with development mode off, something listens on 8082"
  else
    # 7: the connection was refused.
    code=$?
    if [ "$code" = 7 ]; then
      pass "with development mode off, nothing listens on 8082 (connection refused)"
    else
      fail "with development mode off, 8082 did not refuse the connection (curl exit $code)"
    fi
  fi
  ;;

*)
  echo "usage: checks.sh outside|inside|off" >&2
  exit 2
  ;;
esac

rm -rf "$work"
if [ "$failures" -ne 0 ]; then
  exit 1
fi
