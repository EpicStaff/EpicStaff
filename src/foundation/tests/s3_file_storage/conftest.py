"""Real S3-compatible backend for s3_file_storage tests.

A throwaway RustFS container (same image pinned in `src/docker-compose.yaml`) is started
once per test session and torn down at the end. Every test in this package talks to it
through a real boto3 client over real HTTP -- nothing about the S3 wire protocol is mocked.
"""

import socket
import subprocess
import time
import uuid

import httpx
import pytest
from botocore.exceptions import ClientError

from foundation.s3_file_storage.storage import S3FileStorage

RUSTFS_IMAGE = "rustfs/rustfs:1.0.0@sha256:8cc9801755448b71a786705ce76692c77e14936cccd87cf2fc31842e58f4d1ff"
_ACCESS_KEY = "foundation-test"
_SECRET_KEY = "foundation-test-secret"


def client_error(code: str, message: str = "boom", status: int = 400) -> ClientError:
    """A real botocore ClientError, shaped like a real S3 error response -- used in
    tests/s3_file_storage/test_errors.py to exercise handle_error's mapping directly."""
    return ClientError(
        {"Error": {"Code": code, "Message": message}, "ResponseMetadata": {"HTTPStatusCode": status}},
        "TestOperation",
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_until_healthy(port: int, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"http://127.0.0.1:{port}/minio/health/live", timeout=1)
            if response.status_code == 200:
                return
        except httpx.HTTPError as error:
            last_error = error
        time.sleep(0.2)
    raise RuntimeError(f"rustfs container did not become healthy in time: {last_error}")


@pytest.fixture(scope="session")
def rustfs():
    """Start a real, disposable RustFS container and yield its connection info."""
    port = _free_port()
    name = f"foundation-test-rustfs-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker", "run", "-d", "--rm",
            "--name", name,
            "-p", f"{port}:{port}",
            "-e", f"RUSTFS_ACCESS_KEY={_ACCESS_KEY}",
            "-e", f"RUSTFS_SECRET_KEY={_SECRET_KEY}",
            "-e", f"RUSTFS_ADDRESS=:{port}",
            "-e", "RUSTFS_CONSOLE_ENABLE=false",
            RUSTFS_IMAGE,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        _wait_until_healthy(port)
        yield {"host": "127.0.0.1", "port": port, "user": _ACCESS_KEY, "password": _SECRET_KEY}
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


@pytest.fixture
def storage(rustfs) -> S3FileStorage:
    return S3FileStorage(
        host=rustfs["host"], port=rustfs["port"], user=rustfs["user"], password=rustfs["password"]
    )


@pytest.fixture
def bucket_name() -> str:
    """A fresh bucket name per test -- the container and its state outlive a single test."""
    return f"test-{uuid.uuid4().hex[:12]}"
