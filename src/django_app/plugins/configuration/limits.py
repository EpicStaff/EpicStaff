"""Per-plugin limits: what the manifest asks for, the platform maximums, and the SuperAdmin's overrides.

The effective limit is the lowest of the three, so an override can only lower what the
plugin gets. This version enforces `memory_mb` (the node's watchdog) and `cpu_priority`
(nice); the other limits are recorded and checked against the maximums but nothing applies
them yet.
"""

from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import transaction
from epicstaff_plugin.contracts.manifest import PluginManifest
from epicstaff_plugin.problems import Problem

from plugins.audit import log_limit_overrides
from plugins.exceptions import InvalidPluginLimitsError
from plugins.models import Plugin

NUMERIC_LIMITS = ("memory_mb", "db_connections", "statement_timeout_seconds", "requests_per_minute")
CPU_PRIORITY = "cpu_priority"
LOW_PRIORITY = "low"
NORMAL_PRIORITY = "normal"
LIMIT_NAMES = (*NUMERIC_LIMITS, CPU_PRIORITY)
# What a backend gets for a limit its manifest leaves out, capped by the platform maximum.
PLATFORM_DEFAULTS: dict[str, Any] = {
    "memory_mb": 256,
    "db_connections": 5,
    "statement_timeout_seconds": 30,
    "requests_per_minute": 120,
    CPU_PRIORITY: NORMAL_PRIORITY,
}
# Which limits something applies in this version (the database ones and the request rate
# arrive with plugin databases and service accounts).
ENFORCED_LIMITS = {
    "memory_mb": True,
    CPU_PRIORITY: True,
    "db_connections": False,
    "statement_timeout_seconds": False,
    "requests_per_minute": False,
}
# The environment variable behind each platform maximum, for the plugins.E009 check.
MAXIMUM_SETTINGS = {
    "memory_mb": "PLUGINS_MAX_PROCESS_MEMORY_MB",
    "db_connections": "PLUGINS_MAX_DB_CONNECTIONS",
    "statement_timeout_seconds": "PLUGINS_MAX_STATEMENT_TIMEOUT_SECONDS",
    "requests_per_minute": "PLUGINS_MAX_REQUESTS_PER_MINUTE",
    "public_requests_per_minute": "PLUGINS_MAX_PUBLIC_REQUESTS_PER_MINUTE",
    "request_body_mb": "PLUGINS_MAX_REQUEST_BODY_MB",
}


def positive_integer(value: Any) -> int | None:
    """Return `value` as a positive integer when it is one (as a number or decimal text), else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    text = str(value).strip()
    if not text.isascii() or not text.isdigit():
        return None
    number = int(text)
    return number if number > 0 else None


@dataclass(frozen=True)
class PlatformMaximums:
    """The deployment's caps on what a plugin backend may ask for (`PLUGINS_MAX_*`)."""

    memory_mb: int
    db_connections: int
    statement_timeout_seconds: int
    requests_per_minute: int
    public_requests_per_minute: int
    request_body_mb: int

    @classmethod
    def from_settings(cls) -> "PlatformMaximums":
        # The plugins.E009 start-up check guarantees every value is a positive integer
        # while the platform is on.
        return cls(
            **{
                name: positive_integer(getattr(settings, setting))
                for name, setting in MAXIMUM_SETTINGS.items()
            }
        )

    def limit(self, name: str) -> int:
        return getattr(self, name)

    @property
    def max_body_kb(self) -> int:
        return self.request_body_mb * 1024

    def as_limit_values(self) -> dict[str, int]:
        return {name: self.limit(name) for name in NUMERIC_LIMITS}


def manifest_limit_problems(manifest: PluginManifest, maximums: PlatformMaximums) -> list[Problem]:
    """Refuse a manifest that asks for more than this deployment's maximums."""
    problems = []
    if manifest.limits is not None:
        for name in NUMERIC_LIMITS:
            requested = getattr(manifest.limits, name)
            if requested is not None and requested > maximums.limit(name):
                problems.append(
                    Problem(
                        f"manifest.limits.{name}",
                        f"asks for {requested}; this EpicStaff allows at most {maximums.limit(name)}",
                    )
                )
    for index, public_path in enumerate(manifest.public_paths):
        loc = f"manifest.public_paths[{index}]"
        if public_path.rate_limit_per_minute > maximums.public_requests_per_minute:
            problems.append(
                Problem(
                    f"{loc}.rate_limit_per_minute",
                    f"is {public_path.rate_limit_per_minute}; this EpicStaff allows at most "
                    f"{maximums.public_requests_per_minute}",
                )
            )
        if public_path.max_body_kb > maximums.max_body_kb:
            problems.append(
                Problem(
                    f"{loc}.max_body_kb",
                    f"is {public_path.max_body_kb}; this EpicStaff allows at most "
                    f"{maximums.max_body_kb}",
                )
            )
    return problems


@dataclass(frozen=True)
class PluginLimits:
    """Every view of one plugin's limits, as the Limits tab shows them."""

    requested: dict[str, Any]
    platform_max: dict[str, int]
    overrides: dict[str, Any]
    effective: dict[str, Any]
    enforced: dict[str, bool]


def plugin_limits(plugin: Plugin, manifest: PluginManifest) -> PluginLimits:
    """Work out a plugin's limits from its current manifest, the maximums and its overrides."""
    maximums = PlatformMaximums.from_settings()
    requested = _requested(manifest, maximums)
    overrides = dict(plugin.limit_overrides or {})
    effective = {
        name: min(
            value
            for value in (requested[name], maximums.limit(name), overrides.get(name))
            if value is not None
        )
        for name in NUMERIC_LIMITS
    }
    effective[CPU_PRIORITY] = (
        LOW_PRIORITY
        if LOW_PRIORITY in (requested[CPU_PRIORITY], overrides.get(CPU_PRIORITY))
        else NORMAL_PRIORITY
    )
    return PluginLimits(
        requested=requested,
        platform_max=maximums.as_limit_values(),
        overrides=overrides,
        effective=effective,
        enforced=dict(ENFORCED_LIMITS),
    )


def _requested(manifest: PluginManifest, maximums: PlatformMaximums) -> dict[str, Any]:
    """Each limit as the manifest asks for it, or the platform default capped by the maximum.

    A value the manifest names stays as written, even above a maximum lowered after the
    upload, so the Limits tab shows what the plugin asked for; `effective` applies the cap.
    """
    declared = manifest.limits.model_dump() if manifest.limits is not None else {}
    requested = {}
    for name in LIMIT_NAMES:
        value = declared.get(name)
        if value is not None:
            requested[name] = value
        elif name == CPU_PRIORITY:
            requested[name] = PLATFORM_DEFAULTS[name]
        else:
            requested[name] = min(PLATFORM_DEFAULTS[name], maximums.limit(name))
    return requested


class PluginLimitsService:
    """The SuperAdmin's overrides, which can only lower a plugin's limits."""

    def update_overrides(
        self, plugin: Plugin, manifest: PluginManifest, changes: dict[str, Any], actor
    ) -> PluginLimits:
        """Apply `changes` (`null` removes an override) and return the plugin's limits.

        A changed `memory_mb` or `cpu_priority` changes the node's desired state, which
        restarts the process with the new cap.

        Raises:
            InvalidPluginLimitsError: An unknown limit, a value that is not a positive
                integer or is above `min(requested, platform maximum)`, or a `cpu_priority`
                other than `low`.
        """
        current = plugin_limits(plugin, manifest)
        problems = []
        for name, value in changes.items():
            loc = f"overrides.{name}"
            if name not in LIMIT_NAMES:
                problems.append(Problem(loc, "is not a limit"))
            elif value is None:
                continue
            elif name == CPU_PRIORITY:
                if value != LOW_PRIORITY:
                    problems.append(Problem(loc, "can only be lowered to low"))
            elif (number := _strict_positive_integer(value)) is None:
                problems.append(Problem(loc, "must be a positive integer"))
            elif number > (ceiling := min(current.requested[name], current.platform_max[name])):
                problems.append(Problem(loc, f"can only lower the limit, to at most {ceiling}"))
        if problems:
            raise InvalidPluginLimitsError(problems)
        with transaction.atomic():
            locked = Plugin.objects.select_for_update().get(pk=plugin.pk)
            overrides = dict(locked.limit_overrides or {})
            for name, value in changes.items():
                if value is None:
                    overrides.pop(name, None)
                else:
                    overrides[name] = value
            locked.limit_overrides = overrides
            locked.save(update_fields=["limit_overrides", "updated_at"])
        log_limit_overrides(actor, plugin.identifier, overrides)
        return plugin_limits(locked, manifest)


def _strict_positive_integer(value: Any) -> int | None:
    # JSON numbers only: "128" or 128.0 is not an integer override.
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None
