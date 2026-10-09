"""Import a committed flow export through the API, so every machine benchmarks the same flow."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from api import Api, ApiError

HERE = Path(__file__).resolve().parent
PAYLOAD_EXPORT = HERE / "flows" / "payload.json"
# Which export each server and organization already has, so runs reuse the flow instead of
# re-importing it: a replace recreates the nodes with new ids, which changes the graph hash
# and makes two runs of the same flow look like different workloads. Gitignored.
CACHE_FILE = HERE / ".flow-cache.json"
IMPORT_PATH = "/api/graphs/import/"
# Keep the export's uuid and replace the flow holding it, so a re-import updates the same flow
# (same id) in the organization instead of adding a copy next to it.
IMPORT_FIELDS = {"preserve_uuids": "true", "replace_existing": "true", "import_labels": "true"}
FLOW_ENTITY = "Flow"  # the import summary's key for flows (EntityType.GRAPH)
# ponytail: a replace keeps the row's created_at, so an old created_at means "updated". A
# re-import within this many seconds of the first one is reported as created; the id is right
# either way.
REPLACED_AFTER_S = 5
CREATED, UPDATED, EXISTING = "created", "updated", "existing"


class FlowImportError(Exception):
    """The flow export could not be imported; the message says why."""


@dataclass(frozen=True)
class ImportedFlow:
    id: int
    name: str
    status: str  # CREATED or UPDATED by an import, EXISTING when an earlier import is reused


def ensure_flow(api: Api, path: Path, cache_file: Path = CACHE_FILE) -> ImportedFlow:
    """The flow of the export at `path` in the API key's organization, imported only when
    needed: the first time, after the export changed, or when the flow is gone.

    Raises:
        FlowImportError: As import_flow, or the check of the already imported flow failed.
    """
    entry = _read_cache(cache_file).get(_cache_key(api))
    if entry and path.is_file() and entry.get("sha256") == _digest(path):
        try:
            graph = api.request("GET", f"/api/graph-light/{entry['graph_id']}/")[1]
            return ImportedFlow(entry["graph_id"], graph["name"], EXISTING)
        except ApiError as error:
            if error.status != 404:
                message = f"could not check flow {entry['graph_id']}: {error}"
                raise FlowImportError(message) from error
        except (KeyError, TypeError) as error:
            raise FlowImportError(f"unexpected answer for the known flow: {error!r}") from error
    return import_flow(api, path, cache_file)


def import_flow(api: Api, path: Path, cache_file: Path = CACHE_FILE) -> ImportedFlow:
    """Import the flow export at `path` into the API key's organization and remember it.

    Raises:
        FlowImportError: The file is missing, the API refused the import, or its answer does
            not hold exactly one readable flow.
    """
    if not path.is_file():
        raise FlowImportError(
            f"{display_path(path)} not found: export your payload flow (5 Python nodes, no LLM) "
            "from the UI with the `benchmark` label and save it there"
        )
    try:
        summary = api.upload(IMPORT_PATH, path, IMPORT_FIELDS)[1] or {}
        flow_summary = summary.get(FLOW_ENTITY, {})
        created = flow_summary.get("created", {}).get("items", [])
        reused = flow_summary.get("reused", {}).get("items", [])
        if len(created) + len(reused) != 1:
            raise FlowImportError(
                f"expected exactly one flow in the import answer, got {created + reused}; "
                "the payload flow must not contain subflows"
            )
        (item,) = created + reused
        status = CREATED if created and not _replaced(api, item) else UPDATED
        flow = ImportedFlow(item["id"], item["name"], status)
    except ApiError as error:
        raise FlowImportError(f"flow import from {display_path(path)} failed: {error}") from error
    except (KeyError, TypeError, ValueError) as error:
        message = f"unexpected answer importing {display_path(path)}: {error!r}"
        raise FlowImportError(message) from error
    cache = _read_cache(cache_file)
    cache[_cache_key(api)] = {"sha256": _digest(path), "graph_id": flow.id}
    cache_file.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return flow


def describe(phase_name: str, flow: ImportedFlow) -> str:
    return f'{phase_name} flow: id {flow.id} ({flow.status}) "{flow.name}"'


def display_path(path: Path) -> str:
    try:
        return path.relative_to(HERE.parent).as_posix()
    except ValueError:
        return str(path)


def _replaced(api: Api, item: dict) -> bool:
    # the import answer reports a replaced flow as created; only its timestamps tell them apart
    graph = api.request("GET", f"/api/graph-light/{item['id']}/")[1]
    age = datetime.fromisoformat(graph["updated_at"]) - datetime.fromisoformat(graph["created_at"])
    return age.total_seconds() > REPLACED_AFTER_S


def _cache_key(api: Api) -> str:
    return f"{api.base_url} org {api.org_id}"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_cache(cache_file: Path) -> dict:
    # a missing or damaged cache only costs one re-import
    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return cache if isinstance(cache, dict) else {}
