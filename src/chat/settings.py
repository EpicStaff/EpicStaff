import ipaddress
import socket
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

from common.humanize import Rate, to_rate
from common.utils import INTEGER_COLUMN_MAX
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    computed_field,
    model_validator,
)
from src.shared import humanize
from src.shared.envtools import Env

BASE_DIR: Path = Path(__file__).resolve().parent

env = Env()

if not env.bool("RUN_IN_DOCKER", False):
    env.read_env(BASE_DIR / "../.env")


def _duration(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return humanize.to_time(value)
    except OverflowError as error:  # pydantic names the variable only for a ValueError
        raise ValueError(f"duration out of range: {value}") from error


def _rate(value: Any) -> Any:
    return to_rate(value) if isinstance(value, str) else value


def _networks(value: Any) -> Any:
    if isinstance(value, str):
        value = value.split(",")
    networks = tuple(
        ipaddress.ip_network(part.strip(), strict=False)
        for part in value or ()
        if isinstance(part, str) and part.strip()
    )
    # No trusted proxy ("none" or empty) would make every visitor share nginx's address and rate limit.
    if not networks:
        raise ValueError("must list the CIDRs of the proxies in front of the service")
    return networks


# Durations read "10s", "5m", "1h", "7d" or a plain number of seconds (shared humanize); the type
# says int or float seconds. Positive is the norm: 0 would wipe history, stop every run, break
# Redis SET EX or busy-loop pings.
Seconds = Annotated[int, Field(ge=0), BeforeValidator(_duration)]
PositiveSeconds = Annotated[int, Field(gt=0), BeforeValidator(_duration)]
PositiveFractionalSeconds = Annotated[
    float, Field(gt=0, allow_inf_nan=False), BeforeValidator(_duration)
]
# Rates read "<count>/<unit>", e.g. "30/m".
RateLimit = Annotated[Rate, BeforeValidator(_rate)]
# A plain token count that fits the INTEGER budget columns.
TokenCount = Annotated[int, Field(gt=0, le=INTEGER_COLUMN_MAX)]
# A binding's inactivity duration: whole seconds, at least the minute a binding may set, and
# fitting its INTEGER column.
BindingDuration = Annotated[int, Field(ge=60, le=INTEGER_COLUMN_MAX), BeforeValidator(_duration)]
# Comma-separated CIDRs; a bare address is its own /32 or /128.
Networks = Annotated[
    tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...], BeforeValidator(_networks)
]
# Empty means: send the Host that the URL implies (the env reader already maps "none" to None).
OptionalHeader = Annotated[
    str | None, BeforeValidator(lambda value: value if value and value.strip() else None)
]


def _internal_host(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            # The resolver also reads short and numeric forms ("134744072", "0x8080808") as IPv4.
            address = ipaddress.ip_address(socket.inet_aton(host))
        except OSError:
            return "." not in host
    return address.is_private or address.is_loopback


def _origin(value: str) -> str:
    """Accept an http(s) origin, optionally with a port, and drop a trailing slash."""
    value = value.strip().rstrip("/")
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("must be an http:// or https:// URL with a host")
    if parts.path or parts.query or parts.fragment:
        raise ValueError("must be scheme://host[:port] with no path, query or fragment")
    # Every system call carries DJANGO_API_KEY: plain http only where it cannot leave a private network.
    if parts.scheme == "http" and not _internal_host(parts.hostname):
        raise ValueError(
            "http is allowed only for a single-label host (compose service, localhost) "
            "or a private or loopback IP; use https"
        )
    _ = parts.port  # Raises ValueError on a non-numeric or out-of-range port.
    return value


# scheme://host[:port], no path: the client appends the /api/... paths itself.
Origin = Annotated[str, AfterValidator(_origin)]


class Settings(BaseModel):
    """Every knob the service reads, with the env variable name as the field name.

    Built by `load_settings` from the environment; defaults live only in src/env.yaml.
    """

    model_config = ConfigDict(frozen=True)

    CHAT_PORT: int
    CHAT_LOG_LEVEL: str

    CHAT_DB_HOST: str
    CHAT_DB_PORT: int
    CHAT_DB_NAME: str
    CHAT_DB_USER: str
    CHAT_DB_PASSWORD: str

    REDIS_HOST: str
    REDIS_PORT: int
    REDIS_USER: str | None
    REDIS_PASSWORD: str | None
    CHAT_REDIS_DB: int

    CHAT_DJANGO_URL: Origin
    # Overrides the Host header when Django's ALLOWED_HOSTS does not list the URL's host
    # (the container name django_app may not be allowed, "localhost" is).
    CHAT_DJANGO_HOST_HEADER: OptionalHeader
    DJANGO_API_KEY: str
    CHAT_DJANGO_TIMEOUT: PositiveFractionalSeconds
    # The manager presents it to /chat/internal/ (retention purge); it can delete conversations.
    CHAT_INTERNAL_API_KEY: str

    CHAT_PUBLIC_BASE_URL: str
    CHAT_CALLBACK_URL: str
    CHAT_TRUSTED_PROXIES: Networks
    CHAT_IP_MESSAGE_RATE: RateLimit
    CHAT_IP_CONVERSATION_RATE: RateLimit

    # 0 turns the reconcile loop off, and with it the desks' inactivity timers (the tests rely on it).
    CHAT_RECONCILE_INTERVAL: Seconds
    CHAT_STALE_RUN_AFTER: PositiveSeconds
    # A released unconfirmed run is bounded by crew's token budget and the manager TTL, not CHAT_RUN_TIMEOUT.
    CHAT_UNCONFIRMED_START_RELEASE: PositiveSeconds
    CHAT_RUN_TIMEOUT: PositiveSeconds
    CHAT_EVENT_RETENTION: PositiveSeconds
    CHAT_CALLBACK_MAX_SKEW: PositiveSeconds
    CHAT_IDENTITY_CACHE_TTL: PositiveSeconds
    CHAT_VISITOR_TOKEN_IDLE_TTL: PositiveSeconds
    CHAT_TICKET_TTL: PositiveSeconds
    CHAT_STREAM_MAX_LIFETIME: PositiveFractionalSeconds
    CHAT_STREAM_PING_INTERVAL: PositiveFractionalSeconds

    # Binding token budgets are always finite: the default fills an omitted budget, the max caps any.
    CHAT_CONVERSATION_TOKEN_BUDGET_DEFAULT: TokenCount
    CHAT_CONVERSATION_TOKEN_BUDGET_MAX: TokenCount
    CHAT_DAILY_TOKEN_BUDGET_DEFAULT: TokenCount
    CHAT_DAILY_TOKEN_BUDGET_MAX: TokenCount

    # A desk's inactivity rules: the default fills an omitted duration, the max caps any.
    CHAT_RESPONSE_TIME_DEFAULT: BindingDuration
    CHAT_RESPONSE_TIME_MAX: BindingDuration
    CHAT_CLOSE_AFTER_DEFAULT: BindingDuration
    CHAT_CLOSE_AFTER_MAX: BindingDuration

    @model_validator(mode="after")
    def _release_waits_out_a_start(self) -> "Settings":
        # A shorter release would free the slot of a start Django is still answering.
        if self.CHAT_UNCONFIRMED_START_RELEASE <= self.CHAT_DJANGO_TIMEOUT:
            raise ValueError(
                "CHAT_UNCONFIRMED_START_RELEASE must be longer than CHAT_DJANGO_TIMEOUT."
            )
        return self

    @model_validator(mode="after")
    def _defaults_within_caps(self) -> "Settings":
        for prefix in (
            "CHAT_CONVERSATION_TOKEN_BUDGET",
            "CHAT_DAILY_TOKEN_BUDGET",
            "CHAT_RESPONSE_TIME",
            "CHAT_CLOSE_AFTER",
        ):
            default_name, max_name = f"{prefix}_DEFAULT", f"{prefix}_MAX"
            if getattr(self, default_name) > getattr(self, max_name):
                raise ValueError(f"{default_name} must not exceed {max_name}.")
        return self

    @computed_field
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.CHAT_DB_USER}:{self.CHAT_DB_PASSWORD}"
            f"@{self.CHAT_DB_HOST}:{self.CHAT_DB_PORT}/{self.CHAT_DB_NAME}"
        )

    @computed_field
    @property
    def redis_url(self) -> str:
        credentials = ""
        if self.REDIS_PASSWORD:
            credentials = f"{self.REDIS_USER or ''}:{self.REDIS_PASSWORD}@"
        return f"redis://{credentials}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.CHAT_REDIS_DB}"

    @property
    def trusted_networks(self) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        return list(self.CHAT_TRUSTED_PROXIES)


_FIELDS_READ_AS_SECRETS = ("CHAT_DB_PASSWORD", "DJANGO_API_KEY", "CHAT_INTERNAL_API_KEY")


def load_settings(environment: Env = env) -> Settings:
    """Read every setting from the environment; a missing variable fails startup.

    Secrets go through `Env.secret`, which refuses empty and "none"; everything else is read as
    a string ("none" becomes None) and typed and validated by `Settings`, so a bad value names
    its variable.

    Raises:
        EnvironmentNotFoundError: A variable is missing.
        EnvironmentBlankError: A secret is empty or "none".
        pydantic.ValidationError: A value is malformed or out of range.
    """
    values: dict[str, Any] = {
        name: environment.secret(name) if name in _FIELDS_READ_AS_SECRETS else environment.str(name)
        for name in Settings.model_fields
    }
    return Settings(**values)
