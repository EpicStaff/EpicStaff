"""The /run-python-code/ test-mode path resolves declared secrets itself: it
does not go through the session payload at all. The declaration is scanned out
of the code, so these tests declare by writing get_secret("NAME") into it."""

import pytest

from tables.models import PythonCode, PythonCodeResult, Secret
from rbac.models import Organization
from tables.services.run_python_code_service import RunPythonCodeService
from tables.services.secrets import (
    SecretResolutionError,
    UndeclaredSecretError,
    secret_service,
)

PLAINTEXT = "sk-runmode-abc123"


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org RunPythonCode")


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Org RunPythonCode Other")


def _submitted_bodies(sandbox_intake):
    """The bodies submitted to the sandbox intake, in call order."""
    return sandbox_intake.bodies


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        email="runmode@example.com", password="StrongPass123!"
    )


@pytest.mark.django_db
class TestRunPythonCodeResolvesDeclaredSecrets:
    def test_declared_secret_reaches_the_sandbox_message(
        self, org, user, sandbox_intake
    ):
        secret = secret_service.create(text=PLAINTEXT, org=org, name="RUNMODE_KEY")
        python_code = PythonCode.objects.create(
            code='def main(): return get_secret("RUNMODE_KEY")'
        )
        # The declaration is the M2M, not the literal in the code.
        python_code.secrets.set([secret])

        RunPythonCodeService().run_code(
            python_code_id=python_code.pk,
            varaibles={},
            organization_id=org.id,
            user=user,
        )

        bodies = _submitted_bodies(sandbox_intake)
        assert len(bodies) == 1
        assert bodies[0]["secrets"] == {"RUNMODE_KEY": PLAINTEXT}

    def test_no_declarations_sends_an_empty_dict(self, org, user, sandbox_intake):
        python_code = PythonCode.objects.create(code="def main(): return 1")

        RunPythonCodeService().run_code(
            python_code_id=python_code.pk,
            varaibles={},
            organization_id=org.id,
            user=user,
        )

        assert _submitted_bodies(sandbox_intake)[0]["secrets"] == {}

    def test_an_undeclared_name_is_rejected(self, org, user, sandbox_intake):
        """Test mode must agree with a real run about what this code may read, so an
        undeclared name fails here too — before any result row is written.

        This replaces an older test about naming another org's secret: that is no
        longer reachable, because the declaration is an org-scoped relation rather
        than a string the caller picks.
        """
        secret_service.create(text=PLAINTEXT, org=org, name="RUNMODE_KEY")
        python_code = PythonCode.objects.create(
            code='def main(): return get_secret("RUNMODE_KEY")'
        )
        # Deliberately no secrets.set(...) — the name is used but not declared.

        with pytest.raises(UndeclaredSecretError):
            RunPythonCodeService().run_code(
                python_code_id=python_code.pk,
                varaibles={},
                organization_id=org.id,
                user=user,
            )

        assert sandbox_intake.bodies == []
        assert not PythonCodeResult.objects.exists()

    def test_undecryptable_secret_fails_before_anything_is_written(
        self, org, user, sandbox_intake
    ):
        """A row that will not decrypt is an infrastructure fault, so it raises —
        and because resolution runs first, it leaves no PENDING result row and
        submits nothing."""
        secret = secret_service.create(text=PLAINTEXT, org=org, name="CORRUPT_KEY")
        Secret.objects.filter(pk=secret.pk).update(value="not-valid-fernet")
        python_code = PythonCode.objects.create(
            code='def main(): return get_secret("CORRUPT_KEY")'
        )
        # Must be declared so this reaches the decryption failure, which is the
        # point of the test, rather than tripping the declaration gate first.
        python_code.secrets.set([secret])

        with pytest.raises(SecretResolutionError):
            RunPythonCodeService().run_code(
                python_code_id=python_code.pk,
                varaibles={},
                organization_id=org.id,
                user=user,
            )

        assert sandbox_intake.bodies == []
        assert not PythonCodeResult.objects.exists()
