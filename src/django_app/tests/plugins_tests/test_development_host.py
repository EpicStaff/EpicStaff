"""The one host plugin development mode routes to, resolved by django_app and cached."""

import socket

from plugins.development.development_host import ADDRESS_CACHE_SECONDS, DevelopmentHost

from tests.plugins_tests.conftest import FakeResolver


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _host(resolver, clock=None) -> DevelopmentHost:
    return DevelopmentHost(resolver=resolver, clock=clock or FakeClock())


def test_only_host_docker_internal_is_resolved_and_only_for_ipv4():
    resolver = FakeResolver("192.168.65.254")

    assert _host(resolver).address() == "192.168.65.254"
    assert resolver.calls == [("host.docker.internal", None, socket.AF_INET, socket.SOCK_STREAM)]


def test_the_first_ipv4_address_is_the_answer():
    entries = [
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fdc4:f303:9324::254", 0, 0, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.65.254", 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.65.253", 0)),
    ]

    assert _host(lambda *args: entries).address() == "192.168.65.254"


def test_an_answer_without_ipv4_is_no_address():
    entries = [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fdc4:f303:9324::254", 0, 0, 0))]

    assert _host(lambda *args: entries).address() is None


def test_an_address_is_kept_for_sixty_seconds():
    resolver = FakeResolver("192.168.65.254")
    clock = FakeClock()
    host = _host(resolver, clock)

    host.address()
    resolver.address = "192.168.65.200"
    clock.now += ADDRESS_CACHE_SECONDS - 1
    within = host.address()
    clock.now += 1
    after = host.address()

    assert (within, after) == ("192.168.65.254", "192.168.65.200")
    assert len(resolver.calls) == 2


def test_a_failure_is_no_address_kept_and_logged_at_most_once_a_minute(log_messages):
    resolver = FakeResolver(None)
    clock = FakeClock()
    host = _host(resolver, clock)

    answers = [host.address() for _ in range(3)]
    clock.now += ADDRESS_CACHE_SECONDS
    answers.append(host.address())

    assert answers == [None, None, None, None]
    assert len(resolver.calls) == 2
    lines = [line for line in log_messages if line.startswith("plugins.development.host_unresolved")]
    assert lines == ["plugins.development.host_unresolved host=host.docker.internal"] * 2


def test_a_lookup_error_of_any_kind_is_no_address():
    def refuses(*args):
        raise OSError("network is unreachable")

    assert _host(refuses).address() is None


def test_forgetting_resolves_again():
    resolver = FakeResolver("192.168.65.254")
    host = _host(resolver)

    host.address()
    host.forget()
    host.address()

    assert len(resolver.calls) == 2
