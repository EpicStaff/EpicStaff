#!/usr/bin/env bash
# Renders src/nginx/templates the way the epicstaff-nginx container does at start-up (its
# docker-entrypoint.d scripts, then envsubst), with the nginx image pinned in
# src/docker-compose.yaml, and runs `nginx -T` (test the configuration and print it) on the result:
#
#   - every combination of CHAT_ENABLED, PLUGINS_ENABLED and NGINX_SSL_MODE, with throwaway
#     self-signed certificates; with the plugins flag off nothing plugin-related may be rendered;
#   - with plugins on, PLUGINS_DEV_MODE false and true: off, no page decision, no development
#     server location and nothing on 8082; on, both SPA locations ask the page decision, the
#     development server's location hides its cookies, framing rule and policy, asks for
#     localhost and the server's port, and gets no login, key or context, and the development API
#     listener refuses the plugins subnet;
#   - in each, that every location of EpicStaff's own server that proxies anywhere but Django
#     drops the Cookie header and the upstream's Set-Cookie and Clear-Site-Data, and that nginx's
#     X-Frame-Options is the only one (read from the rendered configuration, includes expanded);
#     and that every location of the plugin hosts that proxies, to Django too, does the same;
#   - the values 16-normalize-plugins-enabled.envsh derives, and the ones it must refuse;
#   - the maintenance answers: the flag test in both SPA locations and the page's named location
#     with its headers, the gateway's maintenance refusal (its map entries and JSON), no
#     open_file_cache (the flag must count from the next request on), and that the committed
#     maintenance page is static (no script, nothing loaded);
#   - that only the /api/ of the internal and development API listeners sets
#     X-Plugin-Network-Secret (from PLUGINS_GATEWAY_SECRET, never from the caller),
#     X-EpicStaff-On-Behalf-Of and X-Plugin-Development-Listener (from a value each listener sets
#     itself: none on 8081, 1 on 8082), that every other location that passes a caller's headers
#     on to Django blanks all three in every spelling, and that the internal checks nginx makes
#     before an upload, a plugin request or a plugin page apply no body limit;
#   - the development mode values the start script must refuse: a non-boolean, an unset one, a
#     base domain or EpicStaff host that is not a .localhost name, and no PLUGINS_DEV_LOOPBACK_ONLY
#     (the stack was started without src/docker-compose.plugins-dev.yaml, which alone sets it);
#   - live, inside the container: which upstreams receive the browser's cookies and may set
#     one, the package upload route (with a 1 MiB and a 300 MiB package limit), the login callback
#     pages a plugin host serves from src/nginx/plugin-platform, which listener answers a caller
#     on the plugins subnet (127.0.0.0/8 stands in for it) and which refuses it, and the headers
#     the internal API listener sends Django.
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

# What src/docker-compose.plugins-dev.yaml adds to epicstaff-nginx's environment. Development mode
# needs it: src/docker-compose.yaml never sets it, so set_docker_arguments leaves it out.
loopback_marker=PLUGINS_DEV_LOOPBACK_ONLY=true

# A value of the shape `openssl rand -hex 32` gives; the rendered check location must carry it.
gateway_secret=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef

# The policy of the two login callback pages, next to the plugin hosts' frame-ancestors.
platform_page_policy="default-src 'none'; script-src 'self'; base-uri 'none'; form-action 'none'"
# The maintenance page's: no script at all, only its own inline style.
maintenance_page_policy="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
maintenance_body='{"status_code":503,"code":"plugin_maintenance","message":"The plugin is being updated. Try again in a few minutes."}'

failures=0
pass() { echo "ok - $1"; }
fail() {
  echo "not ok - $1"
  failures=$((failures + 1))
}

# Fills docker_arguments with the stack's nginx environment (the variables
# src/docker-compose.yaml passes to epicstaff-nginx), overridden by the NAME=value arguments, and
# the mounts the image's entrypoint needs. An argument "unset:NAME" leaves NAME out entirely.
docker_arguments=()
set_docker_arguments() {
  local assignment argument unset_names=" "
  for argument in "$@"; do
    case "$argument" in unset:*) unset_names="$unset_names${argument#unset:} " ;; esac
  done
  docker_arguments=(--network none)
  for assignment in \
    NGINX_ENTRYPOINT_QUIET_LOGS=1 \
    NGINX_SERVER_NAME=epicstaff.test NGINX_SSL_MODE=off \
    DJANGO_HOST=django DJANGO_PORT=8000 FRONTEND_HOST=frontend FRONTEND_PORT=80 \
    REALTIME_HOST=realtime REALTIME_PORT=8050 WEBHOOK_HOST=webhook WEBHOOK_PORT=8009 \
    AUDITOR_HOST=auditor AUDITOR_PORT=8010 CHAT_ENABLED=false CHAT_UPSTREAM_URL=http://chat:8200 \
    PLUGINS_ENABLED=false PLUGINS_DEV_MODE=false PLUGINS_BASE_DOMAIN=plugins.epicstaff.test \
    PLUGINS_MAX_PACKAGE_MB=300 PLUGINS_MAX_REQUEST_BODY_MB=20 PLUGINS_GATEWAY_SECRET="$gateway_secret" \
    DJANGO_FRONTEND_BASE_URL=https://epicstaff.test PLUGINS_NETWORK_SUBNET=10.235.0.0/24 \
    "$@"; do
    case "$assignment" in unset:*) continue ;; esac
    case "$unset_names" in *" ${assignment%%=*} "*) continue ;; esac
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

# Reads the flattened configuration twice (the file name, twice) and checks every location of the
# plugin hosts' server (the one whose server_name captures plugin_identifier) that proxies and
# answers the browser (an `internal` one answers an auth_request subrequest only, whose headers
# never reach it): one line "<location> -> <proxy_pass target>: <problem>" per broken rule, then
# "checked <n>". On a plugin host nothing proxied may get the browser's cookies, or set or clear
# one, Django included: Clear-Site-Data from a plugin host clears the cookies of the whole
# registrable domain, EpicStaff's refresh cookie among them. Every one also hides the upstream's
# X-Frame-Options. A location with proxy_pass_request_headers off passes no Cookie on either.
# Inheritance as in the main server's check.
read -r -d '' plugin_hosts_check_program << 'AWK' || :
BEGIN { FS = "\t" }
NR == FNR {
  if ($3 ~ /^server_name "~\^\(\?<plugin_identifier>/) plugin_server = $1
  next
}
$1 != plugin_server { next }
{
  location = $2
  split($3, word, " ")
  if (!(location in seen)) { seen[location] = 1; order[++count] = location }
  if (word[1] == "internal") internal[location] = 1
  if (word[1] == "proxy_pass") target[location] = word[2]
  if (word[1] == "proxy_pass_request_headers" && word[2] == "off") no_request_headers[location] = 1
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

function passes_no_cookie(location) {
  if (location in no_request_headers) return 1
  if (!(location in sets_headers)) location = ""
  return (location in clears)
}

END {
  for (i = 1; i <= count; i++) {
    location = order[i]
    if (location == "" || !(location in target) || (location in internal)) continue
    checked++
    label = location " -> " target[location]
    if (!passes_no_cookie(location)) print label ": passes the browser's Cookie on"
    if (!hides(location, "set-cookie")) print label ": passes Set-Cookie through"
    if (!hides(location, "clear-site-data")) print label ": passes Clear-Site-Data through"
    if (!hides(location, "x-frame-options")) print label ": passes X-Frame-Options through"
  }
  print "checked " checked + 0
}
AWK

# $1 = a file of `nginx -T` output; prints the plugin hosts' check's problems, sorted.
plugin_hosts_violations() {
  flatten_configuration "$1" > "$work_dir/flat"
  awk "$plugin_hosts_check_program" "$work_dir/flat" "$work_dir/flat" | { grep -v '^checked ' || true; } \
    | LC_ALL=C sort
}

# $1 = description, $2 = how many proxied locations the plugin hosts' server must have. Checks the
# last rendered configuration (plugins on).
expect_plugin_hosts_cookie_free() {
  local problems checked
  problems=$(plugin_hosts_violations "$work_dir/out")
  checked=$(awk "$plugin_hosts_check_program" "$work_dir/flat" "$work_dir/flat" | sed -n 's/^checked //p')
  if [ -n "$problems" ]; then
    fail "$1: $(printf '%s\n' "$problems" | paste -sd ';' -)"
  elif [ "$checked" != "$2" ]; then
    fail "$1: found $checked proxied location(s) on the plugin hosts, not $2"
  else
    pass "$1 ($checked proxied locations, none passes a cookie either way, Clear-Site-Data or X-Frame-Options)"
  fi
}

# Reads the flattened configuration twice (the file name, twice) and checks the plugin hosts'
# server (the one whose server_name captures plugin_identifier): every answer the gateway gives
# itself instead of the plugin's carries X-EpicStaff-Gateway-Deny, set with `always` (each named
# error page of any of its locations, and each named location that returns 4xx or 5xx), and /api/
# hides the header from the plugin's own answers. A named error page that proxies (a frontend
# development server's page, in development mode) answers with the plugin's own content: it must
# hide the header instead, like /api/, and never set it. Prints one line per problem, then
# "checked <n>": the answering locations it found that answer for the gateway.
read -r -d '' gateway_deny_check_program << 'AWK' || :
BEGIN { FS = "\t" }
NR == FNR {
  if ($3 ~ /^server_name "~\^\(\?<plugin_identifier>/) plugin_server = $1
  next
}
$1 != plugin_server { next }
{
  last = split($3, word, " ")
  if (word[1] == "error_page" && substr(word[last], 1, 1) == "@") answering[word[last]] = 1
  if (substr($2, 1, 1) == "@" && word[1] == "return" && word[2] ~ /^[45][0-9][0-9]$/) answering[$2] = 1
  if (substr($2, 1, 1) == "@" && word[1] == "proxy_pass") proxying[$2] = 1
  if (word[1] == "add_header" && tolower(word[2]) == "x-epicstaff-gateway-deny" && word[last] == "always") marked[$2] = 1
  if (word[1] == "proxy_hide_header" && tolower(word[2]) == "x-epicstaff-gateway-deny") hides[$2] = 1
}
END {
  for (location in answering) {
    if (location in proxying) {
      if (location in marked) print location ": marks the plugin's own answer as the gateway's"
      if (!(location in hides)) print location ": passes a plugin's X-EpicStaff-Gateway-Deny on"
      continue
    }
    count++
    if (!(location in marked)) print location ": answers without X-EpicStaff-Gateway-Deny"
  }
  if (!(("^~ /api/") in hides)) print "^~ /api/: passes a plugin's X-EpicStaff-Gateway-Deny on"
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
  elif [ "$answering" -lt 4 ]; then
    fail "$1: found only $answering locations that answer for the gateway"
  else
    pass "$1 ($answering locations answer for the gateway, all marked; hidden from the plugin)"
  fi
}

# Reads the flattened configuration twice (the file name, twice) and checks the three headers the
# listeners for plugin credentials add for Django, in the internal API listener (8081) and, with
# -v development=true, the development API listener (8082):
#   - X-Plugin-Network-Secret, which tells Django a request came through one of them (plugin keys
#     authenticate only with it): the rendered PLUGINS_GATEWAY_SECRET (-v secret, quoted as
#     rendered), never a variable a caller could fill;
#   - X-EpicStaff-On-Behalf-Of: the caller's own header;
#   - X-Plugin-Development-Listener: $plugin_development_listener, which only the listener servers
#     set, each once at server level, to a literal: "" on 8081 (no header sent), 1 on 8082.
# Each is set exactly once in each listener's ^~ /api/, which passes none of the caller's own
# headers on, and nowhere else to a value (elsewhere they are only blanked, see the next check).
# Prints one line per problem, then "checked <listeners>".
read -r -d '' internal_headers_check_program << 'AWK' || :
BEGIN {
  FS = "\t"
  expected_value["8081"] = "\"\""
  expected_value["8082"] = "1"
}
NR == FNR {
  if ($3 == "listen 8081" || $3 == "listen 8082") listener[$1] = substr($3, 8)
  next
}
{
  in_listener = ($1 in listener)
  in_api = (in_listener && $2 == "^~ /api/")
  if (in_api && $3 == "proxy_pass_request_headers off") headers_off[$1] = 1
  split($3, word, " ")
  if (index($3, "$plugin_development_listener") > 0) {
    if (word[1] == "set" && word[2] == "$plugin_development_listener" && in_listener && $2 == "") {
      development_sets[$1]++
      development_value[$1] = word[3]
    } else if (!(in_api && word[1] == "proxy_set_header" && tolower(word[2]) == "x-plugin-development-listener")) {
      print "$plugin_development_listener used outside a listener's server level and /api/ (server " $1 ", location [" $2 "]): " $3
    }
  }
  if (word[1] != "proxy_set_header") next
  name = tolower(word[2])
  if (name != "x-plugin-network-secret" && name != "x-epicstaff-on-behalf-of" \
    && name != "x-plugin-development-listener") next
  if (!in_api) {
    if (word[3] != "\"\"" && word[3] != "''")
      print "set outside the listeners' /api/ (server " $1 ", location [" $2 "]): " $3
    next
  }
  count[$1, name]++
  value[$1, name] = substr($3, length(word[1]) + length(word[2]) + 3)
}
# wanted_label names the expected value in a problem line; the secret's is never printed.
function expect_header(server, label, name, shown, wanted, wanted_label) {
  if (count[server, name] != 1)
    print shown " is set " count[server, name] + 0 " times in " label
  else if (value[server, name] != wanted)
    print shown " is " value[server, name] " in " label ", not " wanted_label
}
END {
  for (server in listener) {
    port = listener[server]
    ports[port]++
    label = "the " port " listener's /api/"
    if (!headers_off[server]) print label " passes the caller's headers on"
    expect_header(server, label, "x-plugin-network-secret", "X-Plugin-Network-Secret", "\"" secret "\"", "PLUGINS_GATEWAY_SECRET")
    expect_header(server, label, "x-epicstaff-on-behalf-of", "X-EpicStaff-On-Behalf-Of", "$http_x_epicstaff_on_behalf_of", "the caller's header")
    expect_header(server, label, "x-plugin-development-listener", "X-Plugin-Development-Listener", "$plugin_development_listener", "$plugin_development_listener")
    if (development_sets[server] != 1)
      print "$plugin_development_listener is set " development_sets[server] + 0 " times by the " port " listener"
    else if (development_value[server] != expected_value[port])
      print "$plugin_development_listener is " development_value[server] " on " port ", not " expected_value[port]
  }
  if (ports["8081"] != 1) print ports["8081"] + 0 " servers listen on 8081, not 1"
  if (development == "true" && ports["8082"] != 1) print ports["8082"] + 0 " servers listen on 8082, not 1"
  if (development != "true" && ports["8082"] != 0) print "a server listens on 8082 with development mode off"
  print "checked " (ports["8081"] + ports["8082"])
}
AWK

# $1 = a file of `nginx -T` output, $2 = whether development mode is on (true or false); prints the
# internal header check's problems. Also: no line of the configuration but the listeners' `set` and
# their /api/'s header names $plugin_development_listener (no map or geo may fill it).
internal_header_problems() {
  flatten_configuration "$1" > "$work_dir/flat"
  awk -v secret="$gateway_secret" -v development="$2" "$internal_headers_check_program" \
    "$work_dir/flat" "$work_dir/flat" | { grep -v '^checked ' || true; }
  grep -v '^[[:space:]]*#' "$1" | grep -F '$plugin_development_listener' \
    | grep -vE '^[[:space:]]*set \$plugin_development_listener (""|1);$' \
    | grep -vE '^[[:space:]]*proxy_set_header X-Plugin-Development-Listener \$plugin_development_listener;$' \
    | sed 's/^[[:space:]]*/$plugin_development_listener named elsewhere: /' || true
}

# $1 = description, $2 = whether development mode is on. Checks the last rendered configuration
# (plugins on).
expect_internal_headers() {
  local problems
  problems=$(internal_header_problems "$work_dir/out" "$2")
  if [ -n "$problems" ]; then
    fail "$1: $(printf '%s\n' "$problems" | paste -sd ';' -)"
  else
    pass "$1"
  fi
}

# Every spelling of a header name with - or _ between its words, in lower case, one per line: with
# underscores_in_headers on, nginx passes each as a header of its own and Django folds them into
# one.
spellings_of() { # $1 = header name
  local rest word spelling
  local -a spellings next
  rest=$(printf '%s' "$1" | awk '{ print tolower($0) }')
  spellings=("${rest%%-*}")
  while [ "$rest" != "${rest#*-}" ]; do
    rest=${rest#*-}
    word=${rest%%-*}
    next=()
    for spelling in "${spellings[@]}"; do next+=("$spelling-$word" "${spelling}_$word"); done
    spellings=("${next[@]}")
  done
  printf '%s\n' "${spellings[@]}"
}
plugin_internal_header_spellings=$(
  {
    spellings_of X-Plugin-Network-Secret
    spellings_of X-EpicStaff-On-Behalf-Of
    spellings_of X-Plugin-Development-Listener
  } | paste -sd ' ' -
)

# Reads the flattened configuration and checks every location that proxies to Django
# (backend_server) and passes the caller's headers on (no proxy_pass_request_headers off): it
# must blank every spelling of the three listener headers (-v spellings), so no caller of a
# public server can send Django any of them. A location's proxy_set_header lines replace its
# server's, and the server's the http level's, only when it has any; the check applies that.
# Prints one line per location that passes a spelling on, then "checked <n> <m>": how many such
# locations it checked, and how many proxy to Django without the caller's headers.
read -r -d '' django_header_strip_check_program << 'AWK' || :
BEGIN {
  FS = "\t"
  wanted_count = split(spellings, wanted, " ")
}
{
  key = $1 SUBSEP $2
  if (!(key in seen)) { seen[key] = 1; order[++location_count] = key }
  split($3, word, " ")
  if (word[1] == "proxy_pass") target[key] = word[2]
  if (word[1] == "proxy_pass_request_headers") passes[key] = word[2]
  if (word[1] == "proxy_set_header") {
    sets_headers[key] = 1
    if (word[3] == "\"\"" || word[3] == "''") blanked[key, tolower(word[2])] = 1
  }
}
function header_level(server, location) {
  if ((server SUBSEP location) in sets_headers) return server SUBSEP location
  if ((server SUBSEP "") in sets_headers) return server SUBSEP ""
  return 0 SUBSEP ""
}
function passes_caller_headers(server, location,    value) {
  value = "on"
  if ((0 SUBSEP "") in passes) value = passes[0 SUBSEP ""]
  if ((server SUBSEP "") in passes) value = passes[server SUBSEP ""]
  if ((server SUBSEP location) in passes) value = passes[server SUBSEP location]
  return value != "off"
}
END {
  for (i = 1; i <= location_count; i++) {
    split(order[i], part, SUBSEP)
    if (part[2] == "" || target[order[i]] !~ /^http:\/\/backend_server(\/|$)/) continue
    if (!passes_caller_headers(part[1], part[2])) { closed++; continue }
    checked++
    level = header_level(part[1], part[2])
    missing = ""
    for (w = 1; w <= wanted_count; w++) if (!((level, wanted[w]) in blanked)) missing = missing " " wanted[w]
    if (missing != "") print "server " part[1] " [" part[2] "] passes on:" missing
  }
  print "checked " checked + 0 " " closed + 0
}
AWK

# $1 = a file of `nginx -T` output; prints the Django header check's problems, sorted.
django_header_problems() {
  flatten_configuration "$1" | awk -v spellings="$plugin_internal_header_spellings" \
    "$django_header_strip_check_program" | { grep -v '^checked ' || true; } | LC_ALL=C sort
}

# $1 = description, $2 = the least number of locations that must pass headers on to Django.
expect_django_headers_blanked() {
  local problems counts
  problems=$(django_header_problems "$work_dir/out")
  counts=$(flatten_configuration "$work_dir/out" | awk -v spellings="$plugin_internal_header_spellings" \
    "$django_header_strip_check_program" | sed -n 's/^checked //p')
  if [ -n "$problems" ]; then
    fail "$1: $(printf '%s\n' "$problems" | paste -sd ';' -)"
  elif [ "${counts% *}" -lt "$2" ]; then
    fail "$1: found only ${counts% *} locations that pass headers on to Django"
  else
    pass "$1 (${counts% *} locations pass headers on to Django and blank them, ${counts#* } pass none)"
  fi
}

# $1 = description, $2 = location (as written after `location`), $3 = directive without its ";".
# Passes when that location of the last rendered configuration has the directive itself. The
# texts go to awk through its environment, which keeps a backslash as written (-v would not).
expect_location_directive() {
  if flatten_configuration "$work_dir/out" \
    | expected_location=$2 expected_directive=$3 awk -F '\t' '
        $2 == ENVIRON["expected_location"] && $3 == ENVIRON["expected_directive"] { found = 1 }
        END { exit !found }'; then
    pass "$1"
  else
    fail "$1: [$2] has no [$3;]"
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
    expect_django_headers_blanked "PLUGINS_ENABLED=false $flags: no caller can send Django the internal listener's headers" 6
    leaked=""
    for text in plugin_identifier /srv/plugin-spa /api/admin/plugins/packages/ \
      /_epicstaff/plugin-upload-permission auth_request \
      /api/plugin-gateway/ /api/plugin-nodes/ plugins-fullchain.pem frame-ancestors\ \'self\'\ http \
      /_plugin_gateway_check X-Plugin-Gateway-Secret "listen 8081" "$gateway_secret" \
      '$http_x_epicstaff_on_behalf_of' \
      plugin_network_caller 10.235.0.0/24 /.well-known/epicstaff/callback \
      /usr/share/nginx/plugin-platform X-EpicStaff-Gateway-Deny @plugin_maintenance_page \
      maintenance.html plugin_maintenance /_plugin_development_page_check @plugin_development \
      plugin_spa_upstream plugin_spa_host '$plugin_development_listener' "listen 8082"; do
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
    expect_plugin_hosts_cookie_free "PLUGINS_ENABLED=true $flags: the plugin hosts' proxied locations (the platform config and /api/) pass no cookie either way, no Clear-Site-Data and no X-Frame-Options" 2
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
    # The SPA paths answer with the maintenance page while the flag file exists; the named
    # location keeps the 503 (error_page without "=") and marks it as the gateway's.
    flag_test='if (-f /srv/plugin-spa/$plugin_identifier/maintenance) {'
    if [ "$(directives | grep -cF "$flag_test")" = 2 ]; then
      pass "PLUGINS_ENABLED=true $flags tests the maintenance flag twice (both SPA locations)"
    else
      fail "PLUGINS_ENABLED=true $flags tests the maintenance flag $(directives | grep -cF "$flag_test") time(s), not 2"
    fi
    for location in "= /index.html" "/"; do
      expect_location_directive "PLUGINS_ENABLED=true $flags: [$location] answers 503 while the flag exists" \
        "$location" "return 503"
      expect_location_directive "PLUGINS_ENABLED=true $flags: [$location] answers its 503 with the maintenance page" \
        "$location" "error_page 503 @plugin_maintenance_page"
    done
    for directive in \
      "add_header Content-Security-Policy \"frame-ancestors 'self' https://epicstaff.test\" always" \
      "add_header Content-Security-Policy \"$maintenance_page_policy\" always" \
      "add_header Cache-Control no-store always" \
      "add_header Retry-After 30 always" \
      "add_header X-EpicStaff-Gateway-Deny maintenance always" \
      "add_header X-Content-Type-Options nosniff always" \
      "default_type text/html" \
      "root /usr/share/nginx/plugin-platform" \
      "try_files /maintenance.html =503"; do
      expect_location_directive "PLUGINS_ENABLED=true $flags: the maintenance page has [$directive]" \
        "@plugin_maintenance_page" "$directive"
    done
    # Map entries are printed outside any server and location; each text is unique to its map.
    expect_location_directive "PLUGINS_ENABLED=true $flags: a maintenance refusal comes with Retry-After: 30" \
      "" "maintenance 30"
    expect_location_directive "PLUGINS_ENABLED=true $flags: a maintenance refusal is marked as such" \
      "" "maintenance maintenance"
    expect_location_directive "PLUGINS_ENABLED=true $flags: a maintenance refusal gets the plugin_maintenance JSON" \
      "@plugin_denied" "return 503 '$maintenance_body'"
    if has_directive open_file_cache; then
      fail "PLUGINS_ENABLED=true $flags sets open_file_cache: the maintenance flag would be seen late"
    else
      pass "PLUGINS_ENABLED=true $flags keeps no open_file_cache, so the maintenance flag counts at once"
    fi
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
      'proxy_set_header X-EpicStaff-On-Behalf-Of $http_x_epicstaff_on_behalf_of;' \
      "proxy_set_header X-Plugin-Network-Secret \"$gateway_secret\";" \
      'if ($plugin_network_caller = 0) {'
    expect_internal_headers "PLUGINS_ENABLED=true $flags: only the internal listener's /api/ sets the network secret (from the environment) and the on-behalf-of header, and no development listener header" false
    expect_django_headers_blanked "PLUGINS_ENABLED=true $flags: no caller of a public server can send Django the internal listener's headers" 8
    leaked=""
    for text in /_plugin_development_page_check @plugin_development plugin_spa_upstream \
      plugin_spa_host /api/plugin-gateway/development-spa/ "listen 8082" \
      "set \$plugin_development_listener 1"; do
      if has_directive "$text"; then
        leaked="$leaked [$text]"
      fi
    done
    if [ -z "$leaked" ]; then
      pass "PLUGINS_ENABLED=true PLUGINS_DEV_MODE=false $flags renders no page decision, no development server and nothing on 8082"
    else
      fail "PLUGINS_ENABLED=true PLUGINS_DEV_MODE=false $flags renders development directives:$leaked"
    fi
    # Both checks run as subrequests that carry the request's Content-Length but read no body;
    # a limit of their own would turn a larger request into a 500.
    expect_location_directive "PLUGINS_ENABLED=true $flags: the upload permission check applies no body limit" \
      "= /_epicstaff/plugin-upload-permission" "client_max_body_size 0"
    expect_location_directive "PLUGINS_ENABLED=true $flags: the gateway check applies no body limit" \
      "= /_plugin_gateway_check" "client_max_body_size 0"
  fi
done; done

# $1 = description, $2 = location, the rest = header names. Passes when that location of the last
# rendered configuration blanks every spelling of each header itself (it sets headers of its own,
# so it inherits none).
expect_location_blanks() {
  local description=$1 location=$2 name missing
  shift 2
  missing=$(for name in "$@"; do spellings_of "$name"; done \
    | flatten_configuration_lines_missing "$location")
  if [ -z "$missing" ]; then
    pass "$description"
  else
    fail "$description: [$location] does not blank$(printf ' %s' $missing)"
  fi
}
# Reads header spellings on standard input; prints those the location of the last rendered
# configuration does not set to "".
flatten_configuration_lines_missing() { # $1 = location
  flatten_configuration "$work_dir/out" > "$work_dir/flat"
  awk -F '\t' -v location="$1" '
    NR == FNR {
      split($3, word, " ")
      if ($2 == location && word[1] == "proxy_set_header" && (word[3] == "\"\"" || word[3] == "'"''"'"))
        blanked[tolower(word[2])] = 1
      next
    }
    !($1 in blanked) { print $1 }' "$work_dir/flat" -
}

# Plugin development mode on, with the .localhost names it needs, in every combination of chat
# and TLS: both SPA locations ask the page decision before serving a file (after the maintenance
# test), the development server's answer gets the platform's headers and none of its own cookies,
# framing rule or policy, and never a person's login, an API key or a plugin context, and the
# development API listener serves the internal listener's routes to callers off the plugins subnet.
for chat_enabled in false true; do for ssl_mode in off on; do
  flags="CHAT_ENABLED=$chat_enabled NGINX_SSL_MODE=$ssl_mode PLUGINS_DEV_MODE=true"
  scheme=http
  if [ "$ssl_mode" = on ]; then
    scheme=https
  fi
  if expect_valid "nginx -t: PLUGINS_ENABLED=true $flags" PLUGINS_ENABLED=true PLUGINS_DEV_MODE=true \
    NGINX_SSL_MODE=$ssl_mode CHAT_ENABLED=$chat_enabled PLUGINS_BASE_DOMAIN=plugins.epicstaff.localhost \
    "DJANGO_FRONTEND_BASE_URL=$scheme://epicstaff.localhost" "$loopback_marker"; then
    expect_only_django_cookies "PLUGINS_ENABLED=true $flags: only Django gets and sets cookies"
    expect_plugin_hosts_cookie_free "PLUGINS_ENABLED=true $flags: the plugin hosts' proxied locations (the platform config, /api/ and the development server's page) pass no cookie either way, no Clear-Site-Data and no X-Frame-Options" 3
    expect_gateway_denies_marked "PLUGINS_ENABLED=true $flags: the gateway marks its own refusals, and never the development server's page"
    expect_internal_headers "PLUGINS_ENABLED=true $flags: both listeners' /api/ set the network secret (from the environment) and the on-behalf-of header, and only the development listener says it is" true
    expect_django_headers_blanked "PLUGINS_ENABLED=true $flags: no caller of a public server can send Django the listeners' headers" 8
    # Counted in the flattened configuration: one snippet, included in both SPA locations.
    page_checks=$(flatten_configuration "$work_dir/out" \
      | awk -F '\t' '$3 == "auth_request /_plugin_development_page_check" { count++ } END { print count + 0 }')
    flag_test='if (-f /srv/plugin-spa/$plugin_identifier/maintenance) {'
    if [ "$page_checks" = 2 ] && [ "$(directives | grep -cF "$flag_test")" = 2 ]; then
      pass "PLUGINS_ENABLED=true $flags asks the page decision in both SPA locations, and still tests the maintenance flag in both"
    else
      fail "PLUGINS_ENABLED=true $flags asks the page decision $page_checks time(s) and tests the maintenance flag $(directives | grep -cF "$flag_test") time(s), not 2 each"
    fi
    for location in "= /index.html" "/"; do
      for directive in "auth_request /_plugin_development_page_check" \
        "auth_request_set \$plugin_spa_upstream \$upstream_http_x_plugin_spa_upstream" \
        "error_page 403 = @plugin_development_page" "error_page 500 = @plugin_development_unreachable" \
        "recursive_error_pages on" "error_page 503 @plugin_maintenance_page" "return 503"; do
        expect_location_directive "PLUGINS_ENABLED=true $flags: [$location] has [$directive]" "$location" "$directive"
      done
    done
    for directive in internal "client_max_body_size 0" \
      "proxy_pass http://backend_server/api/plugin-gateway/development-spa/" \
      "proxy_pass_request_headers off" "proxy_pass_request_body off" "proxy_method GET" \
      "proxy_set_header Host localhost" "proxy_set_header X-Plugin-Gateway-Secret \"$gateway_secret\"" \
      "proxy_set_header X-Plugin-Identifier \$plugin_identifier"; do
      expect_location_directive "PLUGINS_ENABLED=true $flags: the page decision has [$directive]" \
        "= /_plugin_development_page_check" "$directive"
    done
    for directive in "proxy_pass http://\$plugin_spa_upstream" "return 502" \
      "error_page 502 504 = @plugin_development_unreachable" "proxy_hide_header Set-Cookie" \
      "proxy_hide_header Clear-Site-Data" "proxy_hide_header X-Frame-Options" \
      "proxy_hide_header Content-Security-Policy" "proxy_hide_header X-EpicStaff-Gateway-Deny" \
      "proxy_ignore_headers X-Accel-Redirect" "proxy_set_header Host \$plugin_spa_host" \
      "proxy_set_header X-Forwarded-Host \$host" \
      "proxy_set_header Upgrade \$http_upgrade" "proxy_set_header Connection \$connection_upgrade" \
      "proxy_buffering off" "proxy_read_timeout 1h" \
      "add_header Content-Security-Policy \"frame-ancestors 'self' $scheme://epicstaff.localhost\" always" \
      "add_header X-Content-Type-Options nosniff always" "add_header Origin-Agent-Cluster \"?1\" always"; do
      expect_location_directive "PLUGINS_ENABLED=true $flags: the development server's page has [$directive]" \
        "@plugin_development_page" "$directive"
    done
    expect_location_blanks "PLUGINS_ENABLED=true $flags: the development server gets no cookie, login, API key or plugin context, in any spelling" \
      "@plugin_development_page" Cookie Authorization X-API-Key X-EpicStaff-Plugin-Context
    # Map entries are printed outside any server and location.
    expect_location_directive "PLUGINS_ENABLED=true $flags: the development server is asked for localhost and its own port" \
      "" '"~:(?<plugin_spa_port>[0-9]+)$" localhost:$plugin_spa_port'
    expect_location_directive "PLUGINS_ENABLED=true $flags: the development server is asked for localhost when the decision names no port" \
      "" "default localhost"
    for directive in "return 503 \"The development server for this plugin cannot be reached.\\n\"" \
      "default_type text/html" "add_header Cache-Control no-store always" \
      "add_header X-EpicStaff-Gateway-Deny unavailable always" \
      "add_header Content-Security-Policy \"frame-ancestors 'self' $scheme://epicstaff.localhost\" always"; do
      expect_location_directive "PLUGINS_ENABLED=true $flags: the unreachable answer has [$directive]" \
        "@plugin_development_unreachable" "$directive"
    done
    if [ "$(directives | grep -cF 'if ($plugin_network_caller) {')" = 3 ] && has_directive 'listen 8082;'; then
      pass "PLUGINS_ENABLED=true $flags renders the development API listener, and it refuses the plugins subnet like EpicStaff's server and the plugin hosts"
    else
      fail "PLUGINS_ENABLED=true $flags: $(directives | grep -cF 'if ($plugin_network_caller) {') server(s) refuse the plugins subnet, not 3, or nothing listens on 8082"
    fi
  fi
done; done

# The internal header check itself, on configurations broken on purpose: it must name each break.
if expect_valid "nginx -t: PLUGINS_ENABLED=true, for the internal header check's self-test" \
  PLUGINS_ENABLED=true; then
  # $1 = what was broken, $2 = text the problems must contain, $3 = the awk program that breaks
  # the `nginx -T` output: in_snippet is set for the lines of the file named by $4 (default: the
  # listeners' shared snippet), $5 = whether development mode is on in the configuration.
  expect_internal_header_break() {
    local problems file=${4:-plugins-api-listener} development=${5:-false}
    awk "/^# configuration file / { in_snippet = (\$0 ~ /$file\\.snippet:\$/) } $3" \
      "$work_dir/out" > "$work_dir/out-broken"
    problems=$(internal_header_problems "$work_dir/out-broken" "$development")
    case "$problems" in
      *"$2"*) pass "the internal header check finds $1" ;;
      *) fail "the internal header check, with $1, found [$(printf '%s\n' "$problems" | paste -sd ';' -)]" ;;
    esac
  }
  expect_internal_header_break "the secret taken from the caller" "not PLUGINS_GATEWAY_SECRET" \
    'in_snippet && /^ *proxy_set_header X-Plugin-Network-Secret / { print "    proxy_set_header X-Plugin-Network-Secret $http_x_plugin_network_secret;"; next } { print }'
  expect_internal_header_break "the secret missing" "X-Plugin-Network-Secret is set 0 times" \
    '!(in_snippet && /^ *proxy_set_header X-Plugin-Network-Secret /)'
  expect_internal_header_break "the on-behalf-of header missing" "X-EpicStaff-On-Behalf-Of is set 0 times" \
    '!(in_snippet && /^ *proxy_set_header X-EpicStaff-On-Behalf-Of /)'
  expect_internal_header_break "the caller's headers passed on" "passes the caller's headers on" \
    '!(in_snippet && /^ *proxy_pass_request_headers off;/)'
  expect_internal_header_break "the secret set in another location" "set outside the listeners' /api/" \
    '{ print } in_snippet && /^location \/ [{]/ { print "    proxy_set_header X-Plugin-Network-Secret \"x\";" }'
  expect_internal_header_break "the internal listener claiming to be the development one" \
    "\$plugin_development_listener is 1 on 8081" \
    'in_snippet && /^ *set \$plugin_development_listener / { print "    set $plugin_development_listener 1;"; next } { print }' \
    plugins-internal-api-true
fi

# The same check on a configuration with development mode on: the development listener's value
# and the header must never come from the caller, and nothing else may fill the variable.
if expect_valid "nginx -t: PLUGINS_DEV_MODE=true, for the internal header check's self-test" \
  PLUGINS_ENABLED=true PLUGINS_DEV_MODE=true PLUGINS_BASE_DOMAIN=plugins.epicstaff.localhost \
  DJANGO_FRONTEND_BASE_URL=http://epicstaff.localhost "$loopback_marker"; then
  expect_internal_header_break "the development listener's value taken from the caller" \
    "\$plugin_development_listener is \$http_x_plugin_development_listener on 8082" \
    'in_snippet && /^ *set \$plugin_development_listener / { print "    set $plugin_development_listener $http_x_plugin_development_listener;"; next } { print }' \
    plugins-development-api-true true
  expect_internal_header_break "the development header taken from the caller" \
    "X-Plugin-Development-Listener is \$http_x_plugin_development_listener in the 8082 listener's /api/" \
    'in_snippet && /^ *proxy_set_header X-Plugin-Development-Listener / { print "    proxy_set_header X-Plugin-Development-Listener $http_x_plugin_development_listener;"; next } { print }' \
    plugins-api-listener true
  expect_internal_header_break "the development header missing" "X-Plugin-Development-Listener is set 0 times" \
    '!(in_snippet && /^ *proxy_set_header X-Plugin-Development-Listener /)' plugins-api-listener true
  expect_internal_header_break "a map filling the development listener's value" \
    "\$plugin_development_listener named elsewhere" \
    '{ print } in_snippet && /^server [{]/ && !added { print "map $http_x_forwarded_for $plugin_development_listener { default 1; }"; added = 1 }' \
    plugins-development-api-true true
  expect_internal_header_break "the development header set on a plugin host" "set outside the listeners' /api/" \
    '{ print } in_snippet && /^location @plugin_development_page [{]/ { print "    proxy_set_header X-Plugin-Development-Listener 1;" }' \
    plugins-development-server-true true
  expect_internal_header_break "no development listener" "0 servers listen on 8082, not 1" \
    '!(in_snippet && /^ *listen 8082;/)' plugins-development-api-true true

  grep -vF 'X-EpicStaff-Gateway-Deny' "$work_dir/out" > "$work_dir/out-without-deny-header"
  found=$(gateway_deny_problems "$work_dir/out-without-deny-header")
  expected=$(printf '%s\n' "@plugin_denied: answers without X-EpicStaff-Gateway-Deny" \
    "@plugin_maintenance_page: answers without X-EpicStaff-Gateway-Deny" \
    "@plugin_request_too_large: answers without X-EpicStaff-Gateway-Deny" \
    "@plugin_unavailable: answers without X-EpicStaff-Gateway-Deny" \
    "@plugin_development_unreachable: answers without X-EpicStaff-Gateway-Deny" \
    "@plugin_development_page: passes a plugin's X-EpicStaff-Gateway-Deny on" \
    "^~ /api/: passes a plugin's X-EpicStaff-Gateway-Deny on" | LC_ALL=C sort)
  if [ "$found" = "$expected" ]; then
    pass "the gateway deny check finds every development location: the unreachable answer, and the development page that must hide the plugin's marker"
  else
    fail "the gateway deny check, development mode, with the header deleted, found [$(printf '%s\n' "$found" | paste -sd ';' -)]"
  fi
fi

if expect_valid "nginx -t: PLUGINS_ENABLED=true, for the Django header check's self-test" \
  PLUGINS_ENABLED=true; then

  # The Django header check itself: one spelling dropped from the snippet must show in every
  # location it checks, and one include dropped in exactly that location.
  checked=$(flatten_configuration "$work_dir/out" | awk -v spellings="$plugin_internal_header_spellings" \
    "$django_header_strip_check_program" | sed -n 's/^checked \([0-9]*\) .*/\1/p')
  awk '/^# configuration file / { in_snippet = ($0 ~ /strip-plugin-internal-headers\.snippet:$/) }
       !(in_snippet && /^proxy_set_header X_EpicStaff_On-Behalf_Of /)' "$work_dir/out" > "$work_dir/out-broken"
  found=$(django_header_problems "$work_dir/out-broken")
  if [ "$(printf '%s\n' "$found" | grep -c ' passes on: x_epicstaff_on-behalf_of$')" = "$checked" ]; then
    pass "the Django header check finds a spelling missing from the snippet in all $checked locations"
  else
    fail "the Django header check, with one spelling dropped, found [$(printf '%s\n' "$found" | paste -sd ';' -)]"
  fi
  awk '/^# configuration file / { in_default = ($0 ~ /\/default\.conf:$/) }
       in_default && !dropped && /include \/etc\/nginx\/conf\.d\/strip-plugin-internal-headers\.snippet;/ { dropped = 1; next }
       { print }' "$work_dir/out" > "$work_dir/out-broken"
  found=$(django_header_problems "$work_dir/out-broken")
  if [ "$(printf '%s\n' "$found" | grep -c .)" = 1 ] \
    && [ "$(printf '%s\n' "$found" | wc -w)" -ge 26 ]; then
    pass "the Django header check finds a location without the snippet ($(printf '%s' "$found" | cut -d: -f1))"
  else
    fail "the Django header check, with one include dropped, found [$(printf '%s\n' "$found" | paste -sd ';' -)]"
  fi
fi

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

# The plugin hosts' check itself, with development mode on (all three proxied locations):
#   - every Cookie, Set-Cookie and Clear-Site-Data rule deleted: it names exactly those three
#     locations, and not the platform config's Cookie (it passes no request header on);
#   - only the Clear-Site-Data line of cookie-free-upstream.snippet deleted: all three pass a
#     plugin's or a development server's Clear-Site-Data through, so each takes it from the snippet.
# Update the list when a location of the plugin hosts that proxies is added or removed.
plugin_hosts_locations=(
  '= /.well-known/epicstaff/config.json -> http://backend_server/api/plugin-public/$plugin_identifier/config/'
  '^~ /api/ -> http://$plugin_upstream'
  '@plugin_development_page -> http://$plugin_spa_upstream'
)
if expect_valid "nginx -t: PLUGINS_DEV_MODE=true, for the plugin hosts' check's self-test" \
  PLUGINS_ENABLED=true PLUGINS_DEV_MODE=true PLUGINS_BASE_DOMAIN=plugins.epicstaff.localhost \
  DJANGO_FRONTEND_BASE_URL=http://epicstaff.localhost "$loopback_marker"; then
  grep -vF -e 'proxy_set_header Cookie "";' -e 'proxy_hide_header Set-Cookie;' \
    -e 'proxy_hide_header Clear-Site-Data;' "$work_dir/out" > "$work_dir/out-without-cookie-rules"
  found=$(plugin_hosts_violations "$work_dir/out-without-cookie-rules")
  expected=$(for location in "${plugin_hosts_locations[@]}"; do
    printf '%s\n' "$location: passes Set-Cookie through" "$location: passes Clear-Site-Data through"
    # The platform config passes no request header on, so no Cookie either.
    if [ "${location#= /.well-known/}" = "$location" ]; then
      printf '%s\n' "$location: passes the browser's Cookie on"
    fi
  done | LC_ALL=C sort)
  if [ "$found" = "$expected" ]; then
    pass "the plugin hosts' check finds every location of the plugin hosts that proxies"
  else
    fail "the plugin hosts' check, with every cookie rule deleted, found [$(printf '%s\n' "$found" | paste -sd ';' -)]"
  fi
  awk '/^# configuration file / { in_snippet = ($0 ~ /cookie-free-upstream\.snippet:$/) }
       !(in_snippet && /proxy_hide_header Clear-Site-Data;/)' "$work_dir/out" \
    > "$work_dir/out-without-snippet-clear-site-data"
  found=$(plugin_hosts_violations "$work_dir/out-without-snippet-clear-site-data")
  expected=$(printf '%s: passes Clear-Site-Data through\n' "${plugin_hosts_locations[@]}" | LC_ALL=C sort)
  if [ "$found" = "$expected" ]; then
    pass "every proxied location of the plugin hosts hides Clear-Site-Data through cookie-free-upstream.snippet"
  else
    fail "the plugin hosts' check, without the snippet's Clear-Site-Data rule, found [$(printf '%s\n' "$found" | paste -sd ';' -)]"
  fi
fi

# The gateway deny check itself: with every X-EpicStaff-Gateway-Deny line deleted it must name
# exactly the four locations that answer for the gateway, and /api/.
if expect_valid "nginx -t: PLUGINS_ENABLED=true, for the gateway deny check's self-test" \
  PLUGINS_ENABLED=true; then
  grep -vF 'X-EpicStaff-Gateway-Deny' "$work_dir/out" > "$work_dir/out-without-deny-header"
  found=$(gateway_deny_problems "$work_dir/out-without-deny-header")
  expected=$(printf '%s\n' "@plugin_denied: answers without X-EpicStaff-Gateway-Deny" \
    "@plugin_maintenance_page: answers without X-EpicStaff-Gateway-Deny" \
    "@plugin_request_too_large: answers without X-EpicStaff-Gateway-Deny" \
    "@plugin_unavailable: answers without X-EpicStaff-Gateway-Deny" \
    "^~ /api/: passes a plugin's X-EpicStaff-Gateway-Deny on" | LC_ALL=C sort)
  if [ "$found" = "$expected" ]; then
    pass "the gateway deny check finds every location that answers for the gateway"
  else
    fail "the gateway deny check, with the header deleted, found [$(printf '%s\n' "$found" | paste -sd ';' -)]"
  fi
fi

# The maintenance page as committed: static, so it runs nothing and loads nothing from anywhere
# (its policy allows only inline style), reloads itself, and says what is happening.
maintenance_page="$platform_dir/maintenance.html"
if [ ! -f "$maintenance_page" ]; then
  fail "$maintenance_page is missing: the plugin hosts have no maintenance page to serve"
else
  loads=$(grep -noiE '<script|<link|<img|<iframe|<object|<embed|<form|src=|href=|url\(|@import|[[:space:]]on[a-z]+=' \
    "$maintenance_page" | paste -sd ' ' - || true)
  if [ -z "$loads" ]; then
    pass "the maintenance page has no script, link, image, frame, form or handler"
  else
    fail "the maintenance page runs or loads something: $loads"
  fi
  if grep -qF '<meta http-equiv="refresh" content="30">' "$maintenance_page" \
    && grep -qF 'This plugin is being updated.' "$maintenance_page" \
    && grep -qF 'It will be back in a few minutes. This page reloads by itself.' "$maintenance_page" \
    && grep -qF '@media (prefers-color-scheme: dark)' "$maintenance_page"; then
    pass "the maintenance page reloads every 30 s, says so, and follows the colour scheme"
  else
    fail "the maintenance page lacks its refresh, its text or its dark colours"
  fi
fi

# The flag is read like every other boolean in the stack (env_bool).
if expect_valid "PLUGINS_ENABLED=Yes is accepted" PLUGINS_ENABLED=Yes; then
  expect_directives "PLUGINS_ENABLED=Yes is read as true" "root /srv/plugin-spa/\$plugin_identifier/current;"
fi
expect_refused "PLUGINS_ENABLED=maybe is refused" "PLUGINS_ENABLED='maybe' is not a boolean" \
  PLUGINS_ENABLED=maybe

# PLUGINS_DEV_MODE: read like every other boolean, only with plugins on, and refused on any
# deployment whose plugin domain or EpicStaff host is not a .localhost name.
local_names=(PLUGINS_BASE_DOMAIN=plugins.epicstaff.localhost DJANGO_FRONTEND_BASE_URL=http://epicstaff.localhost)
if expect_valid "PLUGINS_DEV_MODE=Yes is accepted with .localhost names" PLUGINS_ENABLED=true \
  PLUGINS_DEV_MODE=Yes "${local_names[@]}" "$loopback_marker"; then
  expect_directives "PLUGINS_DEV_MODE=Yes is read as true" "listen 8082;"
fi
expect_refused "PLUGINS_DEV_MODE=maybe is refused" "PLUGINS_DEV_MODE='maybe' is not a boolean" \
  PLUGINS_ENABLED=true PLUGINS_DEV_MODE=maybe "${local_names[@]}"
expect_refused "an unset PLUGINS_DEV_MODE is refused with plugins on" \
  "environment variable PLUGINS_DEV_MODE is not set" PLUGINS_ENABLED=true unset:PLUGINS_DEV_MODE
if expect_valid "PLUGINS_ENABLED=false ignores PLUGINS_DEV_MODE=maybe" PLUGINS_ENABLED=false \
  PLUGINS_DEV_MODE=maybe; then
  if has_directive 'listen 8082'; then
    fail "PLUGINS_ENABLED=false renders the development API listener"
  fi
fi
expect_valid "PLUGINS_ENABLED=false ignores an unset PLUGINS_DEV_MODE" PLUGINS_ENABLED=false \
  unset:PLUGINS_DEV_MODE || :
expect_valid "PLUGINS_ENABLED=false ignores PLUGINS_DEV_MODE=true on names that are not .localhost" \
  PLUGINS_ENABLED=false PLUGINS_DEV_MODE=true || :
development_refusal="plugin development mode is only for a deployment on your own machine"
for names in "plugins.epicstaff.test http://epicstaff.localhost" \
  "plugins.epicstaff.localhost https://epicstaff.example.com" \
  "plugins.epicstaff.localhost https://epicstaff.localhost.example.com" \
  "plugins.epicstaff.localhost http://xlocalhost" "plugins.localhost.example.com https://epicstaff.test" \
  "plugins.epicstaff.test https://epicstaff.test"; do
  read -r base_domain frontend_url <<< "$names"
  expect_refused "PLUGINS_DEV_MODE=true with PLUGINS_BASE_DOMAIN=$base_domain and DJANGO_FRONTEND_BASE_URL=$frontend_url is refused" \
    "$development_refusal" PLUGINS_ENABLED=true PLUGINS_DEV_MODE=true \
    "PLUGINS_BASE_DOMAIN=$base_domain" "DJANGO_FRONTEND_BASE_URL=$frontend_url" "$loopback_marker"
done
for frontend_url in http://localhost:4200 http://EpicStaff.LocalHost https://epicstaff.localhost:8443/; do
  expect_valid "PLUGINS_DEV_MODE=true with DJANGO_FRONTEND_BASE_URL=$frontend_url is accepted" \
    PLUGINS_ENABLED=true PLUGINS_DEV_MODE=true PLUGINS_BASE_DOMAIN=plugins.epicstaff.localhost \
    "DJANGO_FRONTEND_BASE_URL=$frontend_url" "$loopback_marker" || :
done

# PLUGINS_DEV_LOOPBACK_ONLY, which only src/docker-compose.plugins-dev.yaml sets: development mode
# is refused without it, as Django refuses it, since without that file 80 and 443 are open on
# every interface. Read like every other boolean; absent means false.
loopback_refusal="Start EpicStaff with -f src/docker-compose.plugins-dev.yaml after -f src/docker-compose.yaml"
expect_refused "PLUGINS_DEV_MODE=true without PLUGINS_DEV_LOOPBACK_ONLY (no development compose file) is refused" \
  "$loopback_refusal" PLUGINS_ENABLED=true PLUGINS_DEV_MODE=true "${local_names[@]}"
expect_refused "PLUGINS_DEV_MODE=true with PLUGINS_DEV_LOOPBACK_ONLY=false is refused" \
  "$loopback_refusal" PLUGINS_ENABLED=true PLUGINS_DEV_MODE=true "${local_names[@]}" PLUGINS_DEV_LOOPBACK_ONLY=false
expect_refused "PLUGINS_DEV_LOOPBACK_ONLY=maybe is refused" "PLUGINS_DEV_LOOPBACK_ONLY='maybe' is not a boolean" \
  PLUGINS_ENABLED=true PLUGINS_DEV_MODE=true "${local_names[@]}" PLUGINS_DEV_LOOPBACK_ONLY=maybe
if expect_valid "PLUGINS_DEV_MODE=false with the development compose file's marker is accepted" \
  PLUGINS_ENABLED=true PLUGINS_DEV_MODE=false "${local_names[@]}" "$loopback_marker"; then
  if has_directive 'listen 8082'; then
    fail "PLUGINS_DEV_MODE=false with the marker renders the development API listener"
  fi
fi
# The compose files as committed: the development one sets the marker to "true" on both services
# that check it, and the main one never names it, so .env cannot reach either container with it.
dev_compose_file="$nginx_dir/../docker-compose.plugins-dev.yaml"
marked_services=$(awk '/^  [A-Za-z0-9_-]+:$/ { service = substr($1, 1, length($1) - 1) }
  /^      PLUGINS_DEV_LOOPBACK_ONLY: "true"$/ { print service }' "$dev_compose_file" \
  | LC_ALL=C sort | paste -sd ' ' -)
if [ "$marked_services" != "django_app epicstaff-nginx" ]; then
  fail "docker-compose.plugins-dev.yaml sets PLUGINS_DEV_LOOPBACK_ONLY: \"true\" for [$marked_services], not django_app and epicstaff-nginx"
elif grep -v '^[[:space:]]*#' "$compose_file" | grep -q PLUGINS_DEV_LOOPBACK_ONLY; then
  fail "docker-compose.yaml names PLUGINS_DEV_LOOPBACK_ONLY: only docker-compose.plugins-dev.yaml may set it"
else
  pass "only docker-compose.plugins-dev.yaml sets PLUGINS_DEV_LOOPBACK_ONLY, to true, for django_app and epicstaff-nginx"
fi

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
# The stub also records the headers that reach it on /api/plugin-runtime/ and /api/plugin-nodes/
# (/tmp/stub-headers.log), to check what the internal API listener sends Django on the routes of
# plugin backends and of the node, and that EpicStaff's own server passes none of them on.
cat > "$work_dir/stub-django.conf" <<'STUB'
log_format stub_django '$request_method $uri $request_length';
log_format stub_headers 'secret=[$http_x_plugin_network_secret] on_behalf_of=[$http_x_epicstaff_on_behalf_of] development=[$http_x_plugin_development_listener] authorization=[$http_authorization] organization=[$http_x_organization_id]';
server {
    listen 127.0.0.1:8000;
    access_log /tmp/stub-django.log stub_django;
    client_max_body_size 0;
    location ^~ /api/plugin-runtime/ {
        access_log /tmp/stub-headers.log stub_headers;
        default_type application/json;
        return 200 '{"stub":"plugin runtime"}';
    }
    location ^~ /api/plugin-nodes/ {
        access_log /tmp/stub-django.log stub_django;
        access_log /tmp/stub-headers.log stub_headers;
        default_type application/json;
        return 200 '{"stub":"plugin node API"}';
    }
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

# A caller of EpicStaff's own server cannot send Django the internal listener's headers in any
# spelling (the stub's $http_ variables match every spelling, and would join them).
live sh -c ': > /tmp/stub-headers.log'
status=$(live curl -s -o /dev/null -w '%{http_code}' -H 'Host: epicstaff.test' \
  -H 'Authorization: PluginKey esp-check' -H "X-Plugin-Network-Secret: $gateway_secret" \
  -H 'X_Plugin_Network_Secret: forged' -H 'X-Plugin_Network-Secret: forged' \
  -H 'X-EpicStaff-On-Behalf-Of: 7' -H 'X_EpicStaff_On_Behalf_Of: 7' -H 'X-EpicStaff_On-Behalf_Of: 7' \
  -H 'X-Plugin-Development-Listener: 1' -H 'X_Plugin_Development_Listener: 1' -H 'X-Plugin_Development-Listener: 1' \
  http://127.0.0.1/api/plugin-runtime/me/ || true)
received=$(live cat /tmp/stub-headers.log)
if [ "$status" = 200 ] && [ "$received" = "secret=[-] on_behalf_of=[-] development=[-] authorization=[PluginKey esp-check] organization=[-]" ]; then
  pass "EpicStaff's own server passes Django no network secret, on-behalf-of or development listener header, in any spelling"
else
  fail "EpicStaff's own server, /api/plugin-runtime/me/: status $status, Django got other headers than expected"
fi

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

# The package upload route with the default PLUGINS_MAX_PACKAGE_MB=300, above the server's 50M:
# nginx compares an upload's Content-Length with the limit of every location it passes through,
# including the permission check's, which reads no body. Only the upload's headers are sent: nginx
# decides on them before it reads any of the body.
#   - an upload of 51 MiB with a made-up token gets the JSON 401 (not a 500 from the check),
#     after a 100 Continue nginx sends to read and drop the body;
#   - a SuperAdmin's gets 100 Continue and goes on to Django (the stub answers 201 without
#     waiting for the body; nginx streams uploads unbuffered);
#   - 301 MiB and one byte, more than the cap plus the framing allowance, get 413 before Django
#     is asked anything.
set_docker_arguments PLUGINS_ENABLED=true PLUGINS_MAX_PACKAGE_MB=300 DJANGO_HOST=127.0.0.1 DJANGO_PORT=8000
live_container=$(docker run -d "${docker_arguments[@]}" \
  -v "$work_dir/stub-django.conf:/etc/nginx/conf.d/zz-stub-django.conf:ro" "$image")
for _ in $(seq 50); do
  if live curl -s -o /dev/null http://127.0.0.1:8000/ 2> /dev/null; then break; fi
  sleep 0.1
done
# upload_headers AUTHORIZATION CONTENT_LENGTH: prints the status codes nginx answered, in order;
# the answer's body goes to /tmp/response in the container.
upload_headers() {
  live sh -c ': > /tmp/stub-django.log; : > /tmp/response
    curl -s -o /tmp/response -D /tmp/headers --max-time 3 -X POST -H "Host: epicstaff.test" \
      -H "Authorization: $1" -H "Content-Type: multipart/form-data; boundary=check" \
      -H "Content-Length: $2" -H "Expect: 100-continue" \
      http://127.0.0.1/api/admin/plugins/packages/ > /dev/null 2>&1
    awk "/^HTTP\\// { printf \"%s \", \$2 }" /tmp/headers' upload_headers "$@" || true
}
permission_asked() { live grep -q "^GET /api/admin/plugins/packages/upload-permission/ " /tmp/stub-django.log; }
mebibyte=1048576
statuses=$(upload_headers "Bearer made-up" $((51 * mebibyte)))
if { [ "$statuses" = "401 " ] || [ "$statuses" = "100 401 " ]; } \
  && live grep -q '"code":"not_authenticated"' /tmp/response && permission_asked; then
  pass "PLUGINS_MAX_PACKAGE_MB=300: a 51 MiB upload with a made-up token gets the JSON 401"
else
  fail "PLUGINS_MAX_PACKAGE_MB=300: a 51 MiB upload with a made-up token: statuses [$statuses], body $(live head -c 120 /tmp/response | tr '\n' ' ')"
fi
statuses=$(upload_headers "Bearer superadmin" $((51 * mebibyte)))
if [ "$statuses" = "100 201 " ] && permission_asked && reached_django "POST /api/admin/plugins/packages/ "; then
  pass "PLUGINS_MAX_PACKAGE_MB=300: a SuperAdmin's 51 MiB upload is taken and reaches Django"
else
  fail "PLUGINS_MAX_PACKAGE_MB=300: a SuperAdmin's 51 MiB upload: statuses [$statuses], expected 100 then Django's 201"
fi
statuses=$(upload_headers "Bearer superadmin" $((301 * mebibyte + 1)))
if [ "$statuses" = "413 " ] && ! permission_asked; then
  pass "PLUGINS_MAX_PACKAGE_MB=300: 301 MiB and one byte get 413 before Django is asked"
else
  fail "PLUGINS_MAX_PACKAGE_MB=300: 301 MiB and one byte: statuses [$statuses], permission asked: $(permission_asked && echo yes || echo no)"
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
live sh -c ': > /tmp/stub-django.log; : > /tmp/stub-headers.log'
status=$(live curl -s -o /dev/null -w '%{http_code}' -H 'Authorization: PluginNodeKey k' \
  -H 'X-Plugin-Network-Secret: forged' -H 'X-Plugin-Development-Listener: 1' \
  http://127.0.0.1:8081/api/plugin-nodes/self/desired-state/ || true)
received=$(live cat /tmp/stub-headers.log)
if ! reached_django "GET /api/plugin-nodes/self/desired-state/"; then
  fail "the internal API listener did not pass a plugins-subnet caller on to Django ($status)"
elif [ "$received" = "secret=[$gateway_secret] on_behalf_of=[-] development=[-] authorization=[PluginNodeKey k] organization=[-]" ]; then
  pass "the internal API listener serves the node's API to the plugins subnet, with the environment's network secret and never a development listener header ($status from the stub)"
else
  # Never print the received line: on a failure it may hold the secret.
  fail "the internal API listener, node API: status $status, Django got other headers than expected"
fi
# What Django receives through the internal listener: the network secret from the environment,
# whatever the caller sends in its place (every spelling), and the caller's on-behalf-of header,
# key and organization. Without an on-behalf-of header, none reaches Django.
expected_secret="secret=[$gateway_secret]"
for case in "7|-H X-EpicStaff-On-Behalf-Of:7|$expected_secret on_behalf_of=[7]" \
  "forged|-H X-Plugin-Network-Secret:forged -H X_Plugin_Network_Secret:forged -H X-Plugin_Network-Secret:forged -H X-EpicStaff-On-Behalf-Of:7|$expected_secret on_behalf_of=[7]" \
  "none|-H X-Plugin-Network-Secret:forged|$expected_secret on_behalf_of=[-]" \
  "development|-H X-Plugin-Development-Listener:1 -H X_Plugin_Development_Listener:1 -H X-Plugin_Development-Listener:1|$expected_secret on_behalf_of=[-]"; do
  IFS='|' read -r label extra expected <<< "$case"
  live sh -c ': > /tmp/stub-headers.log'
  # shellcheck disable=SC2086  # $extra is a list of curl arguments without spaces in them.
  status=$(live curl -s -o /dev/null -w '%{http_code}' -H 'Authorization: PluginKey esp-check' \
    -H 'X-Organization-Id: 3' $extra http://127.0.0.1:8081/api/plugin-runtime/me/ || true)
  received=$(live cat /tmp/stub-headers.log)
  # The internal listener never says it is the development one, whatever the caller sends.
  if [ "$status" = 200 ] && [ "$received" = "$expected development=[-] authorization=[PluginKey esp-check] organization=[3]" ]; then
    pass "the internal API listener sends Django the environment's network secret and no development listener header ($label)"
  else
    # Never print the received line: on a failure it may hold the secret.
    fail "the internal API listener ($label): status $status, Django got other headers than expected"
  fi
done
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
