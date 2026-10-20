"""Instance-wide data retention policy, shared by django_app and manager.

The policy comes from the environment: for each data type a default number of days and an
optional cap an organization admin may not exceed. 0 days means "keep forever".
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from src.shared.envtools import Env, EnvironmentNotFoundError

RETENTION_CHOICES: tuple[int, ...] = (0, 30, 90, 180, 365)

_CAP_CHOICES: tuple[int, ...] = tuple(days for days in RETENTION_CHOICES if days > 0)


class DataType(StrEnum):
    SESSIONS = "sessions"
    CONVERSATIONS = "conversations"
    AUDIT = "audit"


@dataclass(frozen=True)
class RetentionRule:
    """Retention limits for one data type.

    Attributes:
        default_days: Days kept when the organization has not chosen a value; 0 keeps forever.
        max_days: Highest value an organization may choose, or None for no cap. Never 0.
    """

    default_days: int
    max_days: int | None


@dataclass(frozen=True)
class RetentionPolicy:
    rules: Mapping[DataType, RetentionRule]

    def __post_init__(self):
        object.__setattr__(self, "rules", MappingProxyType(dict(self.rules)))


_RULE_VARIABLES: dict[DataType, tuple[str, str]] = {
    DataType.SESSIONS: ("RETENTION_SESSIONS_DAYS", "RETENTION_SESSION_MAX_DAYS"),
    DataType.CONVERSATIONS: ("RETENTION_CONVERSATIONS_DAYS", "RETENTION_CONVERSATION_MAX_DAYS"),
    DataType.AUDIT: ("RETENTION_AUDIT_DAYS", "RETENTION_AUDIT_MAX_DAYS"),
}


def load_retention_policy(env: Env) -> RetentionPolicy:
    """Read and validate the retention policy from the environment.

    The default variables are required; a cap that is absent or ``none`` means no cap.

    Raises:
        ValueError: A variable is missing, not a whole number, not one of
            RETENTION_CHOICES, or inconsistent with its pair. The message names the
            offending variable.
    """
    return RetentionPolicy(
        rules={
            data_type: _load_rule(env, default_variable, max_variable)
            for data_type, (default_variable, max_variable) in _RULE_VARIABLES.items()
        }
    )


def _load_rule(env: Env, default_variable: str, max_variable: str) -> RetentionRule:
    default_days = _read_days(env, default_variable, required=True)
    max_days = _read_days(env, max_variable, required=False)

    if default_days not in RETENTION_CHOICES:
        raise ValueError(f"{default_variable}={default_days} must be one of {RETENTION_CHOICES}.")
    if max_days is None:
        return RetentionRule(default_days=default_days, max_days=None)

    if max_days not in _CAP_CHOICES:
        raise ValueError(
            f"{max_variable}={max_days} must be one of {_CAP_CHOICES}, or none for no cap."
        )
    if default_days == 0:
        raise ValueError(
            f"{default_variable}=0 keeps data forever, which {max_variable}={max_days} forbids. "
            f"Choose a default of at most {max_days} days or set {max_variable}=none."
        )
    if default_days > max_days:
        raise ValueError(
            f"{default_variable}={default_days} is above its cap {max_variable}={max_days}."
        )
    return RetentionRule(default_days=default_days, max_days=max_days)


def _read_days(env: Env, variable: str, *, required: bool) -> int | None:
    try:
        return env.int(variable) if required else env.int(variable, None)
    except EnvironmentNotFoundError:
        raise ValueError(f"{variable} is required; set it to one of {RETENTION_CHOICES}.") from None
    except ValueError as error:
        raise ValueError(
            f"{variable}={env.str(variable)!r} must be a whole number of days."
        ) from error


def effective_retention_days(org_days: int | None, rule: RetentionRule) -> int:
    """Return the days an organization's data is actually kept; 0 means forever.

    Args:
        org_days: The organization's chosen value, or None to inherit the default.
        rule: The instance rule for the data type.

    Returns:
        The default when the organization chose nothing. Otherwise its value, clamped to
        the cap when one is set: "forever" and anything above the cap both become the cap,
        because a cap lowered after the organization chose must still be enforced.
    """
    if org_days is None:
        return rule.default_days
    if rule.max_days is None:
        return org_days
    if org_days == 0 or org_days > rule.max_days:
        return rule.max_days
    return org_days


def allowed_org_values(rule: RetentionRule) -> tuple[int, ...]:
    """Return the retention values an organization admin may choose under ``rule``."""
    if rule.max_days is None:
        return RETENTION_CHOICES
    return tuple(days for days in _CAP_CHOICES if days <= rule.max_days)


@dataclass(frozen=True)
class SessionTreeLink:
    """A foreign key from ``table.column`` to ``tables_session.id``."""

    table: str
    column: str


# The session-tree contract for the manager's retention job, which deletes expired sessions
# with raw SQL. Django runs on_delete=CASCADE and SET_NULL in Python; in the database these
# foreign keys are NO ACTION (deferred), except tables_graphsessionmessage.session_id, which a
# migration turned into ON DELETE CASCADE. A raw delete must therefore do that work itself.
# Pinned by django_app's test_session_retention_contract.py, which fails when a model relation
# changes without this contract, and by the manager's test_crewdb_grants.py, which fails when
# the manager role's grants in src/crewdb/custom-docker-entrypoint.sh miss a table.

# Subflow sessions point at their parent through this column; deleting a session deletes
# its whole subtree, which the job expands with a recursive query.
SESSION_PARENT_COLUMN = "parent_session_id"

# Every table whose rows are deleted with their session.
SESSION_CHILD_TABLES: tuple[SessionTreeLink, ...] = (
    SessionTreeLink("tables_graphsessionmessage", "session_id"),
    SessionTreeLink("tables_usersessionmessage", "session_id"),
    SessionTreeLink("tables_agentsessionmessage", "session_id"),
    SessionTreeLink("tables_tasksessionmessage", "session_id"),
    SessionTreeLink("tables_sessionwarningmessage", "session_id"),
    SessionTreeLink("tables_sessiontrigger", "session_id"),
    SessionTreeLink("tables_sessionprincipal", "session_id"),
    SessionTreeLink("tables_sessioncallback", "session_id"),
    # The session's link to a storage file; the file's own row and object are kept.
    SessionTreeLink("tables_sessionstoragefile", "session_id"),
    SessionTreeLink("storage_credentials_temp_account", "session_id"),
)

# Columns elsewhere that point at a session and are cleared, not deleted, with it.
SESSION_SET_NULL_COLUMNS: tuple[SessionTreeLink, ...] = (
    SessionTreeLink("tables_keyvaluetableentry", "updated_by_session_id"),
    SessionTreeLink("tables_sessiontrigger", "triggered_by_session_id"),
)

# Session.SessionStatus values after which nothing runs the session again.
TERMINAL_SESSION_STATUSES: frozenset[str] = frozenset({"end", "error", "stop", "expired"})

# SessionCallback.Status values after which no delivery is attempted. Any other status
# (registered, pending, or one added later) means the callback is still owed.
FINAL_SESSION_CALLBACK_STATUSES: frozenset[str] = frozenset({"delivered", "failed"})


def audit_tier(days: int) -> str:
    """Return the audit index tier name for a retention value, e.g. ``90d`` or ``unlimited``.

    Raises:
        ValueError: ``days`` is not one of RETENTION_CHOICES.
    """
    if days not in RETENTION_CHOICES:
        raise ValueError(f"Invalid retention days: {days}. Allowed values are: {RETENTION_CHOICES}")
    if days == 0:
        return "unlimited"
    return f"{days}d"
