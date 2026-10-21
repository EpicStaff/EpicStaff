#!/usr/bin/env bash
# The plugin node lab. Runs the es_plugins service exactly as src/docker-compose.yaml defines it
# (capabilities, read-only root, tmpfs modes, no-new-privileges, plugins-network only) against a
# stand-in for django_app's node API, installs two probe plugins packed with real wheels (and
# refuses a third, hostile one), and checks from inside them what a plugin process can and cannot
# do. One `ok -` / `not ok -` line
# per check; removes every container, volume, network and image it made.
#
# Needs Docker, network access (the packer downloads the probe plugins' wheels), and python3 with
# PyYAML (scripts/envtool.py writes the env file the extended service needs).
# Usage, from anywhere: bash src/es_plugins/lab/run.sh
set -euo pipefail

lab_dir=$(cd "$(dirname "$0")" && pwd)
repository=$(cd "$lab_dir/../../.." && pwd)
work=$(mktemp -d)
node=es-plugins-lab-node

python3 "$repository/scripts/envtool.py" --dev --env-file "$work/lab.env" > /dev/null
# The shell's values win over the env file's: the node talks to the lab's control service.
# A small disk cap, so the lab can write past it quickly.
export IMAGE_TAG=lab ES_PLUGINS_CPUS=2 ES_PLUGINS_MEMORY=2g PLUGINS_NODE_NAME=lab-node \
  PLUGINS_NODE_UID_RANGE=20000-20999 PLUGINS_INTERNAL_API_URL=http://control:8000/api/ \
  ES_PLUGINS_DISK_MB_PER_PLUGIN=64 ES_PLUGINS_FILES_PER_PLUGIN=5000
PLUGINS_NODE_KEY="lab-$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')"
export PLUGINS_NODE_KEY

compose() {
  docker compose -p es-plugins-lab -f "$lab_dir/compose.yaml" --env-file "$work/lab.env" \
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
compose up -d control es_plugins tools > /dev/null 2>&1
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
check "the container has only SETUID SETGID CHOWN, a read-only root and no-new-privileges ($inspected)" \
  test "$inspected" = "false [CAP_CHOWN CAP_SETGID CAP_SETUID] [ALL] true [no-new-privileges:true] |"
launcher_status=$(as_root grep -E '^(Uid|CapEff|CapBnd):' /proc/1/status | tr -s '\t' ' ' | tr '\n' ' ')
check "the launcher (PID 1) is root with exactly those three capabilities" \
  test "$launcher_status" = "Uid: 0 0 0 0 CapEff: 00000000000000c1 CapBnd: 00000000000000c1 "
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
check "its limits: NPROC 64, NOFILE 1024, no core dumps, oom_score_adj 800, its own session" jq -e '
  .rlimit_nproc == [64,64] and .rlimit_nofile == [1024,1024] and .rlimit_core == [0,0]
  and .oom_score_adj == 800 and .pid == .sid and .pid == .pgid' "$work/a.json"
check "cpu_priority normal is nice 0, low is nice 10" \
  test "$(jq .nice "$work/a.json") $(jq .nice "$work/b.json")" = "0 10"
check "its environment is exactly the documented one (docs/plugins/reference/runtime.md), USER and LOGNAME its identifier" jq -e '
  (.environment | keys) == ["EPICSTAFF_API_URL","EPICSTAFF_PLUGIN_ENTRYPOINT","EPICSTAFF_PLUGIN_IDENTIFIER",
    "EPICSTAFF_PLUGIN_LISTEN_FD","EPICSTAFF_PLUGIN_PUBLIC_URL","EPICSTAFF_PLUGIN_RUNTIME_FILE",
    "EPICSTAFF_PLUGIN_VERSION","EPICSTAFF_PUBLIC_URL","HOME","LANG","LOGNAME","PATH","PORT",
    "PYTHONUNBUFFERED","TMPDIR","USER"]
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
# 20500 and 20999 are assigned to no placement.
for port in 20002 20001 20003 20500 20999; do
  call probe-a 20001 /api/bind "port=$port" > "$work/bind-$port.json"
done
check "probe-a can take no port of the range, its own, another plugin's or a free one, listening or only bound, on 0.0.0.0 or 127.0.0.1, with or without SO_REUSEADDR/SO_REUSEPORT" \
  sh -c "for port in 20002 20001 20003 20500 20999; do jq -e 'length == 8 and all(.[]; startswith(\"DENIED\") and contains(\"Address already in use\"))' \"$work/bind-\$port.json\" > /dev/null || exit 1; done"
check "probe-a still serves: on the socket the agent holds and hands it as fd 3" running 1

echo "# disk: a 64 MB cap per plugin, measured every 30 s"

b_pid=$(placement 2 .pid)
call probe-a 20001 /api/fill "mb=100" > "$work/fill.json"
if wait_for 90 field_is 1 .observed_state failed; then
  disk_error=$(placement 1 .last_error)
  # The measurement may catch the write half done: any size past the cap.
  check "probe-a, past its disk cap, is stopped and marked failed ($disk_error)" \
    contains "$disk_error" "MB of disk, more than its limit of 64 MB"
  check "no process of probe-a is left" test "$(placement 1 .pid)" = null
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
check "no secret is in any process's command line" \
  sh -c "! docker exec $node sh -c 'cat /proc/[0-9]*/cmdline' | tr '\0' ' ' | grep -q -e secret-token -e \"$PLUGINS_NODE_KEY\""

if [ "$failures" -ne 0 ]; then
  echo "FAILED: $failures check(s)"
  docker logs "$node" 2>&1 | tail -n 30
  exit 1
fi
echo "All node lab checks passed."
