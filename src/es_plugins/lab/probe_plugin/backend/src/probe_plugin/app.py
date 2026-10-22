"""The node lab's probe plugin: reports what its own process is, and tries to reach another plugin.

A plain ASGI app. `epicstaff_plugin.serve` runs it behind the health endpoint, the hook
dispatch and the context check, so every route here needs a valid gateway context, which the
lab's control service mints. Every attempt that must fail reports `DENIED ...`; positive
controls report `OK ...`. Its install hook leaves a mark in its HOME for each job it ran.
"""

import ctypes
import getpass
import json
import os
import pwd
import resource
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs

from epicstaff_plugin.hooks import hook_registry

DATA_ROOT = "/var/lib/es_plugins"
RUN_ROOT = "/run/es_plugins"
LAUNCHER_SOCKET = "/run/es_launcher/launcher.sock"
AGENT_UID = 10000
PTRACE_ATTACH, PTRACE_SEIZE = 16, 0x4206

libc = ctypes.CDLL(None, use_errno=True)
libc.ptrace.restype = ctypes.c_long
libc.ptrace.argtypes = [ctypes.c_long, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]


def attempt(function) -> str:
    try:
        return f"OK {function()!r}"[:200]
    except BaseException as error:
        return f"DENIED {type(error).__name__}: {error}"[:200]


def status_of(pid="self") -> dict[str, str]:
    with open(f"/proc/{pid}/status") as status_file:
        return dict(line.rstrip("\n").split(":\t", 1) for line in status_file if ":\t" in line)


def pids_of_uid(uid: int) -> list[int]:
    pids = []
    for entry in os.listdir("/proc"):
        if entry.isdigit():
            try:
                fields = status_of(entry)
            except OSError:
                continue
            if int(fields["Uid"].split()[0]) == uid and not fields["State"].startswith("Z"):
                pids.append(int(entry))
    return sorted(pids)


def mode_of(path: str) -> str:
    info = os.stat(path)
    return f"{stat.filemode(info.st_mode)} {info.st_uid}:{info.st_gid}"


def read(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read(64)


def write(path: str) -> str:
    with open(path, "w") as handle:
        handle.write("x")
    return "written"


def ptrace(request: int, pid: int) -> str:
    if libc.ptrace(request, pid, None, None) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return "attached"


def ptrace_own_child() -> str:
    child = os.fork()
    if child == 0:
        time.sleep(5)
        os._exit(0)
    try:
        return ptrace(PTRACE_ATTACH, child)
    finally:
        os.kill(child, signal.SIGKILL)
        os.waitpid(child, 0)


def posix_shared_memory() -> str:
    from multiprocessing import shared_memory

    block = shared_memory.SharedMemory(create=True, size=4096)
    block.close()
    block.unlink()
    return "created"


def multiprocessing_lock() -> str:
    import multiprocessing

    multiprocessing.Lock()
    return "created"


def try_bind(host: str, port: int, reuse: bool, listen: bool) -> str:
    """Bind `host:port` as this plugin (and listen, when asked), then let go at once."""

    def bind() -> str:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if reuse:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            probe.bind((host, port))
            if listen:
                probe.listen(1)
        return "bound"

    return attempt(bind)


def try_bind_udp(host: str, port: int) -> str:
    def bind() -> str:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind((host, port))
        return "bound"

    return attempt(bind)


def bind_attempts(port: int) -> dict:
    """Every way a plugin could try to take `port`: to listen on it, or only to keep it bound,
    over TCP, and a UDP bind."""
    attempts = {}
    for host in ("0.0.0.0", "127.0.0.1"):
        for reuse in (False, True):
            for listen in (True, False):
                name = (
                    f"{host} {'with' if reuse else 'without'} SO_REUSEADDR/SO_REUSEPORT, "
                    f"{'listening' if listen else 'bound only'}"
                )
                attempts[name] = try_bind(host, port, reuse, listen)
        attempts[f"{host} UDP"] = try_bind_udp(host, port)
    return attempts


# Sockets the probe keeps open until its process ends.
kept_sockets: list[socket.socket] = []


def listen_without_bind() -> dict:
    """`listen()` on a TCP socket never bound: the kernel picks a port, and no bind hook runs.
    The socket stays open, for the node's socket watchdog to find."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.listen(1)
    kept_sockets.append(listener)
    return {"port": listener.getsockname()[1], "listened_at": time.time()}


def talk_to_launcher() -> bytes:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    client.connect(LAUNCHER_SOCKET)
    client.send(json.dumps({"operation": "kill_uid", "uid": 20002}).encode())
    return client.recv(4096)


def info() -> dict:
    identifier = os.environ["EPICSTAFF_PLUGIN_IDENTIFIER"]
    runtime_file = os.environ["EPICSTAFF_PLUGIN_RUNTIME_FILE"]
    with open("/proc/self/oom_score_adj") as adjustment:
        oom_score_adj = int(adjustment.read())
    own = status_of()
    with open(runtime_file) as runtime:
        settings = json.load(runtime)["settings"]
    return {
        "pid": os.getpid(),
        "pgid": os.getpgid(0),
        "sid": os.getsid(0),
        "identity": {key: own[key].split() for key in ("Uid", "Gid", "Groups")},
        "capabilities": {
            key: own[key] for key in ("CapInh", "CapPrm", "CapEff", "CapAmb", "CapBnd")
        },
        "no_new_privs": own["NoNewPrivs"],
        "rlimit_nproc": resource.getrlimit(resource.RLIMIT_NPROC),
        "rlimit_nofile": resource.getrlimit(resource.RLIMIT_NOFILE),
        "rlimit_core": resource.getrlimit(resource.RLIMIT_CORE),
        "nice": os.getpriority(os.PRIO_PROCESS, 0),
        "oom_score_adj": oom_score_adj,
        "environment": dict(os.environ),
        "user": getpass.getuser(),
        "passwd_entry": attempt(lambda: pwd.getpwuid(os.getuid())),
        "home_mode": mode_of(os.environ["HOME"]),
        "tmpdir_mode": mode_of(os.environ["TMPDIR"]),
        "write_tmpdir": attempt(lambda: write(os.path.join(os.environ["TMPDIR"], "probe"))),
        "write_tmp": attempt(lambda: write("/tmp/from-a-plugin")),
        "write_rootfs": attempt(lambda: write("/etc/from-a-plugin")),
        "write_own_code": attempt(lambda: write(f"{DATA_ROOT}/plugins/{identifier}/probe")),
        "write_dev_shm": attempt(lambda: write("/dev/shm/from-a-plugin")),
        "posix_shared_memory": attempt(posix_shared_memory),
        "multiprocessing_lock": attempt(multiprocessing_lock),
        "runtime_file_mode": mode_of(runtime_file),
        "runtime_settings": settings,
        "processes_of_my_uid": pids_of_uid(os.getuid()),
    }


def probe(target: str, target_uid: int) -> dict:
    target_pids = pids_of_uid(target_uid)
    target_pid = target_pids[0] if target_pids else 0
    agent_pid = (pids_of_uid(AGENT_UID) or [0])[0]
    results = {
        "target_pid": target_pid,
        "read_target_runtime_file": attempt(lambda: read(f"{RUN_ROOT}/{target}/runtime.json")),
        "list_target_run_directory": attempt(lambda: os.listdir(f"{RUN_ROOT}/{target}")),
        "list_target_home": attempt(lambda: os.listdir(f"{DATA_ROOT}/data/{target}")),
        "write_target_home": attempt(lambda: write(f"{DATA_ROOT}/data/{target}/evil")),
        "list_target_code": attempt(lambda: os.listdir(f"{DATA_ROOT}/plugins/{target}")),
        "list_target_venv": attempt(lambda: os.listdir(f"{DATA_ROOT}/venvs/{target}")),
        "list_agent_directory": attempt(lambda: os.listdir(f"{DATA_ROOT}/agent")),
        "list_logs": attempt(lambda: os.listdir(f"{DATA_ROOT}/logs")),
        "read_target_environ": attempt(lambda: read(f"/proc/{target_pid}/environ")),
        "read_target_maps": attempt(lambda: read(f"/proc/{target_pid}/maps")),
        "read_target_mem": attempt(lambda: read(f"/proc/{target_pid}/mem")),
        "list_target_fds": attempt(lambda: os.listdir(f"/proc/{target_pid}/fd")),
        "read_agent_environ": attempt(lambda: read(f"/proc/{agent_pid}/environ")),
        "read_launcher_environ": attempt(lambda: read("/proc/1/environ")),
        "signal_target": attempt(lambda: os.kill(target_pid, 0)),
        "kill_target": attempt(lambda: os.kill(target_pid, signal.SIGKILL)),
        "kill_target_group": attempt(lambda: os.killpg(os.getpgid(target_pid), signal.SIGKILL)),
        "kill_agent": attempt(lambda: os.kill(agent_pid, signal.SIGKILL)),
        "kill_launcher": attempt(lambda: os.kill(1, signal.SIGKILL)),
        "ptrace_attach_target": attempt(lambda: ptrace(PTRACE_ATTACH, target_pid)),
        "ptrace_seize_target": attempt(lambda: ptrace(PTRACE_SEIZE, target_pid)),
        "reach_launcher": attempt(talk_to_launcher),
        "become_root": attempt(lambda: os.setuid(0)),
        "become_target": attempt(lambda: os.setuid(target_uid)),
        "CONTROL_read_own_runtime_file": attempt(
            lambda: read(os.environ["EPICSTAFF_PLUGIN_RUNTIME_FILE"])[:8]
        ),
        "CONTROL_ptrace_own_child": attempt(ptrace_own_child),
    }
    # What co-located plugins can see of each other; reported, not refused.
    results["SEEN_target_cmdline"] = attempt(lambda: read(f"/proc/{target_pid}/cmdline"))
    return results


def start_daemons(count: int) -> list[int]:
    """Leave `count` processes that left the session and the process tree, as a daemon would."""
    started = []
    for _ in range(count):
        read_end, write_end = os.pipe()
        child = os.fork()
        if child == 0:
            os.close(read_end)
            os.setsid()
            grandchild = os.fork()
            if grandchild == 0:
                os.write(write_end, str(os.getpid()).encode())
                os.close(write_end)
                time.sleep(600)
            os._exit(0)
        os.close(write_end)
        os.waitpid(child, 0)
        with os.fdopen(read_end) as reader:
            started.append(int(reader.read()))
    return started


def start_memory_hog(megabytes: int) -> int:
    """A child that grows to `megabytes` (the parent stays small, as in a real plugin)."""
    child = os.fork()
    if child == 0:
        chunks = []
        while len(chunks) * 16 < megabytes:
            # Written, not just reserved: untouched pages would not count as resident.
            chunks.append(b"\x01" * (16 * 1024 * 1024))
            time.sleep(0.05)
        time.sleep(600)
        os._exit(0)
    return child


def fill_home(megabytes: int) -> dict:
    """Write `megabytes` of data into HOME, as a plugin with a runaway cache would."""
    path = os.path.join(os.environ["HOME"], "fill.bin")
    chunk = b"\x01" * (1024 * 1024)
    with open(path, "wb") as fill:
        fill.writelines(chunk for _ in range(megabytes))
    return {"written_mb": megabytes, "path": path}


def fork_bomb() -> dict:
    """Fork until the kernel refuses; every child becomes a `sleep` of a few seconds.

    The children exec, so they hold processes, not memory: this probes RLIMIT_NPROC, and the
    memory cap does not end the experiment first.
    """
    forked, error = 0, None
    children = []
    while forked < 1000:
        try:
            child = os.fork()
        except OSError as failure:
            error = f"{type(failure).__name__}: {failure}"
            break
        if child == 0:
            try:
                os.execv("/bin/sleep", ["sleep", "4"])
            finally:
                os._exit(127)
        forked += 1
        children.append(child)
    processes = len(pids_of_uid(os.getuid()))
    for child in children:
        os.waitpid(child, 0)
    return {"forked": forked, "processes_at_peak": processes, "stopped_by": error}


IPC_PRIVATE, IPC_CREAT = 0, 0o1000


def open_connections(host: str, port: int, count: int, hold_seconds: float) -> dict:
    """Open `count` connections to host:port and hold them `hold_seconds`; count what opened."""
    opened, refused = [], 0
    for _ in range(count):
        connection = socket.socket()
        connection.settimeout(3)
        try:
            connection.connect((host, port))
            opened.append(connection)
        except OSError:
            connection.close()
            refused += 1

    def release() -> None:
        for connection in opened:
            connection.close()

    threading.Timer(hold_seconds, release).start()
    return {"opened": len(opened), "refused": refused}


# A worker of `hold_accepted`: its own small interpreter, so the UID's memory stays far below its
# cap (forks of this process would count its pages again, each).
ACCEPTOR = """
import socket, sys, time
listen_fd, per_acceptor, accept_seconds, hold_seconds = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
listener = socket.socket(fileno=listen_fd)
accept_until = time.monotonic() + accept_seconds
held = []
while len(held) < per_acceptor and time.monotonic() < accept_until:
    listener.settimeout(max(0.05, accept_until - time.monotonic()))
    try:
        held.append(listener.accept()[0])
    except OSError:
        time.sleep(0.01)
listener.detach()
time.sleep(max(0.0, hold_seconds - accept_seconds))
"""
ACCEPTORS = []


def hold_accepted(
    acceptors: int, per_acceptor: int, accept_seconds: float, hold_seconds: float
) -> dict:
    """Start `acceptors` processes that accept connections on the plugin's own socket for
    `accept_seconds`, up to `per_acceptor` each, and hold them until `hold_seconds`: a busy
    server's workers. Past the accepting time the health checks reach uvicorn again."""
    listen_fd = int(os.environ["EPICSTAFF_PLUGIN_LISTEN_FD"])
    arguments = [str(listen_fd), str(per_acceptor), str(accept_seconds), str(hold_seconds)]
    for _ in range(acceptors):
        process = subprocess.Popen(
            [sys.executable, "-I", "-c", ACCEPTOR, *arguments], pass_fds=(listen_fd,)
        )
        ACCEPTORS.append(process)
        threading.Thread(target=process.wait, daemon=True).start()
    return {"acceptors": [process.pid for process in ACCEPTORS[-acceptors:]]}


def churn(host: str, port: int, count: int) -> dict:
    """Open and close `count` connections to host:port as fast as it can."""
    opened = refused = 0
    started = time.monotonic()
    for _ in range(count):
        connection = socket.socket()
        connection.settimeout(3)
        try:
            connection.connect((host, port))
            opened += 1
        except OSError:
            refused += 1
        finally:
            connection.close()
    return {"opened": opened, "refused": refused, "seconds": round(time.monotonic() - started, 2)}


def leave_traces() -> dict:
    """What a removal must clean up: a private directory, System V IPC objects, and the attempt
    at a POSIX message queue, which the node's limits refuse."""
    private = os.path.join(os.environ["HOME"], "private")
    os.makedirs(private, mode=0o700, exist_ok=True)
    with open(os.path.join(private, "secret.txt"), "w") as secret:
        secret.write("only this plugin's")
    created = {
        "shm": libc.shmget(IPC_PRIVATE, 4096, IPC_CREAT | 0o600),
        "msg": libc.msgget(IPC_PRIVATE, IPC_CREAT | 0o600),
        "sem": libc.semget(IPC_PRIVATE, 1, IPC_CREAT | 0o600),
    }
    librt = ctypes.CDLL("librt.so.1", use_errno=True)
    queue = librt.mq_open(b"/probe-queue", os.O_CREAT | os.O_RDWR, 0o600, None)
    return {"sysv": created, "mq_open": [queue, ctypes.get_errno()]}


def write_mark(name: str, document: dict) -> None:
    with open(os.path.join(os.environ["HOME"], name), "w") as mark_file:
        json.dump(document, mark_file)


@hook_registry.on_install
async def mark_install(request, epicstaff) -> None:
    """Write `install-hook-<job>.json` to HOME; refuse organization 8, to show a failure."""
    if request.org.id == 8:
        raise RuntimeError("the probe refuses organization 8")
    write_mark(
        f"install-hook-{request.job_id}.json",
        {"organization": request.org.id, "attempt": request.attempt},
    )


async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    query = {key: values[0] for key, values in parse_qs(scope["query_string"].decode()).items()}
    path = scope["path"]
    if path == "/api/info":
        body = info()
    elif path == "/api/probe":
        body = probe(query["target"], int(query["target_uid"]))
    elif path == "/api/daemons":
        body = {"started": start_daemons(int(query.get("count", "3")))}
    elif path == "/api/hog":
        body = {"hog": start_memory_hog(int(query["mb"]))}
    elif path == "/api/forkbomb":
        body = fork_bomb()
    elif path == "/api/bind":
        body = bind_attempts(int(query["port"]))
    elif path == "/api/listen":
        body = listen_without_bind()
    elif path == "/api/fill":
        body = fill_home(int(query["mb"]))
    elif path == "/api/connect":
        body = open_connections(
            query["host"], int(query["port"]), int(query["count"]), float(query.get("hold", "20"))
        )
    elif path == "/api/accept":
        body = hold_accepted(
            int(query["acceptors"]), int(query["per"]), float(query["accept"]), float(query["hold"])
        )
    elif path == "/api/churn":
        body = churn(query["host"], int(query["port"]), int(query["count"]))
    elif path == "/api/traces":
        body = leave_traces()
    else:
        body = {"error": "no such probe"}
    payload = json.dumps(body).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": payload})
