import ipaddress

import pytest
from common.humanize import Rate
from pydantic import ValidationError
from settings import Settings, load_settings

from src.shared.envtools import Env, EnvironmentBlankError, EnvironmentNotFoundError

# The src/env.yaml defaults, as compose hands them to the container.
DURATION_AND_RATE_ENV = {
    "CHAT_DJANGO_TIMEOUT": "10s",
    "CHAT_IP_MESSAGE_RATE": "30/m",
    "CHAT_IP_CONVERSATION_RATE": "20/h",
    "CHAT_RECONCILE_INTERVAL": "1m",
    "CHAT_STALE_RUN_AFTER": "5m",
    "CHAT_UNCONFIRMED_START_RELEASE": "1m",
    "CHAT_RUN_TIMEOUT": "30m",
    "CHAT_EVENT_RETENTION": "7d",
    "CHAT_CALLBACK_MAX_SKEW": "5m",
    "CHAT_IDENTITY_CACHE_TTL": "1m",
    "CHAT_TICKET_TTL": "1m",
    "CHAT_VISITOR_TOKEN_IDLE_TTL": "30d",
    "CHAT_STREAM_MAX_LIFETIME": "30m",
    "CHAT_STREAM_PING_INTERVAL": "15s",
}


REQUIRED = {
    "CHAT_PORT": "8200",
    "CHAT_LOG_LEVEL": "INFO",
    "CHAT_DB_HOST": "chatdb",
    "CHAT_DB_PORT": "5432",
    "CHAT_DB_NAME": "chat",
    "CHAT_DB_USER": "chat",
    "CHAT_DB_PASSWORD": "pw",
    "REDIS_HOST": "redis",
    "REDIS_PORT": "6379",
    "REDIS_USER": "none",
    "REDIS_PASSWORD": "none",
    "CHAT_REDIS_DB": "2",
    "CHAT_DJANGO_URL": "http://django_app:8000",
    "CHAT_DJANGO_HOST_HEADER": "localhost",
    "DJANGO_API_KEY": "k" * 32,
    "CHAT_PUBLIC_BASE_URL": "http://localhost",
    "CHAT_CALLBACK_URL": "http://chat:8200/chat/internal/v1/session-callbacks",
    "CHAT_TRUSTED_PROXIES": "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16",
}


# The src/env.yaml defaults; plain token counts.
BUDGET_ENV = {
    "CHAT_CONVERSATION_TOKEN_BUDGET_DEFAULT": "200000",
    "CHAT_CONVERSATION_TOKEN_BUDGET_MAX": "1000000",
    "CHAT_DAILY_TOKEN_BUDGET_DEFAULT": "1000000",
    "CHAT_DAILY_TOKEN_BUDGET_MAX": "50000000",
}


# The src/env.yaml defaults; durations a desk's inactivity rules take.
LIFECYCLE_ENV = {
    "CHAT_RESPONSE_TIME_DEFAULT": "10m",
    "CHAT_RESPONSE_TIME_MAX": "1d",
    "CHAT_CLOSE_AFTER_DEFAULT": "24h",
    "CHAT_CLOSE_AFTER_MAX": "30d",
}

ALL_ENV = {**REQUIRED, **DURATION_AND_RATE_ENV, **BUDGET_ENV, **LIFECYCLE_ENV}


@pytest.fixture
def environ(monkeypatch):
    """The process environment holding exactly ALL_ENV for the settings (conftest exports its own)."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)
    for name, value in ALL_ENV.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


@pytest.fixture
def load(environ):
    def _load(**overrides) -> Settings:
        for name, value in overrides.items():
            environ.setenv(name, value)
        return load_settings(Env())

    return _load


def test_every_field_is_read_from_the_environment():
    assert set(Settings.model_fields) == set(ALL_ENV)


def test_database_url_uses_psycopg_async_driver(load):
    assert load().database_url == "postgresql+psycopg://chat:pw@chatdb:5432/chat"


def test_redis_url_without_credentials(load):
    assert load().redis_url == "redis://redis:6379/2"


def test_redis_url_with_credentials(load):
    assert load(REDIS_USER="bob", REDIS_PASSWORD="s3cret").redis_url == "redis://bob:s3cret@redis:6379/2"


def test_redis_url_with_a_password_and_no_user(load):
    assert load(REDIS_PASSWORD="s3cret").redis_url == "redis://:s3cret@redis:6379/2"


@pytest.mark.parametrize(
    "url, expected",
    [
        ("http://django_app:8000", "http://django_app:8000"),
        ("http://localhost:8000", "http://localhost:8000"),
        ("http://127.0.0.1:8000", "http://127.0.0.1:8000"),
        ("http://192.168.1.20", "http://192.168.1.20"),
        ("http://[fd00::5]:8000", "http://[fd00::5]:8000"),
        ("https://epicstaff.example.com", "https://epicstaff.example.com"),
        ("https://epicstaff.example.com/", "https://epicstaff.example.com"),
        ("https://203.0.113.10", "https://203.0.113.10"),
        ("http://10.0.0.5:8000//", "http://10.0.0.5:8000"),
    ],
)
def test_django_url_accepts_an_http_or_https_origin(load, url, expected):
    assert load(CHAT_DJANGO_URL=url).CHAT_DJANGO_URL == expected


@pytest.mark.parametrize(
    "url",
    [
        "ftp://django_app:8000",
        "django_app:8000",
        "http://",
        "https://epicstaff.example.com/api",
        "http://django_app:8000?x=1",
        "http://django_app:port",
        "http://epicstaff.example.com",
        "http://8.8.8.8:8000",
        "http://[2001:4860::8888]",
        "http://134744072",
        "http://0x08080808",
        "none",
    ],
)
def test_django_url_rejects_anything_but_an_http_or_https_origin(load, url):
    with pytest.raises(ValidationError, match="CHAT_DJANGO_URL"):
        load(CHAT_DJANGO_URL=url)


@pytest.mark.parametrize("name", sorted(ALL_ENV))
def test_every_setting_is_required_with_no_code_default(environ, name):
    environ.delenv(name)
    with pytest.raises(EnvironmentNotFoundError, match=name):
        load_settings(Env())


@pytest.mark.parametrize("name", ["DJANGO_API_KEY", "CHAT_DB_PASSWORD"])
@pytest.mark.parametrize("value", ["", "   ", "none", "NONE"])
def test_secrets_refuse_empty_or_none(load, name, value):
    with pytest.raises(EnvironmentBlankError, match=name):
        load(**{name: value})


@pytest.mark.parametrize("value", ["", "none", "None"])
def test_django_host_header_none_or_empty_means_absent(load, value):
    assert load(CHAT_DJANGO_HOST_HEADER=value).CHAT_DJANGO_HOST_HEADER is None


def test_django_host_header_is_kept_when_set(load):
    assert load(CHAT_DJANGO_HOST_HEADER="localhost").CHAT_DJANGO_HOST_HEADER == "localhost"


def test_trusted_networks_parse_cidrs(load):
    networks = load(CHAT_TRUSTED_PROXIES="10.0.0.0/8, 192.168.1.5").trusted_networks
    assert ipaddress.ip_address("10.1.2.3") in networks[0]
    assert ipaddress.ip_address("192.168.1.5") in networks[1]


@pytest.mark.parametrize("value", ["10.0.0.0/33", "not-a-network", "10.0.0.0/8,300.1.1.1", "none", "", " , "])
def test_trusted_proxies_reject_an_invalid_cidr_at_startup(load, value):
    with pytest.raises(ValidationError, match="CHAT_TRUSTED_PROXIES"):
        load(CHAT_TRUSTED_PROXIES=value)


def test_compose_style_env_values_load(load):
    settings = load()
    assert settings.CHAT_PORT == 8200
    assert settings.CHAT_DB_PORT == 5432
    assert settings.CHAT_REDIS_DB == 2
    assert (settings.REDIS_USER, settings.REDIS_PASSWORD) == (None, None)
    assert settings.CHAT_DJANGO_TIMEOUT == 10.0
    assert settings.CHAT_IP_MESSAGE_RATE == Rate(limit=30, window_seconds=60)
    assert settings.CHAT_IP_CONVERSATION_RATE == Rate(limit=20, window_seconds=3600)
    assert settings.CHAT_RECONCILE_INTERVAL == 60
    assert settings.CHAT_STALE_RUN_AFTER == 300
    assert settings.CHAT_UNCONFIRMED_START_RELEASE == 60
    assert settings.CHAT_RUN_TIMEOUT == 1800
    assert settings.CHAT_EVENT_RETENTION == 7 * 86400
    assert settings.CHAT_CALLBACK_MAX_SKEW == 300
    assert settings.CHAT_IDENTITY_CACHE_TTL == 60
    assert settings.CHAT_TICKET_TTL == 60
    assert settings.CHAT_VISITOR_TOKEN_IDLE_TTL == 30 * 86400
    assert settings.CHAT_STREAM_MAX_LIFETIME == 1800.0
    assert settings.CHAT_STREAM_PING_INTERVAL == 15.0
    assert isinstance(settings.CHAT_TICKET_TTL, int)  # Redis TTLs must be whole seconds


def test_reconcile_interval_accepts_zero_which_turns_the_loop_off(load):
    assert load(CHAT_RECONCILE_INTERVAL="0").CHAT_RECONCILE_INTERVAL == 0


def test_whole_second_setting_rejects_a_fraction(load):
    with pytest.raises(ValidationError, match="CHAT_TICKET_TTL"):
        load(CHAT_TICKET_TTL="1.5s")


DURATIONS = [name for name in DURATION_AND_RATE_ENV if not name.endswith("_RATE")]
POSITIVE_DURATIONS = [name for name in DURATIONS if name != "CHAT_RECONCILE_INTERVAL"]


@pytest.mark.parametrize("name", POSITIVE_DURATIONS)
@pytest.mark.parametrize("value", ["0", "0s", "0.0m"])
def test_positive_duration_rejects_zero(load, name, value):
    with pytest.raises(ValidationError, match=name):
        load(**{name: value})


@pytest.mark.parametrize("name", DURATIONS)
@pytest.mark.parametrize("value", ["-5", "-5s", "inf", "nan", "10w", "10ms", "1h30m", "ten", "1,5h", "9999999999d"])
def test_duration_rejects_what_is_not_a_finite_non_negative_duration(load, name, value):
    with pytest.raises(ValidationError, match=name):
        load(**{name: value})


@pytest.mark.parametrize("name", ["CHAT_IP_MESSAGE_RATE", "CHAT_IP_CONVERSATION_RATE"])
@pytest.mark.parametrize("value", ["30", "0/m", "30/w"])
def test_rate_rejects_a_malformed_value(load, name, value):
    with pytest.raises(ValidationError, match=name):
        load(**{name: value})


def test_values_load_from_the_dotenv_file(environ, tmp_path):
    environ.delenv("CHAT_IP_MESSAGE_RATE")
    env_file = tmp_path / ".env"
    env_file.write_text("CHAT_IP_MESSAGE_RATE=5/s\n", encoding="utf-8")
    environment = Env()
    environment.read_env(env_file)
    assert load_settings(environment).CHAT_IP_MESSAGE_RATE == Rate(limit=5, window_seconds=1)


@pytest.mark.parametrize("release", ["10s", "5s"])
def test_unconfirmed_start_release_must_outlast_the_django_timeout(load, release):
    with pytest.raises(ValidationError, match="CHAT_UNCONFIRMED_START_RELEASE"):
        load(CHAT_DJANGO_TIMEOUT="10s", CHAT_UNCONFIRMED_START_RELEASE=release)


def test_budget_settings_load_as_token_counts(load):
    settings = load()
    assert settings.CHAT_CONVERSATION_TOKEN_BUDGET_DEFAULT == 200_000
    assert settings.CHAT_CONVERSATION_TOKEN_BUDGET_MAX == 1_000_000
    assert settings.CHAT_DAILY_TOKEN_BUDGET_DEFAULT == 1_000_000
    assert settings.CHAT_DAILY_TOKEN_BUDGET_MAX == 50_000_000


@pytest.mark.parametrize("name", list(BUDGET_ENV))
@pytest.mark.parametrize("value", ["0", "-1", "10k", "2147483648"])
def test_budget_setting_must_be_a_positive_token_count(load, name, value):
    with pytest.raises(ValidationError, match=name):
        load(**{name: value})


@pytest.mark.parametrize("kind", ["CONVERSATION", "DAILY"])
def test_startup_rejects_a_budget_default_above_its_max(load, kind):
    with pytest.raises(ValidationError, match=f"CHAT_{kind}_TOKEN_BUDGET_DEFAULT must not exceed"):
        load(**{f"CHAT_{kind}_TOKEN_BUDGET_DEFAULT": "1001", f"CHAT_{kind}_TOKEN_BUDGET_MAX": "1000"})
    load(**{f"CHAT_{kind}_TOKEN_BUDGET_DEFAULT": "1000", f"CHAT_{kind}_TOKEN_BUDGET_MAX": "1000"})


def test_lifecycle_settings_load_as_whole_seconds(load):
    settings = load()
    assert (settings.CHAT_RESPONSE_TIME_DEFAULT, settings.CHAT_RESPONSE_TIME_MAX) == (600, 86_400)
    assert (settings.CHAT_CLOSE_AFTER_DEFAULT, settings.CHAT_CLOSE_AFTER_MAX) == (86_400, 30 * 86_400)


@pytest.mark.parametrize("name", list(LIFECYCLE_ENV))
@pytest.mark.parametrize("value", ["0", "59s", "60.5s", "2147483648", "soon"])
def test_a_lifecycle_setting_is_whole_seconds_from_a_minute_up_to_the_column_limit(load, name, value):
    with pytest.raises(ValidationError, match=name):
        load(**{name: value})


def test_the_smallest_lifecycle_durations_are_a_minute(load):
    settings = load(CHAT_RESPONSE_TIME_DEFAULT="60", CHAT_RESPONSE_TIME_MAX="1m", CHAT_CLOSE_AFTER_DEFAULT="1m", CHAT_CLOSE_AFTER_MAX="60s")
    assert (settings.CHAT_RESPONSE_TIME_DEFAULT, settings.CHAT_CLOSE_AFTER_MAX) == (60, 60)


@pytest.mark.parametrize("prefix", ["CHAT_RESPONSE_TIME", "CHAT_CLOSE_AFTER"])
def test_startup_rejects_a_lifecycle_default_above_its_max(load, prefix):
    with pytest.raises(ValidationError, match=f"{prefix}_DEFAULT must not exceed {prefix}_MAX"):
        load(**{f"{prefix}_DEFAULT": "2h", f"{prefix}_MAX": "1h"})
    load(**{f"{prefix}_DEFAULT": "1h", f"{prefix}_MAX": "1h"})
