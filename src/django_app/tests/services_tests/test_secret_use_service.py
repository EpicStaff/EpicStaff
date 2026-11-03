"""SecretUseService asks for secrets:USE only when a write changes what secrets reach where."""

import pytest
from rbac.access.effective import EffectivePermissions
from rbac.access.resolver import PermissionResolver
from rbac.models.enums import Permission, ResourceType
from tables.models import PythonCode, Secret
from tables.services.secrets import (
    SecretActor,
    SecretUseDeniedError,
    SecretUseService,
    secret_service,
)

_DENIED = (
    'Changing the secrets referenced here requires the "Use" permission on '
    "Secrets. The existing selection was left unchanged. Ask an organization "
    "admin to grant it."
)
_DESTINATION_DENIED = (
    'Changing where this sends its secrets requires the "Use" permission on '
    "Secrets. The existing value was left unchanged. Ask an organization admin "
    "to grant it."
)

_ACTOR = SecretActor(user=object(), org_id=1)


class _FakeResolver:
    """Resolves every actor to a role that holds, or lacks, secrets:USE; counts lookups."""

    def __init__(self, *, grants_use: bool):
        self._grants_use = grants_use
        self.calls = 0

    def resolve(self, user, org_id):
        self.calls += 1
        bits = int(Permission.READ | Permission.USE) if self._grants_use else int(Permission.READ)
        return EffectivePermissions(
            is_superadmin=False, role=None, by_resource={ResourceType.SECRETS.value: bits}
        )


@pytest.fixture
def without_use():
    resolver = _FakeResolver(grants_use=False)
    return resolver, SecretUseService(resolver=resolver)


@pytest.fixture
def with_use():
    resolver = _FakeResolver(grants_use=True)
    return resolver, SecretUseService(resolver=resolver)


def test_references_unchanged_needs_nothing(without_use):
    resolver, service = without_use

    service.check_references(
        _ACTOR, field_path=("api_key_secret_id",), current=Secret(pk=7), incoming=[Secret(pk=7)]
    )

    assert resolver.calls == 0


def test_references_changed_without_use_denied(without_use):
    _, service = without_use

    with pytest.raises(SecretUseDeniedError) as denied:
        service.check_references(
            _ACTOR, field_path=("api_key_secret_id",), current=Secret(pk=7), incoming=8
        )

    assert denied.value.field_path == ("api_key_secret_id",)
    assert denied.value.message == _DENIED


@pytest.mark.parametrize("cleared", [None, [], ()])
def test_references_cleared_without_use_denied(without_use, cleared):
    _, service = without_use

    with pytest.raises(SecretUseDeniedError):
        service.check_references(
            _ACTOR, field_path=("api_key_secret_id",), current=Secret(pk=7), incoming=cleared
        )


@pytest.mark.django_db
def test_references_binned_secret_counts_as_current(without_use, default_org):
    _, service = without_use
    secret = secret_service.create(text="sk-binned", org=default_org, name="BINNED_KEY")
    python_code = PythonCode.objects.create(code="def main(): pass")
    python_code.secrets.add(secret)
    secret.delete()

    service.check_references(
        _ACTOR,
        field_path=("python_code", "secret_ids"),
        current=python_code.secrets,
        incoming=[secret.pk],
    )


def test_references_changed_with_use_allowed(with_use):
    _, service = with_use

    service.check_references(
        _ACTOR, field_path=("api_key_secret_id",), current=None, incoming=Secret(pk=7)
    )


def test_markers_added_name_denied(without_use):
    _, service = without_use

    with pytest.raises(SecretUseDeniedError) as denied:
        service.check_markers(
            _ACTOR,
            field_path=("extra_headers",),
            current_headers={"X-Key": "epicstaff_secret(KEY_A)"},
            incoming_headers={
                "X-Key": "epicstaff_secret(KEY_A)",
                "X-Other": "Bearer epicstaff_secret(KEY_B)",
            },
        )

    assert denied.value.field_path == ("extra_headers",)
    assert denied.value.message == _DENIED


@pytest.mark.parametrize(
    "incoming_headers",
    [
        {"X-Key": "epicstaff_secret(KEY_A)", "X-Plain": "changed"},
        {"X-Renamed": "epicstaff_secret( KEY_A )"},
        {"X-Key": "epicstaff_secret(KEY_A)"},
        {},
        None,
    ],
    ids=["kept-with-other-edit", "kept-under-new-header", "kept-one-of-two", "all-removed", "null"],
)
def test_markers_kept_or_removed_free(without_use, incoming_headers):
    resolver, service = without_use

    service.check_markers(
        _ACTOR,
        field_path=("extra_headers",),
        current_headers={"X-Key": "epicstaff_secret(KEY_A)", "X-B": "epicstaff_secret(KEY_B)"},
        incoming_headers=incoming_headers,
    )

    assert resolver.calls == 0


def test_markers_non_dict_is_empty(without_use):
    _, service = without_use

    service.check_markers(
        _ACTOR,
        field_path=("extra_headers",),
        current_headers={"X-Key": "epicstaff_secret(KEY_A)"},
        incoming_headers=["epicstaff_secret(KEY_B)"],
    )
    with pytest.raises(SecretUseDeniedError):
        service.check_markers(
            _ACTOR,
            field_path=("extra_headers",),
            current_headers="epicstaff_secret(KEY_A)",
            incoming_headers={"X-Key": "epicstaff_secret(KEY_A)"},
        )


@pytest.mark.parametrize(
    "current, incoming",
    [
        ("https://api.openai.com/v1", "https://attacker.example"),
        (None, "https://attacker.example"),
        ("https://api.openai.com/v1", ""),
        (("https://a.example", None), ("https://a.example", "https://attacker.example")),
    ],
    ids=["replaced", "set-from-default", "reset-to-default", "one-part-of-tuple"],
)
def test_destination_change_with_secret_denied(without_use, current, incoming):
    _, service = without_use

    with pytest.raises(SecretUseDeniedError) as denied:
        service.check_destination(
            _ACTOR,
            field_path=("base_url",),
            carries_secret=True,
            current=current,
            incoming=incoming,
        )

    assert denied.value.field_path == ("base_url",)
    assert denied.value.message == _DESTINATION_DENIED


def test_destination_change_without_secret_free(without_use):
    resolver, service = without_use

    service.check_destination(
        _ACTOR,
        field_path=("base_url",),
        carries_secret=False,
        current="https://api.openai.com/v1",
        incoming="https://attacker.example",
    )

    assert resolver.calls == 0


@pytest.mark.parametrize(
    "current, incoming",
    [("", None), (None, ""), (("", "https://a.example"), (None, "https://a.example"))],
    ids=["empty-to-null", "null-to-empty", "tuple"],
)
def test_destination_empty_equals_none(without_use, current, incoming):
    resolver, service = without_use

    service.check_destination(
        _ACTOR,
        field_path=("base_url",),
        carries_secret=True,
        current=current,
        incoming=incoming,
    )

    assert resolver.calls == 0


def test_no_actor_denied_when_change_needs_use(with_use):
    _, service = with_use

    with pytest.raises(SecretUseDeniedError) as denied:
        service.check_references(
            None, field_path=("api_key_secret_id",), current=None, incoming=Secret(pk=7)
        )

    assert denied.value.field_path == ("api_key_secret_id",)


@pytest.mark.django_db
def test_non_member_actor_cannot_use(django_user_model, default_org):
    user = django_user_model.objects.create_user(
        email="secret_use_outsider@example.com", password="StrongPass123!"
    )
    service = SecretUseService(resolver=PermissionResolver())
    actor = SecretActor(user=user, org_id=default_org.id)

    assert service.may_use(actor) is False
    with pytest.raises(SecretUseDeniedError):
        service.check_references(
            actor, field_path=("api_key_secret_id",), current=None, incoming=Secret(pk=7)
        )
