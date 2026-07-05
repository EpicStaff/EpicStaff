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

import re

from django.db.models import Count, Prefetch
from django.utils.dateparse import parse_datetime

from tables.services.llm_clients import ToolSpec

from tables.models.session_models import Session
from tables.models.python_models import PythonCode
from tables.models.graph_models import (
    AudioTranscriptionNode,
    ClassificationDecisionTableNode,
    ClassificationConditionGroup,
    CodeAgentNode,
    ConditionGroup,
    CrewNode,
    DecisionTableNode,
    Edge,
    EndNode,
    FileExtractorNode,
    PythonNode,
    StartNode,
    SubGraphNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)

_SECRET_PATTERN = re.compile(r"api_key|secret|token", re.IGNORECASE)

# ── node tables in evaluation order ──────────────────────────────────────────

# Each entry: (type_label, model_class, has_db_node_name).
# has_db_node_name=False means node_name is a @property returning a fixed
# string (StartNode → "__start__", EndNode → "__end_node__"); we must NOT
# pass "node_name" to .only() for those models or Django will raise
# FieldDoesNotExist.
_NODE_TABLES: list[tuple[str, type, bool]] = [
    ("crew", CrewNode, True),
    ("python", PythonNode, True),
    ("file_extractor", FileExtractorNode, True),
    ("audio_transcription", AudioTranscriptionNode, True),
    ("subgraph", SubGraphNode, True),
    ("code_agent", CodeAgentNode, True),
    ("start", StartNode, False),
    ("end", EndNode, False),
    ("decision_table", DecisionTableNode, True),
    ("classification_decision_table", ClassificationDecisionTableNode, True),
    ("webhook_trigger", WebhookTriggerNode, True),
    ("telegram_trigger", TelegramTriggerNode, True),
]


def _redact(value: object, key: str = "") -> object:
    """Recursively redact secret fields in a plain-Python structure."""
    if isinstance(value, dict):
        return {k: _redact(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if key and _SECRET_PATTERN.search(key):
        return "***"
    return value


def _node_to_dict(node_type: str, node) -> dict:
    """Convert a node ORM object to a sanitised dict.

    Relations (FK / OneToOne) are skipped generically — surface them
    explicitly via the post-loop resolver blocks in `get_node` when needed.
    """
    result: dict = {"type": node_type, "id": node.pk}
    if hasattr(node, "node_name"):
        result["name"] = node.node_name

    skip = {"id", "metadata", "content_hash"}
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
                "prompt_id": group.prompt_id,
            }
        )
    return rules


# ── public tool functions ─────────────────────────────────────────────────────


def get_flow_overview(graph_id: int) -> dict:
    """Return a high-level summary of the flow."""
    from tables.models.graph_models import Graph

    graph = Graph.objects.prefetch_related(
        "crew_node_list",
        "python_node_list",
        "file_extractor_node_list",
        "audio_transcription_node_list",
        "code_agent_node_list",
        "start_node_list",
        "end_node",
        "decision_table_node_list",
        "classification_decision_table_node_list",
        "webhook_trigger_node_list",
        "telegram_trigger_node_list",
        "edge_list",
        Prefetch(
            "subgraph_node_list",
            queryset=SubGraphNode.objects.select_related("subgraph"),
        ),
    ).get(pk=graph_id)

    node_count_by_type = {
        "crew": graph.crew_node_list.count(),
        "python": graph.python_node_list.count(),
        "file_extractor": graph.file_extractor_node_list.count(),
        "audio_transcription": graph.audio_transcription_node_list.count(),
        "subgraph": graph.subgraph_node_list.count(),
        "code_agent": graph.code_agent_node_list.count(),
        "start": graph.start_node_list.count(),
        "end": graph.end_node.count(),
        "decision_table": graph.decision_table_node_list.count(),
        "classification_decision_table": graph.classification_decision_table_node_list.count(),
        "webhook_trigger": graph.webhook_trigger_node_list.count(),
        "telegram_trigger": graph.telegram_trigger_node_list.count(),
    }

    # Build flat node list sorted by (type, id).
    # For has_db_node_name=True tables the prefetch already loaded the rows;
    # we do a small per-table .only() pass here to keep things simple and
    # avoid pulling unneeded columns out of the prefetch cache.
    raw_nodes: list[tuple[str, int, str]] = []
    for node_type, model_cls, has_db_node_name in _NODE_TABLES:
        fields = ["id", "node_name"] if has_db_node_name else ["id"]
        for node in model_cls.objects.filter(graph_id=graph_id).only(*fields):
            raw_nodes.append((node_type, node.pk, getattr(node, "node_name", "")))
    raw_nodes.sort(key=lambda t: (t[0], t[1]))
    nodes: list[dict] = [
        {"id": node_id, "type": node_type, "name": name}
        for node_type, node_id, name in raw_nodes
    ]

    subflows = [
        {
            "id": sn.subgraph.pk,
            "name": sn.subgraph.name,
            "description": sn.subgraph.description,
        }
        for sn in graph.subgraph_node_list.all()
        if sn.subgraph
    ]

    return {
        "id": graph.pk,
        "name": graph.name,
        "description": graph.description,
        "node_count_by_type": node_count_by_type,
        "nodes": nodes,
        "edge_count": graph.edge_list.count(),
        "subflows": subflows,
    }


def get_node(graph_id: int, node_id: str) -> dict:
    """Resolve a node by PK across all node tables and return its config.

    node_id is expected to be an integer string (e.g. "42").  Secrets are
    redacted from config output.

    Uses the node index to find the correct table first (1 query), then
    fetches the full object from that table (1 query) — 2 queries total
    instead of up to 13 try/except probes.
    """
    try:
        pk = int(node_id)
    except (ValueError, TypeError):
        return {"error": f"Invalid node_id '{node_id}': must be an integer string."}

    # One query per table maximum, covering the whole graph.  For a single
    # node lookup this still pays the full index-build cost, but it replaces
    # up to 13 sequential try/get probes with a fixed 13-query batch.
    node_index = build_node_index(graph_id)
    identity = node_index.get(pk)
    if identity is None:
        return {"error": f"Node with id={node_id} not found in graph {graph_id}."}

    node_type = identity["type"]
    model_cls = next(model for label, model, _ in _NODE_TABLES if label == node_type)
    node = model_cls.objects.get(pk=pk, graph_id=graph_id)
    result = _node_to_dict(node_type, node)

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

    # Phase C: attach LLM config summary for nodes that have an llm_config FK.
    if node_type == "code_agent":
        llm_config_id = getattr(node, "llm_config_id", None)
        result["llm_config_summary"] = _resolve_llm_config_summary(llm_config_id)

    # Phase D: attach crew summary for CrewNode.
    if node_type == "crew":
        crew_id = getattr(node, "crew_id", None)
        result["crew_summary"] = _resolve_crew_summary(crew_id)

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

    # Build the index once for the whole graph — O(13) queries regardless of
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

    # Build the index once for the whole graph — O(13) queries regardless of
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


def get_session_messages(
    graph_id: int,
    session_id: int,
    limit: int = 50,
) -> dict:
    """Return the per-step execution trace for a session, including agent thoughts
    and task outputs.

    Use after get_recent_sessions identifies the target session_id.
    Useful for explaining HOW a specific run reached its output — agent reasoning,
    tool calls, and task completions are all surfaced here.

    Bodies may be large — set a targeted limit (1–200, default 50).

    Cross-graph guard: returns an error if session_id belongs to a different flow.
    """
    from tables.models.session_models import AgentSessionMessage, TaskSessionMessage

    session = Session.objects.filter(graph_id=graph_id, pk=session_id).first()
    if session is None:
        return {"error": "Session not found or belongs to a different flow."}

    limit = max(1, min(200, int(limit)))

    agent_rows = list(
        AgentSessionMessage.objects.filter(session_id=session_id)
        .order_by("execution_order", "created_at")
        .values(
            "node_name",
            "execution_order",
            "created_at",
            "thought",
            "text",
            "result",
            "tool",
            "tool_input",
        )[:limit]
    )
    task_rows = list(
        TaskSessionMessage.objects.filter(session_id=session_id)
        .order_by("execution_order", "created_at")
        .values(
            "node_name",
            "execution_order",
            "created_at",
            "name",
            "description",
            "expected_output",
            "raw",
            "agent",
        )[:limit]
    )

    trace = []
    for row in agent_rows:
        extras: dict = {}
        if row["text"]:
            extras["text"] = row["text"]
        if row["tool"]:
            extras["tool"] = row["tool"]
        if row["tool_input"]:
            extras["tool_input"] = row["tool_input"]
        if row["result"]:
            extras["result"] = row["result"]

        trace.append(
            {
                "kind": "agent",
                "node_name": row["node_name"],
                "execution_order": row["execution_order"],
                "created_at": row["created_at"].isoformat()
                if row["created_at"]
                else None,
                "content": row["thought"],
                "extras": extras,
            }
        )

    for row in task_rows:
        extras = {}
        if row["description"]:
            extras["description"] = row["description"]
        if row["expected_output"]:
            extras["expected_output"] = row["expected_output"]
        if row["agent"]:
            extras["agent"] = row["agent"]

        trace.append(
            {
                "kind": "task",
                "node_name": row["node_name"],
                "execution_order": row["execution_order"],
                "created_at": row["created_at"].isoformat()
                if row["created_at"]
                else None,
                "content": row["raw"],
                "name": row["name"],
                "extras": extras,
            }
        )

    trace.sort(key=lambda e: (e["execution_order"], e["created_at"] or ""))

    # Clamp to limit after merge (each per-kind query already limits, but the
    # merged list could be up to 2×limit before this final clamp).
    trace = trace[:limit]

    return {
        "session_id": session_id,
        "messages": trace,
        "count": len(trace),
    }


def get_session_detail(graph_id: int, session_id: int) -> dict:
    """Return per-node execution trace metadata for one session of this flow.

    Returns timings + status + error summary per node — NO message bodies.
    Message text, agent thoughts, and task outputs are explicitly excluded.

    Cross-graph guard: if session_id belongs to a different graph, returns an
    error rather than leaking another flow's data.

    node_trace is derived from AgentSessionMessage and TaskSessionMessage rows
    (created_at, node_name, execution_order only — no body text).  If no
    session-message rows exist, node_trace is an empty list.
    """
    from tables.models.session_models import AgentSessionMessage, TaskSessionMessage

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
    # We deliberately do NOT read any text/content fields.
    agent_entries = list(
        AgentSessionMessage.objects.filter(session_id=session_id)
        .order_by("execution_order", "created_at")
        .values("node_name", "execution_order", "created_at")
    )
    task_entries = list(
        TaskSessionMessage.objects.filter(session_id=session_id)
        .order_by("execution_order", "created_at")
        .values("node_name", "execution_order", "created_at")
    )

    node_trace = []
    for entry in agent_entries:
        node_trace.append(
            {
                "kind": "agent",
                "node_name": entry["node_name"],
                "execution_order": entry["execution_order"],
                "timestamp": entry["created_at"].isoformat()
                if entry["created_at"]
                else None,
            }
        )
    for entry in task_entries:
        node_trace.append(
            {
                "kind": "task",
                "node_name": entry["node_name"],
                "execution_order": entry["execution_order"],
                "timestamp": entry["created_at"].isoformat()
                if entry["created_at"]
                else None,
            }
        )
    node_trace.sort(key=lambda e: (e["execution_order"], e["timestamp"] or ""))

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
    """Return the distinct node types present in the flow."""
    from tables.models.graph_models import Graph

    graph = Graph.objects.prefetch_related(
        "crew_node_list",
        "python_node_list",
        "file_extractor_node_list",
        "audio_transcription_node_list",
        "subgraph_node_list",
        "code_agent_node_list",
        "start_node_list",
        "end_node",
        "decision_table_node_list",
        "classification_decision_table_node_list",
        "webhook_trigger_node_list",
        "telegram_trigger_node_list",
    ).get(pk=graph_id)

    present = []
    checks = [
        ("crew", graph.crew_node_list),
        ("python", graph.python_node_list),
        ("file_extractor", graph.file_extractor_node_list),
        ("audio_transcription", graph.audio_transcription_node_list),
        ("subgraph", graph.subgraph_node_list),
        ("code_agent", graph.code_agent_node_list),
        ("start", graph.start_node_list),
        ("end", graph.end_node),
        ("decision_table", graph.decision_table_node_list),
        (
            "classification_decision_table",
            graph.classification_decision_table_node_list,
        ),
        ("webhook_trigger", graph.webhook_trigger_node_list),
        ("telegram_trigger", graph.telegram_trigger_node_list),
    ]
    for label, qs in checks:
        if qs.exists():
            present.append(label)
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


def _resolve_llm_config_summary(llm_config_id: int | None) -> dict | None:
    """Return a provider/model/temperature summary for an LLMConfig FK value.

    Returns None when llm_config_id is None (the FK is nullable on CodeAgentNode).
    Tolerates a missing LLMConfig row (returns None rather than raising).
    """
    if llm_config_id is None:
        return None

    from tables.models.llm_models import LLMConfig

    try:
        llm_config = LLMConfig.objects.select_related("model__llm_provider").get(
            pk=llm_config_id
        )
    except LLMConfig.DoesNotExist:
        return None

    provider_name = None
    model_name = None
    if llm_config.model:
        model_name = llm_config.model.name
        if llm_config.model.llm_provider:
            provider_name = llm_config.model.llm_provider.name

    return {
        "provider": provider_name,
        "model": model_name,
        "temperature": llm_config.temperature,
    }


def _resolve_knowledge_metadata(knowledge_collection_id: int | None) -> list[dict]:
    """Return name and document count for a SourceCollection FK value.

    Returns an empty list when knowledge_collection_id is None.
    NEVER returns document content.
    """
    if knowledge_collection_id is None:
        return []

    from tables.models.knowledge_models.collection_models import SourceCollection

    try:
        collection = SourceCollection.objects.get(pk=knowledge_collection_id)
    except SourceCollection.DoesNotExist:
        return []

    return [
        {
            "id": collection.pk,
            "name": collection.collection_name,
            "description": None,  # SourceCollection has no description field
            "document_count": collection.documents.count(),
        }
    ]


def _resolve_crew_summary(crew_id: int | None) -> dict | None:
    """Return a structural summary of a Crew for a CrewNode.

    Includes agent roles/goals and task names/descriptions at overview level.
    Explicitly excludes agent backstories and task instructions (prompt text)
    to avoid leaking proprietary persona content.

    Returns None when crew_id is None or the Crew row does not exist.
    """
    if crew_id is None:
        return None

    from tables.models.crew_models import Crew, Task

    try:
        crew = Crew.objects.prefetch_related("agents").get(pk=crew_id)
    except Crew.DoesNotExist:
        return None

    agents = [{"role": agent.role, "goal": agent.goal} for agent in crew.agents.all()]

    tasks_qs = Task.objects.filter(crew=crew).order_by("order", "pk")
    tasks = [
        {
            "name": task.name,
            "description": task.instructions[:200] if task.instructions else None,
        }
        for task in tasks_qs
    ]

    return {
        "id": crew.pk,
        "name": crew.name,
        "description": crew.description,
        "process": crew.process,
        "agent_count": len(agents),
        "task_count": len(tasks),
        "agents": agents,
        "tasks": tasks,
    }


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

    Issues exactly one query per node table (up to 13), fetching only the
    columns needed.  This replaces the previous per-edge try/except loop
    across all 13 tables, which produced O(edges × tables) queries.

    For models where node_name is a @property (StartNode, EndNode) we fetch
    only "id" and call the property after instantiation; Django reconstructs
    a minimal instance without touching the DB again.
    """
    index: dict[int, dict] = {}
    for node_type, model_cls, has_db_node_name in _NODE_TABLES:
        fields = ["id", "node_name"] if has_db_node_name else ["id"]
        for node in model_cls.objects.filter(graph_id=graph_id).only(*fields):
            index[node.pk] = {
                "type": node_type,
                "name": getattr(node, "node_name", ""),
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
    internally (up to 13 ORM queries).
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

TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="get_flow_overview",
        description=(
            "Returns a high-level overview of the current flow: its name, description, "
            "node count by type, the full list of nodes (id + type + name only), "
            "total edge count, and a list of direct subflows (name + description only, "
            "no internal details). Use this when asked to enumerate or look up nodes."
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
            "For llm and code_agent nodes, the response includes `llm_config_summary` "
            "with provider, model, and temperature. "
            "For crew nodes, the response includes `crew_summary` with agents and tasks. "
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
            "after calling get_recent_sessions. Returns node_name, execution order, "
            "and timestamps per node — NO message bodies or content text. "
            "Provide the numeric session ID (from get_recent_sessions output). "
            "To see agent reasoning and task outputs, use get_session_messages instead."
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
            "Returns the per-step execution trace for a session, including agent thoughts, "
            "tool calls, and task outputs. Use after get_recent_sessions identifies the "
            "target session_id, when the user asks how a specific run arrived at its answer "
            "or wants to see the agent reasoning chain. "
            "Bodies may be large — set a targeted limit (1–200, default 50)."
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
