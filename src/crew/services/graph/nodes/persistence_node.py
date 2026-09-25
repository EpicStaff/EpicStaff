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
# Django's PersistenceEntriesValidator applies the same rule on save.
_STATE_PATH = re.compile(r"variables\.\w+(?:\.\w+|\[\d+\])*", re.ASCII)
# Attribute access on a DotDict finds these before any stored key, so a value stored under
# one of these names can never be read back by path.
_DOTDICT_ATTRIBUTES = frozenset(name for name in dir(DotDict) if not name.startswith("_"))


class PersistenceNode(BaseNode):
    """Read, write or delete entries in a persistence table.

    Entries reference flow state directly: key placeholders (`profile_{variables.user.id}`),
    write sources and read targets (`variables.user.name`) are state paths; the node has no
    input map and no output variable. A read writes each stored value (None for a missing
    key) to its entry's target path. A write source's `|default` suffix applies only when the
    path is missing, not when it holds null.
    """

    TYPE = "PERSISTENCE"

    def __init__(
        self,
        session_id: int,
        node_name: str,
        stop_event: StopEvent,
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
            output_variable_path=None,
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
        """Store each read value at its entry's target path; return them keyed by path."""
        key_by_target: dict[str, str] = {}
        for entry in self.entries:
            target = self._check_target(entry["value"])
            if target in key_by_target:
                raise PersistenceNodeError(
                    f"Persistence node '{self.node_name}': '{target}' receives more than one "
                    "key. Use a different variable for each key."
                )
            key_by_target[target] = self._render_key(entry["key"], variables)
        stored = await self.persistence_client.read(
            self.session_id, self.persistence_table_id, sorted(set(key_by_target.values()))
        )
        read = {target: stored.get(key) for target, key in key_by_target.items()}
        for target, value in read.items():
            self._assign(variables, target, value)
        return read

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
            # The panel accepts `{ variables.x }`; the path inside must still be canonical.
            path = match.group(1).strip()
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

    def _check_target(self, path: str) -> str:
        if "|" in path:
            raise PersistenceNodeError(
                f"Persistence node '{self.node_name}': read target '{path}' is where the stored "
                "value goes, so it takes no '|default'. Use a path like 'variables.user.name'."
            )
        segments = self._segments(path)
        method = next((segment for segment in segments if segment in _DOTDICT_ATTRIBUTES), None)
        if method:
            raise PersistenceNodeError(
                f"Persistence node '{self.node_name}': read target '{path}' uses '{method}', "
                "the name of a built-in method. Use a different variable name."
            )
        return path

    def _segments(self, path: str) -> list[str]:
        """Check the path before any `|default` and return its segments."""
        state_path = path.split("|", 1)[0]
        segments = _PATH_SEGMENT.findall(state_path)
        if segments == ["variables"]:
            raise PersistenceNodeError(
                f"Persistence node '{self.node_name}': '{path}' names the whole flow state. "
                "Point at a single variable, e.g. 'variables.user.id'."
            )
        if not _STATE_PATH.fullmatch(state_path):
            raise PersistenceNodeError(
                f"Persistence node '{self.node_name}': '{path}' is not a flow state path. "
                "Use one like 'variables.user.id' (in a key: 'profile_{variables.user.id}')."
            )
        # getattr on a DotDict would return its internals, e.g. `variables._properties`.
        if any(segment.startswith("_") for segment in segments):
            raise PersistenceNodeError(
                f"Persistence node '{self.node_name}': '{path}' has a segment starting with '_'. "
                "Flow state paths cannot name internal attributes."
            )
        return segments

    def _assign(self, variables: DotDict, target: str, value: Any) -> None:
        """Replace the value at `target`, never merging into what is there.

        A missing parent is created as an object when the next segment is a name. A missing
        list is not created: an empty list has no index to fill.
        """
        segments = _PATH_SEGMENT.findall(target)[1:]
        container: Any = variables
        path = "variables"
        for position, segment in enumerate(segments):
            slot = self._slot(container, path, segment)
            path += segment if segment.startswith("[") else f".{segment}"
            if position == len(segments) - 1:
                container[slot] = value
                return
            if isinstance(slot, str) and slot not in container:
                if segments[position + 1].startswith("["):
                    raise PersistenceNodeError(
                        f"Persistence node '{self.node_name}': '{path}' does not exist, so "
                        f"'{target}' has no list to index into."
                    )
                container[slot] = DotDict()
            # Read back rather than keep the DotDict above: DotDict stores a converted copy.
            container = container[slot]

    def _slot(self, container: Any, path: str, segment: str) -> str | int:
        """Return the key or index `segment` names in `container`, which lives at `path`."""
        if segment.startswith("["):
            index = int(segment[1:-1])
            if isinstance(container, dict):
                raise PersistenceNodeError(
                    f"Persistence node '{self.node_name}': '{path}' is an object; use a name "
                    f"like '{path}.name' instead of '{segment}'."
                )
            if not isinstance(container, list):
                raise PersistenceNodeError(
                    f"Persistence node '{self.node_name}': '{path}' is {_describe(container)}, "
                    f"so it has no index {segment}."
                )
            if index >= len(container):
                raise PersistenceNodeError(
                    f"Persistence node '{self.node_name}': index {index} is out of range for "
                    f"'{path}', which has {len(container)} items."
                )
            return index
        if isinstance(container, list):
            raise PersistenceNodeError(
                f"Persistence node '{self.node_name}': '{path}' is a list; use an index like "
                f"'{path}[0]' instead of '.{segment}'."
            )
        if not isinstance(container, dict):
            raise PersistenceNodeError(
                f"Persistence node '{self.node_name}': '{path}' is {_describe(container)}, "
                f"so it cannot hold '{segment}'."
            )
        return segment

    def _resolve(self, path: str, variables: DotDict) -> Any:
        self._segments(path)
        try:
            # Keyed by the path itself so the resolver's own messages name the user's path.
            value = map_variables_to_input(variables, {path: path})[path]
        # The resolver raises IndexError for a list index out of range, KeyError/TypeError
        # for indexing a non-list.
        except (IndexError, KeyError, TypeError) as e:
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


def _describe(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, (int, float)):
        return "a number"
    return f"a {type(value).__name__}"
