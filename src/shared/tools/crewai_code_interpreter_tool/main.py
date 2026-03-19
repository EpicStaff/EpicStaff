import os
import subprocess
from typing import Dict, Any, List

from docker import from_env as docker_from_env
from docker.errors import ImageNotFound, NotFound
from docker.models.containers import Container


DOCKER_IMAGE = "code-interpreter:latest"
CONTAINER_NAME = "code-interpreter"


# -----------------------------
# Restricted sandbox execution
# -----------------------------

BLOCKED_MODULES = {
    "os",
    "sys",
    "subprocess",
    "shutil",
    "importlib",
    "inspect",
    "tempfile",
    "sysconfig",
}

UNSAFE_BUILTINS = {
    "exec",
    "eval",
    "open",
    "compile",
    "input",
    "globals",
    "locals",
    "vars",
    "help",
    "dir",
}


def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name in BLOCKED_MODULES:
        raise ImportError(f"Importing '{name}' is not allowed")
    return __import__(name, globals, locals, fromlist, level)


def _safe_builtins():
    import builtins

    safe = {
        k: v for k, v in builtins.__dict__.items()
        if k not in UNSAFE_BUILTINS
    }
    safe["__import__"] = _restricted_import
    return safe


def run_in_sandbox(code: str) -> str:
    locals_env: Dict[str, Any] = {}
    try:
        exec(code, {"__builtins__": _safe_builtins()}, locals_env)
        return locals_env.get("result", "No result variable found.")
    except Exception as e:
        return f"Sandbox error: {e}"


# -----------------------------
# Docker execution
# -----------------------------

def docker_available() -> bool:
    try:
        subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=1,
            check=True,
        )
        return True
    except Exception:
        return False


def ensure_docker_image():
    client = docker_from_env()
    try:
        client.images.get(DOCKER_IMAGE)
    except ImageNotFound:
        raise RuntimeError(
            f"Docker image '{DOCKER_IMAGE}' not found. "
            f"Please build it manually."
        )


def init_container() -> Container:
    client = docker_from_env()
    cwd = os.getcwd()

    try:
        old = client.containers.get(CONTAINER_NAME)
        old.stop()
        old.remove()
    except NotFound:
        pass

    return client.containers.run(
        DOCKER_IMAGE,
        detach=True,
        tty=True,
        name=CONTAINER_NAME,
        working_dir="/workspace",
        volumes={cwd: {"bind": "/workspace", "mode": "rw"}},
    )


def install_libraries(container: Container, libraries: List[str]):
    for lib in libraries:
        container.exec_run(["pip", "install", lib])


def run_in_docker(code: str, libraries: List[str]) -> str:
    ensure_docker_image()
    container = init_container()

    try:
        install_libraries(container, libraries)
        result = container.exec_run(["python3", "-c", code])

        output = result.output.decode("utf-8")
        if result.exit_code != 0:
            return f"Docker execution failed:\n{output}"
        return output
    finally:
        container.stop()
        container.remove()


# -----------------------------
# Unsafe execution
# -----------------------------

def run_unsafe(code: str, libraries: List[str]) -> str:
    for lib in libraries:
        os.system(f"pip install {lib}")

    try:
        locals_env: Dict[str, Any] = {}
        exec(code, {}, locals_env)
        return locals_env.get("result", "No result variable found.")
    except Exception as e:
        return f"Unsafe execution error: {e}"


# -----------------------------
# Tool entrypoint
# -----------------------------

def main(code: str, libraries_used: List[str] = None, unsafe_mode: bool = False) -> str:
    libraries_used = libraries_used or []

    if unsafe_mode:
        return run_unsafe(code, libraries_used)

    if docker_available():
        return run_in_docker(code, libraries_used)

    return run_in_sandbox(code)