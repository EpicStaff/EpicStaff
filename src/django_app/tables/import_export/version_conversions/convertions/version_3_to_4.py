from loguru import logger
from packaging.requirements import InvalidRequirement, Requirement

from tables.import_export.enums import EntityType, NodeType
from tables.import_export.version_conversions.base import VersionConverter


@VersionConverter.register(from_version=3)
def v3_to_v4(data: dict) -> dict:
    """
    v3 -> v4:
    - `python_code.libraries` (a space-separated string) replaced by `python_code.venv`.
    - Each distinct set of libraries becomes one `Venv` entry carrying them.
    - Code that declared no libraries names no venv and runs in the default one.
    """
    environments = _Environments()

    for entry in data.get(EntityType.PYTHON_CODE_TOOL, []):
        environments.assign(entry.get("python_code"), owner=entry.get("name"))

    for graph in data.get(EntityType.GRAPH, []):
        for node in graph.get("nodes", []):
            owner = node.get("node_name")
            node_type = node.get("node_type")
            if node_type in (NodeType.PYTHON_NODE, NodeType.WEBHOOK_TRIGGER_NODE):
                environments.assign(node.get("python_code"), owner=owner)
            elif node_type == NodeType.CLASSIFICATION_DECISION_TABLE_NODE:
                environments.assign(node.get("pre_python_code"), owner=owner)
                environments.assign(node.get("post_python_code"), owner=owner)

    if environments.entries:
        data[EntityType.VENV] = environments.entries

    return data


class _Environments:
    """Collects the `Venv` entries a v3 file implies and points its code at them.

    Code slots that declared the same libraries share one entry: in v3 they were the
    same install, and keeping them apart would build the same environment twice.
    """

    def __init__(self) -> None:
        self.entries: list[dict] = []
        self._ids_by_libraries: dict[frozenset, int] = {}
        self._used_names: set[str] = set()

    def assign(self, python_code: dict | None, *, owner: str | None) -> None:
        if python_code is None:
            return

        libraries = _parse_libraries(python_code.pop("libraries", ""), owner=owner)
        if not libraries:
            # No libraries to install, so no environment to build: the default one runs it.
            return

        key = frozenset((library["name"], library["specification"]) for library in libraries)
        venv_id = self._ids_by_libraries.get(key)
        if venv_id is None:
            venv_id = len(self.entries) + 1
            self._ids_by_libraries[key] = venv_id
            self.entries.append({"id": venv_id, "name": self._name_for(owner), "libs": libraries})
        python_code["venv"] = venv_id

    def _name_for(self, owner: str | None) -> str:
        """Name the environment after what first asked for it, so the list stays readable."""
        base = f"{owner}-venv" if owner else f"imported-venv-{len(self.entries) + 1}"
        name = base
        suffix = 2
        while name in self._used_names:
            name = f"{base}-{suffix}"
            suffix += 1
        self._used_names.add(name)
        return name


def _parse_libraries(value: str, *, owner: str | None) -> list[dict]:
    """Split a v3 library string into the name and specifier pairs v4 carries.

    Anything pip itself would not read is dropped with a warning rather than
    failing the import: a legacy file cannot be edited to fix it, and a flow that
    arrives without one library is worth more than one that does not arrive.
    """
    libraries = []
    for entry in (value or "").split():
        try:
            requirement = Requirement(entry)
        except InvalidRequirement as error:
            logger.warning(
                "Dropping library '{}' of '{}' while converting to v4: {}", entry, owner, error
            )
            continue
        if requirement.extras:
            # A venv library is a name and a specifier; there is nowhere to put extras.
            logger.warning(
                "Dropping extras {} from library '{}' of '{}' while converting to v4",
                sorted(requirement.extras),
                requirement.name,
                owner,
            )
        libraries.append({"name": requirement.name, "specification": str(requirement.specifier)})
    return libraries
