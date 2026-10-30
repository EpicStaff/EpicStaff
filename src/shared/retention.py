"""Instance-wide data retention policy, shared by django_app and manager.

The policy comes from the environment: for each data type a default number of days, an
optional cap an organization admin may not exceed and, for audit only, an optional floor an
organization admin may not go below. 0 days means "keep forever".
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
        min_days: Lowest positive value an organization may choose, or None for no floor.
            Never 0. Set by the operator so an organization admin cannot shorten a trail
            the deployment must keep, such as its own audit events.
    """

    default_days: int
    max_days: int | None
    min_days: int | None = None


@dataclass(frozen=True)
class RetentionPolicy:
    rules: Mapping[DataType, RetentionRule]

    def __post_init__(self):
        object.__setattr__(self, "rules", MappingProxyType(dict(self.rules)))


@dataclass(frozen=True)
class _RuleVariables:
    default_variable: str
    max_variable: str
    min_variable: str | None = None


_RULE_VARIABLES: dict[DataType, _RuleVariables] = {
    DataType.SESSIONS: _RuleVariables("RETENTION_SESSIONS_DAYS", "RETENTION_SESSION_MAX_DAYS"),
    DataType.CONVERSATIONS: _RuleVariables(
        "RETENTION_CONVERSATIONS_DAYS", "RETENTION_CONVERSATION_MAX_DAYS"
    ),
    # Only audit has a floor: it is the trail an organization admin could otherwise shorten
    # to erase their own actions.
    DataType.AUDIT: _RuleVariables(
        "RETENTION_AUDIT_DAYS", "RETENTION_AUDIT_MAX_DAYS", "RETENTION_AUDIT_MIN_DAYS"
    ),
}


def load_retention_policy(env: Env) -> RetentionPolicy:
    """Read and validate the retention policy from the environment.

    The default variables are required; a cap or floor that is absent or ``none`` means
    no cap or no floor.

    Raises:
        ValueError: A variable is missing, not a whole number, not one of
            RETENTION_CHOICES, or inconsistent with the other variables of its data type.
            The message names the offending variable.
    """
    return RetentionPolicy(
        rules={
            data_type: _load_rule(env, variables)
            for data_type, variables in _RULE_VARIABLES.items()
        }
    )


def _load_rule(env: Env, variables: _RuleVariables) -> RetentionRule:
    default_variable = variables.default_variable
    max_variable = variables.max_variable
    min_variable = variables.min_variable
    default_days = _read_days(env, default_variable, required=True)
    max_days = _read_days(env, max_variable, required=False)
    min_days = None if min_variable is None else _read_days(env, min_variable, required=False)

    if default_days not in RETENTION_CHOICES:
        raise ValueError(f"{default_variable}={default_days} must be one of {RETENTION_CHOICES}.")

    if max_days is not None:
        if max_days not in _CAP_CHOICES:
            raise ValueError(
                f"{max_variable}={max_days} must be one of {_CAP_CHOICES}, or none for no cap."
            )
        if default_days == 0:
            raise ValueError(
                f"{default_variable}=0 keeps data forever, which {max_variable}={max_days} "
                f"forbids. Choose a default of at most {max_days} days or set {max_variable}=none."
            )
        if default_days > max_days:
            raise ValueError(
                f"{default_variable}={default_days} is above its cap {max_variable}={max_days}."
            )

    if min_days is not None:
        if min_days not in _CAP_CHOICES:
            raise ValueError(
                f"{min_variable}={min_days} must be one of {_CAP_CHOICES}, or none for no floor."
            )
        if max_days is not None and min_days > max_days:
            raise ValueError(
                f"{min_variable}={min_days} is above the cap {max_variable}={max_days}."
            )
        # 0 keeps data forever, which is above any floor.
        if default_days != 0 and default_days < min_days:
            raise ValueError(
                f"{default_variable}={default_days} is below its floor {min_variable}={min_days}."
            )

    return RetentionRule(default_days=default_days, max_days=max_days, min_days=min_days)


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
        the cap and floor when set: "forever" and anything above the cap both become the
        cap, and a positive value below the floor becomes the floor, because a cap lowered
        or a floor raised after the organization chose must still be enforced.
    """
    if org_days is None:
        return rule.default_days
    if rule.min_days is not None and 0 < org_days < rule.min_days:
        org_days = rule.min_days
    if rule.max_days is None:
        return org_days
    if org_days == 0 or org_days > rule.max_days:
        return rule.max_days
    return org_days


def allowed_org_values(rule: RetentionRule) -> tuple[int, ...]:
    """Return the retention values an organization admin may choose under ``rule``.

    0 (forever) is allowed when there is no cap, whatever the floor.
    """
    return tuple(
        days
        for days in RETENTION_CHOICES
        if (days == 0 and rule.max_days is None)
        or (
            days > 0
            and (rule.max_days is None or days <= rule.max_days)
            and (rule.min_days is None or days >= rule.min_days)
        )
    )


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
# changes without this contract or when the manager role's grants in
# src/django_app/tables/service_db_grants.py miss one of its tables.

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
