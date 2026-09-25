import re
from typing import Any, Literal

from clients.errors import ClientError
from clients.persistence import PersistenceClient
from dotdict import DotDict
from langgraph.types import StreamWriter
from models.state import State
from services.graph.events import StopEvent
from services.graph.exceptions import PersistenceNodeError
from services.graph.nodes.base_node import BaseNode
from utils import map_variables_to_input

MAX_KEY_LENGTH = 512
_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")
# Same tokenisation as `map_variables_to_input`, which resolves a bare `variables` path to the
# whole flow state.
_PATH_SEGMENT = re.compile(r"\w+|\[\d+\]")


class PersistenceNode(BaseNode):
    """Read, write or delete entries in a persistence table.

    Entries reference flow state directly: key placeholders (`profile_{variables.user.id}`)
    and write values (`variables.user.name`) are state paths; the node has no input map.
    A `|default` suffix applies only when the path is missing, not when it holds null.
    """

    TYPE = "PERSISTENCE"

    def __init__(
        self,
        session_id: int,
        node_name: str,
        stop_event: StopEvent,
        output_variable_path: str | None,
        persistence_table_id: int | None,
        mode: Literal["read", "write", "delete"],
        entries: list[dict],
        persistence_client: PersistenceClient,
    ):
        super().__init__(
            session_id=session_id,
            node_name=node_name,
            stop_event=stop_event,
            input_map={},
            output_variable_path=output_variable_path,
        )
        self.persistence_table_id = persistence_table_id
        self.mode = mode
        self.entries = entries
        self.persistence_client = persistence_client

    async def execute(self, state: State, writer: StreamWriter, execution_order: int, input_: Any):
        if self.persistence_table_id is None:
            raise PersistenceNodeError(
                f"Persistence node '{self.node_name}' has no table selected."
            )
        variables = state["variables"]
        try:
            if self.mode == "read":
                return await self._read(variables)
            if self.mode == "write":
                return await self._write(variables)
            return await self._delete(variables)
        except ClientError as e:
            raise PersistenceNodeError(
                f"Persistence node '{self.node_name}' {self.mode} failed: {e.detail}"
            ) from e

    async def _read(self, variables: DotDict) -> dict[str, Any]:
        key_by_alias = {
            entry["alias"]: self._render_key(entry["key"], variables) for entry in self.entries
        }
        stored = await self.persistence_client.read(
            self.session_id, self.persistence_table_id, sorted(set(key_by_alias.values()))
        )
        default_by_alias = {entry["alias"]: entry.get("default") for entry in self.entries}
        return {
            alias: stored[key] if key in stored else default_by_alias[alias]
            for alias, key in key_by_alias.items()
        }

    async def _write(self, variables: DotDict) -> dict[str, Any]:
        written: dict[str, Any] = {}
        for entry in self.entries:
            key = self._render_key(entry["key"], variables)
            value_path = entry["value"]
            value = self._resolve(value_path, variables)
            if value is None:
                raise PersistenceNodeError(
                    f"Persistence node '{self.node_name}': value '{value_path}' is missing "
                    "from the flow state or resolved to null."
                )
            written[key] = value
        await self.persistence_client.write(self.session_id, self.persistence_table_id, written)
        return written

    async def _delete(self, variables: DotDict) -> None:
        keys = sorted({self._render_key(entry["key"], variables) for entry in self.entries})
        await self.persistence_client.delete(self.session_id, self.persistence_table_id, keys)

    def _render_key(self, template: str, variables: DotDict) -> str:
        def substitute(match: re.Match) -> str:
            path = match.group(1)
            value = self._resolve(path, variables)
            if value is None:
                raise PersistenceNodeError(
                    f"Persistence node '{self.node_name}': key '{template}' needs '{path}', "
                    "which is missing from the flow state or is null."
                )
            if isinstance(value, (dict, list)):
                raise PersistenceNodeError(
                    f"Persistence node '{self.node_name}': '{path}' must be a string or number, "
                    f"got {type(value).__name__}."
                )
            return str(value)

        # Checked on the template, not the rendered key: a resolved value may contain braces.
        leftover = _PLACEHOLDER.sub("", template)
        if "{" in leftover or "}" in leftover:
            raise PersistenceNodeError(
                f"Persistence node '{self.node_name}': key '{template}' has an empty or "
                "unbalanced placeholder. Use '{variables.<path>}', e.g. 'profile_{variables.user.id}'."
            )
        key = _PLACEHOLDER.sub(substitute, template)
        if not key or len(key) > MAX_KEY_LENGTH:
            raise PersistenceNodeError(
                f"Persistence node '{self.node_name}': key must be 1-{MAX_KEY_LENGTH} characters, "
                f"got {len(key)}."
            )
        return key

    def _resolve(self, path: str, variables: DotDict) -> Any:
        if _PATH_SEGMENT.findall(path.split("|", 1)[0]) == ["variables"]:
            raise PersistenceNodeError(
                f"Persistence node '{self.node_name}': '{path}' names the whole flow state. "
                "Point at a single variable, e.g. 'variables.user.id'."
            )
        try:
            # Keyed by the path itself so the resolver's own messages name the user's path.
            value = map_variables_to_input(variables, {path: path})[path]
        # The resolver raises ValueError for a path outside `variables`, IndexError for an
        # empty path or list index out of range, KeyError/TypeError for indexing a non-list.
        except (ValueError, IndexError, KeyError, TypeError) as e:
            raise PersistenceNodeError(
                f"Persistence node '{self.node_name}': cannot resolve '{path}' ({e}). "
                "Use a flow state path such as 'variables.user.id' "
                "(in a key: 'profile_{variables.user.id}')."
            ) from e
        # getattr on a DotDict falls through to dict methods, e.g. `variables.cart.items`.
        if callable(value):
            raise PersistenceNodeError(
                f"Persistence node '{self.node_name}': '{path}' resolves to a built-in method, "
                "not a value in the flow state."
            )
        return value
