"""The recycle bin names what a binned item holds only to a user who may read that kind of item.

An agent's surfaces, a surface's tools and sources, a flow's webhook triggers: each is its
own RBAC resource type. A user who can read the bin tab but not that type gets how many
there are (`hidden_contents`, still counted in `contents_total`), never their names, in
the list and in "Show all", and a detail line that would name one says NO_ACCESS.
"""

from unittest.mock import patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework import status

from agents.models import (
    AgentDefinition,
    Surface,
    SurfaceKnowledge,
    SurfaceMcpTool,
    SurfacePythonTool,
    SurfaceStorageItem,
    ToolMode,
)
from rbac.access.effective import EffectivePermissions
from rbac.models.enums import Permission, ResourceType
from tables.models import (
    Graph,
    PythonCode,
    RealtimeAgentDefinition,
    RealtimeChannel,
    SourceCollection,
    StorageFile,
    TwilioChannel,
    WebhookTrigger,
    WebhookTriggerNode,
)
from tables.services.recycle_bin.presentation import NO_ACCESS, DetailContext, DetailField, bin_presentations
from tests.api_tests.recycle_bin_cases import AGENTS_URL, FLOWS_URL, SURFACES_URL, make_mcp_tool, make_python_tool
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.usefixtures("retention_seven_days")

CHANNELS_URL = "/api/realtime-channels/"
WEBHOOK_REGISTER = "tables.signals.webhook_signals.WebhookTriggerService.register_webhooks"
READ = Permission.READ
# Related paths that are the binned item's own data, not another item's name: a voice
# channel's Twilio settings and a webhook trigger's tunnel config are one-to-one parts of it.
OWN_RELATED_PATHS = frozenset({"twilio__phone_number", "twilio__account_sid", "ngrok__domain", "localhost__domain"})


@pytest.fixture
def client_reading(custom_role_user, client_as, acme):
    """Factory: an Acme client whose custom role holds READ on exactly `resource_types`."""

    def _make(*resource_types: ResourceType):
        email = "bin-reads-" + "-".join(resource_type.value for resource_type in resource_types) + "@example.com"
        user = custom_role_user(acme, email, {resource_type: READ for resource_type in resource_types})
        client = client_as(user)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
        return client

    return _make


def _bin(client, url) -> list[dict]:
    response = client.get(f"{url}recycle-bin/")
    assert response.status_code == status.HTTP_200_OK, response.content
    return response.json()["results"]


def _show_all(client, url, pk) -> dict:
    response = client.get(f"{url}{pk}/recycle-bin-contents/")
    assert response.status_code == status.HTTP_200_OK, response.content
    return response.json()


def _details(entry) -> dict:
    return {detail["label"]: detail["value"] for detail in entry["details"]}


def _binned_agent_with_surfaces(org, name="Support agent", llm_config=None) -> AgentDefinition:
    agent = AgentDefinition.objects.create(
        org=org, name=name, instruction_list=[{"name": "Instruction_1.md", "content": "x"}], llm_config=llm_config
    )
    Surface.objects.create(org=org, name=f"{name} surface one", owner_agent=agent)
    Surface.objects.create(org=org, name=f"{name} surface two", owner_agent=agent)
    agent.delete()
    return agent


def _binned_surface_with_tools(org) -> Surface:
    owner = AgentDefinition.objects.create(
        org=org, name="Owner", instruction_list=[{"name": "Instruction_1.md", "content": "x"}]
    )
    surface = Surface.objects.create(org=org, name="Research", owner_agent=owner)
    SurfacePythonTool.objects.create(surface=surface, python_tool=make_python_tool(org, "Search tool"), mode=ToolMode.ALLOW)
    SurfaceMcpTool.objects.create(surface=surface, mcp_tool=make_mcp_tool(org, "Web MCP"), mode=ToolMode.ALLOW)
    SurfaceKnowledge.objects.create(
        surface=surface, collection=SourceCollection.objects.create(org=org, collection_name="Docs")
    )
    SurfaceStorageItem.objects.create(
        surface=surface, storage_file=StorageFile.objects.create(org=org, path="docs/plan.txt", name="plan.txt")
    )
    surface.delete()
    return surface


SURFACE_NAMES = [
    {"name": "Support agent surface one", "kind": "surface"},
    {"name": "Support agent surface two", "kind": "surface"},
]


@pytest.mark.django_db
class TestAgentTab:
    def test_without_surfaces_read_the_surfaces_are_only_counted(self, client_reading, acme):
        _binned_agent_with_surfaces(acme)
        client = client_reading(ResourceType.AGENTS)

        entry = _bin(client, AGENTS_URL)[0]

        assert entry["contents"] == []
        assert entry["hidden_contents"] == [{"kind": "surface", "count": 2}]
        assert entry["contents_total"] == 2
        assert "surface one" not in str(entry)

    def test_with_surfaces_read_the_surfaces_are_named(self, client_reading, acme):
        _binned_agent_with_surfaces(acme)
        client = client_reading(ResourceType.AGENTS, ResourceType.SURFACES)

        entry = _bin(client, AGENTS_URL)[0]

        assert sorted(entry["contents"], key=lambda content: content["name"]) == SURFACE_NAMES
        assert entry["hidden_contents"] == []
        assert entry["contents_total"] == 2

    @pytest.mark.parametrize("client_fixture", ["acme_admin_client", "superadmin_in_acme"])
    def test_org_admins_and_superadmins_see_the_names(self, request, client_fixture, acme):
        _binned_agent_with_surfaces(acme)
        client = request.getfixturevalue(client_fixture)

        entry = _bin(client, AGENTS_URL)[0]

        assert sorted(entry["contents"], key=lambda content: content["name"]) == SURFACE_NAMES
        assert entry["hidden_contents"] == []

    def test_show_all_counts_the_surfaces_without_surfaces_read(self, client_reading, acme):
        agent = _binned_agent_with_surfaces(acme)

        hidden = _show_all(client_reading(ResourceType.AGENTS), AGENTS_URL, agent.pk)
        named = _show_all(client_reading(ResourceType.AGENTS, ResourceType.SURFACES), AGENTS_URL, agent.pk)

        assert hidden == {"contents": [], "hidden_contents": [{"kind": "surface", "count": 2}], "contents_total": 2}
        assert sorted(named["contents"], key=lambda content: content["name"]) == SURFACE_NAMES
        assert (named["hidden_contents"], named["contents_total"]) == ([], 2)

    def test_the_llm_line_is_named_only_with_llm_configs_read(self, client_reading, acme, llm_config):
        _binned_agent_with_surfaces(acme, llm_config=llm_config)

        without = _details(_bin(client_reading(ResourceType.AGENTS), AGENTS_URL)[0])
        with_read = _details(_bin(client_reading(ResourceType.AGENTS, ResourceType.LLM_CONFIGS), AGENTS_URL)[0])

        assert without["LLM"] == NO_ACCESS
        assert with_read["LLM"] == f"MyGPT-4o · {llm_config.model.name}"

    def test_hidden_contents_add_no_queries_per_row(self, client_reading, acme):
        client = client_reading(ResourceType.AGENTS)
        _binned_agent_with_surfaces(acme, name="First")
        with CaptureQueriesContext(connection) as one_agent:
            _bin(client, AGENTS_URL)
        _binned_agent_with_surfaces(acme, name="Second")
        _binned_agent_with_surfaces(acme, name="Third")

        with CaptureQueriesContext(connection) as three_agents:
            entries = _bin(client, AGENTS_URL)

        assert [entry["hidden_contents"] for entry in entries] == [[{"kind": "surface", "count": 2}]] * 3
        assert len(three_agents.captured_queries) == len(one_agent.captured_queries)


@pytest.mark.django_db
class TestSurfaceTab:
    def test_without_tools_read_the_tools_are_only_counted(self, client_reading, acme):
        surface = _binned_surface_with_tools(acme)
        client = client_reading(ResourceType.SURFACES, ResourceType.KNOWLEDGE_SOURCES)

        entry = _bin(client, SURFACES_URL)[0]
        show_all = _show_all(client, SURFACES_URL, surface.pk)

        expected_hidden = [
            {"kind": "python_tool", "count": 1},
            {"kind": "mcp_tool", "count": 1},
            {"kind": "file", "count": 1},
        ]
        for contents in (entry, show_all):
            assert contents["contents"] == [{"name": "Docs", "kind": "knowledge_source"}]
            assert contents["hidden_contents"] == expected_hidden
            assert contents["contents_total"] == 4
        assert "Search tool" not in str(entry) + str(show_all)
        assert "Web MCP" not in str(entry) + str(show_all)

    def test_files_are_named_only_with_files_read(self, client_reading, acme):
        surface = _binned_surface_with_tools(acme)
        without = client_reading(ResourceType.SURFACES, ResourceType.TOOLS, ResourceType.KNOWLEDGE_SOURCES)
        with_read = client_reading(
            ResourceType.SURFACES, ResourceType.TOOLS, ResourceType.KNOWLEDGE_SOURCES, ResourceType.FILES
        )

        hidden_entry = _bin(without, SURFACES_URL)[0]
        named_show_all = _show_all(with_read, SURFACES_URL, surface.pk)

        assert hidden_entry["hidden_contents"] == [{"kind": "file", "count": 1}]
        assert "plan.txt" not in str(hidden_entry)
        assert {"name": "docs/plan.txt", "kind": "file"} in named_show_all["contents"]
        assert named_show_all["hidden_contents"] == []

    def test_without_agents_read_the_owner_agent_is_not_named(self, client_reading, acme):
        _binned_surface_with_tools(acme)

        without = _details(_bin(client_reading(ResourceType.SURFACES), SURFACES_URL)[0])
        with_read = _details(_bin(client_reading(ResourceType.SURFACES, ResourceType.AGENTS), SURFACES_URL)[0])

        assert without["Owner agent"] == NO_ACCESS
        assert with_read["Owner agent"] == "Owner"

    def test_with_every_read_everything_is_named(self, client_reading, acme):
        _binned_surface_with_tools(acme)
        client = client_reading(
            ResourceType.SURFACES, ResourceType.TOOLS, ResourceType.KNOWLEDGE_SOURCES, ResourceType.FILES
        )

        entry = _bin(client, SURFACES_URL)[0]

        assert sorted((content["kind"], content["name"]) for content in entry["contents"]) == [
            ("file", "docs/plan.txt"),
            ("knowledge_source", "Docs"),
            ("mcp_tool", "Web MCP"),
            ("python_tool", "Search tool"),
        ]
        assert entry["hidden_contents"] == []


@pytest.mark.django_db
class TestWebhookTriggerNotices:
    """Flows and voice channels warn that their binned trigger must come back first."""

    @pytest.mark.parametrize(
        "paths, unnamed, named",
        [
            (["hook-path"], "Its webhook trigger is in the recycle bin", 'Its webhook trigger "hook-path" is in'),
            (
                ["hook-path", "other-path"],
                "Its 2 webhook triggers are in the recycle bin",
                'Its webhook triggers "hook-path", "other-path" are in',
            ),
        ],
        ids=["one-trigger", "two-triggers"],
    )
    def test_a_flow_names_its_binned_triggers_only_with_webhooks_read(
        self, client_reading, acme, paths, unnamed, named
    ):
        with patch(WEBHOOK_REGISTER, return_value=True):
            graph = Graph.objects.create(org=acme, name="Hooked flow")
            triggers = [
                WebhookTrigger.objects.create(org=acme, path=path, provider_type="localhost") for path in paths
            ]
            for trigger in triggers:
                WebhookTriggerNode.objects.create(
                    graph=graph,
                    node_name=trigger.path,
                    python_code=PythonCode.objects.create(code="def main(): pass"),
                    webhook_trigger=trigger,
                )
            graph.delete()
            for trigger in triggers:
                trigger.delete()

            without = _details(_bin(client_reading(ResourceType.FLOWS), FLOWS_URL)[0])["Comes back"]
            with_read = _details(_bin(client_reading(ResourceType.FLOWS, ResourceType.WEBHOOKS), FLOWS_URL)[0])[
                "Comes back"
            ]

        assert without.startswith(unnamed)
        assert not any(path in without for path in paths)
        assert with_read.startswith(named)

    def test_a_voice_channel_names_its_trigger_and_agent_only_with_read(self, client_reading, acme):
        agent = AgentDefinition.objects.create(
            org=acme, name="Phone agent", instruction_list=[{"name": "Instruction_1.md", "content": "x"}]
        )
        with patch(WEBHOOK_REGISTER, return_value=True):
            trigger = WebhookTrigger.objects.create(org=acme, path="calls-path", provider_type="ngrok")
            channel = RealtimeChannel.objects.create(
                org=acme,
                name="Line",
                realtime_agent_definition=RealtimeAgentDefinition.objects.create(agent_definition=agent),
            )
            TwilioChannel.objects.create(channel=channel, account_sid="AC1", webhook_trigger=trigger)
            channel.delete()
            trigger.delete()

            without = _details(_bin(client_reading(ResourceType.VOICE), CHANNELS_URL)[0])
            with_read = _details(
                _bin(client_reading(ResourceType.VOICE, ResourceType.WEBHOOKS, ResourceType.AGENTS), CHANNELS_URL)[0]
            )

        assert "until its webhook trigger is restored" in without["Comes back"]
        assert "calls-path" not in without["Comes back"]
        assert without["Agent"] == NO_ACCESS
        assert 'until its webhook trigger "calls-path" is restored' in with_read["Comes back"]
        assert with_read["Agent"] == "Phone agent"


def _viewer(*readable: ResourceType) -> EffectivePermissions:
    return EffectivePermissions(
        is_superadmin=False, role=None, by_resource={resource_type.value: int(READ) for resource_type in readable}
    )


@pytest.mark.parametrize(
    "readable, value, expected",
    [
        ((ResourceType.AGENTS,), "Owner", "Owner"),
        ((), "Owner", NO_ACCESS),
        # Nothing to hide: an empty line stays empty.
        ((), None, None),
        ((), "", None),
    ],
    ids=["readable", "unreadable", "unreadable-null", "unreadable-blank"],
)
def test_a_detail_line_naming_another_resource(readable, value, expected):
    line = DetailField("Owner agent", ("owner_agent__name",), names=ResourceType.AGENTS)

    rendered = line.render({"owner_agent__name": value}, DetailContext(org_id=1, viewer=_viewer(*readable)))

    assert rendered == expected


def test_a_superadmin_reads_every_detail_line():
    line = DetailField("Owner agent", ("owner_agent__name",), names=ResourceType.AGENTS)
    superadmin = EffectivePermissions(is_superadmin=True, role=None)

    assert line.render({"owner_agent__name": "Owner"}, DetailContext(org_id=1, viewer=superadmin)) == "Owner"


def test_every_related_detail_line_says_what_it_names():
    """A text line read across a relation names another item unless it's the item's own data.

    Such a line must say which resource it names (`names`), so the bin hides it from a
    user without READ on that resource; otherwise every bin reader sees the name.
    """
    unguarded = {
        (key, detail_field.label, path)
        for key, presentation in bin_presentations().items()
        for detail_field in presentation.detail_fields
        if detail_field.format == "text" and detail_field.names is None
        for path in detail_field.paths
        if "__" in path and path not in OWN_RELATED_PATHS
    }

    assert unguarded == set()
