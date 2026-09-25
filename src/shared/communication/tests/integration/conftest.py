"""Integration test fixtures — starts real Redis and MinIO via testcontainers."""

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
# MinIO container — session-scoped
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def minio_params():
    _skip_if_no_docker()
    from testcontainers.minio import MinioContainer

    with MinioContainer(
        image="rustfs/rustfs:1.0.0@sha256:8cc9801755448b71a786705ce76692c77e14936cccd87cf2fc31842e58f4d1ff"
    ) as container:
        cfg = container.get_config()
        # cfg["endpoint"] is "host:port"
        host, port_str = cfg["endpoint"].rsplit(":", 1)
        yield {
            "host": host,
            "port": int(port_str),
            "access_key": cfg["access_key"],
            "secret_key": cfg["secret_key"],
        }
