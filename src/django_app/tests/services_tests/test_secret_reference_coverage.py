"""Coverage tests for secrets:USE: every Secret-writing serializer field has a secret Use check at its write point or is exempt, and the one path the design leaves ungated stays ungated."""

import pytest
from rest_framework.relations import ManyRelatedField, PrimaryKeyRelatedField
from rest_framework.serializers import BaseSerializer
from rest_framework.test import APIClient

from tables.models import Secret
from tables.models.graph_models import Graph, PythonNode
from tables.models.python_models import PythonCode
from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tables.services.secrets import secret_service
from tables.services.secrets import secret_use_checks

NEUTRAL_CODE = "def main(**kwargs):\n    return 1\n"

#: The secret Use check that gates writes of each serializer's entity, by serializer
#: class name. Serializers never check permissions themselves: the write point that
#: saves the entity (viewset, graph bulk save, service, import strategy) calls this
#: `secret_use_checks` function after validation and before the write. Subclasses are
#: listed by their own name on purpose: a new subclass is often a new request path, and
#: whoever adds one must confirm that path's write point runs the check too.
#: Whether a write point really runs its check is pinned by the API tests of each
#: endpoint family (tests/api_tests/test_secret_use_*.py), not here.
SECRET_USE_CHECK_BY_SERIALIZER: dict[str, str] = {
    "LLMConfigSerializer": "check_llm_config_write",
    "EmbeddingConfigSerializer": "check_embedding_config_write",
    "RealtimeConfigSerializer": "check_realtime_config_write",
    "RealtimeTranscriptionConfigSerializer": "check_realtime_transcription_config_write",
    "OpenAIRealtimeConfigSerializer": "check_openai_realtime_config_write",
    "ElevenLabsRealtimeConfigSerializer": "check_elevenlabs_realtime_config_write",
    "GeminiRealtimeConfigSerializer": "check_gemini_realtime_config_write",
    "TwilioChannelSerializer": "check_twilio_channel_write",
    "McpToolSerializer": "check_mcp_tool_write",
    "WebhookTriggerNestedSerializer": "check_webhook_trigger_write",
    # Renders a trigger for the realtime service's lookup_by_token; nothing is written
    # through it, and the trigger it renders is gated where it is written.
    "_WebhookTriggerInternalSerializer": "check_webhook_trigger_write",
    # Nested in WebhookTriggerNestedSerializer; the trigger check gates its token.
    "NgrokConfigInlineSerializer": "check_webhook_trigger_write",
    "TelegramTriggerNodeSerializer": "check_telegram_trigger_node_write",
    "TelegramTriggerNodeReadSerializer": "check_telegram_trigger_node_write",
    # Graph bulk save: NodeTypeConfig.secret_use_check in the bulk-save registry.
    "TelegramTriggerNodeBulkSerializer": "check_telegram_trigger_node_write",
    # Always nested: every parent's check (Python node, webhook trigger node, Python
    # code tool, classification decision table node) calls check_python_code_write.
    "PythonCodeSerializer": "check_python_code_write",
    "QuickstartSerializer": "check_quickstart",
}

#: Fields deliberately left ungated. Each entry is ("SerializerClassName", "field_name")
#: and must come with a written reason in a comment here explaining why an org-scoped
#: secrets:USE gate does not apply to it. See the RBAC backend guide section 5.6.
EXEMPT: set[tuple[str, str]] = {
    # Query input of the Twilio phone-numbers lookup, not a stored reference: nothing
    # is saved, the token is only sent to Twilio and never returned, and the id is
    # already org-scoped. The lookup is gated by voice:READ alone, as it was before the
    # id went through a serializer; requiring secrets:USE would remove the lookup from
    # the Member and Viewer roles, so it is a product decision, not made here.
    ("TwilioAuthTokenSecretSerializer", "auth_token_secret_id"),
}

#: Serializer classes it is fine for `_try_instantiate`/`_secret_fields_of` to be unable
#: to introspect: DRF's own generic abstract bases (ModelSerializer, ListSerializer,
#: HyperlinkedModelSerializer, PolymorphicProxySerializer) and this project's
#: import/export serializer bases (BaseModelImportSerializer, BaseNodeImportSerializer,
#: BaseConfigImportSerializer, BaseTagImportSerializer -- the import/export family
#: deliberately strips every Secret reference by design) and SecretUsageCountListSerializer
#: (a ListSerializer subclass requiring a `child`). None of these are ever used directly
#: with a Secret-targeting field, and none may be silently added to without this test
#: noticing: a name appearing here that is not already in this set fails the test below,
#: so a serializer that *becomes* un-instantiable (or whose get_fields() starts raising)
#: cannot silently drop out of coverage.
KNOWN_SKIPS = {
    "BaseConfigImportSerializer",
    "BaseModelImportSerializer",
    "BaseNodeImportSerializer",
    "BaseTagImportSerializer",
    "HyperlinkedModelSerializer",
    "ListSerializer",
    "ModelSerializer",
    "PolymorphicProxySerializer",
    "SecretUsageCountListSerializer",
}

#: The number of Secret-targeting field occurrences Check 1 discovers today. A floor,
#: not an exact match, so a legitimately new checked field can push it up -- but it
#: must never silently drop: moving a serializer out of tables.urls' import chain, or
#: replacing a field's `queryset=` with a `get_queryset()` override, would make the
#: walk lose a field while the "no unchecked field" assertion below stays green, and
#: this is what would catch that.
MINIMUM_DISCOVERED_SECRET_FIELDS = 17


def _all_serializer_classes():
    """Every production BaseSerializer subclass reachable once `tables.urls` has been imported."""
    from tables import urls  # noqa: F401  -- importing registers every serializer

    seen = set()
    stack = [BaseSerializer]
    while stack:
        cls = stack.pop()
        for sub in cls.__subclasses__():
            if sub not in seen:
                seen.add(sub)
                stack.append(sub)
    # `__subclasses__()` sees every serializer the interpreter has imported, which in a
    # whole-suite run includes throwaway fixtures defined inside other test modules. Those
    # are not API surface, and judging them would make this check's result depend on which
    # test files happened to be collected first -- a deliberately-unguarded fixture in a
    # sibling module would fail Check 1 below for a serializer no request can ever reach.
    return {cls for cls in seen if not cls.__module__.startswith("tests.")}


def _try_instantiate(serializer_class):
    """Bare-construct a serializer class, returning (instance, None) or (None, error) for any failure."""
    # Some serializers require constructor arguments DRF itself enforces with a plain
    # `assert` (e.g. `ListSerializer` needs `child`), which raises `AssertionError`
    # rather than `TypeError` -- both, plus any other bare-construction failure, are
    # treated the same way: skip, and make the skip visible to the caller.
    try:
        return serializer_class(), None
    except Exception as exc:
        return None, exc


def _secret_fields_of(instance):
    """Yield the names of writable fields on this serializer instance whose target is Secret."""
    # Handles both a plain `PrimaryKeyRelatedField` and the `ManyRelatedField` DRF
    # substitutes in when the field is declared with `many=True` (e.g.
    # `PythonCodeSerializer.secret_ids`) -- the real relation with `.queryset` lives
    # on `.child_relation` in that case, not on the field DRF hands back directly.
    for name, field in instance.get_fields().items():
        relation = (
            field.child_relation if isinstance(field, ManyRelatedField) else field
        )
        if not isinstance(relation, PrimaryKeyRelatedField) or relation.read_only:
            continue
        queryset = getattr(relation, "queryset", None)
        if queryset is not None and queryset.model is Secret:
            yield name


# ---------------------------------------------------------------------------
# Check 1 -- every Secret-targeting writable field has a write-point check
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_every_secret_field_has_a_secret_use_check_or_is_exempt():
    skipped = []
    discovered = []
    discovered_serializers = set()
    unchecked = []

    for serializer_class in _all_serializer_classes():
        instance, error = _try_instantiate(serializer_class)
        if instance is None:
            skipped.append(serializer_class.__name__)
            continue

        # A handful of abstract base classes bare-instantiate fine but have no
        # Meta.model, so get_fields() blows up -- treated the same as "could not
        # instantiate" (see KNOWN_SKIPS) rather than letting one abstract base fail
        # the whole test.
        try:
            fields = list(_secret_fields_of(instance))
        except Exception:
            skipped.append(serializer_class.__name__)
            continue

        serializer_name = serializer_class.__name__
        for name in fields:
            discovered.append(f"{serializer_name}.{name}")
            if (serializer_name, name) in EXEMPT:
                continue
            discovered_serializers.add(serializer_name)
            if serializer_name not in SECRET_USE_CHECK_BY_SERIALIZER:
                unchecked.append(f"{serializer_name}.{name}")

    if skipped:
        print(f"Skipped (could not bare-instantiate): {sorted(skipped)}")
    print(
        f"Secret-targeting fields discovered ({len(discovered)}): {sorted(discovered)}"
    )

    unexpected_skips = set(skipped) - KNOWN_SKIPS
    assert not unexpected_skips, (
        "These serializers could not be introspected (bare instantiation or "
        "get_fields() failed) and are not in KNOWN_SKIPS, so any Secret-targeting "
        "field they carry would silently drop out of this test's coverage. Either fix "
        "the introspection failure, or add the name to KNOWN_SKIPS with a reason it is "
        "safe to skip: " + ", ".join(sorted(unexpected_skips))
    )

    assert len(discovered) >= MINIMUM_DISCOVERED_SECRET_FIELDS, (
        f"Only {len(discovered)} Secret-targeting field(s) were discovered, below the "
        f"floor of {MINIMUM_DISCOVERED_SECRET_FIELDS}. A field the walk used to see has "
        "gone missing -- e.g. a serializer moved out of tables.urls' import chain, or a "
        "field's `queryset=` was replaced with a `get_queryset()` override -- so this "
        "test can no longer prove what it claims to: " + ", ".join(sorted(discovered))
    )

    assert not unchecked, (
        "These serializer fields write a Secret reference, but their serializer is not "
        "in SECRET_USE_CHECK_BY_SERIALIZER, so nothing shows that changing them needs "
        "secrets:USE. Add a check_<entity>_write to "
        "tables/services/secrets/secret_use_checks.py (or extend the entity's existing "
        "one), call it at every write point that saves through this serializer "
        "(SecretUseCheckedViewSetMixin.secret_use_check, run_secret_use_check, the "
        "bulk-save NodeTypeConfig.secret_use_check, or the service doing the write), "
        "then map the serializer here -- or add the field to EXEMPT with a written "
        "reason: " + ", ".join(sorted(unchecked))
    )

    stale = set(SECRET_USE_CHECK_BY_SERIALIZER) - discovered_serializers
    assert not stale, (
        "These SECRET_USE_CHECK_BY_SERIALIZER entries name a serializer that no longer "
        "has a writable Secret-targeting field (or was renamed); remove or rename "
        "them: " + ", ".join(sorted(stale))
    )


def test_every_mapped_secret_use_check_exists():
    missing = sorted(
        {
            check_name
            for check_name in SECRET_USE_CHECK_BY_SERIALIZER.values()
            if not callable(getattr(secret_use_checks, check_name, None))
        }
    )

    assert not missing, (
        "SECRET_USE_CHECK_BY_SERIALIZER maps serializers to checks that "
        "tables/services/secrets/secret_use_checks.py does not define: "
        + ", ".join(missing)
    )


# ---------------------------------------------------------------------------
# Check 2 -- the path this design deliberately leaves ungated stays ungated
# ---------------------------------------------------------------------------


def _client_with(*, org, django_user_model, email, resource_permissions):
    """An APIClient for a user whose custom role holds the given per-resource permission bitmasks."""
    role = Role.objects.create(name=f"role-{email}", org=org, is_built_in=False)
    for resource_type, bitmask in resource_permissions.items():
        RolePermission.objects.create(
            role=role, resource_type=resource_type, permissions=bitmask
        )
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def no_use_client(db, django_user_model, default_org):
    """An APIClient whose role holds READ (not USE) on secrets and READ|UPDATE on flows, what bulk save needs."""
    return _client_with(
        org=default_org,
        django_user_model=django_user_model,
        email="coverage_nouse@example.com",
        resource_permissions={
            ResourceType.SECRETS.value: int(Permission.READ),
            ResourceType.FLOWS.value: int(Permission.READ | Permission.UPDATE),
        },
    )


@pytest.fixture
def secret(default_org):
    return secret_service.create(
        text="sk-coverage", org=default_org, name="COVERAGE_KEY"
    )


@pytest.fixture
def graph(default_org):
    return Graph.objects.create(name="Coverage flow", org=default_org)


@pytest.fixture
def python_node(graph, secret):
    python_code = PythonCode.objects.create(code=NEUTRAL_CODE, entrypoint="main")
    python_code.secrets.set([secret])
    return PythonNode.objects.create(
        graph=graph, node_name="declarer", python_code=python_code
    )


@pytest.mark.django_db
class TestUngatedPathsStayUngated:
    """Bulk-save node deletion stays reachable without secrets:USE.

    It reaches PythonCode.secrets without a serializer, but only drops a declaration:
    nobody gains code that reads a secret. Copying such code and restoring a version
    that declares secrets hand the caller code they can edit and run, so both need
    secrets:USE (tests/api_tests/test_secret_use_python_code.py and
    tests/graph_versioning_tests/test_secret_declarations.py).
    """

    def test_deleting_a_declaring_node_is_allowed(
        self, no_use_client, graph, python_node
    ):
        payload = {
            "save_version": graph.save_version,
            "deleted": {"python_node_ids": [python_node.id]},
        }

        response = no_use_client.post(
            f"/api/graphs/{graph.id}/save/", payload, format="json"
        )

        assert response.status_code == 200, response.json()
        assert not PythonNode.objects.filter(pk=python_node.pk).exists()
