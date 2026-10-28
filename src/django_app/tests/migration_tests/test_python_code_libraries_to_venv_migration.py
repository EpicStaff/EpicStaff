"""tables 0257 moves what PythonCode.libraries declared into a venv per organization.

Invariants the upgrade rests on: a library string becomes the package names pip would
install, with versions dropped because the environment is shared by the whole
organization; each organization gets one set of names and the list of code that moves
to it; the organization of a PythonCode is read off whatever owns it, binned owners
included -- they can be restored and would need the same libraries; and a sandbox that
does not answer stops the migration with the field still in place, having removed the
environments it had already created.
"""

from importlib import import_module
from unittest.mock import patch

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

migration = import_module("tables.migrations.0257_remove_pythoncode_libraries_pythoncode_venv_id")

BEFORE = [("tables", "0256_merge_0251_merge_20260928_1131_0255_key_value_tables")]
AFTER = [("tables", "0257_remove_pythoncode_libraries_pythoncode_venv_id")]
SANDBOX_CLIENT = "proxies.sandbox.services.VenvService.client_class"


class FakeSandbox:
    """The sandbox service, as far as the migration can see it.

    Hands out ids of its own, keeps what it was told to build, and records every
    removal so the rollback can be checked. `fail_after` makes it stop answering once
    it has built that many environments, which is how an unreachable sandbox looks
    from here.
    """

    def __init__(self, fail_after: int | None = None):
        self.venvs: dict[int, dict] = {}
        self.removed: list[str] = []
        self.fail_after = fail_after
        self._next_id = 7000

    def __call__(self, *args, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def create(self, data: dict) -> dict:
        if self.fail_after is not None and len(self.venvs) >= self.fail_after:
            raise RuntimeError("the sandbox is not answering")
        self._next_id += 1
        venv = {"id": self._next_id, "status": "declared", **data}
        self.venvs[self._next_id] = venv
        return venv

    def remove(self, venv_id: str) -> None:
        self.removed.append(str(venv_id))


def _migrate(targets):
    MigrationExecutor(connection).migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


def _migrate_to_leaf():
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def _column_names() -> set[str]:
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, "tables_pythoncode")
    return {column.name for column in description}


@pytest.fixture
def historical_apps():
    """Models as the migration sees them: plain managers, so binned rows are included.

    The current state, not 0257's: every field this reads still exists, and building
    the state does not touch the database.
    """
    loader = MigrationExecutor(connection).loader
    return loader.project_state(loader.graph.leaf_nodes()).apps


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", []),
        ("requests", ["requests"]),
        # The venv is shared, so a pin cannot be honoured for everyone; the name moves alone.
        ("requests==2.31.0", ["requests"]),
        ("requests>=2,<3", ["requests"]),
        ("requests[socks]", ["requests"]),
        ("Pydantic", ["pydantic"]),
        ("ruamel.yaml", ["ruamel-yaml"]),
        ("requests numpy", ["requests", "numpy"]),
        # A legacy row cannot be edited to fix it, so the unreadable entry goes and the rest stays.
        ("requests ../evil numpy", ["requests", "numpy"]),
        ("!!!", []),
    ],
)
def test_a_library_string_becomes_the_package_names_pip_would_install(raw, expected):
    assert migration._library_names(raw, code_id=1) == expected


def test_one_organization_gets_one_set_of_names_and_every_code_that_declared_them():
    names_by_org, code_ids_by_org = migration._group_by_org(
        [(1, "requests"), (2, "Requests pandas")], {1: 10, 2: 10}
    )

    assert names_by_org == {10: {"requests", "pandas"}}
    assert code_ids_by_org == {10: [1, 2]}


def test_organizations_do_not_share_an_environment():
    names_by_org, code_ids_by_org = migration._group_by_org(
        [(1, "requests"), (2, "pandas")], {1: 10, 2: 20}
    )

    assert names_by_org == {10: {"requests"}, 20: {"pandas"}}
    assert code_ids_by_org == {10: [1], 20: [2]}


def test_code_outside_any_organization_is_left_behind():
    names_by_org, code_ids_by_org = migration._group_by_org([(1, "requests")], {})

    assert names_by_org == {}
    assert code_ids_by_org == {}


def test_code_whose_libraries_are_all_unreadable_moves_nowhere():
    names_by_org, code_ids_by_org = migration._group_by_org([(1, "!!!")], {1: 10})

    assert names_by_org == {}
    assert code_ids_by_org == {}


@pytest.mark.django_db
def test_every_kind_of_owner_tells_its_code_which_organization_it_is_in(historical_apps):
    organization = historical_apps.get_model("rbac", "Organization")
    graph_model = historical_apps.get_model("tables", "Graph")
    python_code = historical_apps.get_model("tables", "PythonCode")

    tool_org = organization.objects.create(name="Org venv owners tool")
    flow_org = organization.objects.create(name="Org venv owners flow")
    graph = graph_model.objects.create(name="Owners flow", org=flow_org)

    def code():
        return python_code.objects.create(code="def main(): return 1", entrypoint="main")

    tool_code, binned_tool_code = code(), code()
    node_code, webhook_code = code(), code()
    pre_code, post_code = code(), code()
    orphan_code = code()

    tool = historical_apps.get_model("tables", "PythonCodeTool")
    tool.objects.create(org=tool_org, python_code=tool_code, name="live", description="")
    # Binned, not gone: restoring it brings back code that needs the same libraries.
    tool.objects.create(
        org=tool_org,
        python_code=binned_tool_code,
        name="binned",
        description="",
        active=False,
        soft_deleted_at=timezone.now(),
    )
    historical_apps.get_model("tables", "PythonNode").objects.create(
        graph=graph, python_code=node_code, node_name="node"
    )
    historical_apps.get_model("tables", "WebhookTriggerNode").objects.create(
        graph=graph, python_code=webhook_code, node_name="webhook"
    )
    historical_apps.get_model("tables", "ClassificationDecisionTableNode").objects.create(
        graph=graph, node_name="table", pre_python_code=pre_code, post_python_code=post_code
    )

    org_id_by_code_id = migration._org_id_by_code_id(historical_apps)

    assert org_id_by_code_id[tool_code.pk] == tool_org.pk
    assert org_id_by_code_id[binned_tool_code.pk] == tool_org.pk
    assert org_id_by_code_id[node_code.pk] == flow_org.pk
    assert org_id_by_code_id[webhook_code.pk] == flow_org.pk
    assert org_id_by_code_id[pre_code.pk] == flow_org.pk
    assert org_id_by_code_id[post_code.pk] == flow_org.pk
    assert orphan_code.pk not in org_id_by_code_id


def _declaring_code(old_apps, libraries: str):
    return old_apps.get_model("tables", "PythonCode").objects.create(
        code="def main(): return 1", entrypoint="main", libraries=libraries
    )


def _two_organizations_with_declared_libraries(old_apps):
    """One organization declaring through a tool, one through a flow node.

    Returns the organizations and every code the assertions need, by primary key:
    the ids survive the migration, the model objects do not.
    """
    organization = old_apps.get_model("rbac", "Organization")
    tool_org = organization.objects.create(name="Org venv move tool")
    flow_org = organization.objects.create(name="Org venv move flow")

    tool_code = _declaring_code(old_apps, "requests==2.31.0 Pandas")
    quiet_code = _declaring_code(old_apps, "")
    node_code = _declaring_code(old_apps, "requests")
    orphan_code = _declaring_code(old_apps, "numpy")

    tool = old_apps.get_model("tables", "PythonCodeTool")
    tool.objects.create(org=tool_org, python_code=tool_code, name="mover", description="")
    tool.objects.create(org=tool_org, python_code=quiet_code, name="quiet", description="")
    graph = old_apps.get_model("tables", "Graph").objects.create(name="Mover flow", org=flow_org)
    old_apps.get_model("tables", "PythonNode").objects.create(
        graph=graph, python_code=node_code, node_name="mover"
    )

    return {
        "tool_org": tool_org.pk,
        "flow_org": flow_org.pk,
        "tool_code": tool_code.pk,
        "quiet_code": quiet_code.pk,
        "node_code": node_code.pk,
        "orphan_code": orphan_code.pk,
    }


@pytest.mark.django_db(transaction=True)
def test_each_organization_gets_one_environment_and_its_code_points_at_it():
    sandbox = FakeSandbox()
    with patch(SANDBOX_CLIENT, sandbox):
        try:
            rows = _two_organizations_with_declared_libraries(_migrate(BEFORE))

            new_apps = _migrate(AFTER)
            python_code = new_apps.get_model("tables", "PythonCode")
            bindings = new_apps.get_model("proxies", "SandboxVenvBinding")

            def environment_of(code_pk):
                binding = bindings.objects.get(pk=python_code.objects.get(pk=code_pk).venv_id)
                return binding, sandbox.venvs[int(binding.resource_id)]

            tool_binding, tool_venv = environment_of(rows["tool_code"])
            node_binding, node_venv = environment_of(rows["node_code"])

            assert len(sandbox.venvs) == 2
            assert tool_binding.org_id == rows["tool_org"]
            assert node_binding.org_id == rows["flow_org"]
            assert tool_venv["name"] == migration.MIGRATED_VENV_NAME
            # Canonicalized, deduplicated across the organization, and unpinned: one
            # environment cannot hold two versions of the same package.
            assert tool_venv["libs"] == [
                {"name": "pandas", "specification": ""},
                {"name": "requests", "specification": ""},
            ]
            assert node_venv["libs"] == [{"name": "requests", "specification": ""}]

            # Nothing to install, and nobody to install it for: both stay on the default.
            assert python_code.objects.get(pk=rows["quiet_code"]).venv_id is None
            assert python_code.objects.get(pk=rows["orphan_code"]).venv_id is None
        finally:
            _migrate_to_leaf()


@pytest.mark.django_db(transaction=True)
def test_a_sandbox_that_stops_answering_leaves_the_field_and_removes_what_it_built():
    sandbox = FakeSandbox(fail_after=1)
    with patch(SANDBOX_CLIENT, sandbox):
        try:
            _two_organizations_with_declared_libraries(_migrate(BEFORE))

            with pytest.raises(RuntimeError):
                _migrate(AFTER)

            assert len(sandbox.venvs) == 1
            built_id = next(iter(sandbox.venvs))
            assert sandbox.removed == [str(built_id)]
            # The column is still there, so the upgrade can be retried with the data.
            assert "libraries" in _column_names()
        finally:
            sandbox.fail_after = None
            _migrate_to_leaf()
