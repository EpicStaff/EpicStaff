"""Audit log lines for password sets, the delete-every-user reset and refused logins.

Each line names who acted and on which account, and never carries a password
or a reset token.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status

from rbac.identity.passwords.recovery import PasswordRecoveryService
from rbac.identity.passwords.token_repository import PasswordResetTokenRepository
from utils.logger import logger

NEW_PASSWORD = "BrandNewPass456!"


@pytest.fixture
def captured_log_messages():
    messages: list[str] = []
    sink_id = logger.add(messages.append, level="INFO", format="{message}")
    yield messages
    logger.remove(sink_id)


@pytest.fixture(autouse=True)
def clear_throttle_counters():
    cache.clear()
    yield
    cache.clear()


def _lines_with(messages: list[str], marker: str) -> list[str]:
    return [message for message in messages if marker in message]


@pytest.mark.django_db
def test_admin_reset_logs_actor_and_target(
    superadmin_client, superadmin_user, regular_user, captured_log_messages
):
    response = superadmin_client.post(
        reverse("admin_password_reset"),
        data={"user_id": regular_user.pk, "new_password": NEW_PASSWORD},
        format="json",
    )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    (line,) = _lines_with(captured_log_messages, "PasswordRecoveryService.admin_reset")
    assert f"actor={superadmin_user.email}" in line
    assert f"target={regular_user.email}" in line
    assert NEW_PASSWORD not in "".join(captured_log_messages)


@pytest.mark.django_db
def test_reset_link_confirm_logs_target_but_not_token(
    api_client, regular_user, captured_log_messages
):
    _row, raw_token = PasswordResetTokenRepository().create_for_user(regular_user)

    response = api_client.post(
        reverse("password_reset_confirm"),
        data={"token": raw_token, "new_password": NEW_PASSWORD},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    (line,) = _lines_with(captured_log_messages, "PasswordRecoveryService.confirm_reset")
    assert f"target={regular_user.email}" in line
    joined = "".join(captured_log_messages)
    assert raw_token not in joined
    assert NEW_PASSWORD not in joined


@pytest.mark.django_db
def test_cli_reset_logs_target(regular_user, captured_log_messages):
    PasswordRecoveryService().cli_reset(regular_user.email, NEW_PASSWORD)

    (line,) = _lines_with(captured_log_messages, "PasswordRecoveryService.cli_reset")
    assert "actor=cli" in line
    assert f"target={regular_user.email}" in line


@pytest.mark.django_db
def test_reset_user_logs_actor_deleted_count_and_new_superadmin(
    superadmin_client,
    superadmin_user,
    regular_user,
    default_org,
    captured_log_messages,
    django_capture_on_commit_callbacks,
):
    # The reset adopts the flagged default org instead of creating one.
    default_org.is_default = True
    default_org.save(update_fields=["is_default"])

    with django_capture_on_commit_callbacks(execute=True):
        response = superadmin_client.post(
            reverse("reset_user"),
            data={"email": "new-root@example.com", "password": NEW_PASSWORD},
            format="json",
        )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    (line,) = _lines_with(captured_log_messages, "ResetUserService.reset")
    assert f"actor={superadmin_user.email}" in line
    assert "users_deleted=2" in line
    assert "new_superadmin=new-root@example.com" in line
    assert get_user_model().objects.count() == 1


@pytest.mark.django_db
def test_failed_login_logs_account_and_address(api_client, regular_user, captured_log_messages):
    response = api_client.post(
        reverse("login"),
        data={"email": regular_user.email, "password": "wrong-password"},
        format="json",
        REMOTE_ADDR="203.0.113.7",
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    (line,) = _lines_with(captured_log_messages, "login_failed")
    assert f"account='{regular_user.email}'" in line
    assert "address='203.0.113.7'" in line
    assert "wrong-password" not in line


@pytest.mark.django_db
def test_failed_swagger_token_logs_account_and_address(
    api_client, regular_user, captured_log_messages
):
    response = api_client.post(
        reverse("swagger_token"),
        data={"username": regular_user.email, "password": "wrong-password"},
        format="json",
        REMOTE_ADDR="203.0.113.8",
    )

    # 403, not the 401 the view intends: a known separate defect (see
    # test_auth_throttles.py). Only the log line is under test here.
    assert response.status_code == status.HTTP_403_FORBIDDEN
    (line,) = _lines_with(captured_log_messages, "login_failed")
    assert f"account='{regular_user.email}'" in line
    assert "address='203.0.113.8'" in line


@pytest.mark.django_db
def test_failed_login_logs_an_oversized_account_cut_to_email_length(
    api_client, regular_user, captured_log_messages
):
    response = api_client.post(
        reverse("login"),
        data={"email": "a" * 10_000, "password": "wrong-password"},
        format="json",
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    (line,) = _lines_with(captured_log_messages, "login_failed")
    assert f"account='{'a' * 254}'" in line


@pytest.mark.django_db
def test_reset_user_logs_nothing_before_commit(
    superadmin_client, default_org, captured_log_messages, django_capture_on_commit_callbacks
):
    default_org.is_default = True
    default_org.save(update_fields=["is_default"])

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        superadmin_client.post(
            reverse("reset_user"),
            data={"email": "new-root@example.com", "password": NEW_PASSWORD},
            format="json",
        )

    assert len(callbacks) == 1
    assert _lines_with(captured_log_messages, "ResetUserService.reset") == []


@pytest.mark.django_db
def test_successful_login_logs_no_failure(api_client, regular_user, captured_log_messages):
    response = api_client.post(
        reverse("login"),
        data={"email": regular_user.email, "password": "UserStrongPass123!"},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _lines_with(captured_log_messages, "login_failed") == []
