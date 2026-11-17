"""A venv library name sent to the API is a package name with optional extras, or the
write is refused.

The sandbox writes every name as one line of the requirements `uv pip compile` reads
on stdin. A name carrying a line break, an option or a path would switch the package
index, read a file, or install a local project, so it is refused here with a 400 under
`libs` and never forwarded. The sandbox gateway is replaced: it is another service,
and what a refusal did not send to it is the point.
"""

from unittest.mock import patch

import pytest
from proxies.sandbox.models import SandboxVenvBinding
from rest_framework import status

from tables.models import PythonCode
from tables.services.secrets import secret_service

VENV_CLIENT = "proxies.sandbox.services.VenvService.client_class"

STORED_VENV = {"id": 4711, "name": "built", "libs": [], "status": "declared", "error": None}

# The sandbox's own table of refused names, from its domain tests of `Library`, copied
# whole: both sides hold a name to the same grammar, and a row one side accepts and the
# other refuses breaks here visibly.
INJECTED_NAMES = [
    pytest.param("six\n-i http://internal-host:9/simple", id="newline-index-option"),
    pytest.param("six\n-r /etc/passwd", id="newline-requirements-file"),
    pytest.param("requests\n--index-url https://evil.example/simple", id="newline-long-option"),
    pytest.param("requests\n", id="trailing-newline"),
    pytest.param("requests\r-e /etc", id="carriage-return-editable"),
    pytest.param("-e /etc", id="editable-option"),
    pytest.param("-r", id="bare-option"),
    pytest.param("/etc", id="absolute-path"),
    pytest.param("./local/path", id="relative-path"),
    pytest.param("foo @ file:///etc", id="direct-reference"),
    pytest.param("git+https://example.com/repo.git", id="vcs-url"),
    pytest.param("requests>=2", id="specifier-in-name"),
    pytest.param("requests; python_version<'3'", id="marker"),
    pytest.param("requests ", id="trailing-space"),
    pytest.param("-requests", id="leading-hyphen"),
    pytest.param("requests-", id="trailing-hyphen"),
    pytest.param("requests[socks]\n-i x", id="extras-then-newline-option"),
    pytest.param("requests[socks]\n", id="extras-then-trailing-newline"),
    pytest.param("requests[ socks]", id="space-inside-extras"),
    pytest.param("requests[socks];python_version<'3'", id="extras-then-marker"),
    pytest.param("requests[socks]>=2", id="extras-then-specifier"),
    pytest.param("requests[]", id="empty-extras"),
    pytest.param("requests[socks,]", id="trailing-comma-in-extras"),
    pytest.param("requests[socks", id="unclosed-extras"),
    pytest.param("requests[-e]", id="option-as-extra"),
    pytest.param("[socks]", id="extras-without-a-name"),
]


def assert_refused_under_libs(response):
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    message = response.json()["message"]
    assert message.startswith("libs: ") and "is not a package name" in message, message


@pytest.fixture
def venv_sandbox():
    with patch(VENV_CLIENT) as client_class:
        client = client_class.return_value.__enter__.return_value
        client.create.return_value = dict(STORED_VENV)
        client.update.return_value = dict(STORED_VENV)
        yield client


@pytest.fixture
def binding(default_org):
    return SandboxVenvBinding.objects.create(org_id=default_org.id, resource_id="4711")


@pytest.mark.django_db
@pytest.mark.parametrize("name", INJECTED_NAMES)
def test_create_refuses_a_library_name_that_is_not_a_package_name(auth_client, venv_sandbox, name):
    response = auth_client.post(
        "/api/venvs/",
        {"name": "built", "libs": [{"name": "pandas"}, {"name": name}]},
        format="json",
    )

    assert_refused_under_libs(response)
    assert venv_sandbox.method_calls == []
    assert not SandboxVenvBinding.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("name", INJECTED_NAMES)
def test_update_refuses_a_library_name_that_is_not_a_package_name(
    auth_client, binding, venv_sandbox, name
):
    response = auth_client.patch(
        f"/api/venvs/{binding.pk}/", {"libs": [{"name": name}]}, format="json"
    )

    assert_refused_under_libs(response)
    assert venv_sandbox.update.call_count == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    "name",
    [
        "requests",
        "Requests_Toolbelt",
        "zope.interface",
        "requests[socks]",
        "requests[socks,security]",
    ],
)
def test_create_forwards_a_package_name_with_its_specification_as_sent(
    auth_client, venv_sandbox, name
):
    payload = {"name": "built", "libs": [{"name": name, "specification": ">=1.0, <2"}]}

    response = auth_client.post("/api/venvs/", payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    assert venv_sandbox.create.call_args.args[0] == payload


@pytest.mark.django_db
def test_update_forwards_a_package_name_as_sent(auth_client, binding, venv_sandbox):
    payload = {"libs": [{"name": "numpy", "specification": "==1.26.4"}]}

    response = auth_client.patch(f"/api/venvs/{binding.pk}/", payload, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert venv_sandbox.update.call_args.args == ("4711", payload)


@pytest.mark.django_db
def test_update_without_libraries_checks_no_names(auth_client, binding, venv_sandbox):
    response = auth_client.patch(f"/api/venvs/{binding.pk}/", {"name": "renamed"}, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert venv_sandbox.update.call_args.args == ("4711", {"name": "renamed"})


@pytest.mark.django_db
def test_update_refuses_a_bad_name_before_asking_the_sandbox_anything(
    auth_client, default_org, binding, venv_sandbox
):
    """Code declaring a secret runs in this venv, so a change of its libraries would be
    compared with the ones the sandbox holds. A body refused anyway must not cost that
    upstream read."""
    secret = secret_service.create(text="sk-names", org=default_org, name="NAMES_KEY")
    code = PythonCode.objects.create(code="def main():\n    return 1\n", venv=binding)
    code.secrets.set([secret])

    response = auth_client.patch(
        f"/api/venvs/{binding.pk}/", {"libs": [{"name": "six\n-r /etc/passwd"}]}, format="json"
    )

    assert_refused_under_libs(response)
    assert venv_sandbox.method_calls == []
