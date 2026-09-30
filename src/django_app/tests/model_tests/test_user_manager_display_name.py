import pytest
from django.contrib.auth import get_user_model

UserModel = get_user_model()

PASSWORD = "StrongPass123!"


@pytest.mark.django_db
@pytest.mark.parametrize("create_method", ["create_user", "create_superuser"])
def test_display_name_derived_from_email_when_omitted(create_method):
    user = getattr(UserModel.objects, create_method)(
        email="john.smith@acme.com", password=PASSWORD
    )

    user.refresh_from_db()
    assert user.display_name == "John Smith"


@pytest.mark.django_db
@pytest.mark.parametrize("create_method", ["create_user", "create_superuser"])
@pytest.mark.parametrize("blank_display_name", [None, "", "   ", "\t\n"])
def test_display_name_derived_from_email_when_blank(create_method, blank_display_name):
    user = getattr(UserModel.objects, create_method)(
        email="mary_ann@acme.com",
        password=PASSWORD,
        display_name=blank_display_name,
    )

    user.refresh_from_db()
    assert user.display_name == "Mary Ann"


@pytest.mark.django_db
@pytest.mark.parametrize("create_method", ["create_user", "create_superuser"])
def test_explicit_display_name_is_kept(create_method):
    user = getattr(UserModel.objects, create_method)(
        email="john.smith@acme.com", password=PASSWORD, display_name="Jane"
    )

    user.refresh_from_db()
    assert user.display_name == "Jane"


@pytest.mark.django_db
def test_explicit_display_name_is_kept_untrimmed():
    user = UserModel.objects.create_user(
        email="john.smith@acme.com", password=PASSWORD, display_name="  Jane  "
    )

    user.refresh_from_db()
    assert user.display_name == "  Jane  "


@pytest.mark.django_db
def test_display_name_derived_after_email_domain_normalization():
    user = UserModel.objects.create_user(email="John.Smith@ACME.COM", password=PASSWORD)

    user.refresh_from_db()
    assert user.email == "John.Smith@acme.com"
    assert user.display_name == "John Smith"
