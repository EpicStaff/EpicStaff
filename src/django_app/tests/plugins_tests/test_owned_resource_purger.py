"""Deleting for good what a plugin owns in an organization, the way a person's delete and the
recycle bin's purge would."""

import itertools
import re
import threading
import time
from contextlib import contextmanager
from unittest import mock

import httpx
import pytest
from agents.models import AgentDefinition, Surface
from django.core.cache import cache
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from foundation.transport.http.errors import ClientConflictError, ClientConnectionError, ClientNotFoundError
from plugins.lifecycle.grant_purge_service import GrantPurgeService
from plugins.models import GrantState, PluginGrant, PluginOwnedResource
from plugins.ownership import owned_resource_purger
from plugins.ownership.owned_resource_purger import (
    EXTRA_PURGE_ORDER,
    FAILED_ROW_CACHE_KEY,
    PROXIED_ROOT_SERVICES,
    HandedOver,
    HandOverPlan,
    OwnedResourcePurger,
    owned_purge_order,
)
from plugins.ownership.ownership_recorder import ownable_models
from proxies.models import AbstractBinding
from proxies.sandbox.models import SandboxCustomLibraryBinding, SandboxVenvBinding
from tables.models import (
    Graph,
    KeyValueTable,
    McpTool,
    PythonCode,
    PythonCodeTool,
    RealtimeChannel,
    Session,
    SourceCollection,
    StorageFile,
    WebhookTrigger,
)
from ai_models.models import (
    DefaultModels,
    EmbeddingConfig,
    EmbeddingModel,
    LLMModel,
)
from tables.models.llm_models import (
    RealtimeConfig,
    RealtimeModel,
    RealtimeTranscriptionConfig,
    RealtimeTranscriptionModel,
)
from tables.models.realtime_models import (
    ElevenLabsRealtimeConfig,
    GeminiRealtimeConfig,
    OpenAIRealtimeConfig,
)
from tables.services.recycle_bin.deleting import move_to_recycle_bin
from tables.services.recycle_bin.registry import bin_resources
from tables.services.storage_service.manager import StorageManager

from tests.plugins_tests.suspension_helpers import agent, flow, llm_config, own, orphan, secret_row, surface_of
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend, seed_file

pytestmark = [pytest.mark.django_db]

_numbers = itertools.count(1)


def _unique(name: str) -> str:
    return f"{name} {next(_numbers)}"


def _python_tool(organization):
    code = PythonCode.objects.create(code="def main(**kwargs):\n    return 1\n", entrypoint="main")
    return PythonCodeTool.objects.create(org=organization, name=_unique("forecast"), description="d", python_code=code)


def _realtime_config(organization):
    model = RealtimeModel.objects.create(org=organization, name=_unique("voice-model"))
    return RealtimeConfig.objects.create(org=organization, custom_name=_unique("Weather voice"), realtime_model=model)


def _transcription_config(organization):
    model = RealtimeTranscriptionModel.objects.create(org=organization, name=_unique("whisper"))
    return RealtimeTranscriptionConfig.objects.create(
        org=organization, custom_name=_unique("Weather transcription"), realtime_transcription_model=model
    )


def _venv(organization):
    return SandboxVenvBinding.objects.create(org=organization, resource_id=str(next(_numbers)))


def _custom_library(organization):
    return SandboxCustomLibraryBinding.objects.create(org=organization, resource_id=str(next(_numbers)))


# One builder per ownable model: a root of it in the organization.
ROOTS = {
    "tables.Graph": lambda organization: flow(organization, _unique("Weather forecast")),
    "agents.AgentDefinition": lambda organization: agent(organization, _unique("forecaster")),
    "agents.Surface": lambda organization: surface_of(organization, _unique("Research")),
    "tables.PythonCodeTool": _python_tool,
    "tables.McpTool": lambda organization: McpTool.objects.create(
        org=organization, name=_unique("weather-mcp"), transport="http://mcp", tool_name="forecast"
    ),
    "tables.SourceCollection": lambda organization: SourceCollection.objects.create(
        org=organization, collection_name=_unique("Forecasts")
    ),
    "ai_models.LLMConfig": lambda organization: llm_config(organization, _unique("Weather summaries")),
    "ai_models.EmbeddingConfig": lambda organization: EmbeddingConfig.objects.create(
        org=organization, custom_name=_unique("Weather embeddings")
    ),
    "tables.RealtimeConfig": _realtime_config,
    "tables.RealtimeTranscriptionConfig": _transcription_config,
    "tables.OpenAIRealtimeConfig": lambda organization: OpenAIRealtimeConfig.objects.create(
        org=organization, custom_name=_unique("OpenAI voice")
    ),
    "tables.ElevenLabsRealtimeConfig": lambda organization: ElevenLabsRealtimeConfig.objects.create(
        org=organization, custom_name=_unique("ElevenLabs voice")
    ),
    "tables.GeminiRealtimeConfig": lambda organization: GeminiRealtimeConfig.objects.create(
        org=organization, custom_name=_unique("Gemini voice")
    ),
    "ai_models.LLMModel": lambda organization: LLMModel.objects.create(org=organization, name=_unique("weather-llm")),
    "ai_models.EmbeddingModel": lambda organization: EmbeddingModel.objects.create(
        org=organization, name=_unique("weather-embedder")
    ),
    "tables.RealtimeModel": lambda organization: RealtimeModel.objects.create(org=organization, name=_unique("voice")),
    "tables.RealtimeTranscriptionModel": lambda organization: RealtimeTranscriptionModel.objects.create(
        org=organization, name=_unique("transcriber")
    ),
    "tables.KeyValueTable": lambda organization: KeyValueTable.objects.create(
        org=organization, name=_unique("weather_cache")
    ),
    "tables.Secret": lambda organization: secret_row(organization, _unique("Weather · LLM key")),
    "tables.RealtimeChannel": lambda organization: RealtimeChannel.objects.create(
        org=organization, name=_unique("Weather hotline")
    ),
    "tables.WebhookTrigger": lambda organization: WebhookTrigger.objects.create(
        org=organization, path=f"weather-hook-{next(_numbers)}"
    ),
    "proxies.SandboxVenvBinding": _venv,
    "proxies.SandboxCustomLibraryBinding": _custom_library,
}
BIN_ROOT_LABELS = sorted(resource.model._meta.label for resource in bin_resources().values())


@pytest.fixture(autouse=True)
def no_failed_rows_left():
    cache.delete_pattern("plugins:purge:failed:*")
    yield
    cache.delete_pattern("plugins:purge:failed:*")


class FakeSandboxResources:
    """The sandbox's venvs or custom libraries, as far as a delete reaches them.

    Every removal lands in the shared `removed` log as `(kind, sandbox id)`, so a test sees
    what was deleted upstream and in which order.
    """

    def __init__(self, kind: str, removed: list[tuple[str, str]]):
        self.kind = kind
        self.removed = removed
        # Sandbox id -> the error the sandbox answers its delete with.
        self.refusals: dict[str, Exception] = {}
        # Sandbox id of a venv -> the libraries it installs, as the sandbox lists them.
        self.libs: dict[str, list[dict]] = {}

    def __call__(self, *args, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def retrieve(self, resource_id: str) -> dict:
        return {"id": int(resource_id), "name": f"{self.kind}-{resource_id}"}

    def list(self, *, ids, **kwargs) -> dict:
        ids = [str(resource_id) for resource_id in ids]
        return {
            "count": len(ids),
            "result": [{**self.retrieve(resource_id), "libs": self.libs.get(resource_id, [])} for resource_id in ids],
        }

    def remove(self, resource_id: str) -> None:
        if resource_id in self.refusals:
            raise self.refusals[resource_id]
        self.removed.append((self.kind, resource_id))


def _sandbox_error(error_class, status_code):
    return error_class("refused", response=httpx.Response(status_code))


@pytest.fixture(autouse=True)
def sandbox():
    """The sandbox service, the one external boundary a venv or custom library purge reaches."""
    removed: list[tuple[str, str]] = []
    venvs = FakeSandboxResources("venv", removed)
    libraries = FakeSandboxResources("library", removed)
    with (
        mock.patch("proxies.sandbox.services.VenvService.client_class", venvs),
        mock.patch("proxies.sandbox.services.CustomLibraryService.client_class", libraries),
    ):
        yield mock.Mock(venvs=venvs, libraries=libraries, removed=removed)


@pytest.fixture
def storage():
    manager = StorageManager(InMemoryStorageBackend(organization_prefix=""))
    with mock.patch.object(owned_resource_purger, "get_storage_manager", return_value=manager):
        yield manager


@pytest.fixture
def grant(running_plugin, grant_to, acme):
    return grant_to(running_plugin(), acme, state=GrantState.PURGING)


def _purge(grant, *, until=None):
    return OwnedResourcePurger().purge(
        organization_id=grant.org_id,
        plugin_identifier=grant.plugin.identifier,
        grant=grant,
        until=until if until is not None else time.monotonic() + 60,
    )


def _exists(row) -> bool:
    return type(row)._base_manager.filter(pk=row.pk).exists()


def _file(storage, organization, path):
    seed_file(storage._backend, organization.pk, path, b"forecast")
    return StorageFile.all_objects.get(org=organization, path=path)


def _trash_keys(storage):
    return [key for key in storage._backend._objects if ".recycle-bin/" in key]


# ---- the order ----


def test_the_order_names_every_ownable_model_exactly_once():
    order = [model._meta.label for model in owned_purge_order()]

    assert len(order) == len(set(order))
    assert set(order) == {model._meta.label for model in ownable_models()}


def test_the_extra_order_lists_exactly_the_ownable_models_outside_the_bin():
    outside = {model._meta.label for model in ownable_models()} - set(BIN_ROOT_LABELS) - {"tables.StorageFile"}

    assert set(EXTRA_PURGE_ORDER) == outside
    assert len(EXTRA_PURGE_ORDER) == len(set(EXTRA_PURGE_ORDER))


def test_every_ownable_binding_is_deleted_in_the_service_that_holds_its_resource():
    # A binding hard-deleted on its own would leave its venv or library in the sandbox.
    bindings = {model._meta.label for model in ownable_models() if issubclass(model, AbstractBinding)}

    assert bindings == set(PROXIED_ROOT_SERVICES)


def test_users_go_before_what_they_use():
    order = [model._meta.label for model in owned_purge_order()]

    assert order.index("tables.PythonCodeTool") < order.index("proxies.SandboxVenvBinding")
    assert order.index("tables.Graph") < order.index("proxies.SandboxVenvBinding")
    assert order.index("proxies.SandboxVenvBinding") < order.index("proxies.SandboxCustomLibraryBinding")

    assert order.index("tables.Graph") < order.index("agents.AgentDefinition") < order.index("ai_models.LLMConfig")
    assert order.index("tables.StorageFile") < order.index("ai_models.LLMConfig") < order.index("tables.Secret")
    assert order.index("ai_models.LLMConfig") < order.index("ai_models.LLMModel") < order.index("tables.KeyValueTable")


def test_every_ownable_model_has_a_builder_here():
    assert set(ROOTS) | {"tables.StorageFile"} == {model._meta.label for model in ownable_models()}


# ---- one row of each kind ----


@pytest.mark.parametrize("label", sorted(ROOTS))
def test_a_live_root_of_each_kind_is_deleted_for_good_with_its_ownership_row(grant, acme, label, storage):
    root = ROOTS[label](acme)
    own(root, grant)

    result = _purge(grant)

    assert (result.purged, result.failed, result.remaining, result.first_error) == (1, 0, 0, None)
    assert not _exists(root)
    assert not PluginOwnedResource.objects.exists()


@pytest.mark.parametrize("label", BIN_ROOT_LABELS)
def test_a_binned_root_of_each_kind_is_purged_and_leaves_nothing_in_the_bin(grant, acme, label, storage):
    root = ROOTS[label](acme)
    own(root, grant)
    move_to_recycle_bin(root, None)

    _purge(grant)

    assert not _exists(root)
    assert not type(root).deleted_objects.filter(org=acme).exists()
    assert not PluginOwnedResource.objects.exists()


def test_a_flow_goes_with_its_nodes(grant, acme, storage):
    graph = flow(acme, "Weather forecast")
    node_ids = list(graph.python_node_list.values_list("pk", flat=True))
    own(graph, grant)

    _purge(grant)

    assert node_ids
    assert not graph.python_node_list.model._base_manager.filter(pk__in=node_ids).exists()


def test_a_live_file_inside_the_organization_s_folder_is_purged_and_the_folder_stays(grant, acme, storage):
    readme = _file(storage, acme, "weather/README.md")
    folder = StorageFile.objects.get(org=acme, path="weather/")
    own(readme, grant)

    _purge(grant)

    assert not _exists(readme)
    assert StorageFile.objects.filter(pk=folder.pk).exists()
    assert not StorageFile.deleted_objects.filter(org=acme).exists()
    assert _trash_keys(storage) == []


def test_a_file_binned_with_its_folder_is_purged_and_the_folder_stays_in_the_bin(grant, acme, storage):
    readme = _file(storage, acme, "weather/README.md")
    notes = _file(storage, acme, "weather/notes.md")
    own(readme, grant)
    storage.delete(acme.pk, "weather/", user=None)

    result = _purge(grant)

    assert result.purged == 1
    assert not _exists(readme)
    assert StorageFile.deleted_objects.filter(pk=notes.pk).exists()
    assert StorageFile.deleted_objects.filter(org=acme, path="weather/").exists()
    assert not any(key.endswith("weather/README.md") for key in _trash_keys(storage))
    assert any(key.endswith("weather/notes.md") for key in _trash_keys(storage))


def test_a_live_file_leaves_nothing_in_the_bin_or_the_trash(grant, acme, storage):
    readme = _file(storage, acme, "README.md")
    own(readme, grant)

    _purge(grant)

    assert not _exists(readme)
    assert _trash_keys(storage) == []
    assert not storage._backend._objects


def test_rows_made_on_behalf_of_a_person_are_purged(grant, acme, admin_acme, storage):
    secret = secret_row(acme, "Weather · LLM key")
    row = own(secret, grant)
    row.on_behalf_of = admin_acme
    row.save(update_fields=["on_behalf_of"])

    _purge(grant)

    assert not _exists(secret)


def test_a_root_already_gone_drops_its_ownership_row(grant, acme, storage):
    secret = secret_row(acme, "Weather · LLM key")
    own(secret, grant)
    type(secret)._base_manager.filter(pk=secret.pk).delete()

    result = _purge(grant)

    assert (result.purged, result.failed, result.remaining) == (1, 0, 0)
    assert not PluginOwnedResource.objects.exists()


def test_rows_whose_grant_is_gone_go_with_the_grant_s_purge(grant, acme, storage):
    owned = secret_row(acme, "Weather · LLM key")
    left_behind = secret_row(acme, "Weather · old key")
    own(owned, grant)
    orphan(left_behind, acme)

    _purge(grant)

    assert not _exists(owned)
    assert not _exists(left_behind)


# ---- venvs and custom libraries, held by the sandbox ----


def test_a_venv_and_a_custom_library_are_deleted_in_the_sandbox_venv_first(grant, acme, sandbox):
    library = _custom_library(acme)
    venv = _venv(acme)
    own(library, grant)
    own(venv, grant)

    result = _purge(grant)

    assert (result.purged, result.failed, result.remaining) == (2, 0, 0)
    assert sandbox.removed == [("venv", venv.resource_id), ("library", library.resource_id)]
    assert not _exists(venv)
    assert not _exists(library)
    assert not PluginOwnedResource.objects.exists()


def _run_in(venv, python_code_id):
    PythonCode.objects.filter(pk=python_code_id).update(venv=venv)


def _organization_s_tool_code(grant, organization):
    return _python_tool(organization).python_code_id


def _organization_s_binned_tool_code(grant, organization):
    tool = _python_tool(organization)
    move_to_recycle_bin(tool, None)
    return tool.python_code_id


def _organization_s_flow_node_code(grant, organization):
    return flow(organization, _unique("Daily digest")).python_node_list.get().python_code_id


def _plugin_s_held_back_tool_code(grant, organization):
    tool = _python_tool(organization)
    cache.set(FAILED_ROW_CACHE_KEY.format(pk=own(tool, grant).pk), 1)
    return tool.python_code_id


def _hand_over(grant, *, with_grant=True):
    purger = OwnedResourcePurger()
    plan = purger.plan_hand_over(
        organization_id=grant.org_id,
        plugin_identifier=grant.plugin.identifier,
        grant=grant if with_grant else None,
    )
    if plan is None:
        return None
    with transaction.atomic():
        return purger.hand_over(plan)


def _owns(row) -> bool:
    return PluginOwnedResource.objects.filter(
        content_type=ContentType.objects.get_for_model(row), object_id=row.pk
    ).exists()


def _installing(library):
    """A venv's libraries naming `library`, spelled differently: names compare canonical."""
    return [{"name": f"Library_{library.resource_id}", "is_custom": True}]


@pytest.mark.parametrize(
    "code_in_venv",
    [
        _organization_s_tool_code,
        _organization_s_binned_tool_code,
        _organization_s_flow_node_code,
        _plugin_s_held_back_tool_code,
    ],
    ids=["organization's tool", "organization's binned tool", "organization's flow node", "plugin's held-back tool"],
)
def test_a_venv_some_code_still_runs_in_waits_without_an_error(grant, acme, sandbox, code_in_venv):
    venv = _venv(acme)
    own(venv, grant)
    _run_in(venv, code_in_venv(grant, acme))

    result = _purge(grant)

    assert (result.purged, result.failed, result.first_error) == (0, 0, None)
    assert _exists(venv) and _owns(venv)
    assert sandbox.removed == []


def test_a_custom_library_a_venv_of_the_organization_names_waits_without_an_error(grant, acme, sandbox):
    library = _custom_library(acme)
    own(library, grant)
    organization_s_venv = _venv(acme)
    sandbox.venvs.libs[organization_s_venv.resource_id] = _installing(library)

    result = _purge(grant)

    assert (result.purged, result.failed, result.remaining, result.first_error) == (0, 0, 1, None)
    assert _exists(library) and _owns(library)
    assert sandbox.removed == []


@pytest.mark.parametrize("is_custom", [False, True], ids=["package index entry", "another organization's venv"])
def test_a_custom_library_only_an_index_package_or_another_organization_names_is_deleted(
    grant, acme, beta, sandbox, is_custom
):
    library = _custom_library(acme)
    own(library, grant)
    venv = _venv(beta if is_custom else acme)
    sandbox.venvs.libs[venv.resource_id] = [{"name": f"library-{library.resource_id}", "is_custom": is_custom}]

    result = _purge(grant)

    assert (result.purged, result.failed, result.remaining) == (1, 0, 0)
    assert sandbox.removed == [("library", library.resource_id)]


@pytest.mark.parametrize(
    "organization_s_code",
    [_organization_s_tool_code, _organization_s_binned_tool_code, _organization_s_flow_node_code],
    ids=["tool", "binned tool", "flow node"],
)
def test_a_venv_the_organization_s_code_runs_in_is_handed_over_to_it(grant, acme, sandbox, organization_s_code):
    venv = _venv(acme)
    own(venv, grant)
    _run_in(venv, organization_s_code(grant, acme))
    _purge(grant)

    handed_over = _hand_over(grant)

    assert handed_over == HandedOver(venvs=(f"venv-{venv.resource_id} (id {venv.pk})",))
    assert _exists(venv)
    assert not PluginOwnedResource.objects.exists()
    assert sandbox.removed == []


def test_a_handed_over_venv_takes_the_plugin_s_custom_library_it_names_with_it(grant, acme, sandbox):
    library = _custom_library(acme)
    venv = _venv(acme)
    own(library, grant)
    own(venv, grant)
    _run_in(venv, _organization_s_tool_code(grant, acme))
    sandbox.venvs.libs[venv.resource_id] = _installing(library)
    _purge(grant)

    handed_over = _hand_over(grant)

    assert handed_over == HandedOver(
        venvs=(f"venv-{venv.resource_id} (id {venv.pk})",),
        custom_libraries=(f"library-{library.resource_id} (id {library.pk})",),
    )
    assert _exists(venv) and _exists(library)
    assert not PluginOwnedResource.objects.exists()
    assert sandbox.removed == []


def test_a_custom_library_a_venv_of_the_organization_names_is_handed_over(grant, acme, sandbox):
    library = _custom_library(acme)
    own(library, grant)
    organization_s_venv = _venv(acme)
    sandbox.venvs.libs[organization_s_venv.resource_id] = _installing(library)
    _purge(grant)

    handed_over = _hand_over(grant)

    assert handed_over == HandedOver(custom_libraries=(f"library-{library.resource_id} (id {library.pk})",))
    assert _exists(library) and not _owns(library)


def test_rows_whose_grant_is_gone_are_handed_over_too(grant, acme, sandbox):
    venv = _venv(acme)
    orphan(venv, acme)
    _run_in(venv, _organization_s_tool_code(grant, acme))

    handed_over = _hand_over(grant, with_grant=False)

    assert handed_over == HandedOver(venvs=(f"venv-{venv.resource_id} (id {venv.pk})",))
    assert _exists(venv) and not _owns(venv)


def test_nothing_is_handed_over_while_the_plugin_s_own_rows_are_left(grant, acme, sandbox):
    venv = _venv(acme)
    own(venv, grant)
    _run_in(venv, _plugin_s_held_back_tool_code(grant, acme))
    _purge(grant)

    assert _hand_over(grant) is None
    assert _owns(venv)
    assert PluginOwnedResource.objects.count() == 2


def test_a_venv_nothing_runs_in_any_more_is_not_handed_over_but_deleted(grant, acme, sandbox):
    venv = _venv(acme)
    own(venv, grant)
    tool = _python_tool(acme)
    _run_in(venv, tool.python_code_id)
    _purge(grant)
    # The organization moved its tool to another venv after the pass.
    _run_in(None, tool.python_code_id)

    handed_over = _hand_over(grant)
    result = _purge(grant)

    assert handed_over is None
    assert (result.purged, result.remaining) == (1, 0)
    assert not _exists(venv)
    assert sandbox.removed == [("venv", venv.resource_id)]


def test_nothing_left_hands_over_nothing(grant):
    assert _hand_over(grant) == HandedOver()


def test_a_custom_library_no_venv_names_is_not_handed_over(grant, acme, sandbox):
    library = _custom_library(acme)
    own(library, grant)
    venv = _venv(acme)
    own(venv, grant)
    _run_in(venv, _organization_s_tool_code(grant, acme))

    assert _hand_over(grant) is None
    assert _owns(library) and _owns(venv)


@pytest.mark.parametrize("kind", ["venv", "custom library"])
def test_another_organization_s_binding_is_never_handed_over(grant, acme, beta, sandbox, kind):
    if kind == "venv":
        theirs = _venv(beta)
        _run_in(theirs, _organization_s_tool_code(grant, beta))
    else:
        theirs = _custom_library(beta)
        sandbox.venvs.libs[_venv(beta).resource_id] = _installing(theirs)
        sandbox.venvs.libs[_venv(acme).resource_id] = _installing(theirs)
    row = PluginOwnedResource.objects.create(
        org=acme,
        grant=grant,
        plugin_identifier=grant.plugin.identifier,
        content_type=ContentType.objects.get_for_model(theirs),
        object_id=theirs.pk,
    )
    purger = OwnedResourcePurger()
    # What a plan would hold had it not checked the organization: the lock checks it again.
    unchecked_plan = HandOverPlan(
        acme.pk,
        grant.plugin.identifier,
        grant,
        row_ids=(row.pk,),
        venv_ids=(theirs.pk,) if kind == "venv" else (),
        library_ids=(theirs.pk,) if kind != "venv" else (),
        handed_over=HandedOver(venvs=("theirs",)),
    )

    planned = purger.plan_hand_over(organization_id=acme.pk, plugin_identifier=grant.plugin.identifier, grant=grant)
    with transaction.atomic():
        applied = purger.hand_over(unchecked_plan)

    assert (planned, applied) == (None, None)
    assert PluginOwnedResource.objects.filter(pk=row.pk).exists()


def test_code_no_tool_or_node_owns_keeps_no_venv_and_goes_with_it(grant, acme, sandbox):
    venv = _venv(acme)
    own(venv, grant)
    leftover = PythonCode.objects.create(code="def main():\n    return 1\n", venv=venv)

    handed_over = _hand_over(grant)
    result = _purge(grant)

    assert handed_over is None
    assert (result.purged, result.failed, result.remaining) == (1, 0, 0)
    assert not _exists(venv) and not PythonCode.objects.filter(pk=leftover.pk).exists()
    assert sandbox.removed == [("venv", venv.resource_id)]


def _sandbox_list_calls(sandbox, *, raising=None):
    """Record how deep in transactions each list call to the sandbox was made."""
    depths = []
    for resources in (sandbox.venvs, sandbox.libraries):
        original = resources.list

        def listing(*args, original=original, **kwargs):
            depths.append(len(connection.atomic_blocks))
            if raising is not None:
                raise raising
            return original(*args, **kwargs)

        resources.list = listing
    return depths


def test_the_grant_goes_with_its_venv_handed_over_and_the_sandbox_asked_before_any_lock(grant, acme, sandbox):
    venv = _venv(acme)
    own(venv, grant)
    _run_in(venv, _organization_s_tool_code(grant, acme))
    depths = _sandbox_list_calls(sandbox)
    outside = len(connection.atomic_blocks)

    finished = GrantPurgeService().finish_if_done(grant)

    assert finished
    assert depths == [outside]
    assert not PluginGrant.objects.filter(pk=grant.pk).exists()
    assert _exists(venv) and not _owns(venv)


def test_a_sandbox_outage_at_the_finish_keeps_the_grant_and_every_ownership_row(
    grant, acme, sandbox, log_messages
):
    venv = _venv(acme)
    library = _custom_library(acme)
    own(venv, grant)
    own(library, grant)
    _run_in(venv, _organization_s_tool_code(grant, acme))
    _sandbox_list_calls(sandbox, raising=ClientConnectionError("sandbox down"))

    finished = GrantPurgeService().finish_if_done(grant)

    assert not finished
    assert PluginGrant.objects.get(pk=grant.pk).state == GrantState.PURGING
    assert _owns(venv) and _owns(library)
    assert any(
        message.startswith("plugins.purge.hand_over_unplanned")
        and f"org={acme.pk}" in message
        and "error=ClientConnectionError" in message
        for message in log_messages
    )


def test_with_another_row_left_the_finish_locks_nothing_and_asks_no_sandbox(grant, acme, sandbox):
    venv = _venv(acme)
    own(venv, grant)
    _run_in(venv, _plugin_s_held_back_tool_code(grant, acme))
    depths = _sandbox_list_calls(sandbox)

    with CaptureQueriesContext(connection) as queries:
        finished = GrantPurgeService().finish_if_done(grant)

    assert not finished
    assert depths == []
    assert not [query["sql"] for query in queries if re.search(r"FOR (NO KEY )?UPDATE", query["sql"])]
    assert PluginOwnedResource.objects.count() == 2


# Real commits: each row's transaction commits on its own, as in production, so the
# on_commit reclaim of the purged tool's code runs before the venv's row is tried.
@pytest.mark.django_db(transaction=True)
def test_a_venv_the_plugin_s_own_tool_runs_in_goes_in_the_same_pass(grant, acme, sandbox):
    venv = _venv(acme)
    tool = _python_tool(acme)
    PythonCode.objects.filter(pk=tool.python_code_id).update(venv=venv)
    own(venv, grant)
    own(tool, grant)

    result = _purge(grant)

    assert (result.purged, result.failed, result.remaining) == (2, 0, 0)
    assert result.first_error is None
    assert not _exists(tool)
    assert not PythonCode.objects.filter(pk=tool.python_code_id).exists()
    assert not _exists(venv)
    assert sandbox.removed == [("venv", venv.resource_id)]


def test_a_custom_library_the_sandbox_refuses_to_delete_is_kept(grant, acme, sandbox):
    library = _custom_library(acme)
    own(library, grant)
    sandbox.libraries.refusals[library.resource_id] = _sandbox_error(ClientConflictError, 409)

    result = _purge(grant)

    assert (result.purged, result.failed, result.remaining) == (0, 1, 1)
    assert result.first_error == f"Sandbox custom library binding {library.pk}: ClientConflictError"
    assert _exists(library)


def test_a_venv_already_gone_from_the_sandbox_still_loses_its_binding(grant, acme, sandbox):
    venv = _venv(acme)
    own(venv, grant)
    sandbox.venvs.refusals[venv.resource_id] = _sandbox_error(ClientNotFoundError, 404)

    result = _purge(grant)

    assert (result.purged, result.failed, result.remaining) == (1, 0, 0)
    assert not _exists(venv)


def test_another_organization_s_venv_is_never_deleted_in_the_sandbox(grant, acme, beta, sandbox):
    theirs = _venv(beta)
    PluginOwnedResource.objects.create(
        org=acme,
        grant=grant,
        plugin_identifier=grant.plugin.identifier,
        content_type=ContentType.objects.get_for_model(SandboxVenvBinding),
        object_id=theirs.pk,
    )

    _purge(grant)

    assert _exists(theirs)
    assert sandbox.removed == []


def _sandbox_calls(sandbox):
    """Record, per call the purge makes to the sandbox, its kind and how deep in transactions
    it was made."""
    calls = []
    for resources in (sandbox.venvs, sandbox.libraries):
        original_list, original_retrieve = resources.list, resources.retrieve
        listing = []

        def recorded_list(*args, kind=f"{resources.kind}.list", original=original_list, listing=listing, **kwargs):
            calls.append((kind, len(connection.atomic_blocks)))
            listing.append(True)
            try:
                return original(*args, **kwargs)
            finally:
                listing.pop()

        def recorded_retrieve(*args, kind=f"{resources.kind}.retrieve", original=original_retrieve, listing=listing):
            # The fake builds a listing from its own retrieve: that is not a call of its own.
            if not listing:
                calls.append((kind, len(connection.atomic_blocks)))
            return original(*args)

        resources.list, resources.retrieve = recorded_list, recorded_retrieve
    return calls


def test_a_pass_asks_the_sandbox_which_libraries_are_in_use_once_before_any_row_s_transaction(
    grant, acme, sandbox
):
    named = [_custom_library(acme) for _ in range(2)]
    for library in named:
        own(library, grant)
    organization_s_venv = _venv(acme)
    sandbox.venvs.libs[organization_s_venv.resource_id] = [
        entry for library in named for entry in _installing(library)
    ]
    calls = _sandbox_calls(sandbox)
    outside = len(connection.atomic_blocks)

    result = _purge(grant)

    assert (result.purged, result.failed, result.remaining) == (0, 0, 2)
    assert sorted(calls) == [("library.list", outside), ("venv.list", outside)]


def test_a_pass_with_no_custom_library_left_asks_the_sandbox_nothing_about_libraries(grant, acme, sandbox):
    venv = _venv(acme)
    own(venv, grant)
    calls = _sandbox_calls(sandbox)

    _purge(grant)

    assert [kind for kind, _depth in calls if kind.endswith(".list")] == []
    assert sandbox.removed == [("venv", venv.resource_id)]


def test_a_library_only_the_plugin_s_own_venv_named_goes_in_the_same_pass_as_that_venv(grant, acme, sandbox):
    library = _custom_library(acme)
    venv = _venv(acme)
    own(library, grant)
    own(venv, grant)
    sandbox.venvs.libs[venv.resource_id] = _installing(library)

    result = _purge(grant)

    assert (result.purged, result.failed, result.remaining) == (2, 0, 0)
    assert sandbox.removed == [("venv", venv.resource_id), ("library", library.resource_id)]


def test_while_the_sandbox_cannot_say_which_libraries_are_in_use_they_wait_and_the_rest_goes(
    grant, acme, sandbox, storage
):
    library = _custom_library(acme)
    own(library, grant)
    other = secret_row(acme, _unique("Weather key"))
    own(other, grant)
    _sandbox_list_calls(sandbox, raising=ClientConnectionError("sandbox down"))

    result = _purge(grant)

    assert (result.purged, result.failed, result.remaining, result.first_error) == (1, 0, 1, None)
    assert _exists(library) and _owns(library)
    assert not _exists(other)
    assert sandbox.removed == []


def test_a_library_added_after_the_pass_read_the_sandbox_waits_for_the_next_pass(grant, acme, sandbox):
    library = _custom_library(acme)
    own(library, grant)
    late = _custom_library(acme)
    list_venvs = sandbox.venvs.list

    def list_venvs_then_add_a_library(*args, **kwargs):
        # The pass reads the venvs last: the plugin adds a library right after.
        page = list_venvs(*args, **kwargs)
        own(late, grant)
        return page

    sandbox.venvs.list = list_venvs_then_add_a_library

    result = _purge(grant)

    assert (result.purged, result.remaining) == (1, 1)
    assert _exists(late) and _owns(late)
    assert sandbox.removed == [("library", library.resource_id)]


# ---- a plan the ownership rows no longer match ----


def _planned_venv_hand_over(grant, organization):
    venv = _venv(organization)
    own(venv, grant)
    code_id = _organization_s_tool_code(grant, organization)
    _run_in(venv, code_id)
    plan = OwnedResourcePurger().plan_hand_over(
        organization_id=grant.org_id, plugin_identifier=grant.plugin.identifier, grant=grant
    )
    assert plan is not None
    return venv, plan, code_id


def test_a_row_of_another_kind_added_since_the_plan_stops_the_hand_over(grant, acme, sandbox):
    venv, plan, _ = _planned_venv_hand_over(grant, acme)
    added = own(secret_row(acme, _unique("Weather key")), grant)

    with transaction.atomic():
        handed_over = OwnedResourcePurger().hand_over(plan)

    assert handed_over is None
    assert _owns(venv)
    assert PluginOwnedResource.objects.filter(pk=added.pk).exists()


def test_a_venv_no_code_runs_in_any_more_since_the_plan_is_not_handed_over(grant, acme, sandbox):
    venv, plan, code_id = _planned_venv_hand_over(grant, acme)
    assert plan.venv_ids == (venv.pk,)
    # The organization moved its tool off the venv after the plan was read.
    _run_in(None, code_id)

    with transaction.atomic():
        handed_over = OwnedResourcePurger().hand_over(plan)

    assert handed_over is None
    assert _owns(venv)


@contextmanager
def _locked_by_another_connection(row: PluginOwnedResource):
    """Hold `row` locked in another connection's open transaction, as another pass would."""
    locked = threading.Event()
    release = threading.Event()

    def hold():
        try:
            with transaction.atomic():
                PluginOwnedResource.objects.select_for_update().get(pk=row.pk)
                locked.set()
                release.wait(30)
        finally:
            connection.close()

    holder = threading.Thread(target=hold)
    holder.start()
    try:
        assert locked.wait(30)
        yield
    finally:
        release.set()
        holder.join(30)


# Real commits: another connection sees and locks only committed rows.
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("locked_row", ["planned", "added since the plan"])
def test_a_row_another_process_holds_stops_the_hand_over(grant, acme, sandbox, locked_row):
    venv, plan, _ = _planned_venv_hand_over(grant, acme)
    if locked_row == "planned":
        held = PluginOwnedResource.objects.get(pk=plan.row_ids[0])
    else:
        held = own(_custom_library(acme), grant)

    with _locked_by_another_connection(held), transaction.atomic():
        handed_over = OwnedResourcePurger().hand_over(plan)

    assert handed_over is None
    assert _owns(venv)
    assert PluginOwnedResource.objects.filter(pk=held.pk).exists()


# ---- what the organization's own rows lose ----


def test_the_organization_s_rows_lose_what_they_used_and_its_flow_stays(grant, acme, storage):
    config = llm_config(acme, "Weather summaries")
    own(config, grant)
    writer = agent(acme, "Digest writer", llm_config=config)
    digest = flow(acme, "Daily digest")
    DefaultModels.objects.create(org=acme, agent_llm_config=config)

    _purge(grant)

    writer.refresh_from_db()
    assert writer.llm_config_id is None
    assert DefaultModels.objects.get(org=acme).agent_llm_config_id is None
    assert Graph.objects.filter(pk=digest.pk).exists()
    assert AgentDefinition.objects.filter(pk=writer.pk).exists()


def test_a_custom_model_a_person_s_config_reuses_is_kept_and_only_its_ownership_goes(grant, acme, storage):
    # The plugin named a model the catalog does not know: its config created the custom row,
    # and a person's config of the same model reuses that row.
    model = LLMModel.objects.create(org=acme, name="weather-fine-tune", is_custom=True)
    own(model, grant)
    own(llm_config(acme, "Weather summaries", model=model), grant)
    persons_config = llm_config(acme, "Team summaries", model=model)

    first = _purge(grant)
    second = _purge(grant)

    assert (first.purged, first.failed, first.remaining) == (2, 0, 0)
    assert _exists(model) and _exists(persons_config)
    assert not PluginOwnedResource.objects.exists()
    assert (second.purged, second.failed, second.remaining) == (0, 0, 0)


def test_a_model_only_the_plugin_s_configs_use_goes_with_them(grant, acme, storage):
    model = EmbeddingModel.objects.create(org=acme, name="weather-embed", is_custom=True)
    own(model, grant)
    config = EmbeddingConfig.objects.create(org=acme, custom_name="Weather embeddings", model=model)
    own(config, grant)

    result = _purge(grant)

    assert (result.purged, result.failed, result.remaining) == (2, 0, 0)
    assert not _exists(model) and not _exists(config)


# ---- what is held back ----


def test_a_root_linked_to_another_organization_is_kept_and_not_retried_for_an_hour(
    grant, acme, beta, storage, log_messages
):
    forecaster = agent(acme, "Forecaster")
    own(forecaster, grant)
    Surface.objects.create(org=beta, name="Beta research", owner_agent=forecaster)
    secret = secret_row(acme, "Weather · LLM key")
    own(secret, grant)

    first = _purge(grant)
    second = _purge(grant)

    assert (first.purged, first.failed, first.remaining) == (1, 1, 1)
    assert first.first_error.startswith(f"Agent definition {forecaster.pk}: ")
    assert _exists(forecaster)
    assert not _exists(secret)
    assert (second.purged, second.failed, second.remaining) == (0, 0, 1)
    assert cache.get(FAILED_ROW_CACHE_KEY.format(pk=PluginOwnedResource.objects.get().pk)) is not None
    failure = next(message for message in log_messages if message.startswith("plugins.purge.resource_failed"))
    assert f"model=agents.AgentDefinition pk={forecaster.pk} error=CrossOrgCascadeError" in failure
    assert "Beta" not in failure


def test_a_storage_failure_rolls_back_that_row_only(grant, acme, storage):
    readme = _file(storage, acme, "README.md")
    own(readme, grant)
    secret = secret_row(acme, "Weather · LLM key")
    own(secret, grant)

    with mock.patch.object(storage, "delete_trash_batch", side_effect=OSError("storage down")):
        result = _purge(grant)

    assert (result.purged, result.failed) == (1, 1)
    assert result.first_error == f"Storage file {readme.pk}: OSError"
    assert StorageFile.all_objects.filter(pk=readme.pk).exists()
    assert PluginOwnedResource.objects.filter(object_id=readme.pk).exists()
    assert not _exists(secret)


def test_another_plugin_s_or_organization_s_rows_are_untouched(grant, acme, beta, running_plugin, grant_to, storage):
    other_plugin = running_plugin(id="forecast", name="Forecast")
    other_grant = grant_to(other_plugin, acme)
    theirs = secret_row(acme, "Forecast key")
    own(theirs, other_grant)
    beta_grant = grant_to(grant.plugin, beta)
    beta_row = secret_row(beta, "Weather key")
    own(beta_row, beta_grant)
    orphan(secret_row(beta, "Weather old key"), beta)

    result = _purge(grant)

    assert (result.purged, result.remaining) == (0, 0)
    assert _exists(theirs)
    assert _exists(beta_row)
    assert PluginOwnedResource.objects.count() == 3


def test_a_flow_with_a_running_session_waits(grant, acme, storage):
    graph = flow(acme, "Weather forecast")
    own(graph, grant)
    session = Session.objects.create(graph=graph, status=Session.SessionStatus.RUN)

    waiting = _purge(grant)
    Session.objects.filter(pk=session.pk).update(status=Session.SessionStatus.END)
    done = _purge(grant)

    assert (waiting.purged, waiting.failed, waiting.remaining) == (0, 0, 1)
    assert (done.purged, done.remaining) == (1, 0)
    assert not _exists(graph)


def test_the_budget_stops_the_pass_after_one_row(grant, acme, storage):
    for index in range(3):
        own(secret_row(acme, f"Weather key {index}"), grant)

    result = _purge(grant, until=time.monotonic() - 1)

    assert (result.purged, result.remaining) == (1, 2)


def test_the_organization_s_deletion_stops_the_pass(grant, acme, storage):
    own(secret_row(acme, "Weather key"), grant)
    organization_id = acme.pk
    grant_plugin = grant.plugin
    acme.delete()

    result = OwnedResourcePurger().purge(
        organization_id=organization_id, plugin_identifier=grant_plugin.identifier, grant=None, until=time.monotonic() + 60
    )

    assert (result.purged, result.failed, result.remaining) == (0, 0, 0)


def test_each_row_costs_the_same_number_of_queries(grant, acme, storage):
    def queries_for(count):
        for index in range(count):
            own(secret_row(acme, _unique("Weather key")), grant)
        with CaptureQueriesContext(connection) as queries:
            result = _purge(grant)
        assert result.purged == count
        return len(queries)

    one, two, three = queries_for(1), queries_for(2), queries_for(3)

    assert three - two == two - one
    # Nearly all of it is the recycle bin's own delete and purge of a secret, which walk every
    # relation that can point at one.
    assert two - one <= 70


def test_rows_are_purged_in_the_order_users_before_what_they_use(grant, acme, storage):
    secret_ownership = own(secret_row(acme, "Weather key"), grant)
    flow_ownership = own(flow(acme, "Weather forecast"), grant)

    order = list(owned_resource_purger._in_purge_order(PluginOwnedResource.objects.filter(grant=grant)))

    assert order == [flow_ownership.pk, secret_ownership.pk]


# ---- a failure that holds a row back ----

from django.contrib.contenttypes.models import ContentType  # noqa: E402


def test_a_purge_error_stands_while_its_row_is_held_back_and_clears_once_it_is_purged(grant, acme, storage):
    from plugins.lifecycle.grant_purge_service import GrantPurgeService
    from plugins.models import Plugin, PluginGrant

    readme = _file(storage, acme, "README.md")
    own(readme, grant)
    service = GrantPurgeService()

    with mock.patch.object(storage, "delete_trash_batch", side_effect=OSError("storage down")):
        first = service.advance(grant, time.monotonic() + 60)
    second = service.advance(grant, time.monotonic() + 60)

    assert (first.failed, second.failed, second.held_back) == (1, 0, 1)
    assert PluginGrant.objects.get(pk=grant.pk).last_purge_error == f"Storage file {readme.pk}: OSError"
    assert Plugin.objects.with_summary().get(pk=grant.plugin_id).needs_attention

    cache.delete_pattern("plugins:purge:failed:*")
    third = service.advance(grant, time.monotonic() + 60)

    assert (third.purged, third.held_back) == (1, 0)
    assert PluginGrant.objects.get(pk=grant.pk).last_purge_error is None
    assert not Plugin.objects.with_summary().get(pk=grant.plugin_id).needs_attention


def test_an_ownership_row_naming_another_organization_s_resource_never_deletes_it(grant, acme, beta, log_messages):
    theirs = secret_row(beta, "Beta's key")
    PluginOwnedResource.objects.create(
        org=acme,
        grant=grant,
        plugin_identifier=grant.plugin.identifier,
        content_type=ContentType.objects.get_for_model(type(theirs)),
        object_id=theirs.pk,
    )

    result = _purge(grant)

    assert _exists(theirs)
    assert not PluginOwnedResource.objects.filter(object_id=theirs.pk).exists()
    assert result.failed == 0
    assert any(
        message.startswith("plugins.purge.foreign_root ") and f"org={acme.pk}" in message for message in log_messages
    )


def test_the_purge_takes_the_organization_s_lock_without_its_key(grant, acme):
    own(secret_row(acme, "Weather · LLM key"), grant)

    with CaptureQueriesContext(connection) as captured:
        _purge(grant)

    organization_locks = [
        query["sql"] for query in captured.captured_queries if 'FROM "rbac_organization"' in query["sql"] and "FOR " in query["sql"]
    ]
    assert organization_locks and all("FOR NO KEY UPDATE" in sql for sql in organization_locks)
