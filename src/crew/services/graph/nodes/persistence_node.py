import re
from typing import Any, Literal

from clients.errors import ClientError
from clients.persistence import PersistenceClient
from langgraph.types import StreamWriter
from models.state import State
from services.graph.events import StopEvent
from services.graph.exceptions import PersistenceNodeError
from services.graph.nodes.base_node import BaseNode

MAX_KEY_LENGTH = 512
_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")


class PersistenceNode(BaseNode):
    TYPE = "PERSISTENCE"

    def __init__(
        self,
        session_id: int,
        node_name: str,
        stop_event: StopEvent,
        input_map: dict,
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
            input_map=input_map,
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
        variables = input_ if isinstance(input_, dict) else {}
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

    async def _read(self, variables: dict) -> dict[str, Any]:
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

    async def _write(self, variables: dict) -> dict[str, Any]:
        written: dict[str, Any] = {}
        for entry in self.entries:
            key = self._render_key(entry["key"], variables)
            value_alias = entry["value"]
            if variables.get(value_alias) is None:
                raise PersistenceNodeError(
                    f"Persistence node '{self.node_name}': value '{value_alias}' is missing "
                    "from the input or resolved to null."
                )
            written[key] = variables[value_alias]
        await self.persistence_client.write(self.session_id, self.persistence_table_id, written)
        return written

    async def _delete(self, variables: dict) -> None:
        keys = sorted({self._render_key(entry["key"], variables) for entry in self.entries})
        await self.persistence_client.delete(self.session_id, self.persistence_table_id, keys)

    def _render_key(self, template: str, variables: dict) -> str:
        def substitute(match: re.Match) -> str:
            name = match.group(1)
            value = variables.get(name)
            if value is None:
                raise PersistenceNodeError(
                    f"Persistence node '{self.node_name}': key '{template}' needs '{name}', "
                    "which is not in the input map or is null."
                )
            if isinstance(value, (dict, list)):
                raise PersistenceNodeError(
                    f"Persistence node '{self.node_name}': '{name}' must be a string or number, "
                    f"got {type(value).__name__}."
                )
            return str(value)

        key = _PLACEHOLDER.sub(substitute, template)
        if not key or len(key) > MAX_KEY_LENGTH:
            raise PersistenceNodeError(
                f"Persistence node '{self.node_name}': key must be 1-{MAX_KEY_LENGTH} characters, "
                f"got {len(key)}."
            )
        return key
