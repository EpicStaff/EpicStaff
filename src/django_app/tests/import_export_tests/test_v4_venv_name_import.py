"""Importing a v4 flow whose node name the sandbox's venv pattern would reject.

Goes through the real import endpoint, not `ImportService` directly, since only the
endpoint path runs the v4->v5 converter.
"""

import pytest
from django.urls import reverse
from foundation.transport.http import ClientValidationError

from tables.import_export.enums import EntityType, NodeType
from tables.models import PythonNode
from tests.helpers import data_to_json_file
from tests.import_export_tests.venv_fakes import VENV_NAME_PATTERN, FakeSandbox


def _v4_flow_file(node_name: str):
    """A v4 export of one flow whose single Python node declares a library."""
    return data_to_json_file(
        data={
            "main_entity": EntityType.GRAPH,
            "version": 4,
            EntityType.GRAPH: [
                {
                    "id": 40,
                    "name": "scraping flow",
                    "description": "",
                    "metadata": {"nodes": [], "edges": []},
                    "nodes": [
                        {
                            "id": 41,
                            "node_type": NodeType.PYTHON_NODE,
                            "node_name": node_name,
                            "node_number": 1,
                            "python_code": {
                                "code": "def main(**kwargs):\n    return 1\n",
                                "entrypoint": "main",
                                "libraries": "httpx>=0.28",
                                "global_kwargs": {},
                            },
                            "input_map": {},
                            "metadata": {},
                        }
                    ],
                    "edge_list": [],
                }
            ],
        },
        filename="legacy_flow.json",
    )


@pytest.mark.django_db
class TestImportingAV4FlowWhoseNodeNameTheSandboxWouldRefuse:
    @pytest.mark.parametrize(
        "node_name",
        [
            pytest.param("Scraper (v2)", id="brackets"),
            pytest.param("scrape.py", id="dot"),
            pytest.param("Парсер", id="nothing-usable-left"),
        ],
    )
    def test_the_flow_imports(self, auth_client, default_org, sandbox, node_name):
        response = auth_client.post(
            reverse("graphs-import-entity"),
            {"file": _v4_flow_file(node_name)},
            format="multipart",
        )

        assert response.status_code == 200, response.data
        node = PythonNode.objects.get(node_name=node_name)
        binding = node.python_code.venv
        assert binding is not None
        assert binding.org_id == default_org.id

    def test_the_environment_it_creates_is_named_after_the_node(
        self, auth_client, default_org, sandbox
    ):
        """The reduced name still has to read as the node's."""
        response = auth_client.post(
            reverse("graphs-import-entity"),
            {"file": _v4_flow_file("Scraper (v2)")},
            format="multipart",
        )

        assert response.status_code == 200, response.data
        node = PythonNode.objects.get(node_name="Scraper (v2)")
        created = sandbox.venvs[int(node.python_code.venv.resource_id)]
        assert VENV_NAME_PATTERN.fullmatch(created["name"]), created["name"]
        assert created["name"].startswith("Scraper ")
        assert created["libs"] == [{"name": "httpx", "specification": ">=0.28"}]

    def test_the_node_keeps_the_name_it_had(self, auth_client, default_org, sandbox):
        """Only the environment is renamed, not the node."""
        auth_client.post(
            reverse("graphs-import-entity"),
            {"file": _v4_flow_file("Scraper (v2)")},
            format="multipart",
        )

        assert PythonNode.objects.filter(node_name="Scraper (v2)").exists()


class TestTheFakeSandboxRefusesWhatTheRealOneRefuses:
    @pytest.mark.parametrize(
        "name",
        [
            pytest.param("Scraper (v2)", id="brackets"),
            pytest.param("scrape.py", id="dot"),
            pytest.param("Парсер", id="non-latin"),
            pytest.param("", id="empty"),
            pytest.param("scraper\n", id="trailing-newline"),
        ],
    )
    def test_a_name_outside_the_pattern_is_refused(self, name):
        with pytest.raises(ClientValidationError):
            FakeSandbox().create({"name": name, "libs": []})

    def test_a_name_the_pattern_allows_is_created(self):
        venv = FakeSandbox().create({"name": "Scraper _v2-venv", "libs": []})

        assert venv["name"] == "Scraper _v2-venv"
