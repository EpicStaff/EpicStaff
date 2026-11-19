"""A finished test run stores the failure text the user should see as its stderr.

The code's own failure is its stderr. A failure of the sandbox itself arrives as the
result's `error` `{code, detail}`; its `detail` is shown on the line after whatever the
code wrote to stderr. An `error` that isn't a valid `{code, detail}` is never stored: the generic
server-error text stands in for it.
"""

import pytest
from rbac.models import Organization
from src.shared.models import CodeResultData
from tables.models import PythonCode, PythonCodeResult
from tables.services.run_python_code_service import RunPythonCodeService


@pytest.fixture
def pending_run(db, django_user_model):
    org = Organization.objects.create(name="Org ShownStderr")
    user = django_user_model.objects.create_user(
        email="shown-stderr@example.com", password="StrongPass123!"
    )
    python_code = PythonCode.objects.create(
        code="def main(**kw): return kw", entrypoint="main", global_kwargs={}
    )
    yield PythonCodeResult.objects.create(
        execution_id="exec-1",
        org_id=org.id,
        created_by=user,
        python_code=python_code,
        status=PythonCodeResult.Status.PENDING,
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("stderr", "error", "expected_stderr"),
    [
        pytest.param(
            "NameError: name 'x' is not defined",
            None,
            "NameError: name 'x' is not defined",
            id="code-failed",
        ),
        pytest.param(
            "",
            {"code": "venv_failed", "detail": "Couldn't install the libraries."},
            "Couldn't install the libraries.",
            id="sandbox-failed",
        ),
        pytest.param(
            "child wrote this",
            {"code": "result_too_large", "detail": "The function's return value is too big to save."},
            "child wrote this\nThe function's return value is too big to save.",
            id="code-wrote-then-sandbox-failed",
        ),
        pytest.param(
            "",
            {"code": "venv_failed", "reason": "/opt/sandbox/uv.log line 3"},
            "The code couldn't run because of a server error.",
            id="malformed-error",
        ),
    ],
)
def test_a_failed_run_stores_the_text_meant_for_the_user(
    pending_run, stderr, error, expected_stderr
):
    saved = RunPythonCodeService().save_execution_result(
        CodeResultData(
            execution_id="exec-1", stderr=stderr, stdout="", returncode=1, error=error
        )
    )

    pending_run.refresh_from_db()
    assert saved is True
    assert pending_run.status == PythonCodeResult.Status.ERROR
    assert pending_run.stderr == expected_stderr
