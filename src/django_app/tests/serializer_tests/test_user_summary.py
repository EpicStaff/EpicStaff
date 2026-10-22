import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from rbac.authorship import UserSummarySerializer, represent_user_summary, user_summaries_by_id
from rbac.profile.avatar import build_avatar_url
from rbac.serializers.memberships import AssignableUserSerializer
from rbac.serializers.profile import ProfileResponseSerializer
from rbac.serializers.users import UserResponseSerializer

SUMMARY_KEYS = {"id", "display_name", "avatar_url"}
AVATAR_VERSION = "1d2c3b4a5f6e7d8c9b0a1f2e3d4c5b6a"


@pytest.fixture
def author(db, django_user_model):
    user = django_user_model.objects.create_user(
        email="summary-author@example.com",
        password="StrongPass123!",
        display_name="Ada Author",
        is_superadmin=True,
    )
    user.avatar.name = f"avatars/{user.id}/{AVATAR_VERSION}.png"
    user.save(update_fields=["avatar"])
    return user


def expected_avatar_url(user):
    return f"/api/users/{user.id}/avatar/?v={AVATAR_VERSION}"


@pytest.mark.django_db
def test_summary_exposes_only_public_identity(author):
    summary = represent_user_summary(author)

    assert summary == {
        "id": author.id,
        "display_name": "Ada Author",
        "avatar_url": expected_avatar_url(author),
    }
    assert set(summary) == SUMMARY_KEYS


@pytest.mark.django_db
@pytest.mark.parametrize("display_name", ["", None])
def test_blank_display_name_renders_as_null_without_email_fallback(display_name, django_user_model):
    user = django_user_model.objects.create_user(
        email="nameless@example.com", password="StrongPass123!"
    )
    # `create_user` derives a name from the email; a blank one is only reachable afterwards.
    django_user_model.objects.filter(pk=user.pk).update(display_name=display_name)
    user.refresh_from_db()

    assert represent_user_summary(user) == {
        "id": user.id,
        "display_name": None,
        "avatar_url": None,
    }


def test_no_user_renders_as_null():
    assert represent_user_summary(None) is None


@pytest.mark.django_db
def test_serializer_renders_the_summary(author):
    data = UserSummarySerializer(author).data

    assert data == {"id": author.id, "display_name": "Ada Author", "avatar_url": expected_avatar_url(author)}
    assert set(UserSummarySerializer().fields) == SUMMARY_KEYS


@pytest.mark.django_db
def test_summaries_by_id_load_every_user_in_one_query(author, django_user_model):
    colleague = django_user_model.objects.create_user(
        email="summary-colleague@example.com", password="StrongPass123!"
    )

    with CaptureQueriesContext(connection) as captured:
        summaries = user_summaries_by_id([author.id, colleague.id, author.id, None, 999_999])

    assert len(captured.captured_queries) == 1
    assert summaries == {
        author.id: {"id": author.id, "display_name": "Ada Author", "avatar_url": expected_avatar_url(author)},
        colleague.id: {"id": colleague.id, "display_name": colleague.display_name, "avatar_url": None},
    }


@pytest.mark.django_db
def test_summaries_by_id_without_ids_issue_no_query(django_assert_num_queries):
    with django_assert_num_queries(0):
        assert user_summaries_by_id([None, None]) == {}


# ---- the avatar URL shared with the user, profile and membership payloads ----


@pytest.mark.django_db
def test_user_payloads_render_avatar_url_like_build_avatar_url(author):
    expected = expected_avatar_url(author)

    assert build_avatar_url(author) == expected
    assert UserResponseSerializer(author).data["avatar_url"] == expected
    author._profile_memberships = []
    assert ProfileResponseSerializer(author).data["avatar_url"] == expected
    author._visible_memberships = []
    assert AssignableUserSerializer(author).data["avatar_url"] == expected


@pytest.mark.django_db
def test_avatar_url_is_none_without_avatar(django_user_model):
    user = django_user_model.objects.create_user(
        email="no-avatar@example.com", password="StrongPass123!"
    )

    assert build_avatar_url(user) is None
