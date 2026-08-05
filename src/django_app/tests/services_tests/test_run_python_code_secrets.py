"""The /run-python-code/ test-mode path resolves declared secrets itself: it
does not go through the session payload at all. The declaration is scanned out
of the code, so these tests declare by writing get_secret("NAME") into it."""

import json

import pytest

from tables.models import PythonCode, PythonCodeResult, Secret
from tables.models.rbac_models import Organization
from tables.services.redis_service import RedisService
from tables.services.run_python_code_service import RunPythonCodeService
from tables.services.secrets import SecretResolutionError, secret_service

PLAINTEXT = "sk-runmode-abc123"


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org RunPythonCode")


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Org RunPythonCode Other")


def _published_messages(redis_client_mock):
    """The JSON bodies passed to publish(), in call order."""
    return [
        json.loads(call.args[1] if len(call.args) > 1 else call.kwargs["message"])
        for call in redis_client_mock.publish.call_args_list
    ]


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        email="runmode@example.com", password="StrongPass123!"
    )


@pytest.mark.django_db
class TestRunPythonCodeResolvesDeclaredSecrets:
    def test_declared_secret_reaches_the_sandbox_message(
        self, org, user, redis_client_mock
    ):
        secret_service.create(text=PLAINTEXT, org=org, name="RUNMODE_KEY")
        # The declaration is the code: no picker, no request field, no M2M.
        python_code = PythonCode.objects.create(
            code='def main(): return get_secret("RUNMODE_KEY")'
        )

        RunPythonCodeService(redis_service=RedisService()).run_code(
            python_code_id=python_code.pk,
            varaibles={},
            organization_id=org.id,
            user=user,
        )

        messages = _published_messages(redis_client_mock)
        assert len(messages) == 1
        assert messages[0]["secrets"] == {"RUNMODE_KEY": PLAINTEXT}

    def test_no_declarations_sends_an_empty_dict(self, org, user, redis_client_mock):
        python_code = PythonCode.objects.create(code="def main(): return 1")

        RunPythonCodeService(redis_service=RedisService()).run_code(
            python_code_id=python_code.pk,
            varaibles={},
            organization_id=org.id,
            user=user,
        )

        assert _published_messages(redis_client_mock)[0]["secrets"] == {}

    def test_another_orgs_secret_name_resolves_to_nothing(
        self, org, other_org, user, redis_client_mock
    ):
        """Naming another org's secret is trivially easy — it is just a string in
        the code — so resolution is the boundary. The name is scoped to the
        caller's org, so it simply finds nothing and the sandbox raises
        SecretNotAvailableError at the call."""
        secret_service.create(
            text="sk-foreign-runmode", org=other_org, name="FOREIGN_RUNMODE"
        )
        python_code = PythonCode.objects.create(
            code='def main(): return get_secret("FOREIGN_RUNMODE")'
        )

        RunPythonCodeService(redis_service=RedisService()).run_code(
            python_code_id=python_code.pk,
            varaibles={},
            organization_id=org.id,
            user=user,
        )

        published = _published_messages(redis_client_mock)
        assert published[0]["secrets"] == {}
        assert "sk-foreign-runmode" not in json.dumps(published[0])

    def test_undecryptable_secret_fails_before_anything_is_written(
        self, org, user, redis_client_mock
    ):
        """A row that will not decrypt is an infrastructure fault, so it raises —
        and because resolution runs first, it leaves no PENDING result row and
        publishes nothing."""
        secret = secret_service.create(text=PLAINTEXT, org=org, name="CORRUPT_KEY")
        Secret.objects.filter(pk=secret.pk).update(value="not-valid-fernet")
        python_code = PythonCode.objects.create(
            code='def main(): return get_secret("CORRUPT_KEY")'
        )

        with pytest.raises(SecretResolutionError):
            RunPythonCodeService(redis_service=RedisService()).run_code(
                python_code_id=python_code.pk,
                varaibles={},
                organization_id=org.id,
                user=user,
            )

        assert not redis_client_mock.publish.call_args_list
        assert not PythonCodeResult.objects.exists()
