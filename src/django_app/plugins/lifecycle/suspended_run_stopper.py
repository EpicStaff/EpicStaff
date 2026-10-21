from collections.abc import Collection

from tables.models import Session
from tables.services.run_admission import RunKind
from tables.services.run_resources import RunResourceCollector, RunResources
from tables.services.session_manager_service import SessionManagerService
from utils.logger import logger

from plugins.audit import log_suspended_sessions_stopped
from plugins.runs.owned_resource_index import OwnedResourceIndex

OPEN_SESSION_STATES = (
    Session.SessionStatus.PENDING,
    Session.SessionStatus.RUN,
    Session.SessionStatus.WAIT_FOR_USER,
)


class SuspendedRunStopper:
    """Stops the running sessions a suspension refuses from now on."""

    def stop_for(self, *, organization_id: int, grant_id: int, plugin_identifier: str) -> None:
        """Stop every open session of the organization whose flow uses a row a non-active
        grant owns, by the run guard's rule.

        Runs after the suspension commits. The queries do not depend on the number of
        sessions. A stop that fails is logged and the others go on; nothing is raised. Open
        voice conversations are not sessions and keep running.
        """
        sessions = list(
            Session.objects.filter(graph__org_id=organization_id, status__in=OPEN_SESSION_STATES)
            .only("pk", "graph_id")
            .order_by("pk")
        )
        resources_by_graph = RunResourceCollector().collect_many(
            RunKind.FLOW, {session.graph_id for session in sessions}
        )
        index = OwnedResourceIndex.for_inactive_grants(
            organization_id, _union(resources_by_graph.values())
        )
        stopped = failed = 0
        for session in sessions:
            if index.first_owner(resources_by_graph[session.graph_id]) is None:
                continue
            try:
                SessionManagerService().stop_running_session(session)
            except Exception:
                # One session that cannot be stopped must not keep the others running.
                logger.exception(
                    "Could not stop session {} of a suspended plugin's organization", session.pk
                )
                failed += 1
            else:
                stopped += 1
        log_suspended_sessions_stopped(
            identifier=plugin_identifier,
            grant_id=grant_id,
            org_id=organization_id,
            count=stopped,
            failed=failed,
        )


def _union(resources: Collection[RunResources]) -> RunResources:
    return RunResources(
        refs=frozenset().union(*(item.refs for item in resources)),
        storage_prefixes=frozenset().union(*(item.storage_prefixes for item in resources)),
    )
