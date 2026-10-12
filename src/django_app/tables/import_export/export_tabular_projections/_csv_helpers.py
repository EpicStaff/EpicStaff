from collections.abc import Iterable

from utils.graph_utils import resolve_node_names

from tables.models.llm_models import LLMConfig

# Leading characters a spreadsheet reads as a formula (OWASP CSV injection list).
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def _neutralize_formula(value: object) -> object:
    """Prefix `'` so a spreadsheet shows the cell as text: exports carry outsider and LLM text."""
    if isinstance(value, str) and value.startswith(_FORMULA_TRIGGERS):
        return f"'{value}"
    return value


def _yes_no(value: object) -> str:
    return "Yes" if value else "No"


def _format_mapping(mapping: dict | None) -> str:
    if not mapping:
        return ""
    return "\n".join(f"{key}: {value}" for key, value in mapping.items())


def _llm_config_label(config: LLMConfig | None) -> str:
    if config is None:
        return ""
    model_name = config.model.name if config.model else ""
    if model_name and model_name != config.custom_name:
        return f"{config.custom_name} ({model_name})"
    return config.custom_name


def _node_labels(node_ids: Iterable[int | None], graph_id: int) -> dict[int, str]:
    """Label each referenced node by its plain name, in one batched lookup.

    Only nodes of ``graph_id`` resolve. Any other id, including a reference stored
    before same-graph validation that points into another organization, prints
    as ``node #id`` so the foreign node's name never reaches the export.
    """
    labels: dict[int, str] = {}
    for node_id, formatted in resolve_node_names(node_ids, graph_ids=[graph_id]).items():
        name = "" if formatted == f"unknown node #{node_id}" else formatted
        labels[node_id] = name.removesuffix(f" #{node_id}") or f"node #{node_id}"
    return labels


def _node_label(node_id: int | None, labels: dict[int, str]) -> str:
    if not node_id:
        return ""
    return labels[node_id]
