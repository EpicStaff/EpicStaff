"""Docker / compose operations on the stack under test. Standard library only."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

INSTRUMENTED = ("django_app", "crew", "agent", "sandbox")
RESTARTED = (*INSTRUMENTED, "knowledge_new")
BACKUP_SUFFIX = ".bench-backup"


class StackError(RuntimeError):
    pass


def run(args: list[str], timeout: float = 600, env: dict | None = None, check: bool = True):
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, env=env, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise StackError(f"{' '.join(args[:3])}: {error}") from error
    if check and result.returncode != 0:
        raise StackError(
            f"{' '.join(args[:4])} failed ({result.returncode}): {result.stderr.strip()[-500:]}"
        )
    return result


def apply_env_overrides(text: str, overrides: dict[str, str]) -> str:
    lines, seen = text.splitlines(), set()
    for index, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in overrides:
            lines[index] = f"{key}={overrides[key]}"
            seen.add(key)
    lines += [f"{key}={value}" for key, value in overrides.items() if key not in seen]
    return "\n".join(lines) + "\n"


def read_env_file(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        name, separator, value = line.partition("=")
        if separator and not name.lstrip().startswith("#"):
            value = value.strip()
            # Handle quoted values: keep everything inside quotes (including #)
            if value.startswith("'") and "'" in value[1:]:
                # Single-quoted: extract content between first and second quote
                end_quote = value.index("'", 1)
                value = value[1:end_quote]
            elif value.startswith('"') and '"' in value[1:]:
                # Double-quoted: extract content between first and second quote
                end_quote = value.index('"', 1)
                value = value[1:end_quote]
            else:
                # Unquoted: strip inline comment (# preceded by whitespace)
                value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
            values[name.strip().removeprefix("export ").strip()] = value
    return values


class EnvOverride:
    """Writes overrides into src/.env and always restores the original (also on Ctrl+C)."""

    def __init__(self, env_path: Path, overrides: dict[str, str]):
        self.env_path, self.overrides = env_path, overrides
        self.backup_path = env_path.with_name(env_path.name + BACKUP_SUFFIX)

    def __enter__(self):
        if self.backup_path.exists():
            raise StackError(
                f"{self.backup_path} exists: a previous run did not restore .env. "
                f"Check it, then: mv {self.backup_path} {self.env_path}"
            )
        shutil.copy2(self.env_path, self.backup_path)
        try:
            original = self.env_path.read_text(encoding="utf-8")
            self.env_path.write_text(
                apply_env_overrides(original, self.overrides), encoding="utf-8"
            )
        except BaseException:
            shutil.copy2(self.backup_path, self.env_path)
            self.backup_path.unlink()
            raise
        return self

    def __exit__(self, *exc_info):
        shutil.copy2(self.backup_path, self.env_path)
        self.backup_path.unlink()
        return False


def parse_ps(output: str) -> list[dict]:
    """`docker compose ps --format json`: one array (old compose) or one object per line."""
    output = output.strip()
    if not output:
        return []
    if output.startswith("["):
        return json.loads(output)
    return [json.loads(line) for line in output.splitlines() if line.strip()]


@dataclass
class Compose:
    src_dir: Path  # folder holding docker-compose.yaml (main checkout or a worktree)
    env_file: Path  # always the main checkout's src/.env
    project: str

    def cmd(self, *args: str) -> list[str]:
        return [
            "docker",
            "compose",
            "-p",
            self.project,
            "--project-directory",
            str(self.src_dir),
            "-f",
            str(self.src_dir / "docker-compose.yaml"),
            "--env-file",
            str(self.env_file),
            *args,
        ]

    def up(self, build: bool) -> None:
        run(self.cmd("up", "-d", *(["--build"] if build else [])), timeout=3600)
        self.wait_healthy()

    def restart(self, services: tuple[str, ...] = RESTARTED) -> None:
        run(self.cmd("restart", *services), timeout=600)
        self.wait_healthy()

    def ps(self) -> list[dict]:
        return parse_ps(run(self.cmd("ps", "-a", "--format", "json")).stdout)

    def wait_healthy(self, timeout_s: float = 300) -> None:
        deadline = time.monotonic() + timeout_s
        while True:
            waiting = [
                row["Service"]
                for row in self.ps()
                if not (
                    row.get("State") == "running" and row.get("Health") in ("", "healthy", None)
                )
                and not (row.get("State") == "exited" and row.get("ExitCode") == 0)
            ]
            if not waiting:
                return
            if time.monotonic() > deadline:
                raise StackError(f"not healthy after {timeout_s:.0f} s: {waiting}")
            time.sleep(3)

    def containers(self) -> dict[str, dict]:
        return {row["Service"]: row for row in self.ps() if row.get("State") == "running"}

    def images(self) -> dict[str, str]:
        inspected = inspect([row["Name"] for row in self.containers().values()])
        return {name: data["Image"][:19] for name, data in inspected.items()}


def detect_project(container: str = "crew") -> str:
    label = '{{ index .Config.Labels "com.docker.compose.project" }}'
    result = run(["docker", "inspect", "--format", label, container], check=False)
    return result.stdout.strip() or "src"


class Worktree:
    """Checks `ref` out in a temporary directory, so the runner's own files never change mid-run."""

    def __init__(self, repo: Path, ref: str):
        self.repo, self.ref, self.path, self._temp_root = repo, ref, None, None

    def __enter__(self) -> Path:
        self._temp_root = Path(tempfile.mkdtemp(prefix="bench-"))
        self.path = self._temp_root / "EpicStaff"
        try:
            run(
                [
                    "git",
                    "-C",
                    str(self.repo),
                    "worktree",
                    "add",
                    "--detach",
                    str(self.path),
                    self.ref,
                ],
                timeout=300,
            )
        except StackError:
            shutil.rmtree(self._temp_root, ignore_errors=True)
            raise
        try:
            # gitignored bind-mount source the worktree would otherwise lack
            certs = self.repo / "src" / "nginx" / "certs"
            if certs.is_dir():
                target = self.path / "src" / "nginx" / "certs"
                target.mkdir(parents=True, exist_ok=True)
                for item in certs.iterdir():
                    if item.is_file() and item.name != ".gitkeep":
                        shutil.copy2(item, target / item.name)
        except BaseException:
            self.__exit__()
            raise
        return self.path

    def __exit__(self, *exc_info):
        remove_result = run(
            [
                "git",
                "-C",
                str(self.repo),
                "worktree",
                "remove",
                "--force",
                str(self.path),
            ],
            check=False,
        )
        run(["git", "-C", str(self.repo), "worktree", "prune"], check=False)
        shutil.rmtree(self._temp_root, ignore_errors=True)
        if remove_result.returncode != 0:
            print(f"warning: git worktree remove failed for {self.path}")
        return False


def git_info(repo: Path) -> dict:
    def git(*args: str) -> str:
        return run(["git", "-C", str(repo), *args], check=False).stdout.strip()

    return {
        "ref": git("rev-parse", "--abbrev-ref", "HEAD"),
        "sha": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
    }


def inspect(names: list[str]) -> dict[str, dict]:
    if not names:
        return {}
    result = run(["docker", "inspect", *names], check=False)
    rows = json.loads(result.stdout or "[]")
    return {row["Name"].lstrip("/"): row for row in rows}


def container_env(inspected: dict) -> dict[str, str]:
    return dict(item.split("=", 1) for item in inspected["Config"]["Env"] if "=" in item)


class LogFollower:
    """Streams `docker logs -f` of one container and keeps its BENCH JSON lines."""

    def __init__(
        self, container: str, since_epoch: float, on_event=None, service: str | None = None
    ):
        self.container, self.on_event = container, on_event
        self.service = service or container
        self.events: list[dict] = []
        self._process = subprocess.Popen(
            ["docker", "logs", "-f", "--since", f"{since_epoch:.3f}", container],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        for line in self._process.stdout:
            if not line.startswith('{"bench"'):
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            event["service"] = self.service
            self.events.append(event)
            if self.on_event:
                self.on_event(event)

    def stop(self, grace_s: float = 2) -> None:
        time.sleep(grace_s)  # let the last lines arrive
        self._process.terminate()
        self._thread.join(timeout=10)


def host_info() -> dict:
    def command(*args: str) -> str | None:
        try:
            return run(list(args), check=False, timeout=10).stdout.strip() or None
        except StackError:
            return None

    ram_mb = None
    if Path("/proc/meminfo").exists():
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                ram_mb = round(int(line.split()[1]) / 1024)
    return {
        "hostname": socket.gethostname(),
        "vcpu": os.cpu_count(),
        "ram_mb": ram_mb,
        "kernel": platform.release(),
        "os": platform.system(),
        "docker": command("docker", "version", "--format", "{{.Server.Version}}"),
        "virtualization": command("systemd-detect-virt") if platform.system() == "Linux" else None,
    }
