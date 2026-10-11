import pytest
from django.contrib.contenttypes.models import ContentType
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from rbac.authorship import AuthorStampingSerializerMixin
from rbac.identity.api_keys.principals import SystemServicePrincipal
from rbac.models import ResourceLastEdit
from tables.models import Graph, GraphNote, Label

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


class LabelAuthorSerializer(AuthorStampingSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = Label
        fields = ["id", "name", "org", "created_by"]


class GraphNoteAuthorSerializer(AuthorStampingSerializerMixin, serializers.ModelSerializer):
    """A last-edit tracked model, so an update records who edited it."""

    class Meta:
        model = GraphNote
        fields = ["id", "graph", "content", "metadata", "created_by"]


class LabelBodyMethodsSerializer(AuthorStampingSerializerMixin, serializers.ModelSerializer):
    """Defines create/update in its own body without calling super, like the trigger serializers."""

    class Meta:
        model = Label
        fields = ["id", "name", "org", "created_by"]

    def create(self, validated_data):
        return Label.objects.create(**validated_data)

    def update(self, instance, validated_data):
        for attribute, value in validated_data.items():
            setattr(instance, attribute, value)
        instance.save()
        return instance


class LabelBodySuperSerializer(AuthorStampingSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = Label
        fields = ["id", "name", "org", "created_by"]

    def create(self, validated_data):
        return super().create(validated_data)

    def update(self, instance, validated_data):
        return super().update(instance, validated_data)


class LabelBodySuperChildSerializer(LabelBodySuperSerializer):
    def create(self, validated_data):
        return super().create(validated_data)

    def update(self, instance, validated_data):
        return super().update(instance, validated_data)


class LabelMixinLastSerializer(serializers.ModelSerializer, AuthorStampingSerializerMixin):
    class Meta:
        model = Label
        fields = ["id", "name", "org", "created_by"]


class _LabelService:
    def create_label(self, **fields):
        return Label.objects.create(**fields)

    def rename_label(self, label, name, **fields):
        for attribute, value in fields.items():
            setattr(label, attribute, value)
        label.name = name
        label.save()
        return label


class PlainServiceLabelSerializer(AuthorStampingSerializerMixin, serializers.Serializer):
    name = serializers.CharField()
    org_id = serializers.IntegerField(required=False)

    def create(self, validated_data):
        return _LabelService().create_label(**validated_data)

    def update(self, instance, validated_data):
        return _LabelService().rename_label(instance, **validated_data)


@pytest.fixture
def author(db, django_user_model):
    return django_user_model.objects.create_user(
        email="author-serializer@example.com", password="StrongPass123!"
    )


@pytest.fixture
def other_user(db, django_user_model):
    return django_user_model.objects.create_user(
        email="other-serializer@example.com", password="StrongPass123!"
    )


def _context_for(user):
    request = Request(APIRequestFactory().post("/"))
    request.user = user
    return {"request": request}


@pytest.mark.django_db
def test_created_by_field_is_read_only():
    field = LabelAuthorSerializer().fields["created_by"]

    assert field.read_only is True


@pytest.mark.django_db
def test_create_stamps_request_user(acme, author):
    serializer = LabelAuthorSerializer(
        data={"name": "stamped", "org": acme.id}, context=_context_for(author)
    )
    serializer.is_valid(raise_exception=True)
    label = serializer.save()

    assert Label.objects.get(pk=label.pk).created_by_id == author.id
    assert serializer.data["created_by"] == author.id


@pytest.mark.django_db
def test_create_ignores_client_supplied_author(acme, author, other_user):
    serializer = LabelAuthorSerializer(
        data={"name": "spoofed", "org": acme.id, "created_by": other_user.id},
        context=_context_for(author),
    )
    serializer.is_valid(raise_exception=True)
    label = serializer.save()

    assert Label.objects.get(pk=label.pk).created_by_id == author.id


@pytest.mark.django_db
def test_create_without_request_falls_back_to_explicit_author(acme, author):
    serializer = LabelAuthorSerializer(data={"name": "explicit", "org": acme.id})
    serializer.is_valid(raise_exception=True)
    label = serializer.save(created_by=author)

    assert Label.objects.get(pk=label.pk).created_by_id == author.id


@pytest.mark.django_db
def test_create_prefers_request_user_over_explicit_author(acme, author, other_user):
    serializer = LabelAuthorSerializer(
        data={"name": "request-wins", "org": acme.id}, context=_context_for(author)
    )
    serializer.is_valid(raise_exception=True)
    label = serializer.save(created_by=other_user)

    assert Label.objects.get(pk=label.pk).created_by_id == author.id


@pytest.mark.django_db
def test_create_by_system_principal_leaves_no_author(acme):
    principal = SystemServicePrincipal()
    serializer = LabelAuthorSerializer(
        data={"name": "system", "org": acme.id}, context=_context_for(principal)
    )
    serializer.is_valid(raise_exception=True)
    label = serializer.save(created_by=principal)

    assert Label.objects.get(pk=label.pk).created_by_id is None


@pytest.mark.django_db
def test_update_leaves_row_without_author_unauthored(acme, author):
    label = Label.objects.create(name="unauthored", org=acme)
    serializer = LabelAuthorSerializer(
        label, data={"name": "edited-unauthored"}, partial=True, context=_context_for(author)
    )
    serializer.is_valid(raise_exception=True)
    serializer.save()

    stored = Label.objects.get(pk=label.pk)
    assert stored.name == "edited-unauthored"
    assert stored.created_by_id is None


def _last_editor_id(instance) -> int | None:
    return ResourceLastEdit.objects.get(
        content_type=ContentType.objects.get_for_model(instance), object_id=instance.pk
    ).edited_by_id


@pytest.mark.django_db
def test_update_records_explicit_author_as_editor_but_not_as_author(acme, author):
    note = GraphNote.objects.create(graph=Graph.objects.create(name="flow", org=acme))
    serializer = GraphNoteAuthorSerializer(note, data={"content": "explicit-edit"}, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save(created_by=author)

    stored = GraphNote.objects.get(pk=note.pk)
    assert stored.content == "explicit-edit"
    assert stored.created_by_id is None
    assert _last_editor_id(stored) == author.id


@pytest.mark.django_db
def test_update_records_explicit_author_as_editor_and_keeps_existing_author(
    acme, author, other_user
):
    note = GraphNote.objects.create(
        graph=Graph.objects.create(name="flow", org=acme), created_by=author
    )
    serializer = GraphNoteAuthorSerializer(
        note, data={"content": "explicit-owned-edit"}, partial=True
    )
    serializer.is_valid(raise_exception=True)
    serializer.save(created_by=other_user)

    stored = GraphNote.objects.get(pk=note.pk)
    assert stored.created_by_id == author.id
    assert _last_editor_id(stored) == other_user.id


@pytest.mark.django_db
def test_update_keeps_existing_author(acme, author, other_user):
    label = Label.objects.create(name="owned", org=acme, created_by=author)
    serializer = LabelAuthorSerializer(
        label,
        data={"name": "edited", "created_by": other_user.id},
        partial=True,
        context=_context_for(other_user),
    )
    serializer.is_valid(raise_exception=True)
    serializer.save()

    stored = Label.objects.get(pk=label.pk)
    assert stored.name == "edited"
    assert stored.created_by_id == author.id


@pytest.mark.django_db
def test_update_by_system_principal_leaves_row_without_author(acme):
    label = Label.objects.create(name="unowned", org=acme)
    serializer = LabelAuthorSerializer(
        label,
        data={"name": "system-edit"},
        partial=True,
        context=_context_for(SystemServicePrincipal()),
    )
    serializer.is_valid(raise_exception=True)
    serializer.save()

    assert Label.objects.get(pk=label.pk).created_by_id is None


STAMPING_LAYOUTS = [
    LabelAuthorSerializer,
    LabelBodyMethodsSerializer,
    LabelBodySuperSerializer,
    LabelBodySuperChildSerializer,
    LabelMixinLastSerializer,
]
LAYOUT_IDS = ["mixin-only", "body-no-super", "body-super", "body-super-child", "mixin-last"]


@pytest.mark.django_db
@pytest.mark.parametrize("serializer_class", STAMPING_LAYOUTS, ids=LAYOUT_IDS)
def test_every_layout_keeps_created_by_read_only(serializer_class):
    assert serializer_class().fields["created_by"].read_only is True


@pytest.mark.django_db
@pytest.mark.parametrize("serializer_class", STAMPING_LAYOUTS, ids=LAYOUT_IDS)
def test_every_layout_stamps_request_user_on_create(
    serializer_class, acme, author, other_user
):
    serializer = serializer_class(
        data={"name": "layout-create", "org": acme.id, "created_by": other_user.id},
        context=_context_for(author),
    )
    serializer.is_valid(raise_exception=True)
    label = serializer.save()

    assert Label.objects.get(pk=label.pk).created_by_id == author.id


@pytest.mark.django_db
@pytest.mark.parametrize("serializer_class", STAMPING_LAYOUTS, ids=LAYOUT_IDS)
def test_every_layout_leaves_row_without_author_unauthored_on_update(
    serializer_class, acme, author
):
    label = Label.objects.create(name="layout-unauthored", org=acme)
    serializer = serializer_class(
        label,
        data={"name": "layout-edited-unauthored", "created_by": author.id},
        partial=True,
        context=_context_for(author),
    )
    serializer.is_valid(raise_exception=True)
    serializer.save(created_by=author)

    stored = Label.objects.get(pk=label.pk)
    assert stored.name == "layout-edited-unauthored"
    assert stored.created_by_id is None


@pytest.mark.django_db
@pytest.mark.parametrize("serializer_class", STAMPING_LAYOUTS, ids=LAYOUT_IDS)
def test_every_layout_keeps_existing_author_on_update(
    serializer_class, acme, author, other_user
):
    label = Label.objects.create(name="layout-owned", org=acme, created_by=author)
    serializer = serializer_class(
        label,
        data={"name": "layout-edited", "created_by": other_user.id},
        partial=True,
        context=_context_for(other_user),
    )
    serializer.is_valid(raise_exception=True)
    serializer.save()

    assert Label.objects.get(pk=label.pk).created_by_id == author.id


@pytest.mark.django_db
@pytest.mark.parametrize("serializer_class", STAMPING_LAYOUTS, ids=LAYOUT_IDS)
def test_direct_create_call_stamps_request_user(serializer_class, acme, author):
    serializer = serializer_class(
        data={"name": "direct-create", "org": acme.id}, context=_context_for(author)
    )
    serializer.is_valid(raise_exception=True)
    label = serializer.create(dict(serializer.validated_data))

    assert Label.objects.get(pk=label.pk).created_by_id == author.id


@pytest.mark.django_db
@pytest.mark.parametrize("serializer_class", STAMPING_LAYOUTS, ids=LAYOUT_IDS)
def test_direct_update_call_leaves_row_without_author_unauthored(
    serializer_class, acme, author
):
    label = Label.objects.create(name="direct-unauthored", org=acme)
    serializer = serializer_class(
        label, data={"name": "direct-edited"}, partial=True, context=_context_for(author)
    )
    serializer.is_valid(raise_exception=True)
    serializer.update(label, {**serializer.validated_data, "created_by": author})

    stored = Label.objects.get(pk=label.pk)
    assert stored.name == "direct-edited"
    assert stored.created_by_id is None


@pytest.mark.django_db
def test_plain_serializer_passes_author_to_service_on_create(acme, author):
    serializer = PlainServiceLabelSerializer(
        data={"name": "plain", "org_id": acme.id}, context=_context_for(author)
    )
    serializer.is_valid(raise_exception=True)
    label = serializer.save()

    assert Label.objects.get(pk=label.pk).created_by_id == author.id


@pytest.mark.django_db
def test_plain_serializer_direct_create_call_passes_author(acme, author):
    serializer = PlainServiceLabelSerializer(context=_context_for(author))

    label = serializer.create({"name": "plain-direct", "org_id": acme.id})

    assert Label.objects.get(pk=label.pk).created_by_id == author.id


@pytest.mark.django_db
def test_plain_serializer_update_leaves_row_without_author_unauthored(acme, author):
    label = Label.objects.create(name="plain-unauthored", org=acme)
    serializer = PlainServiceLabelSerializer(context=_context_for(author))

    serializer.update(label, {"name": "plain-edited-unauthored", "created_by": author})

    stored = Label.objects.get(pk=label.pk)
    assert stored.name == "plain-edited-unauthored"
    assert stored.created_by_id is None


@pytest.mark.django_db
def test_plain_serializer_update_keeps_existing_author(acme, author, other_user):
    label = Label.objects.create(name="plain-owned", org=acme, created_by=author)
    serializer = PlainServiceLabelSerializer(context=_context_for(other_user))

    serializer.update(label, {"name": "plain-edited", "created_by": other_user})

    assert Label.objects.get(pk=label.pk).created_by_id == author.id
