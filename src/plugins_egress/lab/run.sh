#!/usr/bin/env bash
# The egress proxy lab. Runs plugins_egress exactly as src/docker-compose.yaml defines it, built
# from its production Dockerfile, with the plugin node's real EgressPolicyWriter writing the policy,
# and checks from two plugin clients what a plugin can and cannot reach:
#
#   - Squid waits for the policy files, and the firewall is installed first;
#   - each plugin reaches exactly its own hosts (exact and *. entries, case, trailing dot); wrong
#     or missing credentials get 407; Squid never looks up a name the plugin may not reach;
#   - the clients have no way out but the proxy;
#   - names that resolve to private addresses, and private literals in every spelling, are
#     refused, with Docker's resolver forwarding to a lab DNS server and to the host's resolvers;
#   - a DNS-rebinding race, forced with lab-only settings that never ship (a 1 s DNS cache and a
#     3 s pause after the access rules), reaches nothing with the firewall, and reaches the
#     victim once the firewall is flushed, so the window the firewall closes is real;
#   - CONNECT to port 443 only, no plain HTTP; httpx and requests take the proxy from HTTPS_PROXY;
#   - no password, Basic token or Proxy-Authorization header in any log;
#   - a full host-helper queue (forced with one slow lab helper) refuses at once, and Squid looks
#     up none of the names it refused;
#   - while one plugin floods the proxy, with wrong passwords and then with names on no list, a new
#     plugin user still gets through within a few seconds, no flooded request gets a tunnel, no
#     flooded name is looked up, and Squid keeps running without a restart;
#   - IPv6 off, the firewall rules in place, and NET_ADMIN in no capability set of Squid or a
#     helper; the entrypoint refuses to start without SETPCAP, with IPv6 on, or with no IPv4
#     range, and starts with no IPv6 range;
#   - with --timings: how long a new host, a revoked host, a new user and a removed password
#     take to apply (about 30 s, 30 s, at once, 30 s), without a restart of Squid;
#   - with --overload (about 4 minutes): a password-check queue overloaded for more than 3 minutes,
#     forced with one checker slowed to 0.2 s a check, leaves Squid running with the production
#     action (ERR), and stops it with Squid's default (die) as the control.
#
# One `ok -` / `not ok -` line per check. Every run has project, container and image names of its
# own, so runs never collide; it removes every container, volume, network and image it made.
# Needs Docker, internet access, and python3 with PyYAML (scripts/envtool.py writes the env file
# the extended service needs).
# Usage, from anywhere: bash src/plugins_egress/lab/run.sh [--timings] [--overload]
set -euo pipefail

lab_dir=$(cd "$(dirname "$0")" && pwd)
repository=$(cd "$lab_dir/../../.." && pwd)
work=$(mktemp -d)
timings=0
overload=0
for option in "$@"; do
  case "$option" in
    --timings) timings=1 ;;
    --overload) overload=1 ;;
    *)
      echo "usage: $0 [--timings] [--overload]" >&2
      exit 2
      ;;
  esac
done

python3 "$repository/scripts/envtool.py" --dev --env-file "$work/lab.env" > /dev/null
# The shell's values win over the env file's. The DNS address is known once labdns runs.
lab_name="plugins-egress-lab-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
export IMAGE_TAG=lab EGRESS_LAB_WORK=$work EGRESS_LAB_DNS_ADDRESS=127.0.0.1 EGRESS_LAB_NAME=$lab_name
proxy=$lab_name
declared_url="https://geocoding-api.open-meteo.com/v1/search?name=Berlin&count=1"

compose() {
  docker compose -p "$lab_name" -f "$lab_dir/compose.yaml" --env-file "$work/lab.env" \
    --profile plugins --profile lab "$@"
}
cleanup() {
  docker rm -f "$lab_name-guard" > /dev/null 2>&1 || true
  compose down -v --rmi all --remove-orphans > /dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

failures=0
pass() { echo "ok - $1"; }
fail() {
  echo "not ok - $1"
  failures=$((failures + 1))
}
wait_for() { # seconds, then a command; returns once the command succeeds
  local deadline=$((SECONDS + $1))
  shift
  until "$@" > /dev/null 2>&1; do
    if [ "$SECONDS" -ge "$deadline" ]; then
      return 1
    fi
    sleep 1
  done
}
# No grep -q: under pipefail, its early exit would fail `docker logs` on a long log.
logged() { docker logs "$1" 2>&1 | grep -F -- "$2" > /dev/null; } # container, text
count_in_log() { docker logs "$1" 2>&1 | grep -cF -- "$2" || true; }

writer() { compose exec -T writer python /lab/tools/policy_writer.py call "$@"; }
# The password of a plugin the writer issued; kept in a file, never printed.
issue_password() {
  writer issue-password "$1" | awk '{ print $3 }' > "$work/password-$1"
  chmod 0600 "$work/password-$1"
}
# probe CLIENT USER PASSWORD_OF [probe arguments]: egress_probe.py in a plugin client, with the proxy
# URL in its environment only. PROXY_HOST picks the proxy instance (default: egress).
probe() {
  local client=$1 user=$2 owner=$3
  shift 3
  PROXY_URL="http://$user:$(cat "$work/password-$owner" 2> /dev/null || echo none)@${PROXY_HOST:-egress}:3128" \
    compose exec -T -e PROXY_URL "$client" python -I /lab/egress_probe.py "$@" 2>&1 || true
}
expect() { # description, expected text, then probe arguments
  local description=$1 expected=$2 answer
  shift 2
  answer=$(probe "$@")
  # A transport error (error=...) is the internet's, not a proxy decision: ask once more.
  case "$answer" in error=*) answer="$(probe "$@") (asked twice)" ;; esac
  case "$answer" in
    *"$expected"*) pass "$description ($answer)" ;;
    *) fail "$description: got '$answer', expected '$expected'" ;;
  esac
}
victim_connections() { compose logs victim 2>&1 | grep -c 'VICTIM CONNECTED' || true; }
labdns_count() { compose logs labdns 2>&1 | grep -c -- "$1" || true; }

echo "# build the production image and the lab tools"
compose build --quiet
compose up -d labdns victim plugin-a plugin-b > /dev/null 2>&1
EGRESS_LAB_DNS_ADDRESS=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$(compose ps -q labdns)")
plugin_b_address=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$(compose ps -q plugin-b)")
export EGRESS_LAB_DNS_ADDRESS
wait_for 30 logged "$(compose ps -q labdns)" 'labdns ready'

echo "# start-up"
compose up -d egress > /dev/null 2>&1
if wait_for 60 logged "$proxy" "waiting for the plugin node's policy files"; then
  sleep 3
  if logged "$proxy" 'plugins_egress: egress firewall installed' && ! logged "$proxy" 'Accepting HTTP Socket'; then
    pass "the firewall is installed first, and Squid waits for the policy files"
  else
    fail "start-up order: $(docker logs "$proxy" 2>&1 | tail -n 5)"
  fi
else
  fail "the proxy did not wait for its policy: $(docker logs "$proxy" 2>&1 | tail -n 10)"
fi
compose up -d writer > /dev/null 2>&1
if wait_for 60 logged "$proxy" 'Accepting HTTP Socket'; then
  pass "Squid starts once the node's writer has written its empty policy"
else
  fail "Squid did not start after the writer started: $(docker logs "$proxy" 2>&1 | tail -n 10)"
  exit 1
fi
proxy_started=$(docker inspect -f '{{.State.StartedAt}} {{.RestartCount}}' "$proxy")

for plugin in a b probe; do
  issue_password "$plugin"
done
# probe allows names and literals that point at private space, so only the private-address check
# can refuse them.
hosts=$(
  cat << EOF
{"a": ["geocoding-api.open-meteo.com", "*.wikipedia.org"],
 "b": ["api.github.com"],
 "probe": ["*.nip.io", "*.rebind.test", "*.mixed.test", "*.private.test", "*.ipv6only.test", "127.0.0.1", "127.1",
           "2130706433", "0x7f000001", "0177.0.0.1", "::1", "::ffff:127.0.0.1", "169.254.169.254",
           "100.64.0.1", "fd00:ec2::254", "2606:4700:4700::1111", "$plugin_b_address"],
 "flooder": [],
 "newcomer1": ["geocoding-api.open-meteo.com"], "newcomer2": ["geocoding-api.open-meteo.com"],
 "newcomer3": ["geocoding-api.open-meteo.com"]}
EOF
)
writer write-hosts "$(echo "$hosts" | tr -d '\n')" > /dev/null
cat > "$work/race.conf" << EOF
# Lab only, never shipped: the production configuration, Squid asking labdns directly, a 1 s DNS
# cache, and a 3 s pause after the access rules for names under .slow.rebind.test.
include /etc/squid/production.conf
dns_nameservers $EGRESS_LAB_DNS_ADDRESS
positive_dns_ttl 1 seconds
negative_dns_ttl 1 seconds
external_acl_type lab_delay ttl=0 negative_ttl=0 children-max=5 %DST /lab/delay_acl
acl lab_delay external lab_delay
always_direct allow lab_delay
EOF
{
  echo "# Lab only, never shipped: the production rules, Squid asking labdns directly, and one host"
  echo "# helper, given the production helper's %ul %DST, that answers names under .slow.rebind.test"
  echo "# 3 s late, with a queue of one."
  sed 's#^external_acl_type plugin_hosts .*#external_acl_type plugin_hosts ttl=30 negative_ttl=30 children-max=1 children-startup=1 queue-size=1 %ul %DST /lab/delay_acl#' \
    "$lab_dir/../squid.conf"
  echo "dns_nameservers $EGRESS_LAB_DNS_ADDRESS"
} > "$work/queue.conf"
write_overload_configuration() { # on-persistent-overload action, file
  cat > "$2" << EOF
# Lab only, never shipped: the production configuration with one password checker, slowed to
# 0.2 s a check, and a queue of one, so a flood overloads it for good; on-persistent-overload=$1.
include /etc/squid/production.conf
auth_param basic program /lab/slow_auth /etc/squid/policy/passwords
auth_param basic children 1 startup=1 idle=1 queue-size=1 on-persistent-overload=$1
EOF
}
write_overload_configuration ERR "$work/overload.conf"
write_overload_configuration die "$work/overload-die.conf"
if ! compose up -d --wait --wait-timeout 120 egress-plain egress-race egress-queue > "$work/up.log" 2>&1; then
  fail "the lab instances did not start: $(tail -n 5 "$work/up.log")"
fi

echo "# 1. each plugin reaches its own hosts only"
expect "a reaches its declared host" "connect=200 http=200" plugin-a a a get "https://geocoding-api.open-meteo.com/v1/search?name=Berlin&count=1"
expect "a is refused b's host" "connect=403 http=- squid=ERR_HOST_NOT_ALLOWED" plugin-a a a get https://api.github.com/
expect "a is refused an undeclared host" "connect=403 http=- squid=ERR_HOST_NOT_ALLOWED" plugin-a a a get https://example.com/
expect "*.wikipedia.org covers de.wikipedia.org" "connect=200" plugin-a a a connect de.wikipedia.org:443
expect "*.wikipedia.org covers de.m.wikipedia.org, two levels down" "connect=200" plugin-a a a connect de.m.wikipedia.org:443
expect "*.wikipedia.org does not cover wikipedia.org" "connect=403 squid=ERR_HOST_NOT_ALLOWED" plugin-a a a connect wikipedia.org:443
expect "*.wikipedia.org does not cover evilwikipedia.org" "connect=403 squid=ERR_HOST_NOT_ALLOWED" plugin-a a a connect evilwikipedia.org:443
expect "the host is compared lower-cased" "connect=200" plugin-a a a connect GEOCODING-API.Open-Meteo.com:443
expect "the host's trailing dot is ignored" "connect=200" plugin-a a a connect geocoding-api.open-meteo.com.:443
expect "b reaches its own host" "connect=200 http=200" plugin-b b b get https://api.github.com/
expect "b is refused a's host" "connect=403 http=- squid=ERR_HOST_NOT_ALLOWED" plugin-b b b get https://geocoding-api.open-meteo.com/
expect "user a with b's password gets 407" "connect=407 squid=ERR_CACHE_ACCESS_DENIED" plugin-b a b connect geocoding-api.open-meteo.com:443
expect "user b with a's password gets 407" "connect=407 squid=ERR_CACHE_ACCESS_DENIED" plugin-a b a connect api.github.com:443
expect "a wrong password gets 407" "connect=407" plugin-a a a --wrong-password connect geocoding-api.open-meteo.com:443
expect "no credentials get 407" "connect=407" plugin-a a a --no-credentials connect geocoding-api.open-meteo.com:443
exfil_name="exfil-$RANDOM$RANDOM.rebind.test"
control_name="control-$RANDOM$RANDOM.rebind.test"
probe plugin-a a a connect "$exfil_name:443" > /dev/null
probe plugin-a probe probe connect "$control_name:443" > /dev/null
sleep 1
exfil_queries=$(labdns_count "query A $exfil_name")
control_queries=$(labdns_count "query A $control_name")
if [ "$exfil_queries" = 0 ] && [ "$control_queries" -ge 1 ]; then
  pass "Squid never looks up a name the plugin may not reach (0 queries; $control_queries for an allowed one)"
else
  fail "labdns queries: refused name $exfil_queries, allowed name $control_queries"
fi

echo "# 2. a plugin has no way out but the proxy"
expect "no direct connection to 1.1.1.1:443" "direct=ENETUNREACH" plugin-a a a direct 1.1.1.1 443
expect "no DNS for outside names" "resolve=failed" plugin-a a a resolve geocoding-api.open-meteo.com

echo "# 3. private destinations"
expect "control: 1.1.1.1.nip.io is reached" "connect=200" plugin-a probe probe connect 1.1.1.1.nip.io:443
for name in 10.0.0.1.nip.io 127.0.0.1.nip.io 169.254.169.254.nip.io 192.168.65.254.nip.io \
  "victim-$RANDOM.private.test" "mixed-$RANDOM.mixed.test"; do
  expect "$name, which resolves to a private address, is refused" "connect=403 squid=ERR_PRIVATE_DST" plugin-a probe probe connect "$name:443"
done
for authority in 127.0.0.1:443 127.1:443 2130706433:443 0x7f000001:443 0177.0.0.1:443 \
  '[::ffff:127.0.0.1]:443' 169.254.169.254:443 100.64.0.1:443 "$plugin_b_address:443"; do
  expect "the literal $authority is refused" "connect=403 squid=ERR_PRIVATE_DST" plugin-a probe probe connect "$authority"
done
# With IPv6 off, Squid drops the IPv6 lines of its ACL at start ("IPv6 has not been enabled"), so
# an IPv6 destination fails at the connection: the kernel has no IPv6 route out.
if logged "$proxy" 'aclIpParseIpData: IPv6 has not been enabled'; then
  pass "Squid runs without IPv6"
else
  fail "Squid did not report IPv6 disabled"
fi
for authority in '[::1]:443' '[fd00:ec2::254]:443' '[2606:4700:4700::1111]:443'; do
  expect "the IPv6 literal $authority cannot be reached" "connect=503 squid=ERR_CONNECT_FAIL" plugin-a probe probe connect "$authority"
done
expect "a name with IPv6 addresses only cannot be reached" "connect=503" plugin-a probe probe connect "v6-$RANDOM.ipv6only.test:443"
connections=$(victim_connections)
if [ "$connections" = 0 ]; then pass "the victim got no connection"; else fail "the victim got $connections connection(s)"; fi

echo "# 3c. a DNS-rebinding race: the first answer public, then the victim, TTL 1"
race() { # label; prints the victim connections it caused and the race's DNS answers
  local name="r$RANDOM$RANDOM.slow.rebind.test" before answer
  before=$(victim_connections)
  answer=$(PROXY_HOST=egress-race probe plugin-a probe probe connect "$name:443")
  sleep 1
  race_answers=$(labdns_count "answer $name")
  race_connections=$(($(victim_connections) - before))
  race_result=$answer
}
race
if [ "$race_answers" -ge 2 ] && [ "$race_connections" = 0 ]; then
  pass "with the firewall, the rebound name reaches nothing ($race_result; $race_answers DNS answers)"
else
  fail "with the firewall: $race_connections victim connection(s), $race_answers DNS answers, $race_result"
fi
docker exec "$lab_name-race" iptables -F EGRESS_PRIVATE
race
if [ "$race_connections" -ge 1 ]; then
  pass "control, the firewall flushed: the same race reaches the victim ($race_result), so the firewall closes a real window"
else
  fail "control: the race did not reach the victim without the firewall ($race_answers DNS answers, $race_result)"
fi

echo "# 3d. Docker's resolver forwarding to the host's, through the firewall"
check_resolver=$(docker exec "$lab_name-plain" grep '^nameserver' /etc/resolv.conf)
case "$check_resolver" in
  'nameserver 127.0.0.11') pass "the plain instance resolves through Docker's resolver" ;;
  *) fail "resolver: $check_resolver" ;;
esac
PROXY_HOST=egress-plain expect "it reaches a declared host" "connect=200 http=200" plugin-a a a get "$declared_url"
PROXY_HOST=egress-plain expect "it refuses a name that resolves to a private address" "connect=403 squid=ERR_PRIVATE_DST" plugin-a probe probe connect 10.0.0.1.nip.io:443

echo "# 5. client libraries"
clients=$(PROXY_URL="http://a:$(cat "$work/password-a")@egress:3128" HTTPS_PROXY="http://a:$(cat "$work/password-a")@egress:3128" \
  compose exec -T -e HTTPS_PROXY plugin-a python /lab/tools/http_clients.py 2>&1 || true)
case "$clients" in
  *"httpx declared=200 undeclared=ProxyError"*"requests declared=200 undeclared=ProxyError"*)
    pass "httpx and requests use HTTPS_PROXY with its credentials ($(echo "$clients" | tr '\n' ' '))" ;;
  *) fail "client libraries: $clients" ;;
esac

echo "# 7. CONNECT to port 443 only"
for port in 80 8443 22; do
  expect "CONNECT to port $port is refused" "connect=403 squid=ERR_PORT_NOT_ALLOWED" plugin-a a a connect "geocoding-api.open-meteo.com:$port"
done
expect "plain HTTP through the proxy is refused" "http=403 squid=ERR_ONLY_CONNECT" plugin-a a a plain http://geocoding-api.open-meteo.com/

echo "# 4. live policy changes"
if [ "$timings" = 1 ]; then
  poll() { # output file, expected text, then probe arguments; writes the time it first matched
    local file=$1 expected=$2 deadline=$((SECONDS + 75)) answer
    shift 2
    while [ "$SECONDS" -lt "$deadline" ]; do
      answer=$(probe "$@")
      case "$answer" in *"$expected"*)
        date +%s.%N > "$file"
        return 0
        ;;
      esac
      sleep 1
    done
    echo never > "$file"
  }
  elapsed() { python3 -c "import sys; print('did not apply within 75 s' if sys.argv[1] == 'never' else f'{float(sys.argv[1]) - float(sys.argv[2]):.1f} s')" "$(cat "$1")" "$2"; }
  probe plugin-a a a connect api.open-meteo.com:443 > /dev/null      # caches "not allowed"
  probe plugin-a a a connect en.wikipedia.org:443 > /dev/null        # caches "allowed"
  probe plugin-b b b connect api.github.com:443 > /dev/null          # caches b's credentials
  : > "$work/password-c"
  probe plugin-b c c connect geocoding-api.open-meteo.com:443 > /dev/null
  hosts_written=$(writer write-hosts "$(echo "$hosts" | tr -d '\n' | sed 's/"a": \[[^]]*\]/"a": ["geocoding-api.open-meteo.com", "api.open-meteo.com"]/; s/^{/{"c": ["geocoding-api.open-meteo.com"], /')" | awk '{ print $2 }')
  issue_password c
  user_added=$(date +%s.%N)
  password_removed=$(writer remove-password b | awk '{ print $2 }')
  poll "$work/t-add-host" "connect=200" plugin-a a a connect api.open-meteo.com:443 &
  poll "$work/t-revoke-host" "connect=403" plugin-a a a connect en.wikipedia.org:443 &
  poll "$work/t-new-user" "connect=200" plugin-b c c connect geocoding-api.open-meteo.com:443 &
  poll "$work/t-remove-password" "connect=407" plugin-b b b connect api.github.com:443 &
  wait
  echo "# a host added: $(elapsed "$work/t-add-host" "$hosts_written"); a host revoked: $(elapsed "$work/t-revoke-host" "$hosts_written");" \
    "a new user: $(elapsed "$work/t-new-user" "$user_added"); a password removed: $(elapsed "$work/t-remove-password" "$password_removed")"
  for result in t-add-host t-revoke-host t-new-user t-remove-password; do
    if [ "$(cat "$work/$result")" = never ]; then fail "$result did not apply within 75 s"; else pass "$result applied"; fi
  done
else
  echo "# timings skipped (run with --timings)"
fi

echo "# 8. a full host-helper queue"
burst_tag="$RANDOM$RANDOM"
PROXY_URL="http://probe:$(cat "$work/password-probe")@egress-queue:3128" \
  compose exec -T -e PROXY_URL plugin-a python -I /lab/tools/burst.py 6 "$burst_tag" > "$work/burst" 2>&1 || true
sleep 1
refused_at_once=0
looked_up=0
while read -r name seconds status squid_error; do
  queries=$(labdns_count "query A $name")
  # The lookup names the user, so Squid answers a request it cannot queue as it does wrong credentials.
  if [ "$status" = 407 ] && [ "$squid_error" = ERR_CACHE_ACCESS_DENIED ] && [ "${seconds%%.*}" -lt 1 ]; then
    refused_at_once=$((refused_at_once + 1))
    looked_up=$((looked_up + queries))
  fi
done < "$work/burst"
if [ "$refused_at_once" -ge 3 ] && [ "$looked_up" = 0 ] && logged "$lab_name-queue" "queue full. Request rejected"; then
  pass "a full host-helper queue refuses at once ($refused_at_once of 6, 407 ERR_CACHE_ACCESS_DENIED) and looks up none of those names"
else
  fail "full host-helper queue: $refused_at_once refused at once, $looked_up DNS queries for them: $(tr '\n' ';' < "$work/burst")"
fi

echo "# 9. a flood from one plugin"
issue_password flooder
echo "# the writer hashes proxy passwords with bcrypt cost $(compose exec -T writer sh -c "cut -d'\$' -f3 /policy/passwords | sort -u | tr '\n' ' '")"
flood() { # mode, seconds, output file: plugin-b floods the shipped proxy as the flooder
  PROXY_URL="http://flooder:$(cat "$work/password-flooder")@${PROXY_HOST:-egress}:3128" \
    compose exec -T -e PROXY_URL plugin-b python -I /lab/tools/flood.py "$1" "$2" 64 > "$3" 2>&1 || true
}
newcomer() { # user, label: a user issued now, and the time its first request takes
  local started answer took
  issue_password "$1"
  started=$(date +%s.%N)
  answer=$(probe plugin-a "$1" "$1" get "$declared_url")
  took=$(python3 -c "import sys; print(f'{float(sys.argv[2]) - float(sys.argv[1]):.1f}')" "$started" "$(date +%s.%N)")
  if [[ "$answer" == *"connect=200 http=200"* ]] && python3 -c "import sys; sys.exit(float(sys.argv[1]) >= 5)" "$took"; then
    pass "$2: a new plugin user authenticates and reaches its host in $took s ($answer)"
  else
    fail "$2: a new plugin user took $took s: $answer"
  fi
}
steady() { # output file: plugin a, already active, asks for its host every 2 s for 24 s
  local deadline=$((SECONDS + 24))
  while [ "$SECONDS" -lt "$deadline" ]; do
    probe plugin-a a a connect geocoding-api.open-meteo.com:443 >> "$1"
    sleep 2
  done
}
steady_result() { # label, output file
  local answered refused
  answered=$(grep -c 'connect=200' "$2" || true)
  refused=$(grep -vc 'connect=200' "$2" || true)
  if [ "$refused" = 0 ]; then
    pass "$1: an active plugin's requests all went through ($answered of $answered)"
  else
    fail "$1: an active plugin's requests failed $refused times: $(sort "$2" | uniq -c | tr '\n' ';')"
  fi
}
flood passwords 30 "$work/flood-passwords" &
sleep 3
steady "$work/steady-passwords" &
sleep 5
newcomer newcomer1 "during a flood of wrong passwords"
wait
steady_result "during a flood of wrong passwords" "$work/steady-passwords"
if grep -qE ' 407=[0-9]+' "$work/flood-passwords" && ! grep -q ' 200=' "$work/flood-passwords"; then
  pass "every flooded password was refused with 407 ($(cat "$work/flood-passwords"))"
else
  fail "the password flood: $(cat "$work/flood-passwords")"
fi
flood hosts 30 "$work/flood-hosts" &
sleep 3
steady "$work/steady-hosts" &
sleep 5
newcomer newcomer2 "during a flood of names on no list"
wait
steady_result "during a flood of names on no list" "$work/steady-hosts"
flooded_lookups=$(labdns_count '.flood.test')
if ! grep -q ' 200=' "$work/flood-hosts" && grep -qE ' 403=[0-9]+' "$work/flood-hosts" && [ "$flooded_lookups" = 0 ]; then
  pass "no flooded name got a tunnel or a DNS lookup ($(cat "$work/flood-hosts"))"
else
  fail "the host flood: $(cat "$work/flood-hosts"); DNS lookups of flooded names: $flooded_lookups"
fi

if [ "$(docker inspect -f '{{.State.StartedAt}} {{.RestartCount}}' "$proxy")" = "$proxy_started" ] \
  && ! logged "$proxy" 'Reconfiguring' && ! logged "$proxy" 'FATAL'; then
  pass "Squid ran through the policy changes and both floods without a restart or reconfiguration"
else
  fail "Squid restarted, reconfigured or stopped during the lab: $(docker logs "$proxy" 2>&1 | grep -E 'FATAL|Reconfigur' | tail -n 3)"
fi

if [ "$overload" = 1 ]; then
  echo "# 10. a password-check queue overloaded for more than 3 minutes (one slow checker, a queue of one)"
  if compose up -d --wait --wait-timeout 120 egress-overload egress-overload-die > "$work/up.log" 2>&1; then
    PROXY_HOST=egress-overload flood passwords 210 "$work/flood-overload" &
    PROXY_HOST=egress-overload-die flood passwords 210 "$work/flood-overload-die" &
    sleep 195
    issue_password newcomer3
    started=$(date +%s.%N)
    answer=$(PROXY_HOST=egress-overload probe plugin-a newcomer3 newcomer3 connect geocoding-api.open-meteo.com:443)
    took=$(python3 -c "import sys; print(f'{float(sys.argv[2]) - float(sys.argv[1]):.1f}')" "$started" "$(date +%s.%N)")
    wait
    if [ "$(docker inspect -f '{{.RestartCount}}' "$lab_name-overload")" = 0 ] \
      && logged "$lab_name-overload" 'dropping requests to overloaded' && ! logged "$lab_name-overload" 'FATAL'; then
      pass "with on-persistent-overload=ERR, Squid keeps running and drops the checks it cannot queue"
    else
      fail "ERR: $(docker logs "$lab_name-overload" 2>&1 | grep -E 'FATAL|dropping|overload' | tail -n 3)"
    fi
    # Informational: such a request waits in the queue, or gets 407 at once when it overflows.
    echo "# during that overload, a new user's first request got '$answer' after $took s"
    if [ "$(docker inspect -f '{{.RestartCount}}' "$lab_name-overload-die")" -ge 1 ] \
      || logged "$lab_name-overload-die" 'Too many queued'; then
      pass "control, with Squid's default (die): the same overload stops Squid ($(docker logs "$lab_name-overload-die" 2>&1 | grep -m1 -o 'FATAL: Too many queued [a-z_]* requests'))"
    else
      fail "control: Squid with die did not stop: $(cat "$work/flood-overload-die")"
    fi
  else
    fail "the overload instances did not start: $(tail -n 5 "$work/up.log")"
  fi
else
  echo "# sustained overload skipped (run with --overload)"
fi

echo "# 6. no credential in any log"
# Every password and its Basic token, in a file only this user reads, never on a command line.
patterns="$work/patterns"
: > "$patterns"
chmod 0600 "$patterns"
for password_file in "$work"/password-*; do
  user=${password_file##*-}
  password=$(cat "$password_file")
  if [ -z "$password" ]; then continue; fi
  printf '%s\n%s\n' "$password" "$(printf '%s:%s' "$user" "$password" | base64)" >> "$patterns"
done
log_containers=("$proxy" "$lab_name-plain" "$lab_name-race" "$lab_name-queue" "$(compose ps -q writer)")
if [ "$overload" = 1 ]; then
  log_containers+=("$lab_name-overload" "$lab_name-overload-die")
fi
for container in "${log_containers[@]}"; do
  docker logs "$container" > "$work/log" 2>&1
  leaks=$(grep -cF -f "$patterns" "$work/log" || true)
  headers=$(grep -ci 'proxy-authorization' "$work/log" || true)
  name=$(docker inspect -f '{{.Name}}' "$container")
  if [ "$leaks" = 0 ] && [ "$headers" = 0 ]; then
    pass "${name#/}: no password, Basic token or Proxy-Authorization header in its log"
  else
    fail "${name#/}: $leaks password or token occurrence(s), $headers Proxy-Authorization line(s)"
  fi
done
if logged "$proxy" ' user=a TCP_TUNNEL/200 CONNECT geocoding-api.open-meteo.com:443 ' && logged "$proxy" 'err=ERR_HOST_NOT_ALLOWED'; then
  pass "the access log names the plugin and the refusal"
else
  fail "the access log lacks user=a or a refusal name"
fi

echo "# the container"
# The race instance's firewall was flushed on purpose above.
for container in "$proxy" "$lab_name-plain"; do
  check_ipv6=$(docker exec "$container" cat /proc/sys/net/ipv6/conf/all/disable_ipv6)
  rules=$(docker exec "$container" iptables -S EGRESS_PRIVATE)
  missing=""
  while read -r range; do
    case "$rules" in *"-A EGRESS_PRIVATE -d $range -j REJECT"*) ;; *) missing="$missing $range" ;; esac
  done < <(grep -v ':' "$lab_dir/../private_ranges.txt")
  if [ "$check_ipv6" = 1 ] && [ -z "$missing" ] && docker exec "$container" iptables -C OUTPUT -j EGRESS_PRIVATE; then
    pass "$container: IPv6 off, OUTPUT jumps to EGRESS_PRIVATE, which refuses every IPv4 range"
  else
    fail "$container: disable_ipv6=$check_ipv6, missing ranges:$missing"
  fi
done
for container in "$proxy" "$lab_name-plain" "$lab_name-race"; do
  # Squid is PID 1 and its helpers are its children; a `docker exec` process has neither parent.
  held=$(docker exec "$container" python3 -I -c '
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
')
  case "$held" in
    *"basic_ncsa_auth"*"plugin_host_acl"*"squid"*"| none") pass "$container: no NET_ADMIN in any set of $(echo "$held" | cut -d'|' -f1)" ;;
    *) fail "$container: $held" ;;
  esac
done
guard() { # description, expected log text, then docker run options
  local description=$1 expected=$2 output
  shift 2
  output=$(docker run --rm --network none --read-only --tmpfs /run:mode=0755 --cap-drop ALL "$@" "$lab_name-proxy:local" 2>&1 || true)
  case "$output" in
    *"$expected"*) pass "$description" ;;
    *) fail "$description: $output" ;;
  esac
}
guard "without SETPCAP the entrypoint refuses to start Squid" "refusing to start" \
  --cap-add NET_ADMIN --cap-add CHOWN --cap-add SETUID --cap-add SETGID \
  --sysctl net.ipv6.conf.all.disable_ipv6=1 --sysctl net.ipv6.conf.default.disable_ipv6=1
guard "with IPv6 on the entrypoint refuses to start" "IPv6 is on in this container" \
  --cap-add NET_ADMIN --cap-add SETPCAP --cap-add CHOWN --cap-add SETUID --cap-add SETGID \
  --sysctl net.ipv6.conf.all.disable_ipv6=0
all_capabilities=(--cap-add NET_ADMIN --cap-add SETPCAP --cap-add CHOWN --cap-add SETUID --cap-add SETGID
  --sysctl net.ipv6.conf.all.disable_ipv6=1 --sysctl net.ipv6.conf.default.disable_ipv6=1)
grep ':' "$lab_dir/../private_ranges.txt" > "$work/ranges-ipv6-only.txt"
grep -v ':' "$lab_dir/../private_ranges.txt" > "$work/ranges-ipv4-only.txt"
guard "with no IPv4 range the entrypoint refuses to start" "lists no IPv4 range; refusing to start" \
  "${all_capabilities[@]}" -v "$work/ranges-ipv6-only.txt:/etc/squid/private_ranges.txt:ro"
docker run -d --name "$lab_name-guard" --network none --read-only --tmpfs /run:mode=0755 --cap-drop ALL \
  "${all_capabilities[@]}" -v "$work/ranges-ipv4-only.txt:/etc/squid/private_ranges.txt:ro" "$lab_name-proxy:local" > /dev/null
if wait_for 30 logged "$lab_name-guard" "waiting for the plugin node's policy files" \
  && logged "$lab_name-guard" 'lists no IPv6 range: no IPv6 rules installed' \
  && logged "$lab_name-guard" 'egress firewall installed'; then
  pass "with no IPv6 range the entrypoint installs the IPv4 firewall and goes on"
else
  fail "with no IPv6 range: $(docker logs "$lab_name-guard" 2>&1 | tail -n 3)"
fi
docker rm -f "$lab_name-guard" > /dev/null
echo "# $(docker run --rm --entrypoint squid "$lab_name-proxy:local" -v | sed -n 1p)"

if [ "$failures" -ne 0 ]; then
  echo "FAILED: $failures check(s)"
  docker logs "$proxy" 2>&1 | tail -n 20
  exit 1
fi
echo "All egress lab checks passed."
