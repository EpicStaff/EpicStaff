"""The warnings next to a package's review, on a first install and on an upgrade alike."""

import pytest

from tests.plugins_tests.conftest import mark_running, upload_file
from tests.plugins_tests.package_builder import backend_manifest, build_package, sample_files

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

PACKAGES_URL = "/api/admin/plugins/packages/"
FLOWS_RUN_CODE = {
    "code": "flows_run_code",
    "message": (
        "Through flows, the plugin can run code in EpicStaff's sandbox, which has its own network "
        "access. The plugin's outbound hosts do not apply to that code."
    ),
}
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

    assert FLOWS_RUN_CODE in warnings


def test_creating_flows_without_using_them_also_says_the_flows_still_run(superadmin_client):
    assert _warnings(_review(superadmin_client, _flows("create", "update"))) == [FLOWS_RUN_CODE, FLOWS_USE_MISSING]


def test_using_flows_warns_only_about_the_sandbox(superadmin_client):
    assert _warnings(_review(superadmin_client, _flows("create", "update", "use"))) == [FLOWS_RUN_CODE]


@pytest.mark.parametrize(
    "access",
    [
        _flows(),
        [{"resource_type": "files", "actions": ["read", "create"], "reason": "Stores the readme."}],
        [],
    ],
    ids=["flows_read", "files_only", "no_access"],
)
def test_access_that_runs_no_flow_code_gives_no_flows_warning(superadmin_client, access):
    assert _warnings(_review(superadmin_client, access)) == []


def test_an_upgrade_review_carries_the_warning_too(backend_plugin, superadmin_client):
    mark_running(backend_plugin(access=_flows()))

    review = _review(superadmin_client, _flows("use"), version="0.3.0")

    assert review["is_upgrade"] is True
    assert _warnings(review) == [FLOWS_RUN_CODE]
    again = superadmin_client.get(f"{PACKAGES_URL}{review['id']}/review/").json()
    assert _warnings(again) == [FLOWS_RUN_CODE]
