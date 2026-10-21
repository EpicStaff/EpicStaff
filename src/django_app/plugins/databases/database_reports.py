"""What a node reports about a plugin's database, and the activity events that follow from it."""

from datetime import datetime, timedelta

from src.shared.models.plugin_nodes import DatabaseReport
from utils.logger import logger

from plugins.activity.recorder import ActivityRecorder
from plugins.models import PluginDatabase, PluginDatabaseState

# A plugin that keeps changing its app role's settings back gets at most one activity event
# an hour for it; the record keeps every restore's time.
LIMIT_RESTORED_EVENT_INTERVAL = timedelta(hours=1)
# The app-role setting the node restores. Adding one: the node's app-role settings table,
# then the setting it names here.
RESTORED_SETTING = "statement_timeout"


class DatabaseReportRecorder:
    """Applies a node's report about one plugin's database to its record."""

    def apply(
        self, record: PluginDatabase, identifier: str, report: DatabaseReport, now: datetime
    ) -> None:
        """Store `report` on `record` (locked by the caller) and write the events it causes.

        A report about another installation is ignored. `provisioning` and `failed` store the
        node's error; `ready` stores the ledger and the size and clears the error. Events,
        all deployment-wide: `database_ready` the first time the database is ready, again
        once it is ready after a failure (the node reports `provisioning` in between, so the
        record keeps `failed_at` until then) or when the ledger changed (not when an agent
        restart provisions it again unchanged); `database_failed` once per failure, however
        often the node retries and fails again before the database is ready; and
        `database_limit_restored` when the node restored the app role's settings since the
        last report, at most once an hour.
        """
        if report.installation_id != record.installation_id:
            logger.warning(
                "The plugin node reported a database of another installation for {identifier}; "
                "ignored",
                identifier=identifier,
            )
            return
        changes = _state_changes(record, report, now)
        activity = ActivityRecorder()
        if report.state == PluginDatabaseState.READY and (
            record.ready_at is None
            or record.failed_at is not None
            or list(report.applied_migrations) != record.applied_migrations
        ):
            activity.database_ready(identifier, len(report.applied_migrations))
        if report.state == PluginDatabaseState.FAILED and record.failed_at is None:
            activity.database_failed(identifier, report.last_error)
        if report.limits_restored_at is not None and (
            record.limits_restored_at is None
            or report.limits_restored_at > record.limits_restored_at
        ):
            changes["limits_restored_at"] = report.limits_restored_at
            if (
                record.limits_restored_event_at is None
                or now - record.limits_restored_event_at > LIMIT_RESTORED_EVENT_INTERVAL
            ):
                activity.database_limit_restored(identifier, RESTORED_SETTING)
                changes["limits_restored_event_at"] = now
        changed = [name for name, value in changes.items() if getattr(record, name) != value]
        if not changed:
            return
        for name in changed:
            setattr(record, name, changes[name])
        record.save(update_fields=[*changed, "updated_at"])


def _state_changes(record: PluginDatabase, report: DatabaseReport, now: datetime) -> dict:
    """The record's fields as the report's state sets them."""
    if report.state == PluginDatabaseState.READY:
        return {
            "state": PluginDatabaseState.READY,
            "applied_migrations": list(report.applied_migrations),
            "size_bytes": report.size_bytes,
            "last_error": None,
            "ready_at": record.ready_at or now,
            "failed_at": None,
        }
    if report.state == PluginDatabaseState.FAILED:
        return {
            "state": report.state,
            "last_error": report.last_error,
            "failed_at": record.failed_at or now,
        }
    return {"state": report.state, "last_error": report.last_error}
