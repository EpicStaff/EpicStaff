"""Deleting for good what a plugin owns in an organization, the way a person's delete and the
recycle bin's purge would."""

import itertools
import time
from unittest import mock

import httpx
import pytest
from agents.models import AgentDefinition, Surface
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from foundation.transport.http.errors import ClientConflictError, ClientNotFoundError
from plugins.models import GrantState, PluginOwnedResource
from plugins.ownership import owned_resource_purger
from plugins.ownership.owned_resource_purger import (
    EXTRA_PURGE_ORDER,
    FAILED_ROW_CACHE_KEY,
    PROXIED_ROOT_SERVICES,
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

    def __call__(self, *args, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def retrieve(self, resource_id: str) -> dict:
        return {"id": int(resource_id), "name": f"{self.kind}-{resource_id}"}

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


def test_a_venv_the_organization_s_code_still_runs_in_is_kept_and_reported(grant, acme, sandbox):
    venv = _venv(acme)
    own(venv, grant)
    tool = _python_tool(acme)
    PythonCode.objects.filter(pk=tool.python_code_id).update(venv=venv)

    result = _purge(grant)

    assert (result.purged, result.failed, result.remaining) == (0, 1, 1)
    assert result.first_error.startswith(f"Sandbox venv binding {venv.pk}: This environment is still used by ")
    assert tool.name in result.first_error
    assert _exists(venv)
    assert sandbox.removed == []


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
