from collections import defaultdict
from collections.abc import Collection, Iterable

from django.db.models import F
from tables.models import Session
from tables.services.run_admission import RunKind
from tables.services.run_resources import RunResourceCollector, RunResources
from tables.services.session_manager_service import SessionManagerService
from utils.logger import logger

from plugins.audit import log_refused_sessions_stopped, log_suspended_sessions_stopped
from plugins.runs.owned_resource_index import RUN_STOPPING_GRANT_STATES, OwnedResourceIndex

OPEN_SESSION_STATES = (
    Session.SessionStatus.PENDING,
    Session.SessionStatus.RUN,
    Session.SessionStatus.WAIT_FOR_USER,
)


class SuspendedRunStopper:
    """Stops the running sessions a suspension refuses from now on.

    A session is stopped when its flow uses a row owned under a grant in a state that stops
    running sessions (`RUN_STOPPING_GRANT_STATES`), or whose grant is gone. An organization
    being upgraded refuses new runs, but lets its running sessions finish.
    """

    def stop_for(self, *, organization_id: int, grant_id: int, plugin_identifier: str) -> None:
        """Stop every open session of the organization whose flow uses a row a suspended,
        purging or removed grant owns.

        Runs after the suspension commits. The queries do not depend on the number of
        sessions. A stop that fails is logged and the others go on; nothing is raised. Open
        voice conversations are not sessions and keep running.
        """
        stopped, failed = self._stop_refused_sessions(organization_id)
        log_suspended_sessions_stopped(
            identifier=plugin_identifier,
            grant_id=grant_id,
            org_id=organization_id,
            count=stopped,
            failed=failed,
        )

    def stop_in_organizations(self, organization_ids: Iterable[int]) -> int:
        """Stop the open sessions of these organizations that must not run now; returns how
        many were stopped.

        For the periodic enforcement: a session that started while a suspension committed
        got past both the run guard and the stopper that ran on commit. One query finds the
        open sessions of every organization at once. Logs per organization only when it
        stopped a session or failed to; nothing is raised.
        """
        sessions_by_organization: dict[int, list[Session]] = defaultdict(list)
        for session in (
            Session.objects.filter(
                graph__org_id__in=organization_ids, status__in=OPEN_SESSION_STATES
            )
            .annotate(organization_id=F("graph__org_id"))
            .only("pk", "graph_id")
            .order_by("pk")
        ):
            sessions_by_organization[session.organization_id].append(session)
        total = 0
        for organization_id, sessions in sessions_by_organization.items():
            stopped, failed = self._stop_sessions(organization_id, sessions)
            if stopped or failed:
                log_refused_sessions_stopped(org_id=organization_id, count=stopped, failed=failed)
            total += stopped
        return total

    def _stop_refused_sessions(self, organization_id: int) -> tuple[int, int]:
        sessions = list(
            Session.objects.filter(graph__org_id=organization_id, status__in=OPEN_SESSION_STATES)
            .only("pk", "graph_id")
            .order_by("pk")
        )
        return self._stop_sessions(organization_id, sessions)

    @staticmethod
    def _stop_sessions(organization_id: int, sessions: list[Session]) -> tuple[int, int]:
        if not sessions:
            return 0, 0
        resources_by_graph = RunResourceCollector().collect_many(
            RunKind.FLOW, {session.graph_id for session in sessions}
        )
        index = OwnedResourceIndex.for_inactive_grants(
            organization_id,
            _union(resources_by_graph.values()),
            grant_states=RUN_STOPPING_GRANT_STATES,
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
        return stopped, failed


def _union(resources: Collection[RunResources]) -> RunResources:
    return RunResources(
        refs=frozenset().union(*(item.refs for item in resources)),
        storage_prefixes=frozenset().union(*(item.storage_prefixes for item in resources)),
    )
