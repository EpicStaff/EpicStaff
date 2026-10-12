import pytest
from django.conf import settings

from django_app.settings.base import parse_callback_hosts


def test_session_callback_settings_are_defined():
    assert isinstance(settings.SESSION_CALLBACK_ALLOWED_HOSTS, list)
    assert isinstance(settings.CHAT_ENABLED, bool)


@pytest.mark.parametrize(
    "values, expected",
    [(None, []), ([" Chat ", "", "api"], ["chat", "api"]), ([], [])],
)
def test_parse_callback_hosts(values, expected):
    assert parse_callback_hosts(values) == expected
