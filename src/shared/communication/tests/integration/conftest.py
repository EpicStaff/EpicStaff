"""Integration test fixtures — starts real Redis and S3 storage (RustFS) via testcontainers."""

import pytest

try:
    import docker

    docker.from_env().ping()
    DOCKER_AVAILABLE = True
except Exception:
    DOCKER_AVAILABLE = False


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: marks tests as integration (require Docker)"
    )


def _skip_if_no_docker():
    if not DOCKER_AVAILABLE:
        pytest.skip("Docker is not available — skipping integration test")


# ---------------------------------------------------------------------------
# Redis container — session-scoped
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def redis_url():
    _skip_if_no_docker()
    from testcontainers.redis import RedisContainer

    with RedisContainer() as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(container.port)
        yield f"redis://{host}:{port}/0"


# ---------------------------------------------------------------------------
# S3 (RustFS) container — session-scoped
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def s3_params():
    _skip_if_no_docker()
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.wait_strategies import HttpWaitStrategy

    access_key = "admin"
    secret_key = "admin"

    container = (
        DockerContainer(
            image="rustfs/rustfs:1.0.0@sha256:8cc9801755448b71a786705ce76692c77e14936cccd87cf2fc31842e58f4d1ff"
        )
        .with_env("RUSTFS_ACCESS_KEY", access_key)
        .with_env("RUSTFS_SECRET_KEY", secret_key)
        .with_exposed_ports(9000)
        # The same liveness probe as the storage service's compose healthcheck;
        # RustFS logs to a file, so there is no startup line on stdout to wait for.
        .waiting_for(HttpWaitStrategy(9000, "/minio/health/live").for_status_code(200))
    )

    with container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(9000)
        yield {
            "host": host,
            "port": port,
            "access_key": access_key,
            "secret_key": secret_key,
        }
