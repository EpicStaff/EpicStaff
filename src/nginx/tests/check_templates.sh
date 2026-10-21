#!/usr/bin/env bash
# Renders src/nginx/templates the way the epicstaff-nginx container does at start-up (its
# docker-entrypoint.d scripts, then envsubst), with the nginx image pinned in
# src/docker-compose.yaml, and runs `nginx -T` (test the configuration and print it) on the result:
#
#   - every combination of CHAT_ENABLED, PLUGINS_ENABLED and NGINX_SSL_MODE, with throwaway
#     self-signed certificates; with the plugins flag off nothing plugin-related may be rendered;
#   - in each, that every location of EpicStaff's own server that proxies anywhere but Django
#     drops the Cookie header and the upstream's Set-Cookie and Clear-Site-Data, and that nginx's
#     X-Frame-Options is the only one (read from the rendered configuration, includes expanded);
#   - the values 16-normalize-plugins-enabled.envsh derives, and the ones it must refuse;
#   - live, inside the container: which upstreams receive the browser's cookies and may set
#     one, the package upload route, the login callback pages a plugin host serves from src/nginx/plugin-platform,
#     and which listener answers a caller on the plugins subnet (127.0.0.0/8 stands in for it)
#     and which refuses it.
#
# Needs Docker and openssl. The containers have no network and publish no ports; nothing is left
# behind. Usage, from anywhere: bash src/nginx/tests/check_templates.sh
set -euo pipefail

nginx_dir=$(cd "$(dirname "$0")/.." && pwd)
compose_file="$nginx_dir/../docker-compose.yaml"
plugins_envsh="$nginx_dir/docker-entrypoint.d/16-normalize-plugins-enabled.envsh"
chat_envsh="$nginx_dir/docker-entrypoint.d/15-normalize-chat-enabled.envsh"
platform_dir="$nginx_dir/plugin-platform"

image=$(awk '/^  epicstaff-nginx:$/ { in_service = 1; next }
             in_service && /^    image:/ { print $2; exit }' "$compose_file")
if [ -z "$image" ]; then
  echo "ERROR: no image found for the epicstaff-nginx service in $compose_file" >&2
  exit 2
fi

work_dir=$(mktemp -d)
live_container=""
cleanup() {
  if [ -n "$live_container" ]; then
    docker rm -f "$live_container" > /dev/null 2>&1 || true
  fi
  rm -rf "$work_dir"
}
trap cleanup EXIT
mkdir "$work_dir/certs"

make_certificate() { # $1 = file name prefix, $2 = common name
  openssl req -x509 -nodes -newkey rsa:2048 -days 1 -subj "/CN=$2" \
    -keyout "$work_dir/certs/${1}privkey.pem" -out "$work_dir/certs/${1}fullchain.pem" \
    > /dev/null 2>&1
}
make_certificate "" epicstaff.test
make_certificate plugins- "*.plugins.epicstaff.test"

# A value of the shape `openssl rand -hex 32` gives; the rendered check location must carry it.
gateway_secret=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef

# The policy of the two login callback pages, next to the plugin hosts' frame-ancestors.
platform_page_policy="default-src 'none'; script-src 'self'; base-uri 'none'; form-action 'none'"

failures=0
pass() { echo "ok - $1"; }
fail() {
  echo "not ok - $1"
  failures=$((failures + 1))
}

# Fills docker_arguments with the stack's nginx environment (the variables
# src/docker-compose.yaml passes to epicstaff-nginx), overridden by the NAME=value arguments, and
# the mounts the image's entrypoint needs.
docker_arguments=()
set_docker_arguments() {
  local assignment
  docker_arguments=(--network none)
  for assignment in \
    NGINX_ENTRYPOINT_QUIET_LOGS=1 \
    NGINX_SERVER_NAME=epicstaff.test NGINX_SSL_MODE=off \
    DJANGO_HOST=django DJANGO_PORT=8000 FRONTEND_HOST=frontend FRONTEND_PORT=80 \
    REALTIME_HOST=realtime REALTIME_PORT=8050 WEBHOOK_HOST=webhook WEBHOOK_PORT=8009 \
    AUDITOR_HOST=auditor AUDITOR_PORT=8010 CHAT_ENABLED=false CHAT_UPSTREAM_URL=http://chat:8200 \
    PLUGINS_ENABLED=false PLUGINS_BASE_DOMAIN=plugins.epicstaff.test PLUGINS_MAX_PACKAGE_MB=300 \
    PLUGINS_MAX_REQUEST_BODY_MB=20 PLUGINS_GATEWAY_SECRET="$gateway_secret" \
    DJANGO_FRONTEND_BASE_URL=https://epicstaff.test PLUGINS_NETWORK_SUBNET=10.235.0.0/24 \
    "$@"; do
    docker_arguments+=(-e "$assignment")
  done
  docker_arguments+=(
    -v "$nginx_dir/templates:/etc/nginx/templates:ro"
    -v "$chat_envsh:/docker-entrypoint.d/15-normalize-chat-enabled.envsh:ro"
    -v "$plugins_envsh:/docker-entrypoint.d/16-normalize-plugins-enabled.envsh:ro"
    -v "$work_dir/certs:/etc/nginx/certs:ro"
  )
  # As the stack mounts it. Only when present: Docker would create a missing one on the host.
  if [ -d "$platform_dir" ]; then
    docker_arguments+=(-v "$platform_dir:/usr/share/nginx/plugin-platform:ro")
  fi
}

# Starts the image's entrypoint with `nginx -T` and the environment of set_docker_arguments.
# The rendered configuration goes to $work_dir/out, messages to $work_dir/err; returns the
# container's exit status.
render() {
  set_docker_arguments "$@"
  docker run --rm "${docker_arguments[@]}" "$image" nginx -T > "$work_dir/out" 2> "$work_dir/err"
}

# The rendered configuration without comment lines, so a comment never satisfies a check.
directives() { grep -v '^[[:space:]]*#' "$work_dir/out" || true; }
has_directive() { directives | grep -qF -- "$1"; }

# $1 = description; the rest = overrides. Passes when nginx accepts the configuration; returns
# non-zero otherwise, so a caller can skip the checks on its output.
expect_valid() {
  local description=$1 status=0
  shift
  render "$@" || status=$?
  if [ "$status" -eq 0 ]; then
    pass "$description"
  else
    fail "$description (exit $status): $(tail -n 3 "$work_dir/err" | tr '\n' ' ')"
  fi
  return "$status"
}

# $1 = description, $2 = text the error must contain; the rest = overrides. Passes when the
# container stops with exit status 64 and that error, as the envsh does for a value it refuses.
expect_refused() {
  local description=$1 message=$2 status=0
  shift 2
  render "$@" || status=$?
  if [ "$status" -eq 64 ] && grep -qF -- "$message" "$work_dir/err"; then
    pass "$description"
  else
    fail "$description (exit $status): $(tail -n 3 "$work_dir/err" | tr '\n' ' ')"
  fi
}

# $1 = description; the rest = directive texts that must all be in the last rendered configuration.
expect_directives() {
  local description=$1 text
  shift
  for text in "$@"; do
    if ! has_directive "$text"; then
      fail "$description: missing [$text]"
      return
    fi
  done
  pass "$description"
}

# Reads `nginx -T` output and prints every directive of the configuration nginx loads from
# default.conf, includes expanded, one per line: "<server>\t<location>\t<directive>". <server> is
# the server block's ordinal (1 is EpicStaff's own; 0 outside any server), <location> the
# enclosing location ("" at server level; a directive in an `if` or `limit_except` block counts
# for its location). Block openings are not printed. Quotes and comments are honoured, so a `;`
# or a brace inside a header value or a JSON body is no edge.
read -r -d '' flatten_program << 'AWK' || :
/^# configuration file .*:$/ {
  file = substr($0, 22, length($0) - 22)
  line_count[file] = 0
  next
}
file != "" { line_count[file]++; lines[file, line_count[file]] = $0 }
END { scan("/etc/nginx/conf.d/default.conf") }

function scan(name,    i, k, line, c, quote, word) {
  for (i = 1; i <= line_count[name]; i++) {
    line = lines[name, i]
    for (k = 1; k <= length(line); k++) {
      c = substr(line, k, 1)
      if (quote != "") {
        word = word c
        if (c == "\\") { k++; word = word substr(line, k, 1) }
        else if (c == quote) quote = ""
        continue
      }
      if (c == "#") break
      if (c == " " || c == "\t" || c == ";" || c == "{" || c == "}") {
        if (word != "") { words[++word_count] = word; word = "" }
        if (c == ";" || c == "{" || c == "}") statement(c)
        continue
      }
      if (word == "" && (c == "\"" || c == "'")) quote = c
      word = word c
    }
    if (quote != "") word = word "\n"
    else if (word != "") { words[++word_count] = word; word = "" }
  }
}

function statement(terminator,    d, text, target) {
  if (terminator == "}") {
    depth--
  } else if (word_count == 0) {
    return
  } else if (terminator == "{") {
    depth++
    kind[depth] = words[1]
    if (depth == 1 && words[1] == "server") server_count++
    location_name[depth] = ""
    if (words[1] == "location") {
      location_name[depth] = words[2]
      for (d = 3; d <= word_count; d++) location_name[depth] = location_name[depth] " " words[d]
    }
  } else if (words[1] == "include" && (words[2] in line_count)) {
    target = words[2]
    word_count = 0
    scan(target)
  } else {
    text = words[1]
    for (d = 2; d <= word_count; d++) text = text " " words[d]
    print (depth >= 1 && kind[1] == "server" ? server_count : 0) "\t" enclosing_location() "\t" text
  }
  word_count = 0
}

function enclosing_location(    d) {
  for (d = depth; d >= 2; d--) if (kind[d] == "location") return location_name[d]
  return ""
}
AWK

# Reads the flattened configuration and checks every location of EpicStaff's own server (server 1)
# that proxies: one line "<location> -> <proxy_pass target>: <problem>" per broken rule, then
# "checked <n> <m>" (how many proxy anywhere but Django, how many to Django). The rules:
#   - only Django gets the browser's cookies and may set or clear one: elsewhere Cookie is cleared
#     and Set-Cookie and Clear-Site-Data hidden;
#   - nginx's own X-Frame-Options is the only one: every proxying location hides the upstream's.
# A location's proxy_set_header and proxy_hide_header lines replace the server's when it has any,
# and only then; the check applies nginx's inheritance the same way.
read -r -d '' main_server_check_program << 'AWK' || :
BEGIN { FS = "\t" }
$1 != 1 { next }
{
  location = $2
  split($3, word, " ")
  if (!(location in seen)) { seen[location] = 1; order[++count] = location }
  if (word[1] == "proxy_pass") target[location] = word[2]
  if (word[1] == "proxy_set_header") {
    sets_headers[location] = 1
    if (tolower(word[2]) == "cookie" && (word[3] == "\"\"" || word[3] == "''")) clears[location] = 1
  }
  if (word[1] == "proxy_hide_header") {
    hides_headers[location] = 1
    hidden[location, tolower(word[2])] = 1
  }
}

function hides(location, name) {
  if (!(location in hides_headers)) location = ""
  return ((location, name) in hidden)
}

function clears_cookie(location) {
  if (!(location in sets_headers)) location = ""
  return (location in clears)
}

END {
  for (i = 1; i <= count; i++) {
    location = order[i]
    if (location == "" || !(location in target)) continue
    label = location " -> " target[location]
    if (!hides(location, "x-frame-options")) print label ": passes X-Frame-Options through"
    if (target[location] ~ /^http:\/\/backend_server(\/|$)/) { django++; continue }
    elsewhere++
    if (!clears_cookie(location)) print label ": passes the browser's Cookie on"
    if (!hides(location, "set-cookie")) print label ": passes Set-Cookie through"
    if (!hides(location, "clear-site-data")) print label ": passes Clear-Site-Data through"
  }
  print "checked " elsewhere + 0 " " django + 0
}
AWK

flatten_configuration() { # $1 = a file of `nginx -T` output
  awk "$flatten_program" "$1"
}

main_server_violations() { # $1 = a file of `nginx -T` output
  flatten_configuration "$1" | awk "$main_server_check_program"
}

# $1 = description. Checks the last rendered configuration: the refresh cookie (Path=/ on HTTPS)
# reaches Django only, never the frontend, realtime, webhooks, the auditor or a chat service that
# may run outside the stack; none of them can set a cookie on EpicStaff's host; and nginx's
# X-Frame-Options is the only one.
expect_only_django_cookies() {
  local result violations counts elsewhere django
  result=$(main_server_violations "$work_dir/out")
  violations=$(printf '%s\n' "$result" | grep -v '^checked ' || true)
  counts=$(printf '%s\n' "$result" | sed -n 's/^checked //p')
  elsewhere=${counts% *}
  django=${counts#* }
  if [ -n "$violations" ]; then
    fail "$1: $(printf '%s\n' "$violations" | paste -sd ';' -)"
  elif [ "$elsewhere" -eq 0 ] || [ "$django" -eq 0 ]; then
    fail "$1: found no proxied location in EpicStaff's server ($elsewhere elsewhere, $django to Django)"
  else
    pass "$1 ($elsewhere locations proxy elsewhere without cookies either way, $django proxy to Django)"
  fi
}

# Reads the flattened configuration twice (the file name, twice) and checks the plugin hosts'
# server (the one whose server_name captures plugin_identifier): every answer the gateway gives
# itself instead of the plugin's carries X-EpicStaff-Gateway-Deny, set with `always` (each error
# page of /api/, and each named location that returns 4xx or 5xx), and /api/ hides the header
# from the plugin's own answers. Prints one line per problem, then "checked <n>": the answering
# locations it found.
read -r -d '' gateway_deny_check_program << 'AWK' || :
BEGIN { FS = "\t" }
NR == FNR {
  if ($3 ~ /^server_name "~\^\(\?<plugin_identifier>/) plugin_server = $1
  next
}
$1 != plugin_server { next }
{
  last = split($3, word, " ")
  if ($2 == "^~ /api/" && word[1] == "error_page") answering[word[last]] = 1
  if (substr($2, 1, 1) == "@" && word[1] == "return" && word[2] ~ /^[45][0-9][0-9]$/) answering[$2] = 1
  if (word[1] == "add_header" && tolower(word[2]) == "x-epicstaff-gateway-deny" && word[last] == "always") marked[$2] = 1
  if ($2 == "^~ /api/" && word[1] == "proxy_hide_header" && tolower(word[2]) == "x-epicstaff-gateway-deny") hidden = 1
}
END {
  for (location in answering) {
    count++
    if (!(location in marked)) print location ": answers without X-EpicStaff-Gateway-Deny"
  }
  if (!hidden) print "^~ /api/: passes a plugin's X-EpicStaff-Gateway-Deny on"
  print "checked " count + 0
}
AWK

# $1 = a file of `nginx -T` output; prints the gateway deny check's problems, sorted.
gateway_deny_problems() {
  flatten_configuration "$1" > "$work_dir/flat"
  awk "$gateway_deny_check_program" "$work_dir/flat" "$work_dir/flat" | { grep -v '^checked ' || true; } \
    | LC_ALL=C sort
}

# $1 = description. Checks the last rendered configuration (plugins on).
expect_gateway_denies_marked() {
  local problems answering
  problems=$(gateway_deny_problems "$work_dir/out")
  answering=$(awk "$gateway_deny_check_program" "$work_dir/flat" "$work_dir/flat" | sed -n 's/^checked //p')
  if [ -n "$problems" ]; then
    fail "$1: $(printf '%s\n' "$problems" | paste -sd ';' -)"
  elif [ "$answering" -lt 3 ]; then
    fail "$1: found only $answering locations that answer for the gateway"
  else
    pass "$1 ($answering locations answer for the gateway, all marked; hidden from the plugin)"
  fi
}

if [ -x "$plugins_envsh" ]; then
  pass "16-normalize-plugins-enabled.envsh is executable (the image ignores it otherwise)"
else
  fail "16-normalize-plugins-enabled.envsh is not executable: the image's entrypoint skips it"
fi

for chat_enabled in false true; do for ssl_mode in off on; do
  flags="CHAT_ENABLED=$chat_enabled NGINX_SSL_MODE=$ssl_mode"
  if expect_valid "nginx -t: PLUGINS_ENABLED=false $flags" \
    PLUGINS_ENABLED=false NGINX_SSL_MODE=$ssl_mode CHAT_ENABLED=$chat_enabled; then
    expect_only_django_cookies "PLUGINS_ENABLED=false $flags: only Django gets and sets cookies"
    leaked=""
    for text in plugin_identifier /srv/plugin-spa /api/admin/plugins/packages/ \
      /_epicstaff/plugin-upload-permission auth_request \
      /api/plugin-gateway/ /api/plugin-nodes/ plugins-fullchain.pem frame-ancestors\ \'self\'\ http \
      /_plugin_gateway_check X-Plugin-Gateway-Secret "listen 8081" "$gateway_secret" \
      plugin_network_caller 10.235.0.0/24 /.well-known/epicstaff/callback \
      /usr/share/nginx/plugin-platform X-EpicStaff-Gateway-Deny; do
      if has_directive "$text"; then
        leaked="$leaked [$text]"
      fi
    done
    if [ -z "$leaked" ] && directives | grep -qE "frame-src 'self' *;"; then
      pass "PLUGINS_ENABLED=false $flags renders nothing plugin-related"
    else
      fail "PLUGINS_ENABLED=false $flags renders plugin directives:$leaked"
    fi
  fi

  if expect_valid "nginx -t: PLUGINS_ENABLED=true $flags" \
    PLUGINS_ENABLED=true NGINX_SSL_MODE=$ssl_mode CHAT_ENABLED=$chat_enabled; then
    expect_only_django_cookies "PLUGINS_ENABLED=true $flags: only Django gets and sets cookies"
    expect_gateway_denies_marked "PLUGINS_ENABLED=true $flags: the gateway marks its own refusals"
    expected_tls="include /etc/nginx/conf.d/plugins-ssl-off.snippet;"
    if [ "$ssl_mode" = on ]; then
      expected_tls="ssl_certificate /etc/nginx/certs/plugins-fullchain.pem;"
    fi
    expect_directives "PLUGINS_ENABLED=true $flags renders the plugin routes" \
      'server_name "~^(?<plugin_identifier>[a-z][a-z0-9-]{0,30}[a-z0-9])\.plugins\.epicstaff\.test$";' \
      "frame-src 'self' https://*.plugins.epicstaff.test;" \
      "add_header Content-Security-Policy \"frame-ancestors 'self' https://epicstaff.test\" always;" \
      "location = /api/admin/plugins/packages/ {" \
      "auth_request /_epicstaff/plugin-upload-permission;" \
      "location = /_epicstaff/plugin-upload-permission {" \
      "proxy_pass_request_body off;" \
      "location = /api/admin/plugins/packages/upload-permission/ {" \
      "client_max_body_size 301m;" \
      "location ^~ /api/plugin-gateway/ {" \
      "location ^~ /api/plugin-nodes/ {" \
      "$expected_tls"
    expect_directives "PLUGINS_ENABLED=true $flags serves the login callback pages" \
      'location = /.well-known/epicstaff/callback.html {' \
      'alias /usr/share/nginx/plugin-platform/callback.html;' \
      'location = /.well-known/epicstaff/silent-callback.html {' \
      'alias /usr/share/nginx/plugin-platform/silent-callback.html;' \
      'location = /.well-known/epicstaff/callback.js {' \
      'alias /usr/share/nginx/plugin-platform/callback.js;' \
      'default_type application/javascript;' \
      "add_header Content-Security-Policy \"$platform_page_policy\" always;" \
      'limit_except GET HEAD {'
    expect_directives "PLUGINS_ENABLED=true $flags refuses the plugins subnet on 80/443" \
      'geo $plugin_network_caller {' \
      '10.235.0.0/24  1;' \
      'if ($plugin_network_caller) {'
    if [ "$(directives | grep -cF 'if ($plugin_network_caller) {')" = 2 ]; then
      pass "both EpicStaff's server and the plugin hosts' server refuse the plugins subnet"
    else
      fail "the plugins subnet is refused by $(directives | grep -cF 'if ($plugin_network_caller) {') server(s), not 2"
    fi
    expect_directives "PLUGINS_ENABLED=true $flags renders the plugin gateway" \
      'client_max_body_size 20m;' \
      'set $plugin_normalized_path $uri;' \
      'auth_request /_plugin_gateway_check;' \
      'auth_request_set $plugin_upstream $upstream_http_x_plugin_upstream;' \
      'auth_request_set $plugin_deny $upstream_http_x_plugin_deny;' \
      'error_page 401 403 = @plugin_denied;' \
      'recursive_error_pages on;' \
      'proxy_pass http://$plugin_upstream;' \
      'proxy_set_header Connection $connection_upgrade;' \
      'proxy_set_header Cookie "";' \
      'proxy_set_header X-API-Key "";' \
      'proxy_set_header X_API_Key "";' \
      'error_page 500 = @plugin_unavailable;' \
      'proxy_set_header Authorization $plugin_authorization;' \
      'proxy_set_header X-EpicStaff-Plugin-Context $plugin_context;' \
      'proxy_set_header X_EpicStaff_Plugin_Context "";' \
      'proxy_set_header X-EpicStaff-Plugin_Context "";' \
      'proxy_ignore_headers X-Accel-Redirect;' \
      'proxy_hide_header Set-Cookie;' \
      'proxy_buffering off;' \
      'location = /_plugin_gateway_check {' \
      'proxy_pass_request_headers off;' \
      'proxy_set_header Host localhost;' \
      "proxy_set_header X-Plugin-Gateway-Secret \"$gateway_secret\";" \
      'proxy_set_header X-Original-Normalized-Path $plugin_normalized_path;' \
      'proxy_set_header X-Original-Transfer-Encoding $http_transfer_encoding;' \
      'location @plugin_denied {' \
      "return 401 '{\"status_code\":401,\"code\":\"login_required\""
    expect_directives "PLUGINS_ENABLED=true $flags renders the internal API listener" \
      'listen 8081;' \
      'location ^~ /api/auth/ {' \
      'location ^~ /api/admin/ {' \
      'proxy_set_header X-Organization-Id $http_x_organization_id;' \
      'if ($plugin_network_caller = 0) {'
  fi
done; done

# The check itself, on a configuration with chat and plugins on, from which rules are deleted:
#   - every Cookie, Set-Cookie and Clear-Site-Data rule: it must name exactly EpicStaff's own
#     non-Django locations, the chat snippet's included, and not the plugin host's /api/
#     (another server, which hides Set-Cookie and clears Cookie too);
#   - only the X-Frame-Options line of cookie-free-upstream.snippet: exactly the same locations
#     lose it, and Django's still inherit the server's (nginx's inheritance, modelled right).
# Update the list when a location that proxies anywhere but Django is added or removed.
non_django_locations=$(LC_ALL=C sort << 'LOCATIONS'
/ -> http://frontend_server
= /chat -> http://frontend_server
^~ /webhooks/ -> http://webhook_server
^~ /voice/ -> http://realtime_server
/voice/stream -> http://realtime_server
/realtime/ -> http://realtime_server
/chat/ -> $chat_upstream
/auditor/ -> $auditor_upstream
LOCATIONS
)
# $1 = a file of `nginx -T` output; prints the main server's violations, sorted.
sorted_violations() { main_server_violations "$1" | { grep -v '^checked ' || true; } | LC_ALL=C sort; }
# $@ = problems; prints them for every non-Django location, sorted like sorted_violations.
expected_violations() {
  local problem
  for problem in "$@"; do
    printf '%s\n' "$non_django_locations" | sed "s/\$/: $problem/"
  done | LC_ALL=C sort
}
if expect_valid "nginx -t: CHAT_ENABLED=true PLUGINS_ENABLED=true, for the cookie check's self-test" \
  CHAT_ENABLED=true PLUGINS_ENABLED=true; then
  grep -vF -e 'proxy_set_header Cookie "";' -e 'proxy_hide_header Set-Cookie;' \
    -e 'proxy_hide_header Clear-Site-Data;' "$work_dir/out" > "$work_dir/out-without-cookie-rules"
  found=$(sorted_violations "$work_dir/out-without-cookie-rules")
  if [ "$found" = "$(expected_violations "passes Set-Cookie through" "passes the browser's Cookie on" \
    "passes Clear-Site-Data through")" ]; then
    pass "the cookie check finds every location of EpicStaff's server that proxies elsewhere"
  else
    fail "the cookie check, with every cookie rule deleted, found [$(printf '%s\n' "$found" | paste -sd ';' -)]"
  fi
  awk '/^# configuration file / { in_snippet = ($0 ~ /cookie-free-upstream\.snippet:$/) }
       !(in_snippet && /proxy_hide_header X-Frame-Options;/)' "$work_dir/out" \
    > "$work_dir/out-without-snippet-frame-rule"
  found=$(sorted_violations "$work_dir/out-without-snippet-frame-rule")
  if [ "$found" = "$(expected_violations "passes X-Frame-Options through")" ]; then
    pass "the cookie check applies nginx's proxy_hide_header inheritance"
  else
    fail "the cookie check, without the snippet's X-Frame-Options rule, found [$(printf '%s\n' "$found" | paste -sd ';' -)]"
  fi
fi

# The gateway deny check itself: with every X-EpicStaff-Gateway-Deny line deleted it must name
# exactly the three locations that answer for the gateway, and /api/.
if expect_valid "nginx -t: PLUGINS_ENABLED=true, for the gateway deny check's self-test" \
  PLUGINS_ENABLED=true; then
  grep -vF 'X-EpicStaff-Gateway-Deny' "$work_dir/out" > "$work_dir/out-without-deny-header"
  found=$(gateway_deny_problems "$work_dir/out-without-deny-header")
  expected=$(printf '%s\n' "@plugin_denied: answers without X-EpicStaff-Gateway-Deny" \
    "@plugin_request_too_large: answers without X-EpicStaff-Gateway-Deny" \
    "@plugin_unavailable: answers without X-EpicStaff-Gateway-Deny" \
    "^~ /api/: passes a plugin's X-EpicStaff-Gateway-Deny on" | LC_ALL=C sort)
  if [ "$found" = "$expected" ]; then
    pass "the gateway deny check finds every location that answers for the gateway"
  else
    fail "the gateway deny check, with the header deleted, found [$(printf '%s\n' "$found" | paste -sd ';' -)]"
  fi
fi

# The flag is read like every other boolean in the stack (env_bool).
if expect_valid "PLUGINS_ENABLED=Yes is accepted" PLUGINS_ENABLED=Yes; then
  expect_directives "PLUGINS_ENABLED=Yes is read as true" "root /srv/plugin-spa/\$plugin_identifier/current;"
fi
expect_refused "PLUGINS_ENABLED=maybe is refused" "PLUGINS_ENABLED='maybe' is not a boolean" \
  PLUGINS_ENABLED=maybe

# With the flag off the plugin values are never read, so they cannot stop nginx.
expect_valid "PLUGINS_ENABLED=false ignores malformed plugin values" PLUGINS_ENABLED=false \
  "PLUGINS_BASE_DOMAIN=bad;value" DJANGO_FRONTEND_BASE_URL=none PLUGINS_MAX_PACKAGE_MB=many \
  PLUGINS_MAX_REQUEST_BODY_MB=lots PLUGINS_GATEWAY_SECRET=none "PLUGINS_NETWORK_SUBNET=any; allow all" || :

# Values that would break or inject into the rendered configuration.
for base_domain in "plugins.epicstaff.test;" "plugins.epicstaff.test\"" "Plugins.Epicstaff.test" \
  localhost ".plugins.epicstaff.test" "plugins..epicstaff.test" "plugins.epicstaff.test-" \
  "plugins.epicstaff.test"$'\n'"x.y" ""; do
  expect_refused "PLUGINS_BASE_DOMAIN=$(printf '%q' "$base_domain") is refused" "ERROR: PLUGINS_BASE_DOMAIN=" \
    PLUGINS_ENABLED=true "PLUGINS_BASE_DOMAIN=$base_domain"
done
for frontend_url in "https://epicstaff.test\" always; add_header X-Injected 1; #" \
  epicstaff.test "ftp://epicstaff.test" "https://user@epicstaff.test" "https://" \
  "https://[::1]" "https://epicstaff.test:8443:1"; do
  expect_refused "DJANGO_FRONTEND_BASE_URL=$(printf '%q' "$frontend_url") is refused" \
    "ERROR: DJANGO_FRONTEND_BASE_URL=" PLUGINS_ENABLED=true "DJANGO_FRONTEND_BASE_URL=$frontend_url"
done
# Django's start-up check refuses anything after the origin but a trailing "/"; so does nginx.
for frontend_url in "https://epicstaff.test/app" "https://epicstaff.test/app/" \
  "https://epicstaff.test//" "https://epicstaff.test/?next=/x" "https://epicstaff.test?next=/x" \
  "https://epicstaff.test#top" "http://epicstaff.localhost:8080/epicstaff/"; do
  expect_refused "DJANGO_FRONTEND_BASE_URL=$(printf '%q' "$frontend_url") is refused for its path" \
    "has a path, query or fragment" PLUGINS_ENABLED=true "DJANGO_FRONTEND_BASE_URL=$frontend_url"
done
expect_valid "PLUGINS_ENABLED=false ignores a path in DJANGO_FRONTEND_BASE_URL" PLUGINS_ENABLED=false \
  "DJANGO_FRONTEND_BASE_URL=http://localhost:4200/app/" || :
for body_megabytes in 0 20MB "" 020 -1; do
  expect_refused "PLUGINS_MAX_REQUEST_BODY_MB=$(printf '%q' "$body_megabytes") is refused" \
    "ERROR: PLUGINS_MAX_REQUEST_BODY_MB=" PLUGINS_ENABLED=true "PLUGINS_MAX_REQUEST_BODY_MB=$body_megabytes"
done
for secret in none None "" "short-secret" "${gateway_secret}\"; add_header X 1; #" \
  "${gateway_secret}\$host" "${gateway_secret} space" "${gateway_secret}"$'\n'"x"; do
  expect_refused "PLUGINS_GATEWAY_SECRET of the shape $(printf '%q' "${secret//[0-9a-f]/h}") is refused" \
    "ERROR: PLUGINS_GATEWAY_SECRET" PLUGINS_ENABLED=true "PLUGINS_GATEWAY_SECRET=$secret"
  # Its first 12 characters are enough to show it, and cannot hold a newline here.
  if [ "${#secret}" -ge 12 ] && grep -qF -- "${secret:0:12}" "$work_dir/err"; then
    fail "the refused PLUGINS_GATEWAY_SECRET $(printf '%q' "${secret//[0-9a-f]/h}") is echoed"
  fi
done
# Rendered into allow, deny and geo: anything but a plain IPv4 CIDR could add a directive or
# widen the rule.
for subnet in "" none 10.235.0.0 "10.235.0.0/24; allow all" "10.235.0.0/24 10.0.0.0/8" \
  "fd00:235::/64" "all" "10.235.0.0/24"$'\n'"allow all;" "10.235.0.0/24;"; do
  expect_refused "PLUGINS_NETWORK_SUBNET=$(printf '%q' "$subnet") is refused" \
    "ERROR: PLUGINS_NETWORK_SUBNET=" PLUGINS_ENABLED=true "PLUGINS_NETWORK_SUBNET=$subnet"
done
for package_megabytes in 0 300MB "" 030 -1; do
  expect_refused "PLUGINS_MAX_PACKAGE_MB=$(printf '%q' "$package_megabytes") is refused" \
    "ERROR: PLUGINS_MAX_PACKAGE_MB=" PLUGINS_ENABLED=true "PLUGINS_MAX_PACKAGE_MB=$package_megabytes"
done

# EpicStaff's origin: the scheme is accepted in any case and written in lower case, an explicit
# port is kept and a default one is not, a trailing "/" is dropped, and the plugin hosts'
# frame-src takes the same scheme and port.
if expect_valid "a base URL with an explicit port is accepted" PLUGINS_ENABLED=true \
  "DJANGO_FRONTEND_BASE_URL=HTTPS://EpicStaff.test:8443"; then
  expect_directives "EpicStaff's origin keeps an explicit port and lower-cases the scheme" \
    "frame-ancestors 'self' https://EpicStaff.test:8443\" always;" \
    "frame-src 'self' https://*.plugins.epicstaff.test:8443;"
fi
if expect_valid "a base URL with a trailing / is accepted" PLUGINS_ENABLED=true \
  "DJANGO_FRONTEND_BASE_URL=https://epicstaff.test/"; then
  expect_directives "the trailing / is dropped" \
    "frame-ancestors 'self' https://epicstaff.test\" always;" \
    "frame-src 'self' https://*.plugins.epicstaff.test;"
fi
if expect_valid "a base URL with the default https port is accepted" PLUGINS_ENABLED=true \
  "DJANGO_FRONTEND_BASE_URL=https://epicstaff.test:443/"; then
  expect_directives "the default https port is dropped" \
    "frame-ancestors 'self' https://epicstaff.test\" always;" \
    "frame-src 'self' https://*.plugins.epicstaff.test;"
fi
if expect_valid "the local development values are accepted" PLUGINS_ENABLED=true \
  PLUGINS_BASE_DOMAIN=plugins.epicstaff.localhost "DJANGO_FRONTEND_BASE_URL=http://epicstaff.localhost:80"; then
  expect_directives "plain http keeps its scheme and drops the default port" \
    "frame-ancestors 'self' http://epicstaff.localhost\" always;" \
    "frame-src 'self' http://*.plugins.epicstaff.localhost;" \
    '\.plugins\.epicstaff\.localhost$";'
fi

# The package upload route, live: nginx running, curl inside its container, and a stub of Django
# on 127.0.0.1:8000 (one more nginx server, whose access log records every request that reaches
# "Django"). The stub's permission check answers 204 for "Bearer superadmin", 403 for
# "Bearer org-admin" or any API key, and 401 otherwise.
#   - Refused callers get a JSON 401 or 403 and their upload never reaches Django; the
#     permission check reaches it without a body. (nginx itself still reads and drops the rest
#     of a refused body in memory, as it does for every response it ends early.)
#   - A SuperAdmin's package of exactly PLUGINS_MAX_PACKAGE_MB, with its multipart framing,
#     reaches Django; a body more than one MiB above the cap gets nginx's 413.
#   - Neither the internal location nor Django's permission path answers from outside.
cat > "$work_dir/stub-django.conf" <<'STUB'
log_format stub_django '$request_method $uri $request_length';
server {
    listen 127.0.0.1:8000;
    access_log /tmp/stub-django.log stub_django;
    client_max_body_size 0;
    location = /api/admin/plugins/packages/upload-permission/ {
        if ($http_x_api_key) { return 403; }
        if ($http_authorization = "Bearer superadmin") { return 204; }
        if ($http_authorization = "Bearer org-admin") { return 403; }
        return 401;
    }
    location = /api/admin/plugins/packages/ {
        return 201 '{"stub":"the upload reached Django"}';
    }
}
STUB
set_docker_arguments PLUGINS_ENABLED=true PLUGINS_MAX_PACKAGE_MB=1 DJANGO_HOST=127.0.0.1 DJANGO_PORT=8000
live_container=$(docker run -d "${docker_arguments[@]}" \
  -v "$work_dir/stub-django.conf:/etc/nginx/conf.d/zz-stub-django.conf:ro" "$image")
live() { docker exec "$live_container" "$@"; }
# Prints the status code of an upload with the extra curl arguments.
upload() {
  live sh -c 'curl -s -o /tmp/response -w "%{http_code}" -H "Host: epicstaff.test" \
    "$@" http://127.0.0.1/api/admin/plugins/packages/' upload "$@" || true
}
reached_django() { live grep -q "^$1" /tmp/stub-django.log; }
for _ in $(seq 50); do
  if live curl -s -o /dev/null http://127.0.0.1:8000/ 2> /dev/null; then break; fi
  sleep 0.1
done
live sh -c 'head -c 1048576 /dev/urandom > /tmp/package-at-cap && head -c 2621440 /dev/urandom > /tmp/too-large'

refused_upload() { # $1 = description, $2 = expected status, $3 = expected code; the rest = curl arguments
  local description=$1 expected=$2 code=$3 status
  shift 3
  live sh -c ': > /tmp/stub-django.log'
  status=$(upload "$@" -F file=@/tmp/package-at-cap)
  if [ "$status" != "$expected" ]; then
    fail "$description: expected $expected, got $status"
  elif ! live grep -q "\"code\":\"$code\"" /tmp/response; then
    fail "$description: the answer is not the JSON envelope with code $code"
  elif reached_django "POST /api/admin/plugins/packages/ "; then
    fail "$description: the upload reached Django"
  elif ! live awk '$1 == "GET" && $2 == "/api/admin/plugins/packages/upload-permission/" && $3 < 4096 { found = 1 }
                   END { exit !found }' /tmp/stub-django.log; then
    fail "$description: Django's permission check was not asked, or was sent a body"
  else
    pass "$description"
  fi
}
refused_upload "an upload without credentials gets a JSON 401 and its body never reaches Django" 401 not_authenticated
refused_upload "an upload with a made-up bearer token gets a JSON 401 and its body never reaches Django" 401 \
  not_authenticated -H 'Authorization: Bearer x'
refused_upload "an upload by someone who is not a SuperAdmin gets a JSON 403 and its body never reaches Django" \
  403 permission_denied -H 'Authorization: Bearer org-admin'
refused_upload "an upload with an API key gets a JSON 403 and its body never reaches Django" 403 \
  permission_denied -H 'X-API-Key: some-key'

live sh -c ': > /tmp/stub-django.log'
status=$(upload -H 'Authorization: Bearer superadmin' -F file=@/tmp/package-at-cap)
if [ "$status" = 201 ] && reached_django "POST /api/admin/plugins/packages/ "; then
  pass "a SuperAdmin's package of exactly PLUGINS_MAX_PACKAGE_MB reaches Django"
else
  fail "a SuperAdmin's package of exactly the cap: expected it to reach Django (201), got $status"
fi
status=$(upload -H 'Authorization: Bearer superadmin' --data-binary @/tmp/too-large)
[ "$status" = 413 ] && pass "a body more than one MiB above the cap gets 413 from nginx" \
  || fail "a body of 2.5 MiB with a 1 MiB cap: expected 413, got $status"

# 127.0.0.1 is not in this container's PLUGINS_NETWORK_SUBNET (10.235.0.0/24): a caller off the
# plugins network.
for path in /api/plugin-nodes/self/desired-state/ /api/auth/token/ /; do
  status=$(live curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:8081$path" || true)
  [ "$status" = 403 ] && pass "the internal API listener refuses a caller outside the plugins subnet: $path" \
    || fail "the internal API listener from outside the plugins subnet: $path expected 403, got $status"
done
status=$(live curl -s -o /dev/null -w '%{http_code}' -H 'Host: epicstaff.test' http://127.0.0.1/ || true)
[ "$status" != 403 ] && pass "EpicStaff's server answers a caller outside the plugins subnet ($status)" \
  || fail "EpicStaff's server refused a caller outside the plugins subnet"

for path in /_epicstaff/plugin-upload-permission /api/admin/plugins/packages/upload-permission/; do
  live sh -c ': > /tmp/stub-django.log'
  status=$(live curl -s -o /dev/null -w '%{http_code}' -H 'Host: epicstaff.test' \
    -H 'Authorization: Bearer superadmin' "http://127.0.0.1$path" || true)
  if [ "$status" = 404 ] && ! reached_django "GET"; then
    pass "$path is not reachable from outside"
  else
    fail "$path from outside: expected nginx's 404, got $status"
  fi
done

# The login callback pages, asked of a plugin host: the committed files with their headers, only
# GET and HEAD, the platform's other names 404, and nothing of it reaches Django (the stub's log
# stays empty), whose gateway check would run first for anything proxied.
# plugin_host_request METHOD PATH: prints the status; headers and body go to $work_dir.
plugin_host_request() {
  live sh -c 'curl -s -X "$1" -D /tmp/headers -o /tmp/body -w "%{http_code}" \
    -H "Host: alpha.plugins.epicstaff.test" "http://127.0.0.1$2"' request "$1" "$2" || true
  live cat /tmp/headers | tr -d '\r' > "$work_dir/headers"
  live cat /tmp/body > "$work_dir/body"
}
header_values() { # $1 = header name, as nginx writes it; prints every value, sorted, |-joined
  sed -n "s/^$1: //p" "$work_dir/headers" | LC_ALL=C sort | paste -sd '|' -
}
frame_policy="frame-ancestors 'self' https://epicstaff.test"
page_policies=$(printf '%s\n' "$frame_policy" "$platform_page_policy" | LC_ALL=C sort | paste -sd '|' -)
if [ ! -d "$platform_dir" ]; then
  fail "$platform_dir is missing: the plugin hosts have no login callback pages to serve"
else
  for page in "callback.html text/html" "silent-callback.html text/html" \
    "callback.js application/javascript"; do
    read -r name content_type <<< "$page"
    expected_policies=$frame_policy
    if [ "$content_type" = text/html ]; then
      expected_policies=$page_policies
    fi
    live sh -c ': > /tmp/stub-django.log'
    status=$(plugin_host_request GET "/.well-known/epicstaff/$name")
    problems=""
    [ "$status" = 200 ] || problems="$problems status $status;"
    cmp -s "$work_dir/body" "$platform_dir/$name" || problems="$problems not the committed file;"
    [ "$(header_values Content-Type)" = "$content_type" ] \
      || problems="$problems Content-Type [$(header_values Content-Type)];"
    [ "$(header_values Content-Security-Policy)" = "$expected_policies" ] \
      || problems="$problems Content-Security-Policy [$(header_values Content-Security-Policy)];"
    [ "$(header_values Cache-Control)" = no-cache ] \
      || problems="$problems Cache-Control [$(header_values Cache-Control)];"
    [ "$(header_values X-Content-Type-Options)" = nosniff ] || problems="$problems no nosniff;"
    [ "$(header_values Origin-Agent-Cluster)" = '?1' ] || problems="$problems no Origin-Agent-Cluster;"
    [ -z "$(header_values X-Frame-Options)$(header_values Set-Cookie)" ] \
      || problems="$problems X-Frame-Options or Set-Cookie sent;"
    if live grep -q . /tmp/stub-django.log; then problems="$problems reached Django;"; fi
    if [ -z "$problems" ]; then
      pass "a plugin host serves /.well-known/epicstaff/$name with its headers, without Django"
    else
      fail "/.well-known/epicstaff/$name on a plugin host:$problems"
    fi
  done
  live sh -c ': > /tmp/stub-django.log'
  status=$(plugin_host_request POST /.well-known/epicstaff/callback.html)
  if [ "$status" = 403 ] && [ "$(header_values Content-Security-Policy)" = "$page_policies" ] \
    && ! live grep -q . /tmp/stub-django.log; then
    pass "a POST to a callback page is refused (403), with the page's headers"
  else
    fail "a POST to a callback page: $status, Content-Security-Policy [$(header_values Content-Security-Policy)]"
  fi
  wrong=""
  for path in /.well-known/epicstaff/other.html /.well-known/epicstaff/callback.html/x \
    /.well-known/epicstaff/Callback.html /.well-known/epicstaff/callback.json; do
    status=$(plugin_host_request GET "$path")
    [ "$status" = 404 ] || wrong="$wrong [$path: $status]"
  done
  if [ -n "$wrong" ]; then
    fail "other names under /.well-known/epicstaff/ must stay 404:$wrong"
  elif live grep -q . /tmp/stub-django.log; then
    fail "a request for a callback page reached Django: $(live head -n 3 /tmp/stub-django.log)"
  else
    pass "every other name under /.well-known/epicstaff/ stays 404, and none reached Django"
  fi
fi

docker rm -f "$live_container" > /dev/null
live_container=""

# The same, seen from the plugins network: PLUGINS_NETWORK_SUBNET=127.0.0.0/8 makes curl inside
# the container a plugin backend. The 8081 listener reaches "Django"; EpicStaff's server and a
# plugin host refuse it before any location, so even the plugin API's own error pages (which
# would answer a refusal as 503 plugin_unavailable) never run.
set_docker_arguments PLUGINS_ENABLED=true DJANGO_HOST=127.0.0.1 DJANGO_PORT=8000 \
  PLUGINS_NETWORK_SUBNET=127.0.0.0/8
live_container=$(docker run -d "${docker_arguments[@]}" \
  -v "$work_dir/stub-django.conf:/etc/nginx/conf.d/zz-stub-django.conf:ro" "$image")
for _ in $(seq 50); do
  if live curl -s -o /dev/null http://127.0.0.1:8000/ 2> /dev/null; then break; fi
  sleep 0.1
done
live sh -c ': > /tmp/stub-django.log'
status=$(live curl -s -o /dev/null -w '%{http_code}' -H 'Authorization: PluginNodeKey k' \
  http://127.0.0.1:8081/api/plugin-nodes/self/desired-state/ || true)
if reached_django "GET /api/plugin-nodes/self/desired-state/"; then
  pass "the internal API listener serves a caller on the plugins subnet ($status from the stub)"
else
  fail "the internal API listener did not pass a plugins-subnet caller on to Django ($status)"
fi
for target in "epicstaff.test /" "epicstaff.test /api/other/" "epicstaff.test /api/admin/plugins/packages/" \
  "alpha.plugins.epicstaff.test /api/ping" "alpha.plugins.epicstaff.test /"; do
  live sh -c ': > /tmp/stub-django.log'
  status=$(live curl -s -o /dev/null -w '%{http_code}' -H "Host: ${target% *}" "http://127.0.0.1${target#* }" || true)
  if [ "$status" = 403 ] && ! reached_django ""; then
    pass "a plugins-subnet caller is refused with 403 on ${target% *}${target#* }"
  else
    fail "a plugins-subnet caller on ${target% *}${target#* }: expected 403, got $status"
  fi
done

docker rm -f "$live_container" > /dev/null
live_container=""

# Cookies both ways, live, with plugins off and on: every upstream of EpicStaff's server is a stub
# on 127.0.0.1 that answers with its port and the Cookie header it received, tries to set a cookie
# and to clear every cookie, and sends X-Frame-Options: DENY (as Django does). A browser sends one Cookie header; a client may
# send several, and none may get through.
cat > "$work_dir/stub-upstreams.conf" << 'STUB'
server {
    listen 127.0.0.1:8000;
    listen 127.0.0.1:8001;
    listen 127.0.0.1:8009;
    listen 127.0.0.1:8010;
    listen 127.0.0.1:8050;
    listen 127.0.0.1:8200;
    default_type text/plain;
    add_header Set-Cookie "__Host-auth.refresh=planted-by-$server_port; Path=/; Secure; HttpOnly" always;
    add_header Clear-Site-Data '"cookies"' always;
    add_header X-Frame-Options DENY always;
    return 200 "$server_port cookie=[$http_cookie]";
}
STUB
for plugins_enabled in false true; do
  set_docker_arguments PLUGINS_ENABLED=$plugins_enabled CHAT_ENABLED=true \
    CHAT_UPSTREAM_URL=http://127.0.0.1:8200 DJANGO_HOST=127.0.0.1 DJANGO_PORT=8000 \
    FRONTEND_HOST=127.0.0.1 FRONTEND_PORT=8001 WEBHOOK_HOST=127.0.0.1 WEBHOOK_PORT=8009 \
    AUDITOR_HOST=127.0.0.1 AUDITOR_PORT=8010 REALTIME_HOST=127.0.0.1 REALTIME_PORT=8050
  live_container=$(docker run -d "${docker_arguments[@]}" \
    -v "$work_dir/stub-upstreams.conf:/etc/nginx/conf.d/zz-stub-upstreams.conf:ro" "$image")
  for _ in $(seq 50); do
    if live curl -s -o /dev/null http://127.0.0.1:8001/ 2> /dev/null; then break; fi
    sleep 0.1
  done
  wrong=""
  # "<path> <port of the upstream it must reach> <django: cookies both ways, or - for none>"
  for target in "/ 8001 -" "/plugins/weather 8001 -" "/chat 8001 -" "/chat/api/x 8200 -" \
    "/webhooks/x 8009 -" "/voice/x 8050 -" "/voice/stream 8050 -" "/realtime/x 8050 -" \
    "/auditor/api/x 8010 -" "/api/x/ 8000 django" "/admin/ 8000 django" "/ws/x 8000 django" \
    "/api/storage/upload/stream 8000 django" "/api/run-session/subscribe/1/ 8000 django" \
    "/static/x 8000 django" "/media/x 8000 django"; do
    read -r path port upstream <<< "$target"
    live sh -c 'curl -s -D /tmp/headers -o /tmp/body -H "Host: epicstaff.test" \
      -H "Cookie: __Host-auth.refresh=live-refresh" -H "Cookie: auth.refresh=live-legacy; csrftoken=x" \
      "http://127.0.0.1$1"' request "$path" || true
    answer=$(live cat /tmp/body)
    set_cookies=$(live sh -c 'grep -ci "^set-cookie:" /tmp/headers' || true)
    clear_site_data=$(live sh -c 'grep -ci "^clear-site-data:" /tmp/headers' || true)
    frame_options=$(live sh -c 'grep -i "^x-frame-options:" /tmp/headers | tr -d "\r" | paste -sd "|" -' || true)
    expected="$port cookie=[] set-cookie=0 clear-site-data=0"
    if [ "$upstream" = django ]; then
      expected="$port cookie=[__Host-auth.refresh=live-refresh; auth.refresh=live-legacy; csrftoken=x] set-cookie=1 clear-site-data=1"
    fi
    got="$answer set-cookie=$set_cookies clear-site-data=$clear_site_data"
    if [ "$got" != "$expected" ] || [ "$frame_options" != "X-Frame-Options: SAMEORIGIN" ]; then
      wrong="$wrong [$path: $got $frame_options]"
    fi
  done
  if [ -z "$wrong" ]; then
    pass "PLUGINS_ENABLED=$plugins_enabled, live: only Django's routes get cookies and may set or clear one; X-Frame-Options is nginx's alone"
  else
    fail "PLUGINS_ENABLED=$plugins_enabled, live: wrong cookies or framing rule:$wrong"
  fi
  docker rm -f "$live_container" > /dev/null
  live_container=""
done

if [ "$failures" -ne 0 ]; then
  echo "FAILED: $failures check(s)"
  exit 1
fi
echo "All template checks passed."
