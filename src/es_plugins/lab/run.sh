#!/usr/bin/env bash
# The plugin node lab. Runs the es_plugins service exactly as src/docker-compose.yaml defines it
# (capabilities, read-only root, tmpfs modes, no-new-privileges, plugins-network only) against a
# stand-in for django_app's node API, installs two probe plugins packed with real wheels (and
# refuses a third, hostile one), and checks from inside them what a plugin process can and cannot
# do. Then it backs up and restores a plugin database on the lab's plugins_db, as the node does
# during an upgrade. One `ok -` / `not ok -` line per check. Every run has a Compose project and
# container and image names of its own, so runs never collide; it removes every container,
# volume, network and image it made.
#
# Needs Docker, network access (the packer downloads the probe plugins' wheels), and python3 with
# PyYAML (scripts/envtool.py writes the env file the extended service needs).
# Usage, from anywhere: bash src/es_plugins/lab/run.sh
set -euo pipefail

lab_dir=$(cd "$(dirname "$0")" && pwd)
repository=$(cd "$lab_dir/../../.." && pwd)
work=$(mktemp -d)
run_id=$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')
run_name="es-plugins-lab-$run_id"
node="$run_name-node"
database="$run_name-db"
export ES_PLUGINS_LAB_RUN=$run_id ES_PLUGINS_LAB_NODE=$node ES_PLUGINS_LAB_DATABASE=$database

python3 "$repository/scripts/envtool.py" --dev --env-file "$work/lab.env" > /dev/null
# The shell's values win over the env file's: the node talks to the lab's control service.
# A small disk cap, so the lab can write past it quickly.
export IMAGE_TAG=lab ES_PLUGINS_CPUS=2 ES_PLUGINS_MEMORY=2g PLUGINS_NODE_NAME=lab-node \
  PLUGINS_NODE_UID_RANGE=20000-20999 PLUGINS_INTERNAL_API_URL=http://control:8000/api/ \
  ES_PLUGINS_DISK_MB_PER_PLUGIN=64 ES_PLUGINS_FILES_PER_PLUGIN=5000 PLUGINS_MAX_DB_CONNECTIONS=20
PLUGINS_NODE_KEY="lab-$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')"
random_password() { od -An -N32 -tx1 /dev/urandom | tr -d ' \n'; }
PLUGINS_DB_SUPERUSER_PASSWORD=$(random_password)
PLUGINS_DB_ADMIN_PASSWORD=$(random_password)
PLUGINS_DB_BACKUP_PASSWORD=$(random_password)
export PLUGINS_NODE_KEY PLUGINS_DB_SUPERUSER_PASSWORD PLUGINS_DB_ADMIN_PASSWORD PLUGINS_DB_BACKUP_PASSWORD
export PLUGINS_DB_MAX_CONNECTIONS=100

compose() {
  docker compose -p "$run_name" -f "$lab_dir/compose.yaml" --env-file "$work/lab.env" \
    --profile plugins --profile pack "$@"
}
cleanup() {
  compose down -v --rmi all --remove-orphans > /dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT
compose down -v --rmi all --remove-orphans > /dev/null 2>&1 || true

failures=0
pass() { echo "ok - $1"; }
fail() {
  echo "not ok - $1"
  failures=$((failures + 1))
}
check() { # description, then a command that succeeds when the check holds
  local description=$1
  shift
  if "$@" > "$work/check-output" 2>&1; then
    pass "$description"
  else
    fail "$description: $(head -c 400 "$work/check-output")"
  fi
}

in_tools() { compose exec -T tools "$@"; }
as_root() { docker exec "$node" "$@"; }
report() { in_tools curl -s http://control:8000/lab/reports; }
placement() { # placement id, jq expression on that placement's report
  report | jq -r --argjson id "$1" ".placements[] | select(.placement_id == \$id) | $2"
}
# call PLUGIN PORT PATH [QUERY]: a request with a context the control service signed for it.
call() {
  local token
  token=$(in_tools curl -s "http://control:8000/lab/context?plugin=$1&path=$3")
  # A failed call leaves its output empty; the check that reads it reports the failure.
  in_tools curl -s --max-time 30 -H "X-EpicStaff-Plugin-Context: $token" "http://es_plugins:$2$3${4:+?$4}" || true
}
change() { # placement id, JSON object of changes
  in_tools curl -s -o /dev/null -X POST -H 'Content-Type: application/json' \
    --data "$2" "http://control:8000/lab/placements/$1"
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
running() { [ "$(placement "$1" '.observed_state + " " + .health')" = "running ok" ]; }
field_is() { [ "$(placement "$1" "$2")" = "$3" ]; } # placement id, jq field, expected value
restarted() { [ "$(placement "$1" .restarts)" -ge 1 ]; }
contains() { case "$1" in *"$2"*) return 0 ;; esac; return 1; }

echo "# build, pack the probe plugins, start the node"
compose build --quiet
compose run --rm packer
compose up -d control plugins_db es_plugins tools > /dev/null 2>&1
if wait_for 300 running 1 && wait_for 60 running 2; then
  pass "both probe plugins are installed from their packages and run healthy"
else
  fail "the probe plugins did not start: $(report | head -c 600)"
  docker logs "$node" 2>&1 | tail -n 40
  exit 1
fi
wheel_architectures=$(compose exec -T control python -c "
import zipfile
names = [name for name in zipfile.ZipFile('/packages/probe-b.esplugin').namelist() if name.startswith('backend/wheels/')]
print(' '.join(architecture for architecture in ('aarch64', 'x86_64') if any(architecture in name for name in names)))
")
check "probe-b's package carries wheels for both aarch64 and x86_64, and the node installed the ones that fit it" \
  test "$wheel_architectures" = "aarch64 x86_64"

echo "# the container and the two privileged processes"

inspected=$(docker inspect "$node" --format \
  '{{.HostConfig.Privileged}} {{.HostConfig.CapAdd}} {{.HostConfig.CapDrop}} {{.HostConfig.ReadonlyRootfs}} {{.HostConfig.SecurityOpt}} {{.HostConfig.UsernsMode}}|')
check "the container has SETUID SETGID CHOWN, and NET_ADMIN BPF SETPCAP for its entrypoint only, a read-only root and no-new-privileges ($inspected)" \
  test "$inspected" = "false [CAP_BPF CAP_CHOWN CAP_NET_ADMIN CAP_SETGID CAP_SETPCAP CAP_SETUID] [ALL] true [no-new-privileges:true] |"
launcher_status=$(as_root grep -E '^(Uid|CapInh|CapPrm|CapEff|CapBnd|CapAmb):' /proc/1/status | tr -s '\t' ' ' | tr '\n' ' ')
check "the launcher (PID 1) is root with exactly SETUID SETGID CHOWN in every set: the entrypoint dropped the rest" \
  test "$launcher_status" = "Uid: 0 0 0 0 CapInh: 0000000000000000 CapPrm: 00000000000000c1 CapEff: 00000000000000c1 CapBnd: 00000000000000c1 CapAmb: 0000000000000000 "
agent_status=$(as_root python -c "
import os
for pid in filter(str.isdigit, os.listdir('/proc')):
    fields = dict(line.split(':', 1) for line in open(f'/proc/{pid}/status') if ':' in line)
    if fields['Uid'].split()[0] == '10000' and 'es_plugins.agent' in open(f'/proc/{pid}/cmdline').read():
        print(fields['Uid'].split(), fields['CapEff'].strip(), fields['NoNewPrivs'].strip())
" | head -n 1)
check "the agent runs as UID 10000 without capabilities" \
  test "$agent_status" = "['10000', '10000', '10000', '10000'] 0000000000000000 1"
check "the container reports healthy (the agent's heartbeat)" \
  wait_for 90 sh -c "[ \"\$(docker inspect $node --format '{{.State.Health.Status}}')\" = healthy ]"

echo "# a plugin process"

call probe-a 20001 /api/info > "$work/a.json"
call probe-b 20002 /api/info > "$work/b.json"
check "probe-a runs as 20001:20001 without groups, capabilities or new privileges" jq -e '
  .identity == {"Uid": ["20001","20001","20001","20001"], "Gid": ["20001","20001","20001","20001"], "Groups": []}
  and .capabilities.CapEff == "0000000000000000" and .capabilities.CapPrm == "0000000000000000"
  and .capabilities.CapAmb == "0000000000000000" and .no_new_privs == "1"' "$work/a.json"
check "its limits: NPROC 64, NOFILE 256, no core dumps, oom_score_adj 800, its own session" jq -e '
  .rlimit_nproc == [64,64] and .rlimit_nofile == [256,256] and .rlimit_core == [0,0]
  and .oom_score_adj == 800 and .pid == .sid and .pid == .pgid' "$work/a.json"
check "cpu_priority normal is nice 0, low is nice 10" \
  test "$(jq .nice "$work/a.json") $(jq .nice "$work/b.json")" = "0 10"
check "its environment is exactly the documented one (docs/plugins/reference/runtime.md), USER and LOGNAME its identifier" jq -e '
  (.environment | keys) == ["EPICSTAFF_API_URL","EPICSTAFF_PLUGIN_ENTRYPOINT","EPICSTAFF_PLUGIN_IDENTIFIER",
    "EPICSTAFF_PLUGIN_LISTEN_FD","EPICSTAFF_PLUGIN_PUBLIC_URL","EPICSTAFF_PLUGIN_RUNTIME_FILE",
    "EPICSTAFF_PLUGIN_VERSION","EPICSTAFF_PUBLIC_URL","HOME","HTTPS_PROXY","HTTP_PROXY","LANG","LOGNAME",
    "NO_PROXY","PATH","PORT","PYTHONUNBUFFERED","TMPDIR","USER","http_proxy","https_proxy","no_proxy"]
  and .environment.EPICSTAFF_PLUGIN_LISTEN_FD == "3" and .environment.USER == "probe-a" and .environment.LOGNAME == "probe-a" and .user == "probe-a"
  and (.passwd_entry | startswith("DENIED KeyError"))' "$work/a.json"
check "HOME and TMPDIR are 0700 its own; it can write only there" jq -e '
  .home_mode == "drwx------ 20001:20001" and .tmpdir_mode == "drwx------ 20001:20001"
  and (.write_tmpdir | startswith("OK")) and (.write_tmp | startswith("DENIED"))
  and (.write_rootfs | startswith("DENIED")) and (.write_own_code | startswith("DENIED"))' "$work/a.json"
check "no POSIX shared memory: /dev/shm is not writable, so neither shared_memory nor a multiprocessing lock works" jq -e '
  (.write_dev_shm | startswith("DENIED")) and (.posix_shared_memory | startswith("DENIED"))
  and (.multiprocessing_lock | startswith("DENIED"))' "$work/a.json"
check "its runtime file is 0400 its own, with its settings" jq -e '
  .runtime_file_mode == "-r-------- 20001:20001" and .runtime_settings.credentials_revision == "00000000"' \
  "$work/a.json"
in_tools curl -s -o /dev/null -w '%{http_code}' http://es_plugins:20001/api/info > "$work/status"
check "without a gateway context the plugin answers 401" test "$(cat "$work/status")" = 401
in_tools curl -s -o /dev/null -w '%{http_code}' http://es_plugins:20001/_epicstaff/health > "$work/status"
check "its health endpoint answers without a context" test "$(cat "$work/status")" = 200

echo "# outbound access: the egress policy the agent writes"

policy=/var/lib/es_plugins_egress/policy
check "the egress policy volume is 0755 10000:10000 below a 0710 root:10000 directory; its files 0644 10000:10000" \
  test "$(as_root stat -c '%a %u:%g' /var/lib/es_plugins_egress $policy $policy/passwords $policy/hosts.json | tr '\n' ' ')" \
  = "710 0:10000 755 10000:10000 644 10000:10000 644 10000:10000 "
check "a plugin UID cannot pass through /var/lib/es_plugins_egress" \
  sh -c "! docker exec --user 20001:20001 $node cat $policy/hosts.json 2> '$work/denied' && grep -q 'Permission denied' '$work/denied'"
check "hosts.json lists every placement of the desired state with its hosts, in manifest order" \
  test "$(as_root cat $policy/hosts.json | jq -c .)" \
  = '{"probe-a":["geocoding-api.open-meteo.com","*.wikipedia.org"],"probe-b":[],"probe-evil":[]}'
check "the password file holds a bcrypt hash for each running probe and none for the refused package" \
  test "$(as_root sh -c "cut -d: -f1 $policy/passwords | tr '\n' ' '; cut -d: -f2 $policy/passwords | cut -c1-7 | sort -u")" \
  = 'probe-a probe-b $2b$04$'
proxy_matches() { # the probe's info file: its proxy URL names it, and its password verifies
  jq -r .environment.HTTPS_PROXY "$1" | docker exec -i "$node" python -c "
import sys, bcrypt
url = sys.stdin.read().strip()
user, _, rest = url.removeprefix('http://').partition(':')
password, _, address = rest.partition('@')
hashes = dict(line.split(':', 1) for line in open('$policy/passwords').read().splitlines())
sys.exit(not (user == sys.argv[1] and address == 'plugins_egress:3128' and len(password) >= 32
              and bcrypt.checkpw(password.encode(), hashes[user].encode())))
" "$2"
}
both_probes_have_their_own_proxy_credentials() {
  proxy_matches "$work/a.json" probe-a && proxy_matches "$work/b.json" probe-b
}
check "each probe's proxy variables carry its own credentials, which the policy verifies" \
  both_probes_have_their_own_proxy_credentials
check "NO_PROXY keeps the API host and loopback direct" \
  test "$(jq -r '.environment.NO_PROXY + " " + .environment.no_proxy' "$work/a.json")" \
  = "control,localhost,127.0.0.1,::1 control,localhost,127.0.0.1,::1"

echo "# probe-a against probe-b"

call probe-a 20001 /api/probe "target=probe-b&target_uid=20002" > "$work/probe.json"
check "probe-a cannot read, signal, ptrace or impersonate probe-b, nor reach the agent or launcher" jq -e '
  [to_entries[] | select(.key | test("^(target_pid|CONTROL_|SEEN_)") | not) | select(.value | startswith("OK"))]
  | length == 0' "$work/probe.json"
check "its positive controls pass (own runtime file, ptrace of its own child)" jq -e '
  (.CONTROL_read_own_runtime_file | startswith("OK")) and (.CONTROL_ptrace_own_child | startswith("OK"))
  and .target_pid > 0' "$work/probe.json"
jq -r 'to_entries[] | "    \(.key): \(.value)"' "$work/probe.json" | cut -c1-150

echo "# hooks: the node claims a job, calls the plugin on loopback, reports the result"

lab_job() { in_tools curl -s http://control:8000/lab/hook-jobs | jq -c --arg id "$1" '.[$id]'; }
job_state_is() { [ "$(lab_job "$1" | jq -r .state)" = "$2" ]; }
add_job() { # placement id, job id, organization id
  in_tools curl -s -o /dev/null -X POST -H 'Content-Type: application/json' \
    --data "{\"placement_id\": $1, \"job_id\": $2, \"organization_id\": $3}" \
    http://control:8000/lab/hook-jobs
}
a_pid=$(placement 1 .pid)
add_job 1 41 7
if wait_for 60 job_state_is 41 succeeded; then
  check "an install hook reaches probe-a, passes the SDK's assertion check and succeeds, claimed once ($(lab_job 41 | jq -c .result))" \
    jq -e '.result.http_status == 200 and .result.attempt == 1 and .claims == 1' <<< "$(lab_job 41)"
  # As probe-a's UID: its HOME is 0700, and root here has no CAP_DAC_OVERRIDE.
  check "the plugin's handler ran for the job's organization" \
    test "$(docker exec --user 20001:20001 "$node" cat /var/lib/es_plugins/data/probe-a/install-hook-41.json)" \
    = '{"organization": 7, "attempt": 1}'
else
  fail "the install hook of job 41: $(lab_job 41)"
fi
# The runtime file holds a key for organization 7 only: job 42's hook waits until it holds one
# for 8, which comes with the next credentials revision.
add_job 1 42 8
sleep 12
check "a hook waits while the runtime file has no key for its organization (no claim in 12 s)" \
  test "$(lab_job 42 | jq .claims)" = 0
in_tools curl -s -o /dev/null -X POST -H 'Content-Type: application/json' --data '[7, 8]' \
  http://control:8000/lab/service-accounts/1
change 1 "{\"credentials_revision\": \"$(printf '2%.0s' $(seq 64))\"}"
if wait_for 60 job_state_is 42 failed; then
  check "with the key written, the hook runs, and the plugin's failure comes back with its message ($(lab_job 42 | jq -c .result))" \
    jq -e '.result.http_status == 500 and .result.error == "the probe refuses organization 8" and .claims == 1' <<< "$(lab_job 42)"
else
  fail "the install hook of job 42: $(lab_job 42)"
fi
check "probe-a ran both hooks without a restart (same pid)" test "$(placement 1 .pid)" = "$a_pid"
service_account_key="esp-$(printf 'lab%.0s' $(seq 14))k"
check "no hook assertion and no service-account key reaches the node's log" \
  sh -c "! docker logs $node 2>&1 | grep -q -e '$service_account_key' -e 'eyJ'"

echo "# limits"

call probe-a 20001 /api/forkbomb > "$work/bomb.json" &
bomb=$!
sleep 1
call probe-b 20002 /api/info > "$work/b-during.json"
wait "$bomb"
check "a fork bomb in probe-a stops at RLIMIT_NPROC (64) while probe-b keeps working" jq -e \
  --slurpfile other "$work/b-during.json" \
  '.processes_at_peak <= 64 and (.stopped_by | test("Resource temporarily unavailable")) and ($other[0].pid > 0)' \
  "$work/bomb.json"
jq -c . "$work/bomb.json"

b_pid=$(jq .pid "$work/b.json")
call probe-a 20001 /api/hog "mb=320" > /dev/null
if wait_for 60 restarted 1 && wait_for 60 running 1; then
  pass "probe-a above its 128 MB cap is killed by UID and restarted: $(placement 1 .last_error)"
else
  fail "the memory cap: $(placement 1 '[.observed_state, .restarts, .rss_mb, .last_error] | tostring')"
fi
check "probe-b was not touched (same pid)" test "$(placement 2 .pid)" = "$b_pid"

echo "# ports: the agent holds every port of the node's range"

# 20002 is probe-b's, 20001 probe-a's own, 20003 the hostile package's (whose install failed),
# 20500 and 20999 are assigned to no placement; 0 is any free port, 30000 one outside the range.
bind_ports="20002 20001 20003 20500 20999 0 30000"
for port in $bind_ports; do
  call probe-a 20001 /api/bind "port=$port" > "$work/bind-$port.json"
done
check "probe-a can bind no inet socket: no port of the range, its own, another plugin's, a free one, any port (0) or one outside the range, listening or only bound, on 0.0.0.0 or 127.0.0.1, with or without SO_REUSEADDR/SO_REUSEPORT (EPERM)" \
  sh -c "for port in $bind_ports; do jq -e 'length == 8 and all(.[]; startswith(\"DENIED\") and contains(\"Operation not permitted\"))' \"$work/bind-\$port.json\" > /dev/null || exit 1; done"
check "probe-a still serves: on the socket the agent holds and hands it as fd 3" running 1

echo "# connection limits: each plugin UID's open connections and new ones a second"

check "the entrypoint set the limits before the launcher started" \
  sh -c "docker logs $node 2>&1 | grep -q 'plugins.node.connection_limits uids=20000-20999 database=20 proxy=64 tcp=512 new_per_second=200 bind=refused'"
# The agent's UID, from the node's own interpreter: opens `count` connections and holds them.
as_agent_connect() { # host, port, count, then hold or churn
  docker exec --user 10000:10000 "$node" python -c "
import socket, sys, time
host, port, count, mode = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
held, opened = [], 0
for _ in range(count):
    connection = socket.socket()
    connection.settimeout(3)
    try:
        connection.connect((host, port))
        opened += 1
        held.append(connection) if mode == 'hold' else connection.close()
    except OSError:
        connection.close()
print(opened)
" "$@"
}
compose exec -d -T tools python -u /lab/holder.py
holder_listens() { in_tools python -c "import socket; socket.create_connection(('127.0.0.1', 5432), 2).close()"; }
if wait_for 30 holder_listens; then
  # Connections to "plugins_db" (5432) that never authenticate, held for 30 s.
  call probe-a 20001 /api/connect "host=tools&port=5432&count=30&hold=30" > "$work/flood-db.json"
  call probe-b 20002 /api/connect "host=tools&port=5432&count=5&hold=5" > "$work/other-db.json"
  agent_opened=$(as_agent_connect tools 5432 30 hold)
  check "probe-a holding 30 connections to port 5432 gets exactly PLUGINS_MAX_DB_CONNECTIONS (20): $(jq -c . "$work/flood-db.json")" \
    jq -e '.opened == 20 and .refused == 10' "$work/flood-db.json"
  check "... while probe-b still gets its own 5" jq -e '.opened == 5' "$work/other-db.json"
  check "... and the agent's UID all 30 ($agent_opened)" test "$agent_opened" = 30
  call probe-a 20001 /api/connect "host=tools&port=3128&count=70&hold=5" > "$work/flood-proxy.json"
  check "probe-a gets at most 64 connections to the egress proxy's port: $(jq -c . "$work/flood-proxy.json")" \
    jq -e '.opened == 64 and .refused == 6' "$work/flood-proxy.json"
  call probe-a 20001 /api/churn "host=tools&port=8080&count=3000" > "$work/churn.json"
  call probe-b 20002 /api/churn "host=tools&port=8080&count=50" > "$work/churn-other.json"
  agent_churned=$(as_agent_connect tools 8080 1000 churn)
  check "probe-a opening 3000 short connections at once is cut to about 200 a second: $(jq -c . "$work/churn.json")" \
    jq -e '.refused > 0 and .opened < 1500' "$work/churn.json"
  check "... while probe-b still opens all of its 50" jq -e '.opened == 50' "$work/churn-other.json"
  check "... and the agent's UID all 1000 ($agent_churned)" test "$agent_churned" = 1000
  echo "# $(as_root nft list table inet es_plugins_limits | grep -o 'counter packets [0-9]*' | tr '\n' ' ')"
else
  fail "the lab's connection holder did not start"
fi

echo "# disk: a 64 MB cap per plugin, measured every 30 s"

b_pid=$(placement 2 .pid)
call probe-a 20001 /api/fill "mb=100" > "$work/fill.json"
if wait_for 90 field_is 1 .observed_state failed; then
  disk_error=$(placement 1 .last_error)
  # The measurement may catch the write half done: any size past the cap.
  check "probe-a, past its disk cap, is stopped and marked failed ($disk_error)" \
    contains "$disk_error" "MB of disk, more than its limit of 64 MB"
  check "no process of probe-a is left" test "$(placement 1 .pid)" = null
  only_probe_b_has_a_password() { [ "$(as_root cut -d: -f1 $policy/passwords | tr '\n' ' ')" = "probe-b " ]; }
  check "a plugin stopped for good loses its proxy password (only probe-b's is left)" \
    wait_for 10 only_probe_b_has_a_password
  a_restarts=$(placement 1 .restarts)
  sleep 40
  check "it is not restarted (still failed, no new restart after a measurement and more)" \
    test "$(placement 1 '.observed_state + " " + (.restarts | tostring)')" = "failed $a_restarts"
  check "probe-b was not touched (same pid)" test "$(placement 2 .pid)" = "$b_pid"
  change 1 '{"restart_generation": 1}'
  if wait_for 60 field_is 1 .applied_restart_generation 1 && wait_for 90 field_is 1 .observed_state failed; then
    check "restarted with its files still there, it is stopped again at the next measurement" \
      test "$(placement 1 .last_error)" = "uses 100 MB of disk, more than its limit of 64 MB"
  else
    fail "probe-a after a restart over its disk cap: $(placement 1 '[.observed_state, .last_error] | tostring')"
  fi
else
  fail "the disk cap: $(placement 1 '[.observed_state, .restarts, .last_error] | tostring') $(cat "$work/fill.json")"
fi

echo "# kill by UID, runtime file rewrite, purge"

call probe-b 20002 /api/daemons "count=3" > "$work/daemons.json"
daemons=$(jq -r '.started | join(" ")' "$work/daemons.json")
change 2 '{"restart_generation": 1}'
if wait_for 60 field_is 2 .applied_restart_generation 1 && wait_for 60 running 2; then
  left=""
  for pid in $daemons; do
    if as_root test -d "/proc/$pid"; then left="$left $pid"; fi
  done
  call probe-b 20002 /api/info > "$work/b-after.json"
  check "a restart kills every process of the UID, also daemons that left the session ($daemons)" \
    sh -c "[ -z '$left' ] && [ \"\$(jq '.processes_of_my_uid | length' '$work/b-after.json')\" = 1 ]"
else
  fail "probe-b was not restarted for restart_generation 1"
fi

b_pid=$(placement 2 .pid)
new_revision=$(printf '1%.0s' $(seq 64))
change 2 "{\"credentials_revision\": \"$new_revision\"}"
if wait_for 60 field_is 2 .applied_credentials_revision "$new_revision"; then
  call probe-b 20002 /api/info > "$work/b-rotated.json"
  check "a new credentials_revision rewrites the runtime file without a restart" \
    sh -c "[ \"\$(jq -r .runtime_settings.credentials_revision '$work/b-rotated.json')\" = 11111111 ] && [ \"\$(jq .pid '$work/b-rotated.json')\" = '$b_pid' ]"
else
  fail "the runtime file was not rewritten for the new credentials_revision"
fi

refusal=$(as_root python -c "
import socket
client = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
client.connect('/run/es_launcher/launcher.sock')
try:
    client.send(b'{\"operation\": \"kill_uid\", \"uid\": 20002}')
    print(repr(client.recv(4096)))
except OSError as error:
    print(type(error).__name__)
")
check "the launcher answers no peer but the agent, not even root ($refusal)" \
  sh -c "[ '$refusal' = \"b''\" ] || [ '$refusal' = ConnectionResetError ] || [ '$refusal' = BrokenPipeError ]"
check "the launcher logged the refused peer" sh -c "docker logs $node 2>&1 | grep -q 'Refused a launcher connection from UID 0'"

change 2 '{"desired_state": "stopped"}'
if wait_for 60 field_is 2 .observed_state stopped; then
  # As the agent's UID and GID: the launcher's socket directory is root:10000, mode 0750.
  docker exec --user 10000:10000 "$node" python -c "
import asyncio
from es_plugins.agent.launcher_client import LauncherClient
async def purge():
    client = LauncherClient(__import__('pathlib').Path('/run/es_launcher/launcher.sock'))
    await client.connect()
    await client.purge_data('probe-b', 20002)
asyncio.run(purge())
" > "$work/purge.out" 2>&1 || true
  check "purging probe-b's data (as its UID, through the launcher) removes its HOME, keeps its code" \
    sh -c "! docker exec $node test -e /var/lib/es_plugins/data/probe-b && docker exec $node test -d /var/lib/es_plugins/plugins/probe-b"
  if [ -s "$work/purge.out" ]; then sed 's/^/    /' "$work/purge.out"; fi
else
  fail "probe-b did not stop for desired_state stopped"
fi

echo "# a hostile package"

if wait_for 120 field_is 3 .observed_state failed; then
  evil_error=$(placement 3 .last_error)
  check "a package whose wheel replaces the venv's python is refused at install ($evil_error)" \
    contains "$evil_error" "is not a symlink"
  markers=$(as_root find /var/lib/es_plugins /run /dev/shm \( -name 'pth-ran-as-*' -o -name 'replaced-python-ran-as-*' \) -print 2> /dev/null || true)
  check "neither its .pth file nor its replacement python ever ran, as the agent or anyone ($markers)" test -z "$markers"
  check "no process was started for it" test "$(placement 3 .pid)" = null
else
  fail "the hostile package: $(placement 3 '[.observed_state, .last_error] | tostring')"
fi

echo "# reports and logs"

reported=$(report | jq -r '[.agent_version, (.placements | length)] | map(tostring) | join(" ")')
check "the node reports its agent version and all three placements ($reported)" test "$reported" = "0.1.0 3"
check "plugin output reaches the node's log, prefixed with the plugin" \
  sh -c "docker logs $node 2>&1 | grep -q '^\[probe-a\] '"
# Searched for with -F -f, so no secret is on a command line of its own.
printf '%s\n' "$PLUGINS_NODE_KEY" "$PLUGINS_DB_ADMIN_PASSWORD" "$PLUGINS_DB_BACKUP_PASSWORD" > "$work/node-secrets"
{ cat "$work/node-secrets"; echo secret-token; } > "$work/all-secrets"
chmod 600 "$work/node-secrets" "$work/all-secrets"
check "no secret is in any process's command line" \
  sh -c "! docker exec $node sh -c 'cat /proc/[0-9]*/cmdline' | tr '\0' ' ' | grep -q -F -f '$work/all-secrets'"
check "no plugin process gets the node key or a database password" \
  sh -c "! grep -q -F -f '$work/node-secrets' '$work/a.json' '$work/b.json'"
check "no proxy password and no policy path reaches the node's log" \
  sh -c "! docker logs $node 2>&1 | grep -q -e 'plugins_egress:3128' -e '\$2b\$'"

echo "# removal: nothing of probe-b is left, and its UID and port are free"

processes_of() { as_root sh -c "stat -c %u /proc/[0-9]* 2> /dev/null | grep -c '^$1\$'" || true; }
ipc_objects_of() { as_root python -c "from es_plugins.launcher.ipc_cleanup import ipc_objects_of; print(len(ipc_objects_of($1)))"; }
removal_state() { report | jq -r ".removals[] | select(.placement_id == $1) | .state"; }
removed() { [ "$(removal_state 2)" = removed ]; }
change 2 '{"desired_state": "running"}'
if wait_for 90 running 2; then
  call probe-b 20002 /api/traces > "$work/traces.json"
  check "a plugin cannot create a POSIX message queue (RLIMIT_MSGQUEUE 0, EMFILE): $(jq -c .mq_open "$work/traces.json")" \
    jq -e '.mq_open == [-1, 24]' "$work/traces.json"
  check "a plugin cannot create System V IPC objects (its seccomp filter): $(jq -c .sysv "$work/traces.json")" \
    jq -e '.sysv == {"shm": -1, "msg": -1, "sem": -1}' "$work/traces.json"
  # Made outside the plugin's process tree (a shell as its UID), so the removal has some to delete.
  docker exec --user 20002:20002 "$node" python -c "
import ctypes
libc = ctypes.CDLL(None, use_errno=True)
assert libc.shmget(0, 4096, 0o1600) >= 0 and libc.msgget(0, 0o1600) >= 0 and libc.semget(0, 1, 0o1600) >= 0
"
  call probe-b 20002 /api/daemons "count=2" > /dev/null
  change 2 '{"desired_state": "stopped"}'
  wait_for 60 field_is 2 .observed_state stopped || true
  # As many files as ES_PLUGINS_FILES_PER_PLUGIN's default allows, made as probe-b's UID while it
  # is stopped (the disk watchdog measures running plugins only), to time the launcher's delete.
  docker exec --user 20002:20002 "$node" python -c "
import os
root = '/var/lib/es_plugins/data/probe-b/many'
for directory in range(100):
    os.makedirs(f'{root}/{directory}')
    for name in range(1000):
        open(f'{root}/{directory}/{name}', 'w').close()
"
  ipc_before=$(ipc_objects_of 20002)
  in_tools curl -s -o /dev/null -X POST http://control:8000/lab/placements/2/remove
  if wait_for 180 removed; then
    pass "probe-b's removal is reported removed"
    check "its 3 System V IPC objects were there before ($ipc_before) and none is left" \
      sh -c "[ '$ipc_before' -ge 3 ] && [ \"\$(docker exec $node python -c 'from es_plugins.launcher.ipc_cleanup import ipc_objects_of; print(len(ipc_objects_of(20002)))')\" = 0 ]"
    check "no process of probe-b's UID is left" test "$(processes_of 20002)" = 0
    left_as_root=$(as_root ls -A /var/lib/es_plugins/data /var/lib/es_plugins/plugins /var/lib/es_plugins/venvs /run/es_plugins)
    left_as_agent=$(docker exec --user 10000:10000 "$node" ls -A /var/lib/es_plugins/logs /var/lib/es_plugins/agent/unpack)
    check "nothing named probe-b is left under data, plugins, venvs, logs, agent/unpack or /run/es_plugins (its HOME, with a directory only its UID could enter, included)" \
      sh -c "! printf '%s\n%s\n' '$left_as_root' '$left_as_agent' | grep -qx probe-b"
    check "probe-a's trees are untouched" sh -c "printf '%s\n' '$left_as_root' | grep -qx probe-a"
    check "probe-b is in neither egress policy file" \
      sh -c "! docker exec $node grep -q probe-b $policy/passwords && ! docker exec $node grep -q '\"probe-b\"' $policy/hosts.json"
    check "the agent logged the removal's start and end" \
      sh -c "docker logs $node 2>&1 | grep -q 'plugins.removal.started plugin=probe-b placement=2' && docker logs $node 2>&1 | grep -q 'plugins.removal.done plugin=probe-b placement=2'"
    removal_line=$(docker logs "$node" 2>&1 | grep -o 'plugins.launcher.plugin_removed plugin=probe-b uid=20002 ipc_objects=[0-9]* seconds=[0-9.]*' | tail -n 1)
    echo "# $removal_line (a HOME of 100000 files)"
    check "the launcher removed probe-b's IPC objects itself ($removal_line)" sh -c "printf '%s' '$removal_line' | grep -q 'ipc_objects=3'"
  else
    fail "the removal of probe-b: $(report | jq -c .removals)"
  fi
else
  fail "probe-b did not run again for the removal: $(placement 2 '[.observed_state, .last_error] | tostring')"
fi

echo "# backups: as the node takes them before an upgrade, and a restore"

check "no plugin UID can enter the backups directory" \
  sh -c "! docker exec --user 20001:20001 $node ls /var/lib/es_plugins/backups 2> '$work/denied' && grep -q 'Permission denied' '$work/denied'"
check "the backups directory is 0700, the agent's" \
  test "$(as_root stat -c '%a %u:%g' /var/lib/es_plugins/backups)" = "700 10000:10000"
client_major=$(as_root sh -c 'LD_LIBRARY_PATH=/opt/postgresql-client/17/lib /opt/postgresql-client/17/bin/pg_dump --version' | sed -E 's/.*\(PostgreSQL\) ([0-9]+)\..*/\1/')
server_major=$(docker exec -u postgres "$database" psql -X -At -c 'SHOW server_version_num' | cut -c1-2)
check "the node's pg_dump is plugins_db's major version (client $client_major, server $server_major)" \
  sh -c "[ -n '$client_major' ] && [ '$client_major' = '$server_major' ]"
if docker exec -i --user 10000:10000 -e PLUGINS_DB_ADMIN_PASSWORD -e PLUGINS_DB_BACKUP_PASSWORD "$node" \
  python - < "$lab_dir/backup_restore.py" > "$work/backup.json" 2> "$work/backup.err"; then
  check "a backup of a database with rows behind FORCE ROW LEVEL SECURITY, as plugins_backup: $(jq -c .backup "$work/backup.json" | cut -c1-300)" \
    jq -e '.rows_before == 300 and .backup.size_bytes > 0 and .backup.directory == "0o700"
      and (.backup.files | length == 2) and all(.backup.files[]; endswith(" 0o600"))
      and .backup.ledger == ["001_schema.sql"] and (.backup.pg_dump | startswith("pg_dump (PostgreSQL) 17."))' "$work/backup.json"
  check "a restore with the owner as session user brings every row and the ledger back: $(jq -c .restore "$work/backup.json")" \
    jq -e '.rows_after_the_change == 100 and .rows_after_the_restore == 300
      and .restore.steps == ["verify","backup","close","recreate","restore","settings","assert"]
      and .restore.ledger == ["001_schema.sql"] and (.restore.pre_restore | endswith("-u1-pre_restore.dump"))' "$work/backup.json"
else
  fail "the backup and restore did not run: $(tail -n 5 "$work/backup.err")"
fi
check "no database password reaches the node's or the server's log" \
  sh -c "! { docker logs $node 2>&1; docker logs $database 2>&1; } | grep -q -F -f '$work/node-secrets'"

if [ "$failures" -ne 0 ]; then
  echo "FAILED: $failures check(s)"
  docker logs "$node" 2>&1 | tail -n 30
  exit 1
fi
echo "All node lab checks passed."
