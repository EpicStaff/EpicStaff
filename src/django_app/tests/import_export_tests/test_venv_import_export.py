"""Virtual environments crossing an export/import boundary.

The environment itself lives in the sandbox service and only its binding lives
here, so this is the one entity whose import writes outside the transaction. The
sandbox is the external boundary and the only thing replaced: `FakeSandbox` stands
in for it and records what it was asked to create and remove.

Two numbers are deliberately kept apart throughout: a binding's pk, which is what
the file and the rest of django use, and the id the sandbox knows the environment
under. Confusing them would run code in the wrong environment, so no test lets
them coincide.
"""

from unittest.mock import patch

import pytest
from proxies.sandbox.models import SandboxVenvBinding
from rbac.models import Organization
from rest_framework.exceptions import PermissionDenied

from rbac.models.enums import Permission, ResourceType

from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.import_export.schemas import ImportSettings
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.import_service import ImportService
from tables.models import PythonCode, PythonCodeTool

STRATEGY_CLIENT = "tables.import_export.strategies.venv.SandboxVenvClient"
IMPORT_CLIENT = "tables.import_export.services.import_service.SandboxVenvClient"


class FakeSandbox:
    """The sandbox service, as far as import/export can see it.

    Holds the environments it was told about, hands out ids of its own, and records
    every removal so a rollback can be checked.
    """

    def __init__(self, venvs: dict | None = None):
        self.venvs = dict(venvs or {})
        self.removed: list[str] = []
        self._next_id = 9000

    def __call__(self, *args, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def create(self, data: dict) -> dict:
        self._next_id += 1
        venv = {
            "id": self._next_id,
            "name": data["name"],
            "libs": data["libs"],
            "status": "declared",
        }
        self.venvs[self._next_id] = venv
        return venv

    def retrieve(self, venv_id: str) -> dict:
        return self.venvs[int(venv_id)]

    def list(self, ids, limit=None, offset=None) -> dict:
        wanted = {int(venv_id) for venv_id in ids}
        return {"result": [v for key, v in self.venvs.items() if key in wanted]}

    def remove(self, venv_id: str) -> None:
        self.removed.append(venv_id)


@pytest.fixture
def sandbox():
    fake = FakeSandbox()
    with patch(STRATEGY_CLIENT, fake), patch(IMPORT_CLIENT, fake):
        yield fake


@pytest.fixture
def target_org(db):
    return Organization.objects.create(name="Org venv import target")


def upstream_venv(sandbox, org, *, name="scraper-venv", libs=None, status="completed", venv_id):
    """An environment the sandbox already has, bound to `org`."""
    sandbox.venvs[venv_id] = {
        "id": venv_id,
        "name": name,
        "libs": libs if libs is not None else [{"name": "httpx", "specification": ">=0.28"}],
        "status": status,
    }
    return SandboxVenvBinding.objects.create(org_id=org.id, resource_id=str(venv_id))


def tool_in(org, binding, *, name="Fetch orders", code="def main(): return 1"):
    python_code = PythonCode.objects.create(code=code, entrypoint="main", venv=binding)
    return PythonCodeTool.objects.create(
        org=org, name=name, description="d", python_code=python_code
    )


def export_tool(tool, org):
    return ExportService(entity_registry).export_entities(
        EntityType.PYTHON_CODE_TOOL, [tool.id], org_id=org.id
    )


def import_into(export_data, org, user=None, effective_permissions=None):
    return ImportService(entity_registry).import_data(
        export_data,
        main_entity=EntityType.PYTHON_CODE_TOOL,
        settings=ImportSettings(),
        org_id=org.id,
        user=user,
        effective_permissions=effective_permissions,
    )


class PermissionsWithout:
    """Grants everything except the named resources."""

    def __init__(self, *denied: ResourceType):
        self._denied = set(denied)

    def can(self, resource: ResourceType, permission: Permission) -> bool:
        return resource not in self._denied


@pytest.mark.django_db
class TestExport:
    def test_the_environment_the_code_runs_in_travels_with_it(self, default_org, sandbox):
        binding = upstream_venv(sandbox, default_org, venv_id=4711)

        export_data = export_tool(tool_in(default_org, binding), default_org)

        [venv] = export_data[EntityType.VENV]
        assert venv["name"] == "scraper-venv"
        assert venv["libs"] == [{"name": "httpx", "specification": ">=0.28"}]
        # Addressed by the binding, so the importing system can remap it like any id.
        assert venv["id"] == binding.pk

    def test_code_on_the_default_environment_carries_none(self, default_org, sandbox):
        python_code = PythonCode.objects.create(code="x", entrypoint="main")
        tool = PythonCodeTool.objects.create(
            org=default_org, name="Plain", description="d", python_code=python_code
        )

        export_data = export_tool(tool, default_org)

        assert export_data.get(EntityType.VENV, []) == []

    def test_an_authors_pin_survives_as_a_specifier(self, default_org, sandbox):
        """`version` carries the author's pin and the build's result in one field, so
        it is not exported; a pin with no specification of its own would be lost."""
        binding = upstream_venv(
            sandbox,
            default_org,
            libs=[{"name": "httpx", "specification": "", "version": "0.28.1"}],
            venv_id=4711,
        )

        export_data = export_tool(tool_in(default_org, binding), default_org)

        assert export_data[EntityType.VENV][0]["libs"] == [
            {"name": "httpx", "specification": "==0.28.1"}
        ]

    def test_a_resolved_version_is_not_exported(self, default_org, sandbox):
        binding = upstream_venv(
            sandbox,
            default_org,
            libs=[{"name": "httpx", "specification": ">=0.28", "version": "0.28.1"}],
            venv_id=4711,
        )

        export_data = export_tool(tool_in(default_org, binding), default_org)

        assert export_data[EntityType.VENV][0]["libs"] == [
            {"name": "httpx", "specification": ">=0.28"}
        ]

    def test_a_built_in_tools_environment_of_another_org_stays_out(
        self, default_org, target_org, sandbox
    ):
        """A built-in tool is one row shared by every org, so the environment on it
        can be another tenant's. Its name and libraries must not reach this file."""
        foreign = upstream_venv(sandbox, target_org, name="their-venv", venv_id=4712)
        built_in = tool_in(default_org, foreign, name="Shared")
        PythonCodeTool.objects.filter(pk=built_in.pk).update(built_in=True)

        export_data = export_tool(built_in, default_org)

        assert export_data.get(EntityType.VENV, []) == []


@pytest.mark.django_db
class TestImport:
    def test_the_environment_is_created_and_bound_to_the_importing_org(
        self, default_org, target_org, sandbox, regular_user
    ):
        binding = upstream_venv(sandbox, default_org, venv_id=4711)
        export_data = export_tool(tool_in(default_org, binding), default_org)

        id_mapper, _ = import_into(export_data, target_org, user=regular_user)

        [new_binding_id] = id_mapper.get_created_ids(EntityType.VENV)
        new_binding = SandboxVenvBinding.objects.get(pk=new_binding_id)
        assert new_binding.org_id == target_org.id
        assert new_binding.created_by_id == regular_user.id
        # A fresh environment upstream, under an id of the sandbox's choosing.
        assert sandbox.venvs[int(new_binding.resource_id)]["name"] == "scraper-venv"
        assert new_binding.resource_id != str(binding.pk)

    def test_the_imported_code_points_at_the_new_binding(
        self, default_org, target_org, sandbox, regular_user
    ):
        binding = upstream_venv(sandbox, default_org, venv_id=4711)
        export_data = export_tool(tool_in(default_org, binding), default_org)

        id_mapper, _ = import_into(export_data, target_org, user=regular_user)

        [new_binding_id] = id_mapper.get_created_ids(EntityType.VENV)
        imported = PythonCodeTool.objects.get(org=target_org)
        assert imported.python_code.venv_id == new_binding_id

    def test_an_identical_environment_of_the_org_is_reused(
        self, default_org, target_org, sandbox, regular_user
    ):
        source = upstream_venv(sandbox, default_org, venv_id=4711)
        export_data = export_tool(tool_in(default_org, source), default_org)
        upstream_venv(sandbox, target_org, venv_id=4712)

        id_mapper, _ = import_into(export_data, target_org, user=regular_user)

        assert id_mapper.get_created_ids(EntityType.VENV) == []
        assert SandboxVenvBinding.objects.filter(org_id=target_org.id).count() == 1

    @pytest.mark.parametrize(
        ("name", "libs"),
        [
            pytest.param("other-name", None, id="another-name"),
            pytest.param(None, [{"name": "httpx", "specification": ">=0.29"}], id="another-spec"),
            pytest.param(None, [], id="no-libraries"),
        ],
    )
    def test_an_environment_that_differs_is_not_reused(
        self, default_org, target_org, sandbox, regular_user, name, libs
    ):
        source = upstream_venv(sandbox, default_org, venv_id=4711)
        export_data = export_tool(tool_in(default_org, source), default_org)
        upstream_venv(
            sandbox,
            target_org,
            name=name or "scraper-venv",
            libs=libs,
            venv_id=4712,
        )

        id_mapper, _ = import_into(export_data, target_org, user=regular_user)

        assert len(id_mapper.get_created_ids(EntityType.VENV)) == 1

    def test_an_environment_whose_build_failed_is_not_reused(
        self, default_org, target_org, sandbox, regular_user
    ):
        """Handing the flow a known-broken environment is worse than building one."""
        source = upstream_venv(sandbox, default_org, venv_id=4711)
        export_data = export_tool(tool_in(default_org, source), default_org)
        upstream_venv(sandbox, target_org, status="failed", venv_id=4712)

        id_mapper, _ = import_into(export_data, target_org, user=regular_user)

        assert len(id_mapper.get_created_ids(EntityType.VENV)) == 1


@pytest.mark.django_db
class TestFileCannotReachAnotherOrgsEnvironment:
    def test_code_naming_an_environment_the_file_does_not_carry_is_refused(
        self, default_org, target_org, sandbox, regular_user
    ):
        """`venv` in the file is the exporting system's binding pk and is remapped.

        A hand-edited file could otherwise name a binding of any org: the column is
        a real foreign key, so the database would take it and the code would run in
        another tenant's environment.
        """
        foreign = upstream_venv(sandbox, target_org, name="their-venv", venv_id=4712)
        source = upstream_venv(sandbox, default_org, venv_id=4711)
        export_data = export_tool(tool_in(default_org, source), default_org)
        export_data.pop(EntityType.VENV)
        export_data[EntityType.PYTHON_CODE_TOOL][0]["python_code"]["venv"] = foreign.pk

        with pytest.raises(ValueError):
            import_into(export_data, target_org, user=regular_user)

        assert not PythonCodeTool.objects.filter(org=target_org).exists()


@pytest.mark.django_db
class TestRollback:
    def test_a_failed_import_removes_the_environment_it_created(
        self, default_org, target_org, sandbox, regular_user
    ):
        """The rollback takes the binding with it. Left alone, the sandbox would keep
        an environment no org can see, use, or delete through the API."""
        source = upstream_venv(sandbox, default_org, venv_id=4711)
        export_data = export_tool(tool_in(default_org, source), default_org)

        # Denied on the tool, not on the venv: the refusal has to land after the
        # environment was already created upstream, or there is nothing to undo.
        with pytest.raises(PermissionDenied):
            import_into(
                export_data,
                target_org,
                user=regular_user,
                effective_permissions=PermissionsWithout(ResourceType.TOOLS),
            )

        [created_id] = sandbox.removed
        assert sandbox.venvs[int(created_id)]["name"] == "scraper-venv"
        assert not SandboxVenvBinding.objects.filter(org_id=target_org.id).exists()

    def test_a_reused_environment_is_never_removed(
        self, default_org, target_org, sandbox, regular_user
    ):
        source = upstream_venv(sandbox, default_org, venv_id=4711)
        export_data = export_tool(tool_in(default_org, source), default_org)
        upstream_venv(sandbox, target_org, venv_id=4712)

        with pytest.raises(PermissionDenied):
            import_into(
                export_data,
                target_org,
                user=regular_user,
                effective_permissions=PermissionsWithout(ResourceType.TOOLS),
            )

        assert sandbox.removed == []
        assert SandboxVenvBinding.objects.filter(resource_id="4712").exists()


@pytest.mark.django_db
class TestToolReuseFollowsTheEnvironment:
    """A tool is matched on the environment its code runs in.

    That is what makes re-importing a flow leave both alone: reuse the environment
    and the tool running in it matches too. `find_existing` is called directly
    because the main entity of an import is always created, never matched.
    """

    def entry_from(self, tool, org):
        export_data = export_tool(tool, org)
        return export_data[EntityType.PYTHON_CODE_TOOL][0]

    def test_a_tool_on_the_same_environment_is_matched(self, default_org, sandbox):
        binding = upstream_venv(sandbox, default_org, venv_id=4711)
        tool = tool_in(default_org, binding)
        entry = self.entry_from(tool, default_org)

        id_mapper = IDMapper()
        id_mapper.map(EntityType.VENV, entry["python_code"]["venv"], binding.pk)
        found = entity_registry.get_strategy(EntityType.PYTHON_CODE_TOOL).find_existing(
            entry, id_mapper, org_id=default_org.id
        )

        assert found == tool

    def test_the_same_code_in_another_environment_is_not_matched(self, default_org, sandbox):
        binding = upstream_venv(sandbox, default_org, venv_id=4711)
        other = upstream_venv(sandbox, default_org, name="other-venv", venv_id=4712)
        entry = self.entry_from(tool_in(default_org, binding), default_org)

        id_mapper = IDMapper()
        id_mapper.map(EntityType.VENV, entry["python_code"]["venv"], other.pk)
        found = entity_registry.get_strategy(EntityType.PYTHON_CODE_TOOL).find_existing(
            entry, id_mapper, org_id=default_org.id
        )

        assert found is None
