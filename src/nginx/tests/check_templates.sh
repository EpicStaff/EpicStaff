#!/usr/bin/env bash
# Renders src/nginx/templates the way the epicstaff-nginx container does at start-up (its
# docker-entrypoint.d scripts, then envsubst), with the nginx image pinned in
# src/docker-compose.yaml, and runs `nginx -T` (test the configuration and print it) on the result:
#
#   - every combination of PLUGINS_ENABLED and NGINX_SSL_MODE, with throwaway self-signed
#     certificates; with the flag off nothing plugin-related may be rendered;
#   - the values 16-normalize-plugins-enabled.envsh derives, and the ones it must refuse.
#
# Needs Docker and openssl. The containers have no network and publish no ports; nothing is left
# behind. Usage, from anywhere: bash src/nginx/tests/check_templates.sh
set -euo pipefail

nginx_dir=$(cd "$(dirname "$0")/.." && pwd)
compose_file="$nginx_dir/../docker-compose.yaml"
plugins_envsh="$nginx_dir/docker-entrypoint.d/16-normalize-plugins-enabled.envsh"
chat_envsh="$nginx_dir/docker-entrypoint.d/15-normalize-chat-enabled.envsh"

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
    DJANGO_FRONTEND_BASE_URL=https://epicstaff.test \
    "$@"; do
    docker_arguments+=(-e "$assignment")
  done
  docker_arguments+=(
    -v "$nginx_dir/templates:/etc/nginx/templates:ro"
    -v "$chat_envsh:/docker-entrypoint.d/15-normalize-chat-enabled.envsh:ro"
    -v "$plugins_envsh:/docker-entrypoint.d/16-normalize-plugins-enabled.envsh:ro"
    -v "$work_dir/certs:/etc/nginx/certs:ro"
  )
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

if [ -x "$plugins_envsh" ]; then
  pass "16-normalize-plugins-enabled.envsh is executable (the image ignores it otherwise)"
else
  fail "16-normalize-plugins-enabled.envsh is not executable: the image's entrypoint skips it"
fi

for ssl_mode in off on; do
  if expect_valid "nginx -t: PLUGINS_ENABLED=false NGINX_SSL_MODE=$ssl_mode" \
    PLUGINS_ENABLED=false NGINX_SSL_MODE=$ssl_mode; then
    leaked=""
    for text in plugin_identifier /srv/plugin-spa /api/admin/plugins/packages/ \
      /_epicstaff/plugin-upload-permission auth_request \
      /api/plugin-gateway/ plugins-fullchain.pem frame-ancestors\ \'self\'\ http; do
      if has_directive "$text"; then
        leaked="$leaked [$text]"
      fi
    done
    if [ -z "$leaked" ] && directives | grep -qE "frame-src 'self' *;"; then
      pass "PLUGINS_ENABLED=false NGINX_SSL_MODE=$ssl_mode renders nothing plugin-related"
    else
      fail "PLUGINS_ENABLED=false NGINX_SSL_MODE=$ssl_mode renders plugin directives:$leaked"
    fi
  fi

  if expect_valid "nginx -t: PLUGINS_ENABLED=true NGINX_SSL_MODE=$ssl_mode" \
    PLUGINS_ENABLED=true NGINX_SSL_MODE=$ssl_mode; then
    expected_tls="include /etc/nginx/conf.d/plugins-ssl-off.snippet;"
    if [ "$ssl_mode" = on ]; then
      expected_tls="ssl_certificate /etc/nginx/certs/plugins-fullchain.pem;"
    fi
    expect_directives "PLUGINS_ENABLED=true NGINX_SSL_MODE=$ssl_mode renders the plugin routes" \
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
      "$expected_tls"
  fi
done

# The flag is read like every other boolean in the stack (env_bool).
if expect_valid "PLUGINS_ENABLED=Yes is accepted" PLUGINS_ENABLED=Yes; then
  expect_directives "PLUGINS_ENABLED=Yes is read as true" "root /srv/plugin-spa/\$plugin_identifier/current;"
fi
expect_refused "PLUGINS_ENABLED=maybe is refused" "PLUGINS_ENABLED='maybe' is not a boolean" \
  PLUGINS_ENABLED=maybe

# With the flag off the plugin values are never read, so they cannot stop nginx.
expect_valid "PLUGINS_ENABLED=false ignores malformed plugin values" PLUGINS_ENABLED=false \
  "PLUGINS_BASE_DOMAIN=bad;value" DJANGO_FRONTEND_BASE_URL=none PLUGINS_MAX_PACKAGE_MB=many || :

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

if [ "$failures" -ne 0 ]; then
  echo "FAILED: $failures check(s)"
  exit 1
fi
echo "All template checks passed."
