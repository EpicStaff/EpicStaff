import abc
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RunStatus:
    status: str
    token_usage: dict


@dataclass(frozen=True)
class CallerCredentials:
    """The operator's own credentials, so Django applies that user's permissions and org scoping."""

    org_id: int
    bearer_token: str = field(repr=False)


@dataclass(frozen=True)
class GraphContract:
    """What the flow declares: the start node's `variables` and the end node's `output_map` (None when the node is missing)."""

    start_variables: dict | None
    output_map: dict | None


class AbstractFlowRunner(abc.ABC):
    """Django as seen by the chat service: start, stop and read runs, read a graph's contract."""

    @abc.abstractmethod
    async def start_run(
        self,
        *,
        org_id: int,
        graph_id: int,
        variables: dict,
        token_budget: int,
        callback_url: str,
        callback_secret: str,
    ) -> int:
        """Return the new session id. Raises FlowNotFoundError (404) or FlowStartError."""

    @abc.abstractmethod
    async def stop_run(self, session_id: int) -> None:
        """Stop a run; an unknown session is not an error."""

    @abc.abstractmethod
    async def run_status(self, org_id: int, session_id: int) -> RunStatus:
        """Raises RunNotFoundError when the session is missing or outside the org."""

    @abc.abstractmethod
    async def run_result(self, org_id: int, session_id: int) -> object | None:
        """The persisted `graph_end` end-node result, or None when there is none."""

    @abc.abstractmethod
    async def graph_contract(self, caller: CallerCredentials, graph_id: int) -> GraphContract:
        """Read the graph as `caller`, never with the system key: binding a flow must not exceed what the user may read.

        Raises:
            FlowNotFoundError: The graph is missing or outside the caller's org.
            FlowForbiddenError: The caller lacks `flows:read` in the org.
            InvalidTokenError: Django rejected the caller's token.
        """
