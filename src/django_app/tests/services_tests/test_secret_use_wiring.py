"""Every write point that saves a secret-bearing entity is wired to its secret Use check.

`test_secret_reference_coverage.py` proves each Secret-targeting serializer has a
`check_<entity>_write`. These tests prove the routed viewsets and the graph bulk-save
registry actually run it: a viewset that reuses a guarded serializer without
`secret_use_check`, or whose `SecretUseCheckedViewSetMixin` sits where it never runs,
writes unchecked and no API test of another endpoint would notice.

They read classes only and need no database.
"""

from types import SimpleNamespace

from django.urls import URLResolver, get_resolver
from rbac.scoping.mixins import (
    BuiltInWriteProtectedMixin,
    OrgScopedChildViewSetMixin,
    OrgScopedHybridViewSetMixin,
    OrgScopedViewSetMixin,
)
from rest_framework.generics import GenericAPIView
from rest_framework.serializers import BaseSerializer, ListSerializer
from tables.services.graph_bulk_save_service.registry import NODE_TYPE_REGISTRY
from tables.services.secrets import secret_use_checks
from tables.views.secret_use import SecretUseCheckedViewSetMixin
from tests.services_tests.test_secret_reference_coverage import (
    KNOWN_SKIPS,
    SECRET_USE_CHECK_BY_SERIALIZER,
    _secret_fields_of,
    _try_instantiate,
)

#: The secret Use check of each viewset whose check cannot be read off its write
#: serializer: either the serializer only nests a guarded one (PythonCodeSerializer,
#: whose check_python_code_write every parent's own check calls), or the check gates
#: a destination rather than a Secret field.
SECRET_USE_CHECK_BY_VIEWSET: dict[str, str] = {
    "PythonNodeViewSet": "check_python_node_write",
    "WebhookTriggerNodeViewSet": "check_webhook_trigger_node_write",
    "PythonCodeToolViewSet": "check_python_code_tool_write",
    # No Secret field: the check gates `base_url` while a config of the model carries a secret.
    "LLMModelReadWriteViewSet": "check_llm_model_write",
    "EmbeddingModelReadWriteViewSet": "check_embedding_model_write",
}

#: Viewsets that write a guarded serializer without `secret_use_check`, because their
#: write does not go through perform_create / perform_update. Each entry says where the
#: check runs instead; the API tests named there pin that it does.
CUSTOM_WRITE_PATHS: dict[str, str] = {
    "ClassificationDecisionTableNodeModelViewSet": (
        "create and update hand the request to ClassificationDecisionTableNodeService."
        "create_or_update, which runs check_cdt_node_write after validation "
        "(tests/api_tests/test_secret_use_fk_fields.py)."
    ),
}
# Not routed through a viewset serializer, so out of reach of the discovery below:
# QuickstartView.post builds QuickstartSerializer itself and calls check_quickstart
# (tests/api_tests/test_secret_use_fk_fields.py), and the config import strategies call
# check_config_import (tests/import_export_tests/test_config_marker_import_secret_use.py).

#: Classes allowed between a viewset and SecretUseCheckedViewSetMixin in its MRO, each
#: with why it cannot stop the secret check from running. Any other class there that
#: overrides perform_create or perform_update could save before the check.
DELEGATING_MIXINS_BEFORE_SECRET_CHECK: dict[type, str] = {
    # On LLMModelReadWriteViewSet and EmbeddingModelReadWriteViewSet, so a built-in model
    # is a 403 before the secret check counts its configs. It defines no perform_create
    # and its perform_update calls super(), so the secret check still runs.
    BuiltInWriteProtectedMixin: "perform_update calls super(); no perform_create",
}

#: The bulk-save check of every node type whose bulk serializer, or a serializer nested
#: in it, has a writable Secret-targeting field.
BULK_SAVE_SECRET_USE_CHECK_BY_LIST_KEY: dict[str, str] = {
    "python_node_list": "check_python_node_write",
    "webhook_trigger_node_list": "check_webhook_trigger_node_write",
    "classification_decision_table_node_list": "check_cdt_node_write",
    "telegram_trigger_node_list": "check_telegram_trigger_node_write",
}

# The OrgScoped* mixins whose perform_create saves without calling super().
_SAVING_ORG_SCOPED_MIXINS = (
    OrgScopedViewSetMixin,
    OrgScopedChildViewSetMixin,
    OrgScopedHybridViewSetMixin,
)
_WRITE_ACTIONS = ("create", "update", "partial_update")


def _routed_view_classes() -> dict[str, type]:
    """Every DRF view class the URLconf routes to, by class name."""
    view_classes = {}
    pending = list(get_resolver().url_patterns)
    while pending:
        pattern = pending.pop()
        if isinstance(pattern, URLResolver):
            pending.extend(pattern.url_patterns)
            continue
        view_class = getattr(pattern.callback, "cls", None)
        if view_class is not None:
            view_classes[view_class.__name__] = view_class
    return view_classes


def _write_serializer_classes(view_class) -> set[type]:
    """`serializer_class` plus what an overridden get_serializer_class returns for each write action."""
    serializer_classes = set()
    declared = getattr(view_class, "serializer_class", None)
    if declared is not None:
        serializer_classes.add(declared)
    if view_class.get_serializer_class is not GenericAPIView.get_serializer_class:
        for action in _WRITE_ACTIONS:
            # Built without __init__: the overrides read only `action` and the query string.
            view = view_class.__new__(view_class)
            view.action = action
            view.request = SimpleNamespace(query_params={}, method="POST", user=None)
            view.kwargs = {}
            view.format_kwarg = None
            serializer_class = view.get_serializer_class()
            if serializer_class is not None:
                serializer_classes.add(serializer_class)
    return serializer_classes


def _writable_serializer_tree(root: BaseSerializer):
    """Yield `root` and every serializer nested in it that a write can fill."""
    pending = [root]
    seen_classes = set()
    while pending:
        current = pending.pop()
        if type(current) in seen_classes:
            continue
        seen_classes.add(type(current))
        yield current
        for field in current.get_fields().values():
            if field.read_only:
                continue
            nested = field.child if isinstance(field, ListSerializer) else field
            if isinstance(nested, BaseSerializer):
                pending.append(nested)


def _guarded_serializer_names(serializer_class) -> set[str]:
    """Names of the SECRET_USE_CHECK_BY_SERIALIZER serializers in this serializer's writable tree.

    Raises:
        LookupError: The serializer cannot be bare-instantiated or its fields cannot
            be listed, and it is not one of the coverage test's KNOWN_SKIPS.
    """
    instance, error = _try_instantiate(serializer_class)
    try:
        if instance is None:
            raise error
        return {
            type(serializer).__name__
            for serializer in _writable_serializer_tree(instance)
            if type(serializer).__name__ in SECRET_USE_CHECK_BY_SERIALIZER
        }
    except Exception as introspection_error:
        if serializer_class.__name__ in KNOWN_SKIPS:
            return set()
        raise LookupError(serializer_class.__name__) from introspection_error


def _carries_secret_field(serializer_class) -> bool:
    return any(
        field_name
        for serializer in _writable_serializer_tree(serializer_class())
        for field_name in _secret_fields_of(serializer)
    )


# ---------------------------------------------------------------------------
# Every routed viewset writing a guarded serializer sets the matching check
# ---------------------------------------------------------------------------


def test_every_viewset_writing_a_guarded_serializer_sets_its_secret_use_check():
    routed = _routed_view_classes()
    problems = []
    guarded_view_names = set()

    for name, view_class in sorted(routed.items()):
        if not issubclass(view_class, GenericAPIView):
            continue
        try:
            serializer_classes = _write_serializer_classes(view_class)
        except Exception as error:
            problems.append(
                f"{name}: get_serializer_class failed for a write action ({error!r}), so its "
                "write serializers cannot be checked. Make it answer from `self.action` "
                "alone, or teach _write_serializer_classes how to call it."
            )
            continue

        direct_checks = {
            SECRET_USE_CHECK_BY_SERIALIZER[serializer_class.__name__]
            for serializer_class in serializer_classes
            if serializer_class.__name__ in SECRET_USE_CHECK_BY_SERIALIZER
        }
        writes_guarded_serializer = False
        for serializer_class in serializer_classes:
            try:
                if _guarded_serializer_names(serializer_class):
                    writes_guarded_serializer = True
            except LookupError:
                problems.append(
                    f"{name}: its serializer {serializer_class.__name__} cannot be "
                    "introspected, so a secret field in it would go unnoticed. Fix the "
                    "introspection failure, or add it to KNOWN_SKIPS in "
                    "test_secret_reference_coverage.py with a reason."
                )
        if not writes_guarded_serializer and name not in SECRET_USE_CHECK_BY_VIEWSET:
            continue
        guarded_view_names.add(name)
        if name in CUSTOM_WRITE_PATHS:
            continue

        expected_name = SECRET_USE_CHECK_BY_VIEWSET.get(name)
        if expected_name is None:
            if len(direct_checks) != 1:
                written_names = sorted(written.__name__ for written in serializer_classes)
                problems.append(
                    f"{name} writes {written_names}, which "
                    "carry or nest secret references, but no single check follows from "
                    "SECRET_USE_CHECK_BY_SERIALIZER. Set `secret_use_check` on the viewset "
                    "(SecretUseCheckedViewSetMixin) to the entity's check_<entity>_write "
                    "and add the viewset to SECRET_USE_CHECK_BY_VIEWSET, or, if its write "
                    "bypasses perform_create / perform_update, run the check there and add "
                    "it to CUSTOM_WRITE_PATHS with where it runs."
                )
                continue
            (expected_name,) = direct_checks

        actual = getattr(view_class, "secret_use_check", None)
        if actual is not getattr(secret_use_checks, expected_name, None):
            problems.append(
                f"{name}.secret_use_check is "
                f"{getattr(actual, '__name__', actual)!r}, expected {expected_name!r}. "
                "Without it the viewset writes secret references unchecked: add "
                "SecretUseCheckedViewSetMixin (before the OrgScoped* mixin) and set "
                f"`secret_use_check = {expected_name}`."
            )

    stale_by_viewset = set(SECRET_USE_CHECK_BY_VIEWSET) - set(routed)
    stale_custom = set(CUSTOM_WRITE_PATHS) - guarded_view_names
    assert not stale_by_viewset and not stale_custom, (
        "These entries name a viewset that is no longer routed (or was renamed), or, in "
        "CUSTOM_WRITE_PATHS, one that no longer writes a guarded serializer. Remove or "
        f"rename them: {sorted(stale_by_viewset | stale_custom)}"
    )
    assert not problems, "\n".join(problems)


def test_every_check_named_here_exists():
    names = {
        *SECRET_USE_CHECK_BY_VIEWSET.values(),
        *BULK_SAVE_SECRET_USE_CHECK_BY_LIST_KEY.values(),
    }
    missing = sorted(
        name for name in names if not callable(getattr(secret_use_checks, name, None))
    )

    assert not missing, (
        "These checks are not defined in tables/services/secrets/secret_use_checks.py; "
        f"rename the entries here to the function that exists: {missing}"
    )


# ---------------------------------------------------------------------------
# SecretUseCheckedViewSetMixin sits where its perform_create / perform_update run
# ---------------------------------------------------------------------------


def test_secret_use_mixin_runs_before_any_save():
    problems = []

    for name, view_class in sorted(_routed_view_classes().items()):
        if getattr(view_class, "secret_use_check", None) is None:
            continue
        mro = view_class.__mro__
        if SecretUseCheckedViewSetMixin not in mro:
            problems.append(
                f"{name} sets secret_use_check but does not inherit "
                "SecretUseCheckedViewSetMixin, so nothing calls the check. Add the mixin "
                "first in the base list."
            )
            continue
        secret_index = mro.index(SecretUseCheckedViewSetMixin)

        for org_mixin in _SAVING_ORG_SCOPED_MIXINS:
            if org_mixin in mro and mro.index(org_mixin) < secret_index:
                problems.append(
                    f"{name} lists {org_mixin.__name__} before "
                    "SecretUseCheckedViewSetMixin. Its perform_create saves without "
                    "calling super(), so the secret check never runs on create. Move "
                    "SecretUseCheckedViewSetMixin before it in the base list."
                )

        # The viewset's own overrides (mro[0]) are left to the API tests: a custom
        # perform_* there calls run_secret_use_check itself (WebhookTriggerViewSet).
        for klass in mro[1:secret_index]:
            overrides = {"perform_create", "perform_update"} & set(vars(klass))
            if overrides and klass not in DELEGATING_MIXINS_BEFORE_SECRET_CHECK:
                problems.append(
                    f"{name} lists {klass.__name__} before SecretUseCheckedViewSetMixin and "
                    f"it overrides {sorted(overrides)}, which could save before the secret "
                    "check runs. Move SecretUseCheckedViewSetMixin before it, or, if every "
                    "override calls super(), add it to "
                    "DELEGATING_MIXINS_BEFORE_SECRET_CHECK with that reason."
                )

    assert not problems, "\n".join(problems)


# ---------------------------------------------------------------------------
# Graph bulk save runs the check of every node type that carries a secret
# ---------------------------------------------------------------------------


def test_every_bulk_save_node_type_with_a_secret_field_sets_its_secret_use_check():
    problems = []
    list_keys = {config.list_key for config in NODE_TYPE_REGISTRY}

    for config in NODE_TYPE_REGISTRY:
        expected_name = BULK_SAVE_SECRET_USE_CHECK_BY_LIST_KEY.get(config.list_key)
        if expected_name is None:
            if _carries_secret_field(config.serializer_class):
                problems.append(
                    f"{config.list_key}: {config.serializer_class.__name__} writes a secret "
                    "reference but bulk save runs no secret Use check for it. Set "
                    "`secret_use_check=check_<entity>_write` on its NodeTypeConfig in "
                    "tables/services/graph_bulk_save_service/registry.py and add the list "
                    "key to BULK_SAVE_SECRET_USE_CHECK_BY_LIST_KEY."
                )
            elif config.secret_use_check is not None:
                problems.append(
                    f"{config.list_key} sets secret_use_check "
                    f"{config.secret_use_check.__name__!r} but is not in "
                    "BULK_SAVE_SECRET_USE_CHECK_BY_LIST_KEY. Add it there."
                )
            continue
        if config.secret_use_check is not getattr(secret_use_checks, expected_name, None):
            actual = getattr(config.secret_use_check, "__name__", config.secret_use_check)
            problems.append(
                f"{config.list_key}: NodeTypeConfig.secret_use_check is {actual!r}, expected "
                f"{expected_name!r}. Without it graph save writes this node's secret "
                "references unchecked."
            )

    stale = set(BULK_SAVE_SECRET_USE_CHECK_BY_LIST_KEY) - list_keys
    assert not stale, (
        "BULK_SAVE_SECRET_USE_CHECK_BY_LIST_KEY names node lists that are not in "
        f"NODE_TYPE_REGISTRY (renamed or removed); update them: {sorted(stale)}"
    )
    assert not problems, "\n".join(problems)
