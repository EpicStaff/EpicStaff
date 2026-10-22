"""The warnings next to a package's review, on a first install and on an upgrade alike."""

import pytest
from plugins.access.declared_access import NON_DECLARABLE_RESOURCE_TYPES
from plugins.packages.review import ACTIONS_THAT_RUN_CODE
from rbac.access.catalog import RESOURCE_TYPE_METADATA

from tests.plugins_tests.conftest import mark_running, upload_file
from tests.plugins_tests.package_builder import backend_manifest, build_package, sample_files

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

PACKAGES_URL = "/api/admin/plugins/packages/"


def _runs_code(subjects: str) -> dict:
    return {
        "code": "runs_code_in_sandbox",
        "message": (
            f"Through {subjects}, the plugin can have code of its choosing run in EpicStaff's sandbox, "
            "which has its own network access. The plugin's outbound hosts do not apply to that code."
        ),
    }


THROUGH_FLOWS = _runs_code("flows")
THROUGH_TOOLS = _runs_code("tools")
THROUGH_FLOWS_AND_TOOLS = _runs_code("flows and tools")
FLOWS_USE_MISSING = {
    "code": "flows_use_missing",
    "message": (
        "The plugin may create or edit flows but not use them: it cannot run a flow itself or write "
        "schedule, webhook or Telegram trigger nodes. A flow it writes still runs, with its code, "
        "when someone in the organization runs it."
    ),
}


def _flows(*actions: str) -> list[dict]:
    return [{"resource_type": "flows", "actions": ["read", *actions], "reason": "Runs the forecast flow."}]


def _tools(*actions: str) -> list[dict]:
    return [{"resource_type": "tools", "actions": ["read", *actions], "reason": "Adds the forecast tool."}]


def _review(client, access: list[dict], **changes) -> dict:
    manifest = backend_manifest(access=access, **changes)
    data = build_package(sample_files(manifest), manifest=manifest)
    response = client.post(PACKAGES_URL, {"file": upload_file(data)}, format="multipart")
    assert response.status_code == 201, response.content
    return response.json()


def _warnings(review: dict) -> list[dict]:
    return [warning for warning in review["warnings"] if warning["code"] != "untrusted_package"]


@pytest.mark.parametrize("action", ["create", "update", "use"])
def test_every_flows_action_that_runs_code_warns_that_outbound_hosts_do_not_bound_it(superadmin_client, action):
    warnings = _warnings(_review(superadmin_client, _flows(action)))

    assert THROUGH_FLOWS in warnings


@pytest.mark.parametrize("action", ["create", "update"])
def test_writing_tools_alone_warns_that_their_code_runs_in_the_sandbox(superadmin_client, action):
    assert _warnings(_review(superadmin_client, _tools(action))) == [THROUGH_TOOLS]


def test_flows_and_tools_together_give_one_warning_naming_both(superadmin_client):
    access = [*_flows("create", "update", "use"), *_tools("create", "update")]

    assert _warnings(_review(superadmin_client, access)) == [THROUGH_FLOWS_AND_TOOLS]


def test_creating_flows_without_using_them_also_says_the_flows_still_run(superadmin_client):
    assert _warnings(_review(superadmin_client, _flows("create", "update"))) == [THROUGH_FLOWS, FLOWS_USE_MISSING]


def test_using_flows_warns_only_about_the_sandbox(superadmin_client):
    assert _warnings(_review(superadmin_client, _flows("create", "update", "use"))) == [THROUGH_FLOWS]


@pytest.mark.parametrize(
    "access",
    [
        _flows(),
        _tools("delete", "export"),
        [{"resource_type": "files", "actions": ["read", "create"], "reason": "Stores the readme."}],
        [],
    ],
    ids=["flows_read", "tools_without_writes", "files_only", "no_access"],
)
def test_access_that_runs_no_code_gives_no_sandbox_warning(superadmin_client, access):
    assert _warnings(_review(superadmin_client, access)) == []


def test_every_resource_that_runs_code_is_one_a_plugin_may_declare_with_those_actions():
    applicable = {entry["code"]: set(entry["applicable_actions"]) for entry in RESOURCE_TYPE_METADATA}

    assert {
        resource_type: actions - applicable[resource_type]
        for resource_type, actions in ACTIONS_THAT_RUN_CODE.items()
        if resource_type in NON_DECLARABLE_RESOURCE_TYPES or actions - applicable[resource_type]
    } == {}


@pytest.mark.parametrize(
    ("previous", "access", "expected"),
    [
        (_flows(), _flows("use"), [THROUGH_FLOWS]),
        (_tools(), _tools("create"), [THROUGH_TOOLS]),
        (_flows(), [*_flows("create", "update", "use"), *_tools("update")], [THROUGH_FLOWS_AND_TOOLS]),
    ],
    ids=["flows", "tools", "flows_and_tools"],
)
def test_an_upgrade_review_carries_the_warning_too(backend_plugin, superadmin_client, previous, access, expected):
    mark_running(backend_plugin(access=previous))

    review = _review(superadmin_client, access, version="0.3.0")

    assert review["is_upgrade"] is True
    assert _warnings(review) == expected
    again = superadmin_client.get(f"{PACKAGES_URL}{review['id']}/review/").json()
    assert _warnings(again) == expected
