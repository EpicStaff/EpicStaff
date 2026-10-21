"""Every view a plugin's service-account key can authenticate on is gated, or listed here with why.

A view is safe for a service account when one of these holds:

- (a) it runs `HasOrgPermission` with an `rbac_resource_type`: the plugin's declared access in
  its own organization decides;
- (b) it refuses the key outright (`DenyPluginCredential`, `DenyApiKeyAuth`, `IsSuperadmin`, or
  `IsSystemApiKeyAuthenticated`, which admits the system key alone);
- (c) it is in `PLUGIN_REACHABLE_VIEWS`: `resolver_in_code` when it checks through rbac in its
  body, `global_read_only` when it serves no organization's data and writes nothing.

Gates are read per action from `get_permissions()`, so a gate a view adds in code counts, and a
view is gated only when every action of the route is. A new view that fits none of them fails
this test until it is gated or listed.
"""

from importlib import import_module, reload

import pytest
from rbac.access.gates import (
    DenyApiKeyAuth,
    DenyPluginCredential,
    HasOrgPermission,
    IsSuperadmin,
    IsSystemApiKeyAuthenticated,
)

from tests.plugins_tests.conftest import reload_root_urlconf
from tests.plugins_tests.view_walker import plugin_reachable_views

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("every_route")]


@pytest.fixture
def every_route(plugins_enabled, settings):
    """Mount every route, the ones only DEBUG serves (the API schema) too, so each is judged."""
    debug = settings.DEBUG
    settings.DEBUG = True
    reload(import_module("django_app.yasg"))
    reload_root_urlconf()
    yield
    settings.DEBUG = debug
    reload(import_module("django_app.yasg"))
    reload_root_urlconf()

RESOLVER_IN_CODE = "resolver_in_code"
GLOBAL_READ_ONLY = "global_read_only"
REFUSING_GATES = (DenyPluginCredential, DenyApiKeyAuth, IsSuperadmin, IsSystemApiKeyAuthenticated)

# Dotted path of the view class → (category, why it is safe for a service account).
PLUGIN_REACHABLE_VIEWS: dict[str, tuple[str, str]] = {
    "plugins.views.runtime_api.ServiceAccountMeView": (RESOLVER_IN_CODE, "the plugin key only; pinned to the key's own organization by OrgContextService"),
    "plugins.views.runtime_api.PluginPersonView": (RESOLVER_IN_CODE, "the plugin key only; answers only about people who may use the plugin in the key's organization"),
    "plugins.views.runtime_api.PeopleLookupView": (RESOLVER_IN_CODE, "the plugin key only; answers only about people who may use the plugin in the key's organization"),
    "rest_framework.routers.APIRootView": (GLOBAL_READ_ONLY, "the router's index of endpoint addresses"),
    "drf_spectacular.views.SpectacularAPIView": (GLOBAL_READ_ONLY, "the API schema, served with DEBUG only"),
    "drf_spectacular.views.SpectacularSwaggerView": (GLOBAL_READ_ONLY, "the schema viewer, served with DEBUG only"),
    "drf_spectacular.views.SpectacularRedocView": (GLOBAL_READ_ONLY, "the schema viewer, served with DEBUG only"),
    "tables.views.views.RunSession": (RESOLVER_IN_CODE, "get_runnable_graph: flows use in the flow's organization"),
    "tables.views.views.SessionTestRunView": (RESOLVER_IN_CODE, "assert_org_permission on the flow, fetched in the active organization"),
    "tables.views.views.GetUpdates": (RESOLVER_IN_CODE, "get_accessible_session: flows read in the session's organization"),
    "tables.views.views.StopSession": (RESOLVER_IN_CODE, "get_accessible_session: flows use in the session's organization"),
    "tables.views.views.RunPythonCodeAPIView": (RESOLVER_IN_CODE, "assert_org_permission in the active organization"),
    "tables.views.views.PythonNodeLastTestInputView": (RESOLVER_IN_CODE, "assert_org_permission on the node's flow, fetched in the active organization"),
    "tables.views.views.QuickstartView": (RESOLVER_IN_CODE, "assert_org_permission in the active organization"),
    "tables.views.views.QuickstartApplyView": (RESOLVER_IN_CODE, "assert_org_permission in the active organization"),
    "tables.views.views.ProcessRagIndexingView": (RESOLVER_IN_CODE, "assert_org_permission on the knowledge source, fetched in the active organization"),
    "tables.views.views.CancelRagIndexingView": (RESOLVER_IN_CODE, "assert_org_permission on the knowledge source, fetched in the active organization"),
    "tables.views.views.TelegramTriggerNodeAvailableFieldsView": (GLOBAL_READ_ONLY, "the fixed list of Telegram trigger fields"),
    "tables.views.default_config.DefaultModelsAPIView": (RESOLVER_IN_CODE, "assert_org_permission in the active organization"),
    "tables.views.recycle_bin_views.RecycleBinSettingsView": (GLOBAL_READ_ONLY, "the deployment's recycle-bin retention"),
    "tables.views.sse_views.RunSessionSSEViewSwagger": (GLOBAL_READ_ONLY, "a documentation stub that answers nothing"),
    "tables.views.knowledge_views.naive_rag_views.ProcessNaiveRagDocumentChunkingView": (RESOLVER_IN_CODE, "assert_org_permission on the knowledge source, fetched in the active organization"),
    "tables.views.knowledge_views.naive_rag_views.CancelNaiveRagDocumentChunkingView": (RESOLVER_IN_CODE, "assert_org_permission on the knowledge source, fetched in the active organization"),
    "tables.views.knowledge_views.naive_rag_views.NaiveRagChunkSearchView": (RESOLVER_IN_CODE, "assert_org_permission on the knowledge source, fetched in the active organization"),
    "tables.views.knowledge_views.naive_rag_views.NaiveRagPreviewChunkBulkByIdsView": (RESOLVER_IN_CODE, "assert_org_permission on the knowledge source, fetched in the active organization"),
    "tables.views.knowledge_views.naive_rag_views.NaiveRagChunkPreviewView": (RESOLVER_IN_CODE, "assert_org_permission on the knowledge source in the active organization"),
    "tables.views.knowledge_views.search_config_views.NaiveRagSuggestParamsView": (RESOLVER_IN_CODE, "assert_org_permission on the knowledge source, fetched in the active organization"),
    "tables.views.knowledge_views.search_config_views.GraphRagSuggestParamsView": (RESOLVER_IN_CODE, "assert_org_permission on the knowledge source, fetched in the active organization"),
    "tables.views.model_view_sets.ProviderReadWriteViewSet": (GLOBAL_READ_ONLY, "the deployment's provider catalog: a service account may read it, writes are SuperAdmin-only (SuperadminWriteMixin)"),
}


def _has_org_permission_gate(view) -> bool:
    return getattr(view.view_class, "rbac_resource_type", None) is not None and all(
        any(issubclass(permission, HasOrgPermission) for permission in permissions)
        for permissions in view.permission_classes_by_action.values()
    )


def _refuses_plugin_credentials(view) -> bool:
    return all(
        any(issubclass(permission, REFUSING_GATES) for permission in permissions)
        for permissions in view.permission_classes_by_action.values()
    )


def test_every_reachable_view_is_gated_or_listed():
    unclassified = sorted(
        {
            f"{view.dotted_path} ({view.route})"
            for view in plugin_reachable_views()
            if not _has_org_permission_gate(view)
            and not _refuses_plugin_credentials(view)
            and view.dotted_path not in PLUGIN_REACHABLE_VIEWS
        }
    )

    assert unclassified == [], "gate these views or list them in PLUGIN_REACHABLE_VIEWS:\n" + "\n".join(unclassified)


def test_every_listed_view_is_reachable_and_needs_its_entry():
    routes_by_view = {}
    for view in plugin_reachable_views():
        routes_by_view.setdefault(view.dotted_path, []).append(view)

    stale = sorted(path for path in PLUGIN_REACHABLE_VIEWS if path not in routes_by_view)
    gated = sorted(
        path
        for path in PLUGIN_REACHABLE_VIEWS
        if path in routes_by_view
        and all(_has_org_permission_gate(view) or _refuses_plugin_credentials(view) for view in routes_by_view[path])
    )

    assert stale == [], f"listed views a service account can no longer reach: {stale}"
    assert gated == [], f"listed views that are gated anyway: {gated}"


def test_every_entry_names_a_category_and_a_reason():
    for path, (category, reason) in PLUGIN_REACHABLE_VIEWS.items():
        assert category in (RESOLVER_IN_CODE, GLOBAL_READ_ONLY), path
        assert reason.strip(), path


def test_the_runtime_api_reads_only_the_plugin_key():
    from plugins.identity.service_account_authentication import PluginServiceAccountAuthentication

    runtime_views = [view for view in plugin_reachable_views() if view.route.startswith("api/plugin-runtime/")]

    assert {view.route for view in runtime_views} == {
        "api/plugin-runtime/me/",
        "api/plugin-runtime/people/lookup/",
        "api/plugin-runtime/people/<int:user_id>/",
    }
    assert all(view.authentication_classes == (PluginServiceAccountAuthentication,) for view in runtime_views)
