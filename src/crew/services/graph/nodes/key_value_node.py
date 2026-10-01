import json
import re
from dataclasses import asdict
from typing import Any, Literal

from clients.errors import ClientError
from clients.key_value import KeyValueClient
from dotdict import DotDict
from langgraph.types import StreamWriter
from models.graph_models import KeyValueMessageData, KeyValueMessageEntry
from models.state import State
from services.graph.events import StopEvent
from services.graph.exceptions import KeyValueNodeError
from services.graph.nodes.base_node import BaseNode
from utils import map_variables_to_input

MAX_KEY_LENGTH = 512
# Mirrors KEY_PATTERN and KEY_RULE in Django's tables/constants/key_value_constants.py and
# KEY_VALUE_KEY_PATTERN in the frontend. Always `fullmatch`: `$` also matches before a
# trailing newline.
KEY_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
KEY_RULE = (
    "use only letters, digits and _, don't start with a digit, "
    f"and keep it to at most {MAX_KEY_LENGTH} characters"
)
# Mirrors Django's MAX_KEYS_PER_REQUEST, which the internal routes enforce per call.
MAX_ENTRIES = 500
# Mirrors Django's VALUE_PREVIEW_CHARS: a value past the message budget is previewed the way
# the table view previews it.
VALUE_PREVIEW_CHARS = 200
# Total UTF-8 JSON size of the values one session message carries in full; later long values
# are sent as previews so a large read, write or delete cannot bloat the message stream. This bounds
# the size as the message is stored (a JSONField), not the Redis payload: that is published
# with ensure_ascii escaping, which can grow non-ASCII text several times over.
MESSAGE_VALUE_BUDGET_BYTES = 512 * 1024
_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")
# Same tokenisation as `map_variables_to_input`, which resolves a bare `variables` path to the
# whole flow state.
_PATH_SEGMENT = re.compile(r"\w+|\[(?:0|[1-9]\d*)\]")
# Django's KeyValueEntriesValidator applies the same rule on save. Indexes are canonical
# (`[0]`, `[10]`, not `[01]`) so equal paths compare equal as strings.
_STATE_PATH = re.compile(r"variables\.\w+(?:\.\w+|\[(?:0|[1-9]\d*)\])*", re.ASCII)
# Attribute access on a DotDict finds these before any stored key, so a value stored under
# one of these names can never be read back by path.
_DOTDICT_ATTRIBUTES = frozenset(name for name in dir(DotDict) if not name.startswith("_"))


class KeyValueNode(BaseNode):
    """Read, write or delete entries in a key-value table.

    Entries reference flow state directly: key placeholders (`profile_{variables.user.id}`),
    write sources and read targets (`variables.user.name`) are state paths; the node has no
    input map and no output variable. A read writes each stored value (None for a missing
    key) to its entry's target path, in entry order, and rejects two entries whose targets
    are the same or nested (`variables.user` and `variables.user.name`); one key may feed
    several targets. A write rejects two entries with the same
    rendered key; one source path may feed several keys. A write source's `|default` suffix
    applies only when the path is missing, not when it holds null.

    After the table call succeeds, the node emits one `key_value` session message listing
    the entries that took effect (for a delete, each requested key with the value it held,
    if any), with their full values while they fit MESSAGE_VALUE_BUDGET_BYTES and a
    truncated preview after that.
    """

    TYPE = "KEY_VALUE"

    def __init__(
        self,
        session_id: int,
        node_name: str,
        stop_event: StopEvent,
        key_value_table_id: int | None,
        mode: Literal["read", "write", "delete"],
        entries: list[dict],
        key_value_client: KeyValueClient,
    ):
        super().__init__(
            session_id=session_id,
            node_name=node_name,
            stop_event=stop_event,
            input_map={},
            output_variable_path=None,
        )
        self.key_value_table_id = key_value_table_id
        self.mode = mode
        self.entries = entries
        self.key_value_client = key_value_client

    async def execute(self, state: State, writer: StreamWriter, execution_order: int, input_: Any):
        if self.key_value_table_id is None:
            raise KeyValueNodeError(f"Key-Value node '{self.node_name}' has no table selected.")
        if len(self.entries) > MAX_ENTRIES:
            raise KeyValueNodeError(
                f"Key-Value node '{self.node_name}' has {len(self.entries)} entries; "
                f"at most {MAX_ENTRIES} are allowed."
            )
        variables = state["variables"]
        try:
            if self.mode == "read":
                output, message = await self._read(variables)
            elif self.mode == "write":
                output, message = await self._write(variables)
            else:
                output, message = await self._delete(variables)
        except ClientError as e:
            raise KeyValueNodeError(
                f"Key-Value node '{self.node_name}' {self.mode} failed: {e.detail}"
            ) from e
        self.custom_session_message_writer.add_custom_message(
            session_id=self.session_id,
            node_name=self.node_name,
            writer=writer,
            message_data=asdict(message),
            execution_order=execution_order,
        )
        return output

    async def _read(self, variables: DotDict) -> tuple[dict[str, Any], KeyValueMessageData]:
        """Store each read value at its entry's target path; return them keyed by path."""
        targets_and_keys = [
            (self._check_target(entry["value"]), self._render_key(entry["key"], variables))
            for entry in self.entries
        ]
        self._check_separate_targets([target for target, _ in targets_and_keys])
        response = await self.key_value_client.read(
            self.session_id,
            self.key_value_table_id,
            sorted({key for _, key in targets_and_keys}),
        )
        stored = response["values"]
        read: dict[str, Any] = {}
        message_entries: list[KeyValueMessageEntry] = []
        for target, key in targets_and_keys:
            read[target] = stored.get(key)
            self._assign(variables, target, read[target])
            message_entries.append(
                KeyValueMessageEntry(key=key, path=target, found=key in stored, value=read[target])
            )
        return read, self._message(response, message_entries)

    async def _write(self, variables: DotDict) -> tuple[dict[str, Any], KeyValueMessageData]:
        written: dict[str, Any] = {}
        source_by_key: dict[str, str] = {}
        for entry in self.entries:
            key = self._render_key(entry["key"], variables)
            # Checked on the rendered key: different templates can render to the same one.
            if key in written:
                raise KeyValueNodeError(
                    f"Key-Value node '{self.node_name}': more than one entry writes key "
                    f"'{key}'. Use a different key for each entry."
                )
            value_path = entry["value"]
            value = self._resolve(value_path, variables)
            if value is None:
                raise KeyValueNodeError(
                    f"Key-Value node '{self.node_name}': value '{value_path}' is missing "
                    "from the flow state or resolved to null."
                )
            written[key] = value
            source_by_key[key] = value_path
        response = await self.key_value_client.write(
            self.session_id, self.key_value_table_id, written
        )
        created = set(response["created"])
        message_entries = [
            KeyValueMessageEntry(
                key=key, path=source_by_key[key], created=key in created, value=value
            )
            for key, value in written.items()
        ]
        return written, self._message(response, message_entries)

    async def _delete(self, variables: DotDict) -> tuple[None, KeyValueMessageData]:
        keys = sorted({self._render_key(entry["key"], variables) for entry in self.entries})
        response = await self.key_value_client.delete(
            self.session_id, self.key_value_table_id, keys
        )
        deleted = response["values"]
        message_entries = [
            KeyValueMessageEntry(key=key, found=key in deleted, value=deleted.get(key))
            for key in keys
        ]
        return None, self._message(response, message_entries, deleted_count=response["deleted"])

    def _message(
        self,
        response: dict[str, Any],
        entries: list[KeyValueMessageEntry],
        deleted_count: int | None = None,
    ) -> KeyValueMessageData:
        _fit_values_to_budget(entries)
        return KeyValueMessageData(
            mode=self.mode,
            table_id=self.key_value_table_id,
            table_name=response["table_name"],
            entries=entries,
            deleted_count=deleted_count,
        )

    def _render_key(self, template: str, variables: DotDict) -> str:
        def substitute(match: re.Match) -> str:
            # The panel accepts `{ variables.x }`; the path inside must still be canonical.
            path = match.group(1).strip()
            value = self._resolve(path, variables)
            if value is None:
                raise KeyValueNodeError(
                    f"Key-Value node '{self.node_name}': key '{template}' needs '{path}', "
                    "which is missing from the flow state or is null."
                )
            if isinstance(value, (dict, list)):
                raise KeyValueNodeError(
                    f"Key-Value node '{self.node_name}': '{path}' must be a string or number, "
                    f"got {type(value).__name__}."
                )
            return str(value)

        # Checked on the template, not the rendered key, so the message can name the
        # malformed placeholder.
        leftover = _PLACEHOLDER.sub("", template)
        if "{" in leftover or "}" in leftover:
            raise KeyValueNodeError(
                f"Key-Value node '{self.node_name}': key '{template}' has an empty or "
                "unbalanced placeholder. Use '{variables.<path>}', e.g. 'profile_{variables.user.id}'."
            )
        key = _PLACEHOLDER.sub(substitute, template)
        # Checked on the resolved key: placeholder values are free text until rendered.
        if len(key) > MAX_KEY_LENGTH or not KEY_PATTERN.fullmatch(key):
            shown = key if len(key) <= 100 else f"{key[:100]}…"
            raise KeyValueNodeError(
                f"Key-Value node '{self.node_name}': key '{template}' resolved to {shown!r}, "
                f"which is not a valid key: {KEY_RULE}."
            )
        return key

    def _check_separate_targets(self, targets: list[str]) -> None:
        """Reject targets that repeat or nest: reading into both would overwrite one of them.

        Compared by path segment, so `variables.user` and `variables.username` are separate.
        """
        seen: list[tuple[list[str], str]] = []
        for target in targets:
            segments = _PATH_SEGMENT.findall(target)
            for earlier_segments, earlier in seen:
                shared = min(len(segments), len(earlier_segments))
                if segments[:shared] != earlier_segments[:shared]:
                    continue
                if len(segments) == len(earlier_segments):
                    raise KeyValueNodeError(
                        f"Key-Value node '{self.node_name}': more than one entry reads into "
                        f"'{target}'. Use a different variable for each entry."
                    )
                inner, outer = (target, earlier) if len(segments) > shared else (earlier, target)
                raise KeyValueNodeError(
                    f"Key-Value node '{self.node_name}': read target '{inner}' is inside "
                    f"read target '{outer}'. Use a different variable for each entry."
                )
            seen.append((segments, target))

    def _check_target(self, path: str) -> str:
        if "|" in path:
            raise KeyValueNodeError(
                f"Key-Value node '{self.node_name}': read target '{path}' is where the stored "
                "value goes, so it takes no '|default'. Use a path like 'variables.user.name'."
            )
        segments = self._segments(path)
        method = next((segment for segment in segments if segment in _DOTDICT_ATTRIBUTES), None)
        if method:
            raise KeyValueNodeError(
                f"Key-Value node '{self.node_name}': read target '{path}' uses '{method}', "
                "the name of a built-in method. Use a different variable name."
            )
        return path

    def _segments(self, path: str) -> list[str]:
        """Check the path before any `|default` and return its segments."""
        state_path = path.split("|", 1)[0]
        segments = _PATH_SEGMENT.findall(state_path)
        if segments == ["variables"]:
            raise KeyValueNodeError(
                f"Key-Value node '{self.node_name}': '{path}' names the whole flow state. "
                "Point at a single variable, e.g. 'variables.user.id'."
            )
        if not _STATE_PATH.fullmatch(state_path):
            raise KeyValueNodeError(
                f"Key-Value node '{self.node_name}': '{path}' is not a flow state path. "
                "Use one like 'variables.user.id' (in a key: 'profile_{variables.user.id}')."
            )
        # getattr on a DotDict would return its internals, e.g. `variables._properties`.
        if any(segment.startswith("_") for segment in segments):
            raise KeyValueNodeError(
                f"Key-Value node '{self.node_name}': '{path}' has a segment starting with '_'. "
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
                    raise KeyValueNodeError(
                        f"Key-Value node '{self.node_name}': '{path}' does not exist, so "
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
                raise KeyValueNodeError(
                    f"Key-Value node '{self.node_name}': '{path}' is an object; use a name "
                    f"like '{path}.name' instead of '{segment}'."
                )
            if not isinstance(container, list):
                raise KeyValueNodeError(
                    f"Key-Value node '{self.node_name}': '{path}' is {_describe(container)}, "
                    f"so it has no index {segment}."
                )
            if index >= len(container):
                raise KeyValueNodeError(
                    f"Key-Value node '{self.node_name}': index {index} is out of range for "
                    f"'{path}', which has {len(container)} items."
                )
            return index
        if isinstance(container, list):
            raise KeyValueNodeError(
                f"Key-Value node '{self.node_name}': '{path}' is a list; use an index like "
                f"'{path}[0]' instead of '.{segment}'."
            )
        if not isinstance(container, dict):
            raise KeyValueNodeError(
                f"Key-Value node '{self.node_name}': '{path}' is {_describe(container)}, "
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
            raise KeyValueNodeError(
                f"Key-Value node '{self.node_name}': cannot resolve '{path}' ({e}). "
                "Use a flow state path such as 'variables.user.id' "
                "(in a key: 'profile_{variables.user.id}')."
            ) from e
        # getattr on a DotDict falls through to dict methods, e.g. `variables.cart.items`.
        if callable(value):
            raise KeyValueNodeError(
                f"Key-Value node '{self.node_name}': '{path}' resolves to a built-in method, "
                "not a value in the flow state."
            )
        return value


def _fit_values_to_budget(entries: list[KeyValueMessageEntry]) -> None:
    """Keep full values, in entry order, while their JSON fits MESSAGE_VALUE_BUDGET_BYTES.

    Once the running total passes the budget, every later value whose JSON text is longer
    than VALUE_PREVIEW_CHARS is replaced by the start of that text, marked truncated; shorter
    values stay as they are.
    """
    used_bytes = 0
    for entry in entries:
        if entry.value is None:
            continue
        text = json.dumps(entry.value, ensure_ascii=False)
        used_bytes += len(text.encode("utf-8"))
        if used_bytes > MESSAGE_VALUE_BUDGET_BYTES and len(text) > VALUE_PREVIEW_CHARS:
            entry.value = text[:VALUE_PREVIEW_CHARS]
            entry.truncated = True


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
