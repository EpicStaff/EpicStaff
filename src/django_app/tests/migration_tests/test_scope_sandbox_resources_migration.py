"""The data migration that puts every bound sandbox row in its organization's scope.

The sandbox is the only thing replaced: one recording client per resource kind. A row
the sandbox no longer has is skipped, anything else stops the migration.
"""

from importlib import import_module
from unittest.mock import patch

import httpx
import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from foundation.transport.http.errors import ClientNotFoundError
from proxies.sandbox.models import SandboxCustomLibraryBinding, SandboxVenvBinding
from rbac.models import Organization

migration = import_module("proxies.migrations.0004_scope_sandbox_resources")

BEFORE = [("proxies", "0003_sandboxcustomlibrarybinding")]
AFTER = [("proxies", "0004_scope_sandbox_resources")]


class RecordingClient:
    """Records the updates it was sent; answers 404 for the ids in `missing`."""

    def __init__(self, missing: set[str] | None = None):
        self.updates: list[tuple[str, dict]] = []
        self.missing = missing or set()

    def __call__(self, *args, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def update(self, resource_id: str, data: dict) -> dict:
        if resource_id in self.missing:
            raise ClientNotFoundError("gone", response=httpx.Response(404))
        self.updates.append((resource_id, data))
        return {"id": int(resource_id), **data}


def _migrate(targets):
    MigrationExecutor(connection).migrate(targets)


def _migrate_to_leaf():
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


@pytest.mark.django_db(transaction=True)
def test_every_bound_row_gets_its_organizations_scope():
    venvs = RecordingClient(missing={"13"})
    libraries = RecordingClient()
    clients = (("SandboxVenvBinding", venvs), ("SandboxCustomLibraryBinding", libraries))
    try:
        _migrate(BEFORE)
        first = Organization.objects.create(name="Org scope backfill one")
        second = Organization.objects.create(name="Org scope backfill two")
        SandboxVenvBinding.objects.create(org_id=first.id, resource_id="11")
        SandboxVenvBinding.objects.create(org_id=second.id, resource_id="12")
        SandboxVenvBinding.objects.create(org_id=second.id, resource_id="13")
        SandboxVenvBinding.objects.create(org_id=None, resource_id="14")
        SandboxCustomLibraryBinding.objects.create(org_id=first.id, resource_id="21")

        with patch.object(migration, "BINDING_CLIENTS", clients):
            _migrate(AFTER)

        assert sorted(venvs.updates) == [
            ("11", {"scope": str(first.id)}),
            ("12", {"scope": str(second.id)}),
        ]
        assert libraries.updates == [("21", {"scope": str(first.id)})]
    finally:
        _migrate_to_leaf()
