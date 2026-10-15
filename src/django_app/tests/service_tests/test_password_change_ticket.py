import fakeredis
import pytest
from types import SimpleNamespace

from django.test import override_settings
from unittest.mock import patch

from rbac.identity.passwords.change_ticket import PasswordChangeTicketService


@pytest.fixture
def fake_redis():
    fake = fakeredis.FakeStrictRedis()
    with patch(
        "rbac.identity.passwords.change_ticket.get_redis_connection",
        return_value=fake,
    ):
        yield fake


# Env.time() parses durations such as "5m" into float seconds; redis-py rejects float `ex`.
@override_settings(PASSWORD_CHANGE_TICKET_TTL=300.0)
def test_issue_accepts_float_ttl_from_env_time(fake_redis):
    user = SimpleNamespace(pk=42)
    service = PasswordChangeTicketService()

    ticket, expires_in = service.issue(user)

    assert expires_in == 300
    assert isinstance(expires_in, int)
    assert 0 < fake_redis.ttl(service._cache_key(ticket)) <= 300
    assert fake_redis.get(service._cache_key(ticket)) == b"42"
