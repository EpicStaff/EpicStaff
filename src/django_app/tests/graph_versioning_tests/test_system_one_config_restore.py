"""Version preview and restore of a Classification Decision Table's System One prompt entries.

A System One entry links an organization-owned ``SystemOneConfig`` by id. The version keeps
that id; preview, restore and "create a flow from a version" must keep it while the config
still exists in the flow's organization, and clear it with a warning once the config is
deleted or belongs to another organization: another organization's config is never linked.
"""

import pytest

from tables.models import SystemOneConfig
from tables.models.graph_models import (
    ClassificationDecisionTableNode,
    ClassificationDecisionTablePrompt,
)
from tests.fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

QUESTIONS = {"is_engineering": {"type": "noul", "instructions": "Engineering?"}}
PROMPT_KEY = "jev_check"
CLEARED_WARNING_TYPE = "system_one_config_ref_cleared"


def _system_one_config(org, name="jev"):
    return SystemOneConfig.objects.create(
        org=org, custom_name=name, provider="typesafe", model_name="jev-1.14.0"
    )


def _cdt_with_system_one_prompt(graph, config):
    node = ClassificationDecisionTableNode.objects.create(graph=graph, node_name="cdt")
    ClassificationDecisionTablePrompt.objects.create(
        cdt_node=node,
        prompt_key=PROMPT_KEY,
        kind="system_one",
        system_one_config=config,
        questions=QUESTIONS,
        result_variable=PROMPT_KEY,
    )
    return node


def _version_whose_config_is_gone(service, graph, default_org, beta, reason):
    """Save a version of a CDT whose System One config is then deleted, or always was foreign.

    Returns the version, the snapshot node id and the id the version still names.
    """
    if reason == "deleted":
        config = _system_one_config(default_org)
    else:
        # The database does not check the organization of the link, so a foreign config
        # can only be set up here; the API refuses it.
        config = _system_one_config(beta)
    node = _cdt_with_system_one_prompt(graph, config)
    version = service.save_version(graph, name="with-system-one")
    config_id = config.id
    if reason == "deleted":
        config.delete()
    return version, node.id, config_id


def _snapshot_prompt(snapshot):
    [cdt_node] = [
        node
        for node in snapshot["nodes"]
        if node["node_type"] == "ClassificationDecisionTableNode"
    ]
    [prompt] = cdt_node["prompt_configs"]
    return prompt


def _restored_prompt(graph):
    return ClassificationDecisionTablePrompt.objects.get(
        cdt_node__graph=graph, prompt_key=PROMPT_KEY
    )


def _cleared_warnings(warnings):
    return [warning for warning in warnings if warning["type"] == CLEARED_WARNING_TYPE]


@pytest.mark.django_db
def test_preview_keeps_a_config_of_the_flows_org(service, graph, default_org):
    config = _system_one_config(default_org)
    _cdt_with_system_one_prompt(graph, config)
    version = service.save_version(graph, name="with-system-one")

    preview = service.preview_version(version)

    assert _snapshot_prompt(preview["snapshot"])["system_one_config"] == config.id
    assert _cleared_warnings(preview["warnings"]) == []


@pytest.mark.django_db
def test_restore_keeps_a_config_of_the_flows_org(service, graph, default_org):
    config = _system_one_config(default_org)
    _cdt_with_system_one_prompt(graph, config)
    version = service.save_version(graph, name="with-system-one")

    result = service.restore_version(
        version, backup=False, expected_save_version=graph.save_version
    )

    assert _restored_prompt(graph).system_one_config_id == config.id
    assert _cleared_warnings(result["warnings"]) == []


@pytest.mark.django_db
def test_new_flow_from_version_keeps_a_config_of_the_flows_org(service, graph, default_org):
    config = _system_one_config(default_org)
    _cdt_with_system_one_prompt(graph, config)
    version = service.save_version(graph, name="with-system-one")

    result = service.create_graph_from_version(version)

    new_prompt = ClassificationDecisionTablePrompt.objects.get(
        cdt_node__graph_id=result["graph_id"], prompt_key=PROMPT_KEY
    )
    assert new_prompt.system_one_config_id == config.id
    assert _cleared_warnings(result["warnings"]) == []


@pytest.mark.django_db
@pytest.mark.parametrize("reason", ["deleted", "foreign_org"])
def test_preview_clears_a_config_the_flows_org_cannot_see(
    service, graph, default_org, beta, reason
):
    version, node_id, config_id = _version_whose_config_is_gone(
        service, graph, default_org, beta, reason
    )

    preview = service.preview_version(version)

    prompt = _snapshot_prompt(preview["snapshot"])
    assert prompt["system_one_config"] is None
    assert prompt["kind"] == "system_one"
    [warning] = _cleared_warnings(preview["warnings"])
    assert warning["node_name"] == "cdt"
    assert warning["node_id"] == node_id
    assert warning["prompt_key"] == PROMPT_KEY
    assert warning["missing_id"] == config_id


@pytest.mark.django_db
@pytest.mark.parametrize("reason", ["deleted", "foreign_org"])
def test_restore_clears_a_config_the_flows_org_cannot_see(
    service, graph, default_org, beta, reason
):
    version, _, config_id = _version_whose_config_is_gone(
        service, graph, default_org, beta, reason
    )

    result = service.restore_version(
        version, backup=False, expected_save_version=graph.save_version
    )

    prompt = _restored_prompt(graph)
    assert prompt.system_one_config_id is None
    assert prompt.kind == "system_one"
    assert prompt.questions == QUESTIONS
    restored_node_id = prompt.cdt_node_id
    [warning] = _cleared_warnings(result["warnings"])
    assert warning["node_id"] == restored_node_id
    assert warning["prompt_key"] == PROMPT_KEY
    assert warning["missing_id"] == config_id


@pytest.mark.django_db
def test_new_flow_from_version_never_links_a_foreign_config(service, graph, default_org, beta):
    version, _, config_id = _version_whose_config_is_gone(
        service, graph, default_org, beta, "foreign_org"
    )

    result = service.create_graph_from_version(version)

    new_prompt = ClassificationDecisionTablePrompt.objects.get(
        cdt_node__graph_id=result["graph_id"], prompt_key=PROMPT_KEY
    )
    assert new_prompt.system_one_config_id is None
    [warning] = _cleared_warnings(result["warnings"])
    assert warning["missing_id"] == config_id
