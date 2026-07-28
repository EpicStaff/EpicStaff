import pytest
from django.db import IntegrityError, transaction

from tables.models import Secret
from tables.models.rbac_models import Organization
from tables.services.secrets import secret_cipher


@pytest.mark.django_db
def test_duplicate_name_same_org_raises_integrity_error(default_org):
    Secret.objects.create(name="OPENAI_KEY", value="ciphertext-a", org=default_org)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Secret.objects.create(
                name="OPENAI_KEY", value="ciphertext-b", org=default_org
            )


@pytest.mark.django_db
def test_duplicate_name_different_org_is_allowed(default_org):
    other_org = Organization.objects.create(name="Other Org")
    Secret.objects.create(name="OPENAI_KEY", value="ciphertext-a", org=default_org)
    # Must not raise — same name, different org.
    Secret.objects.create(name="OPENAI_KEY", value="ciphertext-b", org=other_org)


@pytest.mark.django_db
def test_name_uniqueness_is_case_sensitive(default_org):
    Secret.objects.create(name="OPENAI_KEY", value="ciphertext-a", org=default_org)
    # Different case is a distinct secret — must not raise.
    Secret.objects.create(name="openai_key", value="ciphertext-b", org=default_org)


@pytest.mark.django_db
def test_org_is_required_at_db_layer():
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Secret.objects.create(name="NO_ORG", value="ciphertext", org=None)


@pytest.mark.django_db
def test_empty_value_raises_integrity_error(default_org):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Secret.objects.create(name="EMPTY_VALUE", value="", org=default_org)


@pytest.mark.django_db
def test_metadata_defaults_to_empty_dict(default_org):
    secret = Secret.objects.create(
        name="WITH_DEFAULTS", value="ciphertext", org=default_org
    )
    assert secret.metadata == {}


@pytest.mark.django_db
def test_seal_and_persist_round_trips_through_the_database(default_org):
    plaintext = "sk-live-51H8xJ2eZvKYlo2C0X9F3q7R"
    secret = Secret(name="ROUND_TRIP", org=default_org)
    secret_cipher.seal(plaintext=plaintext).write_to(secret)
    secret.save()

    reloaded = Secret.objects.get(pk=secret.pk)
    assert secret_cipher.open(ciphertext=reloaded.value) == plaintext
    assert reloaded.tail == plaintext[-4:]
