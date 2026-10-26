#!/usr/bin/env bash
# Smoke check of outbound access on a running stack with the plugins profile: asks plugins_egress
# as a plugin backend does, from inside es_plugins under the plugin's own UID, with the proxy URL
# the plugin's process got (read from its /proc/<pid>/environ, as the plugin itself could):
#
#   1. the declared URL is reached: CONNECT 200, then HTTP 200;
#   2. an undeclared host and private literals in several spellings: 403 ERR_HOST_NOT_ALLOWED;
#   3. the declared host on ports 80 and 22: 403 ERR_PORT_NOT_ALLOWED;
#   4. plain HTTP through the proxy: 403 ERR_ONLY_CONNECT;
#   5. a wrong password, and no credentials: 407;
#   6. no direct connection out, and no DNS for outside names;
#   7. the policy directory is closed to the plugin (EACCES);
#   8. in plugins_egress: IPv6 off, the firewall refusing every IPv4 private range, and NET_ADMIN
#      in no capability set of Squid or a helper;
#   9. the proxy's log names the plugin and holds neither its password nor a Proxy-Authorization
#      header (the password is compared inside the probe; only a count comes out).
#
# It never prints a credential. One `ok -` / `not ok -` line per check.
# Settings, from the environment:
#   PLUGIN_UID         the plugin's UID, from its Runtime tab (required)
#   PLUGIN_IDENTIFIER  the plugin's identifier (default: weather)
#   DECLARED_URL       an HTTPS URL on one of its declared hosts
#                      (default: https://geocoding-api.open-meteo.com/v1/search?name=Berlin&count=1)
# Runs `docker compose` on src/docker-compose.yaml, with its usual .env.
# Usage, from anywhere: PLUGIN_UID=<uid> bash src/plugins_egress/smoke/check_egress.sh
set -euo pipefail

smoke_dir=$(cd "$(dirname "$0")" && pwd)
egress_dir=$(cd "$smoke_dir/.." && pwd)
compose_file=$(cd "$egress_dir/.." && pwd)/docker-compose.yaml
plugin_uid=${PLUGIN_UID:?set PLUGIN_UID to the UID the Runtime tab shows}
plugin_identifier=${PLUGIN_IDENTIFIER:-weather}
declared_url=${DECLARED_URL:-https://geocoding-api.open-meteo.com/v1/search?name=Berlin&count=1}
declared_host=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.urlsplit(sys.argv[1]).hostname)' "$declared_url")
probe_source=$(cat "$smoke_dir/egress_probe.py")

compose() { docker compose -f "$compose_file" "$@"; }

failures=0
pass() { echo "ok - $1"; }
fail() {
  echo "not ok - $1"
  failures=$((failures + 1))
}
# The probe in es_plugins as the plugin's UID, with the plugin process's own proxy URL.
probe() {
  compose exec -T -u "$plugin_uid:$plugin_uid" es_plugins \
    python3 -I -c "$probe_source" --proxy same-uid "$@" 2>&1 || true
}
expect() { # description, expected text, then probe arguments
  local description=$1 expected=$2 answer
  shift 2
  answer=$(probe "$@")
  case "$answer" in
    *"$expected"*) pass "$description ($answer)" ;;
    *) fail "$description: got '$answer', expected '$expected'" ;;
  esac
}

echo "# the plugin's process"
user=$(probe user)
if [ "$user" = "user=$plugin_identifier" ]; then
  pass "a process of UID $plugin_uid has a proxy URL for $plugin_identifier"
else
  fail "no process of UID $plugin_uid with the proxy URL of $plugin_identifier: $user"
  exit 1
fi

echo "# 1-5. through the proxy"
expect "the declared URL is reached" "connect=200 http=200" get "$declared_url"
expect "an undeclared host is refused" "connect=403 squid=ERR_HOST_NOT_ALLOWED" connect example.com:443
for literal in 127.1 2130706433 0x7f000001 '[::ffff:127.0.0.1]' 169.254.169.254; do
  expect "the literal $literal is on no list" "connect=403 squid=ERR_HOST_NOT_ALLOWED" connect "$literal:443"
done
for port in 80 22; do
  expect "$declared_host on port $port is refused" "connect=403 squid=ERR_PORT_NOT_ALLOWED" connect "$declared_host:$port"
done
expect "plain HTTP through the proxy is refused" "http=403 squid=ERR_ONLY_CONNECT" plain "http://$declared_host/"
expect "a wrong password gets 407" "connect=407" --wrong-password connect "$declared_host:443"
expect "no credentials get 407" "connect=407" --no-credentials connect "$declared_host:443"

echo "# 6-7. around the proxy"
direct=$(probe direct 1.1.1.1 443)
case "$direct" in
  direct=connected) fail "a direct connection to 1.1.1.1:443 succeeded" ;;
  *) pass "no direct connection to 1.1.1.1:443 ($direct)" ;;
esac
expect "no DNS for example.com" "resolve=failed" resolve example.com
expect "the policy directory is closed to the plugin" "open=EACCES" open /var/lib/es_plugins_egress/policy/hosts.json

echo "# 8. plugins_egress"
ipv6=$(compose exec -T plugins_egress cat /proc/sys/net/ipv6/conf/all/disable_ipv6 2>&1 || true)
if [ "$ipv6" = 1 ]; then pass "IPv6 is off"; else fail "disable_ipv6 is '$ipv6'"; fi
rules=$(compose exec -T plugins_egress iptables -S EGRESS_PRIVATE 2>&1 || true)
missing=""
while read -r range; do
  case "$rules" in *"-A EGRESS_PRIVATE -d $range -j REJECT"*) ;; *) missing="$missing $range" ;; esac
done < <(grep -v ':' "$egress_dir/private_ranges.txt")
if [ -z "$missing" ]; then
  pass "EGRESS_PRIVATE refuses every IPv4 range of private_ranges.txt"
else
  fail "EGRESS_PRIVATE lacks:$missing"
fi
# Squid is PID 1 and its helpers are its children; a `docker compose exec` process has neither parent.
held=$(compose exec -T plugins_egress python3 -I -c '
import os
NET_ADMIN = 1 << 12
seen, held = [], []
for pid in filter(str.isdigit, os.listdir("/proc")):
    try:
        status = dict(line.split(":\t", 1) for line in open(f"/proc/{pid}/status").read().splitlines() if ":\t" in line)
    except OSError:
        continue
    if pid != "1" and status["PPid"].strip() != "1":
        continue
    name = status["Name"].strip()
    seen.append(name)
    for capability_set in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"):
        if int(status[capability_set], 16) & NET_ADMIN:
            held.append(f"{name}:{capability_set}")
print(" ".join(sorted(set(seen))), "|", " ".join(held) or "none")
' 2>&1 || true)
case "$held" in
  *"basic_ncsa_auth"*"plugin_host_acl"*"squid"*"| none") pass "no NET_ADMIN in any set of $(echo "$held" | cut -d'|' -f1)" ;;
  *) fail "capabilities: $held" ;;
esac

echo "# 9. the proxy's log"
proxy_log=$(compose logs --no-color plugins_egress 2>&1)
if grep -F -- " user=$plugin_identifier " <<< "$proxy_log" > /dev/null; then
  pass "the log names the plugin (user=$plugin_identifier)"
else
  fail "no user=$plugin_identifier line in the log"
fi
secret=$(compose logs --no-color plugins_egress 2>&1 | compose exec -T -u "$plugin_uid:$plugin_uid" es_plugins \
  python3 -I -c "$probe_source" --proxy same-uid count-secret 2>&1 || true)
if [ "$secret" = secret=0 ]; then
  pass "the log holds neither the plugin's password nor its Basic token"
else
  fail "the plugin's password or Basic token in the log: $secret"
fi
headers=$(grep -ci 'proxy-authorization' <<< "$proxy_log" || true)
if [ "$headers" = 0 ]; then
  pass "no Proxy-Authorization header in the log"
else
  fail "$headers Proxy-Authorization line(s) in the log"
fi

if [ "$failures" -ne 0 ]; then
  echo "FAILED: $failures check(s)"
  exit 1
fi
echo "All egress smoke checks passed."
