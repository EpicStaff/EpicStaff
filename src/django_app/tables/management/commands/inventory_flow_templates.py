"""List the placeholders in flow templates that do not run as their author meant.

Ops run this before a release on each installation and send the rows to the flow owners.
It is operator-only, so it reads every organization. CSV goes to stdout, a count per category
to stderr.

Sources: the only author texts crew renders through `src.shared.flow_templates`:

- `TaskNode.instructions`
- `AgentNodeTask.instructions`, reported on its agent node
- `KnowledgeNode.query`
- `ClassificationDecisionTablePrompt.prompt_text`, LLM prompts only: a System One prompt reaches
  crew with an empty `prompt_text`. `ClassificationDecisionTableNode.prompts` is never sent to
  crew.

A new template field that crew renders must be added to `_templates` here too, or this report
misses it. The save and import check in `tables/validators/run_refusal_validator.py` lists the
same template fields and needs it as well.

Only live flows and live nodes are read, through the default managers. A session runs only a
live graph's live nodes; binned rows and version snapshots (JSON in `GraphVersion.snapshot`)
never run. A restored flow is live again, and the next run of this command reports it.

Categories, by the classification in `src.shared.flow_templates`:

- refused: a REFUSED placeholder; crew fails the node.
- not rendered: a POSITIONAL placeholder other than an empty `{}` (`{0}`, `{.a}`, `{[0]}`), or a
  FORMATTED / BAD_PATH one whose head is an identifier, so the author most likely meant a
  variable. Crew sends the template as written.
- review: the template is sent as written because of a JSON example (`{"a": 1}`, or an empty
  `{}` as in "return {} if none"), and that silently leaves
  each VALUE placeholder in it unfilled, one row per VALUE placeholder. Also one row, with no
  placeholder, for a template that does not parse and holds placeholder-like text. A template
  whose only braces are JSON examples is sent as written, as meant, and produces no row.
"""

import csv
import re
from collections import Counter
from collections.abc import Iterator

from django.core.management.base import BaseCommand
from src.shared.flow_templates import Placeholder, PlaceholderKind, inspect_template
from tables.import_export.export_tabular_projections._csv_helpers import _neutralize_formula
from tables.models import (
    AgentNode,
    AgentNodeTask,
    ClassificationDecisionTableNode,
    ClassificationDecisionTablePrompt,
    Graph,
    KnowledgeNode,
    TaskNode,
)

COLUMNS = (
    "org_id",
    "org_name",
    "flow_id",
    "flow_name",
    "node_type",
    "node_id",
    "node_name",
    "field",
    "placeholder",
    "category",
    "reason",
)
REFUSED = "refused"
NOT_RENDERED = "not rendered"
REVIEW = "review"

# The kinds a JSON example such as `{"a": 1}` parses as.
_EXAMPLE_KINDS = (PlaceholderKind.FORMATTED, PlaceholderKind.BAD_PATH)
# An innermost `{...}` that is not one half of a `{{` or `}}` escape.
_BRACED_TEXT = re.compile(r"(?<!\{)\{[^{}]*\}(?!\})")


class Command(BaseCommand):
    help = (
        "Print, as CSV, the placeholders in live flow templates that crew refuses or sends "
        "unrendered, with a count per category on stderr."
    )

    def handle(self, *args, **options):
        writer = csv.writer(self.stdout)
        writer.writerow(COLUMNS)
        counts = Counter()
        for graph, node_type, node_id, node_name, field, template in _templates():
            for placeholder, category, reason in _template_findings(template):
                # Every org's names in one sheet that ops open and forward: no cell may run as a formula.
                writer.writerow(
                    _neutralize_formula(value)
                    for value in (
                        graph.org_id,
                        graph.org.name,
                        graph.pk,
                        graph.name,
                        node_type,
                        node_id,
                        node_name,
                        field,
                        placeholder,
                        category,
                        reason,
                    )
                )
                counts[category] += 1
        for category in (REFUSED, NOT_RENDERED, REVIEW):
            self.stderr.write(f"{category}: {counts[category]}")


def _template_findings(template: str) -> list[tuple[str, str, str]]:
    """Return `(placeholder, category, reason)` for each problem in `template`, without repeats."""
    inspection = inspect_template(template)
    if inspection.parse_error is not None:
        if _holds_placeholder_like_text(template):
            return [("", REVIEW, inspection.parse_error)]
        return []

    examples = [placeholder for placeholder in inspection.placeholders if _is_example(placeholder)]
    findings = []
    for placeholder in inspection.placeholders:
        braced = "{" + placeholder.field + "}"
        if placeholder.kind is PlaceholderKind.REFUSED:
            findings.append((braced, REFUSED, placeholder.reason))
        elif not _is_example(placeholder) and placeholder.kind is not PlaceholderKind.VALUE:
            findings.append((braced, NOT_RENDERED, placeholder.reason))
        elif placeholder.kind is PlaceholderKind.VALUE and examples:
            findings.append(
                (braced, REVIEW, f"Placeholder '{braced}' is not filled. {examples[0].reason}")
            )
    return list(dict.fromkeys(findings))


def _is_example(placeholder: Placeholder) -> bool:
    # Prompt text the author meant literally: a JSON example, or an empty `{}` object.
    if placeholder.kind is PlaceholderKind.POSITIONAL:
        return placeholder.field == ""
    return placeholder.kind in _EXAMPLE_KINDS and not placeholder.variable_like


def _holds_placeholder_like_text(template: str) -> bool:
    return any(
        placeholder.variable_like
        for match in _BRACED_TEXT.finditer(template)
        for placeholder in inspect_template(match.group()).placeholders
    )


def _templates() -> Iterator[tuple[Graph, str, int, str, str, str]]:
    """Yield `(graph, node_type, node_id, node_name, field, template)` for every live template.

    A template without `{` holds no placeholder, so the database skips it.
    """
    live_graphs = Graph.objects.all()

    task_nodes = (
        TaskNode.objects.filter(graph__in=live_graphs, instructions__contains="{")
        .select_related("graph__org")
        .only("node_name", "instructions", "graph__name", "graph__org__name")
        .order_by("graph__org_id", "graph_id", "pk")
    )
    for node in task_nodes.iterator():
        yield node.graph, "TaskNode", node.pk, node.node_name, "instructions", node.instructions

    agent_node_tasks = (
        AgentNodeTask.objects.filter(
            agent_node__in=AgentNode.objects.filter(graph__in=live_graphs),
            instructions__contains="{",
        )
        .select_related("agent_node__graph__org")
        .only(
            "name",
            "instructions",
            "agent_node__node_name",
            "agent_node__graph__name",
            "agent_node__graph__org__name",
        )
        .order_by("agent_node__graph__org_id", "agent_node__graph_id", "agent_node_id", "order")
    )
    for task in agent_node_tasks.iterator():
        node = task.agent_node
        yield (
            node.graph,
            "AgentNode",
            node.pk,
            node.node_name,
            f"tasks[{task.name}].instructions",
            task.instructions,
        )

    knowledge_nodes = (
        KnowledgeNode.objects.filter(graph__in=live_graphs, query__contains="{")
        .select_related("graph__org")
        .only("node_name", "query", "graph__name", "graph__org__name")
        .order_by("graph__org_id", "graph_id", "pk")
    )
    for node in knowledge_nodes.iterator():
        yield node.graph, "KnowledgeNode", node.pk, node.node_name, "query", node.query

    prompts = (
        ClassificationDecisionTablePrompt.objects.filter(
            cdt_node__in=ClassificationDecisionTableNode.objects.filter(graph__in=live_graphs),
            kind=ClassificationDecisionTablePrompt.Kind.LLM,
            prompt_text__contains="{",
        )
        .select_related("cdt_node__graph__org")
        .only(
            "prompt_key",
            "prompt_text",
            "cdt_node__node_name",
            "cdt_node__graph__name",
            "cdt_node__graph__org__name",
        )
        .order_by("cdt_node__graph__org_id", "cdt_node__graph_id", "cdt_node_id", "prompt_key")
    )
    for prompt in prompts.iterator():
        node = prompt.cdt_node
        yield (
            node.graph,
            "ClassificationDecisionTableNode",
            node.pk,
            node.node_name,
            f"prompt_configs[{prompt.prompt_key}].prompt_text",
            prompt.prompt_text,
        )
