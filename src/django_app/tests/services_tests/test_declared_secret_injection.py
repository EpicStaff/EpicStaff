"""The flip: injection is the declared set, not the scanned set.

Both tests here fail under the old code-derived behaviour, so they are the
regression guard for the change.
"""

import pytest

from tables.models import PythonCode
from tables.models.rbac_models import Organization
from tables.services.converter_service import ConverterService
from tables.services.secrets import secret_service


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org DeclaredInjection")


@pytest.mark.django_db
class TestInjectedSetIsTheDeclaration:
    def test_a_declared_but_unreferenced_secret_is_still_injected(self, org):
        """ "Chosen in the panel" means "available to this code". Under the old
        scanned-set behaviour this name would be absent."""
        secret = secret_service.create(text="sk-unused", org=org, name="UNUSED_KEY")
        python_code = PythonCode.objects.create(
            code="def main(**kwargs):\n    return 1\n", entrypoint="main"
        )
        python_code.secrets.set([secret])

        data = ConverterService().convert_python_code_to_pydantic(python_code)

        assert data.secret_names == ["UNUSED_KEY"]

    def test_a_name_only_in_code_is_not_injected(self, org):
        """The parser no longer decides anything. An undeclared name reaches the
        sandbox as nothing at all — and never gets this far in practice, because
        both enforcement points reject it first."""
        secret_service.create(text="sk-scan", org=org, name="SCANNED_KEY")
        python_code = PythonCode.objects.create(
            code='def main(**kwargs):\n    return get_secret("SCANNED_KEY")\n',
            entrypoint="main",
        )

        data = ConverterService().convert_python_code_to_pydantic(python_code)

        assert data.secret_names == []

    def test_a_computed_name_resolves_because_the_declaration_drives_injection(
        self, org
    ):
        """A dynamic name is invisible to any static parse, so this only works
        because injection is the declared set."""
        secret = secret_service.create(text="sk-dyn", org=org, name="KEY_PROD")
        python_code = PythonCode.objects.create(
            code=(
                "def main(**kwargs):\n"
                '    env = "PROD"\n'
                '    return get_secret(f"KEY_{env}")\n'
            ),
            entrypoint="main",
        )
        python_code.secrets.set([secret])

        data = ConverterService().convert_python_code_to_pydantic(python_code)

        assert data.secret_names == ["KEY_PROD"]
