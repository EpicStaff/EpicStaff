import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from rbac.authorship import UserSummarySerializer, represent_user_summary, user_summaries_by_id
from rbac.profile.avatar import build_avatar_url
from rbac.serializers.memberships import AssignableUserSerializer
from rbac.serializers.profile import ProfileResponseSerializer
from rbac.serializers.users import UserResponseSerializer

SUMMARY_KEYS = {"id", "display_name", "avatar_url"}


@pytest.fixture
def request_with_host():
    return Request(APIRequestFactory().get("/", HTTP_HOST="epicstaff.example"))


@pytest.fixture
def author(db, django_user_model):
    user = django_user_model.objects.create_user(
        email="summary-author@example.com",
        password="StrongPass123!",
        display_name="Ada Author",
        is_superadmin=True,
    )
    user.avatar.name = f"avatars/{user.id}/ada.png"
    user.save(update_fields=["avatar"])
    return user


@pytest.mark.django_db
def test_summary_exposes_only_public_identity(author, request_with_host):
    summary = represent_user_summary(author, request_with_host)

    assert summary == {
        "id": author.id,
        "display_name": "Ada Author",
        "avatar_url": f"http://epicstaff.example/media/avatars/{author.id}/ada.png",
    }
    assert set(summary) == SUMMARY_KEYS


@pytest.mark.django_db
def test_summary_without_request_has_relative_avatar_url(author):
    assert represent_user_summary(author, None)["avatar_url"] == (
        f"/media/avatars/{author.id}/ada.png"
    )


@pytest.mark.django_db
@pytest.mark.parametrize("display_name", ["", None])
def test_blank_display_name_renders_as_null_without_email_fallback(display_name, django_user_model):
    user = django_user_model.objects.create_user(
        email="nameless@example.com", password="StrongPass123!"
    )
    # `create_user` derives a name from the email; a blank one is only reachable afterwards.
    django_user_model.objects.filter(pk=user.pk).update(display_name=display_name)
    user.refresh_from_db()

    assert represent_user_summary(user, None) == {
        "id": user.id,
        "display_name": None,
        "avatar_url": None,
    }


def test_no_user_renders_as_null():
    assert represent_user_summary(None, None) is None


@pytest.mark.django_db
def test_serializer_renders_the_summary(author, request_with_host):
    data = UserSummarySerializer(author, context={"request": request_with_host}).data

    assert data == represent_user_summary(author, request_with_host)
    assert set(UserSummarySerializer().fields) == SUMMARY_KEYS


@pytest.mark.django_db
def test_summaries_by_id_load_every_user_in_one_query(author, django_user_model):
    colleague = django_user_model.objects.create_user(
        email="summary-colleague@example.com", password="StrongPass123!"
    )

    with CaptureQueriesContext(connection) as captured:
        summaries = user_summaries_by_id([author.id, colleague.id, author.id, None, 999_999], None)

    assert len(captured.captured_queries) == 1
    assert summaries == {
        author.id: represent_user_summary(author, None),
        colleague.id: {"id": colleague.id, "display_name": colleague.display_name, "avatar_url": None},
    }


@pytest.mark.django_db
def test_summaries_by_id_without_ids_issue_no_query(django_assert_num_queries):
    with django_assert_num_queries(0):
        assert user_summaries_by_id([None, None], None) == {}


# ---- the avatar URL shared with the user, profile and membership payloads ----


@pytest.mark.django_db
def test_user_payloads_render_avatar_url_like_build_avatar_url(author, request_with_host):
    expected = f"http://epicstaff.example/media/avatars/{author.id}/ada.png"
    context = {"request": request_with_host}

    assert build_avatar_url(author, request_with_host) == expected
    assert UserResponseSerializer(author, context=context).data["avatar_url"] == expected
    author._profile_memberships = []
    assert ProfileResponseSerializer(author, context=context).data["avatar_url"] == expected
    author._visible_memberships = []
    assert AssignableUserSerializer(author, context=context).data["avatar_url"] == expected


@pytest.mark.django_db
def test_avatar_url_is_none_without_avatar(django_user_model, request_with_host):
    user = django_user_model.objects.create_user(
        email="no-avatar@example.com", password="StrongPass123!"
    )

    assert build_avatar_url(user, request_with_host) is None
