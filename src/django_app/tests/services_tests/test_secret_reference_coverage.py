"""Coverage tests for the secrets:USE guard: every Secret-writing field must be gated or exempt, the paths the design leaves ungated must stay ungated, and every guarded serializer's validate() chain must actually reach the guard."""

import pytest
from rest_framework.exceptions import ValidationError
from rest_framework.relations import ManyRelatedField, PrimaryKeyRelatedField
from rest_framework.serializers import BaseSerializer
from rest_framework.test import APIClient

from tables.models import Secret
from tables.models.graph_models import Graph, PythonNode
from tables.models.python_models import PythonCode
from tables.models.rbac_models import OrganizationUser, Role, RolePermission
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.services.secrets import secret_service
from tables.services.secrets.reference_guard import secret_reference_guard

NEUTRAL_CODE = "def main(**kwargs):\n    return 1\n"

#: Fields deliberately left ungated. Each entry is ("SerializerClassName", "field_name")
#: and must come with a written reason in a comment here explaining why an org-scoped
#: secrets:USE gate does not apply to it.
EXEMPT: set[tuple[str, str]] = set()

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
    """Every BaseSerializer subclass reachable once `tables.urls` has been imported."""
    from tables import urls  # noqa: F401  -- importing registers every serializer

    seen = set()
    stack = [BaseSerializer]
    while stack:
        cls = stack.pop()
        for sub in cls.__subclasses__():
            if sub not in seen:
                seen.add(sub)
                stack.append(sub)
    return seen


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

        guarded = set(getattr(serializer_class, "secret_reference_fields", ()))
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
        "These serializer fields write a Secret reference but are not listed in any "
        "secret_reference_fields tuple. Add them to the owning serializer's "
        "secret_reference_fields, or add them to EXEMPT with a written reason: "
        + ", ".join(sorted(unguarded))
    )


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
    """Every serializer that declares or inherits a non-empty secret_reference_fields must genuinely invoke the guard through its validate() chain."""
    # Not merely listing the fields: a serializer whose own validate() overrides the
    # mixin's without calling super().validate() would pass Check 1 and look fully
    # guarded in every static inspection while the guard never runs -- that happened
    # four times in this feature (TwilioChannelSerializer, TelegramTriggerNodeSerializer,
    # QuickstartSerializer, WebhookTriggerNestedSerializer) and was found by hand. This
    # spies on the guard itself so a repeat is caught functionally.
    #
    # Uses `getattr` rather than `cls.__dict__.get(...)` so a subclass that *inherits*
    # secret_reference_fields and overrides validate() without super() is covered too --
    # `__dict__` would miss it, since it never redeclares the tuple itself.
    spy = mocker.patch.object(
        secret_reference_guard,
        "assert_unchanged_or_permitted",
        wraps=secret_reference_guard.assert_unchanged_or_permitted,
    )

    guarded_classes = [
        cls
        for cls in _all_serializer_classes()
        if getattr(cls, "secret_reference_fields", ())
    ]
    assert guarded_classes, (
        "No serializer declares secret_reference_fields -- discovery is broken."
    )

    unreached = []

    for serializer_class in sorted(guarded_classes, key=lambda c: c.__name__):
        instance, error = _try_instantiate(serializer_class)
        if instance is None:
            # A guarded serializer that cannot even be bare-instantiated is itself a
            # failure here -- there is no way to prove its guard is reachable, and
            # silently skipping it would be exactly the kind of coverage gap this test
            # exists to prevent.
            unreached.append(
                f"{serializer_class.__name__} (could not instantiate: {error})"
            )
            continue

        spy.reset_mock()
        try:
            instance.validate({})
        except ValidationError:
            # Unrelated validation errors raised from an empty attrs dict (e.g.
            # QuickstartSerializer's "provide either api_key or
            # api_key_secret_id") are expected and irrelevant here -- only
            # whether the guard itself was reached matters. Anything else --
            # e.g. the KeyError this guard used to raise for a field a
            # narrowed subclass no longer exposes -- is a real defect and
            # must fail the test rather than be swallowed.
            pass

        if not spy.called:
            unreached.append(serializer_class.__name__)

    print(
        f"Guarded serializers checked ({len(guarded_classes)}): "
        f"{sorted(c.__name__ for c in guarded_classes)}"
    )

    assert not unreached, (
        "These serializers declare or inherit secret_reference_fields but never "
        "actually invoke the guard through their validate() chain -- almost certainly "
        "because they override validate() without calling super().validate(): "
        + ", ".join(sorted(unreached))
    )
