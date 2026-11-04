"""The request cap and slot wait django_app reads at startup.

Invariant: every process loading the settings needs DJANGO_SGI_MAX_CONCURRENT_REQUESTS at least 1
and DJANGO_SGI_ADMISSION_TIMEOUT `none` (no limit) or not negative. Only a request handler also
needs the cap below its pool's max size (tests/asgi_tests/test_request_admission_middleware.py);
the Redis workers start with a pool of 2 and the default cap of 8.
"""

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_app.settings.base import read_request_admission
from src.shared.envtools import Env


def _environment(max_concurrent_requests="8", timeout="5s") -> Env:
    return Env(
        {
            "DJANGO_SGI_MAX_CONCURRENT_REQUESTS": max_concurrent_requests,
            "DJANGO_SGI_ADMISSION_TIMEOUT": timeout,
        }
    )


@pytest.mark.parametrize(
    ("max_concurrent_requests", "timeout", "expected"),
    [("8", "5s", (8, 5.0)), ("1", "0", (1, 0.0)), ("15", "none", (15, None))],
)
def test_reads_a_cap_of_at_least_one_and_a_timeout_that_is_none_or_not_negative(
    max_concurrent_requests, timeout, expected
):
    environment = _environment(max_concurrent_requests, timeout)

    assert read_request_admission(environment) == expected


@pytest.mark.parametrize("max_concurrent_requests", ["0", "-1", "none"])
def test_refuses_a_cap_below_one(max_concurrent_requests):
    with pytest.raises(ImproperlyConfigured, match="DJANGO_SGI_MAX_CONCURRENT_REQUESTS must be"):
        read_request_admission(_environment(max_concurrent_requests))


@pytest.mark.parametrize("timeout", ["-1", "-0.5"])
def test_refuses_a_negative_timeout(timeout):
    with pytest.raises(ImproperlyConfigured, match="DJANGO_SGI_ADMISSION_TIMEOUT must not be"):
        read_request_admission(_environment(timeout=timeout))
