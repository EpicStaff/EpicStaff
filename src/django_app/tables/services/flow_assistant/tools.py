from __future__ import annotations

"""
Stateless read-only tools for the Flow Assistant.

Every function takes a graph_id plus tool-specific args and returns a plain
dict or list.  They are synchronous (called via sync_to_async from the async
service layer).  All ORM access uses select_related / prefetch_related to
avoid N+1 queries.

Secret redaction: any config key whose name contains 'api_key', 'secret', or
'token' (case-insensitive) is replaced with "***".
"""

import json
import re
from collections import Counter

from django.db.models import Count, F
from django.utils.dateparse import parse_datetime

from agents.services.node_surface_service import NodeSurfaceService
from src.shared.models import CombinedSurfaceData

from tables.services.llm_clients import ToolSpec

from tables.models.base_models import BaseGlobalNode
from tables.models.mcp_models import McpTool
from tables.models.session_models import Session
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.models.graph_models import (
    ClassificationDecisionTableNode,
    ClassificationConditionGroup,
    ConditionGroup,
    DecisionTableNode,
    Edge,
    GraphSessionMessage,
    SubGraphNode,
)

from .node_registry import (
    FLOW_ASSISTANT_NODE_TYPES,
    NODE_TYPE_SPEC_BY_MODEL,
    NodeTypeSpec,
)

_SECRET_PATTERN = re.compile(r"api_key|secret|token", re.IGNORECASE)

# Per-field cap for content/extras truncation in get_session_messages, and the
# overall per-response character budget. See _truncate_leaves /
# _apply_response_budget below.
_MAX_FIELD_CHARS = 4000
_MAX_RESPONSE_CHARS = 60_000


def _redact(value: object, key: str = "") -> object:
    """Recursively redact secret fields in a plain-Python structure."""
    if isinstance(value, dict):
        return {k: _redact(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if key and _SECRET_PATTERN.search(key):
        return "***"
    return value


def _node_to_dict(spec: NodeTypeSpec, node) -> dict:
    """Convert a node ORM object to a sanitised dict.

    Relations (FK / OneToOne) are skipped generically — surface them
    explicitly via the post-loop resolver blocks in `get_node` when needed.
    `name` always comes from `spec.display_name()` so types without a real
    `node_name` (e.g. ConditionalEdge) still get a usable display name
    instead of being silently omitted.
    """
    result: dict = {"type": spec.label, "id": node.pk, "name": spec.display_name(node)}

    # "node_name" is skipped here because it's already surfaced as result["name"]
    # via spec.display_name() above — including it in config too would duplicate it.
    skip = {"id", "metadata", "content_hash", "node_name"}
    config: dict = {}
    for field in node._meta.fields:
        if field.is_relation:
            continue
        fname = field.name
        if fname in skip:
            continue
        raw_value = getattr(node, fname)
        config[fname] = _redact(raw_value, fname)
    result["config"] = config
    return result


# ── Decision-table rule serializers ──────────────────────────────────────────


def _serialize_decision_table_rules(node: DecisionTableNode) -> list[dict]:
    """Return a human-readable list of rules for a DecisionTableNode.

    Each entry represents one ConditionGroup (a named rule/branch) with its
    constituent conditions and the target node id it routes to.

    Shape:
      [
        {
          "rule_name": "high_value_order",
          "rule_type": "simple",          # "simple" or "complex"
          "expression": "...",            # complex-type join expression, else null
          "conditions": [
            {"name": "amount_check", "expression": "amount > 10000"},
            ...
          ],
          "routes_to_node_id": 42,        # null when not yet wired
        },
        ...
      ]
    """
    groups = (
        ConditionGroup.objects.filter(decision_table_node=node)
        .prefetch_related("conditions")
        .order_by("order")
    )
    rules: list[dict] = []
    for group in groups:
        conditions = [
            {"name": c.condition_name, "expression": c.condition}
            for c in group.conditions.all().order_by("order")
        ]
        rules.append(
            {
                "rule_name": group.group_name,
                "rule_type": group.group_type,
                "expression": group.expression,
                "manipulation": group.manipulation,
                "conditions": conditions,
                "routes_to_node_id": group.next_node_id,
            }
        )
    return rules


def _serialize_classification_decision_table_rules(
    node: ClassificationDecisionTableNode,
) -> list[dict]:
    """Return a human-readable list of rules for a ClassificationDecisionTableNode.

    Each entry represents one ClassificationConditionGroup (a named branch) with its
    expression/manipulation and the target node id it routes to.

    Shape:
      [
        {
          "rule_name": "positive_sentiment",
          "route_code": "pos",            # short routing key, may be null
          "expression": "...",
          "manipulation": "...",
          "field_expressions": {...},
          "continue_to_next_rule": false,
          "routes_to_node_id": 55,
          "prompt_id": "sentiment_check", # which prompt drives classification, may be null
        },
        ...
      ]
    """
    groups = ClassificationConditionGroup.objects.filter(
        classification_decision_table_node=node
    ).order_by("order")
    rules: list[dict] = []
    for group in groups:
        rules.append(
            {
                "rule_name": group.group_name,
                "route_code": group.route_code,
                "expression": group.expression,
                "manipulation": group.manipulation,
                "field_expressions": group.field_expressions or {},
                "continue_to_next_rule": group.continue_flag,
                "routes_to_node_id": group.next_node_id,
                "prompt_id": group.prompt.prompt_key if group.prompt else None,
            }
        )
    return rules


# ── public tool functions ─────────────────────────────────────────────────────


def get_flow_overview(graph_id: int) -> dict:
    """Return a high-level summary of the flow."""
    from tables.models.graph_models import Graph

    graph = Graph.objects.get(pk=graph_id)

    node_specs = [spec for spec in FLOW_ASSISTANT_NODE_TYPES if not spec.is_edge]
    edge_specs = [spec for spec in FLOW_ASSISTANT_NODE_TYPES if spec.is_edge]

    # One query per node-table type. node_count_by_type is derived from these
    # same rows below instead of re-reading every table a second time.
    raw_nodes: list[tuple[str, int, str]] = []
    for spec in node_specs:
        for node in spec.model.objects.filter(graph_id=graph_id).only(
            *spec.only_fields()
        ):
            raw_nodes.append((spec.label, node.pk, spec.display_name(node)))
    raw_nodes.sort(key=lambda t: (t[0], t[1]))

    counts_by_label = Counter(node_type for node_type, _, _ in raw_nodes)
    node_count_by_type = {
        spec.label: counts_by_label[spec.label] for spec in node_specs
    }

    nodes: list[dict] = [
        {"id": node_id, "type": node_type, "name": name}
        for node_type, node_id, name in raw_nodes
    ]

    # ConditionalEdge is an edge, not a node (see NodeTypeSpec.is_edge) — fold
    # its count into edge_count instead of node_count_by_type/nodes.
    edge_count = Edge.objects.filter(graph_id=graph_id).count()
    for spec in edge_specs:
        edge_count += spec.model.objects.filter(graph_id=graph_id).count()

    subflows = [
        {
            "id": sn.subgraph.pk,
            "name": sn.subgraph.name,
            "description": sn.subgraph.description,
        }
        for sn in SubGraphNode.objects.filter(graph_id=graph_id).select_related(
            "subgraph"
        )
        if sn.subgraph
    ]

    return {
        "id": graph.pk,
        "name": graph.name,
        "description": graph.description,
        "node_count_by_type": node_count_by_type,
        "nodes": nodes,
        "edge_count": edge_count,
        "subflows": subflows,
    }


def get_node(graph_id: int, node_id: str) -> dict:
    """Resolve a node by PK and return its config.

    node_id is expected to be an integer string (e.g. "42").  Secrets are
    redacted from config output.

    Uses BaseGlobalNode.find_globally — a single UNION ALL query across every
    node table to locate the row, plus the query that loads it — 2 queries
    total, regardless of how many node types exist.
    """
    try:
        pk = int(node_id)
    except (ValueError, TypeError):
        return {"error": f"Invalid node_id '{node_id}': must be an integer string."}

    node = BaseGlobalNode.find_globally(pk)
    if node is None:
        return {"error": f"Node with id={node_id} not found in graph {graph_id}."}

    # Reject models the Flow Assistant doesn't treat as node types (e.g.
    # GraphNote, a canvas sticky note) and nodes belonging to a different graph.
    spec = NODE_TYPE_SPEC_BY_MODEL.get(type(node))
    if spec is None or node.graph_id != graph_id:
        return {"error": f"Node with id={node_id} not found in graph {graph_id}."}

    node_type = spec.label
    result = _node_to_dict(spec, node)

    # Attach decision rules for the two decision-table node types so the LLM
    # can reason about branching logic without requiring separate tool calls.
    if node_type == "decision_table":
        result["decision_rules"] = _serialize_decision_table_rules(node)
    elif node_type == "classification_decision_table":
        result["decision_rules"] = _serialize_classification_decision_table_rules(node)
        result["pre_python_code_summary"] = _resolve_python_code_summary(
            getattr(node, "pre_python_code_id", None)
        )
        result["post_python_code_summary"] = _resolve_python_code_summary(
            getattr(node, "post_python_code_id", None)
        )
    elif node_type in ("agent", "task"):
        result.update(_resolve_agent_or_task_enrichment(node_type, node))
    elif node_type == "conditional_edge":
        result["python_code_summary"] = _resolve_python_code_summary(
            getattr(node, "python_code_id", None)
        )

    # Phase F (Fix 16): attach python_code summary for nodes that wrap user-authored Python.
    if node_type in ("python", "webhook_trigger"):
        python_code_id = getattr(node, "python_code_id", None)
        result["python_code_summary"] = _resolve_python_code_summary(python_code_id)

    # Add connected edge IDs
    outgoing = list(
        Edge.objects.filter(graph_id=graph_id, start_node_id=pk).values_list(
            "end_node_id", flat=True
        )
    )
    incoming = list(
        Edge.objects.filter(graph_id=graph_id, end_node_id=pk).values_list(
            "start_node_id", flat=True
        )
    )
    result["connected_node_ids"] = {"outgoing": outgoing, "incoming": incoming}
    return result


def get_subflow(graph_id: int, subgraph_node_id: str) -> dict:
    """Return the target subgraph's name, description, and subgraph_graph_id.

    Accepts either the SubGraphNode's PK (canonical) or the target
    subgraph's Graph PK (fallback) — the two have non-overlapping
    interpretations, so try strict first and fall back gracefully when
    the LLM passes the wrong one.

    subgraph_graph_id is the PK of the referenced Graph — pass it to
    get_flow_overview(subgraph_graph_id) and get_node(subgraph_graph_id, ...)
    to introspect the subflow's internals recursively.
    """
    try:
        pk = int(subgraph_node_id)
    except (ValueError, TypeError):
        return {"error": f"Invalid subgraph_node_id '{subgraph_node_id}'."}

    # Strict: SubGraphNode PK in this graph.
    sn = (
        SubGraphNode.objects.select_related("subgraph")
        .filter(pk=pk, graph_id=graph_id)
        .first()
    )

    # Fallback: maybe the LLM passed the target subgraph's Graph PK.
    if sn is None:
        sn = (
            SubGraphNode.objects.select_related("subgraph")
            .filter(graph_id=graph_id, subgraph_id=pk)
            .first()
        )

    if sn is None:
        # Build a helpful error listing available SubGraphNode IDs in this graph.
        available = list(
            SubGraphNode.objects.filter(graph_id=graph_id).values_list("pk", flat=True)
        )
        return {
            "error": (
                f"No SubGraphNode matched id={pk} in graph {graph_id}. "
                f"Pass the SubGraphNode's PK (from get_flow_overview, "
                f"nodes where type=='subgraph'), not the target subflow's "
                f"graph id. Available SubGraphNode PKs in this graph: "
                f"{available if available else 'none'}."
            )
        }

    if not sn.subgraph:
        return {"error": f"SubGraphNode {sn.pk} has no linked subgraph."}

    return {
        "id": sn.subgraph.pk,
        "name": sn.subgraph.name,
        "description": sn.subgraph.description,
        "subgraph_graph_id": sn.subgraph.pk,
    }


def get_edges_from(graph_id: int, node_id: str) -> list[dict]:
    """Return outgoing edges from a node."""
    try:
        pk = int(node_id)
    except (ValueError, TypeError):
        return [{"error": f"Invalid node_id '{node_id}'."}]

    edges = list(Edge.objects.filter(graph_id=graph_id, start_node_id=pk))
    if not edges:
        return []

    # Build the index once for the whole graph — O(15) queries regardless of
    # how many edges are returned.  Each _resolve_node_identity call is then
    # an O(1) dict lookup.
    node_index = build_node_index(graph_id)
    result = []
    for edge in edges:
        target_info = _resolve_node_identity(edge.end_node_id, node_index)
        result.append(
            {
                "edge_id": edge.pk,
                "target_node_id": edge.end_node_id,
                "target_node_name": target_info.get("name", ""),
                "target_node_type": target_info.get("type", ""),
            }
        )
    return result


def get_edges_to(graph_id: int, node_id: str) -> list[dict]:
    """Return incoming edges to a node."""
    try:
        pk = int(node_id)
    except (ValueError, TypeError):
        return [{"error": f"Invalid node_id '{node_id}'."}]

    edges = list(Edge.objects.filter(graph_id=graph_id, end_node_id=pk))
    if not edges:
        return []

    # Build the index once for the whole graph — O(15) queries regardless of
    # how many edges are returned.  Each _resolve_node_identity call is then
    # an O(1) dict lookup.
    node_index = build_node_index(graph_id)
    result = []
    for edge in edges:
        source_info = _resolve_node_identity(edge.start_node_id, node_index)
        result.append(
            {
                "edge_id": edge.pk,
                "source_node_id": edge.start_node_id,
                "source_node_name": source_info.get("name", ""),
                "source_node_type": source_info.get("type", ""),
            }
        )
    return result


def get_session_stats(
    graph_id: int,
    since: str | None = None,
    until: str | None = None,
    status: str | None = None,
) -> dict:
    """Aggregate execution stats for this flow.

    Args:
        since: ISO 8601 timestamp (inclusive). e.g. "2026-05-15T00:00:00Z".
        until: ISO 8601 timestamp (exclusive).
        status: one of {pending, run, wait_for_user, error, end, stop, expired}.

    Returns: {total, by_status: {...}, since, until, status_filter}.
    """
    since_dt = None
    until_dt = None

    if since is not None:
        since_dt = parse_datetime(since)
        if since_dt is None:
            return {
                "error": f"Invalid since: expected ISO 8601 timestamp, got '{since}'"
            }

    if until is not None:
        until_dt = parse_datetime(until)
        if until_dt is None:
            return {
                "error": f"Invalid until: expected ISO 8601 timestamp, got '{until}'"
            }

    if status is not None:
        allowed_statuses = Session.SessionStatus.values
        if status not in allowed_statuses:
            return {
                "error": (
                    f"Invalid status '{status}'. " f"Allowed values: {allowed_statuses}"
                )
            }

    qs = Session.objects.filter(graph_id=graph_id)
    if since_dt is not None:
        qs = qs.filter(created_at__gte=since_dt)
    if until_dt is not None:
        qs = qs.filter(created_at__lt=until_dt)
    if status is not None:
        qs = qs.filter(status=status)

    total = qs.count()
    by_status_rows = qs.values("status").annotate(n=Count("id"))
    by_status = {row["status"]: row["n"] for row in by_status_rows}

    return {
        "total": total,
        "by_status": by_status,
        "since": since_dt.isoformat() if since_dt is not None else None,
        "until": until_dt.isoformat() if until_dt is not None else None,
        "status_filter": status,
    }


def get_recent_sessions(
    graph_id: int,
    limit: int = 5,
    since: str | None = None,
    until: str | None = None,
    where: dict | None = None,
    include_full_variables: bool = False,
) -> dict:
    """Return the most recent execution sessions for this flow.

    These are EXECUTION sessions of the flow itself — not Flow Assistant
    conversations. Used to answer "have I run recently?", "did my last run
    succeed?", "how often do I get called?", or "when was city X processed?".

    Args:
        limit: Number of sessions to return (1–25, default 5).
        since: ISO 8601 timestamp (inclusive). Filters sessions created at or after
            this time. e.g. "2026-05-15T00:00:00Z".
        until: ISO 8601 timestamp (exclusive). Filters sessions created before this time.
        where: Flat dict of variable key→value pairs to filter on. For example,
            {"city": "Berlin"} returns only sessions whose variables["city"] == "Berlin".
            Uses Postgres JSONField path lookups natively.
        include_full_variables: When True, each result row gains a `full_variables`
            field containing the entire Session.variables dict. Can return large
            objects — use targeted queries (where + limit) rather than broad scans.

    limit is clamped to [1, 25] to prevent excessive result sets.
    """
    since_dt = None
    until_dt = None

    if since is not None:
        since_dt = parse_datetime(since)
        if since_dt is None:
            return {
                "error": f"Invalid since: expected ISO 8601 timestamp, got '{since}'"
            }

    if until is not None:
        until_dt = parse_datetime(until)
        if until_dt is None:
            return {
                "error": f"Invalid until: expected ISO 8601 timestamp, got '{until}'"
            }

    limit = max(1, min(25, int(limit)))
    qs = Session.objects.filter(graph_id=graph_id)

    if since_dt is not None:
        qs = qs.filter(created_at__gte=since_dt)
    if until_dt is not None:
        qs = qs.filter(created_at__lt=until_dt)

    if where:
        for key, value in where.items():
            # Translate dot-notation to Django's __ nested lookup path.
            django_key = key.replace(".", "__")
            qs = qs.filter(**{f"variables__{django_key}": value})

    sessions = qs.order_by("-created_at")[:limit]

    _error_statuses = {
        Session.SessionStatus.ERROR,
        Session.SessionStatus.EXPIRED,
    }

    result = []
    for session in sessions:
        if session.finished_at and session.created_at:
            duration_seconds = int(
                (session.finished_at - session.created_at).total_seconds()
            )
        else:
            duration_seconds = None

        row: dict = {
            "id": session.pk,
            "status": session.status,
            "created_at": session.created_at.isoformat()
            if session.created_at
            else None,
            "finished_at": session.finished_at.isoformat()
            if session.finished_at
            else None,
            "duration_seconds": duration_seconds,
            "has_error": session.status in _error_statuses,
            "entrypoint": session.entrypoint,
            "start_variables": session.variables,
        }
        if include_full_variables:
            # Final / runtime variables (mutations made during execution) are stored
            # at Session.status_data["variables"] when the crew publishes session-end
            # status. Fall back to Session.variables if status_data has no entry
            # (e.g. a session that ended abnormally before the publish completed).
            runtime_variables = (session.status_data or {}).get("variables")
            row["full_variables"] = (
                runtime_variables
                if runtime_variables is not None
                else session.variables
            )

        result.append(row)

    return {"sessions": result}


# message_type → the message_data field that holds this entry's headline
# content. This must track the message types actually written by the crew
# service (custom_message_writer.py, python_node.py/webhook_trigger_node.py,
# subgraph_node.py, agent_stream_events.py, knowledge_search_service.py) —
# NOT the CrewAI-era dataclasses in crew/models/graph_models.py
# (LLMMessageData, AgentMessageData, AgentFinishMessageData, TaskMessageData,
# UserMessageData) that are declared but constructed nowhere. Types not
# listed here (e.g. "condition_group", "condition_group_manipulation",
# "graph_end") have no single natural "content" field — everything about
# them lives in `extras`.
_PRIMARY_CONTENT_FIELD_BY_MESSAGE_TYPE: dict[str, str] = {
    "start": "input",
    "finish": "output",
    "error": "details",
    "subgraph_start": "input",
    "subgraph_finish": "output",
    "classification_prompt": "raw_response",
    "python": "python_code_execution_data",
    "python_stream": "text",
    "agent_node_stream": "data",
    "task_node_stream": "data",
    "extracted_chunks": "knowledge_query",
}


def _truncate_leaves(value: object, cap: int) -> object:
    """Recursively truncate every string leaf in `value` to `cap` characters.

    Dicts and lists are walked structurally; non-string scalars (int, float,
    bool, None) pass through unchanged. A truncated string gets a visible
    "…[truncated N chars]" suffix (N = characters removed) so cuts are never
    silent — same spirit as extras["state_truncated"].
    """
    if isinstance(value, str):
        if len(value) <= cap:
            return value
        omitted = len(value) - cap
        return f"{value[:cap]}…[truncated {omitted} chars]"
    if isinstance(value, dict):
        return {key: _truncate_leaves(item, cap) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_truncate_leaves(item, cap) for item in value]
    return value


def _apply_response_budget(entries: list[dict], budget: int) -> list[dict]:
    """Bound the whole trace's serialized size, on top of the per-field cap.

    Per-field truncation alone doesn't bound the total — e.g. 200 rows each
    near the per-field cap can still add up to megabytes. Once the running
    serialized size crosses `budget`, subsequent entries keep their
    structural fields (kind/node_name/execution_order/created_at) but have
    content/extras replaced with an explicit marker.
    """
    running_total = 0
    budgeted: list[dict] = []
    for entry in entries:
        if running_total > budget:
            entry = {
                **entry,
                "content": None,
                "extras": {"body_dropped_for_response_budget": True},
            }
        budgeted.append(entry)
        running_total += len(json.dumps(entry, default=str))
    return budgeted


def _graph_session_message_to_entry(row: dict) -> dict:
    """Map one GraphSessionMessage row to the get_session_messages entry shape.

    `state` (the entire session variable namespace) is stripped out before
    returning — it appears on "finish" and "condition_group_manipulation"
    messages and can be arbitrarily large. Its removal is flagged via
    extras["state_truncated"] rather than silently dropped.

    Every remaining field in `content`/`extras` is then recursively truncated
    to _MAX_FIELD_CHARS per string leaf (_truncate_leaves) — this is what
    bounds e.g. extracted_chunks' RAG document text and python's stdout/
    stderr instead of returning them verbatim.
    """
    message_data = dict(row["message_data"] or {})
    message_type = message_data.pop("message_type", "unknown")
    state_present = message_data.pop("state", None) is not None

    content_field = _PRIMARY_CONTENT_FIELD_BY_MESSAGE_TYPE.get(message_type)
    content = message_data.pop(content_field, None) if content_field else None

    extras = message_data
    if state_present:
        extras["state_truncated"] = True

    return {
        "kind": message_type,
        "node_name": row["name"],
        "execution_order": row["execution_order"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "content": _truncate_leaves(content, _MAX_FIELD_CHARS),
        "extras": _truncate_leaves(extras, _MAX_FIELD_CHARS),
    }


def get_session_messages(
    graph_id: int,
    session_id: int,
    limit: int = 50,
) -> dict:
    """Return the per-step execution trace for a session, oldest to newest:
    node start/finish, subgraph start/finish, python execution, agent/task
    tool-call and tool-result stream events, knowledge retrieval, decision-
    table branch results, classification prompts, and errors.

    Use after get_recent_sessions identifies the target session_id.
    Useful for explaining HOW a specific run reached its output, or why it
    failed.

    Returns the MOST RECENT `limit` entries (1–200, default 50) — not the
    first `limit` — so a failure at the end of a long run is never truncated
    away.

    Bodies are size-bounded: individual string fields are truncated to a few
    KB each (marked "…[truncated N chars]" when cut), and the whole response
    is capped by an overall character budget — entries beyond the budget
    keep their identity but have extras["body_dropped_for_response_budget"]
    set to True. The full variable-namespace snapshot ("state") carried by
    some message types is always stripped outright; extras["state_truncated"]
    is set to True when that happened for a given entry.

    Cross-graph guard: returns an error if session_id belongs to a different
    flow. Messages from nested subflow executions are excluded — only this
    flow's own trace is returned.
    """
    session = Session.objects.filter(graph_id=graph_id, pk=session_id).first()
    if session is None:
        return {"error": "Session not found or belongs to a different flow."}

    limit = max(1, min(200, int(limit)))

    # Most recent `limit` rows first (so a trailing error always survives the
    # cap), then reversed back to oldest→newest for the returned trace.
    rows = list(
        GraphSessionMessage.objects.filter(
            session_id=session_id, parent_subgraph_execution_id__isnull=True
        )
        .order_by("-execution_order", "-id")
        .values("name", "execution_order", "created_at", "message_data")[:limit]
    )
    rows.reverse()

    trace = [_graph_session_message_to_entry(row) for row in rows]
    trace = _apply_response_budget(trace, _MAX_RESPONSE_CHARS)

    return {
        "session_id": session_id,
        "messages": trace,
        "count": len(trace),
    }


_MAX_NODE_TRACE_ENTRIES = 200


def get_session_detail(graph_id: int, session_id: int) -> dict:
    """Return per-node execution trace metadata for one session of this flow.

    Returns timings + status + error summary per node — NO message bodies.
    Message text, agent thoughts, and task outputs are explicitly excluded.

    Cross-graph guard: if session_id belongs to a different graph, returns an
    error rather than leaking another flow's data.

    node_trace is derived from GraphSessionMessage rows (node_name,
    execution_order, created_at, message_type only — no message_data body
    fields). Capped to the most recent _MAX_NODE_TRACE_ENTRIES (200) entries
    — a tool-heavy run writes one row per tool call, so a long run keeps the
    most recent entries rather than being truncated from the start (a
    trailing error would otherwise be cut off). Messages from nested subflow
    executions are excluded — only this flow's own trace is returned. If no
    session-message rows exist, node_trace is an empty list.
    """
    session = Session.objects.filter(pk=session_id).first()
    if session is None:
        return {"error": "Session not found."}

    # Defense in depth: reject sessions that belong to a different graph.
    if session.graph_id != graph_id:
        return {"error": "Session not found or belongs to a different flow."}

    if session.finished_at and session.created_at:
        duration_seconds = int(
            (session.finished_at - session.created_at).total_seconds()
        )
    else:
        duration_seconds = None

    # Build node trace from message rows — timestamps and structural metadata only.
    # We deliberately do NOT read any message_data body fields (content, thought,
    # tool_input, state, ...) — only the message_type discriminator.
    rows = list(
        GraphSessionMessage.objects.filter(
            session_id=session_id, parent_subgraph_execution_id__isnull=True
        )
        .order_by("-execution_order", "-id")
        .values(
            "name",
            "execution_order",
            "created_at",
            message_type=F("message_data__message_type"),
        )[:_MAX_NODE_TRACE_ENTRIES]
    )
    rows.reverse()
    node_trace = [
        {
            "node_name": row["name"],
            "execution_order": row["execution_order"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "message_type": row["message_type"],
        }
        for row in rows
    ]

    _error_statuses = {
        Session.SessionStatus.ERROR,
        Session.SessionStatus.EXPIRED,
    }

    # Final / runtime variables are stored at Session.status_data["variables"] when
    # the crew publishes session-end status. Fall back to Session.variables when that
    # key is absent (abnormal termination before publish completed).
    runtime_variables = (session.status_data or {}).get("variables")
    final_variables = (
        runtime_variables if runtime_variables is not None else session.variables
    )

    return {
        "session_id": session.pk,
        "status": session.status,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "finished_at": session.finished_at.isoformat() if session.finished_at else None,
        "duration_seconds": duration_seconds,
        "has_error": session.status in _error_statuses,
        "entrypoint": session.entrypoint,
        "final_variables": final_variables,
        "node_trace": node_trace,
    }


def list_node_types(graph_id: int) -> list[str]:
    """Return the distinct node types present in the flow (edges excluded).

    One .exists() query per type — no prefetch, since only a boolean answer
    is needed and prefetching would materialise every row for nothing.
    """
    present = []
    for spec in FLOW_ASSISTANT_NODE_TYPES:
        if spec.is_edge:
            continue
        if spec.model.objects.filter(graph_id=graph_id).exists():
            present.append(spec.label)
    return present


def list_skills() -> dict:
    """Return the catalog of EpicStaff knowledge skills."""
    from .skills_loader import list_skills_summaries

    return {"skills": list_skills_summaries()}


def load_skill(name: str) -> dict:
    """Return the full content of one EpicStaff knowledge skill."""
    from .skills_loader import load_skill_body

    body = load_skill_body(name)
    if body is None:
        return {
            "error": f"Unknown skill '{name}'. Call list_skills to see available skills."
        }
    return {"name": name, "content": body}


# ── private enrichment helpers ───────────────────────────────────────────────


def _resolve_knowledge_metadata(
    knowledge_collection_ids: int | list[int] | None,
) -> list[dict]:
    """Return name and document count for one or more SourceCollection ids.

    Accepts either a single id (int) or an iterable of ids, so a caller
    resolving several collections at once pays for one query total instead
    of one .get() + one .count() per id. Ids that don't resolve to a
    SourceCollection are skipped. NEVER returns document content.
    """
    if knowledge_collection_ids is None:
        return []
    if isinstance(knowledge_collection_ids, int):
        ids = [knowledge_collection_ids]
    else:
        ids = [cid for cid in knowledge_collection_ids if cid is not None]
    if not ids:
        return []

    from tables.models.knowledge_models.collection_models import SourceCollection

    collections = SourceCollection.objects.filter(pk__in=ids).annotate(
        document_count=Count("documents")
    )
    return [
        {
            "id": collection.pk,
            "name": collection.collection_name,
            "description": None,  # SourceCollection has no description field
            "document_count": collection.document_count,
        }
        for collection in collections
    ]


def _resolve_llm_config_summary(llm_config) -> dict | None:
    """Return {provider, model, temperature} for an LLMConfig instance, or None."""
    if llm_config is None:
        return None

    model_name = llm_config.model.name if llm_config.model else None
    provider_name = None
    if llm_config.model and llm_config.model.llm_provider:
        provider_name = llm_config.model.llm_provider.name

    return {
        "provider": provider_name,
        "model": model_name,
        "temperature": llm_config.temperature,
    }


def _resolve_agent_definition(agent_definition_id: int | None):
    """Return the AgentDefinition for an FK value, or None if absent/missing."""
    if agent_definition_id is None:
        return None

    from agents.models.agent_models import AgentDefinition

    return (
        AgentDefinition.objects.select_related("llm_config__model__llm_provider")
        .filter(pk=agent_definition_id)
        .first()
    )


def _serialize_agent_definition(agent_definition) -> dict | None:
    """Return a summary of an AgentDefinition, or None if absent.

    No field here carries credential data: llm_config_summary
    (_resolve_llm_config_summary) deliberately excludes the API key at the
    source, so there is nothing left in this shape to redact.
    """
    if agent_definition is None:
        return None

    return {
        "id": agent_definition.pk,
        "name": agent_definition.name,
        "description": agent_definition.description,
        "instructions": agent_definition.instructions,
        "llm_config_summary": _resolve_llm_config_summary(agent_definition.llm_config),
    }


def _resolve_surfaces_tools_and_knowledge(node) -> tuple[list[dict], list[dict]]:
    """Resolve a node's available tools and knowledge sources as the runtime would.

    Delegates to NodeSurfaceService.build_combined_surface — the same
    allow/deny-precedence resolution the crew's node payload services use to
    build the actual tool pool for flow execution, sourced from
    node.surface_list + node.inline_surface only. This intentionally does
    NOT fall back to AgentDefinition default surfaces: flow execution never
    consults those (they apply to chat/realtime places, not flow), so
    including them would report tools the node cannot actually call.

    Deny-mode tool entries are excluded from the result, matching how the
    runtime builds its tool pool (BaseNodePayloadService._build_tool_pool
    only includes mode == "allow") — a denied tool is not callable by this
    node, so listing it would misrepresent what the LLM can do.
    """
    combined_surface = CombinedSurfaceData(
        **NodeSurfaceService.build_combined_surface(node)
    )

    allowed_python_tool_ids = [
        entry.python_tool
        for entry in combined_surface.python_tools
        if entry.mode == "allow"
    ]
    allowed_mcp_tool_ids = [
        entry.mcp_tool for entry in combined_surface.mcp_tools if entry.mode == "allow"
    ]

    tools: list[dict] = [
        {"name": name, "type": "python"}
        for name in PythonCodeTool.objects.filter(
            pk__in=allowed_python_tool_ids
        ).values_list("name", flat=True)
    ]
    tools.extend(
        {"name": name, "type": "mcp"}
        for name in McpTool.objects.filter(pk__in=allowed_mcp_tool_ids).values_list(
            "name", flat=True
        )
    )

    knowledge_sources = _resolve_knowledge_metadata(
        [entry.collection for entry in combined_surface.knowledge]
    )

    return tools, knowledge_sources


def _resolve_agent_node_tasks(agent_node_id: int) -> list[dict]:
    """Return the ordered sub-tasks (AgentNodeTask) executed by an AgentNode."""
    from tables.models.graph_models import AgentNodeTask

    tasks = (
        AgentNodeTask.objects.filter(agent_node_id=agent_node_id)
        .order_by("order")
        .prefetch_related("context_tasks")
    )
    return [
        {
            "id": task.pk,
            "name": task.name,
            "order": task.order,
            "instructions": task.instructions,
            "output_schema": task.output_schema,
            "context_task_ids": [ct.pk for ct in task.context_tasks.all()],
        }
        for task in tasks
    ]


def _resolve_agent_or_task_enrichment(node_type: str, node) -> dict:
    """Build the agent_definition / tools / knowledge_sources (/ tasks) block
    shared by AgentNode and TaskNode get_node responses.

    Tools and knowledge come from _resolve_surfaces_tools_and_knowledge,
    which mirrors the runtime's own resolution
    (node.surface_list + node.inline_surface, allow/deny precedence applied)
    instead of approximating it.
    """
    agent_definition = _resolve_agent_definition(
        getattr(node, "agent_definition_id", None)
    )

    tools, knowledge_sources = _resolve_surfaces_tools_and_knowledge(node)

    enrichment: dict = {
        "agent_definition": _serialize_agent_definition(agent_definition),
        "tools": tools,
        "knowledge_sources": knowledge_sources,
    }
    if node_type == "agent":
        enrichment["tasks"] = _resolve_agent_node_tasks(node.pk)
    return enrichment


def _resolve_python_code_summary(python_code_id: int | None) -> dict | None:
    """Return the user-authored Python for a node, or None if the FK is absent."""
    if python_code_id is None:
        return None
    try:
        pc = PythonCode.objects.only("code", "entrypoint", "libraries").get(
            pk=python_code_id
        )
    except PythonCode.DoesNotExist:
        return None
    return {
        "code": pc.code,
        "entrypoint": pc.entrypoint,
        "libraries": pc.get_libraries_list(),
    }


# ── internal helpers ──────────────────────────────────────────────────────────


def build_node_index(graph_id: int) -> dict[int, dict]:
    """Build a {node_pk: {type, name}} mapping for every node in the graph.

    Issues exactly one query per node table (15), fetching only the columns
    needed.  This replaces the previous per-edge try/except loop across all
    node tables, which produced O(edges × tables) queries.

    ConditionalEdge is deliberately included here even though it's an edge,
    not a node (NodeTypeSpec.is_edge) — the index is also used to resolve
    edge endpoints, and a ConditionalEdge can be the source/target of a plain
    Edge, so leaving it out would break that lookup.

    For models where node_name is a @property (StartNode, EndNode) we fetch
    only "id" and call the property after instantiation; Django reconstructs
    a minimal instance without touching the DB again.
    """
    index: dict[int, dict] = {}
    for spec in FLOW_ASSISTANT_NODE_TYPES:
        for node in spec.model.objects.filter(graph_id=graph_id).only(
            *spec.only_fields()
        ):
            index[node.pk] = {
                "type": spec.label,
                "name": spec.display_name(node),
            }
    return index


def _resolve_node_identity(node_pk: int, node_index: dict[int, dict]) -> dict:
    """Look up {type, name} for a node PK using a pre-built index.

    O(1) — no database queries.  node_index must have been produced by
    build_node_index() for the same graph_id.
    """
    return node_index.get(node_pk, {"type": "unknown", "name": ""})


# ── Public display-name helpers ───────────────────────────────────────────────


def resolve_node_display_name(
    graph_id: int,
    node_id: int,
    node_index: dict[int, dict] | None = None,
) -> str | None:
    """Best-effort lookup of a node's display name.  Returns None on miss.

    Pass node_index when resolving multiple nodes in a single graph context to
    avoid rebuilding the index each call.  If node_index is None, one is built
    internally (15 ORM queries — see build_node_index).
    """
    try:
        index = node_index if node_index is not None else build_node_index(graph_id)
        entry = index.get(int(node_id))
        if entry is None:
            return None
        name = entry.get("name") or None
        return name
    except (ValueError, TypeError):
        return None


def resolve_subgraph_display_name(graph_id: int, subgraph_node_id: int) -> str | None:
    """Best-effort lookup of the target subgraph's name.  Returns None on miss.

    subgraph_node_id is the PK of the SubGraphNode row (not the subgraph itself).
    """
    try:
        sn = SubGraphNode.objects.select_related("subgraph").get(
            pk=int(subgraph_node_id),
            graph_id=graph_id,
        )
        return sn.subgraph.name if sn.subgraph else None
    except (SubGraphNode.DoesNotExist, ValueError, TypeError):
        return None


# ── Tool specs ───────────────────────────────────────────────────────────────


def _flow_assistant_node_type_labels() -> str:
    """Comma-joined node type labels for the get_flow_overview ToolSpec description.

    Derived from FLOW_ASSISTANT_NODE_TYPES so this description can't drift
    from the registry the way a hand-maintained literal list would.
    ConditionalEdge is excluded — get_flow_overview folds it into edge_count,
    not the node list (see NodeTypeSpec.is_edge).
    """
    labels = []
    for spec in FLOW_ASSISTANT_NODE_TYPES:
        if spec.is_edge:
            continue
        label = spec.label
        if spec.deprecated:
            label += " (deprecated, legacy graphs only)"
        labels.append(label)
    return ", ".join(labels)


TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="get_flow_overview",
        description=(
            "Returns a high-level overview of the current flow: its name, description, "
            "node count by type, the full list of nodes (id + type + name only), "
            "total edge count (includes conditional_edge routing nodes, which route "
            "flow but are not themselves listed as nodes), and a list of direct "
            "subflows (name + description only, no internal details). Node types "
            f"include {_flow_assistant_node_type_labels()}. Canvas sticky notes are "
            "not nodes and are not included. Use this when asked to enumerate or "
            "look up nodes."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    ToolSpec(
        name="get_node",
        description=(
            "Returns the configuration and connectivity of a single node in the flow. "
            "Sensitive fields (api_key, secret, token) are redacted. "
            "For decision_table and classification_decision_table nodes, the response "
            "includes `decision_rules` with the full branching logic. "
            "For agent and task nodes, the response includes `agent_definition` "
            "(role/instructions/llm_config_summary of the assigned agent), `tools` "
            "(python/mcp tools the node can actually call at runtime, resolved with "
            "the same allow/deny precedence flow execution uses — denied tools are "
            "omitted), and `knowledge_sources` (attached knowledge collections — "
            "metadata only, never document content). Agent nodes additionally include "
            "`tasks`, the ordered sub-tasks the node executes. "
            "For conditional_edge nodes, the response includes `python_code_summary` "
            "for the routing logic. "
            "For python and webhook_trigger nodes, the response includes "
            "`python_code_summary` with the actual code body, entrypoint, and library "
            "list — use it to answer questions about what the node does, which APIs it "
            "calls, and what libraries it depends on. "
            "Provide the numeric node ID as a string."
        ),
        parameters={
            "type": "object",
            "properties": {
                "node_id": {
                    "type": "string",
                    "description": "The numeric ID of the node (e.g. '42').",
                }
            },
            "required": ["node_id"],
        },
    ),
    ToolSpec(
        name="get_subflow",
        description=(
            "Returns the name, description, and subgraph_graph_id of the target "
            "subflow referenced by a SubGraphNode. "
            "Pass the SubGraphNode's PK (the 'id' field of a node with type=='subgraph' "
            "from get_flow_overview) — NOT the target subflow's graph id. "
            "The response's subgraph_graph_id is the target graph's PK; use that with "
            "get_flow_overview(subgraph_graph_id) for recursive introspection."
        ),
        parameters={
            "type": "object",
            "properties": {
                "subgraph_node_id": {
                    "type": "string",
                    "description": "The numeric ID of the SubGraphNode row.",
                }
            },
            "required": ["subgraph_node_id"],
        },
    ),
    ToolSpec(
        name="get_edges_from",
        description="Returns the outgoing edges from a node (what nodes it leads to).",
        parameters={
            "type": "object",
            "properties": {
                "node_id": {
                    "type": "string",
                    "description": "The numeric ID of the source node.",
                }
            },
            "required": ["node_id"],
        },
    ),
    ToolSpec(
        name="get_edges_to",
        description="Returns the incoming edges to a node (what nodes lead to it).",
        parameters={
            "type": "object",
            "properties": {
                "node_id": {
                    "type": "string",
                    "description": "The numeric ID of the target node.",
                }
            },
            "required": ["node_id"],
        },
    ),
    ToolSpec(
        name="list_node_types",
        description="Returns the distinct node type tokens used in this flow.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    ToolSpec(
        name="list_skills",
        description=(
            "List available EpicStaff knowledge skills. Each entry has a slug and a "
            "short description of when to use that skill. Call this when you need "
            "deeper context about EpicStaff flow concepts, node types, debugging, "
            "or design principles than the inline system prompt provides. "
            "After deciding which skill applies, call load_skill(name=<slug>)."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="load_skill",
        description=(
            "Load the full content of one EpicStaff knowledge skill by its slug "
            "(as returned by list_skills). The body is a self-contained markdown "
            "document. Use this only after consulting list_skills — do not guess slugs. "
            "Each skill is several thousand tokens, so load only the one you need."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill slug from list_skills",
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="get_session_stats",
        description=(
            "Returns aggregate execution counts for this flow. Use when the user asks "
            "for counts of past runs — e.g. 'how many times did I run today?', "
            "'how many failed last week?', 'how many are in error status?'. "
            "All parameters are optional. since/until must be ISO 8601 timestamps "
            "(e.g. '2026-05-15T00:00:00Z'). status must be one of: "
            "pending, run, wait_for_user, error, end, stop, expired. "
            "Response includes total count and by_status breakdown."
        ),
        parameters={
            "type": "object",
            "properties": {
                "since": {
                    "type": "string",
                    "description": (
                        "ISO 8601 timestamp (inclusive lower bound on created_at). "
                        "e.g. '2026-05-15T00:00:00Z'."
                    ),
                },
                "until": {
                    "type": "string",
                    "description": (
                        "ISO 8601 timestamp (exclusive upper bound on created_at). "
                        "e.g. '2026-05-16T00:00:00Z'."
                    ),
                },
                "status": {
                    "type": "string",
                    "description": (
                        "Filter by session status. One of: "
                        "pending, run, wait_for_user, error, end, stop, expired."
                    ),
                },
            },
            "required": [],
        },
    ),
    ToolSpec(
        name="get_recent_sessions",
        description=(
            "Returns the most recent EXECUTION sessions for this flow (not Flow "
            "Assistant chat conversations). Use this when asked whether the flow "
            "has run recently, whether the last run succeeded, how often it runs, "
            "what errors occurred, or to search runs by input variable value. "
            "Each entry has status, timestamps, duration, has_error, entrypoint, "
            "and start_variables (initial inputs only). "
            "Optional params: since/until (ISO 8601 timestamps) for date range; "
            "where (flat dict of variable key→value) to filter by input value "
            '(e.g. where={"city": "Berlin"} finds sessions whose variables.city=Berlin); '
            "include_full_variables=true to also get full_variables per row — "
            "the final variable namespace after the flow ran (inputs + outputs, "
            "e.g. shows what the flow produced). "
            "Can return large objects — combine with targeted where and low limit. "
            "limit defaults to 5, maximum 25."
        ),
        parameters={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of recent sessions to return (1–25, default 5).",
                    "default": 5,
                },
                "since": {
                    "type": "string",
                    "description": (
                        "ISO 8601 timestamp (inclusive). Only sessions created at or "
                        "after this time are returned. e.g. '2026-05-15T00:00:00Z'."
                    ),
                },
                "until": {
                    "type": "string",
                    "description": (
                        "ISO 8601 timestamp (exclusive). Only sessions created before "
                        "this time are returned. e.g. '2026-05-16T00:00:00Z'."
                    ),
                },
                "where": {
                    "type": "object",
                    "description": (
                        "Flat key→value dict to filter sessions by input variable value. "
                        'e.g. {"city": "Berlin"} returns only sessions whose '
                        "variables[\"city\"] equals 'Berlin'."
                    ),
                    "additionalProperties": True,
                },
                "include_full_variables": {
                    "type": "boolean",
                    "description": (
                        "When true, each result row includes a full_variables field "
                        "containing the final variable namespace state after the flow ran "
                        "(inputs + outputs). Use this to inspect what the flow produced. "
                        "start_variables always holds the initial inputs only. "
                        "Can be large — prefer targeted queries."
                    ),
                    "default": False,
                },
            },
            "required": [],
        },
    ),
    ToolSpec(
        name="get_session_detail",
        description=(
            "Returns per-node execution trace metadata (timings and status) for one "
            "EXECUTION session of this flow. Use this to investigate a specific failure "
            "after calling get_recent_sessions. Each node_trace entry has node_name, "
            "execution_order, created_at, and message_type (e.g. start, finish, error, "
            "python, subgraph_start, agent_node_stream, task_node_stream, "
            "extracted_chunks) — NO message bodies or content text. Capped to the most "
            "recent 200 entries; nested subflow messages are excluded. "
            "Provide the numeric session ID (from get_recent_sessions output). "
            "To see node/tool/task outputs, use get_session_messages instead."
        ),
        parameters={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "integer",
                    "description": "The numeric ID of the session to inspect.",
                }
            },
            "required": ["session_id"],
        },
    ),
    ToolSpec(
        name="get_session_messages",
        description=(
            "Returns the per-step execution trace for a session, oldest to newest: "
            "node start/finish, subgraph start/finish, python execution, agent/task "
            "tool-call and tool-result stream events, knowledge retrieval, decision-"
            "table branch results, classification prompts, and errors. Use after "
            "get_recent_sessions identifies the target session_id, when the user asks "
            "how a specific run arrived at its answer or why it failed. "
            "Returns the MOST RECENT entries up to limit (1–200, default 50) so a "
            "trailing error is never truncated away. Bodies are size-bounded: string "
            "fields are truncated per-field and the whole response is capped by an "
            "overall budget (see extras.body_dropped_for_response_budget). The full "
            "variable-namespace snapshot some entries carry internally is always "
            "stripped; entries where that happened have extras.state_truncated=true."
        ),
        parameters={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "integer",
                    "description": "The numeric ID of the session (from get_recent_sessions).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max trace entries to return (1–200, default 50).",
                    "default": 50,
                },
            },
            "required": ["session_id"],
        },
    ),
]


# ── Tool callable registry ────────────────────────────────────────────────────

# Map tool name → callable(graph_id, **kwargs).
# Kept here alongside the tool implementations it dispatches to.
_TOOL_CALLABLES: dict[str, callable] = {
    "get_flow_overview": lambda graph_id, **_: get_flow_overview(graph_id),
    "get_node": lambda graph_id, node_id, **_: get_node(graph_id, node_id),
    "get_subflow": lambda graph_id, subgraph_node_id, **_: get_subflow(
        graph_id, subgraph_node_id
    ),
    "get_edges_from": lambda graph_id, node_id, **_: get_edges_from(graph_id, node_id),
    "get_edges_to": lambda graph_id, node_id, **_: get_edges_to(graph_id, node_id),
    "list_node_types": lambda graph_id, **_: list_node_types(graph_id),
    # Skill tools are graph-independent; graph_id is accepted but ignored.
    "list_skills": lambda _graph_id, **__: list_skills(),
    "load_skill": lambda _graph_id, name, **__: load_skill(name),
    # Session tools are org-scoped by graph_id inside the tool implementation.
    "get_session_stats": lambda graph_id, since=None, until=None, status=None, **_: (
        get_session_stats(graph_id, since=since, until=until, status=status)
    ),
    "get_recent_sessions": lambda graph_id,
    limit=5,
    since=None,
    until=None,
    where=None,
    include_full_variables=False,
    **_: (
        get_recent_sessions(
            graph_id,
            limit=int(limit),
            since=since,
            until=until,
            where=where,
            include_full_variables=bool(include_full_variables),
        )
    ),
    "get_session_detail": lambda graph_id, session_id, **_: get_session_detail(
        graph_id, int(session_id)
    ),
    "get_session_messages": lambda graph_id, session_id, limit=50, **_: (
        get_session_messages(graph_id, int(session_id), limit=int(limit))
    ),
}
