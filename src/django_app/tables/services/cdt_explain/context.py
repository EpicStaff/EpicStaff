"""Renders the frontend's explain payload into the user message.

Labelled plain text rather than JSON: fewer tokens, and the model reads the
table's shape more reliably than it reads nested braces.
"""

from typing import Any

CODE_LIMIT = 2000
TEXT_LIMIT = 1500

_OPERATOR_PREFIXES = (
    "==", "!=", ">=", "<=", ">", "<", "in ", "not ", "is ",
)

_KIND_LABELS = {
    "pre_computation": "preparation script",
    "post_computation": "cleanup script",
    "condition": "condition",
    "prompt": "AI prompt",
    "manipulation": "assignments",
}


def _truncate(value: str, limit: int) -> str:
    value = (value or "").strip()
    if len(value) <= limit:
        return value
    return f"{value[:limit].rstrip()}\n… (truncated — {len(value) - limit} more characters)"


def _field_clause(name: str, fragment: str) -> str:
    """Mirror of the engine's field-fragment normalisation, in display form."""
    fragment = (fragment or "").strip()
    if not fragment:
        return ""
    if fragment.startswith(_OPERATOR_PREFIXES):
        return f"@{name} {fragment}"
    if " and " in fragment or " or " in fragment or "@" in fragment:
        return fragment
    return f"@{name} == {fragment}"


def _clause_set(expression: str) -> set[str]:
    return {
        " ".join(part.split())
        for part in (expression or "").split(" and ")
        if part.strip()
    }


def _render_conditions(block: dict) -> list[str]:
    expression = (block.get("expression") or "").strip()
    fields = block.get("field_expressions") or {}
    field_clauses = [c for c in (_field_clause(k, v) for k, v in fields.items()) if c]

    if not expression and not field_clauses:
        return ["  condition: none — this rule always matches"]

    lines = []
    if expression:
        lines.append(f"  condition: {expression}")
    if field_clauses:
        redundant = expression and _clause_set(" and ".join(field_clauses)) <= _clause_set(expression)
        if not redundant:
            lines.append(f"  column conditions (combined with and): {'; '.join(field_clauses)}")
    return lines


def _render_mapping(label: str, mapping: dict | None, indent: str = "  ") -> list[str]:
    if not mapping:
        return []
    pairs = "; ".join(f"{k} ← {v}" for k, v in mapping.items())
    return [f"{indent}{label}: {pairs}"]


def render_table(table: dict) -> str:
    lines = [
        "THE TABLE THIS STEP BELONGS TO",
        f"  name: {table.get('node_name') or '(unnamed)'}",
        f"  default destination: {table.get('default_next_node') or '(none — the flow ends here)'}",
        f"  error destination: {table.get('error_next_node') or '(none — the flow ends here)'}",
        f"  model the table's prompts run on: {table.get('default_model') or 'Default LLM'}",
        "  rules, in the order they are checked:",
    ]
    rules = table.get("rules") or []
    if not rules:
        lines.append("    (none)")
    for rule in rules:
        state = "enabled" if rule.get("enabled", True) else "DISABLED — never checked"
        lines.append(f"    {rule.get('order')}. {rule.get('name')} [{state}]")
    return "\n".join(lines)


def render_block(block: dict, position: int, total: int) -> str:
    kind = block.get("block")
    lines = [
        f"STEP {position} of {total}",
        f"  id: {block['id']}",
        f"  kind: {_KIND_LABELS.get(kind, kind)}",
    ]

    if kind in ("pre_computation", "post_computation"):
        lines += _render_mapping("values it receives", block.get("input_map"))
        path = block.get("output_variable_path")
        lines.append(f"  result stored as: {path}" if path else "  result stored as: (not kept)")
        libraries = block.get("libraries") or []
        if libraries:
            lines.append(f"  outside tools used: {', '.join(libraries)}")
        lines.append("  code:")
        lines.append(_truncate(block.get("code"), CODE_LIMIT))

    elif kind == "condition":
        enabled = block.get("enabled", True)
        state = "enabled" if enabled else "DISABLED — never checked, nothing in it runs"
        lines.append(f"  rule: {block.get('rule_name')} (position {block.get('order')}, {state})")
        lines += _render_conditions(block)
        on_match = block.get("on_match") or {}
        prompt = on_match.get("prompt")
        lines.append(f"  on match, runs the AI prompt: {prompt}" if prompt else "  on match, runs no AI prompt")
        lines.append(
            "  on match, changes stored values: yes"
            if on_match.get("sets_variables")
            else "  on match, changes stored values: no"
        )
        goes_to = on_match.get("goes_to")
        if goes_to == "default_exit":
            destination = "the table's default destination"
        elif goes_to:
            destination = f'"{goes_to}"'
        else:
            destination = "nowhere — nothing is connected, so the table's default destination applies"
        lines.append(f"  on match, sends the work to: {destination}")
        lines.append(f"  continue after match: {'on' if block.get('continue_after_match') else 'off'}")
        if goes_to and goes_to != "default_exit":
            lines.append(
                "    (this rule has a destination, so the table stops here when it matches — "
                "the continue setting has no effect)"
            )
        no_match = block.get("on_no_match")
        lines.append(
            "  if the test fails: the work goes to the table's default destination (no rule below can match)"
            if no_match == "default_exit"
            else "  if the test fails: the next rule is checked"
        )
        route_code = block.get("route_code")
        if route_code:
            lines.append(f"  outgoing connector label: {route_code} (a label only — it does not affect routing)")

    elif kind == "prompt":
        lines.append(f"  belongs to rule: {block.get('rule_name')} — runs only when that rule matches")
        lines.append(f"  prompt name: {block.get('prompt_key')}")
        lines.append(f"  answered by: {block.get('model') or 'Default LLM'}")
        lines.append(f"  answer stored as: {block.get('result_variable')}")
        # `fills` is the old name for the same value; the handoff misdescribed it
        # as an input map (contract D1). Accept both keys, label it correctly.
        mappings = block.get("result_mappings")
        if mappings is None:
            mappings = block.get("fills")
        lines += _render_mapping("after the answer returns, these values are filled from its fields", mappings)
        if block.get("answer_schema"):
            lines.append("  the answer must come back as structured fields, not free text")
        lines.append("  prompt text:")
        lines.append(_truncate(block.get("text"), TEXT_LIMIT))

    elif kind == "manipulation":
        lines.append(f"  belongs to rule: {block.get('rule_name')} — runs only when that rule matches")
        assignments = (block.get("assignments") or "").strip()
        field_assignments = block.get("field_assignments") or {}
        if assignments:
            lines.append(f"  sets: {assignments}")
        for name, value in field_assignments.items():
            lines.append(f"  sets: @{name} = {value}")
        if not assignments and not field_assignments:
            lines.append("  sets: nothing — this rule changes no values when it matches")

    return "\n".join(lines)


def render_user_message(table: dict, blocks: list[dict[str, Any]]) -> str:
    total = len(blocks)
    parts = [render_table(table), ""]
    parts += [render_block(block, i, total) for i, block in enumerate(blocks, start=1)]
    parts.append(
        f"\nWrite one explanation for each of the {total} step(s) above, "
        "using each step's id exactly as given."
    )
    return "\n\n".join(parts)
