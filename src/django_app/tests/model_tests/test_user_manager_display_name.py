import pytest
from django.contrib.auth import get_user_model

UserModel = get_user_model()

OMITTED = object()


@pytest.mark.django_db
@pytest.mark.parametrize("create_method", ["create_user", "create_superuser"])
@pytest.mark.parametrize(
    ("email", "display_name", "expected"),
    [
        ("john.smith@acme.com", OMITTED, "John Smith"),
        ("mary_ann@acme.com", None, "Mary Ann"),
        ("mary_ann@acme.com", "", "Mary Ann"),
        ("mary_ann@acme.com", "   ", "Mary Ann"),
        ("mary_ann@acme.com", "\t\n", "Mary Ann"),
        ("john.smith@acme.com", "Jane", "Jane"),
        # An explicit name is stored exactly as given.
        ("john.smith@acme.com", "  Jane  ", "  Jane  "),
        # Derived after the email's domain is normalised.
        ("John.Smith@ACME.COM", OMITTED, "John Smith"),
    ],
    ids=["omitted", "none", "empty", "spaces", "whitespace", "explicit", "explicit-untrimmed", "mixed-case-email"],
)
def test_a_missing_display_name_is_derived_from_the_email(create_method, email, display_name, expected):
    extra = {} if display_name is OMITTED else {"display_name": display_name}

    user = getattr(UserModel.objects, create_method)(email=email, password="StrongPass123!", **extra)

    user.refresh_from_db()
    assert user.display_name == expected
