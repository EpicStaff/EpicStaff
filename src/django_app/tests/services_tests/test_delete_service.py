from tables.services.rbac.rbac_exceptions import (
    DefaultOrganizationNotDeletableError,
    LastOrganizationError,
    SelfAccountDeletionError,
)


def test_default_organization_not_deletable_error_shape():
    error = DefaultOrganizationNotDeletableError()
    assert error.status_code == 400
    assert error.default_code == "default_organization_not_deletable"


def test_last_organization_error_shape():
    error = LastOrganizationError()
    assert error.status_code == 400
    assert error.default_code == "last_organization"


def test_self_account_deletion_error_shape():
    error = SelfAccountDeletionError()
    assert error.status_code == 400
    assert error.default_code == "cannot_delete_self"


import pytest

from tables.models.graph_models import Graph
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.rbac.delete.dry_run import parse_dry_run
from tables.services.rbac.delete.service import DeleteService
from tables.services.rbac.rbac_exceptions import UserNotFoundError


@pytest.fixture
def actor(db, django_user_model):
    user = django_user_model.objects.create_user(
        email="actor@x.com", password="StrongPass123!"
    )
    user.is_superadmin = True
    user.save(update_fields=["is_superadmin"])
    return user


@pytest.fixture
def target_user(db, django_user_model):
    return django_user_model.objects.create_user(
        email="target@x.com", password="StrongPass123!"
    )


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("true", True),
        ("TRUE", True),
        ("True", True),
        ("1", True),
        ("false", False),
        ("FALSE", False),
        ("0", False),
        ("", False),
        (None, False),
        ("  true  ", True),
    ],
)
def test_parse_dry_run_accepts_documented_values(raw, expected):
    assert parse_dry_run(raw) is expected


def test_parse_dry_run_rejects_garbage():
    from tables.services.rbac.rbac_exceptions import FormValidationError

    with pytest.raises(FormValidationError):
        parse_dry_run("yes")


@pytest.mark.django_db
def test_unknown_user_id_raises_not_found(db, actor):
    with pytest.raises(UserNotFoundError):
        DeleteService().delete(
            target_type="user", target_id=999999, actor=actor, dry_run=True
        )


@pytest.mark.django_db
def test_dry_run_deletes_nothing(actor, target_user):
    DeleteService().delete(
        target_type="user", target_id=target_user.pk, actor=actor, dry_run=True
    )
    target_user.refresh_from_db()
    assert target_user.pk is not None


def _row_counts() -> dict[str, int]:
    """Count the rows of every installed model through its base manager, so soft-delete filters cannot hide a row."""
    from django.apps import apps

    return {
        model._meta.label: model._base_manager.count() for model in apps.get_models()
    }


def _assert_report_matched_reality(
    predicted: dict[str, int], before: dict, after: dict
):
    """Assert every model lost exactly the rows the report predicted, and no model lost unpredicted rows."""
    for label, before_count in before.items():
        removed = before_count - after[label]
        expected = predicted.get(label, 0)
        assert removed == expected, (
            f"{label}: report predicted {expected} removed, actually removed {removed}"
        )
    assert set(predicted) <= set(before), "report named a model that does not exist"


@pytest.mark.django_db
def test_dry_run_prediction_matches_what_the_delete_actually_removes(
    actor, target_user
):
    """The load-bearing guarantee: the delete removes exactly the rows the preview predicted, and nothing else."""
    service = DeleteService()
    preview = service.delete(
        target_type="user", target_id=target_user.pk, actor=actor, dry_run=True
    )
    assert preview["dry_run"] is True

    predicted = {row["model"]: row["count"] for row in preview["database"]["by_model"]}
    before = _row_counts()

    actual = service.delete(
        target_type="user", target_id=target_user.pk, actor=actor, dry_run=False
    )
    assert actual["dry_run"] is False

    _assert_report_matched_reality(predicted, before, _row_counts())


@pytest.mark.django_db
def test_report_is_stable_across_calls(actor, target_user):
    """Two service calls against the same target report identical database and field_updates blocks."""
    service = DeleteService()
    preview = service.delete(
        target_type="user", target_id=target_user.pk, actor=actor, dry_run=True
    )
    actual = service.delete(
        target_type="user", target_id=target_user.pk, actor=actor, dry_run=False
    )
    assert preview["database"] == actual["database"]
    assert preview["field_updates"] == actual["field_updates"]


@pytest.mark.django_db
def test_real_delete_removes_the_user(actor, target_user, django_user_model):
    DeleteService().delete(
        target_type="user", target_id=target_user.pk, actor=actor, dry_run=False
    )
    assert not django_user_model.objects.filter(pk=target_user.pk).exists()


@pytest.mark.django_db
def test_deleting_a_user_preserves_their_authored_content(actor, target_user):
    org = Organization.objects.create(name="Authored Org")
    graph = Graph.objects.create(name="kept", org=org, created_by=target_user)

    DeleteService().delete(
        target_type="user", target_id=target_user.pk, actor=actor, dry_run=False
    )

    graph.refresh_from_db()
    assert graph.created_by is None


@pytest.mark.django_db
def test_deleting_a_user_removes_their_memberships(actor, target_user):
    org = Organization.objects.create(name="Membership Org")
    role = Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)
    OrganizationUser.objects.create(user=target_user, org=org, role=role)

    DeleteService().delete(
        target_type="user", target_id=target_user.pk, actor=actor, dry_run=False
    )

    assert not OrganizationUser.objects.filter(org=org).exists()


@pytest.mark.django_db
def test_cannot_delete_self(actor):
    from tables.services.rbac.rbac_exceptions import SelfAccountDeletionError

    with pytest.raises(SelfAccountDeletionError):
        DeleteService().delete(
            target_type="user", target_id=actor.pk, actor=actor, dry_run=True
        )


@pytest.mark.django_db
def test_cannot_delete_the_last_superadmin(db, django_user_model, actor):
    from tables.services.rbac.rbac_exceptions import LastSuperadminError

    other_actor = django_user_model.objects.create_user(
        email="other@x.com", password="StrongPass123!"
    )
    other_actor.is_superadmin = True
    other_actor.save(update_fields=["is_superadmin"])
    # `actor` is the only OTHER superadmin; remove it so the target is last.
    django_user_model.objects.filter(pk=actor.pk).update(is_superadmin=False)

    with pytest.raises(LastSuperadminError):
        DeleteService().delete(
            target_type="user",
            target_id=other_actor.pk,
            actor=actor,
            dry_run=True,
        )


@pytest.mark.django_db
def test_deleting_a_user_blacklists_their_refresh_tokens(actor, target_user):
    """Access tokens outlive the row by up to 15 min; refresh must not."""
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )
    from rest_framework_simplejwt.tokens import RefreshToken

    RefreshToken.for_user(target_user)
    token_ids = list(
        OutstandingToken.objects.filter(user=target_user).values_list("id", flat=True)
    )
    assert token_ids, "fixture failed to mint an outstanding token"

    DeleteService().delete(
        target_type="user", target_id=target_user.pk, actor=actor, dry_run=False
    )

    assert BlacklistedToken.objects.filter(token_id__in=token_ids).count() == len(
        token_ids
    )


@pytest.mark.django_db
def test_blocker_applies_in_real_mode_too(actor):
    from tables.services.rbac.rbac_exceptions import SelfAccountDeletionError

    with pytest.raises(SelfAccountDeletionError):
        DeleteService().delete(
            target_type="user", target_id=actor.pk, actor=actor, dry_run=False
        )


from tables.models.label_models import Label
from tables.services.rbac.rbac_exceptions import (
    OrganizationNotFoundError,
)


@pytest.fixture
def populated_org(db):
    org = Organization.objects.create(name="Doomed Org")
    Graph.objects.create(name="doomed-graph", org=org)
    Label.objects.create(name="doomed-label", org=org)
    return org


@pytest.fixture
def _surviving_org(db):
    """A second org so `populated_org` is never the last one."""
    return Organization.objects.create(name="Survivor Org")


@pytest.fixture(autouse=True)
def _no_storage_calls(mocker):
    """Storage is a network dependency; stub it for every service test."""
    backend = mocker.MagicMock()
    backend.list_all_objects.return_value = [("a.txt", 10, ""), ("b.txt", 5, "")]
    return mocker.patch(
        "tables.services.rbac.delete.organization_strategy.get_storage_backend",
        return_value=backend,
    )


@pytest.mark.django_db
def test_unknown_org_id_raises_not_found(db, actor):
    with pytest.raises(OrganizationNotFoundError):
        DeleteService().delete(
            target_type="organization",
            target_id=999999,
            actor=actor,
            dry_run=True,
        )


@pytest.mark.django_db
def test_org_dry_run_prediction_matches_what_the_delete_actually_removes(
    actor, populated_org, _surviving_org
):
    """The load-bearing guarantee: the delete removes exactly the rows the preview predicted, and nothing else."""
    service = DeleteService()
    preview = service.delete(
        target_type="organization",
        target_id=populated_org.pk,
        actor=actor,
        dry_run=True,
    )
    assert preview["dry_run"] is True

    predicted = {row["model"]: row["count"] for row in preview["database"]["by_model"]}
    before = _row_counts()

    actual = service.delete(
        target_type="organization",
        target_id=populated_org.pk,
        actor=actor,
        dry_run=False,
    )
    assert actual["dry_run"] is False

    _assert_report_matched_reality(predicted, before, _row_counts())


@pytest.mark.django_db
def test_org_report_is_stable_across_calls(actor, populated_org, _surviving_org):
    """Two service calls against the same org report identical database and field_updates blocks."""
    service = DeleteService()
    preview = service.delete(
        target_type="organization",
        target_id=populated_org.pk,
        actor=actor,
        dry_run=True,
    )
    actual = service.delete(
        target_type="organization",
        target_id=populated_org.pk,
        actor=actor,
        dry_run=False,
    )
    assert preview["database"] == actual["database"]
    assert preview["field_updates"] == actual["field_updates"]


@pytest.mark.django_db
def test_org_delete_removes_owned_rows(actor, populated_org, _surviving_org):
    DeleteService().delete(
        target_type="organization",
        target_id=populated_org.pk,
        actor=actor,
        dry_run=False,
    )
    assert not Organization.objects.filter(pk=populated_org.pk).exists()
    assert not Graph.objects.filter(org_id=populated_org.pk).exists()
    assert not Label.objects.filter(org_id=populated_org.pk).exists()


@pytest.mark.django_db
def test_org_delete_leaves_other_orgs_untouched(actor, populated_org, _surviving_org):
    keeper_graph = Graph.objects.create(name="keeper", org=_surviving_org)

    DeleteService().delete(
        target_type="organization",
        target_id=populated_org.pk,
        actor=actor,
        dry_run=False,
    )

    assert Organization.objects.filter(pk=_surviving_org.pk).exists()
    assert Graph.objects.filter(pk=keeper_graph.pk).exists()


@pytest.mark.django_db
def test_built_in_roles_survive_an_org_delete(actor, populated_org, _surviving_org):
    before = Role.objects.filter(is_built_in=True, org__isnull=True).count()
    DeleteService().delete(
        target_type="organization",
        target_id=populated_org.pk,
        actor=actor,
        dry_run=False,
    )
    assert Role.objects.filter(is_built_in=True, org__isnull=True).count() == before


@pytest.mark.django_db
def test_custom_roles_of_the_org_are_deleted(actor, populated_org, _surviving_org):
    custom = Role.objects.create(name="Custom", is_built_in=False, org=populated_org)
    DeleteService().delete(
        target_type="organization",
        target_id=populated_org.pk,
        actor=actor,
        dry_run=False,
    )
    assert not Role.objects.filter(pk=custom.pk).exists()


@pytest.mark.django_db
def test_cannot_delete_the_default_org(db, actor, _surviving_org):
    from tables.services.rbac.rbac_exceptions import (
        DefaultOrganizationNotDeletableError,
    )

    org = Organization.objects.create(name="Default Org", is_default=True)
    with pytest.raises(DefaultOrganizationNotDeletableError):
        DeleteService().delete(
            target_type="organization",
            target_id=org.pk,
            actor=actor,
            dry_run=True,
        )


@pytest.mark.django_db
def test_cannot_delete_the_last_org(db, actor):
    from tables.services.rbac.rbac_exceptions import LastOrganizationError

    Organization.objects.all().delete()
    only = Organization.objects.create(name="Only Org")
    with pytest.raises(LastOrganizationError):
        DeleteService().delete(
            target_type="organization",
            target_id=only.pk,
            actor=actor,
            dry_run=True,
        )


@pytest.mark.django_db
def test_org_report_includes_storage_totals(actor, populated_org, _surviving_org):
    report = DeleteService().delete(
        target_type="organization",
        target_id=populated_org.pk,
        actor=actor,
        dry_run=True,
    )
    storage = next(row for row in report["external"] if row["kind"] == "object_storage")
    assert storage["prefix"] == f"org_{populated_org.pk}/"
    assert storage["objects"] == 2
    assert storage["bytes"] == 15


@pytest.mark.django_db
def test_org_report_survives_storage_listing_failure(
    actor, populated_org, _surviving_org, _no_storage_calls
):
    """A `list_all_objects` failure degrades the storage row to null counts instead of raising."""
    _no_storage_calls.return_value.list_all_objects.side_effect = RuntimeError(
        "minio down"
    )

    report = DeleteService().delete(
        target_type="organization",
        target_id=populated_org.pk,
        actor=actor,
        dry_run=True,
    )

    storage = next(row for row in report["external"] if row["kind"] == "object_storage")
    assert storage["prefix"] == f"org_{populated_org.pk}/"
    assert storage["objects"] is None
    assert storage["bytes"] is None


@pytest.mark.django_db
def test_org_report_survives_storage_backend_construction_failure(
    actor, populated_org, _surviving_org, _no_storage_calls
):
    """A `get_storage_backend` construction failure also degrades to null counts instead of raising."""
    _no_storage_calls.side_effect = RuntimeError("bad credentials")

    report = DeleteService().delete(
        target_type="organization",
        target_id=populated_org.pk,
        actor=actor,
        dry_run=True,
    )

    storage = next(row for row in report["external"] if row["kind"] == "object_storage")
    assert storage["prefix"] == f"org_{populated_org.pk}/"
    assert storage["objects"] is None
    assert storage["bytes"] is None


@pytest.mark.django_db
def test_storage_purge_runs_after_a_real_delete(
    actor,
    populated_org,
    _surviving_org,
    _no_storage_calls,
    django_capture_on_commit_callbacks,
):
    with django_capture_on_commit_callbacks(execute=True):
        DeleteService().delete(
            target_type="organization",
            target_id=populated_org.pk,
            actor=actor,
            dry_run=False,
        )
    _no_storage_calls.return_value.delete_prefix.assert_called_once_with("")


@pytest.mark.django_db
def test_storage_failure_does_not_undo_the_delete(
    actor,
    populated_org,
    _surviving_org,
    _no_storage_calls,
    django_capture_on_commit_callbacks,
):
    _no_storage_calls.return_value.delete_prefix.side_effect = RuntimeError(
        "minio down"
    )

    with django_capture_on_commit_callbacks(execute=True):
        DeleteService().delete(
            target_type="organization",
            target_id=populated_org.pk,
            actor=actor,
            dry_run=False,
        )

    assert not Organization.objects.filter(pk=populated_org.pk).exists()


@pytest.mark.django_db
def test_org_blocker_applies_in_real_mode_too(db, actor, _surviving_org):
    from tables.services.rbac.rbac_exceptions import (
        DefaultOrganizationNotDeletableError,
    )

    org = Organization.objects.create(name="Default Org", is_default=True)
    with pytest.raises(DefaultOrganizationNotDeletableError):
        DeleteService().delete(
            target_type="organization",
            target_id=org.pk,
            actor=actor,
            dry_run=False,
        )


@pytest.mark.django_db
def test_locked_revalidation_refuses_the_last_superadmin(db, django_user_model, actor):
    """The in-transaction re-check raises even when the unlocked guard already passed."""
    from tables.services.rbac.delete.user_strategy import UserDeleteStrategy
    from tables.services.rbac.rbac_exceptions import LastSuperadminError

    django_user_model.objects.filter(is_superadmin=True).exclude(pk=actor.pk).update(
        is_superadmin=False
    )

    with pytest.raises(LastSuperadminError):
        UserDeleteStrategy().validate_locked(actor, actor=actor)


@pytest.mark.django_db
def test_locked_revalidation_allows_a_user_who_is_not_the_last_superadmin(
    db, django_user_model, actor, target_user
):
    """A non-superadmin target passes the locked re-check."""
    from tables.services.rbac.delete.user_strategy import UserDeleteStrategy

    assert UserDeleteStrategy().validate_locked(target_user, actor=actor) is None


@pytest.mark.django_db
def test_locked_revalidation_refuses_the_default_org(db, actor, _surviving_org):
    """The in-transaction re-check refuses the default organization."""
    from tables.services.rbac.delete.organization_strategy import (
        OrganizationDeleteStrategy,
    )
    from tables.services.rbac.rbac_exceptions import (
        DefaultOrganizationNotDeletableError,
    )

    org = Organization.objects.create(name="Locked Default Org", is_default=True)
    with pytest.raises(DefaultOrganizationNotDeletableError):
        OrganizationDeleteStrategy().validate_locked(org, actor=actor)


@pytest.mark.django_db
def test_locked_revalidation_refuses_the_last_org(db, actor):
    """The in-transaction re-check refuses the last remaining organization."""
    from tables.services.rbac.delete.organization_strategy import (
        OrganizationDeleteStrategy,
    )
    from tables.services.rbac.rbac_exceptions import LastOrganizationError

    Organization.objects.all().delete()
    only = Organization.objects.create(name="Locked Only Org")
    with pytest.raises(LastOrganizationError):
        OrganizationDeleteStrategy().validate_locked(only, actor=actor)


@pytest.mark.django_db
def test_locked_revalidation_allows_a_deletable_org(
    db, actor, populated_org, _surviving_org
):
    """A non-default organization with a neighbour passes the locked re-check."""
    from tables.services.rbac.delete.organization_strategy import (
        OrganizationDeleteStrategy,
    )

    assert (
        OrganizationDeleteStrategy().validate_locked(populated_org, actor=actor) is None
    )


@pytest.mark.django_db
def test_storage_purge_does_not_short_circuit_on_a_folder_marker(
    mocker,
    actor,
    populated_org,
    _surviving_org,
    _no_storage_calls,
    django_capture_on_commit_callbacks,
):
    """A zero-byte `org_{id}/` marker must not divert the purge into a single-object delete."""
    from datetime import datetime, timezone
    from unittest.mock import patch

    from tables.services.storage_service.s3_backend import S3StorageBackend

    prefix = f"org_{populated_org.pk}/"
    with patch("tables.services.storage_service.s3_backend.boto3"):
        backend = S3StorageBackend(
            bucket_name="test",
            access_key="k",
            secret_key="s",
            organization_prefix=prefix,
            endpoint_url=None,
        )
    backend.client = mocker.MagicMock()
    # head_object succeeding is exactly the case that used to swallow the purge.
    backend.client.head_object.return_value = {"ContentLength": 0}
    paginator = mocker.MagicMock()
    paginator.paginate.return_value = [
        {
            "Contents": [
                {"Key": prefix, "Size": 0, "LastModified": datetime.now(timezone.utc)},
                {
                    "Key": f"{prefix}a.txt",
                    "Size": 10,
                    "LastModified": datetime.now(timezone.utc),
                },
            ]
        }
    ]
    backend.client.get_paginator.return_value = paginator
    _no_storage_calls.return_value = backend

    with django_capture_on_commit_callbacks(execute=True):
        DeleteService().delete(
            target_type="organization",
            target_id=populated_org.pk,
            actor=actor,
            dry_run=False,
        )

    backend.client.delete_object.assert_not_called()
    deleted_keys = {
        entry["Key"]
        for call in backend.client.delete_objects.call_args_list
        for entry in call.kwargs["Delete"]["Objects"]
    }
    assert deleted_keys == {prefix, f"{prefix}a.txt"}


@pytest.mark.django_db
def test_org_delete_clears_the_platform_default_config_cache(
    actor, populated_org, _surviving_org, django_capture_on_commit_callbacks
):
    """Platform defaults pointing at the org's configs are nulled, and the process cache stops serving the dead row."""
    from tables.models.base_models import DefaultBaseModel
    from tables.models.default_models import DefaultModels
    from tables.models.llm_models import LLMConfig

    config = LLMConfig.objects.create(custom_name="doomed-llm", org=populated_org)
    defaults = DefaultModels.load()
    defaults.agent_llm_config = config
    defaults.save()
    assert DefaultModels.load().agent_llm_config_id == config.pk

    with django_capture_on_commit_callbacks(execute=True):
        DeleteService().delete(
            target_type="organization",
            target_id=populated_org.pk,
            actor=actor,
            dry_run=False,
        )

    assert not LLMConfig.objects.filter(pk=config.pk).exists()
    assert DefaultModels.objects.get(pk=1).agent_llm_config_id is None
    assert DefaultModels not in DefaultBaseModel._load_cache
    assert DefaultModels.load().agent_llm_config_id is None


@pytest.mark.django_db
def test_user_avatar_is_previewed_and_removed_from_disk(
    actor, target_user, settings, tmp_path, django_capture_on_commit_callbacks
):
    """The avatar lives on local disk, not in MinIO: the report names it and the real delete removes the file."""
    from pathlib import Path

    from django.core.files.uploadedfile import SimpleUploadedFile

    settings.MEDIA_ROOT = str(tmp_path)
    target_user.avatar.save(
        "face.png", SimpleUploadedFile("face.png", b"fake-image-bytes"), save=True
    )
    avatar_name = target_user.avatar.name
    stored = Path(settings.MEDIA_ROOT) / avatar_name
    assert stored.exists(), "fixture failed to write the avatar"

    service = DeleteService()
    preview = service.delete(
        target_type="user", target_id=target_user.pk, actor=actor, dry_run=True
    )
    assert {"kind": "avatar", "path": avatar_name} in preview["external"]
    assert stored.exists(), "a dry run must not touch the file"

    with django_capture_on_commit_callbacks(execute=True):
        service.delete(
            target_type="user", target_id=target_user.pk, actor=actor, dry_run=False
        )

    assert not stored.exists()
