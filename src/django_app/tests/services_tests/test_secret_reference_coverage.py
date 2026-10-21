"""Coverage tests for the secrets:USE guard: every Secret-writing field must be gated or exempt, the paths the design leaves ungated must stay ungated, and every guarded serializer's validate() chain must actually reach the guard."""

import pytest
from rest_framework.exceptions import ValidationError
from rest_framework.relations import ManyRelatedField, PrimaryKeyRelatedField
from rest_framework.serializers import BaseSerializer
from rest_framework.test import APIClient

from tables.models import Secret
from tables.models.graph_models import Graph, PythonNode
from tables.models.python_models import PythonCode
from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tables.serializers.utils.persisted_value import PersistedValueMixin
from tables.serializers.utils.secret_reference_guard_mixin import SecretReferenceGuardMixin
from tables.serializers.utils.soft_delete_fields import KeptLinkPrimaryKeyRelatedField
from tables.services.secrets import secret_service
from tables.services.secrets.policies import SECRET_POLICIES, RowWrite, SecretPolicy
from tables.services.secrets.reference_guard import secret_reference_guard

NEUTRAL_CODE = "def main(**kwargs):\n    return 1\n"

#: Fields deliberately left ungated. Each entry is ("SerializerClassName", "field_name")
#: and must come with a written reason in a comment here explaining why an org-scoped
#: secrets:USE gate does not apply to it. A subclass that NARROWS its guarded fields by
#: setting a narrower `secret_policy` lands here too: widening a path's coverage is free,
#: but removing protection from one has to be justified in writing. See guide section 5.6.
EXEMPT: set[tuple[str, str]] = {
    # Query input of the Twilio phone-numbers lookup, not a stored reference: nothing
    # is saved, the token is only sent to Twilio and never returned, and the id is
    # already org-scoped. The lookup is gated by voice:READ alone, as it was before the
    # id went through a serializer; requiring secrets:USE would remove the lookup from
    # the Member and Viewer roles, so it is a product decision, not made here.
    ("TwilioAuthTokenSecretSerializer", "auth_token_secret_id"),
}

#: Field names whose string values the session resolver scans for
#: `epicstaff_secret(<name>)` markers (SecretResolver's header convention). A writable
#: field of this name references org secrets by name, exactly like a Secret FK.
HEADER_MARKER_FIELD_NAMES = {"extra_headers"}

#: Header-marker fields deliberately left out of a serializer's policy, each with its reason.
HEADER_EXEMPT: set[tuple[str, str]] = {
    # The import serializer is driven by LLMConfigStrategy.create_entity, which has no
    # request in serializer context; the strategy gates markers itself, passing
    # LLMConfigSecretPolicy's changes to SecretReferenceGuard
    # (tests/import_export_tests/test_import_llm_config_header_markers.py).
    ("LLMConfigImportSerializer", "extra_headers"),
}

#: Field names that set the URL a provider request -- and the secrets it carries -- is
#: sent to. A serializer writing one must have a policy that describes its destination
#: (overrides `destination` and `carries_secret`) so a secret-bearing row cannot be repointed
#: without secrets:USE. A destination reached through an FK (a config's `model`) cannot
#: be discovered by name; those serializers are pinned by name in the test below.
DESTINATION_FIELD_NAMES = {"base_url"}

#: Destination fields deliberately left out, each with its reason.
DESTINATION_EXEMPT: set[tuple[str, str]] = {
    # Import serializers only ever create rows (strategies have no update path), and the
    # destination rule gates updates only: a new row reaches a secret through a
    # reference, and imports never carry a secret FK (header markers are gated by
    # LLMConfigStrategy.create_entity).
    ("LLMConfigImportSerializer", "base_url"),
    ("LLMModelImportSerializer", "base_url"),
    ("EmbeddingModelImportSerializer", "base_url"),
    ("OpenAIRealtimeConfigImportSerializer", "base_url"),
}

#: Serializers whose destination is an FK to a row holding the base_url; the walk
#: below cannot find them by field name, so each must be shown to describe one.
FK_DESTINATION_SERIALIZERS = {"LLMConfigSerializer", "EmbeddingConfigSerializer"}

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

#: The number of Secret-targeting field occurrences Check 1 discovers today (see the
#: task report for the full inventory). A floor, not an exact match, so a legitimately
#: new guarded field can push it up -- but it must never silently drop: moving a
#: serializer out of tables.urls' import chain, or replacing a field's `queryset=` with
#: a `get_queryset()` override, would make the walk lose a field while the "no unguarded
#: field" assertion below stays green, and this is what would catch that.
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


def _policy_of(serializer_class) -> SecretPolicy | None:
    """The policy this serializer class writes under -- its own, or the one it inherits."""
    if not issubclass(serializer_class, SecretReferenceGuardMixin):
        return None
    return getattr(serializer_class, "secret_policy", None)


def _guarded_fields_of(instance):
    """The guarded FK/M2M field names of this serializer's policy, honouring a per-path policy."""
    policy = _policy_of(type(instance))
    return set(policy.reference_fields) if policy is not None else set()


def _guarded_header_fields_of(instance):
    """The guarded header-marker field names of this serializer's policy."""
    policy = _policy_of(type(instance))
    return set(policy.header_fields) if policy is not None else set()


# ---------------------------------------------------------------------------
# Check 1 -- every Secret-targeting writable field is registered
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_every_secret_field_is_guarded_or_exempt():
    skipped = []
    discovered = []
    unguarded = []

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

        guarded = _guarded_fields_of(instance)
        for name in fields:
            discovered.append(f"{serializer_class.__name__}.{name}")
            if name in guarded:
                continue
            if (serializer_class.__name__, name) in EXEMPT:
                continue
            unguarded.append(f"{serializer_class.__name__}.{name}")

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

    assert not unguarded, (
        "These serializer fields write a Secret reference but no policy guards them. "
        "Add them to the reference_fields of the owning serializer's secret_policy, "
        "or add them to EXEMPT with a written reason: "
        + ", ".join(sorted(unguarded))
    )


@pytest.mark.django_db
def test_every_header_marker_field_is_guarded_or_exempt():
    discovered = []
    unguarded = []

    for serializer_class in _all_serializer_classes():
        instance, error = _try_instantiate(serializer_class)
        if instance is None:
            continue
        try:
            fields = instance.get_fields()
        except Exception:
            # The same abstract bases Check 1 skips; it already fails on any new one.
            continue

        guarded = _guarded_header_fields_of(instance)
        for name, field in fields.items():
            if name not in HEADER_MARKER_FIELD_NAMES or field.read_only:
                continue
            discovered.append(f"{serializer_class.__name__}.{name}")
            if name in guarded or (serializer_class.__name__, name) in HEADER_EXEMPT:
                continue
            unguarded.append(f"{serializer_class.__name__}.{name}")

    assert "LLMConfigSerializer.extra_headers" in discovered, (
        "Discovery is broken: the one known header-marker field was not found, so the "
        "assertion below would pass vacuously. Found: " + ", ".join(sorted(discovered))
    )
    assert not unguarded, (
        "These writable header fields can carry epicstaff_secret(<name>) markers but are "
        "no policy guards them. Add them to the header_fields of the owning "
        "serializer's secret_policy, or to HEADER_EXEMPT with a written reason: "
        + ", ".join(sorted(unguarded))
    )


def _describes_a_destination(serializer_class) -> bool:
    policy = _policy_of(serializer_class)
    return (
        policy is not None
        and type(policy).destination is not SecretPolicy.destination
        and type(policy).carries_secret is not SecretPolicy.carries_secret
    )


@pytest.mark.django_db
def test_every_destination_field_is_guarded_or_exempt():
    discovered = []
    unguarded = []
    serializers_by_name = {}

    for serializer_class in _all_serializer_classes():
        serializers_by_name[serializer_class.__name__] = serializer_class
        instance, error = _try_instantiate(serializer_class)
        if instance is None:
            continue
        try:
            fields = instance.get_fields()
        except Exception:
            # The same abstract bases Check 1 skips; it already fails on any new one.
            continue

        for name, field in fields.items():
            if name not in DESTINATION_FIELD_NAMES or field.read_only:
                continue
            discovered.append(f"{serializer_class.__name__}.{name}")
            if (serializer_class.__name__, name) in DESTINATION_EXEMPT:
                continue
            if not _describes_a_destination(serializer_class):
                unguarded.append(f"{serializer_class.__name__}.{name}")

    for expected in (
        "LLMModelSerializer.base_url",
        "EmbeddingModelSerializer.base_url",
        "OpenAIRealtimeConfigSerializer.base_url",
    ):
        assert expected in discovered, (
            f"Discovery is broken: {expected} was not found, so the assertion below "
            "would pass vacuously. Found: " + ", ".join(sorted(discovered))
        )
    assert not unguarded, (
        "These writable fields decide where a provider request goes, but their "
        "serializer's secret_policy does not override `destination` and "
        "`carries_secret`, so a secret-bearing row can be repointed without "
        "secrets:USE. Override both, or add the field to DESTINATION_EXEMPT with a "
        "written reason: " + ", ".join(sorted(unguarded))
    )
    for name in FK_DESTINATION_SERIALIZERS:
        assert _describes_a_destination(serializers_by_name[name]), (
            f"{name} sends its secret to the base_url of the row its FK points at, "
            "but no longer describes that destination to the guard."
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "serializer_path,model_class_path,expected_routing_fields",
    [
        (
            "tables.serializers.model_serializers.llm_serializers.LLMModelSerializer",
            "tables.models.llm_models.LLMModel",
            {"name", "llm_provider", "deployment_id", "api_version", "base_url"},
        ),
        (
            "tables.serializers.model_serializers.embedding_serializers.EmbeddingModelSerializer",
            "tables.models.embedding_models.EmbeddingModel",
            {"name", "embedding_provider", "deployment", "base_url"},
        ),
    ],
)
def test_model_serializers_treat_every_routing_field_as_destination(
    serializer_path, model_class_path, expected_routing_fields
):
    """A model row's destination is every writable field but the cosmetic ones.

    Pinned by hand so that adding a writable field to these serializers forces a
    decision: it routes (update the expected set) or it is cosmetic (add it to the
    policy's non-routing set).
    """
    from django.utils.module_loading import import_string

    serializer_class = import_string(serializer_path)
    model_class = import_string(model_class_path)
    serializer = serializer_class(model_class(name="pinned"))
    # The writable fields as the serializer adapter hands them to the policy.
    write = RowWrite(
        instance=serializer.instance,
        attrs={},
        writable_fields={
            name: field.source for name, field in serializer.fields.items() if not field.read_only
        },
        persisted_value=serializer.persisted_value,
    )

    assert set(serializer.secret_policy.destination(write)) == expected_routing_fields


# ---------------------------------------------------------------------------
# Check 2 -- the paths this design deliberately leaves ungated stay ungated
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
    """An APIClient whose role holds READ (not USE) on secrets and CREATE|READ|UPDATE on flows."""
    # Flows needs CREATE because `GraphViewSet.rbac_action_map` maps `copy` to
    # `Permission.CREATE`; READ|UPDATE are what the bulk save path needs.
    return _client_with(
        org=default_org,
        django_user_model=django_user_model,
        email="coverage_nouse@example.com",
        resource_permissions={
            ResourceType.SECRETS.value: int(Permission.READ),
            ResourceType.FLOWS.value: int(
                Permission.CREATE | Permission.READ | Permission.UPDATE
            ),
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
    """copy_python_code and bulk-save node deletion must stay reachable without secrets:USE, per spec sec5."""

    # Both reach PythonCode.secrets without a serializer and reproduce or drop an
    # existing declaration inside one org rather than granting new access. Graph-version
    # restore is the third such path; it is exercised in
    # tests/graph_versioning_tests/test_secret_declarations.py rather than here.

    def test_copying_a_flow_preserves_the_declaration(
        self, no_use_client, graph, python_node, secret
    ):
        response = no_use_client.post(f"/api/graphs/{graph.id}/copy/")

        assert response.status_code in (200, 201), response.json()
        copied = Graph.objects.exclude(pk=graph.pk).order_by("-id").first()
        copied_node = copied.python_node_list.get(node_name=python_node.node_name)
        assert list(copied_node.python_code.secrets.values_list("name", flat=True)) == [
            secret.name
        ]

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


# ---------------------------------------------------------------------------
# Check 3 -- the guard is actually reachable on every guarded serializer
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_guard_is_reached_through_every_guarded_serializers_validate(mocker):
    """Every serializer that carries a secret_policy must genuinely invoke the guard through its validate() chain."""
    # Not merely listing the fields: a serializer whose own validate() overrides the
    # mixin's without calling super().validate() would pass Check 1 and look fully
    # guarded in every static inspection while the guard never runs -- that happened
    # four times in this feature (TwilioChannelSerializer, TelegramTriggerNodeSerializer,
    # QuickstartSerializer, WebhookTriggerNestedSerializer) and was found by hand. This
    # spies on the guard itself so a repeat is caught functionally.
    spy = mocker.patch.object(
        secret_reference_guard,
        "authorize_write",
        wraps=secret_reference_guard.authorize_write,
    )

    candidates = [cls for cls in _all_serializer_classes() if _policy_of(cls) is not None]

    unreached = []
    guarded_names = []

    for serializer_class in sorted(candidates, key=lambda c: c.__name__):
        instance, error = _try_instantiate(serializer_class)
        if instance is None and serializer_class.__name__ in KNOWN_SKIPS:
            continue
        if instance is None:
            # A guarded serializer that cannot even be bare-instantiated is itself a
            # failure here -- there is no way to prove its guard is reachable, and
            # silently skipping it would be exactly the kind of coverage gap this test
            # exists to prevent.
            unreached.append(
                f"{serializer_class.__name__} (could not instantiate: {error})"
            )
            continue
        guarded_names.append(serializer_class.__name__)

        spy.reset_mock()
        try:
            instance.validate({})
        except ValidationError:
            # Unrelated validation errors raised from an empty attrs dict (e.g.
            # QuickstartSerializer's "provide either api_key or
            # api_key_secret_id") are expected and irrelevant here -- only
            # whether the guard itself was reached matters. Anything else is a
            # real defect and must fail the test rather than be swallowed.
            pass

        if not spy.called:
            unreached.append(serializer_class.__name__)

    print(
        f"Guarded serializers checked ({len(guarded_names)}): {sorted(guarded_names)}"
    )

    assert guarded_names, (
        "No serializer carries a secret_policy -- discovery is broken, and every "
        "assertion below would pass vacuously."
    )

    assert not unreached, (
        "These serializers carry a secret_policy but never actually invoke the guard "
        "through their validate() chain -- almost certainly because they override "
        "validate() without calling super().validate(): " + ", ".join(sorted(unreached))
    )


# ---------------------------------------------------------------------------
# Check 4 -- the policy registry matches what the serializers use
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_every_policy_is_registered_used_and_names_real_fields():
    """SECRET_POLICIES is the complete list of policies, and each one's field names exist.

    A policy skips a field its writer does not expose (so a narrower variant can share
    it), which means a misspelt field name would skip silently on every writer. So each
    name a policy declares must be a writable field on at least one serializer using it.
    """
    # Policies compare by identity: a serializer must use the registered instance.
    serializers_by_policy: dict[SecretPolicy, list] = {}
    for serializer_class in _all_serializer_classes():
        policy = _policy_of(serializer_class)
        if policy is None:
            continue
        serializers_by_policy.setdefault(policy, []).append(serializer_class)

    unregistered = set(serializers_by_policy) - set(SECRET_POLICIES)
    assert not unregistered, (
        "These policies are used by a serializer but missing from SECRET_POLICIES: "
        + ", ".join(sorted(repr(policy) for policy in unregistered))
    )
    unused = set(SECRET_POLICIES) - set(serializers_by_policy)
    assert not unused, (
        "These registered policies are used by no serializer; delete them or wire "
        "them up: " + ", ".join(sorted(repr(policy) for policy in unused))
    )

    misnamed = []
    for policy, serializer_classes in serializers_by_policy.items():
        writable = set()
        for serializer_class in serializer_classes:
            instance, error = _try_instantiate(serializer_class)
            assert instance is not None, f"{serializer_class.__name__}: {error}"
            writable |= {name for name, field in instance.fields.items() if not field.read_only}
        declared = set(policy.reference_fields) | set(policy.header_fields)
        misnamed.extend(f"{policy!r}.{name}" for name in declared - writable)

    assert not misnamed, (
        "These policy field names are not a writable field on any serializer using the "
        "policy, so they guard nothing: " + ", ".join(sorted(misnamed))
    )


@pytest.mark.django_db
def test_every_kept_link_owner_can_say_what_it_links_to():
    """A serializer declaring a KeptLinkPrimaryKeyRelatedField must mix in PersistedValueMixin.

    The field asks its owner for the link it already holds; without the mixin it raises
    a TypeError on the first write, so catch it here instead.
    """
    owners_without_mixin = []
    for serializer_class in _all_serializer_classes():
        instance, error = _try_instantiate(serializer_class)
        if instance is None:
            continue
        try:
            fields = instance.get_fields()
        except Exception:
            # The same abstract bases Check 1 skips; it already fails on any new one.
            continue
        declares_kept_link = any(
            isinstance(
                field.child_relation if isinstance(field, ManyRelatedField) else field,
                KeptLinkPrimaryKeyRelatedField,
            )
            for field in fields.values()
        )
        if declares_kept_link and not issubclass(serializer_class, PersistedValueMixin):
            owners_without_mixin.append(serializer_class.__name__)

    assert not owners_without_mixin, (
        "These serializers declare a KeptLinkPrimaryKeyRelatedField but do not mix in "
        "PersistedValueMixin: " + ", ".join(sorted(owners_without_mixin))
    )
