"""The view-layer glue turns secret Use denials into the field errors clients already get."""

from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser
from rbac.scoping.mixins import OrgScopedChildViewSetMixin
from rest_framework import mixins, serializers
from rest_framework.exceptions import NotFound
from rest_framework.test import APIRequestFactory
from tables.services.secrets import SecretUseDeniedError
from tables.views.secret_use import (
    SecretUseCheckedViewSetMixin,
    actor_from_request,
    denial_as_validation_error,
)
from utils.exception_handler import custom_exception_handler

_MESSAGE = "Changing the secrets referenced here requires Use."


def _envelope(error: serializers.ValidationError) -> dict:
    return custom_exception_handler(error, {}).data


def test_denial_nests_along_field_path():
    error = denial_as_validation_error(
        SecretUseDeniedError(field_path=("python_code", "secret_ids"), message=_MESSAGE)
    )

    assert error.detail == {"python_code": {"secret_ids": [_MESSAGE]}}
    assert _envelope(error) == {
        "status_code": 400,
        "code": "invalid",
        "message": f"python_code: secret_ids: {_MESSAGE}",
    }


def test_single_segment_path():
    error = denial_as_validation_error(
        SecretUseDeniedError(field_path=("api_key_secret_id",), message=_MESSAGE)
    )

    assert error.detail == {"api_key_secret_id": [_MESSAGE]}
    # Same envelope the serializer-level ValidationError({field: message}) produced.
    assert _envelope(error) == _envelope(
        serializers.ValidationError({"api_key_secret_id": _MESSAGE})
    )


@pytest.mark.parametrize(
    "incoming_request",
    [None, SimpleNamespace(user=None), SimpleNamespace(user=AnonymousUser())],
    ids=["no_request", "no_user", "anonymous_user"],
)
def test_actor_from_request_without_user_is_none(incoming_request):
    assert actor_from_request(incoming_request) is None


def test_actor_without_org_header_has_no_org():
    request = APIRequestFactory().post("/")
    request.user = SimpleNamespace(is_authenticated=True)

    actor = actor_from_request(request)

    assert actor.user is request.user
    assert actor.org_id is None


@pytest.mark.django_db
def test_actor_in_org_the_user_is_not_a_member_of_has_no_org(regular_user, default_org):
    request = APIRequestFactory().post("/", HTTP_X_ORGANIZATION_ID=str(default_org.id + 1000))
    request.user = regular_user

    assert actor_from_request(request).org_id is None


@pytest.mark.django_db
def test_actor_carries_active_org(regular_user, default_org):
    request = APIRequestFactory().post("/", HTTP_X_ORGANIZATION_ID=str(default_org.id))
    request.user = regular_user

    actor = actor_from_request(request)

    assert actor.user == regular_user
    assert actor.org_id == default_org.id


class _RecordingSerializer:
    """Stands in for a validated serializer; records when it is saved."""

    def __init__(self, log: list, *, instance=None, validated_data=None):
        self._log = log
        self.instance = instance
        self.validated_data = validated_data or {}

    def save(self, **kwargs):
        self._log.append("save")


def _viewset(check):
    attributes = {} if check is None else {"secret_use_check": check}
    viewset_class = type(
        "_ViewSet",
        (SecretUseCheckedViewSetMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin),
        attributes,
    )
    viewset = viewset_class()
    viewset.request = SimpleNamespace(user=None)
    return viewset


def _write(viewset, action, serializer):
    getattr(viewset, f"perform_{action}")(serializer)


@pytest.mark.parametrize(
    ("action", "instance"),
    [("create", None), ("update", "persisted-row")],
)
def test_mixin_runs_check_before_save(action, instance):
    log = []

    def check(actor, checked_instance, data):
        log.append(("check", actor, checked_instance, data))

    serializer = _RecordingSerializer(log, instance=instance, validated_data={"base_url": "x"})

    _write(_viewset(check), action, serializer)

    assert log == [("check", None, instance, {"base_url": "x"}), "save"]


@pytest.mark.parametrize("action", ["create", "update"])
def test_mixin_denial_blocks_save(action):
    log = []

    def check(actor, instance, data):
        raise SecretUseDeniedError(field_path=("api_key_secret_id",), message=_MESSAGE)

    with pytest.raises(serializers.ValidationError) as raised:
        _write(_viewset(check), action, _RecordingSerializer(log))

    assert raised.value.detail == {"api_key_secret_id": [_MESSAGE]}
    assert log == []


@pytest.mark.parametrize("action", ["create", "update"])
def test_mixin_without_check_fails_loudly(action):
    log = []

    with pytest.raises(NotImplementedError):
        _write(_viewset(None), action, _RecordingSerializer(log))

    assert log == []


@pytest.mark.parametrize("action", ["create", "update"])
def test_child_viewset_cross_org_parent_is_404_before_secret_check(action):
    log = []

    def check(actor, instance, data):
        log.append("check")
        raise SecretUseDeniedError(field_path=("api_key_secret_id",), message=_MESSAGE)

    viewset_class = type(
        "_ChildViewSet",
        (
            SecretUseCheckedViewSetMixin,
            OrgScopedChildViewSetMixin,
            mixins.CreateModelMixin,
            mixins.UpdateModelMixin,
        ),
        {"secret_use_check": check, "org_filter_path": "graph__org_id"},
    )
    viewset = viewset_class()
    viewset.kwargs = {}
    # The active org as HasOrgPermission leaves it cached on the request.
    viewset.request = SimpleNamespace(user=None, _rbac_active_org_id=1)
    serializer = _RecordingSerializer(
        log, validated_data={"graph": SimpleNamespace(org_id=2)}
    )

    with pytest.raises(NotFound):
        _write(viewset, action, serializer)

    assert log == []
