"""A new password resembling the account's own email is rejected on every flow.

The request validators run before the account is known, so this check lives in
`PasswordWriter`. Each flow must answer with the usual 400 on `new_password`
and leave everything untouched: the old password still works, the reset link
or change ticket can be retried, and no credential is revoked.
"""

import io

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

from rbac.identity.passwords.token_repository import PasswordResetTokenRepository
from rbac.models import PasswordResetToken

ACCOUNT_EMAIL = "jane.doe.kowalska@example.com"
ORIGINAL_PASSWORD = "OriginalPass123!"
STRONG_PASSWORD = "BrandNewPass456!"
SIMILARITY_REASON = "The password is too similar to the email."

# The exact email, and the email without its top-level domain (quick_ratio
# 0.93, well over Django's 0.7 threshold).
PASSWORDS_LIKE_THE_EMAIL = [ACCOUNT_EMAIL, "Jane.Doe.Kowalska@example"]


@pytest.fixture
def account(db):
    return get_user_model().objects.create_user(email=ACCOUNT_EMAIL, password=ORIGINAL_PASSWORD)


@pytest.fixture
def live_credentials(account, issue_api_key):
    """A refresh token and a personal API key the account holds before the attempt."""
    RefreshToken.for_user(account)
    _, api_key = issue_api_key(user=account)
    return api_key


@pytest.fixture
def superadmin_client(superadmin_user):
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(superadmin_user).access_token}"
    )
    return client


def _assert_rejected_for_similarity(response):
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "invalid"
    assert {"field": "new_password", "value": "***", "reason": SIMILARITY_REASON} in body[
        "errors"
    ]


def _assert_account_untouched(account, api_key):
    account.refresh_from_db()
    assert account.check_password(ORIGINAL_PASSWORD)
    assert not BlacklistedToken.objects.filter(token__user=account).exists()
    api_key.refresh_from_db()
    assert api_key.revoked_at is None


@pytest.mark.django_db
@pytest.mark.parametrize("new_password", PASSWORDS_LIKE_THE_EMAIL)
def test_reset_confirm_rejects_password_like_email_and_keeps_token(
    api_client, account, live_credentials, new_password
):
    token, raw_token = PasswordResetTokenRepository().create_for_user(account)

    response = api_client.post(
        reverse("password_reset_confirm"),
        data={"token": raw_token, "new_password": new_password},
        format="json",
    )

    _assert_rejected_for_similarity(response)
    _assert_account_untouched(account, live_credentials)
    assert PasswordResetToken.objects.filter(pk=token.pk).exists()

    retry = api_client.post(
        reverse("password_reset_confirm"),
        data={"token": raw_token, "new_password": STRONG_PASSWORD},
        format="json",
    )

    assert retry.status_code == 200
    account.refresh_from_db()
    assert account.check_password(STRONG_PASSWORD)


@pytest.mark.django_db
def test_admin_reset_rejects_password_like_email_and_changes_nothing(
    superadmin_client, account, live_credentials
):
    pending_token, _ = PasswordResetTokenRepository().create_for_user(account)

    response = superadmin_client.post(
        reverse("admin_password_reset"),
        data={"user_id": account.id, "new_password": ACCOUNT_EMAIL},
        format="json",
    )

    _assert_rejected_for_similarity(response)
    _assert_account_untouched(account, live_credentials)
    # The pending reset link is invalidated only on success.
    assert PasswordResetToken.objects.filter(pk=pending_token.pk).exists()


@pytest.mark.django_db
def test_admin_reset_accepts_a_strong_password(superadmin_client, account):
    response = superadmin_client.post(
        reverse("admin_password_reset"),
        data={"user_id": account.id, "new_password": STRONG_PASSWORD},
        format="json",
    )

    assert response.status_code == 204
    account.refresh_from_db()
    assert account.check_password(STRONG_PASSWORD)


@pytest.mark.django_db
class TestProfilePasswordChangeConfirm:
    REQUEST_URL = "/api/profile/password-change/request/"
    CONFIRM_URL = "/api/profile/password-change/confirm/"

    @pytest.fixture(autouse=True)
    def empty_throttle_buckets(self):
        # Step 1 is login-throttled per IP and email; start from empty buckets.
        cache.clear()

    @staticmethod
    def _client_for(user) -> APIClient:
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    @pytest.fixture
    def account_client(self, account):
        return self._client_for(account)

    @pytest.fixture
    def other_user(self, db):
        return get_user_model().objects.create_user(
            email="other.person@example.com", password=ORIGINAL_PASSWORD
        )

    def _issue_ticket(self, client) -> str:
        response = client.post(
            self.REQUEST_URL, {"current_password": ORIGINAL_PASSWORD}, format="json"
        )
        assert response.status_code == 200
        return response.json()["ticket"]

    def test_rejects_password_like_email_and_keeps_ticket(
        self, account_client, account, live_credentials
    ):
        ticket = self._issue_ticket(account_client)

        response = account_client.post(
            self.CONFIRM_URL,
            {"ticket": ticket, "new_password": ACCOUNT_EMAIL},
            format="json",
        )

        _assert_rejected_for_similarity(response)
        _assert_account_untouched(account, live_credentials)

        retry = account_client.post(
            self.CONFIRM_URL,
            {"ticket": ticket, "new_password": STRONG_PASSWORD},
            format="json",
        )

        assert retry.status_code == 200
        account.refresh_from_db()
        assert account.check_password(STRONG_PASSWORD)

    def test_unknown_ticket_with_password_like_email_reports_the_password_first(
        self, account_client, account, live_credentials
    ):
        response = account_client.post(
            self.CONFIRM_URL,
            {"ticket": "no-such-ticket", "new_password": ACCOUNT_EMAIL},
            format="json",
        )

        _assert_rejected_for_similarity(response)
        _assert_account_untouched(account, live_credentials)

    def test_foreign_ticket_with_password_like_email_is_rejected_without_consuming_it(
        self, account_client, account, live_credentials, other_user
    ):
        other_client = self._client_for(other_user)
        foreign_ticket = self._issue_ticket(other_client)

        response = account_client.post(
            self.CONFIRM_URL,
            {"ticket": foreign_ticket, "new_password": ACCOUNT_EMAIL},
            format="json",
        )

        # The password is checked against the caller before the ticket is
        # touched, so the field error wins and the owner's ticket survives.
        _assert_rejected_for_similarity(response)
        _assert_account_untouched(account, live_credentials)
        owner_retry = other_client.post(
            self.CONFIRM_URL,
            {"ticket": foreign_ticket, "new_password": STRONG_PASSWORD},
            format="json",
        )
        assert owner_retry.status_code == 200
        other_user.refresh_from_db()
        assert other_user.check_password(STRONG_PASSWORD)


@pytest.mark.django_db
def test_cli_reset_rejects_password_like_email_with_clean_error(account, live_credentials):
    pending_token, _ = PasswordResetTokenRepository().create_for_user(account)

    with pytest.raises(CommandError) as error:
        call_command(
            "reset_password",
            ACCOUNT_EMAIL,
            "--password",
            ACCOUNT_EMAIL,
            stdout=io.StringIO(),
        )

    assert str(error.value) == f"Password validation failed:\n  new_password: {SIMILARITY_REASON}"
    _assert_account_untouched(account, live_credentials)
    assert PasswordResetToken.objects.filter(pk=pending_token.pk).exists()
